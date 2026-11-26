"""Allowed host-side transitions for a single-run worker."""

from dataclasses import dataclass
from enum import StrEnum


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting_approval"
    RECOVERY = "pending_recovery"
    REVIEW = "needs_human_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState(StrEnum):
    TODO = "todo"
    READY = "ready"
    ACTIVE = "in_progress"
    TEST = "waiting_test"
    REWORK = "rework"
    DONE = "done"
    BLOCKED = "blocked"


R, T = RunState, TaskState
RUN_EVENTS = {
    (R.QUEUED, "claim"): R.RUNNING,
    (R.RUNNING, "request_approval"): R.WAITING,
    (R.WAITING, "approve_current"): R.QUEUED,
    (R.WAITING, "request_revision"): R.QUEUED,
    (R.RUNNING, "effects_uncertain"): R.RECOVERY,
    (R.RUNNING, "lease_expired"): R.RECOVERY,
    (R.RECOVERY, "reconciled"): R.QUEUED,
    (R.RUNNING, "quota_exceeded"): R.REVIEW,
    (R.RUNNING, "repairs_exhausted"): R.REVIEW,
    (R.REVIEW, "owner_resume"): R.QUEUED,
    (R.RUNNING, "final_checks_passed"): R.COMPLETED,
    (R.RUNNING, "irrecoverable_error"): R.FAILED,
}
for state in (R.QUEUED, R.RUNNING, R.WAITING, R.RECOVERY, R.REVIEW):
    RUN_EVENTS[state, "cancel"] = R.CANCELLED

TASK_EVENTS = {
    (T.TODO, "dependencies_done"): T.READY,
    (T.READY, "start"): T.ACTIVE,
    (T.ACTIVE, "patch_committed"): T.TEST,
    (T.TEST, "verified"): T.DONE,
    (T.TEST, "code_bug"): T.REWORK,
    (T.REWORK, "start"): T.ACTIVE,
    (T.TEST, "repairs_exhausted"): T.BLOCKED,
}


def run_transition(state: RunState, event: str) -> RunState:
    try:
        return RUN_EVENTS[state, event]
    except KeyError:
        raise ValueError(f"invalid_transition: {state} / {event}") from None


def task_transition(state: TaskState, event: str, *, repair_count: int) -> TaskState:
    if not 0 <= repair_count <= 3:
        raise ValueError("invalid repair count")
    if event == "code_bug" and repair_count == 3:
        event = "repairs_exhausted"
    try:
        return TASK_EVENTS[state, event]
    except KeyError:
        raise ValueError(f"invalid_transition: {state} / {event}") from None


@dataclass(frozen=True)
class Checkpoint:
    operation_id: str
    input_commit: str
    patch_hash: str
    output_commit: str | None


def recovery_action(expected: Checkpoint, receipt: Checkpoint | None, current_commit: str) -> str:
    """A missing receipt cannot establish that a side effect never happened."""
    if not receipt or not receipt.output_commit or receipt.output_commit != current_commit:
        return "pending_recovery"
    if (expected.operation_id, expected.input_commit, expected.patch_hash) != (
        receipt.operation_id, receipt.input_commit, receipt.patch_hash
    ):
        return "pending_recovery"
    if expected.output_commit and expected.output_commit != receipt.output_commit:
        return "pending_recovery"
    return "advance_without_replay"
