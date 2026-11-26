"""Verification suite for E01 independent acceptance tests, fixtures, reports, and checksums."""

from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluation.checksums import compute_manifest, verify_manifest
from evaluation.fixtures.reference_apps import (
    FaultFlags,
    ReferenceA1Adapter,
    ReferenceA2Adapter,
    ReferenceA3Adapter,
)
from evaluation.reporting import CriterionOutcome, run_case_evaluation, summarize_outcomes
from evaluation.ui_driver import StrictMissingUIDriver


SAMPLE_COMMIT = "a" * 40


class E01EvaluationTests(unittest.TestCase):
    def test_a1_positive_reference_passes_all_10_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = ReferenceA1Adapter(root)
            try:
                out_dir = root / "reports"
                report = run_case_evaluation("A1", adapter, code_commit=SAMPLE_COMMIT, output_dir=out_dir)
                self.assertTrue(report.build_ok)
                self.assertEqual(report.exit_code, 0)
                self.assertEqual((report.passed, report.failed, report.errors, report.skipped), (10, 0, 0, 0))
                self.assertEqual(report.acceptance_passed, 10)
                self.assertEqual(report.acceptance_total, 10)
                self.assertEqual([c.criterion_id for c in report.criteria], [f"A1-{i:02d}" for i in range(1, 11)])

                json_data = json.loads((out_dir / "A1_report.json").read_text(encoding="utf-8"))
                self.assertEqual(json_data["code_commit"], SAMPLE_COMMIT)
                self.assertEqual(json_data["acceptance_passed"], 10)

                junit_root = ET.fromstring((out_dir / "A1_junit.xml").read_text(encoding="utf-8"))
                self.assertEqual(junit_root.attrib["tests"], "10")
                self.assertEqual(junit_root.attrib["failures"], "0")
                case_props = {
                    p.attrib["value"]
                    for p in junit_root.findall("./testcase/properties/property[@name='criterion_id']")
                }
                self.assertEqual(case_props, {f"A1-{i:02d}" for i in range(1, 11)})
            finally:
                adapter.close()

    def test_a2_positive_reference_passes_all_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = ReferenceA2Adapter(Path(tmp))
            try:
                report = run_case_evaluation("A2", adapter, code_commit=SAMPLE_COMMIT)
                self.assertEqual(report.exit_code, 0)
                self.assertEqual((report.passed, report.failed, report.errors, report.skipped), (10, 0, 0, 0))
            finally:
                adapter.close()

    def test_a3_positive_reference_passes_all_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = ReferenceA3Adapter(Path(tmp))
            try:
                report = run_case_evaluation("A3", adapter, code_commit=SAMPLE_COMMIT)
                self.assertEqual(report.exit_code, 0)
                self.assertEqual((report.passed, report.failed, report.errors, report.skipped), (10, 0, 0, 0))
            finally:
                adapter.close()

    def test_negative_fixtures_fail_exact_target_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            a1_bad = ReferenceA1Adapter(
                root / "a1",
                faults=FaultFlags(allow_empty_title=True, allow_invalid_status=True, lose_data_on_restart=True),
            )
            try:
                rep1 = run_case_evaluation("A1", a1_bad, code_commit=SAMPLE_COMMIT)
                failed1 = {c.criterion_id for c in rep1.criteria if c.status != "passed"}
                self.assertEqual(failed1, {"A1-05", "A1-07", "A1-09"})
                self.assertEqual(rep1.acceptance_passed, 7)
            finally:
                a1_bad.close()

            a2_bad = ReferenceA2Adapter(
                root / "a2",
                faults=FaultFlags(case_sensitive_tags=True, keep_orphan_links=True),
            )
            try:
                rep2 = run_case_evaluation("A2", a2_bad, code_commit=SAMPLE_COMMIT)
                failed2 = {c.criterion_id for c in rep2.criteria if c.status != "passed"}
                self.assertIn("A2-04", failed2)
                self.assertIn("A2-09", failed2)
            finally:
                a2_bad.close()

            a3_bad = ReferenceA3Adapter(
                root / "a3",
                faults=FaultFlags(allow_bad_quantity=True, allow_overdraft=True),
            )
            try:
                rep3 = run_case_evaluation("A3", a3_bad, code_commit=SAMPLE_COMMIT)
                failed3 = {c.criterion_id for c in rep3.criteria if c.status != "passed"}
                self.assertEqual(failed3, {"A3-05", "A3-06"})
                self.assertEqual(rep3.acceptance_passed, 8)
            finally:
                a3_bad.close()

    def test_build_failure_forces_zero_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = ReferenceA1Adapter(Path(tmp), faults=FaultFlags(build_fail=True))
            try:
                report = run_case_evaluation("A1", adapter, code_commit=SAMPLE_COMMIT)
                self.assertFalse(report.build_ok)
                self.assertEqual(report.passed, 0)
                self.assertEqual(report.acceptance_passed, 0)
                self.assertEqual(report.failed, 10)
                self.assertEqual(report.exit_code, 1)
            finally:
                adapter.close()

    def test_ui_criterion_never_inferred_from_backend_when_driver_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = ReferenceA1Adapter(Path(tmp), ui_driver=StrictMissingUIDriver("browser unavailable"))
            try:
                report = run_case_evaluation("A1", adapter, code_commit=SAMPLE_COMMIT)
                by_id = {c.criterion_id: c for c in report.criteria}
                self.assertEqual(by_id["A1-10"].status, "error")
                self.assertEqual(report.passed, 9)
                self.assertEqual(report.errors, 1)
                self.assertEqual(report.exit_code, 1)
            finally:
                adapter.close()

    def test_skipped_error_and_unexecuted_never_count_as_pass(self) -> None:
        outcomes = [
            CriterionOutcome("A1-01", "Tạo Task", "passed", 10),
            CriterionOutcome("A1-02", "Đọc danh sách", "skipped", 0, "skipped"),
            CriterionOutcome("A1-03", "Sửa thông tin", "error", 5, "boom"),
        ]
        manifest = compute_manifest()
        report = summarize_outcomes(
            case_id="A1",
            code_commit=SAMPLE_COMMIT,
            build_ok=True,
            build_message="ok",
            outcomes=outcomes,
            duration_ms=15,
            bundle_sha256=str(manifest["bundle_sha256"]),
        )
        self.assertEqual(report.passed, 1)
        self.assertEqual(report.skipped, 1)
        self.assertEqual(report.errors, 8)  # 1 explicit error + 7 not-run criteria
        self.assertEqual(report.acceptance_passed, 1)
        self.assertEqual(report.exit_code, 1)

    def test_checksum_manifest_verifies_and_detects_tampering(self) -> None:
        ok, mismatches = verify_manifest()
        self.assertTrue(ok, f"Checksum mismatches: {mismatches}")
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "checksums.json"
            data = compute_manifest()
            tampered_files = dict(data["files"])  # type: ignore[arg-type]
            tampered_files["A1.json"] = "0" * 64
            data["files"] = tampered_files
            fake.write_text(json.dumps(data), encoding="utf-8")
            bad_ok, bad_mismatches = verify_manifest(manifest_path=fake)
            self.assertFalse(bad_ok)
            self.assertTrue(any("A1.json" in m for m in bad_mismatches))


if __name__ == "__main__":
    unittest.main()
