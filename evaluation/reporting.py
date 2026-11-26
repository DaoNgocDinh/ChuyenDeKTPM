"""Deterministic JUnit XML and JSON report generation for E01 acceptance runs.

Scoring discipline (P01, Word 5.3, Issue #51):
- build_ok == False forces 0 passed across all 10 criteria.
- skipped, error, or not_run NEVER count toward passed / acceptance_passed.
- Every report binds criterion_id, code_commit, case_id, and evaluation checksums.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from evaluation.adapters import AppAdapter
from evaluation.checksums import compute_manifest
from evaluation.suites import load_case_spec, run_criteria_for_case


OutcomeStatus = Literal["passed", "failed", "error", "skipped"]
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


@dataclass(frozen=True)
class CriterionOutcome:
    criterion_id: str
    title: str
    status: OutcomeStatus
    duration_ms: int
    message: str = ""


@dataclass(frozen=True)
class EvaluationReport:
    case_id: str
    code_commit: str
    suite_id: str
    build_ok: bool
    build_message: str
    exit_code: int
    passed: int
    failed: int
    errors: int
    skipped: int
    acceptance_passed: int
    acceptance_total: int
    duration_ms: int
    suite_bundle_sha256: str
    criteria: tuple[CriterionOutcome, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["criteria"] = [asdict(item) for item in self.criteria]
        return payload

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def write_junit_xml(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        suite = ET.Element(
            "testsuite",
            name=self.suite_id,
            tests=str(self.acceptance_total),
            failures=str(self.failed),
            errors=str(self.errors),
            skipped=str(self.skipped),
            time=f"{self.duration_ms / 1000:.3f}",
        )
        props = ET.SubElement(suite, "properties")
        for key, value in (
            ("case_id", self.case_id),
            ("code_commit", self.code_commit),
            ("build_ok", str(self.build_ok).lower()),
            ("suite_bundle_sha256", self.suite_bundle_sha256),
        ):
            ET.SubElement(props, "property", name=key, value=value)

        for item in self.criteria:
            case_el = ET.SubElement(
                suite,
                "testcase",
                classname=f"evaluation.{self.case_id}",
                name=item.criterion_id,
                time=f"{item.duration_ms / 1000:.3f}",
            )
            case_props = ET.SubElement(case_el, "properties")
            ET.SubElement(case_props, "property", name="criterion_id", value=item.criterion_id)
            ET.SubElement(case_props, "property", name="code_commit", value=self.code_commit)
            if item.status == "failed":
                ET.SubElement(case_el, "failure", message=item.message or "criterion failed")
            elif item.status == "error":
                ET.SubElement(case_el, "error", message=item.message or "criterion error")
            elif item.status == "skipped":
                ET.SubElement(case_el, "skipped", message=item.message or "criterion skipped")

        ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
        return path


def summarize_outcomes(
    *,
    case_id: str,
    code_commit: str,
    build_ok: bool,
    build_message: str,
    outcomes: list[CriterionOutcome],
    duration_ms: int,
    bundle_sha256: str,
) -> EvaluationReport:
    if not COMMIT_RE.match(code_commit):
        raise ValueError(f"code_commit must be a 40- or 64-char lowercase hex commit hash, got: {code_commit!r}")
    spec = load_case_spec(case_id)
    expected_ids = [c["id"] for c in spec["criteria"]]
    if len(expected_ids) != 10:
        raise ValueError(f"{case_id} must define exactly 10 criteria")

    if not build_ok:
        forced = tuple(
            CriterionOutcome(
                criterion_id=c["id"],
                title=c["title"],
                status="failed",
                duration_ms=0,
                message=f"build_failed: {build_message or 'application failed to build'}",
            )
            for c in spec["criteria"]
        )
        return EvaluationReport(
            case_id=case_id,
            code_commit=code_commit,
            suite_id=f"evaluation.{case_id}",
            build_ok=False,
            build_message=build_message,
            exit_code=1,
            passed=0,
            failed=len(forced),
            errors=0,
            skipped=0,
            acceptance_passed=0,
            acceptance_total=len(forced),
            duration_ms=duration_ms,
            suite_bundle_sha256=bundle_sha256,
            criteria=forced,
        )

    outcome_by_id = {o.criterion_id: o for o in outcomes}
    ordered: list[CriterionOutcome] = []
    for c in spec["criteria"]:
        cid = c["id"]
        if cid in outcome_by_id:
            ordered.append(outcome_by_id[cid])
        else:
            ordered.append(
                CriterionOutcome(
                    criterion_id=cid,
                    title=c["title"],
                    status="error",
                    duration_ms=0,
                    message="criterion did not execute (not_run never counts as pass)",
                )
            )

    passed = sum(1 for o in ordered if o.status == "passed")
    failed = sum(1 for o in ordered if o.status == "failed")
    errors = sum(1 for o in ordered if o.status == "error")
    skipped = sum(1 for o in ordered if o.status == "skipped")
    exit_code = 0 if (passed == len(ordered) and failed == 0 and errors == 0 and skipped == 0) else 1

    return EvaluationReport(
        case_id=case_id,
        code_commit=code_commit,
        suite_id=f"evaluation.{case_id}",
        build_ok=True,
        build_message=build_message,
        exit_code=exit_code,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        acceptance_passed=passed,
        acceptance_total=len(ordered),
        duration_ms=duration_ms,
        suite_bundle_sha256=bundle_sha256,
        criteria=tuple(ordered),
    )


def run_case_evaluation(
    case_id: str,
    adapter: AppAdapter,
    *,
    code_commit: str,
    output_dir: Path | None = None,
) -> EvaluationReport:
    if adapter.case_id != case_id:
        raise ValueError(f"Adapter case_id {adapter.case_id!r} does not match {case_id!r}")
    start = time.monotonic()
    manifest = compute_manifest()
    build_ok, build_message = adapter.build_check()
    outcomes: list[CriterionOutcome] = []
    if build_ok:
        raw_outcomes = run_criteria_for_case(case_id, adapter)
        outcomes = [
            CriterionOutcome(
                criterion_id=item["criterion_id"],
                title=item["title"],
                status=item["status"],
                duration_ms=item["duration_ms"],
                message=item["message"],
            )
            for item in raw_outcomes
        ]
    elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
    report = summarize_outcomes(
        case_id=case_id,
        code_commit=code_commit,
        build_ok=build_ok,
        build_message=build_message,
        outcomes=outcomes,
        duration_ms=elapsed_ms,
        bundle_sha256=str(manifest["bundle_sha256"]),
    )
    if output_dir is not None:
        report.write_json(output_dir / f"{case_id}_report.json")
        report.write_junit_xml(output_dir / f"{case_id}_junit.xml")
    return report
