"""Fair Single-Agent Baseline (S) sharing the host, MCP, skills, gates, quota, and runner of M (E02)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from mcp import Client, StdioServerParameters
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ConfigDict, Field

from backend.approvals import ApprovalService
from backend.coding_agents import BugDiagnosis, FileChange, ReviewFinding, ReviewReport, _dedupe_findings, _max_severity, _merge_usage, _unwrap_group
from backend.contracts import (
    Architecture,
    ArtifactRef,
    BugReport,
    DevResult,
    Plan,
    Requirements,
    TestReport,
    check_handoff,
)
from backend.gateway import FIELDS, POLICY, Gateway, HostStep, ToolDenied, allowed_file
from backend.lifecycle import TaskState, task_transition
from backend.llm import ModelError
from backend.llm import invoke as infer
from backend.mcp_tools import CONFIG_VAR, ToolSession, discover, invoke
from backend.quota import BudgetExceededError, PricingSnapshot, QuotaLimits, RunQuotaTracker, UsageEntry
from backend.skill_registry import ROLE_SKILLS, RunSkills
from backend.storage import StorageConflict, encode, new_id
from backend.trace import TraceAuditService
from backend.worker import PERSISTED_TRANSITION
from backend.workspace import Workspace


BASELINE_ROLE_LABEL = "SingleAgent"
INFRA_STATUSES = frozenset({"infrastructure_error", "timeout", "cancelled", "cleanup_error"})


def build_single_agent_policy() -> dict[str, list[str]]:
    """Compute the exact union of Dev and Tester permissions from D11, keeping forbidden areas closed."""
    dev = POLICY["roles"]["Dev"]
    tester = POLICY["roles"]["Tester"]
    read_tools = sorted(set(dev["read"]) | set(tester["read"]))
    read_roots = sorted(set(dev["read_roots"]) | set(tester["read_roots"]))
    write_roots = sorted(set(dev["write"]) | set(tester["write"]))
    suites = sorted(set(dev["suites"]) | set(tester["suites"]))
    forbidden = {"evaluation", "skills", "docs", "backend", "frontend"}
    if set(write_roots) & forbidden or set(read_roots) & forbidden:
        raise ValueError("Baseline policy cannot include evaluation, skills, or host policy directories")
    return {
        "read": read_tools,
        "read_roots": read_roots,
        "write": write_roots,
        "suites": suites,
    }


SINGLE_AGENT_POLICY = build_single_agent_policy()


class BaselineRequirementsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requirements: Requirements
    markdown: str = Field(min_length=1)


class BaselineDesignPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    architecture: Architecture
    plan: Plan


class BaselineTaskDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1)
    blocker: str | None
    suite_id: Literal["build", "smoke", "development"]
    files: list[FileChange] = Field(min_length=1, max_length=64)
    review_findings: list[ReviewFinding] = Field(max_length=64)


class SingleAgentGateway(Gateway):
    """Host Gateway variant enforcing union Dev+Tester permissions (app/ and tests_dev/ only) for baseline S."""

    def _authorize(self, worker, step, workspace, tool, args):
        role = SINGLE_AGENT_POLICY
        if tool not in FIELDS or type(args) is not dict or set(args) != FIELDS[tool]:
            raise ToolDenied("invalid_tool_arguments")
        if tool == "workspace.apply_patch":
            if not role["write"] or not step["task_id"] or not isinstance(args["edits"], list) or not args["edits"]:
                raise ToolDenied("write_denied")
            for edit in args["edits"]:
                if type(edit) is not dict or set(edit) != {"path", "expected_hash", "text"}:
                    raise ToolDenied("invalid_edit")
                path = allowed_file(workspace, edit["path"])
                if path.split("/")[0] not in role["write"]:
                    raise ToolDenied("write_scope")
        elif tool == "tests.run_suite":
            if not step["task_id"] or args["suite_id"] not in role["suites"]:
                raise ToolDenied("suite_denied")
        elif tool not in role["read"]:
            raise ToolDenied("read_denied")
        elif tool == "workspace.read_file":
            allowed_file(workspace, args["path"])
        elif tool == "project.read_artifact":
            if not any(
                (r["id"], r["version"], r["sha256"]) == (args["artifact_id"], args["version"], args["sha256"])
                for r in worker.records("artifacts")
            ):
                raise ToolDenied("artifact_not_in_run")


@asynccontextmanager
async def baseline_step_client(database_path, root, host: HostStep, image=None):
    """Spawn a step-bound MCP stdio server using SingleAgentGateway (same 7 tools and DockerRunner as M)."""
    config = {
        "database": str(Path(database_path).resolve()),
        "root": str(Path(root).resolve()),
        "host": asdict(host),
        "image": image,
    }
    env = {
        key: val
        for key, val in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "LOCALAPPDATA"}
    }
    env[CONFIG_VAR] = json.dumps(config)
    transport = StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.baseline_single_agent"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
    )
    async with Client(transport, read_timeout_seconds=215) as client:
        yield client


def assert_fair_baseline_parity(
    s_config: dict,
    m_config: dict,
    s_budget: dict,
    m_budget: dict,
) -> None:
    """Verify experimental fairness between single-agent baseline S and 6-agent M (Issue #52 / Word 5.1-5.2)."""
    for key in ("model", "skills_enabled", "runner_image", "case_id"):
        if s_config.get(key) != m_config.get(key):
            raise ValueError(f"Unfair S vs M configuration mismatch on {key!r}: S={s_config.get(key)!r} vs M={m_config.get(key)!r}")
    for key in ("max_total_tokens", "max_tool_calls", "max_auto_seconds", "max_repair_rounds"):
        if s_budget.get(key) != m_budget.get(key):
            raise ValueError(f"Unfair S vs M budget mismatch on {key!r}: S={s_budget.get(key)!r} vs M={m_budget.get(key)!r}")


def _ref(row: dict) -> ArtifactRef:
    return ArtifactRef(run_id=row["run_id"], artifact_id=row["id"], version=row["version"], sha256=row["sha256"])


def _task_key(plan_ref: ArtifactRef, logical_id: str) -> str:
    return "T-" + hashlib.sha256((plan_ref.artifact_id + "\0" + logical_id).encode()).hexdigest()[:32]


def _combined_skills_context(skills: RunSkills) -> str:
    sections = []
    for role in ROLE_SKILLS:
        text = skills.context(role).strip()
        if text:
            sections.append(f"## Skill ({role})\n{text}")
    return "\n\n".join(sections)


class SingleAgentBaseline:
    """Single-role baseline handler pluggable directly into Worker(queue, baseline) for fair S vs M runs."""

    def __init__(
        self,
        queue,
        store,
        image,
        *,
        model=infer,
        final_check=None,
        skill_root=None,
        client_factory=baseline_step_client,
    ):
        self.queue = queue
        self.database = queue.database
        self.store = store
        self.image = image
        self.model = model
        self.final_check = final_check or (lambda lease, refs: True)
        self.skill_root = Path(skill_root or Path(__file__).resolve().parents[1] / "skills")
        self.client_factory = client_factory
        self.gates = ApprovalService(self.database)
        self.audit = TraceAuditService(self.database)

    def _snapshot(self, lease):
        with self.database.transaction() as repo:
            run = repo.get_run(lease.project_id, lease.run_id)
            writer = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            artifacts = writer.records("artifacts")
            latest = {a["type"]: _ref(a) for a in sorted(artifacts, key=lambda a: a["version"])}
            return run, latest

    def _read(self, lease, ref: ArtifactRef, schema):
        data = self.store.read(lease.project_id, lease.run_id, ref.artifact_id, ref.version, ref.sha256)
        return schema.model_validate_json(data)

    def _stage(self, lease, stage: str) -> None:
        with self.database.transaction(write=True) as repo:
            repo.worker_run(lease.project_id, lease.run_id, lease.token)
            repo._db.execute("UPDATE runs SET stage=? WHERE id=?", (stage, lease.run_id))

    def _update_checkpoint(self, lease, **updates):
        with self.database.transaction(write=True) as repo:
            repo.worker_run(lease.project_id, lease.run_id, lease.token)
            checkpoint = json.loads(repo.get_run(lease.project_id, lease.run_id)["checkpoint_json"] or "{}")
            for key, value in updates.items():
                if value is None:
                    checkpoint.pop(key, None)
                else:
                    checkpoint[key] = value
            repo._db.execute("UPDATE runs SET checkpoint_json=? WHERE id=?", (encode(checkpoint), lease.run_id))
        return checkpoint

    def _put_artifact(self, lease, kind: str, content, *, parent_refs=()):
        with self.database.transaction() as repo:
            prior = repo.for_run(lease.project_id, lease.run_id).latest_version(kind)
        return self.store.put(
            lease.project_id, lease.run_id, lease.token, kind, content,
            created_by=BASELINE_ROLE_LABEL, expected_previous_version=prior, parent_refs=parent_refs,
        )

    def _quota(self, lease, *, before_call=False):
        now = time.time()
        with self.database.transaction() as repo:
            run = repo.get_run(lease.project_id, lease.run_id)
            view = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            saved = json.loads(run["budget_json"])
            original = saved.get("submitted_budget", saved)
            limits = QuotaLimits(**{key: original[key] for key in QuotaLimits.__dataclass_fields__ if key in original})
            config = json.loads(run["config_json"])
            pricing = PricingSnapshot(str(config.get("model", "")), "", cost_note="No price recorded")
            if config.get("pricing"):
                pricing = PricingSnapshot(**config["pricing"])

            def epoch(text: str) -> float:
                return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()

            tracker = RunQuotaTracker(limits, pricing, started_at_monotonic=epoch(run["started_at"]))
            waiting_since = None
            for row in sorted(view.records("events"), key=lambda r: r["id"]):
                if row["event_type"] == "gate.opened":
                    waiting_since = epoch(row["created_at"])
                elif waiting_since is not None and row["event_type"] in {
                    "gate.approved", "gate.revision_requested", "claimed",
                }:
                    tracker.add_approval_wait(max(0.0, epoch(row["created_at"]) - waiting_since))
                    waiting_since = None
            tracker.record_tool_call(len(view.records("tool_calls")))
            for step in view.records("agent_steps"):
                if step["status"] == "started":
                    continue
                usage = json.loads(step["usage_json"] or "{}")
                tracker.record_llm_usage(UsageEntry(
                    BASELINE_ROLE_LABEL,
                    step["id"],
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("cached_tokens"),
                    usage.get("usage_complete", True),
                    step["attempt"] > 1,
                ))
        try:
            tracker.check_limits(now_monotonic=now)
            if before_call and limits.max_total_tokens is not None and tracker.total_tokens >= limits.max_total_tokens:
                tracker.stop_reason = "token_limit_exceeded"
                raise BudgetExceededError(tracker.stop_reason, "No tokens remain for another model call")
        finally:
            tracker.persist(self.database, lease.project_id, lease.run_id, lease.token, now_monotonic=now)

    def _prepare_tasks(self, lease, plan_ref: ArtifactRef, plan: Plan) -> None:
        with self.database.transaction(write=True) as repo:
            view = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            if any(row["plan_artifact_id"] == plan_ref.artifact_id for row in view.records("tasks")):
                return
            for task in plan.tasks:
                key = _task_key(plan_ref, task.task_id)
                view.add_task(key, plan_ref.artifact_id, task.task_id, task.requirement_ids, task.done_conditions)
            for task in plan.tasks:
                for dep in task.dependencies:
                    view.add_dependency(_task_key(plan_ref, task.task_id), _task_key(plan_ref, dep))

    def _move_task(self, lease, key: str, current: str, event: str, repairs: int) -> tuple[str, int]:
        target = task_transition(TaskState(current), event, repair_count=repairs)
        if event == "start" and current == "rework":
            repairs += 1
        with self.database.transaction(write=True) as repo:
            writer = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            writer.update_task(key, current, target, repairs)
            writer.add_event("task.transition", {
                "task_id": key, "from": current, "to": target, "repair_round": repairs, "mode": "single_agent",
            })
        return target.value, repairs

    def _run_model_step(self, lease, *, db_role: str, phase: str, prompt: str, schema: dict, inputs=(), task_id=None, attempt=1):
        self._quota(lease, before_call=True)
        step_id = new_id()
        checkpoint = {"operation_id": new_id(), "phase_name": phase, "input_refs": [r.model_dump() for r in inputs]}
        self.queue.start_step(lease, step_id, db_role, attempt, checkpoint["input_refs"], checkpoint, task_id)
        try:
            reply = self.model(prompt, schema)
        except ModelError as exc:
            self.queue.finish_step(lease, step_id, "model_error", [], checkpoint, exc.usage)
            self.audit.record_event(
                lease.project_id, lease.run_id, lease.token, "model.failed",
                {"code": exc.code, "mode": "single_agent", "phase": phase},
                correlation_id=checkpoint["operation_id"], step_id=step_id, error_category="environment",
            )
            self._quota(lease)
            raise ValueError("Baseline model failed: " + exc.code) from exc
        usage = _merge_usage([reply])
        self._put_artifact(lease, "log", json.dumps({
            "mode": "single_agent", "phase": phase, "model": reply.model, "usage": reply.usage,
            "usage_complete": reply.usage_complete, "prompt_sha256": reply.prompt_sha256,
            "config_sha256": reply.config_sha256,
        }), parent_refs=inputs)
        return step_id, checkpoint, reply, usage

    async def _execute_task_turn(self, lease, step_id: str, task_key: str, task_dict: dict, refs: list[ArtifactRef],
                                 base_commit: str, skills_text: str, bug_report: dict | None, attempt: int):
        host = HostStep(lease.project_id, lease.run_id, step_id, lease.token)
        try:
            async with self.client_factory(self.database.path, self.store.root, host, self.image) as client:
                async def tool(name, **args):
                    return await invoke(client, uuid4().hex, name, args)

                descriptor = await discover(client)
                head = (await tool("git.status"))["head"]
                if head != base_commit:
                    raise ValueError("workspace commit changed before baseline task turn")
                catalog = await tool("workspace.list_files")
                if catalog["truncated"]:
                    raise ValueError("file catalog exceeds limit")
                existing = set(catalog["files"])
                read_files = {}
                read_size = 0
                priority = [*task_dict.get("files", []), *sorted(f for f in existing if f.startswith("tests_dev/"))]
                for p in priority:
                    if p in existing and p not in read_files:
                        observed = await tool("workspace.read_file", path=p)
                        size = len(json.dumps({p: observed}, ensure_ascii=False))
                        if read_size + size > 140_000:
                            break
                        read_files[p] = observed
                        read_size += size
                source_docs = []
                for ref in refs[:3]:
                    doc = await tool(
                        "project.read_artifact",
                        artifact_id=ref.artifact_id, version=ref.version, sha256=ref.sha256,
                    )
                    source_docs.append(doc["text"])
                details = {
                    "mode": "single_agent",
                    "task": task_dict,
                    "attempt": attempt,
                    "source_artifacts": source_docs,
                    "known_files": sorted(existing),
                    "files": read_files,
                    "bug_report": bug_report,
                }
                if len(json.dumps(details, ensure_ascii=False)) > 220_000:
                    raise ValueError("baseline task context exceeds model allowance")

                prompt = (
                    skills_text
                    + "\nYou are the single-agent baseline (S) with union permissions on app/ and tests_dev/ "
                    "(never touch evaluation/, skills/, or policy files). Implement or repair the assigned "
                    "task in app/ AND include development + regression tests in tests_dev/. Return summary, "
                    "blocker (null if implemented), suite_id ('development' recommended), files [{path,text}], "
                    "and review_findings. Respond with JSON and empty tool_proposals. Task data:\n"
                    + json.dumps(details, ensure_ascii=False)
                )
                reply = await asyncio.to_thread(self.model, prompt, BaselineTaskDelivery.model_json_schema())
                delivery = BaselineTaskDelivery.model_validate(reply.output)
                self._put_artifact(lease, "log", json.dumps({
                    "mode": "single_agent", "phase": "implement_and_test", "model": reply.model,
                    "usage": reply.usage, "usage_complete": reply.usage_complete,
                    "prompt_sha256": reply.prompt_sha256, "config_sha256": reply.config_sha256,
                    "tools_sha256": descriptor["tool_schema_sha256"],
                }), parent_refs=refs)
                replies = [reply]
                if delivery.blocker or not delivery.files:
                    raise ValueError("SingleAgent blocked: " + (delivery.blocker or "empty patch"))

                edits = []
                for item in delivery.files:
                    if item.path in read_files and item.text == read_files[item.path]["text"]:
                        continue
                    if item.path.split("/")[0] in SINGLE_AGENT_POLICY["write"] and item.path in existing and item.path not in read_files:
                        raise ValueError("missing original file observation")
                    edits.append({
                        "path": item.path,
                        "expected_hash": read_files.get(item.path, {}).get("sha256"),
                        "text": item.text,
                    })
                if not edits:
                    raise ValueError("SingleAgent produced no file changes")

                receipt = await tool("workspace.apply_patch", input_commit=head, edits=edits)
                tested_commit = receipt["output_commit"]
                patch_ref = self._put_artifact(lease, "patch", receipt["diff"], parent_refs=refs)

                suite_res = await tool("tests.run_suite", suite_id=delivery.suite_id)
                report = suite_res["report"]
                report_id = suite_res["report_id"]
                runner_ref = ArtifactRef.model_validate(suite_res["runner_output"])
                log_tail = suite_res.get("log_tail", "")
                if report.get("commit") != tested_commit or report.get("exit_code") is None or not report_id:
                    raise ValueError("Baseline runner failed to produce a commit-bound test report")

                dev_result = DevResult(
                    task_id=task_key,
                    input_commit=head,
                    output_commit=tested_commit,
                    patch_sha256=receipt["patch_hash"],
                    changed_files=[e["path"] for e in edits],
                    summary=delivery.summary,
                )
                test_report = TestReport(
                    task_id=task_key,
                    commit=report["commit"],
                    suite_id=report["suite_id"],
                    runner_output=runner_ref,
                    exit_code=report["exit_code"],
                    passed=report["passed"],
                    failures=report["failed"],
                    errors=report["errors"],
                    skipped=report["skipped"],
                )

                bug = None
                findings = list(delivery.review_findings)
                review_summary = delivery.summary
                review_severity = _max_severity(findings)
                if not test_report.all_passed:
                    diag_prompt = (
                        skills_text
                        + "\nYour baseline test suite failed. Diagnose the failure strictly from the real "
                        "runner report and log_tail, returning BugDiagnosis JSON with empty tool_proposals:\n"
                        + json.dumps({
                            "task": task_dict, "test_report": test_report.model_dump(),
                            "runner_status": report.get("status"), "log_tail": log_tail[-8192:],
                        }, ensure_ascii=False)
                    )
                    diag_reply = await asyncio.to_thread(self.model, diag_prompt, BugDiagnosis.model_json_schema())
                    diagnosis = BugDiagnosis.model_validate(diag_reply.output)
                    replies.append(diag_reply)
                    category = "infrastructure" if report.get("status") in INFRA_STATUSES else diagnosis.category
                    bug = BugReport(
                        task_id=task_key,
                        commit=test_report.commit,
                        report=runner_ref,
                        requirement_ids=diagnosis.requirement_ids,
                        reproduce=diagnosis.reproduce,
                        expected=diagnosis.expected,
                        actual=diagnosis.actual,
                        category=category,
                    )
                    findings = _dedupe_findings(findings, diagnosis.findings)
                    review_summary = diagnosis.summary
                    review_severity = _max_severity(findings, fallback=diagnosis.severity)

                review = ReviewReport(
                    task_id=task_key,
                    commit=test_report.commit,
                    dev_commit=tested_commit,
                    suite_id=test_report.suite_id,
                    runner_output=runner_ref,
                    requirement_ids=list(task_dict["requirement_ids"]),
                    verdict="pass" if test_report.all_passed else "fail",
                    severity=review_severity,
                    summary=review_summary,
                    findings=findings,
                )
                return {
                    "dev_result": dev_result,
                    "patch_ref": patch_ref,
                    "test_report": test_report,
                    "report_id": report_id,
                    "runner_ref": runner_ref,
                    "review": review,
                    "bug": bug,
                    "usage": _merge_usage(replies),
                }
        except BaseExceptionGroup as eg:
            leaf = _unwrap_group(eg)
            if leaf is not eg:
                raise leaf from None
            raise

    def _run_tasks(self, lease, lost, refs: list[ArtifactRef], plan: Plan, skills_text: str, config: dict) -> str:
        self._prepare_tasks(lease, refs[2], plan)
        workspace = Workspace(self.store.root, lease.project_id, lease.run_id)
        workspace.initialize()
        while not lost.is_set():
            with self.database.transaction() as repo:
                view = repo.worker_run(lease.project_id, lease.run_id, lease.token)
                rows = {t["id"]: t for t in view.records("tasks") if t["plan_artifact_id"] == refs[2].artifact_id}
            if all(row["status"] == "done" for row in rows.values()):
                return "final_checks_passed" if self.final_check(lease, tuple(refs)) is True else "needs_evidence"
            ready = next(
                (
                    t for t in plan.tasks
                    if rows[_task_key(refs[2], t.task_id)]["status"] in {"todo", "ready", "rework"}
                    and all(rows[_task_key(refs[2], d)]["status"] == "done" for d in t.dependencies)
                ),
                None,
            )
            if ready is None:
                return "needs_evidence"

            key = _task_key(refs[2], ready.task_id)
            current, repairs = rows[key]["status"], rows[key]["repair_round"]
            if current == "todo":
                current, repairs = self._move_task(lease, key, current, "dependencies_done", repairs)
            current, repairs = self._move_task(lease, key, current, "start", repairs)
            self._stage(lease, "development")

            bug_dict = None
            turn_inputs = list(refs)
            if repairs:
                with self.database.transaction() as repo:
                    arts = repo.for_run(lease.project_id, lease.run_id).records("artifacts")
                bugs = sorted((a for a in arts if a["type"] == "bug_report"), key=lambda a: a["version"], reverse=True)
                for row in bugs:
                    bref = _ref(row)
                    candidate = self._read(lease, bref, BugReport)
                    if candidate.task_id == key:
                        bug_dict = candidate.model_dump()
                        turn_inputs.append(bref)
                        break

            self._quota(lease, before_call=True)
            base = workspace.head()
            step_id = new_id()
            checkpoint = {
                "operation_id": new_id(),
                "mode": "single_agent",
                "input_commit": base,
                "input_refs": [r.model_dump() for r in turn_inputs],
            }
            self.queue.start_step(lease, step_id, "Dev", repairs + 1, checkpoint["input_refs"], checkpoint, key)
            outcome = asyncio.run(
                self._execute_task_turn(
                    lease, step_id, key, ready.model_dump(), turn_inputs, base, skills_text, bug_dict, repairs + 1,
                )
            )
            dev_ref = self._put_artifact(lease, "dev_result", outcome["dev_result"], parent_refs=turn_inputs)
            current, repairs = self._move_task(lease, key, current, "patch_committed", repairs)
            self._stage(lease, "testing")
            report_ref = self._put_artifact(
                lease, "test_report", outcome["test_report"],
                parent_refs=[*turn_inputs, dev_ref, outcome["patch_ref"]],
            )
            self._put_artifact(
                lease, "document", outcome["review"].model_dump_json(indent=2),
                parent_refs=[*turn_inputs, dev_ref, outcome["patch_ref"], outcome["runner_ref"]],
            )
            outputs = [dev_ref.model_dump(), outcome["patch_ref"].model_dump(), report_ref.model_dump()]
            self.queue.finish_step(lease, step_id, "finished", outputs, checkpoint, outcome["usage"])
            self._quota(lease)

            with self.database.transaction() as repo:
                report_row = next(
                    r for r in repo.for_run(lease.project_id, lease.run_id).records("test_reports")
                    if r["id"] == outcome["report_id"]
                )
            for fr in ready.requirement_ids:
                self.audit.link_fr_chain(
                    lease.project_id, lease.run_id, lease.token,
                    fr_id=fr, task_id=key,
                    patch_artifact_id=outcome["patch_ref"].artifact_id,
                    test_report_id=report_row["id"],
                    evidence_uri=report_row["report_uri"],
                )

            if outcome["test_report"].all_passed:
                self._move_task(lease, key, current, "verified", repairs)
                continue
            bug = outcome["bug"]
            if bug is None:
                return "needs_evidence"
            bug_ref = self._put_artifact(lease, "bug_report", bug, parent_refs=[report_ref])
            if bug.category == "code":
                current, _ = self._move_task(lease, key, current, "code_bug", repairs)
                if current == "blocked":
                    return "repairs_exhausted"
                continue
            if bug.category in {"requirements", "design"}:
                route = "Requirement" if bug.category == "requirements" else "Architecture"
                self._update_checkpoint(lease, revision_route=route, routing_bug=bug_ref.model_dump())
                return self._pipeline(lease, lost)
            return "needs_evidence"
        raise StorageConflict("Worker lost ownership")

    def _pipeline(self, lease, lost) -> str:
        run, latest = self._snapshot(lease)
        config = json.loads(run["config_json"] or "{}")
        checkpoint = json.loads(run["checkpoint_json"] or "{}")
        route = checkpoint.get("revision_route")
        run_dir = self.store.root / lease.project_id / lease.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        skills = RunSkills(self.skill_root, enabled=config.get("skills_enabled", True))
        skills.bind(run_dir / "skills.json")
        skills_text = _combined_skills_context(skills)

        with self.database.transaction() as repo:
            project = repo.get_project(lease.project_id)
            events = repo.for_run(lease.project_id, lease.run_id).records("events")
        feedback = [
            json.loads(r["payload_json"])
            for r in events
            if r["event_type"] in {"clarification.recorded", "gate.revision_requested"}
        ]
        if not any(r["event_type"] == "baseline.configured" for r in events):
            self.audit.record_event(
                lease.project_id, lease.run_id, lease.token, "baseline.configured",
                {"mode": "single_agent", "policy": SINGLE_AGENT_POLICY, "skills_enabled": config.get("skills_enabled", True)},
                correlation_id=new_id(),
            )

        # Stage 1: Requirements + Gate 1
        req = latest.get("requirements")
        self._stage(lease, "requirements")
        if not req or route == "Requirement":
            prompt = (
                skills_text
                + "\nYou are the single-agent baseline (S). Produce complete Requirements + markdown SRS "
                "for the project brief. Return BaselineRequirementsOutput JSON with empty tool_proposals:\n"
                + json.dumps({"project": project, "feedback": feedback}, ensure_ascii=False)
            )
            step_id, cp, reply, usage = self._run_model_step(
                lease, db_role="Orchestrator", phase="requirements", prompt=prompt,
                schema=BaselineRequirementsOutput.model_json_schema(), inputs=[req] if req else [],
            )
            parsed = BaselineRequirementsOutput.model_validate(reply.output)
            req = self._put_artifact(lease, "requirements", parsed.requirements, parent_refs=[req] if req else [])
            self._put_artifact(lease, "requirements_markdown", parsed.markdown, parent_refs=[req])
            self.queue.finish_step(lease, step_id, "finished", [req.model_dump()], cp, usage)
            self._quota(lease)
            if route == "Requirement":
                self._update_checkpoint(lease, revision_route=None, routing_bug=None)
                route = None

        requirements = self._read(lease, req, Requirements)
        if not self.gates.is_gate_approved(lease.project_id, lease.run_id, "requirements", [req]):
            self.gates.open_gate(
                lease.project_id, lease.run_id, lease.token, "requirements", [req], questions=requirements.questions,
            )
            return PERSISTED_TRANSITION

        # Stage 2: Architecture + Plan + Gate 2
        self._stage(lease, "architecture")
        arch = latest.get("architecture")
        plan_ref = latest.get("plan")
        need_design = (
            not arch
            or not plan_ref
            or route in {"Architecture", "Planning"}
            or self._read(lease, arch, Architecture).requirements != req
            or self._read(lease, plan_ref, Plan).requirements != req
            or self._read(lease, plan_ref, Plan).architecture != arch
        )
        if need_design:
            prompt = (
                skills_text
                + "\nYou are the single-agent baseline (S). Produce Architecture and executable task Plan "
                "covering every FR with valid DAG dependencies. Return BaselineDesignPlanOutput JSON "
                "with empty tool_proposals:\n"
                + json.dumps({
                    "project": project,
                    "requirements_ref": req.model_dump(),
                    "requirements": requirements.model_dump(),
                    "feedback": feedback,
                }, ensure_ascii=False)
            )
            step_id, cp, reply, usage = self._run_model_step(
                lease, db_role="Orchestrator", phase="architecture_plan", prompt=prompt,
                schema=BaselineDesignPlanOutput.model_json_schema(), inputs=[req],
            )
            parsed = BaselineDesignPlanOutput.model_validate(reply.output)
            if parsed.architecture.requirements != req:
                raise ValueError("Baseline architecture references stale requirements")
            arch = self._put_artifact(lease, "architecture", parsed.architecture, parent_refs=[req])
            # Rebind plan's architecture ref if model emitted placeholder artifact_id matching schema.
            plan_data = parsed.plan.model_dump()
            plan_data["requirements"] = req.model_dump()
            plan_data["architecture"] = arch.model_dump()
            plan_obj = Plan.model_validate(plan_data)
            check_handoff(requirements, parsed.architecture, plan_obj, req, arch)
            plan_ref = self._put_artifact(lease, "plan", plan_obj, parent_refs=[req, arch])
            self.queue.finish_step(lease, step_id, "finished", [arch.model_dump(), plan_ref.model_dump()], cp, usage)
            self._quota(lease)
            if route in {"Architecture", "Planning"}:
                self._update_checkpoint(lease, revision_route=None, routing_bug=None)
                route = None

        architecture = self._read(lease, arch, Architecture)
        plan = self._read(lease, plan_ref, Plan)
        check_handoff(requirements, architecture, plan, req, arch)
        if not self.gates.is_gate_approved(lease.project_id, lease.run_id, "architecture_plan", [arch, plan_ref]):
            self.gates.open_gate(lease.project_id, lease.run_id, lease.token, "architecture_plan", [arch, plan_ref])
            return PERSISTED_TRANSITION

        # Stage 3: Unified Implement + Test + Self-Repair Loop
        return self._run_tasks(lease, lost, [req, arch, plan_ref], plan, skills_text, config)

    def __call__(self, lease, lost) -> str:
        try:
            return self._pipeline(lease, lost)
        except BudgetExceededError:
            return "quota_exceeded"
        except (ValueError, KeyError, RuntimeError) as exc:
            self.audit.record_event(
                lease.project_id, lease.run_id, lease.token, "handoff.rejected",
                {"reason": type(exc).__name__, "mode": "single_agent"},
                correlation_id=new_id(), error_category="schema",
            )
            with self.database.transaction() as repo:
                steps = repo.for_run(lease.project_id, lease.run_id).records("agent_steps")
            if any(step["status"] == "started" for step in steps):
                return "effects_uncertain"
            return "invalid_handoff"


async def _run_baseline_mcp_server() -> None:
    config = json.loads(os.environ.pop(CONFIG_VAR))
    session = ToolSession(config)
    session.gateway = SingleAgentGateway(session.database, session.root)
    server = session.make_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_run_baseline_mcp_server())
