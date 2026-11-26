"""SUPPORT MODULE (draft prior to I06 Orchestrator) for I07 approval gates & change impact.

Implements Gate 1 (requirements) and atomic Gate 2 (architecture + plan),
stale-approval conflict checks, clarification binding, and downstream invalidation
directly on top of I02 Database, I03 ArtifactStore, D07 contracts, and D08 lifecycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from backend.contracts import ArtifactRef
from backend.lifecycle import RunState, run_transition
from backend.storage import Database, StorageConflict, encode


GATE_KINDS = {
    "requirements": ("requirements",),
    "architecture_plan": ("architecture", "plan"),
}


class ApprovalVersionConflict(StorageConflict):
    """Raised when an approval or clarification targets a stale or mismatched artifact."""

    code = "approval_version_conflict"


class InvalidGateTransition(ValueError):
    """Raised when a gate action is attempted outside a valid lifecycle state."""

    code = "invalid_transition"


@dataclass(frozen=True)
class GateDecisionResult:
    run_id: str
    gate: str
    decision: str
    approval_ids: tuple[str, ...]
    next_status: str
    route_to: str | None
    stale_artifact_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChangeImpact:
    run_id: str
    trigger_artifact: ArtifactRef
    stale_artifact_ids: tuple[str, ...]
    affected_task_ids: tuple[str, ...]


class ApprovalService:
    """Host-owned approval gate service ready to be wired into I06 (Orchestrator) and I22 (API)."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def open_gate(
        self,
        project_id: str,
        run_id: str,
        lease: str,
        gate: str,
        artifact_refs: list[ArtifactRef],
        *,
        questions: list[str] | None = None,
    ) -> str:
        expected_kinds = GATE_KINDS.get(gate)
        if expected_kinds is None:
            raise ValueError(f"Unknown approval gate: {gate!r}")
        if len(artifact_refs) != len(expected_kinds):
            raise ValueError(f"Gate {gate} requires exactly {len(expected_kinds)} artifact(s)")

        with self.database.transaction(write=True) as repo:
            run = repo.get_run(project_id, run_id)
            writer = repo.worker_run(project_id, run_id, lease)
            self._verify_gate_refs(writer, run_id, gate, artifact_refs)
            next_state = run_transition(RunState(run["status"]), "request_approval")

            checkpoint = json.loads(run["checkpoint_json"]) if run["checkpoint_json"] else {}
            checkpoint["pending_gate"] = {
                "gate": gate,
                "artifacts": [ref.model_dump(mode="json") for ref in artifact_refs],
            }
            checkpoint.pop("pending_questions", None)
            if questions:
                if gate != "requirements":
                    raise ValueError("Only requirements can request clarification")
                checkpoint["pending_questions"] = {f"Q{i}": text for i, text in enumerate(questions, 1)}
            repo._db.execute(
                "UPDATE runs SET status=?, checkpoint_json=?, worker_lease=NULL, lease_expires_at=NULL "
                "WHERE id=? AND status='running'",
                (next_state.value, encode(checkpoint), run_id),
            )
            writer.add_event(
                "gate.opened",
                {
                    "gate": gate,
                    "artifacts": [ref.model_dump(mode="json") for ref in artifact_refs],
                },
            )
            return next_state.value

    def decide_gate(
        self,
        project_id: str,
        run_id: str,
        gate: str,
        artifact_refs: list[ArtifactRef],
        decision: str,
        comment: str = "",
        *,
        revision_target: str | None = None,
    ) -> GateDecisionResult:
        if gate not in GATE_KINDS:
            raise ValueError(f"Unknown approval gate: {gate!r}")
        if decision not in {"approve", "request_changes"}:
            raise ValueError(f"Unsupported decision: {decision!r}")
        if decision == "request_changes" and not comment.strip():
            raise ValueError("Comment is required when requesting changes")

        with self.database.transaction(write=True) as repo:
            run = repo.get_run(project_id, run_id)
            if run["status"] != RunState.WAITING.value:
                raise InvalidGateTransition(
                    f"invalid_transition: run status is {run['status']}, expected waiting_approval"
                )
            checkpoint = json.loads(run["checkpoint_json"]) if run["checkpoint_json"] else {}
            pending = checkpoint.get("pending_gate")
            if not pending or pending.get("gate") != gate:
                raise InvalidGateTransition(f"invalid_transition: run is not waiting at gate {gate}")
            if decision == "approve" and gate == "requirements" and checkpoint.get("pending_questions"):
                raise InvalidGateTransition("Requirements are waiting for clarification")

            reader = repo.for_run(project_id, run_id)
            self._verify_gate_refs(reader, run_id, gate, artifact_refs)

            expected_set = {
                (item["artifact_id"], item["version"], item["sha256"])
                for item in pending.get("artifacts", [])
            }
            provided_set = {(r.artifact_id, r.version, r.sha256) for r in artifact_refs}
            if provided_set != expected_set:
                raise ApprovalVersionConflict("approval_version_conflict: submitted refs do not match current gate")

            approval_ids: list[str] = []
            for ref in artifact_refs:
                try:
                    aid = repo.record_approval(
                        project_id,
                        run_id,
                        ref.artifact_id,
                        ref.version,
                        ref.sha256,
                        decision,
                        comment,
                    )
                except StorageConflict as exc:
                    raise ApprovalVersionConflict("approval_version_conflict: stale artifact or hash") from exc
                approval_ids.append(aid)

            event_name = "approve_current" if decision == "approve" else "request_revision"
            next_state = run_transition(RunState(run["status"]), event_name)

            route_to: str | None = None
            stale_ids: tuple[str, ...] = ()
            if decision == "request_changes":
                if gate == "requirements":
                    route_to = "Requirement"
                else:
                    route_to = revision_target if revision_target in {"Architecture", "Planning"} else "Architecture"
                stale_ids = tuple(ref.artifact_id for ref in artifact_refs)
                checkpoint["stale_artifacts"] = sorted(
                    set(checkpoint.get("stale_artifacts", [])) | set(stale_ids)
                )
                checkpoint["revision_route"] = route_to
            else:
                checkpoint.pop("revision_route", None)
                approved_gates = dict(checkpoint.get("approved_gates", {}))
                approved_gates[gate] = [ref.model_dump(mode="json") for ref in artifact_refs]
                checkpoint["approved_gates"] = approved_gates

            checkpoint.pop("pending_gate", None)
            repo._db.execute(
                "UPDATE runs SET status=?, checkpoint_json=? WHERE id=? AND status='waiting_approval'",
                (next_state.value, encode(checkpoint), run_id),
            )
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, ?, ?)",
                (
                    run_id,
                    "gate.approved" if decision == "approve" else "gate.revision_requested",
                    encode(
                        {
                            "gate": gate,
                            "decision": decision,
                            "approval_ids": approval_ids,
                            "route_to": route_to,
                            "stale_artifact_ids": list(stale_ids),
                        }
                    ),
                ),
            )
            return GateDecisionResult(
                run_id=run_id,
                gate=gate,
                decision=decision,
                approval_ids=tuple(approval_ids),
                next_status=next_state.value,
                route_to=route_to,
                stale_artifact_ids=stale_ids,
            )

    def record_clarification(
        self,
        project_id: str,
        run_id: str,
        artifact_ref: ArtifactRef,
        answers: list[dict[str, str]],
    ) -> None:
        if artifact_ref.run_id != run_id:
            raise ApprovalVersionConflict("approval_version_conflict: cross-run clarification rejected")
        if not answers or any(
            not isinstance(item.get("question_id"), str)
            or not item["question_id"].strip()
            or not isinstance(item.get("answer"), str)
            or not item["answer"].strip()
            for item in answers
        ):
            raise ValueError("Clarification requires at least one non-empty question_id/answer pair")

        with self.database.transaction(write=True) as repo:
            reader = repo.for_run(project_id, run_id)
            run = repo.get_run(project_id, run_id)
            try:
                row = reader.artifact(artifact_ref.artifact_id, artifact_ref.version)
            except KeyError as exc:
                raise ApprovalVersionConflict("approval_version_conflict: unknown clarification artifact") from exc
            if row["sha256"] != artifact_ref.sha256 or reader.latest_version(row["type"]) != artifact_ref.version:
                raise ApprovalVersionConflict("approval_version_conflict: clarification targets stale version")
            checkpoint = json.loads(run["checkpoint_json"] or "{}")
            outstanding = checkpoint.get("pending_questions", {})
            if outstanding:
                refs = checkpoint.get("pending_gate", {}).get("artifacts", [])
                keys = [answer["question_id"] for answer in answers]
                if (run["status"] != "waiting_approval" or artifact_ref.model_dump() not in refs
                        or len(keys) != len(set(keys)) or not set(keys) <= outstanding.keys()):
                    raise ApprovalVersionConflict("Clarification does not match pending questions")
                for key in keys:
                    del outstanding[key]
                status = run["status"]
                if not outstanding:
                    checkpoint.pop("pending_questions")
                    checkpoint.pop("pending_gate")
                    checkpoint["revision_route"] = "Requirement"
                    status = run_transition(RunState.WAITING, "request_revision").value
                repo._db.execute("UPDATE runs SET checkpoint_json=?,status=? WHERE id=?",
                                 (encode(checkpoint), status, run_id))
            repo._db.execute(
                "INSERT INTO events(run_id, step_id, event_type, payload_json) VALUES (?, NULL, ?, ?)",
                (
                    run_id,
                    "clarification.recorded",
                    encode({"artifact": artifact_ref.model_dump(mode="json"), "answers": answers}),
                ),
            )

    def is_gate_approved(
        self,
        project_id: str,
        run_id: str,
        gate: str,
        expected_refs: list[ArtifactRef],
    ) -> bool:
        """Host guard: returns True ONLY if every ref is latest AND currently approved by exact version/hash."""
        if gate not in GATE_KINDS or len(expected_refs) != len(GATE_KINDS[gate]):
            return False
        with self.database.transaction() as repo:
            reader = repo.for_run(project_id, run_id)
            try:
                self._verify_gate_refs(reader, run_id, gate, expected_refs)
            except (ApprovalVersionConflict, ValueError):
                return False

            approvals = reader.records("approvals")
            for ref in expected_refs:
                matching = [
                    a
                    for a in approvals
                    if (a["artifact_id"], a["artifact_version"], a["artifact_sha256"])
                    == (ref.artifact_id, ref.version, ref.sha256)
                ]
                if not matching or matching[-1]["decision"] != "approve":
                    return False
            return True

    def compute_requirement_change_impact(
        self,
        project_id: str,
        run_id: str,
        new_requirement_ref: ArtifactRef,
    ) -> ChangeImpact:
        """Identify downstream architecture/plan artifacts & tasks invalidated by a newer requirements version."""
        with self.database.transaction() as repo:
            reader = repo.for_run(project_id, run_id)
            row = reader.artifact(new_requirement_ref.artifact_id, new_requirement_ref.version)
            if row["type"] != "requirements" or row["sha256"] != new_requirement_ref.sha256:
                raise ApprovalVersionConflict("approval_version_conflict: invalid requirements reference")

            stale_artifacts: list[str] = []
            for art in reader.records("artifacts"):
                if art["type"] not in {"architecture", "plan"}:
                    continue
                parents = json.loads(art["parent_refs_json"])
                req_parents = [p for p in parents if p.get("artifact_id") == new_requirement_ref.artifact_id]
                if not req_parents:
                    stale_artifacts.append(art["id"])

            stale_set = set(stale_artifacts)
            affected_tasks = [
                t["id"]
                for t in reader.records("tasks")
                if t["plan_artifact_id"] in stale_set
            ]
            return ChangeImpact(
                run_id=run_id,
                trigger_artifact=new_requirement_ref,
                stale_artifact_ids=tuple(sorted(stale_set)),
                affected_task_ids=tuple(sorted(affected_tasks)),
            )

    @staticmethod
    def _verify_gate_refs(reader, run_id: str, gate: str, artifact_refs: list[ArtifactRef]) -> None:
        expected_kinds = set(GATE_KINDS[gate])
        seen_kinds: dict[str, dict] = {}
        for ref in artifact_refs:
            if ref.run_id != run_id:
                raise ApprovalVersionConflict("approval_version_conflict: artifact belongs to another run")
            try:
                row = reader.artifact(ref.artifact_id, ref.version)
            except KeyError as exc:
                raise ApprovalVersionConflict("approval_version_conflict: artifact not found in run") from exc
            if row["sha256"] != ref.sha256:
                raise ApprovalVersionConflict("approval_version_conflict: artifact sha256 mismatch")
            if reader.latest_version(row["type"]) != ref.version:
                raise ApprovalVersionConflict("approval_version_conflict: artifact version is stale")
            if row["type"] not in expected_kinds or row["type"] in seen_kinds:
                raise ValueError(f"Gate {gate} received unexpected or duplicate artifact type {row['type']!r}")
            seen_kinds[row["type"]] = row

        if set(seen_kinds) != expected_kinds:
            raise ValueError(f"Gate {gate} missing required artifact kinds")

        if gate == "architecture_plan":
            arch_row = seen_kinds["architecture"]
            plan_parents = json.loads(seen_kinds["plan"]["parent_refs_json"])
            matches_arch = any(
                p.get("artifact_id") == arch_row["id"]
                and p.get("version") == arch_row["version"]
                and p.get("sha256") == arch_row["sha256"]
                for p in plan_parents
            )
            if not matches_arch:
                raise ApprovalVersionConflict(
                    "approval_version_conflict: plan does not reference the submitted architecture version"
                )
