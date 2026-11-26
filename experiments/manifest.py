"""Manifest schema and integrity validator for experiment runs (E03).

Validates every required field from Word section 5.4 and Issue #53 using Python
standard library only so E03 stays self-contained and easy to wire into I21/E04-E08.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


EXPERIMENTS_DIR = Path(__file__).resolve().parent
RUN_MATRIX_PATH = EXPERIMENTS_DIR / "run_matrix.json"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SAFE_URI_RE = re.compile(r"^[a-zA-Z0-9._:/-]+$")

VALID_CASES = frozenset({"A1", "A2", "A3"})
VALID_CONDITIONS = frozenset({"S", "M", "M_no_skill"})
VALID_SPLITS = frozenset({"pilot", "main", "ablation"})
VALID_FINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "needs_human_review", "pending_recovery"}
)

REQUIRED_FIELDS = (
    "run_id",
    "case_id",
    "condition",
    "repetition",
    "split",
    "system_commit",
    "model_id",
    "config_hash",
    "prompt_hash",
    "skill_hash",
    "tool_version",
    "start_time",
    "end_time",
    "approval_wait_seconds",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "usage_complete",
    "usage_note",
    "cost_usd",
    "cost_note",
    "repair_rounds",
    "manual_edits",
    "build_ok",
    "acceptance_passed",
    "acceptance_total",
    "final_status",
    "artifact_manifest_uri",
    "code_commit",
    "runner_report_uri",
)


class ManifestValidationError(ValueError):
    """Raised when a run manifest or dataset violates protocol rules."""


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    case_id: str
    condition: str
    repetition: int
    split: str
    system_commit: str
    model_id: str
    config_hash: str
    prompt_hash: str
    skill_hash: str
    tool_version: str
    start_time: str
    end_time: str
    approval_wait_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    usage_complete: bool
    usage_note: str
    cost_usd: float | None
    cost_note: str
    repair_rounds: int
    manual_edits: int
    build_ok: bool
    acceptance_passed: int
    acceptance_total: int
    final_status: str
    artifact_manifest_uri: str
    code_commit: str | None
    runner_report_uri: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_run_matrix(path: Path = RUN_MATRIX_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{name} must be a non-empty string")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _require_optional_int(value: Any, name: str, *, minimum: int = 0) -> int | None:
    if value is None:
        return None
    return _require_int(value, name, minimum=minimum)


def _require_non_negative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ManifestValidationError(f"{name} must be a number >= 0")
    return float(value)


def _validate_safe_uri(value: Any, name: str) -> str:
    uri = _require_non_empty_str(value, name)
    if uri.startswith("/") or uri.startswith("\\") or ".." in uri.split("/"):
        raise ManifestValidationError(f"{name} must not use absolute host paths or parent traversal: {uri!r}")
    if re.match(r"^[a-zA-Z]:\\", uri) or re.match(r"^[a-zA-Z]:/", uri):
        raise ManifestValidationError(f"{name} must not use drive-letter host paths: {uri!r}")
    if not SAFE_URI_RE.match(uri):
        raise ManifestValidationError(f"{name} contains disallowed characters: {uri!r}")
    return uri


def _parse_iso(value: Any, name: str) -> datetime:
    text = _require_non_empty_str(value, name)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError(f"{name} must be valid ISO-8601 timestamp: {text!r}") from exc
    if dt.tzinfo is None:
        raise ManifestValidationError(f"{name} must include timezone offset or 'Z'")
    return dt


def validate_manifest(raw: dict[str, Any]) -> RunManifest:
    if not isinstance(raw, dict):
        raise ManifestValidationError("manifest payload must be a JSON object")

    missing = [key for key in REQUIRED_FIELDS if key not in raw]
    if missing:
        raise ManifestValidationError(f"missing required fields: {', '.join(missing)}")
    extra = sorted(set(raw.keys()) - set(REQUIRED_FIELDS))
    if extra:
        raise ManifestValidationError(f"unexpected fields not allowed: {', '.join(extra)}")

    run_id = _require_non_empty_str(raw["run_id"], "run_id")
    case_id = _require_non_empty_str(raw["case_id"], "case_id")
    if case_id not in VALID_CASES:
        raise ManifestValidationError(f"invalid case_id: {case_id!r}")

    condition = _require_non_empty_str(raw["condition"], "condition")
    if condition not in VALID_CONDITIONS:
        raise ManifestValidationError(f"invalid condition: {condition!r}")

    split = _require_non_empty_str(raw["split"], "split")
    if split not in VALID_SPLITS:
        raise ManifestValidationError(f"invalid split: {split!r}")
    if split == "main" and condition not in {"S", "M"}:
        raise ManifestValidationError("main split only allows conditions S or M")
    if split == "ablation" and (condition != "M_no_skill" or case_id != "A3"):
        raise ManifestValidationError("ablation split is restricted to M_no_skill on A3 per protocol")

    repetition = _require_int(raw["repetition"], "repetition", minimum=1)
    if repetition > 3:
        raise ManifestValidationError("repetition must be in 1..3")

    system_commit = _require_non_empty_str(raw["system_commit"], "system_commit")
    if not COMMIT_RE.match(system_commit):
        raise ManifestValidationError("system_commit must be a 40- or 64-char hex hash")

    model_id = _require_non_empty_str(raw["model_id"], "model_id")
    for hash_field in ("config_hash", "prompt_hash", "skill_hash"):
        hv = _require_non_empty_str(raw[hash_field], hash_field)
        if not SHA256_RE.match(hv):
            raise ManifestValidationError(f"{hash_field} must be a 64-char lowercase hex SHA-256")
    tool_version = _require_non_empty_str(raw["tool_version"], "tool_version")

    start_dt = _parse_iso(raw["start_time"], "start_time")
    end_dt = _parse_iso(raw["end_time"], "end_time")
    total_seconds = (end_dt - start_dt).total_seconds()
    if total_seconds < 0:
        raise ManifestValidationError("end_time must be >= start_time")

    approval_wait_seconds = _require_non_negative_number(raw["approval_wait_seconds"], "approval_wait_seconds")
    if approval_wait_seconds > total_seconds + 1e-6:
        raise ManifestValidationError("approval_wait_seconds cannot exceed total run duration")

    if not isinstance(raw["usage_complete"], bool):
        raise ManifestValidationError("usage_complete must be a boolean")
    usage_complete = raw["usage_complete"]
    input_tokens = _require_optional_int(raw["input_tokens"], "input_tokens", minimum=0)
    output_tokens = _require_optional_int(raw["output_tokens"], "output_tokens", minimum=0)
    cached_tokens = _require_optional_int(raw["cached_tokens"], "cached_tokens", minimum=0)
    usage_note = raw["usage_note"]
    if not isinstance(usage_note, str):
        raise ManifestValidationError("usage_note must be a string")
    if usage_complete:
        if input_tokens is None or output_tokens is None:
            raise ManifestValidationError("usage_complete=True requires non-null input_tokens and output_tokens")
    elif not usage_note.strip():
        raise ManifestValidationError("usage_complete=False requires a non-empty usage_note explaining missing usage")

    cost_raw = raw["cost_usd"]
    cost_usd = None if cost_raw is None else _require_non_negative_number(cost_raw, "cost_usd")
    cost_note = raw["cost_note"]
    if not isinstance(cost_note, str):
        raise ManifestValidationError("cost_note must be a string")
    if cost_usd is None and not cost_note.strip():
        raise ManifestValidationError("cost_usd=None requires a non-empty cost_note (e.g. Antigravity CLI subscription)")

    repair_rounds = _require_int(raw["repair_rounds"], "repair_rounds", minimum=0)
    manual_edits = _require_int(raw["manual_edits"], "manual_edits", minimum=0)

    if not isinstance(raw["build_ok"], bool):
        raise ManifestValidationError("build_ok must be a boolean")
    build_ok = raw["build_ok"]

    acceptance_total = _require_int(raw["acceptance_total"], "acceptance_total", minimum=1)
    if acceptance_total != 10:
        raise ManifestValidationError("acceptance_total must be 10 for A1, A2, and A3")
    acceptance_passed = _require_int(raw["acceptance_passed"], "acceptance_passed", minimum=0)
    if acceptance_passed > acceptance_total:
        raise ManifestValidationError("acceptance_passed cannot exceed acceptance_total")
    if not build_ok and acceptance_passed != 0:
        raise ManifestValidationError("build_ok=False requires acceptance_passed=0 (build fail = 0 pass)")

    final_status = _require_non_empty_str(raw["final_status"], "final_status")
    if final_status not in VALID_FINAL_STATUSES:
        raise ManifestValidationError(f"invalid final_status: {final_status!r}")

    artifact_manifest_uri = _validate_safe_uri(raw["artifact_manifest_uri"], "artifact_manifest_uri")
    runner_report_uri = _validate_safe_uri(raw["runner_report_uri"], "runner_report_uri")

    code_commit = raw["code_commit"]
    if code_commit is not None:
        code_commit = _require_non_empty_str(code_commit, "code_commit")
        if not COMMIT_RE.match(code_commit):
            raise ManifestValidationError("code_commit must be null or a 40-/64-char hex commit hash")
    elif build_ok:
        raise ManifestValidationError("build_ok=True requires a non-null code_commit")

    return RunManifest(
        run_id=run_id,
        case_id=case_id,
        condition=condition,
        repetition=repetition,
        split=split,
        system_commit=system_commit,
        model_id=model_id,
        config_hash=raw["config_hash"],
        prompt_hash=raw["prompt_hash"],
        skill_hash=raw["skill_hash"],
        tool_version=tool_version,
        start_time=raw["start_time"],
        end_time=raw["end_time"],
        approval_wait_seconds=approval_wait_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        usage_complete=usage_complete,
        usage_note=usage_note,
        cost_usd=cost_usd,
        cost_note=cost_note,
        repair_rounds=repair_rounds,
        manual_edits=manual_edits,
        build_ok=build_ok,
        acceptance_passed=acceptance_passed,
        acceptance_total=acceptance_total,
        final_status=final_status,
        artifact_manifest_uri=artifact_manifest_uri,
        code_commit=code_commit,
        runner_report_uri=runner_report_uri,
    )


def is_automated_success(manifest: RunManifest) -> bool:
    """Manual code edits disqualify a run from automated completion credit (Word 5.2-5.3)."""
    return (
        manifest.build_ok
        and manifest.acceptance_passed == manifest.acceptance_total
        and manifest.manual_edits == 0
        and manifest.final_status == "completed"
    )


def validate_dataset_manifests(
    manifests: list[RunManifest],
    *,
    require_complete_main: bool = False,
) -> dict[str, list[RunManifest]]:
    """Group validated manifests by split, ensuring strict isolation and no duplicate run IDs."""
    seen_ids: set[str] = set()
    grouped: dict[str, list[RunManifest]] = {"pilot": [], "main": [], "ablation": []}
    seen_slots: set[tuple[str, str, str, int]] = set()

    for m in manifests:
        if m.run_id in seen_ids:
            raise ManifestValidationError(f"duplicate run_id: {m.run_id}")
        seen_ids.add(m.run_id)
        slot = (m.split, m.case_id, m.condition, m.repetition)
        if slot in seen_slots:
            raise ManifestValidationError(f"duplicate experiment matrix slot: {slot}")
        seen_slots.add(slot)
        grouped[m.split].append(m)

    if require_complete_main:
        expected_main = {
            ("main", case, cond, rep)
            for case in ("A1", "A2", "A3")
            for cond in ("S", "M")
            for rep in (1, 2, 3)
        }
        actual_main = {(m.split, m.case_id, m.condition, m.repetition) for m in grouped["main"]}
        missing = sorted(expected_main - actual_main)
        if missing:
            raise ManifestValidationError(f"main dataset is incomplete; missing {len(missing)} runs: {missing[:3]}")

    return grouped
