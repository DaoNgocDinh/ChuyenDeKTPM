"""Unit tests for E03 experiment protocol, run matrix, and manifest validation."""

from __future__ import annotations

import unittest
from pathlib import Path

from experiments.manifest import (
    ManifestValidationError,
    is_automated_success,
    load_run_matrix,
    validate_dataset_manifests,
    validate_manifest,
)


def _sample_manifest(**overrides):
    base = {
        "run_id": "MAIN-A1-M-01",
        "case_id": "A1",
        "condition": "M",
        "repetition": 1,
        "split": "main",
        "system_commit": "a" * 40,
        "model_id": "gemini-4-neon-high",
        "config_hash": "1" * 64,
        "prompt_hash": "2" * 64,
        "skill_hash": "3" * 64,
        "tool_version": "mcp-2.3.0",
        "start_time": "2026-12-01T10:00:00+07:00",
        "end_time": "2026-12-01T10:12:30+07:00",
        "approval_wait_seconds": 90.0,
        "input_tokens": 12000,
        "output_tokens": 3500,
        "cached_tokens": 4000,
        "usage_complete": True,
        "usage_note": "",
        "cost_usd": None,
        "cost_note": "Antigravity CLI subscription; no direct token billing",
        "repair_rounds": 1,
        "manual_edits": 0,
        "build_ok": True,
        "acceptance_passed": 10,
        "acceptance_total": 10,
        "final_status": "completed",
        "artifact_manifest_uri": "run://MAIN-A1-M-01/artifacts/manifest.json",
        "code_commit": "b" * 40,
        "runner_report_uri": "run://MAIN-A1-M-01/reports/A1_report.json",
    }
    base.update(overrides)
    return base


class E03ProtocolAndManifestTests(unittest.TestCase):
    def test_run_matrix_has_exact_3_pilot_18_main_and_3_ablation_alternating(self) -> None:
        matrix = load_run_matrix()
        self.assertEqual(matrix["ordering_policy"], "fixed_alternating_S_M_across_A1_A2_A3")
        self.assertIsNone(matrix["random_seed"])
        self.assertEqual(len(matrix["pilot_runs"]), 3)
        self.assertEqual(len(matrix["main_runs"]), 18)
        self.assertEqual(len(matrix["ablation_runs"]), 3)

        # Verify alternating S, M across A1 -> A2 -> A3 for repetitions 1..3
        expected_pairs = [
            (case, cond, rep)
            for rep in (1, 2, 3)
            for case in ("A1", "A2", "A3")
            for cond in ("S", "M")
        ]
        actual_pairs = [(r["case_id"], r["condition"], r["repetition"]) for r in matrix["main_runs"]]
        self.assertEqual(actual_pairs, expected_pairs)

        # Verify ablation runs are strictly M_no_skill on A3 with skills disabled
        for row in matrix["ablation_runs"]:
            self.assertEqual(row["case_id"], "A3")
            self.assertEqual(row["condition"], "M_no_skill")
            self.assertEqual(row["split"], "ablation")
            self.assertFalse(row["skills_enabled"])

        # Verify unfrozen parameters are explicitly marked pending_owner_freeze
        for key in ("infra_retry_limit", "time_budget_seconds", "tool_call_limit", "system_commit"):
            entry = matrix["freeze_parameters"][key]
            self.assertIsNone(entry["value"])
            self.assertEqual(entry["status"], "pending_owner_freeze")
            self.assertEqual(entry["freeze_issue"], "E04")

    def test_valid_manifest_passes_and_counts_automated_success(self) -> None:
        m = validate_manifest(_sample_manifest())
        self.assertTrue(is_automated_success(m))

    def test_manual_edits_disqualify_automated_success(self) -> None:
        m = validate_manifest(_sample_manifest(manual_edits=1))
        self.assertFalse(is_automated_success(m))

    def test_failed_run_remains_valid_for_denominator_when_build_fail_has_zero_pass(self) -> None:
        m = validate_manifest(
            _sample_manifest(
                build_ok=False,
                acceptance_passed=0,
                final_status="failed",
                code_commit=None,
            )
        )
        self.assertFalse(is_automated_success(m))

    def test_rejects_build_fail_with_nonzero_acceptance_passed(self) -> None:
        with self.assertRaises(ManifestValidationError):
            validate_manifest(_sample_manifest(build_ok=False, acceptance_passed=3))

    def test_rejects_missing_usage_without_note_or_null_cost_without_note(self) -> None:
        with self.assertRaises(ManifestValidationError):
            validate_manifest(
                _sample_manifest(usage_complete=False, input_tokens=None, output_tokens=None, usage_note="")
            )
        ok_missing = validate_manifest(
            _sample_manifest(
                usage_complete=False,
                input_tokens=None,
                output_tokens=None,
                usage_note="Provider omitted token usage on timeout retry",
            )
        )
        self.assertFalse(ok_missing.usage_complete)

        with self.assertRaises(ManifestValidationError):
            validate_manifest(_sample_manifest(cost_usd=None, cost_note=""))

    def test_rejects_unsafe_uris_and_invalid_hashes_and_durations(self) -> None:
        with self.assertRaises(ManifestValidationError):
            validate_manifest(_sample_manifest(artifact_manifest_uri="C:\\secret\\manifest.json"))
        with self.assertRaises(ManifestValidationError):
            validate_manifest(_sample_manifest(runner_report_uri="../outside/report.json"))
        with self.assertRaises(ManifestValidationError):
            validate_manifest(_sample_manifest(config_hash="not-a-sha256"))
        with self.assertRaises(ManifestValidationError):
            validate_manifest(_sample_manifest(approval_wait_seconds=99999))

    def test_dataset_separates_pilot_from_main_and_enforces_18_run_completeness(self) -> None:
        matrix = load_run_matrix()
        pilots = [
            validate_manifest(
                _sample_manifest(
                    run_id=row["run_id"],
                    case_id=row["case_id"],
                    condition=row["condition"],
                    repetition=row["repetition"],
                    split="pilot",
                )
            )
            for row in matrix["pilot_runs"]
        ]
        mains = [
            validate_manifest(
                _sample_manifest(
                    run_id=row["run_id"],
                    case_id=row["case_id"],
                    condition=row["condition"],
                    repetition=row["repetition"],
                    split="main",
                )
            )
            for row in matrix["main_runs"]
        ]
        grouped = validate_dataset_manifests(pilots + mains, require_complete_main=True)
        self.assertEqual(len(grouped["pilot"]), 3)
        self.assertEqual(len(grouped["main"]), 18)

        # Removing one main run must fail completeness even when 3 pilot runs exist
        with self.assertRaises(ManifestValidationError):
            validate_dataset_manifests(pilots + mains[:-1], require_complete_main=True)

    def test_protocol_doc_mentions_key_rules(self) -> None:
        doc = (Path(__file__).resolve().parents[1] / "experiments" / "protocol.md").read_text(encoding="utf-8")
        for token in ("pending_owner_freeze", "cost_usd = null", "Antigravity CLI", "manual_edits", "18"):
            self.assertIn(token, doc)


if __name__ == "__main__":
    unittest.main()
