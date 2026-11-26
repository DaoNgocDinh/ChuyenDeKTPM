import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.artifacts import ArtifactStore
from backend.contracts import Architecture, ArtifactRef, Requirements
from backend.design_agents import DesignAgents
from backend.llm import MODEL, ModelError, ModelReply, envelope_schema
from backend.orchestrator import Orchestrator, RoleOutput
from backend.skill_registry import RunSkills
from backend.storage import Database
from backend.worker import Queue, Worker

ROOT = Path(__file__).resolve().parents[1]
BRIEF = "Một người dùng cần thêm và xem danh sách việc. Tên việc bắt buộc. Dữ liệu lưu sau khởi động lại."
REQ = {
    "actors": ["Người dùng"],
    "functional": [{"id": "FR1", "description": "Thêm việc",
                    "acceptance": ["Từ chối lưu tên trống."]}],
    "nonfunctional": [], "assumptions": [], "questions": ["Tên trùng có được chấp nhận?"],
}
APPROVED_REQ = {
    "actors": ["Người dùng"],
    "functional": [
        {"id": "FR1", "description": "Thêm việc mới", "acceptance": ["Từ chối tiêu đề trống."]},
        {"id": "FR2", "description": "Xem danh sách việc", "acceptance": ["Trả đủ bản ghi từ SQLite."]},
    ],
    "nonfunctional": [{"id": "NFR1", "description": "Bền vững", "acceptance": ["Khởi động lại không mất dữ liệu."]}],
    "assumptions": [],
    "questions": [],
}
ARCH_BODY = {
    "adr": ["Dùng FastAPI + React + SQLite cục bộ theo P01."],
    "components": {
        "api": "FastAPI REST API kiểm tra validation và trả mã lỗi nhất quán",
        "db": "SQLite repository lưu bảng tasks bền vững",
        "web": "React giao diện tạo và xem danh sách việc",
    },
    "entities": {
        "tasks": "id INTEGER PRIMARY KEY, title TEXT NOT NULL CHECK(length(trim(title)) > 0), status TEXT NOT NULL",
    },
    "api_contract": {
        "POST /tasks": json.dumps({
            "summary": "Tạo việc mới",
            "requestBody": {"required": True},
            "responses": {"201": {"description": "Đã tạo"}, "422": {"description": "Tiêu đề trống"}},
        }, ensure_ascii=False),
        "GET /tasks/{task_id}": json.dumps({
            "summary": "Xem chi tiết việc",
            "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "responses": {"200": {"description": "Thành công"}, "404": {"description": "Không tìm thấy"}},
        }, ensure_ascii=False),
    },
    "frontend": "Một màn hình gồm biểu mẫu thêm việc, thông báo lỗi validation và bảng danh sách việc.",
    "test_strategy": "Chạy kiểm thử smoke và development cho CRUD, validation rỗng và bền vững SQLite.",
    "fr_components": {"FR1": ["api", "db", "web"], "FR2": ["api", "db", "web"]},
}


def reply(output):
    return ModelReply(MODEL, output, [], {"input_tokens": 3, "output_tokens": 2}, True, "p", "c")


def order(role="Requirement", inputs=()):
    return SimpleNamespace(role=role, project_id="project", run_id="run", lease_token="lease",
                           step_id="step", task_id=None, inputs=inputs, context={"brief": BRIEF})


class RequirementAgentTest(unittest.TestCase):
    def test_retry_accounts_for_both_attempts_and_keeps_clarification(self):
        model = Mock(side_effect=[reply({}), reply(REQ)])
        skills = Mock()
        skills.context.return_value = "Chỉ hỏi khi còn thiếu thông tin."
        result = DesignAgents(None, skills, model).dispatch(order())
        self.assertEqual(result.payload, Requirements.model_validate(REQ))
        self.assertIn(REQ["questions"][0], result.markdown)
        self.assertIn(REQ["functional"][0]["acceptance"][0], result.markdown)
        self.assertEqual(result.usage["input_tokens"], 6)
        self.assertEqual(model.call_count, 2)
        skills.context.assert_called_once_with("Requirement")

    def test_second_invalid_output_ends_the_step(self):
        model = Mock(side_effect=[reply({}), reply({})])
        skills = Mock()
        skills.context.return_value = ""
        with self.assertRaisesRegex(ModelError, "invalid_handoff") as failed:
            DesignAgents(None, skills, model).dispatch(order())
        self.assertEqual(failed.exception.usage["output_tokens"], 4)
        self.assertEqual(model.call_count, 2)

    @unittest.skipUnless(os.getenv("SDLC_LIVE_MODEL") == "1", "Set SDLC_LIVE_MODEL=1 to call agy")
    def test_live_requirement_from_vietnamese_brief(self):
        agent = DesignAgents(None, RunSkills(ROOT / "skills", enabled=True))
        result = agent.dispatch(order())
        self.assertTrue(result.payload.functional[0].acceptance)
        self.assertIn(result.payload.functional[0].id, result.markdown)
        print("FRs=", len(result.payload.functional), "questions=", len(result.payload.questions),
              "total_tokens=", result.usage["total_tokens"])


class ArchitectureAgentTest(unittest.TestCase):
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
        self.run = self.queue.enqueue(self.project, "arch-test", {"brief": BRIEF}, {})
        self.skills = RunSkills(ROOT / "skills", enabled=True)

    def _seed_requirements(self, req_data, *, approve=True):
        lease = self.queue.claim()
        ref = self.store.put(self.project, self.run, lease.token, "requirements", req_data, created_by="Requirement")
        self.queue.release(lease, "request_approval")
        if approve:
            with self.db.transaction(write=True) as repo:
                repo.record_approval(self.project, self.run, ref.artifact_id, ref.version, ref.sha256, "approve", "ok")
        return ref

    def test_unapproved_or_clarifying_requirements_stops_before_model(self):
        unapproved = self._seed_requirements(APPROVED_REQ, approve=False)
        model = Mock(side_effect=AssertionError("model must not be called before Gate 1 approval"))
        agent = DesignAgents(self.store, self.skills, model)
        with self.assertRaisesRegex(ValueError, "gate 1"):
            agent.dispatch(SimpleNamespace(
                role="Architecture", project_id=self.project, run_id=self.run, lease_token="w",
                step_id="s1", task_id=None, inputs=(unapproved,), context={},
            ))
        model.assert_not_called()

    def test_architecture_validates_openapi_stack_fr_and_persists_markdown_via_orchestrator(self):
        design_model = Mock(side_effect=[reply(APPROVED_REQ), reply({**ARCH_BODY, "blocker": None})])
        agents = DesignAgents(self.store, self.skills, design_model)

        def dispatch(work_order):
            if work_order.role == "Orchestrator":
                return RoleOutput({"decision": "approve"}, usage={"input_tokens": 1, "output_tokens": 1, "usage_complete": True})
            if work_order.role in {"Requirement", "Architecture"}:
                return agents.dispatch(work_order)
            if work_order.role == "Planning":
                req_ref, arch_ref = work_order.inputs
                return RoleOutput({
                    "requirements": req_ref.model_dump(),
                    "architecture": arch_ref.model_dump(),
                    "tasks": [{
                        "task_id": "T1", "requirement_ids": ["FR1", "FR2"], "dependencies": [],
                        "files": ["app/main.py"], "done_conditions": ["works"], "tests": ["smoke"],
                    }],
                }, usage={"input_tokens": 2, "output_tokens": 1, "usage_complete": True})
            self.fail(f"Unexpected role before Gate 2 approval: {work_order.role}")

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        worker.run_one()

        # Approve Gate 1
        with self.db.transaction() as repo:
            cp = json.loads(repo.get_run(self.project, self.run)["checkpoint_json"])
        req_refs = [ArtifactRef.model_validate(item) for item in cp["pending_gate"]["artifacts"]]
        host.gates.decide_gate(self.project, self.run, "requirements", req_refs, "approve")

        # Worker runs Architecture + Planning and stops at Gate 2
        worker.run_one()
        with self.db.transaction() as repo:
            run_row = repo.get_run(self.project, self.run)
            arts = repo.for_run(self.project, self.run).records("artifacts")
        self.assertEqual(run_row["status"], "waiting_approval")
        arch_rows = [a for a in arts if a["type"] == "architecture"]
        doc_rows = [a for a in arts if a["type"] == "document" and a["created_by"] == "Architecture"]
        self.assertEqual(len(arch_rows), 1)
        self.assertEqual(len(doc_rows), 1)
        arch_obj = Architecture.model_validate_json(
            self.store.read(self.project, self.run, arch_rows[0]["id"], arch_rows[0]["version"], arch_rows[0]["sha256"])
        )
        self.assertEqual(arch_obj.requirements, req_refs[0])
        arch_md = self.store.read(self.project, self.run, doc_rows[0]["id"], doc_rows[0]["version"], doc_rows[0]["sha256"]).decode()
        self.assertIn("```mermaid", arch_md)
        self.assertIn('"openapi": "3.1.0"', arch_md)
        self.assertIn("FR1", arch_md)
        self.assertIn("FR2", arch_md)

    def test_invalid_architecture_variants_rejected_after_retry(self):
        req_ref = self._seed_requirements(APPROVED_REQ, approve=True)
        bad_cases = {
            "missing_fr": {**ARCH_BODY, "fr_components": {"FR1": ["api"]}},
            "unknown_component": {**ARCH_BODY, "fr_components": {"FR1": ["missing"], "FR2": ["api"]}},
            "wrong_stack": {**ARCH_BODY, "components": {"api": "Django", "db": "MongoDB", "web": "Vue"}},
            "missing_path_param": {
                **ARCH_BODY,
                "api_contract": {
                    "GET /tasks/{task_id}": json.dumps({"summary": "get", "responses": {"200": {"description": "ok"}}}),
                },
            },
            "missing_2xx": {
                **ARCH_BODY,
                "api_contract": {
                    "GET /tasks": json.dumps({"summary": "list", "responses": {"500": {"description": "err"}}}),
                },
            },
        }
        for name, bad in bad_cases.items():
            with self.subTest(case=name):
                model = Mock(side_effect=[reply(bad), reply(bad)])
                agent = DesignAgents(self.store, self.skills, model)
                with self.assertRaisesRegex(ModelError, "invalid_handoff") as exc:
                    agent.dispatch(SimpleNamespace(
                        role="Architecture", project_id=self.project, run_id=self.run, lease_token="w",
                        step_id="s", task_id=None, inputs=(req_ref,), context={},
                    ))
                self.assertEqual(model.call_count, 2)
                self.assertEqual(exc.exception.usage["input_tokens"], 6)

    def test_blocker_response_routes_cleanly_to_needs_human_review(self):
        schema_seen = {}

        def model(prompt, schema):
            schema_seen.update(schema)
            if '"stack"' in prompt:
                return reply({"blocker": "Yêu cầu bắt buộc dùng Oracle DB mâu thuẫn với stack khóa SQLite."})
            return reply(APPROVED_REQ)

        agents = DesignAgents(self.store, self.skills, model)

        def dispatch(work_order):
            if work_order.role == "Orchestrator":
                return RoleOutput({"decision": "approve"}, usage={"input_tokens": 1, "output_tokens": 1, "usage_complete": True})
            return agents.dispatch(work_order)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        worker.run_one()
        with self.db.transaction() as repo:
            cp = json.loads(repo.get_run(self.project, self.run)["checkpoint_json"])
        req_refs = [ArtifactRef.model_validate(item) for item in cp["pending_gate"]["artifacts"]]
        host.gates.decide_gate(self.project, self.run, "requirements", req_refs, "approve")

        worker.run_one()
        self.assertIn("output", envelope_schema(schema_seen, {})["properties"])
        with self.db.transaction() as repo:
            run_row = repo.get_run(self.project, self.run)
            events = [e for e in repo.for_run(self.project, self.run).records("events") if e["event_type"] == "model.failed"]
        self.assertEqual(run_row["status"], "needs_human_review")
        self.assertEqual(json.loads(events[-1]["payload_json"])["code"], "architecture_blocked")

    @unittest.skipUnless(os.getenv("SDLC_LIVE_MODEL") == "1", "Set SDLC_LIVE_MODEL=1 to call agy")
    def test_live_architecture_from_approved_requirements(self):
        req_ref = self._seed_requirements(APPROVED_REQ, approve=True)
        agent = DesignAgents(self.store, self.skills)
        result = agent.dispatch(SimpleNamespace(
            role="Architecture", project_id=self.project, run_id=self.run, lease_token="w",
            step_id="s-live", task_id=None, inputs=(req_ref,), context={},
        ))
        self.assertEqual(result.payload.requirements, req_ref)
        self.assertIn('"openapi": "3.1.0"', result.markdown)
        print("components=", list(result.payload.components), "total_tokens=", result.usage["total_tokens"])
