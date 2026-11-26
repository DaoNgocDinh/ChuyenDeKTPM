"""SUPPORT MODULE (draft prior to E05/E06/V02) for reproducible E07 tables & CSV export.

Reads raw manifest JSON files from a directory, validates every file with E03's
strict schema, and produces Markdown (Word section 5.6 layout) and CSV outputs
traceable back to individual run_ids.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from experiments.manifest import RunManifest, validate_dataset_manifests, validate_manifest
from experiments.metrics import DistributionSummary, GroupMetrics, compute_all_groups


def load_manifests_from_dir(directory: Path) -> list[RunManifest]:
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No manifest JSON files found in {directory}")
    manifests = [validate_manifest(json.loads(p.read_text(encoding="utf-8"))) for p in files]
    validate_dataset_manifests(manifests, require_complete_main=False)
    return manifests


def _fmt_dist(dist: DistributionSummary, unit: str) -> str:
    if dist.count == 0 or dist.median is None:
        return "không áp dụng"
    return f"med {dist.median:.1f}{unit} ({dist.minimum:.1f}–{dist.maximum:.1f}{unit})"


def _fmt_cost(group: GroupMetrics) -> str:
    if group.cost_usd_summary.count == 0:
        return f"N/A (CLI, {len(group.cost_missing_run_ids)}/{group.total_runs} run không báo giá USD)"
    base = _fmt_dist(group.cost_usd_summary, " USD")
    if group.cost_missing_run_ids:
        return f"{base}; thiếu giá ở {', '.join(group.cost_missing_run_ids)}"
    return base


def render_word_56_markdown(groups: list[GroupMetrics], *, split: str = "main") -> str:
    """Render Markdown table matching Word section 5.6 (S and M on separate rows per case)."""
    selected = [g for g in groups if g.split == split]
    lines = [
        f"### Bảng kết quả ({split}) — tái tính từ dữ liệu manifest thô",
        "",
        "| Bài | Cấu hình | Đạt toàn bộ | Tiêu chí đạt | Build đạt | Thời gian tự động & Chi phí | Truy nguồn (`run_id`) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for g in selected:
        time_str = _fmt_dist(g.auto_duration_seconds, "s")
        cost_str = _fmt_cost(g)
        usage_flag = f"; thiếu usage: {', '.join(g.missing_usage_run_ids)}" if g.missing_usage_run_ids else ""
        lines.append(
            f"| {g.case_id} | {g.condition} | {g.automated_complete_runs}/{g.total_runs} "
            f"| {g.criteria_passed}/{g.criteria_total} | {g.build_ok_runs}/{g.total_runs} "
            f"| {time_str}; {cost_str}{usage_flag} | {', '.join(g.run_ids)} |"
        )
    return "\n".join(lines) + "\n"


def write_summary_csv(groups: list[GroupMetrics], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "split",
        "case_id",
        "condition",
        "total_runs",
        "automated_complete_runs",
        "build_ok_runs",
        "criteria_passed",
        "criteria_total",
        "auto_duration_median_s",
        "auto_duration_min_s",
        "auto_duration_max_s",
        "approval_wait_median_s",
        "total_input_tokens",
        "total_output_tokens",
        "total_cached_tokens",
        "missing_usage_run_ids",
        "cost_usd_total",
        "cost_missing_run_ids",
        "total_repair_rounds",
        "repair_success_label",
        "manual_edit_runs",
        "run_ids",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for g in groups:
            writer.writerow(
                {
                    "split": g.split,
                    "case_id": g.case_id,
                    "condition": g.condition,
                    "total_runs": g.total_runs,
                    "automated_complete_runs": g.automated_complete_runs,
                    "build_ok_runs": g.build_ok_runs,
                    "criteria_passed": g.criteria_passed,
                    "criteria_total": g.criteria_total,
                    "auto_duration_median_s": g.auto_duration_seconds.median,
                    "auto_duration_min_s": g.auto_duration_seconds.minimum,
                    "auto_duration_max_s": g.auto_duration_seconds.maximum,
                    "approval_wait_median_s": g.approval_wait_seconds.median,
                    "total_input_tokens": g.total_input_tokens,
                    "total_output_tokens": g.total_output_tokens,
                    "total_cached_tokens": g.total_cached_tokens,
                    "missing_usage_run_ids": ";".join(g.missing_usage_run_ids),
                    "cost_usd_total": g.cost_usd_total,
                    "cost_missing_run_ids": ";".join(g.cost_missing_run_ids),
                    "total_repair_rounds": g.total_repair_rounds,
                    "repair_success_label": g.repair_success_label,
                    "manual_edit_runs": g.manual_edit_runs,
                    "run_ids": ";".join(g.run_ids),
                }
            )
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python -m experiments.tables <manifests_dir> [output_csv]", file=sys.stderr)
        return 2
    manifests = load_manifests_from_dir(Path(argv[1]))
    groups = compute_all_groups(manifests)
    print(render_word_56_markdown(groups, split="main"))
    if len(argv) >= 3:
        write_summary_csv(groups, Path(argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
