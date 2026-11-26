import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from backend.storage import Database, StorageConflict


DIGEST = "a" * 64


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "store" / "metadata.sqlite"
        self.db = Database(self.path)
        self.db.migrate()
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1", "brief/A1")
            self.other_project = repo.create_project("A2", "brief/A2")
            self.run = repo.create_run(self.project, "key", {"model": "fixture"}, {"tokens": 500})
        # A test-controlled assignment until the queue hands out production leases in I05.
        with closing(sqlite3.connect(self.path)) as seed, seed:
            seed.execute("UPDATE runs SET status='running',worker_lease='lease',"
                         "lease_expires_at=datetime('now','+5 minutes') WHERE id=?", (self.run,))

    def test_metadata_survives_new_process_connection(self):
        with self.db.transaction(write=True) as repo:
            work = repo.worker_run(self.project, self.run, "lease")
            work.add_artifact("P1", "plan", 1, "1", "artifacts/P1", DIGEST, "Planning")
            for task in ("T1", "T2"):
                work.add_task(task, "P1", task, ["FR1"], ["test passes"])
            work.add_dependency("T2", "T1")
            work.update_task("T1", "todo", "ready", 0)
            work.start_step("S1", "Tester", 1, [], "T1")
            work.add_tool_call("S1", "op", "tests.run_suite", {"suite": "unit"})
            work.finish_tool_call("op", "succeeded", "runs/test-output", 4)
            report = work.add_report("T1", "fixture-commit", "unit", "logs/test", 0, 2, 0, 0, 0, 4)
            work.add_trace("task", "T1", "test", report, "logs/test")
            work.add_event("tested", {"pass": 2}, "S1")
            work.add_event("finished", {"report": report}, "S1")
            work.finish_step("S1", "finished", [report], usage=None)
            repo.record_approval(self.project, self.run, "P1", 1, DIGEST, "approve")
        reopened = Database(self.path)
        reopened.migrate()
        with reopened.transaction() as repo:
            self.assertEqual(repo.get_project(self.project)["name"], "A1")
            self.assertEqual(repo.get_run(self.project, self.run)["project_id"], self.project)
            view = repo.for_run(self.project, self.run)
            self.assertEqual(view.records("agent_steps")[0]["status"], "finished")
            self.assertIsNone(view.records("agent_steps")[0]["usage_json"])
            self.assertEqual(view.records("test_reports")[0]["passed"], 2)
            self.assertEqual(view.records("tool_calls")[0]["operation_id"], "op")
            self.assertEqual(view.records("trace_links")[0]["target_id"], report)
            self.assertEqual(view.records("approvals")[0]["artifact_sha256"], DIGEST)
            self.assertEqual(view.records("task_dependencies")[0]["depends_on_task_id"], "T1")
            first = view.events_after(limit=1)[0]
            self.assertEqual(json.loads(first["payload_json"]), {"pass": 2})
            self.assertEqual([e["event_type"] for e in view.events_after(first["id"])], ["finished"])
        read_after_restart = (
            "import sys; from backend.storage import Database\n"
            "with Database(sys.argv[1]).transaction() as repo:\n"
            " view = repo.for_run(sys.argv[2], sys.argv[3])\n"
            " print(repo.get_project(sys.argv[2])['name'], "
            "repo.get_run(sys.argv[2], sys.argv[3])['status'], "
            "view.records('agent_steps')[0]['status'], len(view.events_after()))"
        )
        result = subprocess.run([sys.executable, "-c", read_after_restart, str(self.path), self.project, self.run],
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "A1 running finished 2")

    def test_project_scope_and_worker_lease(self):
        with self.db.transaction(write=True) as repo:
            with self.assertRaises(KeyError):
                repo.for_run(self.other_project, self.run)
            with self.assertRaises(StorageConflict):
                repo.worker_run(self.project, self.run, "some-other-worker")
            other_run = repo.create_run(self.other_project, "key", {}, {})
            with self.assertRaises(StorageConflict):
                repo.worker_run(self.other_project, other_run, "lease")
        with closing(sqlite3.connect(self.path)) as seed, seed:
            seed.execute("UPDATE runs SET lease_expires_at=datetime('now','-1 minute')")
        with self.db.transaction(write=True) as repo, self.assertRaises(StorageConflict):
            repo.worker_run(self.project, self.run, "lease")

    def test_fk_failure_rolls_back_whole_transaction(self):
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction(write=True) as repo:
            repo.rename_project(self.project, "should roll back")
            work = repo.worker_run(self.project, self.run, "lease")
            work.add_dependency("missing", "also-missing")
        with self.db.transaction() as repo:
            self.assertEqual(repo.get_project(self.project)["name"], "A1")
            self.assertEqual(repo.for_run(self.project, self.run).records("task_dependencies"), [])
            with self.assertRaises(sqlite3.OperationalError):
                repo.rename_project(self.project, "forbidden in read transaction")

    def test_idempotency_and_stale_approval(self):
        with self.db.transaction(write=True) as repo:
            self.assertEqual(repo.create_run(self.project, "key", {"model": "fixture"}, {"tokens": 500}), self.run)
            with self.assertRaises(StorageConflict):
                repo.create_run(self.project, "key", {}, {})
            work = repo.worker_run(self.project, self.run, "lease")
            for version in (1, 2):
                work.add_artifact(f"A{version}", "requirements", version, "1", f"uri{version}", DIGEST, "Requirement")
            with self.assertRaises(StorageConflict):
                repo.record_approval(self.project, self.run, "A1", 1, DIGEST, "approve")
            with self.assertRaises(ValueError):
                repo.record_approval(self.project, self.run, "A2", 2, DIGEST, "request_changes")
            repo.record_approval(self.project, self.run, "A2", 2, DIGEST, "request_changes", "Clarify title")
            with self.assertRaises(ValueError):
                work.add_trace("task", "unknown", "artifact", "A2", "uri")

    def test_only_empty_projects_can_be_deleted(self):
        with self.db.transaction(write=True) as repo:
            repo.delete_empty_project(self.other_project)
            with self.assertRaises(KeyError):
                repo.get_project(self.other_project)
            with self.assertRaises(sqlite3.IntegrityError):
                repo.delete_empty_project(self.project)

    def test_concurrent_migrations_and_idempotent_submission(self):
        path = Path(self.temp.name) / "race.db"
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: Database(path).migrate(), range(8)))
        def submit(_):
            with self.db.transaction(write=True) as repo:
                return repo.create_run(self.project, "new", {"a": 1}, {"b": 2})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(8)))
        self.assertEqual(len(set(results)), 1)

    def test_migrate_refuses_unrecognized_or_future_database(self):
        for name, sql in (("unknown", "CREATE TABLE legacy(id)"), ("future", "PRAGMA user_version=2"),
                          ("incomplete", "PRAGMA user_version=1")):
            with self.subTest(name=name):
                path = Path(self.temp.name) / f"{name}.sqlite"
                with closing(sqlite3.connect(path)) as seed:
                    seed.execute(sql)
                with self.assertRaises(StorageConflict):
                    Database(path).migrate()
