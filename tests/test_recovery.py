import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from backend.artifacts import ArtifactStore
from backend.contracts import ArtifactRef
from backend.gateway import CURRENT_OPERATION, Gateway, HostStep
from backend.llm import ModelError
from backend.orchestrator import Orchestrator, RoleOutput
from backend.recovery import RecoveryService, controlled_command
from backend.storage import Database, StorageConflict, encode
from backend.worker import Queue, Worker
from backend.workspace import Edit, Workspace


class RecoveryAndCancelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "platform.sqlite")
        self.db.migrate()
        self.ws_root = root / "workspaces"
        self.store = ArtifactStore(self.ws_root, self.db)
        self.queue = Queue(self.db)
        self.recovery = RecoveryService(self.db, self.store)
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1", "brief/A1")

    def _run_row(self, run_id):
        with self.db.transaction() as repo:
            return repo.get_run(self.project, run_id)

    def _approve_gate(self, host, run_id, expected_gate):
        cp = json.loads(self._run_row(run_id)["checkpoint_json"])
        pending = cp["pending_gate"]
        self.assertEqual(pending["gate"], expected_gate)
        refs = [ArtifactRef.model_validate(item) for item in pending["artifacts"]]
        host.gates.decide_gate(self.project, run_id, expected_gate, refs, "approve")
        return refs

    def test_cancel_terminates_active_child_process_tree_and_blocks_resume(self):
        run_id = self.queue.enqueue(self.project, "cancel-tree", {}, {})
        started = threading.Event()
        pid_file = Path(self.temp.name) / "child.pid"

        def handler(lease, lost):
            started.set()
            script = (
                "import os, pathlib, time\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            controlled_command(
                [sys.executable, "-c", script],
                cwd=self.temp.name, env=os.environ.copy(), input="", timeout=30,
            )
            return "final_checks_passed"

        worker = Worker(self.queue, handler, lease_seconds=10)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_one)
            self.assertTrue(started.wait(3))
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(pid_file.exists(), "child process did not start")

            outcome = self.recovery.cancel(self.project, run_id, wait_seconds=5)
            self.assertEqual(outcome["status"], "cancelled")
            self.assertTrue(future.result(timeout=5))

        row = self._run_row(run_id)
        self.assertEqual(row["status"], "cancelled")
        self.assertIsNotNone(row["ended_at"])
        with self.db.transaction() as repo:
            events = [e["event_type"] for e in repo.for_run(self.project, run_id).records("events")]
        self.assertIn("resource.started", events)
        self.assertIn("cancel.requested", events)
        self.assertIn("resource.stopped", events)
        self.assertIn("cancelled", events)

        # Cancelled run cannot be resumed.
        with self.assertRaises(StorageConflict):
            self.recovery.resume(self.project, run_id)

    def test_crash_after_patch_before_checkpoint_resumes_at_tester_without_replaying_dev(self):
        run_id = self.queue.enqueue(self.project, "crash-after-patch", {}, {})
        gateway = Gateway(self.db, self.ws_root)
        counts = {"Dev": 0, "Tester": 0}
        crash_once = {"armed": True}

        def dispatch(order):
            role = order.role
            if role == "Orchestrator":
                return RoleOutput({"decision": "approve"})
            if role == "Requirement":
                return RoleOutput({
                    "actors": ["Owner"],
                    "functional": [{"id": "FR1", "description": "Greeting", "acceptance": ["OK"]}],
                    "nonfunctional": [], "assumptions": [], "questions": [],
                })
            if role == "Architecture":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(), "adr": ["Python"],
                    "components": {"app": "py"}, "entities": {"Msg": "str"},
                    "api_contract": {"GET /": "ok"}, "frontend": "web",
                    "test_strategy": "unit", "fr_components": {"FR1": ["app"]},
                })
            if role == "Planning":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "architecture": order.inputs[1].model_dump(),
                    "tasks": [{
                        "task_id": "t1", "requirement_ids": ["FR1"], "dependencies": [],
                        "files": ["app/greet.py"], "done_conditions": ["OK=True"], "tests": ["unit"],
                    }],
                })
            if role == "Dev":
                counts["Dev"] += 1
                host_step = HostStep(self.project, run_id, order.step_id, order.lease_token)
                args = {
                    "input_commit": order.context["input_commit"],
                    "edits": [{"path": "app/greet.py", "expected_hash": None, "text": "OK = True\n"}],
                }

                def crash_after_commit(ws, step, name, payload):
                    receipt = ws.apply(
                        step["task_id"], payload["input_commit"],
                        [Edit(**e) for e in payload["edits"]],
                        operation_id=CURRENT_OPERATION.get(),
                    )
                    if crash_once["armed"]:
                        crash_once["armed"] = False
                        # Simulate abrupt process crash AFTER Git commit & receipt, BEFORE Gateway._finish / finish_step.
                        raise BaseException("simulated_hard_crash_after_patch")
                    return receipt

                gateway.call(host_step, "op_patch_1", "workspace.apply_patch", args, crash_after_commit)
                self.fail("unreachable on crash turn")

            # Tester executes on the recovered commit without Dev ever running a 2nd time!
            counts["Tester"] += 1
            ws = Workspace(self.ws_root, self.project, run_id)
            test_code = "from app.greet import OK\nassert OK\n"
            ws.apply(order.task_id, ws.head(), [Edit("tests_dev/test_greet.py", None, test_code)])
            commit = ws.head()
            proc = subprocess.run([sys.executable, "-B", "-c", test_code], cwd=ws.path, capture_output=True)
            with self.db.transaction() as repo:
                ver = repo.for_run(self.project, run_id).latest_version("runner_output")
            raw = self.store.put(
                self.project, run_id, order.lease_token, "runner_output",
                json.dumps({"exit_code": proc.returncode, "passed": 1}),
                created_by="runner", expected_previous_version=ver,
            )
            with self.db.transaction(write=True) as repo:
                writer = repo.worker_run(self.project, run_id, order.lease_token)
                rid = writer.add_report(order.task_id, commit, "development", "reports/t1", proc.returncode, 1, 0, 0, 0, 5)
            return RoleOutput({
                "task_id": order.task_id, "commit": commit, "suite_id": "development",
                "runner_output": raw.model_dump(), "exit_code": proc.returncode,
                "passed": 1, "failures": 0, "errors": 0, "skipped": 0,
            }, report_id=rid)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host, lease_seconds=5)

        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")

        # Crash right after Git commit + receipt write.
        with self.assertRaises(BaseException):
            worker.run_one()

        # Simulate expired lease sweeping the crashed worker into pending_recovery.
        with closing(sqlite3.connect(self.db.path)) as conn, conn:
            conn.execute("UPDATE runs SET lease_expires_at=datetime('now','-1 minute') WHERE id=?", (run_id,))
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self._run_row(run_id)["status"], "pending_recovery")
        self.assertEqual(counts["Dev"], 1)

        # RecoveryService reconciles the applied patch receipt -> advances to Tester WITHOUT replaying Dev!
        resumed = self.recovery.resume(self.project, run_id)
        self.assertEqual(resumed, {"status": "queued", "reason": "resume_at_tester"})

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "completed")
        self.assertEqual(counts["Dev"], 1)
        self.assertEqual(counts["Tester"], 1)

    def test_missing_receipt_and_incomplete_patch_journal_block_blind_replay(self):
        run_id = self.queue.enqueue(self.project, "uncertain-crash", {}, {})
        lease = self.queue.claim()
        ws = Workspace(self.ws_root, self.project, run_id)
        base = ws.initialize()
        req = self.store.put(self.project, run_id, lease.token, "requirements", {
            "actors": ["u"], "functional": [{"id": "FR1", "description": "d", "acceptance": ["a"]}],
            "nonfunctional": [], "assumptions": [], "questions": [],
        }, created_by="Requirement")
        arch = self.store.put(self.project, run_id, lease.token, "architecture", {
            "requirements": req.model_dump(), "adr": ["a"], "components": {"c": "c"},
            "entities": {"e": "e"}, "api_contract": {"GET /": "ok"}, "frontend": "f",
            "test_strategy": "t", "fr_components": {"FR1": ["c"]},
        }, created_by="Architecture")
        plan = self.store.put(self.project, run_id, lease.token, "plan", {
            "requirements": req.model_dump(), "architecture": arch.model_dump(),
            "tasks": [{"task_id": "t1", "requirement_ids": ["FR1"], "dependencies": [],
                       "files": ["app/a.py"], "done_conditions": ["ok"], "tests": ["unit"]}],
        }, created_by="Planning")
        with self.db.transaction(write=True) as repo:
            w = repo.worker_run(self.project, run_id, lease.token)
            for ref in (req, arch, plan):
                repo.record_approval(self.project, run_id, ref.artifact_id, ref.version, ref.sha256, "approve", "ok")
            w.add_task("t1", plan.artifact_id, "t1", ["FR1"], ["ok"])
            w.update_task("t1", "todo", "in_progress", 0)
            w.start_step("s1", "Dev", 1, [], "t1")
        cp = {
            "phase": "before",
            "step_id": "s1",
            "operation_id": "op_missing",
            "input_refs": [req.model_dump()],
            "approved_gates": {
                "requirements": [req.model_dump()],
                "architecture_plan": [arch.model_dump(), plan.model_dump()],
            },
            "pending_effect": {
                "operation_id": "op_missing",
                "step_id": "s1",
                "task_id": "t1",
                "input_commit": base,
                "patch_hash": "a" * 64,
            },
        }
        with self.db.transaction(write=True) as repo:
            repo._db.execute(
                "UPDATE runs SET status='pending_recovery', worker_lease=NULL, lease_expires_at=NULL, checkpoint_json=? WHERE id=?",
                (encode(cp), run_id),
            )

        # Case 1: Missing receipt blocks blind replay.
        blocked = self.recovery.resume(self.project, run_id)
        self.assertEqual(blocked, {"status": "pending_recovery", "reason": "missing_or_mismatched_receipt"})

        # Case 2: Pending patch journal left on disk also blocks resume.
        journal = ws.path / "logs" / "pending-patch.json"
        journal.write_text("{}", encoding="utf-8")
        blocked_journal = self.recovery.resume(self.project, run_id)
        self.assertEqual(blocked_journal, {"status": "pending_recovery", "reason": "incomplete_patch_journal"})

    def test_resume_rejects_changed_inputs_approvals_workspace_and_blocked_tasks(self):
        run_id = self.queue.enqueue(self.project, "tamper-checks", {}, {})
        lease = self.queue.claim()
        ws = Workspace(self.ws_root, self.project, run_id)
        base = ws.initialize()
        req = self.store.put(self.project, run_id, lease.token, "requirements", {
            "actors": ["u"], "functional": [{"id": "FR1", "description": "d", "acceptance": ["a"]}],
            "nonfunctional": [], "assumptions": [], "questions": [],
        }, created_by="Requirement")
        with self.db.transaction(write=True) as repo:
            repo.record_approval(self.project, run_id, req.artifact_id, req.version, req.sha256, "approve", "ok")
        cp = {
            "phase": "after",
            "output_commit": base,
            "input_refs": [req.model_dump()],
            "approved_gates": {"requirements": [req.model_dump()]},
        }
        with self.db.transaction(write=True) as repo:
            repo._db.execute(
                "UPDATE runs SET status='needs_human_review', worker_lease=NULL, lease_expires_at=NULL, checkpoint_json=? WHERE id=?",
                (encode(cp), run_id),
            )

        # 1. Dirty workspace rejected.
        (ws.path / "app" / "untracked.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(self.recovery.resume(self.project, run_id)["reason"], "workspace_changed")
        (ws.path / "app" / "untracked.py").unlink()

        # 2. Blocked task preserves human blocker.
        with self.db.transaction(write=True) as repo:
            repo._db.execute(
                "INSERT INTO artifacts(id,run_id,type,version,schema_version,uri,sha256,created_by,parent_refs_json) "
                "VALUES ('p1',?,'plan',1,'1','artifacts/x','b' || substr(hex(zeroblob(32)),2),'host','[]')",
                (run_id,),
            )
            repo._db.execute(
                "INSERT INTO tasks(id,run_id,plan_artifact_id,requirement_refs_json,description,status,repair_round,done_conditions_json) "
                "VALUES ('t_blk',?,'p1','[\"FR1\"]','blocked task','blocked',3,'[\"ok\"]')",
                (run_id,),
            )
        self.assertEqual(self.recovery.resume(self.project, run_id)["reason"], "task_blocked_needs_human")
        with self.db.transaction(write=True) as repo:
            repo._db.execute("UPDATE tasks SET status='rework' WHERE run_id=? AND id='t_blk'", (run_id,))

        # 3. Corrupted artifact content rejected (input hash mismatch).
        blob_path = self.ws_root / self.project / run_id / "artifacts" / f"{req.sha256}.blob"
        original_bytes = blob_path.read_bytes()
        blob_path.write_bytes(b"corrupted")
        self.assertEqual(self.recovery.resume(self.project, run_id)["reason"], "evidence_unavailable")
        blob_path.write_bytes(original_bytes)

        # 4. Stale approval rejected when a newer unapproved requirements v2 appears.
        with self.db.transaction(write=True) as repo:
            repo._db.execute(
                "INSERT INTO artifacts(id,run_id,type,version,schema_version,uri,sha256,created_by,parent_refs_json) "
                "VALUES ('req2',?,'requirements',2,'1','artifacts/y','c' || substr(hex(zeroblob(32)),2),'host','[]')",
                (run_id,),
            )
        self.assertEqual(self.recovery.resume(self.project, run_id)["reason"], "approval_changed")

    def test_clean_needs_human_review_resumes_at_checkpoint(self):
        run_id = self.queue.enqueue(self.project, "clean-resume", {}, {})
        lease = self.queue.claim()
        ws = Workspace(self.ws_root, self.project, run_id)
        base = ws.initialize()
        req = self.store.put(self.project, run_id, lease.token, "requirements", {
            "actors": ["u"], "functional": [{"id": "FR1", "description": "d", "acceptance": ["a"]}],
            "nonfunctional": [], "assumptions": [], "questions": [],
        }, created_by="Requirement")
        with self.db.transaction(write=True) as repo:
            repo.record_approval(self.project, run_id, req.artifact_id, req.version, req.sha256, "approve", "ok")
        cp = {
            "phase": "after",
            "output_commit": base,
            "input_refs": [req.model_dump()],
            "approved_gates": {"requirements": [req.model_dump()]},
        }
        with self.db.transaction(write=True) as repo:
            repo._db.execute(
                "UPDATE runs SET status='needs_human_review', worker_lease=NULL, lease_expires_at=NULL, checkpoint_json=? WHERE id=?",
                (encode(cp), run_id),
            )

        resumed = self.recovery.resume(self.project, run_id)
        self.assertEqual(resumed, {"status": "queued", "reason": "resume_at_checkpoint"})
        self.assertEqual(self._run_row(run_id)["status"], "queued")

    def test_resume_after_tester_model_error_reenters_tester_without_replaying_dev(self):
        run_id = self.queue.enqueue(self.project, "resume-waiting-test", {}, {})
        counts = {"Dev": 0, "Tester": 0}

        def dispatch(order):
            role = order.role
            if role == "Orchestrator":
                return RoleOutput({"decision": "approve"})
            if role == "Requirement":
                return RoleOutput({
                    "actors": ["Owner"],
                    "functional": [{"id": "FR1", "description": "Greeting", "acceptance": ["OK"]}],
                    "nonfunctional": [], "assumptions": [], "questions": [],
                })
            if role == "Architecture":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(), "adr": ["Python"],
                    "components": {"app": "py"}, "entities": {"Msg": "str"},
                    "api_contract": {"GET /": "ok"}, "frontend": "web",
                    "test_strategy": "unit", "fr_components": {"FR1": ["app"]},
                })
            if role == "Planning":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "architecture": order.inputs[1].model_dump(),
                    "tasks": [{
                        "task_id": "t1", "requirement_ids": ["FR1"], "dependencies": [],
                        "files": ["app/greet.py"], "done_conditions": ["OK=True"], "tests": ["unit"],
                    }],
                })
            ws = Workspace(self.ws_root, self.project, run_id)
            if role == "Dev":
                counts["Dev"] += 1
                receipt = ws.apply(order.task_id, ws.head(), [Edit("app/greet.py", None, "OK = True\n")])
                with self.db.transaction() as repo:
                    ver = repo.for_run(self.project, run_id).latest_version("patch")
                patch = self.store.put(
                    self.project, run_id, order.lease_token, "patch", receipt["diff"],
                    created_by="Dev", expected_previous_version=ver, parent_refs=order.inputs,
                )
                return RoleOutput({
                    "task_id": order.task_id, "input_commit": receipt["input_commit"],
                    "output_commit": receipt["output_commit"], "patch_sha256": receipt["patch_hash"],
                    "changed_files": ["app/greet.py"], "summary": "implement greet",
                }, patch_ref=patch)
            counts["Tester"] += 1
            if counts["Tester"] == 1:
                raise ModelError("provider_quota", {"input_tokens": 120, "output_tokens": 40})
            test_code = "from app.greet import OK\nassert OK\n"
            ws.apply(order.task_id, ws.head(), [Edit("tests_dev/test_greet.py", None, test_code)])
            commit = ws.head()
            proc = subprocess.run([sys.executable, "-B", "-c", test_code], cwd=ws.path, capture_output=True)
            with self.db.transaction() as repo:
                ver = repo.for_run(self.project, run_id).latest_version("runner_output")
            raw = self.store.put(
                self.project, run_id, order.lease_token, "runner_output",
                json.dumps({"exit_code": proc.returncode, "passed": 1}),
                created_by="runner", expected_previous_version=ver,
            )
            with self.db.transaction(write=True) as repo:
                writer = repo.worker_run(self.project, run_id, order.lease_token)
                rid = writer.add_report(order.task_id, commit, "development", "reports/t1", proc.returncode, 1, 0, 0, 0, 5)
            return RoleOutput({
                "task_id": order.task_id, "commit": commit, "suite_id": "development",
                "runner_output": raw.model_dump(), "exit_code": proc.returncode,
                "passed": 1, "failures": 0, "errors": 0, "skipped": 0,
            }, report_id=rid)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()

        self.assertEqual(self._run_row(run_id)["status"], "needs_human_review")
        self.assertEqual(counts, {"Dev": 1, "Tester": 1})

        resumed = self.recovery.resume(self.project, run_id)
        self.assertEqual(resumed, {"status": "queued", "reason": "resume_at_checkpoint"})

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "completed")
        self.assertEqual(counts, {"Dev": 1, "Tester": 2})

    def test_interrupted_read_only_planning_step_resumes_while_dev_still_blocks(self):
        run_id = self.queue.enqueue(self.project, "resume-planning", {}, {})
        crash_once = {"armed": True}

        def dispatch(order):
            role = order.role
            if role == "Orchestrator":
                return RoleOutput({"decision": "approve"})
            if role == "Requirement":
                return RoleOutput({
                    "actors": ["Owner"],
                    "functional": [{"id": "FR1", "description": "Greeting", "acceptance": ["OK"]}],
                    "nonfunctional": [], "assumptions": [], "questions": [],
                })
            if role == "Architecture":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(), "adr": ["Python"],
                    "components": {"app": "py"}, "entities": {"Msg": "str"},
                    "api_contract": {"GET /": "ok"}, "frontend": "web",
                    "test_strategy": "unit", "fr_components": {"FR1": ["app"]},
                })
            if role == "Planning":
                if crash_once["armed"]:
                    crash_once["armed"] = False
                    raise PermissionError("simulated windows tempdir cleanup lock")
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "architecture": order.inputs[1].model_dump(),
                    "tasks": [{
                        "task_id": "t1", "requirement_ids": ["FR1"], "dependencies": [],
                        "files": ["app/greet.py"], "done_conditions": ["OK=True"], "tests": ["unit"],
                    }],
                })
            self.fail(f"Unexpected role {role}")

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        with self.assertRaises(PermissionError):
            worker.run_one()

        self.assertEqual(self._run_row(run_id)["status"], "pending_recovery")
        resumed = self.recovery.resume(self.project, run_id)
        self.assertEqual(resumed, {"status": "queued", "reason": "resume_at_checkpoint"})

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "waiting_approval")

        # Contrast: an interrupted Dev step without an operation receipt MUST remain blocked.
        dev_run = self.queue.enqueue(self.project, "dev-no-receipt", {}, {})
        lease = self.queue.claim()
        self.queue.start_step(lease, "s-dev", "Dev", 1, [], {"operation_id": "op-dev"})
        self.queue.release(lease, "effects_uncertain")
        blocked = self.recovery.resume(self.project, dev_run)
        self.assertEqual(blocked, {"status": "pending_recovery", "reason": "missing_operation_receipt"})

    def test_resume_after_dev_model_error_before_patch_reenters_in_progress_task(self):
        run_id = self.queue.enqueue(self.project, "resume-in-progress-dev", {}, {})
        counts = {"Dev": 0, "Tester": 0}

        def dispatch(order):
            role = order.role
            if role == "Orchestrator":
                return RoleOutput({"decision": "approve"})
            if role == "Requirement":
                return RoleOutput({
                    "actors": ["Owner"],
                    "functional": [{"id": "FR1", "description": "Greeting", "acceptance": ["OK"]}],
                    "nonfunctional": [], "assumptions": [], "questions": [],
                })
            if role == "Architecture":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(), "adr": ["Python"],
                    "components": {"app": "py"}, "entities": {"Msg": "str"},
                    "api_contract": {"GET /": "ok"}, "frontend": "web",
                    "test_strategy": "unit", "fr_components": {"FR1": ["app"]},
                })
            if role == "Planning":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "architecture": order.inputs[1].model_dump(),
                    "tasks": [{
                        "task_id": "t1", "requirement_ids": ["FR1"], "dependencies": [],
                        "files": ["app/greet.py"], "done_conditions": ["OK=True"], "tests": ["unit"],
                    }],
                })
            ws = Workspace(self.ws_root, self.project, run_id)
            if role == "Dev":
                counts["Dev"] += 1
                if counts["Dev"] == 1:
                    raise ModelError("provider_timeout", {"input_tokens": 0, "output_tokens": 0})
                receipt = ws.apply(order.task_id, ws.head(), [Edit("app/greet.py", None, "OK = True\n")])
                with self.db.transaction() as repo:
                    ver = repo.for_run(self.project, run_id).latest_version("patch")
                patch = self.store.put(
                    self.project, run_id, order.lease_token, "patch", receipt["diff"],
                    created_by="Dev", expected_previous_version=ver, parent_refs=order.inputs,
                )
                return RoleOutput({
                    "task_id": order.task_id, "input_commit": receipt["input_commit"],
                    "output_commit": receipt["output_commit"], "patch_sha256": receipt["patch_hash"],
                    "changed_files": ["app/greet.py"], "summary": "implement greet",
                }, patch_ref=patch)
            counts["Tester"] += 1
            test_code = "from app.greet import OK\nassert OK\n"
            ws.apply(order.task_id, ws.head(), [Edit("tests_dev/test_greet.py", None, test_code)])
            commit = ws.head()
            proc = subprocess.run([sys.executable, "-B", "-c", test_code], cwd=ws.path, capture_output=True)
            with self.db.transaction() as repo:
                ver = repo.for_run(self.project, run_id).latest_version("runner_output")
            raw = self.store.put(
                self.project, run_id, order.lease_token, "runner_output",
                json.dumps({"exit_code": proc.returncode, "passed": 1}),
                created_by="runner", expected_previous_version=ver,
            )
            with self.db.transaction(write=True) as repo:
                writer = repo.worker_run(self.project, run_id, order.lease_token)
                rid = writer.add_report(order.task_id, commit, "development", "reports/t1", proc.returncode, 1, 0, 0, 0, 5)
            return RoleOutput({
                "task_id": order.task_id, "commit": commit, "suite_id": "development",
                "runner_output": raw.model_dump(), "exit_code": proc.returncode,
                "passed": 1, "failures": 0, "errors": 0, "skipped": 0,
            }, report_id=rid)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()

        self.assertEqual(self._run_row(run_id)["status"], "needs_human_review")
        self.assertEqual(counts, {"Dev": 1, "Tester": 0})

        resumed = self.recovery.resume(self.project, run_id)
        self.assertEqual(resumed, {"status": "queued", "reason": "resume_at_checkpoint"})

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "completed")
        self.assertEqual(counts, {"Dev": 2, "Tester": 1})
