"""Tests for I21 support trace and audit service on real SQLite + ArtifactStore."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.artifacts import ArtifactStore
from backend.contracts import Architecture, Plan, RequirementItem, Requirements, Task
from backend.storage import Database
from backend.trace import TraceAuditService


class TraceAuditServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = Database(self.root / "platform.sqlite")
        self.db.migrate()
        self.store = ArtifactStore(self.root / "workspaces", self.db)
        self.service = TraceAuditService(self.db)
        with self.db.transaction(write=True) as repo:
            self.project_id = repo.create_project("A1", "brief/A1")
            self.run_id = repo.create_run(self.project_id, "tr-1", {"model": "test"}, {})
            self.other_run_id = repo.create_run(self.project_id, "tr-2", {"model": "test"}, {})
            repo._db.execute(
                "UPDATE runs SET status='running', worker_lease='lease-1', "
                "lease_expires_at=datetime('now', '+5 minutes') WHERE id=?",
                (self.run_id,),
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_fr_chain_orphan_detection_and_cross_run_isolation(self) -> None:
        req = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "requirements",
            Requirements(
                actors=["User"],
                functional=[
                    RequirementItem(id="FR-1", description="Title required", acceptance=["reject empty"]),
                    RequirementItem(id="FR-2", description="Filter", acceptance=["filter ok"]),
                ],
                nonfunctional=[],
                assumptions=[],
                questions=[],
            ),
            created_by="Requirement",
        )
        arch = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "architecture",
            Architecture(
                requirements=req,
                adr=["FastAPI"],
                components={"api": "FastAPI"},
                entities={"Task": "id"},
                api_contract={"POST /tasks": "201"},
                frontend="React",
                test_strategy="pytest",
                fr_components={"FR-1": ["api"], "FR-2": ["api"]},
            ),
            created_by="Architecture",
        )
        plan = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "plan",
            Plan(
                requirements=req,
                architecture=arch,
                tasks=[
                    Task(
                        task_id="T1",
                        requirement_ids=["FR-1"],
                        dependencies=[],
                        files=["app/main.py"],
                        done_conditions=["pass"],
                        tests=["tests_dev/test_1.py"],
                    )
                ],
            ),
            created_by="Planning",
        )
        patch_ref = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "patch",
            "--- a/app/main.py\n+++ b/app/main.py\n+validate()\n",
            created_by="Dev",
            parent_refs=(plan,),
        )
        with self.db.transaction(write=True) as repo:
            w = repo.worker_run(self.project_id, self.run_id, "lease-1")
            w.add_task("T1", plan.artifact_id, "Validate title", ["FR-1"], ["pass"])
            rep_id = w.add_report("T1", "c" * 40, "development", "reports/rep1.json", 0, 3, 0, 0, 0, 85)

        self.service.link_fr_chain(
            self.project_id,
            self.run_id,
            "lease-1",
            fr_id="FR-1",
            task_id="T1",
            patch_artifact_id=patch_ref.artifact_id,
            test_report_id=rep_id,
            evidence_uri="reports/rep1.json",
        )

        # Cross-run / unknown patch MUST be rejected
        with self.assertRaises(ValueError):
            self.service.link_fr_chain(
                self.project_id,
                self.run_id,
                "lease-1",
                fr_id="FR-2",
                task_id="T1",
                patch_artifact_id="nonexistent-other-run-patch",
                evidence_uri="reports/rep1.json",
            )

        chain1 = self.service.trace_requirement(self.project_id, self.run_id, "FR-1")
        self.assertTrue(chain1.complete)
        self.assertEqual(chain1.task_ids, ("T1",))
        self.assertEqual(chain1.patch_artifacts[0]["sha256"], patch_ref.sha256)
        self.assertEqual(chain1.test_reports[0]["passed"], 3)

        coverage = self.service.audit_requirements_coverage(self.project_id, self.run_id, ["FR-1", "FR-2"])
        self.assertEqual(coverage["linked_complete"], 1)
        self.assertEqual(coverage["incomplete_frs"], ["FR-2"])

        history = self.service.artifact_version_history(self.project_id, self.run_id)
        self.assertEqual(len(history), 4)

    def test_event_redaction_error_taxonomy_and_cursor_stability(self) -> None:
        canary = "CANARY_LIVE_KEY_4242"
        self.service.record_event(
            self.project_id,
            self.run_id,
            "lease-1",
            "step.failed",
            {"api_key": "raw-secret", "detail": f"leaked {canary} here"},
            correlation_id="FLOW-1",
            error_category="policy",
            secrets=(canary,),
        )
        with self.assertRaises(ValueError):
            self.service.record_event(
                self.project_id,
                self.run_id,
                "lease-1",
                "step.failed",
                {},
                correlation_id="FLOW-1",
                error_category="unknown_bucket",
            )

        page1 = self.service.poll_events(self.project_id, self.run_id, after=0)
        self.assertEqual(len(page1["items"]), 1)
        payload = page1["items"][0]["payload"]
        self.assertEqual(payload["api_key"], "[REDACTED]")
        self.assertNotIn(canary, payload["detail"])
        self.assertEqual(payload["error_category"], "policy")

        # Empty second page preserves cursor unchanged
        cursor = page1["next_cursor"]
        page2 = self.service.poll_events(self.project_id, self.run_id, after=cursor)
        self.assertEqual(page2["items"], [])
        self.assertEqual(page2["next_cursor"], cursor)


if __name__ == "__main__":
    unittest.main()
