import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.artifacts import ArtifactStore
from backend.gateway import HostStep
from backend.mcp_tools import TOOLS, discover, invoke, step_client
from backend.storage import Database
from backend.workspace import Workspace, content_hash


class RealSession(unittest.IsolatedAsyncioTestCase):
    async def test_discover_patch_audit_and_deny(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspaces"
            db = Database(Path(tmp) / "meta.sqlite")
            db.migrate()
            with db.transaction(write=True) as repo:
                project = repo.create_project("demo", "brief")
                run = repo.create_run(project, "id", {}, {})
            with closing(sqlite3.connect(db.path)) as conn, conn:
                conn.execute("UPDATE runs SET status='running',worker_lease='w',"
                             "lease_expires_at=datetime('now','+10 minutes') WHERE id=?", (run,))
            with db.transaction(write=True) as repo:
                writer = repo.worker_run(project, run, "w")
                writer.add_artifact("plan", "plan", 1, "1", "fixture", "b"*64, "host")
                writer.add_task("t", "plan", "add item", ["FR-1"], ["smoke"])
                writer.start_step("dev", "Dev", 1, [], "t")
                writer.start_step("test", "Tester", 1, [], "t")
            store = ArtifactStore(root, db)
            ref = store.put(project,run,"w","document","demo requirements",created_by="host")
            first = Workspace(root, project, run).initialize()
            async with step_client(db.path, root, HostStep(project,run,"dev","w")) as client:
                manifest = await discover(client)
                self.assertEqual(set(TOOLS), set(manifest["tools"]))
                self.assertEqual(len(manifest["tool_schema_sha256"]), 64)
                result = await invoke(client,"doc","project.read_artifact",{"artifact_id":ref.artifact_id,
                                      "version":ref.version,"sha256":ref.sha256})
                self.assertEqual("demo requirements", result["text"])
                args = {"input_commit":first,"edits":[{"path":"app/tasks.py","text":"title = 'demo'\n",
                                                       "expected_hash":None}]}
                out = await invoke(client,"write","workspace.apply_patch",args)
                head = (await invoke(client,"status","git.status",{}))["head"]
                self.assertEqual(out["output_commit"],head)
                self.assertIn("app/tasks.py",(await invoke(client,"list","workspace.list_files",{}))["files"])
                file = await invoke(client,"read","workspace.read_file",{"path":"app/tasks.py"})
                self.assertEqual(content_hash(b"title = 'demo'\n"),file["sha256"])
                self.assertIn("+title", (await invoke(client,"diff","git.diff",{"before":first,"after":head}))["diff"])
                with self.assertRaises(RuntimeError):
                    await invoke(client,"stale","workspace.apply_patch",args)
            image = os.getenv("KTPM_TEST_RUNNER_IMAGE")
            async with step_client(db.path,root,HostStep(project,run,"test","w"),image=image) as client:
                with self.assertRaisesRegex(RuntimeError,"tool_denied"):
                    await invoke(client,"denied","workspace.apply_patch",dict(args,input_commit=head))
                with self.assertRaisesRegex(RuntimeError,"tool_denied"):
                    await invoke(client,"spoof","git.status",{"role":"Dev","secret":"do-not-log"})
                if image:
                    test_file = {"path":"tests_dev/test_smoke.py","expected_hash":None,
                                 "text":"from app.tasks import title\n\ndef test_title():\n    assert title == 'demo'\n"}
                    tested = await invoke(client,"add-test","workspace.apply_patch",
                                          {"input_commit":head,"edits":[test_file]})
                    verified = await invoke(client,"suite","tests.run_suite",{"suite_id":"smoke"})
                    self.assertEqual(verified["report"]["commit"], tested["output_commit"])
                    self.assertEqual(verified["report"]["status"], "passed", verified)
                    self.assertEqual(verified["report"]["passed"], 1)
                    self.assertTrue(verified["report_id"])
                    self.assertEqual(verified["runner_output"]["run_id"], run)
            with db.transaction() as repo:
                rows = repo.for_run(project,run).records("tool_calls")
                self.assertEqual(len(rows), 11 if image else 9)
                self.assertNotIn("do-not-log",json.dumps(rows))
                self.assertEqual(2,sum(r["status"]=="denied" for r in rows))
