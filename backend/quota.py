"""SUPPORT MODULE (draft prior to I04/I06/I15) for I19 shared run quota & usage tracking.

Shares one budget across all six roles (M) or one baseline agent (S), separates
approval_wait_seconds from automated execution time, preserves missing-usage flags
without coercing unknown usage to exact 0, and supports token_limit=None per D08.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from backend.lifecycle import RunState, run_transition
from backend.storage import Database, encode


class BudgetExceededError(RuntimeError):
    """Raised before/after an action when a run hits any configured hard budget limit."""

    code = "budget_exceeded"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class QuotaLimits:
    """Hard caps for a run. None means no app-side cap (e.g. token_limit=None per D08)."""

    max_total_tokens: int | None = None
    max_tool_calls: int | None = None
    max_auto_seconds: float | None = None
    max_repair_rounds: int = 3

    def __post_init__(self) -> None:
        if self.max_total_tokens is not None and self.max_total_tokens < 0:
            raise ValueError("max_total_tokens must be >= 0")
        if self.max_tool_calls is not None and self.max_tool_calls < 0:
            raise ValueError("max_tool_calls must be >= 0")
        if self.max_auto_seconds is not None and self.max_auto_seconds < 0:
            raise ValueError("max_auto_seconds must be >= 0")
        if not 0 <= self.max_repair_rounds <= 3:
            raise ValueError("max_repair_rounds must be in 0..3 per P01/D08")


@dataclass(frozen=True)
class PricingSnapshot:
    model_id: str
    captured_date: str
    input_per_1m_usd: float | None = None
    output_per_1m_usd: float | None = None
    cached_per_1m_usd: float | None = None
    cost_note: str = ""


@dataclass(frozen=True)
class UsageEntry:
    role: str
    step_id: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None = None
    usage_complete: bool = True
    is_retry: bool = False
    note: str = ""


@dataclass
class RunQuotaTracker:
    limits: QuotaLimits
    pricing: PricingSnapshot
    started_at_monotonic: float = 0.0
    approval_wait_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    tool_calls: int = 0
    usage_complete: bool = True
    missing_usage_steps: list[str] = field(default_factory=list)
    by_role_tokens: dict[str, int] = field(default_factory=dict)
    retry_calls: int = 0
    stop_reason: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def automated_elapsed_seconds(self, now_monotonic: float) -> float:
        total = max(0.0, now_monotonic - self.started_at_monotonic)
        return max(0.0, total - self.approval_wait_seconds)

    def add_approval_wait(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("approval wait seconds must be >= 0")
        self.approval_wait_seconds += seconds

    def record_llm_usage(self, entry: UsageEntry) -> None:
        if entry.is_retry:
            self.retry_calls += 1
        if not entry.usage_complete or entry.input_tokens is None or entry.output_tokens is None:
            self.usage_complete = False
            if entry.step_id not in self.missing_usage_steps:
                self.missing_usage_steps.append(entry.step_id)
        in_tok = max(0, entry.input_tokens or 0)
        out_tok = max(0, entry.output_tokens or 0)
        cache_tok = max(0, entry.cached_tokens or 0)
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.cached_tokens += cache_tok
        self.by_role_tokens[entry.role] = self.by_role_tokens.get(entry.role, 0) + in_tok + out_tok

    def record_tool_call(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("tool call increment must be >= 0")
        self.tool_calls += count

    def estimated_cost_usd(self) -> float | None:
        if self.pricing.input_per_1m_usd is None or self.pricing.output_per_1m_usd is None:
            return None
        cached_rate = self.pricing.cached_per_1m_usd or 0.0
        cost = (
            (self.input_tokens / 1_000_000.0) * self.pricing.input_per_1m_usd
            + (self.output_tokens / 1_000_000.0) * self.pricing.output_per_1m_usd
            + (self.cached_tokens / 1_000_000.0) * cached_rate
        )
        return round(cost, 6)

    def check_limits(
        self,
        *,
        now_monotonic: float,
        pending_tool_calls: int = 0,
        task_repair_round: int = 0,
    ) -> None:
        if self.limits.max_total_tokens is not None and self.total_tokens > self.limits.max_total_tokens:
            self.stop_reason = "token_limit_exceeded"
            raise BudgetExceededError(
                self.stop_reason,
                f"budget_exceeded: total tokens {self.total_tokens} > {self.limits.max_total_tokens}",
            )
        if self.limits.max_tool_calls is not None and (self.tool_calls + pending_tool_calls) > self.limits.max_tool_calls:
            self.stop_reason = "tool_call_limit_exceeded"
            raise BudgetExceededError(
                self.stop_reason,
                f"budget_exceeded: tool calls {self.tool_calls + pending_tool_calls} > {self.limits.max_tool_calls}",
            )
        auto_sec = self.automated_elapsed_seconds(now_monotonic)
        if self.limits.max_auto_seconds is not None and auto_sec > self.limits.max_auto_seconds:
            self.stop_reason = "time_limit_exceeded"
            raise BudgetExceededError(
                self.stop_reason,
                f"budget_exceeded: automated time {auto_sec:.1f}s > {self.limits.max_auto_seconds:.1f}s",
            )
        if task_repair_round > self.limits.max_repair_rounds:
            self.stop_reason = "repair_round_limit_exceeded"
            raise BudgetExceededError(
                self.stop_reason,
                f"budget_exceeded: repair round {task_repair_round} > {self.limits.max_repair_rounds}",
            )

    def snapshot(self, now_monotonic: float | None = None) -> dict[str, object]:
        return {
            "limits": asdict(self.limits),
            "pricing": asdict(self.pricing),
            "input_tokens": self.input_tokens if self.usage_complete or self.input_tokens > 0 else None,
            "output_tokens": self.output_tokens if self.usage_complete or self.output_tokens > 0 else None,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "usage_complete": self.usage_complete,
            "missing_usage_steps": list(self.missing_usage_steps),
            "by_role_tokens": dict(self.by_role_tokens),
            "retry_calls": self.retry_calls,
            "approval_wait_seconds": round(self.approval_wait_seconds, 3),
            "automated_elapsed_seconds": (
                round(self.automated_elapsed_seconds(now_monotonic), 3) if now_monotonic is not None else None
            ),
            "cost_usd": self.estimated_cost_usd(),
            "stop_reason": self.stop_reason,
        }

    def persist(
        self,
        database: Database,
        project_id: str,
        run_id: str,
        lease: str,
        *,
        now_monotonic: float | None = None,
        transition_on_exceeded: bool = False,
    ) -> dict[str, object]:
        """Persist current quota snapshot into runs.budget_json (even on failed/stopped runs)."""
        snap = self.snapshot(now_monotonic)
        with database.transaction(write=True) as repo:
            run = repo.get_run(project_id, run_id)
            writer = repo.worker_run(project_id, run_id, lease)
            if transition_on_exceeded and self.stop_reason is not None:
                next_state = run_transition(RunState(run["status"]), "quota_exceeded")
                repo._db.execute(
                    "UPDATE runs SET budget_json=?, status=?, worker_lease=NULL, lease_expires_at=NULL "
                    "WHERE id=? AND worker_lease=?",
                    (encode(snap), next_state.value, run_id, lease),
                )
                writer.add_event(
                    "quota.exceeded",
                    {"code": "budget_exceeded", "reason": self.stop_reason, "usage_complete": self.usage_complete},
                )
            else:
                repo._db.execute(
                    "UPDATE runs SET budget_json=? WHERE id=? AND worker_lease=?",
                    (encode(snap), run_id, lease),
                )
        return snap


def read_persisted_quota(database: Database, project_id: str, run_id: str) -> dict[str, object]:
    with database.transaction() as repo:
        run = repo.get_run(project_id, run_id)
        return json.loads(run["budget_json"])
