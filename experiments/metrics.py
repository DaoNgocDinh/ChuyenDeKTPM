"""SUPPORT MODULE (draft prior to E05/E06/V02) for E07 metric computation.

Computes all metrics specified in Word section 5.3 and Issue #57 strictly from
raw validated RunManifest records and optional execution audit metrics.
Never fabricates missing measurements or omits failed runs from denominators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from typing import Iterable

from experiments.manifest import RunManifest, is_automated_success


@dataclass(frozen=True)
class RunExecutionCounters:
    """Optional fine-grained counters collected from runner/audit logs per run."""

    run_id: str
    fixed_tests_passed: int = 0
    fixed_tests_total: int = 0
    bugs_confirmed: int = 0
    bugs_fixed_with_regression: int = 0
    trace_criteria_linked: int = 0
    trace_criteria_total: int = 0
    handoffs_invalid: int = 0
    handoffs_total: int = 0
    tool_calls_failed: int = 0
    tool_calls_total: int = 0
    human_clarifications: int = 0
    human_approvals: int = 0
    human_blocker_interventions: int = 0


@dataclass(frozen=True)
class DistributionSummary:
    median: float | None
    minimum: float | None
    maximum: float | None
    count: int


@dataclass(frozen=True)
class GroupMetrics:
    split: str
    case_id: str
    condition: str
    run_ids: tuple[str, ...]
    total_runs: int
    automated_complete_runs: int
    build_ok_runs: int
    criteria_passed: int
    criteria_total: int
    fixed_tests_passed: int
    fixed_tests_total: int
    auto_duration_seconds: DistributionSummary
    approval_wait_seconds: DistributionSummary
    total_duration_seconds: DistributionSummary
    total_input_tokens: int
    total_output_tokens: int
    total_cached_tokens: int
    missing_usage_run_ids: tuple[str, ...]
    cost_usd_summary: DistributionSummary
    cost_usd_total: float | None
    cost_missing_run_ids: tuple[str, ...]
    total_repair_rounds: int
    bugs_confirmed: int
    bugs_fixed_with_regression: int
    repair_success_label: str
    trace_criteria_linked: int
    trace_criteria_total: int
    handoffs_invalid: int
    handoffs_total: int
    tool_calls_failed: int
    tool_calls_total: int
    manual_edit_runs: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_total_seconds(manifest: RunManifest) -> float:
    start = datetime.fromisoformat(manifest.start_time.replace("Z", "+00:00"))
    end = datetime.fromisoformat(manifest.end_time.replace("Z", "+00:00"))
    return max(0.0, (end - start).total_seconds())


def run_automated_seconds(manifest: RunManifest) -> float:
    return max(0.0, run_total_seconds(manifest) - manifest.approval_wait_seconds)


def summarize_distribution(values: list[float]) -> DistributionSummary:
    if not values:
        return DistributionSummary(median=None, minimum=None, maximum=None, count=0)
    return DistributionSummary(
        median=round(float(median(values)), 3),
        minimum=round(float(min(values)), 3),
        maximum=round(float(max(values)), 3),
        count=len(values),
    )


def format_ratio(numerator: int, denominator: int) -> str:
    """Per Issue #57: zero denominator MUST report 'không áp dụng' rather than 0% or crash."""
    if denominator == 0:
        return "không áp dụng"
    pct = (numerator / denominator) * 100.0
    return f"{numerator}/{denominator} ({pct:.1f}%)"


def aggregate_group(
    manifests: list[RunManifest],
    counters_by_run: dict[str, RunExecutionCounters] | None = None,
) -> GroupMetrics:
    if not manifests:
        raise ValueError("Cannot aggregate an empty group of manifests")
    first = manifests[0]
    for m in manifests[1:]:
        if (m.split, m.case_id, m.condition) != (first.split, first.case_id, first.condition):
            raise ValueError("All manifests in a group must share (split, case_id, condition)")

    counters = counters_by_run or {}
    sorted_runs = sorted(manifests, key=lambda m: (m.repetition, m.run_id))

    auto_secs = [run_automated_seconds(m) for m in sorted_runs]
    wait_secs = [float(m.approval_wait_seconds) for m in sorted_runs]
    total_secs = [run_total_seconds(m) for m in sorted_runs]

    missing_usage = tuple(m.run_id for m in sorted_runs if not m.usage_complete)
    cost_values = [float(m.cost_usd) for m in sorted_runs if m.cost_usd is not None]
    cost_missing = tuple(m.run_id for m in sorted_runs if m.cost_usd is None)

    bugs_confirmed = sum(counters[m.run_id].bugs_confirmed for m in sorted_runs if m.run_id in counters)
    bugs_fixed = sum(
        counters[m.run_id].bugs_fixed_with_regression for m in sorted_runs if m.run_id in counters
    )

    return GroupMetrics(
        split=first.split,
        case_id=first.case_id,
        condition=first.condition,
        run_ids=tuple(m.run_id for m in sorted_runs),
        total_runs=len(sorted_runs),
        automated_complete_runs=sum(1 for m in sorted_runs if is_automated_success(m)),
        build_ok_runs=sum(1 for m in sorted_runs if m.build_ok),
        criteria_passed=sum(m.acceptance_passed for m in sorted_runs),
        criteria_total=sum(m.acceptance_total for m in sorted_runs),
        fixed_tests_passed=sum(
            counters[m.run_id].fixed_tests_passed for m in sorted_runs if m.run_id in counters
        ),
        fixed_tests_total=sum(
            counters[m.run_id].fixed_tests_total for m in sorted_runs if m.run_id in counters
        ),
        auto_duration_seconds=summarize_distribution(auto_secs),
        approval_wait_seconds=summarize_distribution(wait_secs),
        total_duration_seconds=summarize_distribution(total_secs),
        total_input_tokens=sum(m.input_tokens or 0 for m in sorted_runs),
        total_output_tokens=sum(m.output_tokens or 0 for m in sorted_runs),
        total_cached_tokens=sum(m.cached_tokens or 0 for m in sorted_runs),
        missing_usage_run_ids=missing_usage,
        cost_usd_summary=summarize_distribution(cost_values),
        cost_usd_total=round(sum(cost_values), 6) if cost_values else None,
        cost_missing_run_ids=cost_missing,
        total_repair_rounds=sum(m.repair_rounds for m in sorted_runs),
        bugs_confirmed=bugs_confirmed,
        bugs_fixed_with_regression=bugs_fixed,
        repair_success_label=format_ratio(bugs_fixed, bugs_confirmed),
        trace_criteria_linked=sum(
            counters[m.run_id].trace_criteria_linked for m in sorted_runs if m.run_id in counters
        ),
        trace_criteria_total=sum(
            counters[m.run_id].trace_criteria_total for m in sorted_runs if m.run_id in counters
        ),
        handoffs_invalid=sum(
            counters[m.run_id].handoffs_invalid for m in sorted_runs if m.run_id in counters
        ),
        handoffs_total=sum(
            counters[m.run_id].handoffs_total for m in sorted_runs if m.run_id in counters
        ),
        tool_calls_failed=sum(
            counters[m.run_id].tool_calls_failed for m in sorted_runs if m.run_id in counters
        ),
        tool_calls_total=sum(
            counters[m.run_id].tool_calls_total for m in sorted_runs if m.run_id in counters
        ),
        manual_edit_runs=sum(1 for m in sorted_runs if m.manual_edits > 0),
    )


def compute_all_groups(
    manifests: Iterable[RunManifest],
    counters_by_run: dict[str, RunExecutionCounters] | None = None,
) -> list[GroupMetrics]:
    """Group by (split, case_id, condition), strictly isolating pilot/main/ablation."""
    buckets: dict[tuple[str, str, str], list[RunManifest]] = {}
    for m in manifests:
        buckets.setdefault((m.split, m.case_id, m.condition), []).append(m)

    split_order = {"pilot": 0, "main": 1, "ablation": 2}
    cond_order = {"S": 0, "M": 1, "M_no_skill": 2}
    ordered_keys = sorted(
        buckets.keys(),
        key=lambda k: (split_order.get(k[0], 9), k[1], cond_order.get(k[2], 9)),
    )
    return [aggregate_group(buckets[k], counters_by_run) for k in ordered_keys]
