import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.contracts import Requirements
from backend.design_agents import DesignAgents
from backend.llm import MODEL, ModelError, ModelReply
from backend.skill_registry import RunSkills

ROOT = Path(__file__).resolve().parents[1]
BRIEF = "Một người dùng cần thêm và xem danh sách việc. Tên việc bắt buộc. Dữ liệu lưu sau khởi động lại."
REQ = {
    "actors": ["Người dùng"],
    "functional": [{"id": "FR1", "description": "Thêm việc",
                    "acceptance": ["Từ chối lưu tên trống."]}],
    "nonfunctional": [], "assumptions": [], "questions": ["Tên trùng có được chấp nhận?"],
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
