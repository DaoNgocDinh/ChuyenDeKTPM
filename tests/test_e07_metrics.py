"""Unit tests for E07 support scripts using explicitly synthetic test manifests."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from experiments.manifest import validate_manifest
from experiments.metrics import RunExecutionCounters, compute_all_groups, format_ratio
from experiments.rubric import create_blind_scoring_sheet, summarize_rubric, unmask_blind_scores
from experiments.tables import load_manifests_from_dir, render_word_56_markdown, write_summary_csv


def _synthetic_manifest(run_id: str, case_id: str, condition: str, rep: int, **overrides):
    raw = {
        "run_id": run_id,
        "case_id": case_id,
        "condition": condition,
        "repetition": rep,
        "split": "main",
        "system_commit": "a" * 40,
        "model_id": "gemini-4-neon-high",
        "config_hash": "1" * 64,
        "prompt_hash": "2" * 64,
        "skill_hash": "3" * 64,
        "tool_version": "mcp-2.3.0",
        "start_time": "2026-12-01T10:00:00+07:00",
        "end_time": "2026-12-01T10:10:00+07:00",
        "approval_wait_seconds": 60.0,
        "input_tokens": 10000,
        "output_tokens": 2500,
        "cached_tokens": 1000,
        "usage_complete": True,
        "usage_note": "",
        "cost_usd": None,
        "cost_note": "Antigravity CLI subscription",
        "repair_rounds": 1,
        "manual_edits": 0,
        "build_ok": True,
        "acceptance_passed": 10,
        "acceptance_total": 10,
        "final_status": "completed",
        "artifact_manifest_uri": f"run://{run_id}/artifacts/manifest.json",
        "code_commit": "b" * 40,
        "runner_report_uri": f"run://{run_id}/reports/{case_id}_report.json",
    }
    raw.update(overrides)
    return validate_manifest(raw)


class E07SupportMetricsTests(unittest.TestCase):
    def test_metrics_include_failed_runs_isolate_pilot_and_handle_zero_denominator(self) -> None:
        pilot = _synthetic_manifest("PILOT-A1-M-01", "A1", "M", 1, split="pilot")
        m1 = _synthetic_manifest("MAIN-A1-M-01", "A1", "M", 1, acceptance_passed=10)
        m2 = _synthetic_manifest(
            "MAIN-A1-M-02",
            "A1",
            "M",
            2,
            build_ok=False,
            acceptance_passed=0,
            code_commit=None,
            final_status="failed",
            usage_complete=False,
            input_tokens=None,
            output_tokens=None,
            usage_note="Missing usage on timeout",
            end_time="2026-12-01T10:20:00+07:00",
        )
        s1 = _synthetic_manifest("MAIN-A1-S-01", "A1", "S", 1, manual_edits=1, acceptance_passed=10)

        counters = {
            "MAIN-A1-M-01": RunExecutionCounters("MAIN-A1-M-01", bugs_confirmed=2, bugs_fixed_with_regression=2),
            "MAIN-A1-S-01": RunExecutionCounters("MAIN-A1-S-01", bugs_confirmed=0, bugs_fixed_with_regression=0),
        }
        groups = compute_all_groups([pilot, m1, m2, s1], counters)
        self.assertEqual([(g.split, g.case_id, g.condition) for g in groups], [
            ("pilot", "A1", "M"),
            ("main", "A1", "S"),
            ("main", "A1", "M"),
        ])

        main_m = groups[2]
        self.assertEqual(main_m.total_runs, 2)  # pilot excluded, failed run included
        self.assertEqual(main_m.automated_complete_runs, 1)
        self.assertEqual(main_m.build_ok_runs, 1)
        self.assertEqual((main_m.criteria_passed, main_m.criteria_total), (10, 20))
        self.assertEqual(main_m.missing_usage_run_ids, ("MAIN-A1-M-02",))
        self.assertEqual(main_m.repair_success_label, "2/2 (100.0%)")

        main_s = groups[1]
        self.assertEqual(main_s.automated_complete_runs, 0)  # manual_edits=1 disqualifies
        self.assertEqual(main_s.repair_success_label, "không áp dụng")
        self.assertEqual(format_ratio(0, 0), "không áp dụng")

    def test_markdown_table_and_csv_trace_back_to_run_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mdir = root / "manifests"
            mdir.mkdir()
            for m in (
                _synthetic_manifest("MAIN-A1-S-01", "A1", "S", 1, acceptance_passed=8),
                _synthetic_manifest("MAIN-A1-M-01", "A1", "M", 1, acceptance_passed=10),
            ):
                (mdir / f"{m.run_id}.json").write_text(json.dumps(m.to_dict()), encoding="utf-8")

            loaded = load_manifests_from_dir(mdir)
            groups = compute_all_groups(loaded)
            md = render_word_56_markdown(groups, split="main")
            self.assertIn("| A1 | S | 0/1 | 8/10 |", md)
            self.assertIn("| A1 | M | 1/1 | 10/10 |", md)
            self.assertIn("MAIN-A1-S-01", md)
            self.assertIn("MAIN-A1-M-01", md)

            csv_path = write_summary_csv(groups, root / "summary.csv")
            with csv_path.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["condition"], "S")
            self.assertEqual(rows[1]["condition"], "M")

    def test_blind_rubric_scoring_hides_condition_and_unmasks_accurately(self) -> None:
        entries = [
            {"run_id": "MAIN-A1-S-01", "case_id": "A1", "condition": "S", "artifact_refs": {"req": "a1"}},
            {"run_id": "MAIN-A1-M-01", "case_id": "A1", "condition": "M", "artifact_refs": {"req": "a2"}},
        ]
        sheet, key_map = create_blind_scoring_sheet(entries)
        self.assertEqual(len(sheet), 2)
        for item in sheet:
            self.assertTrue(item.blind_id.startswith("BLIND-"))
            self.assertNotIn("S", item.blind_id)
            self.assertNotIn("M", item.blind_id)

        raw_scores = [
            {
                "blind_id": item.blind_id,
                "requirements": 2,
                "design": 1,
                "plan": 2,
                "test_evidence": 1,
                "notes": "checked",
            }
            for item in sheet
        ]
        unmasked = unmask_blind_scores(raw_scores, key_map)
        summary = summarize_rubric(unmasked)
        self.assertEqual(len(summary), 2)
        self.assertEqual(summary[0]["mean_total_out_of_8"], 6.0)


if __name__ == "__main__":
    unittest.main()
