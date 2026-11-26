"""Transactional SQLite metadata used by the API and the trusted worker."""

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4


SCHEMA = Path(__file__).with_name("migrations") / "001_platform.sql"
TABLES_BY_RUN = frozenset({
    "agent_steps", "artifacts", "tasks", "task_dependencies", "tool_calls",
    "approvals", "test_reports", "trace_links", "events",
})


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def new_id():
    return uuid4().hex


class StorageConflict(ValueError):
    """A version, lease, or idempotency precondition changed."""


class Database:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def migrate(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 1:
                names = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                if not (TABLES_BY_RUN | {"projects", "runs"}).issubset(names):
                    raise StorageConflict("Platform schema v1 is incomplete")
                return
            nonempty = db.execute(
                "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
            if version != 0 or nonempty:
                raise StorageConflict(f"Unrecognized platform database at version {version}")
            # BEGIN IMMEDIATE above serializes version detection and all DDL, including triggers.
            statement = ""
            for line in SCHEMA.read_text(encoding="utf-8").splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    sql = statement.strip()
                    if sql not in {"PRAGMA foreign_keys = ON;", "BEGIN IMMEDIATE;", "COMMIT;"}:
                        db.execute(sql)
                    statement = ""
            if statement.strip() or db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise StorageConflict("Incomplete platform migration")

    @contextmanager
    def transaction(self, *, write=False):
        with closing(self._connect()) as db, db:
            if not write:
                db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield Repository(db)


class Repository:
    def __init__(self, db):
        self._db = db

    def create_project(self, name, brief_uri):
        if not name.strip() or not brief_uri.strip():
            raise ValueError("Project name and brief URI are required")
        project_id = new_id()
        self._db.execute(
            "INSERT INTO projects(id,name,brief_uri) VALUES (?,?,?)", (project_id, name, brief_uri)
        )
        return project_id

    def get_project(self, project_id):
        row = self._db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown project")
        return dict(row)

    def rename_project(self, project_id, name):
        if not name.strip():
            raise ValueError("Project name is required")
        if not self._db.execute("UPDATE projects SET name=? WHERE id=?", (name, project_id)).rowcount:
            raise KeyError("Unknown project")

    def delete_empty_project(self, project_id):
        # Run history has a deliberately restrictive foreign key to projects.
        if not self._db.execute("DELETE FROM projects WHERE id=?", (project_id,)).rowcount:
            raise KeyError("Unknown project")

    def create_run(self, project_id, idempotency_key, config, budget):
        if not idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        previous = self._db.execute(
            "SELECT id,config_json,budget_json FROM runs WHERE project_id=? AND idempotency_key=?",
            (project_id, idempotency_key),
        ).fetchone()
        if previous is not None:
            if json.loads(previous["config_json"]) != config or json.loads(previous["budget_json"]) != budget:
                raise StorageConflict("Idempotency key already belongs to different run inputs")
            return previous["id"]
        run_id = new_id()
        self._db.execute(
            "INSERT INTO runs(id,project_id,idempotency_key,config_json,budget_json) VALUES (?,?,?,?,?)",
            (run_id, project_id, idempotency_key, encode(config), encode(budget)),
        )
        return run_id

    def get_run(self, project_id, run_id):
        row = self._db.execute(
            "SELECT * FROM runs WHERE project_id=? AND id=?", (project_id, run_id)
        ).fetchone()
        if row is None:
            raise KeyError("Unknown run for project")
        return dict(row)

    def for_run(self, project_id, run_id):
        self.get_run(project_id, run_id)
        return RunReader(self._db, run_id)

    def worker_run(self, project_id, run_id, lease):
        self.get_run(project_id, run_id)
        valid = self._db.execute(
            "SELECT 1 FROM runs WHERE id=? AND status='running' AND worker_lease=? "
            "AND julianday(lease_expires_at)>julianday('now')", (run_id, lease),
        ).fetchone()
        if valid is None:
            raise StorageConflict("Missing, expired or superseded worker lease")
        return WorkerRepository(self._db, run_id)

    def record_approval(self, project_id, run_id, artifact_id, version, digest, decision, comment=""):
        self.get_run(project_id, run_id)
        if decision not in {"approve", "request_changes"} or (decision == "request_changes" and not comment.strip()):
            raise ValueError("Invalid owner decision or missing revision comment")
        current = self._db.execute(
            "SELECT a.id FROM artifacts a WHERE a.run_id=? AND a.id=? AND a.version=? AND a.sha256=? "
            "AND NOT EXISTS (SELECT 1 FROM artifacts newer WHERE newer.run_id=a.run_id "
            "AND newer.type=a.type AND newer.version>a.version)",
            (run_id, artifact_id, version, digest),
        ).fetchone()
        if current is None:
            raise StorageConflict("Artifact is missing, stale, or its hash differs")
        approval_id = new_id()
        self._db.execute(
            "INSERT INTO approvals(id,run_id,artifact_id,artifact_version,artifact_sha256,decision,comment) "
            "VALUES (?,?,?,?,?,?,?)", (approval_id, run_id, artifact_id, version, digest, decision, comment),
        )
        return approval_id


class RunReader:
    def __init__(self, db, run_id):
        self._db = db
        self.run_id = run_id

    def records(self, table):
        if table not in TABLES_BY_RUN:
            raise ValueError("Unknown collection of run records")
        rows = self._db.execute(f"SELECT * FROM {table} WHERE run_id=?", (self.run_id,))
        return [dict(row) for row in rows]

    def events_after(self, cursor=0, limit=100):
        if cursor < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid event cursor or page size")
        rows = self._db.execute(
            "SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT ?", (self.run_id, cursor, limit)
        )
        return [dict(row) for row in rows]

    def artifact(self, artifact_id, version):
        row = self._db.execute(
            "SELECT * FROM artifacts WHERE run_id=? AND id=? AND version=?",
            (self.run_id, artifact_id, version),
        ).fetchone()
        if row is None:
            raise KeyError("Unknown artifact version for run")
        return dict(row)

    def latest_version(self, kind):
        return self._db.execute(
            "SELECT COALESCE(MAX(version),0) FROM artifacts WHERE run_id=? AND type=?",
            (self.run_id, kind),
        ).fetchone()[0]


class WorkerRepository(RunReader):
    """Only created by worker_run after checking host ownership inside the transaction."""

    def _insert(self, table, **fields):
        # Tables and field names come only from the fixed methods below.
        fields["run_id"] = self.run_id
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        self._db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(fields.values()))

    def add_artifact(self, artifact_id, kind, version, schema_version, uri, sha256, created_by, parents=()):
        self._insert("artifacts", id=artifact_id, type=kind, version=version, schema_version=schema_version,
                     uri=uri, sha256=sha256, created_by=created_by, parent_refs_json=encode(parents))

    def add_task(self, task_id, plan_id, description, requirement_refs, done_conditions):
        plan = self._db.execute(
            "SELECT 1 FROM artifacts WHERE run_id=? AND id=? AND type='plan'", (self.run_id, plan_id)
        ).fetchone()
        if plan is None:
            raise ValueError("Task requires a plan artifact in the current run")
        self._insert("tasks", id=task_id, plan_artifact_id=plan_id, description=description,
                     requirement_refs_json=encode(requirement_refs), done_conditions_json=encode(done_conditions))

    def add_dependency(self, task_id, prerequisite):
        self._insert("task_dependencies", task_id=task_id, depends_on_task_id=prerequisite)

    def update_task(self, task_id, expected_status, status, repair_round):
        changed = self._db.execute(
            "UPDATE tasks SET status=?,repair_round=? WHERE run_id=? AND id=? AND status=?",
            (status, repair_round, self.run_id, task_id, expected_status),
        ).rowcount
        if not changed:
            raise StorageConflict("Unknown task or outdated status")

    def start_step(self, step_id, role, attempt, inputs, task_id=None):
        self._insert("agent_steps", id=step_id, agent_role=role.lower(), task_id=task_id,
                     attempt=attempt, status="started", input_refs_json=encode(inputs))

    def finish_step(self, step_id, status, outputs, usage=None):
        changed = self._db.execute(
            "UPDATE agent_steps SET status=?,output_refs_json=?,usage_json=? "
            "WHERE run_id=? AND id=? AND status='started'",
            (status, encode(outputs), encode(usage) if usage is not None else None, self.run_id, step_id),
        ).rowcount
        if not changed:
            raise StorageConflict("Unknown step or step already finished")

    def add_tool_call(self, step_id, operation_id, name, redacted_request):
        self._insert("tool_calls", id=new_id(), step_id=step_id, operation_id=operation_id,
                     tool_name=name, request_redacted_json=encode(redacted_request), status="started")

    def finish_tool_call(self, operation_id, status, result_uri, duration_ms):
        changed = self._db.execute(
            "UPDATE tool_calls SET status=?, result_uri=?, duration_ms=? "
            "WHERE run_id=? AND operation_id=? AND status='started'",
            (status, result_uri, duration_ms, self.run_id, operation_id),
        ).rowcount
        if not changed:
            raise StorageConflict("Unknown operation or operation already finished")

    def add_event(self, event_type, payload, step_id=None):
        self._insert("events", event_type=event_type, payload_json=encode(payload), step_id=step_id)

    def add_report(self, task_id, commit_hash, suite_id, uri, exit_code, passed, failed, skipped, errors, duration_ms):
        report_id = new_id()
        self._insert("test_reports", id=report_id, task_id=task_id, commit_hash=commit_hash, suite_id=suite_id,
                     report_uri=uri, exit_code=exit_code, passed=passed, failed=failed,
                     skipped=skipped, errors=errors, duration_ms=duration_ms)
        return report_id

    def add_trace(self, source_type, source_id, target_type, target_id, evidence_uri):
        collections = {"task": "tasks", "test": "test_reports", "report": "test_reports",
                       "step": "agent_steps", "artifact": "artifacts", "patch": "artifacts"}
        for kind, key in ((source_type, source_id), (target_type, target_id)):
            table = collections.get(kind)
            if table and not self._db.execute(
                f"SELECT 1 FROM {table} WHERE run_id=? AND id=?", (self.run_id, key)
            ).fetchone():
                raise ValueError(f"Unknown {kind} in current run")
        self._insert("trace_links", id=new_id(), source_type=source_type, source_id=source_id,
                     target_type=target_type, target_id=target_id, evidence_uri=evidence_uri)
