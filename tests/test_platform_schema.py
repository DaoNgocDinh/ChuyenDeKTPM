import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1] / "backend" / "migrations" / "001_platform.sql"
).read_text(encoding="utf-8")
PLAN_HASH = "a" * 64


class PlatformSchemaTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript(MIGRATION)
        self.db.execute("INSERT INTO projects(id,name,brief_uri) VALUES ('P','A1','brief')")
        for run in ("R1", "R2"):
            self.db.execute(
                "INSERT INTO runs(id, project_id, idempotency_key, config_json, budget_json) "
                "VALUES (?, 'P', ?, '{}', '{}')",
                (run, run),
            )
            self.db.execute(
                "INSERT INTO artifacts(id,run_id,type,version,schema_version,uri,sha256,created_by) "
                "VALUES ('P1', ?, 'plan', 1, '1', 'artifacts/P1', ?, 'planning')",
                (run, PLAN_HASH),
            )
        for run, task in (("R1", "T1"), ("R1", "T2"), ("R2", "T1"), ("R2", "T3")):
            self.db.execute(
                "INSERT INTO tasks(id,run_id,plan_artifact_id,description,"
                "requirement_refs_json,done_conditions_json) VALUES (?, ?, 'P1', 'CRUD', '[]', '[]')",
                (task, run),
            )

    def test_version_and_tables(self):
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone(), (1,))
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone(), (1,))
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        names = {name for (name,) in self.db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertEqual(names, {
            "projects", "runs", "agent_steps", "artifacts", "tasks", "task_dependencies",
            "tool_calls", "approvals", "test_reports", "trace_links", "events",
        })

    def test_project_idempotency_and_single_running_job(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO runs(id,project_id,idempotency_key,config_json,budget_json) "
                "VALUES ('R3','P','R1','{}','{}')"
            )
        self.db.execute("UPDATE runs SET status='running' WHERE id='R1'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE runs SET status='running' WHERE id='R2'")
        self.assertEqual(self.db.execute("SELECT status FROM runs WHERE id='R2'").fetchone(), ("queued",))

    def test_artifacts_are_immutable_including_replace(self):
        insert = (
            "INTO artifacts(id,run_id,type,version,schema_version,uri,sha256,created_by) "
            "VALUES ('NEW','R1','plan',1,'1','new',?,'planning')"
        )
        for command in ("INSERT ", "INSERT OR REPLACE "):
            with self.subTest(command=command), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(command + insert, ("b" * 64,))
        for mutation in ("UPDATE artifacts SET uri='altered'", "DELETE FROM artifacts"):
            with self.subTest(mutation=mutation), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(mutation + " WHERE run_id='R1'")
        actual = self.db.execute("SELECT id,sha256 FROM artifacts WHERE run_id='R1'").fetchone()
        self.assertEqual(actual, ("P1", PLAN_HASH))

    def test_approval_binds_run_id_version_and_hash(self):
        sql = (
            "INSERT INTO approvals(id,run_id,artifact_id,artifact_version,artifact_sha256,decision) "
            "VALUES (?, ?, ?, ?, ?, 'approve')"
        )
        self.db.execute(sql, ("YES", "R1", "P1", 1, PLAN_HASH))
        for values in [
            ("R1", "P1", 2, PLAN_HASH), ("R1", "P1", 1, "b" * 64),
            ("R1", "unknown", 1, PLAN_HASH), ("unknown", "P1", 1, PLAN_HASH),
        ]:
            with self.subTest(values=values), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, ("NO", *values))

    def test_tasks_and_dependencies_remain_inside_run(self):
        sql = "INSERT INTO task_dependencies(run_id,task_id,depends_on_task_id) VALUES (?,?,?)"
        self.db.execute(sql, ("R1", "T2", "T1"))
        for pair in (("T1","T1"), ("T3","T1"), ("T1","T3"), ("T2","T1")):
            with self.subTest(pair=pair), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, ("R1", *pair))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE tasks SET repair_round=4 WHERE run_id='R1' AND id='T1'")

    def test_tool_operations_and_events_require_step_in_same_run(self):
        self.db.execute(
            "INSERT INTO agent_steps(id,run_id,agent_role,task_id,attempt,status) "
            "VALUES ('S1','R1','dev','T1',1,'started')"
        )
        sql = (
            "INSERT INTO tool_calls(id,run_id,step_id,operation_id,tool_name,request_redacted_json,status) "
            "VALUES (?, ?, 'S1', 'OP', 'workspace.read_file', '{}', 'started')"
        )
        self.db.execute(sql, ("CALL1", "R1"))
        for call in (("CROSS", "R2"), ("REPLAY", "R1")):
            with self.subTest(call=call), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, call)
        event = "INSERT INTO events(run_id,step_id,event_type,payload_json) VALUES (?, 'S1','tool','{}')"
        self.db.execute(event, ("R1",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(event, ("R2",))

    def test_runner_report_requires_realistic_counts_and_local_task(self):
        sql = (
            "INSERT INTO test_reports(id,run_id,task_id,commit_hash,suite_id,report_uri,"
            "exit_code,passed,failed,skipped,errors,duration_ms) "
            "VALUES (?, 'R1', ?, 'fixture-commit', 'unit', 'logs/result', 0, ?, 0, 0, 0, 7)"
        )
        self.db.execute(sql, ("REPORT1","T1",2))
        for task, passed in (("T3",1), ("T1",-1), ("T1",1.5)):
            with self.subTest(task=task, passed=passed), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, ("INVALID",task,passed))

    def test_migration_survives_reopen_and_failed_ddl_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "platform.db"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(MIGRATION)
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA foreign_keys=ON")
                self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (1,))
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO events(run_id,event_type,payload_json) VALUES ('?','x','{}')")
        with closing(sqlite3.connect(":memory:")) as broken:
            broken.execute("CREATE TABLE tasks(legacy TEXT)")
            with self.assertRaises(sqlite3.OperationalError):
                broken.executescript(MIGRATION)
            broken.rollback()
            self.assertEqual(broken.execute("PRAGMA user_version").fetchone(), (0,))
            names = broken.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall()
            self.assertEqual(names, [("tasks",)])
