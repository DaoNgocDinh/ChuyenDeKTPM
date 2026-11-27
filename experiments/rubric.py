"""SUPPORT MODULE (draft prior to E05/E06) for artifact quality rubric 0/1/2 (E07).

Supports blind scoring (hiding S vs M labels while the researcher scores artifacts)
and deterministic unmasking back to (case_id, condition, run_id).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass


RUBRIC_DIMENSIONS = ("requirements", "design", "plan", "test_evidence")


@dataclass(frozen=True)
class BlindRubricItem:
    blind_id: str
    case_id: str
    artifact_refs: dict[str, str]


@dataclass(frozen=True)
class RubricScore:
    run_id: str
    case_id: str
    condition: str
    requirements: int
    design: int
    plan: int
    test_evidence: int
    notes: str = ""

    def __post_init__(self) -> None:
        for dim in RUBRIC_DIMENSIONS:
            val = getattr(self, dim)
            if isinstance(val, bool) or not isinstance(val, int) or val not in (0, 1, 2):
                raise ValueError(f"Rubric score for {dim} must be 0, 1, or 2; got {val!r}")

    @property
    def total(self) -> int:
        return self.requirements + self.design + self.plan + self.test_evidence

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["total"] = self.total
        return data


def create_blind_scoring_sheet(
    entries: list[dict[str, object]],
    *,
    salt: str = "blind-rubric-v1",
) -> tuple[list[BlindRubricItem], dict[str, tuple[str, str, str]]]:
    """Generate condition-blind IDs for scoring without revealing S vs M labels.

    Returns (blind_sheet, key_map) where key_map[blind_id] = (run_id, case_id, condition).
    """
    keyed: list[tuple[str, dict[str, object]]] = []
    for entry in entries:
        run_id = str(entry["run_id"])
        digest = hashlib.sha256(f"{salt}:{run_id}".encode("utf-8")).hexdigest()
        keyed.append((digest, entry))
    keyed.sort(key=lambda pair: pair[0])

    sheet: list[BlindRubricItem] = []
    key_map: dict[str, tuple[str, str, str]] = {}
    for index, (_, entry) in enumerate(keyed, start=1):
        blind_id = f"BLIND-{index:03d}"
        run_id = str(entry["run_id"])
        case_id = str(entry["case_id"])
        condition = str(entry["condition"])
        refs = dict(entry.get("artifact_refs", {}))  # type: ignore[arg-type]
        sheet.append(BlindRubricItem(blind_id=blind_id, case_id=case_id, artifact_refs=refs))
        key_map[blind_id] = (run_id, case_id, condition)
    return sheet, key_map


def unmask_blind_scores(
    blind_scores: list[dict[str, object]],
    key_map: dict[str, tuple[str, str, str]],
) -> list[RubricScore]:
    out: list[RubricScore] = []
    for item in blind_scores:
        bid = str(item["blind_id"])
        if bid not in key_map:
            raise KeyError(f"Unknown blind_id: {bid}")
        run_id, case_id, condition = key_map[bid]
        out.append(
            RubricScore(
                run_id=run_id,
                case_id=case_id,
                condition=condition,
                requirements=int(item["requirements"]),
                design=int(item["design"]),
                plan=int(item["plan"]),
                test_evidence=int(item["test_evidence"]),
                notes=str(item.get("notes", "")),
            )
        )
    return out


def summarize_rubric(scores: list[RubricScore]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], list[RubricScore]] = {}
    for s in scores:
        buckets.setdefault((s.case_id, s.condition), []).append(s)
    rows: list[dict[str, object]] = []
    for (case_id, condition), group in sorted(buckets.items()):
        n = len(group)
        row: dict[str, object] = {
            "case_id": case_id,
            "condition": condition,
            "run_ids": [s.run_id for s in sorted(group, key=lambda x: x.run_id)],
            "count": n,
            "mean_total_out_of_8": round(sum(s.total for s in group) / n, 2),
        }
        for dim in RUBRIC_DIMENSIONS:
            row[f"mean_{dim}"] = round(sum(getattr(s, dim) for s in group) / n, 2)
        rows.append(row)
    return rows
