"""Consistency checks for Part 3 design report (B02)."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "bao-cao-phan-3.md"


class Part3DesignReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = REPORT.read_text(encoding="utf-8")

    def test_covers_all_18_platform_requirements(self) -> None:
        expected = [f"FR{i:02d}" for i in range(1, 11)] + [f"NFR{i:02d}" for i in range(1, 9)]
        found = re.findall(r"^\| \*\*((?:FR|NFR)\d{2})\*\* \|", self.text, flags=re.MULTILINE)
        self.assertEqual(found, expected)

    def test_covers_six_roles_and_skill_mappings(self) -> None:
        pairs = [
            ("Orchestrator", "workflow-coordination"),
            ("Requirement", "requirements-analysis"),
            ("Architecture", "architecture-design"),
            ("Planning", "task-planning"),
            ("Dev", "implementation"),
            ("Tester", "testing-review"),
        ]
        for role, skill in pairs:
            self.assertIn(f"**{role}**", self.text)
            self.assertIn(f"`{skill}`", self.text)

    def test_covers_all_11_sqlite_tables(self) -> None:
        tables = [
            "projects",
            "runs",
            "artifacts",
            "tasks",
            "task_dependencies",
            "agent_steps",
            "tool_calls",
            "approvals",
            "test_reports",
            "trace_links",
            "events",
        ]
        for table in tables:
            self.assertIn(f"`{table}`", self.text)

    def test_covers_run_and_task_states_and_api_paths(self) -> None:
        for state in (
            "queued",
            "running",
            "waiting_approval",
            "pending_recovery",
            "needs_human_review",
            "completed",
            "failed",
            "cancelled",
            "todo",
            "ready",
            "in_progress",
            "waiting_test",
            "rework",
            "done",
            "blocked",
        ):
            self.assertIn(f"`{state}`", self.text)

        for path in (
            "/projects",
            "/projects/{project_id}/runs",
            "/runs/{run_id}",
            "/runs/{run_id}/events",
            "/runs/{run_id}/clarifications",
            "/runs/{run_id}/cancel",
            "/runs/{run_id}/resume",
            "/runs/{run_id}/artifacts",
            "/artifacts/{artifact_id}",
            "/runs/{run_id}/approvals",
            "/runs/{run_id}/tasks",
            "/runs/{run_id}/test-reports",
            "/runs/{run_id}/export",
            "/runs/{run_id}/acceptance",
        ):
            self.assertIn(path, self.text)

    def test_includes_mermaid_diagrams_walkthrough_and_cross_contract_audit(self) -> None:
        diagrams = re.findall(r"```mermaid", self.text)
        self.assertGreaterEqual(len(diagrams), 3)
        self.assertIn("sequenceDiagram", self.text)
        self.assertIn("erDiagram", self.text)
        self.assertIn("3.10. Ví dụ minh họa một task đi xuyên đủ sáu vai trò", self.text)
        self.assertIn("3.11. Rà soát tính nhất quán giữa các hợp đồng", self.text)
        self.assertIn("không phải", self.text.lower())


if __name__ == "__main__":
    unittest.main()
