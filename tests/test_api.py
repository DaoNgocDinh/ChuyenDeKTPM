import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import create_app, serve_local
from backend.artifacts import ArtifactStore
from backend.exporter import verify_export_zip
from backend.orchestrator import Orchestrator, RoleOutput
from backend.storage import Database
from backend.worker import Queue, Worker
from backend.workspace import Edit, Workspace


class PlatformApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "platform.sqlite")
        self.ws_root = root / "workspaces"
        self.cancelled = []
        self.app = create_app(
            self.db,
            self.ws_root,
            on_cancel=lambda pid, rid: self.cancelled.append((pid, rid)),
        )
        self.client = TestClient(self.app)
        self.store = ArtifactStore(self.ws_root, self.db)
        self.queue = Queue(self.db)

    def _make_worker(self, *, ask_questions=False):
        state = {"ask": ask_questions}

        def dispatch(order):
            role = order.role
            step_usage = {"input_tokens": 10, "output_tokens": 5, "usage_complete": True}
            if role == "Orchestrator":
                return RoleOutput({"decision": "approve", "requested_role": order.context.get("expected_role")}, usage=step_usage)
            if role == "Requirement":
                return RoleOutput(
                    {
                        "actors": ["Owner"],
                        "functional": [{"id": "FR1", "description": "Create task", "acceptance": ["Returns 201"]}],
                        "nonfunctional": [],
                        "assumptions": [],
                        "questions": ["Tiêu đề tối đa bao nhiêu ký tự?"] if state["ask"] else [],
                    },
                    usage=step_usage,
                    markdown="# SRS",
                )
            if role == "Architecture":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "adr": ["SQLite"],
                    "components": {"api": "HTTP"},
                    "entities": {"Task": "id"},
                    "api_contract": {"GET /tasks": "list"},
                    "frontend": "React",
                    "test_strategy": "unit",
                    "fr_components": {"FR1": ["api"]},
                }, usage=step_usage)
            if role == "Planning":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "architecture": order.inputs[1].model_dump(),
                    "tasks": [{
                        "task_id": "t1",
                        "requirement_ids": ["FR1"],
                        "dependencies": [],
                        "files": ["app/tasks.py"],
                        "done_conditions": ["works"],
                        "tests": ["unit"],
                    }],
                }, usage=step_usage)
            ws = Workspace(self.ws_root, order.project_id, order.run_id)
            if role == "Dev":
                receipt = ws.apply(order.task_id, ws.head(), [Edit("app/tasks.py", None, "OK = True\n")])
                with self.db.transaction() as repo:
                    ver = repo.for_run(order.project_id, order.run_id).latest_version("patch")
                patch = self.store.put(
                    order.project_id, order.run_id, order.lease_token, "patch", receipt["diff"],
                    created_by="Dev", expected_previous_version=ver, parent_refs=order.inputs,
                )
                return RoleOutput(
                    {
                        "task_id": order.task_id,
                        "input_commit": receipt["input_commit"],
                        "output_commit": receipt["output_commit"],
                        "patch_sha256": receipt["patch_hash"],
                        "changed_files": ["app/tasks.py"],
                        "summary": "implement tasks",
                    },
                    usage={"input_tokens": 50, "output_tokens": 25, "usage_complete": True},
                    patch_ref=patch,
                )
            ws.apply(order.task_id, ws.head(), [Edit("tests_dev/test_tasks.py", None, "from app.tasks import OK\nassert OK\n")])
            commit = ws.head()
            with self.db.transaction() as repo:
                ver = repo.for_run(order.project_id, order.run_id).latest_version("runner_output")
            raw = self.store.put(
                order.project_id, order.run_id, order.lease_token, "runner_output",
                json.dumps({"exit_code": 0, "passed": 1}),
                created_by="runner", expected_previous_version=ver,
            )
            with self.db.transaction(write=True) as repo:
                writer = repo.worker_run(order.project_id, order.run_id, order.lease_token)
                report_id = writer.add_report(order.task_id, commit, "development", "reports/t1", 0, 1, 0, 0, 0, 12)
            return RoleOutput(
                {
                    "task_id": order.task_id,
                    "commit": commit,
                    "suite_id": "development",
                    "runner_output": raw.model_dump(),
                    "exit_code": 0,
                    "passed": 1,
                    "failures": 0,
                    "errors": 0,
                    "skipped": 0,
                },
                usage={"input_tokens": 40, "output_tokens": 20, "usage_complete": True},
                report_id=report_id,
            )

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        return Worker(self.queue, host), state

    def test_loopback_only_enforcement(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            serve_local(self.db.path, self.ws_root, host="0.0.0.0", port=8000)

    def test_projects_idempotent_runs_and_validation_errors(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

        created = self.client.post("/projects", json={
            "name": "A1",
            "brief": "Quản lý công việc và hạn chót.",
            "constraints": ["SQLite"],
        })
        self.assertEqual(created.status_code, 201)
        project = created.json()
        pid = project["project_id"]
        self.assertEqual(project["constraints"], ["SQLite"])

        listed = self.client.get("/projects").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["project_id"], pid)

        # Invalid body returns D10 error shape with code="invalid_request".
        bad = self.client.post("/projects", json={"name": "", "brief": "x"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["code"], "invalid_request")

        # Create run returns 202 and is idempotent on identical key + payload.
        first = self.client.post(f"/projects/{pid}/runs", json={"idempotency_key": "a1-lan-1"})
        self.assertEqual(first.status_code, 202)
        ticket = first.json()
        self.assertEqual(ticket["status"], "queued")

        replay = self.client.post(f"/projects/{pid}/runs", json={"idempotency_key": "a1-lan-1"})
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["run_id"], ticket["run_id"])

        # Same key with different configuration_ref returns 409 idempotency_conflict.
        conflict = self.client.post(
            f"/projects/{pid}/runs",
            json={"idempotency_key": "a1-lan-1", "configuration_ref": "cfg-v2"},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "idempotency_conflict")

        runs = self.client.get(f"/projects/{pid}/runs").json()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], ticket["run_id"])

    def test_full_http_lifecycle_gates_events_cross_run_isolation_and_export(self):
        p1 = self.client.post("/projects", json={"name": "A1", "brief": "Task app"}).json()["project_id"]
        p2 = self.client.post("/projects", json={"name": "A2", "brief": "Notes app"}).json()["project_id"]
        run1 = self.client.post(f"/projects/{p1}/runs", json={"idempotency_key": "r1"}).json()["run_id"]
        run2 = self.client.post(f"/projects/{p2}/runs", json={"idempotency_key": "r2"}).json()["run_id"]

        worker, state = self._make_worker(ask_questions=True)
        worker.run_one()  # runs run1 to Gate 1 with pending question

        detail = self.client.get(f"/runs/{run1}").json()
        self.assertEqual(detail["status"], "waiting_approval")
        self.assertIn("clarify", detail["next_actions"])
        self.assertTrue(detail["question_artifact_id"])

        # Read requirements v1 via /runs/{run_id}/artifacts and /artifacts/{artifact_id}?run_id=...
        req_items = self.client.get(f"/runs/{run1}/artifacts?kind=requirements").json()
        self.assertEqual(len(req_items), 1)
        req_v1 = req_items[0]
        self.assertIsNone(req_v1["previous_artifact_id"])

        art_detail = self.client.get(f"/artifacts/{req_v1['artifact_id']}", params={"run_id": run1})
        self.assertEqual(art_detail.status_code, 200)
        self.assertEqual(art_detail.json()["media_type"], "application/json")

        # Cross-run read MUST be blocked with 404 not_found.
        cross = self.client.get(f"/artifacts/{req_v1['artifact_id']}", params={"run_id": run2})
        self.assertEqual(cross.status_code, 404)
        self.assertEqual(cross.json()["code"], "not_found")

        # Cannot approve Gate 1 while clarification is unanswered.
        blocked_approve = self.client.post(f"/runs/{run1}/approvals", json={
            "gate": "requirements",
            "artifacts": [{"artifact_id": req_v1["artifact_id"], "version": req_v1["version"], "sha256": req_v1["sha256"]}],
            "decision": "approve",
            "comment": "",
        })
        self.assertEqual(blocked_approve.status_code, 409)
        self.assertEqual(blocked_approve.json()["code"], "invalid_transition")

        # Submit clarification for v1 -> run re-queues; worker regenerates requirements v2.
        clar = self.client.post(f"/runs/{run1}/clarifications", json={
            "artifact": {"artifact_id": req_v1["artifact_id"], "version": req_v1["version"], "sha256": req_v1["sha256"]},
            "answers": [{"question_id": "Q1", "answer": "Tối đa 120 ký tự"}],
        })
        self.assertEqual(clar.status_code, 200)
        self.assertEqual(clar.json()["status"], "queued")

        # Cancel run2 so worker processes run1 next.
        c2 = self.client.post(f"/runs/{run2}/cancel")
        self.assertEqual(c2.status_code, 202)
        self.assertEqual(c2.json()["status"], "cancelled")
        self.assertEqual(self.cancelled, [(p2, run2)])

        state["ask"] = False
        worker.run_one()

        req_versions = self.client.get(f"/runs/{run1}/artifacts?kind=requirements").json()
        self.assertEqual(len(req_versions), 2)
        req_v2 = req_versions[-1]
        self.assertEqual(req_v2["version"], 2)
        self.assertEqual(req_v2["previous_artifact_id"], req_v1["artifact_id"])

        # Stale Gate 1 approval targeting v1 MUST fail with 409 approval_version_conflict.
        stale = self.client.post(f"/runs/{run1}/approvals", json={
            "gate": "requirements",
            "artifacts": [{"artifact_id": req_v1["artifact_id"], "version": req_v1["version"], "sha256": req_v1["sha256"]}],
            "decision": "approve",
            "comment": "",
        })
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["code"], "approval_version_conflict")

        # Approve current Gate 1 (v2).
        ok1 = self.client.post(f"/runs/{run1}/approvals", json={
            "gate": "requirements",
            "artifacts": [{"artifact_id": req_v2["artifact_id"], "version": req_v2["version"], "sha256": req_v2["sha256"]}],
            "decision": "approve",
            "comment": "Đồng ý v2",
        })
        self.assertEqual(ok1.status_code, 200)
        self.assertEqual(ok1.json()["status"], "queued")

        worker.run_one()  # runs Architecture + Planning -> Gate 2
        arch = self.client.get(f"/runs/{run1}/artifacts?kind=architecture").json()[-1]
        plan = self.client.get(f"/runs/{run1}/artifacts?kind=plan").json()[-1]
        ok2 = self.client.post(f"/runs/{run1}/approvals", json={
            "gate": "architecture_plan",
            "artifacts": [
                {"artifact_id": arch["artifact_id"], "version": arch["version"], "sha256": arch["sha256"]},
                {"artifact_id": plan["artifact_id"], "version": plan["version"], "sha256": plan["sha256"]},
            ],
            "decision": "approve",
            "comment": "Duyệt cổng 2",
        })
        self.assertEqual(ok2.status_code, 200)

        worker.run_one()  # completes Dev + Tester
        done = self.client.get(f"/runs/{run1}").json()
        self.assertEqual(done["status"], "completed")
        self.assertIn("accept_output", done["next_actions"])
        self.assertGreaterEqual(done["quota"]["input_tokens"], 90)
        self.assertGreaterEqual(done["quota"]["output_tokens"], 45)
        self.assertTrue(done["quota"]["usage_complete"])

        # Event cursor pagination: page 1 returns events, second poll with next_cursor stays empty & unchanged.
        ev1 = self.client.get(f"/runs/{run1}/events", params={"after": 0}).json()
        self.assertGreater(len(ev1["items"]), 0)
        cursor = ev1["next_cursor"]
        ev2 = self.client.get(f"/runs/{run1}/events", params={"after": cursor}).json()
        self.assertEqual(ev2["items"], [])
        self.assertEqual(ev2["next_cursor"], cursor)

        # Tasks & TestReports endpoints return linked patch and report records.
        tasks = self.client.get(f"/runs/{run1}/tasks").json()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "done")
        self.assertEqual(len(tasks[0]["patch_artifact_ids"]), 1)

        reports = self.client.get(f"/runs/{run1}/test-reports").json()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["passed"], 1)
        self.assertTrue(reports[0]["log_artifact_id"])

        # Export returns verified ZIP.
        exported = self.client.get(f"/runs/{run1}/export")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.headers["content-type"], "application/zip")
        zip_path = Path(self.temp.name) / "downloaded.zip"
        zip_path.write_bytes(exported.content)
        manifest = verify_export_zip(zip_path)
        self.assertEqual(manifest["run_id"], run1)

        # Final acceptance succeeds on current manifest artifact; resume on completed run returns 409 invalid_transition.
        test_art = self.client.get(f"/runs/{run1}/artifacts?kind=test_report").json()[-1]
        acc = self.client.post(f"/runs/{run1}/acceptance", json={
            "manifest": {
                "artifact_id": test_art["artifact_id"],
                "version": test_art["version"],
                "sha256": test_art["sha256"],
            },
            "decision": "accept",
            "comment": "Nghiệm thu đạt",
        })
        self.assertEqual(acc.status_code, 200)

        bad_resume = self.client.post(f"/runs/{run1}/resume")
        self.assertEqual(bad_resume.status_code, 409)
        self.assertEqual(bad_resume.json()["code"], "invalid_transition")

    def test_resume_from_needs_human_review_and_pending_recovery_journal_guard(self):
        pid = self.client.post("/projects", json={"name": "A1", "brief": "Task app"}).json()["project_id"]
        run_id = self.client.post(f"/projects/{pid}/runs", json={"idempotency_key": "rec-1"}).json()["run_id"]
        with self.db.transaction(write=True) as repo:
            repo._db.execute("UPDATE runs SET status='pending_recovery' WHERE id=?", (run_id,))

        # Pending patch journal on disk blocks blind resume with 409 invalid_transition.
        journal = self.ws_root / pid / run_id / "logs" / "pending-patch.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("{}", encoding="utf-8")
        blocked = self.client.post(f"/runs/{run_id}/resume")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["code"], "invalid_transition")

        # Removing reconciled journal allows safe resume back to queued.
        journal.unlink()
        resumed = self.client.post(f"/runs/{run_id}/resume")
        self.assertEqual(resumed.status_code, 202)
        self.assertEqual(resumed.json()["status"], "queued")

    def test_last_error_surfaces_model_failed_code_over_generic_invalid_handoff(self):
        pid = self.client.post("/projects", json={"name": "A1", "brief": "Task app"}).json()["project_id"]
        run_id = self.client.post(f"/projects/{pid}/runs", json={"idempotency_key": "err-1"}).json()["run_id"]
        with self.db.transaction(write=True) as repo:
            repo._db.execute("UPDATE runs SET status='needs_human_review' WHERE id=?", (run_id,))
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, 'claimed', '{}')",
                (run_id,),
            )
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, 'model.failed', ?)",
                (run_id, json.dumps({"code": "provider_quota"})),
            )
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, 'handoff.rejected', ?)",
                (run_id, json.dumps({"reason": "InvalidHandoff"})),
            )
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, 'invalid_handoff', ?)",
                (run_id, json.dumps({"status": "needs_human_review"})),
            )

        detail = self.client.get(f"/runs/{run_id}").json()
        self.assertEqual(detail["last_error"]["code"], "invalid_request")
        self.assertIn("provider_quota", detail["last_error"]["message"])
