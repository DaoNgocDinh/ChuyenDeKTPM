import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.artifacts import ArtifactStore
from backend.contracts import Architecture, ArtifactRef, Plan, Requirements
from backend.design_agents import DesignAgents
from backend.llm import ModelError
from backend.orchestrator import Orchestrator, RoleOutput
from backend.planning import render_plan, task_order, validate_plan
from backend.skill_registry import RunSkills
from backend.storage import Database
from backend.worker import Queue, Worker
from backend.workspace import Edit, Workspace
from tests.test_design_agents import APPROVED_REQ, ARCH_BODY, BRIEF, ROOT, reply


VALID_PLAN_BODY = {
    "tasks": [
        {
            "task_id": "T_UI",
            "requirement_ids": ["FR1", "FR2"],
            "dependencies": ["T_API"],
            "files": ["app/frontend/Tasks.tsx"],
            "done_conditions": ["Hiển thị danh sách việc và báo lỗi khi tiêu đề rỗng."],
            "tests": ["development"],
        },
        {
            "task_id": "T_DB",
            "requirement_ids": ["FR1", "FR2", "NFR1"],
            "dependencies": [],
            "files": ["app/db.py"],
            "done_conditions": ["Khởi tạo bảng SQLite và lưu bền sau khởi động lại."],
            "tests": ["smoke", "development"],
        },
        {
            "task_id": "T_API",
            "requirement_ids": ["FR1", "FR2"],
            "dependencies": ["T_DB"],
            "files": ["app/api.py"],
            "done_conditions": ["POST /tasks từ chối tiêu đề rỗng và GET /tasks trả đủ bản ghi."],
            "tests": ["smoke", "development"],
        },
    ]
}


class PlanningAgentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "platform.sqlite")
        self.db.migrate()
        self.store = ArtifactStore(root / "workspaces", self.db)
        self.queue = Queue(self.db)
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1", BRIEF)
        self.run = self.queue.enqueue(self.project, "plan-test", {"brief": BRIEF}, {})
        self.skills = RunSkills(ROOT / "skills", enabled=True)

    def _seed_design(self, *, approve_gate1=True, arch_req_override=None):
        lease = self.queue.claim()
        req_ref = self.store.put(self.project, self.run, lease.token, "requirements", APPROVED_REQ, created_by="Requirement")
        arch_payload = {**ARCH_BODY, "requirements": (arch_req_override or req_ref).model_dump()}
        arch_ref = self.store.put(self.project, self.run, lease.token, "architecture", arch_payload, created_by="Architecture")
        self.queue.release(lease, "request_approval")
        if approve_gate1:
            with self.db.transaction(write=True) as repo:
                repo.record_approval(self.project, self.run, req_ref.artifact_id, req_ref.version, req_ref.sha256, "approve", "ok")
        return req_ref, arch_ref

    def test_task_order_and_validate_plan_accepts_valid_dag(self):
        req_ref, arch_ref = self._seed_design()
        req = Requirements.model_validate(APPROVED_REQ)
        arch = Architecture.model_validate({**ARCH_BODY, "requirements": req_ref.model_dump()})
        plan = Plan.model_validate({
            "requirements": req_ref.model_dump(),
            "architecture": arch_ref.model_dump(),
            **VALID_PLAN_BODY,
        })
        ordered = validate_plan(plan, req, arch, req_ref, arch_ref)
        self.assertEqual(ordered, ["T_DB", "T_API", "T_UI"])
        self.assertEqual(task_order(plan), ["T_DB", "T_API", "T_UI"])
        rendered = render_plan(plan, ordered)
        self.assertIn("T_DB -> T_API -> T_UI", rendered)

    def test_invalid_dag_and_policy_violations_rejected(self):
        req_ref, arch_ref = self._seed_design()
        bad_plans = {
            "cycle": {
                "tasks": [
                    {"task_id": "T1", "requirement_ids": ["FR1"], "dependencies": ["T2"],
                     "files": ["app/a.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                    {"task_id": "T2", "requirement_ids": ["FR2"], "dependencies": ["T1"],
                     "files": ["app/b.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                ]
            },
            "unknown_dep": {
                "tasks": [
                    {"task_id": "T1", "requirement_ids": ["FR1", "FR2"], "dependencies": ["T_MISSING"],
                     "files": ["app/a.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                ]
            },
            "missing_fr": {
                "tasks": [
                    {"task_id": "T1", "requirement_ids": ["FR1"], "dependencies": [],
                     "files": ["app/a.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                ]
            },
            "task_without_fr": {
                "tasks": [
                    {"task_id": "T1", "requirement_ids": ["FR1", "FR2"], "dependencies": [],
                     "files": ["app/a.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                    {"task_id": "T2", "requirement_ids": ["NFR1"], "dependencies": ["T1"],
                     "files": ["app/b.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                ]
            },
            "file_outside_app": {
                "tasks": [
                    {"task_id": "T1", "requirement_ids": ["FR1", "FR2"], "dependencies": [],
                     "files": ["tests_dev/test_a.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                ]
            },
            "path_traversal": {
                "tasks": [
                    {"task_id": "T1", "requirement_ids": ["FR1", "FR2"], "dependencies": [],
                     "files": ["app/../evaluation/A1.json"], "done_conditions": ["ok"], "tests": ["smoke"]},
                ]
            },
        }
        for name, bad in bad_plans.items():
            with self.subTest(case=name):
                model = Mock(side_effect=[reply(bad), reply(bad)])
                agents = DesignAgents(self.store, self.skills, model)
                with self.assertRaisesRegex(ModelError, "invalid_handoff") as exc:
                    agents.dispatch(SimpleNamespace(
                        role="Planning", project_id=self.project, run_id=self.run, lease_token="w",
                        step_id="s1", task_id=None, inputs=(req_ref, arch_ref), context={},
                    ))
                self.assertEqual(model.call_count, 2)
                self.assertEqual(exc.exception.usage["input_tokens"], 6)

    def test_unapproved_gate1_or_stale_architecture_stops_before_model(self):
        req_ref, arch_ref = self._seed_design(approve_gate1=False)
        model = Mock(side_effect=AssertionError("model must not be called"))
        agents = DesignAgents(self.store, self.skills, model)
        with self.assertRaisesRegex(ValueError, "gate 1"):
            agents.dispatch(SimpleNamespace(
                role="Planning", project_id=self.project, run_id=self.run, lease_token="w",
                step_id="s1", task_id=None, inputs=(req_ref, arch_ref), context={},
            ))
        model.assert_not_called()

    def test_retry_recovers_from_cyclic_dag_and_aggregates_usage(self):
        req_ref, arch_ref = self._seed_design()
        cyclic = {
            "tasks": [
                {"task_id": "T1", "requirement_ids": ["FR1"], "dependencies": ["T2"],
                 "files": ["app/a.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
                {"task_id": "T2", "requirement_ids": ["FR2"], "dependencies": ["T1"],
                 "files": ["app/b.py"], "done_conditions": ["ok"], "tests": ["smoke"]},
            ]
        }
        model = Mock(side_effect=[reply(cyclic), reply(VALID_PLAN_BODY)])
        agents = DesignAgents(self.store, self.skills, model)
        result = agents.dispatch(SimpleNamespace(
            role="Planning", project_id=self.project, run_id=self.run, lease_token="w",
            step_id="s1", task_id=None, inputs=(req_ref, arch_ref), context={},
        ))
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result.usage["input_tokens"], 6)
        self.assertEqual(result.payload.requirements, req_ref)
        self.assertEqual(result.payload.architecture, arch_ref)
        self.assertIn("T_DB -> T_API -> T_UI", result.markdown)

    def test_three_design_agents_stop_at_atomic_gate2_then_dispatch_dev_in_dag_order(self):
        model = Mock(side_effect=[
            reply(APPROVED_REQ),
            reply({**ARCH_BODY, "blocker": None}),
            reply(VALID_PLAN_BODY),
        ])
        design_agents = DesignAgents(self.store, self.skills, model)
        dev_order = []

        def dispatch(work_order):
            role = work_order.role
            if role == "Orchestrator":
                return RoleOutput({"decision": "approve"}, usage={"input_tokens": 1, "output_tokens": 1, "usage_complete": True})
            if role in {"Requirement", "Architecture", "Planning"}:
                return design_agents.dispatch(work_order)
            ws = Workspace(self.store.root, self.project, self.run)
            label = work_order.context["task"]["task_id"]
            if role == "Dev":
                dev_order.append(label)
                target_file = work_order.context["task"]["files"][0]
                receipt = ws.apply(work_order.task_id, ws.head(), [Edit(target_file, None, f"# {label}\nOK = True\n")])
                with self.db.transaction() as repo:
                    ver = repo.for_run(self.project, self.run).latest_version("patch")
                patch = self.store.put(
                    self.project, self.run, work_order.lease_token, "patch", receipt["diff"],
                    created_by="Dev", expected_previous_version=ver, parent_refs=work_order.inputs,
                )
                return RoleOutput({
                    "task_id": work_order.task_id, "input_commit": receipt["input_commit"],
                    "output_commit": receipt["output_commit"], "patch_sha256": receipt["patch_hash"],
                    "changed_files": [target_file], "summary": label,
                }, usage={"input_tokens": 2, "output_tokens": 1, "usage_complete": True}, patch_ref=patch)
            test_code = "assert True\n"
            ws.apply(work_order.task_id, ws.head(), [Edit(f"tests_dev/test_{label}.py", None, test_code)])
            commit = ws.head()
            proc = subprocess.run([sys.executable, "-B", "-c", test_code], cwd=ws.path, capture_output=True)
            with self.db.transaction() as repo:
                ver = repo.for_run(self.project, self.run).latest_version("runner_output")
            raw = self.store.put(
                self.project, self.run, work_order.lease_token, "runner_output",
                json.dumps({"exit_code": proc.returncode, "passed": 1}),
                created_by="runner", expected_previous_version=ver,
            )
            with self.db.transaction(write=True) as repo:
                w = repo.worker_run(self.project, self.run, work_order.lease_token)
                rid = w.add_report(work_order.task_id, commit, "development", f"reports/{label}", 0, 1, 0, 0, 0, 1)
            return RoleOutput({
                "task_id": work_order.task_id, "commit": commit, "suite_id": "development",
                "runner_output": raw.model_dump(), "exit_code": 0, "passed": 1, "failures": 0, "errors": 0, "skipped": 0,
            }, usage={"input_tokens": 2, "output_tokens": 1, "usage_complete": True}, report_id=rid)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)

        # Gate 1
        worker.run_one()
        with self.db.transaction() as repo:
            cp1 = json.loads(repo.get_run(self.project, self.run)["checkpoint_json"])
        req_refs = [ArtifactRef.model_validate(item) for item in cp1["pending_gate"]["artifacts"]]
        host.gates.decide_gate(self.project, self.run, "requirements", req_refs, "approve")

        # Architecture + Planning -> MUST stop at Gate 2 without calling Dev or creating/closing tasks!
        worker.run_one()
        self.assertEqual(dev_order, [])
        with self.db.transaction() as repo:
            run_row = repo.get_run(self.project, self.run)
            view = repo.for_run(self.project, self.run)
            self.assertEqual(run_row["status"], "waiting_approval")
            cp2 = json.loads(run_row["checkpoint_json"])
            self.assertEqual(cp2["pending_gate"]["gate"], "architecture_plan")
            self.assertEqual(len(cp2["pending_gate"]["artifacts"]), 2)
            self.assertEqual(view.records("tasks"), [])
            self.assertEqual(view.latest_version("requirements"), 1)

        # Atomic Gate 2 approval unlocks Dev strictly in DAG dependency order: T_DB -> T_API -> T_UI.
        gate2_refs = [ArtifactRef.model_validate(item) for item in cp2["pending_gate"]["artifacts"]]
        host.gates.decide_gate(self.project, self.run, "architecture_plan", gate2_refs, "approve")
        worker.run_one()

        with self.db.transaction() as repo:
            self.assertEqual(repo.get_run(self.project, self.run)["status"], "completed")
        self.assertEqual(dev_order, ["T_DB", "T_API", "T_UI"])

    @unittest.skipUnless(os.getenv("SDLC_LIVE_MODEL") == "1", "Set SDLC_LIVE_MODEL=1 to call agy")
    def test_live_planning_from_approved_requirements_and_architecture(self):
        req_ref, arch_ref = self._seed_design()
        agents = DesignAgents(self.store, self.skills)
        result = agents.dispatch(SimpleNamespace(
            role="Planning", project_id=self.project, run_id=self.run, lease_token="w",
            step_id="s-live", task_id=None, inputs=(req_ref, arch_ref), context={},
        ))
        self.assertEqual(result.payload.requirements, req_ref)
        self.assertEqual(result.payload.architecture, arch_ref)
        self.assertGreaterEqual(len(result.payload.tasks), 1)
        print("tasks=", [t.task_id for t in result.payload.tasks], "total_tokens=", result.usage["total_tokens"])
