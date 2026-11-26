PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE projects (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    brief_uri TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running', 'waiting_approval', 'pending_recovery',
        'needs_human_review', 'completed', 'failed', 'cancelled'
    )),
    stage TEXT,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    budget_json TEXT NOT NULL CHECK (json_valid(budget_json)),
    worker_lease TEXT,
    lease_expires_at TEXT,
    checkpoint_json TEXT CHECK (json_valid(checkpoint_json) OR checkpoint_json IS NULL),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    ended_at TEXT,
    UNIQUE (project_id, idempotency_key)
);
CREATE UNIQUE INDEX one_running_worker ON runs(status) WHERE status = 'running';
CREATE INDEX runs_queue ON runs(status, created_at, id);

CREATE TABLE artifacts (
    id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    type TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (typeof(version) = 'integer' AND version >= 1),
    schema_version TEXT NOT NULL,
    uri TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^a-f0-9]*'),
    created_by TEXT NOT NULL,
    parent_refs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(parent_refs_json)),
    UNIQUE (run_id, type, version),
    PRIMARY KEY (run_id, id),
    UNIQUE (run_id, id, version, sha256)
);
CREATE TRIGGER artifacts_no_replace BEFORE INSERT ON artifacts
WHEN EXISTS (
    SELECT 1 FROM artifacts WHERE run_id = NEW.run_id
      AND (id = NEW.id OR (type = NEW.type AND version = NEW.version))
)
BEGIN
    SELECT RAISE(ABORT, 'artifact version already exists');
END;
CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts BEGIN
    SELECT RAISE(ABORT, 'artifact version is immutable');
END;
CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts BEGIN
    SELECT RAISE(ABORT, 'artifact version is immutable');
END;

CREATE TABLE tasks (
    id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    plan_artifact_id TEXT NOT NULL,
    requirement_refs_json TEXT NOT NULL CHECK (json_valid(requirement_refs_json)),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (
        status IN ('todo', 'ready', 'in_progress', 'waiting_test', 'rework', 'done', 'blocked')
    ),
    repair_round INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(repair_round) = 'integer' AND repair_round BETWEEN 0 AND 3),
    done_conditions_json TEXT NOT NULL CHECK (json_valid(done_conditions_json)),
    PRIMARY KEY (run_id, id),
    FOREIGN KEY (run_id, plan_artifact_id) REFERENCES artifacts(run_id, id)
);

CREATE TABLE task_dependencies (
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    PRIMARY KEY (run_id, task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id),
    FOREIGN KEY (run_id, task_id) REFERENCES tasks(run_id, id),
    FOREIGN KEY (run_id, depends_on_task_id) REFERENCES tasks(run_id, id)
);

CREATE TABLE agent_steps (
    id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    agent_role TEXT NOT NULL CHECK (agent_role IN (
        'orchestrator', 'requirement', 'architecture', 'planning', 'dev', 'tester'
    )),
    task_id TEXT,
    attempt INTEGER NOT NULL CHECK (typeof(attempt) = 'integer' AND attempt >= 1),
    status TEXT NOT NULL,
    input_refs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(input_refs_json)),
    output_refs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(output_refs_json)),
    usage_json TEXT CHECK (json_valid(usage_json) OR usage_json IS NULL),
    PRIMARY KEY (run_id, id),
    FOREIGN KEY (run_id, task_id) REFERENCES tasks(run_id, id)
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    request_redacted_json TEXT NOT NULL CHECK (json_valid(request_redacted_json)),
    result_uri TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER CHECK (duration_ms IS NULL OR (typeof(duration_ms) = 'integer' AND duration_ms >= 0)),
    UNIQUE (run_id, operation_id),
    FOREIGN KEY (run_id, step_id) REFERENCES agent_steps(run_id, id)
);

CREATE TABLE approvals (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (length(trim(decision)) > 0),
    comment TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id, artifact_id, artifact_version, artifact_sha256)
        REFERENCES artifacts(run_id, id, version, sha256)
);

CREATE TABLE test_reports (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT,
    commit_hash TEXT NOT NULL,
    suite_id TEXT NOT NULL,
    report_uri TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    passed INTEGER NOT NULL CHECK (typeof(passed) = 'integer' AND passed >= 0),
    failed INTEGER NOT NULL CHECK (typeof(failed) = 'integer' AND failed >= 0),
    skipped INTEGER NOT NULL CHECK (typeof(skipped) = 'integer' AND skipped >= 0),
    errors INTEGER NOT NULL CHECK (typeof(errors) = 'integer' AND errors >= 0),
    duration_ms INTEGER NOT NULL CHECK (typeof(duration_ms) = 'integer' AND duration_ms >= 0),
    FOREIGN KEY (run_id, task_id) REFERENCES tasks(run_id, id)
);

CREATE TABLE trace_links (
    id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    evidence_uri TEXT NOT NULL
);
CREATE INDEX trace_source ON trace_links(run_id, source_type, source_id);
CREATE INDEX trace_target ON trace_links(run_id, target_type, target_id);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    step_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id, step_id) REFERENCES agent_steps(run_id, id)
);
CREATE INDEX events_by_run ON events(run_id, id);

PRAGMA user_version = 1;
COMMIT;
