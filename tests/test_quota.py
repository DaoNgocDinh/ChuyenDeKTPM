"""Tests for I19 support run quota tracker on real SQLite."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.quota import (
    BudgetExceededError,
    PricingSnapshot,
    QuotaLimits,
    RunQuotaTracker,
    UsageEntry,
    read_persisted_quota,
)
from backend.storage import Database


class QuotaTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "platform.sqlite")
        self.db.migrate()
        with self.db.transaction(write=True) as repo:
            self.project_id = repo.create_project("A1", "brief/A1")
            self.run_id = repo.create_run(self.project_id, "q1", {"model": "gemini-4-neon-high"}, {})
            repo._db.execute(
                "UPDATE runs SET status='running', worker_lease='lease-1', "
                "lease_expires_at=datetime('now', '+5 minutes') WHERE id=?",
                (self.run_id,),
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_shared_six_role_budget_separates_approval_wait_and_flags_missing_usage(self) -> None:
        tracker = RunQuotaTracker(
            limits=QuotaLimits(max_total_tokens=None, max_tool_calls=5, max_auto_seconds=120.0),
            pricing=PricingSnapshot(
                model_id="gemini-4-neon-high",
                captured_date="2026-11-26",
                cost_note="Antigravity CLI subscription",
            ),
            started_at_monotonic=100.0,
        )
        tracker.record_llm_usage(UsageEntry("Requirement", "s1", 1000, 400, 200, True))
        tracker.record_llm_usage(UsageEntry("Dev", "s2", None, None, None, False, is_retry=True, note="missing"))
        tracker.add_approval_wait(90.0)
        tracker.record_tool_call(3)

        # Total elapsed = 150s, minus 90s approval wait = 60s automated <= 120s
        tracker.check_limits(now_monotonic=250.0, pending_tool_calls=1)
        snap = tracker.snapshot(now_monotonic=250.0)
        self.assertFalse(snap["usage_complete"])
        self.assertEqual(snap["missing_usage_steps"], ["s2"])
        self.assertEqual(snap["automated_elapsed_seconds"], 60.0)
        self.assertIsNone(snap["cost_usd"])
        self.assertEqual(snap["retry_calls"], 1)

    def test_low_thresholds_block_next_action_and_persist_needs_human_review(self) -> None:
        tracker = RunQuotaTracker(
            limits=QuotaLimits(max_total_tokens=500, max_tool_calls=2, max_auto_seconds=30.0, max_repair_rounds=3),
            pricing=PricingSnapshot(
                model_id="test-priced-model",
                captured_date="2026-11-26",
                input_per_1m_usd=1.0,
                output_per_1m_usd=2.0,
            ),
            started_at_monotonic=10.0,
        )
        tracker.record_llm_usage(UsageEntry("Orchestrator", "s1", 400, 200, 0, True))
        with self.assertRaises(BudgetExceededError) as ctx:
            tracker.check_limits(now_monotonic=15.0)
        self.assertEqual(ctx.exception.reason, "token_limit_exceeded")

        persisted = tracker.persist(
            self.db,
            self.project_id,
            self.run_id,
            "lease-1",
            now_monotonic=15.0,
            transition_on_exceeded=True,
        )
        self.assertEqual(persisted["stop_reason"], "token_limit_exceeded")
        self.assertGreater(persisted["cost_usd"], 0.0)

        with self.db.transaction() as repo:
            run = repo.get_run(self.project_id, self.run_id)
            self.assertEqual(run["status"], "needs_human_review")
            events = repo.for_run(self.project_id, self.run_id).events_after(0)
            self.assertEqual(events[-1]["event_type"], "quota.exceeded")
        saved = read_persisted_quota(self.db, self.project_id, self.run_id)
        self.assertEqual(saved["total_tokens"], 600)

    def test_tool_time_and_repair_limits_each_raise_distinct_reason(self) -> None:
        tracker = RunQuotaTracker(
            limits=QuotaLimits(max_total_tokens=None, max_tool_calls=2, max_auto_seconds=10.0, max_repair_rounds=3),
            pricing=PricingSnapshot(model_id="m", captured_date="2026-11-26"),
            started_at_monotonic=0.0,
        )
        tracker.record_tool_call(2)
        with self.assertRaises(BudgetExceededError) as c1:
            tracker.check_limits(now_monotonic=5.0, pending_tool_calls=1)
        self.assertEqual(c1.exception.reason, "tool_call_limit_exceeded")

        with self.assertRaises(BudgetExceededError) as c2:
            tracker.check_limits(now_monotonic=15.0, pending_tool_calls=0)
        self.assertEqual(c2.exception.reason, "time_limit_exceeded")

        with self.assertRaises(BudgetExceededError) as c3:
            tracker.check_limits(now_monotonic=5.0, pending_tool_calls=0, task_repair_round=4)
        self.assertEqual(c3.exception.reason, "repair_round_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
