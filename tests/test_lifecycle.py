import unittest
from dataclasses import replace

from backend.lifecycle import Checkpoint, R, T, recovery_action, run_transition, task_transition


class LifecycleTest(unittest.TestCase):
    def test_review_and_retry(self):
        for decision in ("approve_current", "request_revision"):
            state = run_transition(R.QUEUED, "claim")
            state = run_transition(state, "request_approval")
            with self.assertRaises(ValueError):
                run_transition(state, "final_checks_passed")
            self.assertEqual(R.QUEUED, run_transition(state, decision))
        self.assertEqual(R.REVIEW, run_transition(R.RUNNING, "quota_exceeded"))

    def test_repairs_and_terminals(self):
        for used in range(4):
            actual = task_transition(T.TEST, "code_bug", repair_count=used)
            self.assertEqual(T.BLOCKED if used == 3 else T.REWORK, actual)
        for state in (R.COMPLETED, R.CANCELLED, R.FAILED):
            with self.assertRaises(ValueError):
                run_transition(state, "claim")
        self.assertEqual(R.CANCELLED, run_transition(R.WAITING, "cancel"))

    def test_recover_without_duplicate_patch(self):
        start = Checkpoint("op", "base", "patch", None)
        done = replace(start, output_commit="new")
        self.assertEqual("advance_without_replay", recovery_action(start, done, "new"))
        for receipt, head in [(None, "base"), (done, "other"), (replace(done, operation_id="x"), "new")]:
            self.assertEqual("pending_recovery", recovery_action(start, receipt, head))
