import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from backend.gateway import Gateway, HostStep, ToolDenied
from backend.storage import Database


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        db = self.database = Database(root / "platform.db")
        db.migrate()
        with db.transaction(write=True) as repo:
            self.p = repo.create_project("fixture", "brief")
            self.r = repo.create_run(self.p, "k", {}, {})
        with closing(sqlite3.connect(db.path)) as conn, conn:
            conn.execute("UPDATE runs SET status='running', worker_lease='host', "
                         "lease_expires_at=datetime('now','+5 minutes') WHERE id=?", (self.r,))
        with db.transaction(write=True) as repo:
            w = repo.worker_run(self.p, self.r, "host")
            w.add_artifact("plan", "plan", 1, "1", "plan", "a"*64, "Planning")
            w.add_task("t", "plan", "task", ["FR1"], ["works"])
            for role in ("dev","tester","requirement"):
                w.start_step(role, role, 1, [], task_id="t" if role != "requirement" else None)
        self.g = Gateway(db, root / "workspaces")

    def call(self, role, op, name, args, fn=None):
        return self.g.call(HostStep(self.p, self.r, role, "host"), op, name, args,
                           fn or (lambda *_: {"value": {"secret": "hidden-text"}}))

    def test_roles_scope_and_private_paths(self):
        for i, (role, tool, args) in enumerate([
            ("dev","workspace.read_file",{"role":"tester","path":"app/a"}),
            ("requirement","git.status",{}),
            ("tester","workspace.apply_patch",{"input_commit":"x","edits":[
                {"path":"app/a","expected_hash":None,"text":"hidden-text"}]}),
            ("dev","workspace.read_file",{"path":"app/settings/private.pem"}),
            ("dev","workspace.read_file",{"path":"app/../evaluation/case"}),
            ("dev","tests.run_suite",{"suite_id":"independent"}),
            ("dev","project.read_artifact",{"artifact_id":"foreign","version":1,"sha256":"a"*64})]):
            with self.subTest(role=role,tool=tool), self.assertRaises(ToolDenied):
                self.call(role, f"denied-{i}", tool, args)
        self.call("dev","allowed","workspace.read_file",{"path":"app/main.py"})
        with self.database.transaction() as repo:
            reader = repo.for_run(self.p,self.r)
            calls = reader.records("tool_calls")
            self.assertEqual(7, sum(c["status"]=="denied" for c in calls))
            self.assertNotIn("hidden-text", json.dumps([calls,reader.events_after()]))

    def test_invalid_step_error_and_duplicate_operation(self):
        with self.assertRaises(ToolDenied):
            self.call("missing","wrong-step","git.status",{})
        def bad(*_):
            raise RuntimeError("hidden-text")
        with self.assertRaisesRegex(RuntimeError, "^tool_error$"):
            self.call("dev","err","git.status",{},bad)
        with self.assertRaises(sqlite3.IntegrityError):
            self.call("dev","err","git.status",{})
        with self.database.transaction() as repo:
            reader = repo.for_run(self.p,self.r)
            self.assertNotIn("hidden-text", json.dumps(reader.events_after()))
            self.assertEqual("error", reader.records("tool_calls")[0]["status"])
