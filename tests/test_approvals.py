"""Tests for I07 support approval gate service on real SQLite + ArtifactStore."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.approvals import ApprovalService, ApprovalVersionConflict, InvalidGateTransition
from backend.artifacts import ArtifactStore
from backend.contracts import Architecture, Plan, RequirementItem, Requirements, Task
from backend.storage import Database


def _claim_running(db: Database, run_id: str, lease: str) -> None:
    with db.transaction(write=True) as repo:
        repo._db.execute(
            "UPDATE runs SET status='running', worker_lease=?, lease_expires_at=datetime('now', '+5 minutes') "
            "WHERE id=?",
            (lease, run_id),
        )


def _sample_requirements(desc: str = "Tạo task") -> Requirements:
    return Requirements(
        actors=["User"],
        functional=[RequirementItem(id="FR-1", description=desc, acceptance=["Lưu được"])],
        nonfunctional=[],
        assumptions=[],
        questions=["Trạng thái nào hợp lệ?"],
    )


def _sample_architecture(req_ref) -> Architecture:
    return Architecture(
        requirements=req_ref,
        adr=["Dùng FastAPI + SQLite"],
        components={"api": "FastAPI"},
        entities={"Task": "id, title"},
        api_contract={"POST /tasks": "201"},
        frontend="React",
        test_strategy="pytest",
        fr_components={"FR-1": ["api"]},
    )


def _sample_plan(req_ref, arch_ref) -> Plan:
    return Plan(
        requirements=req_ref,
        architecture=arch_ref,
        tasks=[
            Task(
                task_id="T1",
                requirement_ids=["FR-1"],
                dependencies=[],
                files=["app/main.py"],
                done_conditions=["API trả 201"],
                tests=["tests_dev/test_tasks.py"],
            )
        ],
    )


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = Database(self.root / "platform.sqlite")
        self.db.migrate()
        self.store = ArtifactStore(self.root / "workspaces", self.db)
        self.service = ApprovalService(self.db)
        with self.db.transaction(write=True) as repo:
            self.project_id = repo.create_project("A1", "brief/A1")
            self.run_id = repo.create_run(self.project_id, "k1", {"model": "test"}, {})
            self.other_run_id = repo.create_run(self.project_id, "k2", {"model": "test"}, {})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_gate1_revision_blocks_stale_approval_and_v2_approves_cleanly(self) -> None:
        _claim_running(self.db, self.run_id, "lease-1")
        req_v1 = self.store.put(
            self.project_id, self.run_id, "lease-1", "requirements", _sample_requirements("v1"), created_by="Requirement"
        )
        self.assertFalse(self.service.is_gate_approved(self.project_id, self.run_id, "requirements", [req_v1]))

        self.assertEqual(
            self.service.open_gate(self.project_id, self.run_id, "lease-1", "requirements", [req_v1]),
            "waiting_approval",
        )

        # Request changes requires a comment and routes back to Requirement
        with self.assertRaises(ValueError):
            self.service.decide_gate(self.project_id, self.run_id, "requirements", [req_v1], "request_changes", "")
        rev = self.service.decide_gate(
            self.project_id, self.run_id, "requirements", [req_v1], "request_changes", "Thêm kiểm tra tiêu đề rỗng"
        )
        self.assertEqual(rev.next_status, "queued")
        self.assertEqual(rev.route_to, "Requirement")

        # Worker claims again and publishes v2
        _claim_running(self.db, self.run_id, "lease-2")
        req_v2 = self.store.put(
            self.project_id,
            self.run_id,
            "lease-2",
            "requirements",
            _sample_requirements("v2"),
            created_by="Requirement",
            expected_previous_version=1,
            parent_refs=(req_v1,),
        )
        self.service.open_gate(self.project_id, self.run_id, "lease-2", "requirements", [req_v2])

        # Stale approval targeting v1 MUST fail
        with self.assertRaises(ApprovalVersionConflict):
            self.service.decide_gate(self.project_id, self.run_id, "requirements", [req_v1], "approve")

        # Cross-run approval MUST fail
        with self.assertRaises(InvalidGateTransition):
            self.service.decide_gate(self.project_id, self.other_run_id, "requirements", [req_v2], "approve")

        approved = self.service.decide_gate(self.project_id, self.run_id, "requirements", [req_v2], "approve", "OK")
        self.assertEqual(approved.next_status, "queued")
        self.assertTrue(self.service.is_gate_approved(self.project_id, self.run_id, "requirements", [req_v2]))
        self.assertFalse(self.service.is_gate_approved(self.project_id, self.run_id, "requirements", [req_v1]))

    def test_gate2_atomic_approval_and_requirement_change_impact(self) -> None:
        _claim_running(self.db, self.run_id, "lease-1")
        req_v1 = self.store.put(
            self.project_id, self.run_id, "lease-1", "requirements", _sample_requirements("v1"), created_by="Requirement"
        )
        arch_v1 = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "architecture",
            _sample_architecture(req_v1),
            created_by="Architecture",
        )
        plan_v1 = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "plan",
            _sample_plan(req_v1, arch_v1),
            created_by="Planning",
        )
        with self.db.transaction(write=True) as repo:
            w = repo.worker_run(self.project_id, self.run_id, "lease-1")
            w.add_task("T1", plan_v1.artifact_id, "Task 1", ["FR-1"], ["done"])

        # Gate 2 opens with architecture + plan pair and records both atomically
        self.service.open_gate(self.project_id, self.run_id, "lease-1", "architecture_plan", [arch_v1, plan_v1])
        res = self.service.decide_gate(
            self.project_id, self.run_id, "architecture_plan", [arch_v1, plan_v1], "approve", "Đạt cả 2"
        )
        self.assertEqual(len(res.approval_ids), 2)
        self.assertTrue(
            self.service.is_gate_approved(self.project_id, self.run_id, "architecture_plan", [arch_v1, plan_v1])
        )

        # Scope change creates requirements v2 -> flags old arch/plan & tasks as stale
        _claim_running(self.db, self.run_id, "lease-2")
        req_v2 = self.store.put(
            self.project_id,
            self.run_id,
            "lease-2",
            "requirements",
            _sample_requirements("v2 scope change"),
            created_by="Requirement",
            expected_previous_version=1,
            parent_refs=(req_v1,),
        )
        impact = self.service.compute_requirement_change_impact(self.project_id, self.run_id, req_v2)
        self.assertEqual(set(impact.stale_artifact_ids), {arch_v1.artifact_id, plan_v1.artifact_id})
        self.assertEqual(impact.affected_task_ids, ("T1",))

        # Clarification binds strictly to latest version
        self.service.record_clarification(
            self.project_id, self.run_id, req_v2, [{"question_id": "Q1", "answer": "todo, doing, done"}]
        )
        with self.assertRaises(ApprovalVersionConflict):
            self.service.record_clarification(
                self.project_id, self.run_id, req_v1, [{"question_id": "Q1", "answer": "stale"}]
            )


if __name__ == "__main__":
    unittest.main()
