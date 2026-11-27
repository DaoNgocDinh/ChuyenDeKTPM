"""Deterministic orchestration over approved artifacts, user decisions and durable task state."""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .approvals import ApprovalService
from .contracts import Architecture, ArtifactRef, BugReport, DevResult, Plan, Requirements, TestReport, check_handoff
from .lifecycle import TaskState, task_transition
from .llm import ModelError
from .quota import BudgetExceededError, PricingSnapshot, QuotaLimits, RunQuotaTracker, UsageEntry
from .recovery import OperationCancelled
from .storage import StorageConflict, encode, new_id
from .trace import TraceAuditService
from .worker import PERSISTED_TRANSITION
from .workspace import Workspace


@dataclass(frozen=True)
class WorkOrder:
    role: str
    project_id: str
    run_id: str
    lease_token: str
    step_id: str
    task_id: str | None
    inputs: tuple[ArtifactRef, ...]
    context: dict


@dataclass
class RoleOutput:
    payload: object
    usage: dict | None = None
    patch_ref: ArtifactRef | None = None
    report_id: str | None = None
    bug: BugReport | dict | None = None
    markdown: str | None = None


class InvalidHandoff(ValueError):
    pass


TYPES = {"Requirement": ("requirements", Requirements), "Architecture": ("architecture", Architecture),
         "Planning": ("plan", Plan), "Dev": ("dev_result", DevResult), "Tester": ("test_report", TestReport)}


def _ref(row):
    return ArtifactRef(run_id=row["run_id"], artifact_id=row["id"], version=row["version"], sha256=row["sha256"])


def _task_key(plan_ref, logical_id):
    return "T-" + hashlib.sha256((plan_ref.artifact_id + "\0" + logical_id).encode()).hexdigest()[:32]


class Orchestrator:
    def __init__(self, queue, store, dispatch, final_check):
        self.queue, self.database, self.store = queue, queue.database, store
        self.dispatch, self.final_check = dispatch, final_check
        self.gates = ApprovalService(self.database)
        self.audit = TraceAuditService(self.database)

    def _snapshot(self, lease):
        with self.database.transaction() as repo:
            run = repo.get_run(lease.project_id, lease.run_id)
            writer = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            artifacts = writer.records("artifacts")
            latest = {a["type"]: _ref(a) for a in sorted(artifacts, key=lambda a: a["version"])}
            return run, latest

    def _read(self, lease, ref, schema):
        data = self.store.read(lease.project_id, lease.run_id, ref.artifact_id, ref.version, ref.sha256)
        return schema.model_validate_json(data)

    def _quota(self, lease, *, before_call=False):
        now = time.time()
        with self.database.transaction() as repo:
            run = repo.get_run(lease.project_id, lease.run_id)
            view = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            saved = json.loads(run["budget_json"])
            original = saved.get("submitted_budget", saved)
            limits = QuotaLimits(**{key: original[key] for key in QuotaLimits.__dataclass_fields__ if key in original})
            config = json.loads(run["config_json"])
            pricing = PricingSnapshot(str(config.get("model", "")), "",
                                      cost_note="No price recorded")
            if config.get("pricing"):
                pricing = PricingSnapshot(**config["pricing"])
            def epoch(text):
                return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()
            tracker = RunQuotaTracker(limits, pricing, started_at_monotonic=epoch(run["started_at"]))
            waiting_since = None
            for row in sorted(view.records("events"), key=lambda r: r["id"]):
                if row["event_type"] == "gate.opened":
                    waiting_since = epoch(row["created_at"])
                elif waiting_since is not None and row["event_type"] in {"gate.approved", "gate.revision_requested", "claimed"}:
                    tracker.add_approval_wait(max(0, epoch(row["created_at"]) - waiting_since))
                    waiting_since = None
            tracker.record_tool_call(len(view.records("tool_calls")))
            for step in view.records("agent_steps"):
                if step["status"] == "started":
                    continue
                usage = json.loads(step["usage_json"] or "{}")
                tracker.record_llm_usage(UsageEntry(step["agent_role"], step["id"], usage.get("input_tokens"),
                                                       usage.get("output_tokens"), usage.get("cached_tokens"),
                                                       usage.get("usage_complete", True), step["attempt"] > 1))
        try:
            tracker.check_limits(now_monotonic=now)
            if before_call and limits.max_total_tokens is not None and tracker.total_tokens >= limits.max_total_tokens:
                tracker.stop_reason = "token_limit_exceeded"
                raise BudgetExceededError(tracker.stop_reason, "No tokens remain for another model call")
        finally:
            tracker.persist(self.database, lease.project_id, lease.run_id, lease.token, now_monotonic=now)

    def _call(self, lease, role, inputs, context, task_id=None):
        self._quota(lease, before_call=True)
        step_id = new_id()
        checkpoint = {"operation_id": new_id(), "input_refs": [r.model_dump() for r in inputs]}
        if "input_commit" in context:
            checkpoint["input_commit"] = context["input_commit"]
        self.queue.start_step(lease, step_id, role, context.get("attempt", 1), checkpoint["input_refs"],
                              checkpoint, task_id)
        order = WorkOrder(role, lease.project_id, lease.run_id, lease.token, step_id, task_id, tuple(inputs), context)
        try:
            response = self.dispatch(order)
        except ModelError as exc:
            self.queue.finish_step(lease, step_id, "model_error", [], checkpoint, exc.usage)
            self.audit.record_event(lease.project_id, lease.run_id, lease.token, "model.failed", {"code": exc.code},
                                    correlation_id=checkpoint["operation_id"], step_id=step_id, error_category="environment")
            self._quota(lease)
            raise InvalidHandoff("Model did not return a validated result") from exc
        except (ValueError, KeyError) as exc:
            with self.database.transaction() as repo:
                touched_tools = any(
                    tc["step_id"] == step_id for tc in repo.for_run(lease.project_id, lease.run_id).records("tool_calls")
                )
            if not touched_tools:
                self.queue.finish_step(lease, step_id, "rejected", [], checkpoint)
                raise InvalidHandoff(str(exc)) from exc
            raise
        if not isinstance(response, RoleOutput):
            raise TypeError("Dispatcher must return RoleOutput")
        actual = None
        try:
            if role == "Orchestrator":
                if not isinstance(response.payload, dict):
                    raise InvalidHandoff("Orchestrator advisory must be an object")
            else:
                kind, schema = TYPES[role]
                value = response.payload
                if isinstance(value, schema):
                    value = value.model_dump()
                payload = schema.model_validate(value)
                if role in ("Dev", "Tester") and payload.task_id != task_id:
                    raise InvalidHandoff("Output belongs to another task")
                if role == "Architecture" and payload.requirements != inputs[0]:
                    raise InvalidHandoff("Architecture has stale requirements")
                if role == "Planning" and (payload.requirements != inputs[0] or payload.architecture != inputs[1]):
                    raise InvalidHandoff("Plan has stale inputs")
                _, latest = self._snapshot(lease)
                actual = self.store.put(lease.project_id, lease.run_id, lease.token, kind, payload,
                                        created_by=role, expected_previous_version=latest[kind].version if kind in latest else 0,
                                        parent_refs=inputs)
                if response.markdown and role in {"Requirement", "Architecture", "Planning"}:
                    md_kind = "requirements_markdown" if role == "Requirement" else "document"
                    prior = latest.get(md_kind)
                    self.store.put(lease.project_id, lease.run_id, lease.token, md_kind,
                                   response.markdown, created_by=role, expected_previous_version=prior.version if prior else 0,
                                   parent_refs=[actual])
                response.payload = payload
        except (ValueError, KeyError) as exc:
            self.queue.finish_step(lease, step_id, "rejected", [], checkpoint, response.usage)
            raise InvalidHandoff(str(exc)) from exc
        result_refs = [actual.model_dump()] if actual else []
        self.queue.finish_step(lease, step_id, "finished", result_refs, checkpoint, response.usage)
        self.audit.record_event(lease.project_id, lease.run_id, lease.token, "handoff",
                                {"role": role, "inputs": checkpoint["input_refs"], "outputs": result_refs},
                                correlation_id=checkpoint["operation_id"], step_id=step_id)
        self._quota(lease)
        return response, actual

    def _stage(self, lease, stage):
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

    def _latest_task_bug(self, lease, task_id):
        with self.database.transaction() as repo:
            rows = repo.for_run(lease.project_id, lease.run_id).records("artifacts")
        bugs = sorted((r for r in rows if r["type"] == "bug_report"), key=lambda r: r["version"], reverse=True)
        for row in bugs:
            ref = _ref(row)
            bug = self._read(lease, ref, BugReport)
            if bug.task_id == task_id:
                return ref, bug
        return None, None

    def _gate(self, lease, name, refs, questions=None):
        self.gates.open_gate(lease.project_id, lease.run_id, lease.token, name, list(refs), questions=questions)
        return PERSISTED_TRANSITION

    def _prepare_tasks(self, lease, plan_ref, plan):
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

    def _move_task(self, lease, key, current, event, repairs):
        target = task_transition(TaskState(current), event, repair_count=repairs)
        if event == "start" and current == "rework":
            repairs += 1
        with self.database.transaction(write=True) as repo:
            writer = repo.worker_run(lease.project_id, lease.run_id, lease.token)
            writer.update_task(key, current, target, repairs)
            writer.add_event("task.transition", {"task_id": key, "from": current, "to": target,
                                                 "repair_round": repairs})
        return target.value, repairs

    def _check_dev(self, lease, workspace, base, result, *, allow_descendant_tests=False):
        dev, patch = result.payload, result.patch_ref
        if dev.input_commit != base or not patch or patch.run_id != lease.run_id:
            raise InvalidHandoff("Dev result does not match the workspace commit and patch")
        head = workspace.head()
        if dev.output_commit != head:
            if not allow_descendant_tests:
                raise InvalidHandoff("Dev result does not match the workspace commit and patch")
            workspace.git("merge-base", "--is-ancestor", dev.output_commit, head)
            extra = [
                name for name in workspace.git("diff", "--name-only", "-z", dev.output_commit, head).strip("\0").split("\0")
                if name
            ]
            if not extra or any(not name.startswith("tests_dev/") for name in extra):
                raise InvalidHandoff("Workspace diverged outside tests_dev after Dev commit")
        with self.database.transaction() as repo:
            stored = repo.for_run(lease.project_id, lease.run_id).artifact(patch.artifact_id, patch.version)
        if stored["type"] != "patch":
            raise InvalidHandoff("Expected a patch artifact")
        diff = workspace.diff(base, dev.output_commit).encode()
        content = self.store.read(lease.project_id, lease.run_id, patch.artifact_id, patch.version, patch.sha256)
        if not diff or content != diff:
            raise InvalidHandoff("Patch evidence differs from the Git diff")
        files = set(workspace.git("diff", "--name-only", "-z", base, dev.output_commit).strip("\0").split("\0"))
        if files != set(dev.changed_files) or any(not f.startswith("app/") for f in files):
            raise InvalidHandoff("Dev changed undeclared files or files outside app")
        subject = workspace.git("log", "-1", "--format=%s", dev.output_commit).strip().split()
        if dev.patch_sha256 != patch.sha256 and (len(subject) != 3 or subject[0] != dev.task_id + ":"
                                                or subject[-1] != dev.patch_sha256):
            raise InvalidHandoff("Patch hash differs from Git checkpoint and artifact")

    def _recover_waiting_test(self, lease, workspace, task_id):
        if workspace.status():
            raise InvalidHandoff("Workspace has uncommitted changes while resuming waiting_test task")
        with self.database.transaction() as repo:
            artifacts = repo.for_run(lease.project_id, lease.run_id).records("artifacts")
        dev_rows = sorted((a for a in artifacts if a["type"] == "dev_result"), key=lambda a: a["version"], reverse=True)
        dev_ref = None
        dev_payload = None
        for row in dev_rows:
            candidate_ref = _ref(row)
            candidate = self._read(lease, candidate_ref, DevResult)
            if candidate.task_id == task_id:
                dev_ref = candidate_ref
                dev_payload = candidate
                break
        if dev_ref is None or dev_payload is None:
            raise InvalidHandoff("Missing verified DevResult for waiting_test task")
        expected_diff = workspace.diff(dev_payload.input_commit, dev_payload.output_commit).encode()
        if not expected_diff:
            raise InvalidHandoff("Dev commit diff is empty")
        patch_rows = sorted((a for a in artifacts if a["type"] == "patch"), key=lambda a: a["version"], reverse=True)
        patch_ref = None
        for row in patch_rows:
            candidate_patch = _ref(row)
            content = self.store.read(
                lease.project_id, lease.run_id, candidate_patch.artifact_id, candidate_patch.version, candidate_patch.sha256
            )
            if content == expected_diff:
                patch_ref = candidate_patch
                break
        if patch_ref is None:
            raise InvalidHandoff("Missing matching patch artifact for waiting_test task")
        dev = RoleOutput(payload=dev_payload, patch_ref=patch_ref)
        self._check_dev(lease, workspace, dev_payload.input_commit, dev, allow_descendant_tests=True)
        return dev, dev_ref, workspace.head() != dev_payload.output_commit

    def _can_resume_in_progress(self, lease, workspace, task_id, repairs):
        if workspace.status() or (workspace.path / "logs" / "pending-patch.json").exists():
            return False
        with self.database.transaction() as repo:
            view = repo.for_run(lease.project_id, lease.run_id)
            steps = view.records("agent_steps")
            tool_calls = view.records("tool_calls")
        if any(s["status"] == "started" for s in steps):
            return False
        attempt = repairs + 1
        dev_steps = [
            s for s in steps
            if s["task_id"] == task_id and s["agent_role"] == "dev" and s["attempt"] == attempt
        ]
        if not dev_steps or dev_steps[-1]["status"] not in {"model_error", "rejected"}:
            return False
        step_ids = {s["id"] for s in dev_steps}
        return not any(tc["step_id"] in step_ids and tc["tool_name"] == "workspace.apply_patch" for tc in tool_calls)

    def _check_test(self, lease, workspace, dev, result):
        report = result.payload
        if report.commit != workspace.head() or not result.report_id:
            raise InvalidHandoff("Tester must identify the actual checked-out runner commit and report")
        if report.commit != dev.output_commit:
            workspace.git("merge-base", "--is-ancestor", dev.output_commit, report.commit)
            changed = workspace.git("diff", "--name-only", "-z", dev.output_commit, report.commit).strip("\0").split("\0")
            if not changed or any(not name.startswith("tests_dev/") for name in changed):
                raise InvalidHandoff("Tester changed files outside the development test tree")
        with self.database.transaction() as repo:
            view = repo.for_run(lease.project_id, lease.run_id)
            evidence = view.artifact(report.runner_output.artifact_id, report.runner_output.version)
            row = next((r for r in view.records("test_reports") if r["id"] == result.report_id), None)
        if evidence["type"] != "runner_output" or row is None:
            raise InvalidHandoff("Missing host runner evidence")
        expected = (report.task_id, report.commit, report.suite_id, report.exit_code, report.passed,
                    report.failures, report.errors, report.skipped)
        keys = ("task_id", "commit_hash", "suite_id", "exit_code", "passed", "failed", "errors", "skipped")
        if tuple(row[key] for key in keys) != expected:
            raise InvalidHandoff("Structured result differs from the executed report")
        return row

    def _tasks(self, lease, lost, refs, plan, context):
        self._prepare_tasks(lease, refs[2], plan)
        workspace = Workspace(self.store.root, lease.project_id, lease.run_id)
        workspace.initialize()
        while not lost.is_set():
            with self.database.transaction() as repo:
                run_row = repo.get_run(lease.project_id, lease.run_id)
                view = repo.worker_run(lease.project_id, lease.run_id, lease.token)
                rows = {t["id"]: t for t in view.records("tasks") if t["plan_artifact_id"] == refs[2].artifact_id}
            if all(row["status"] == "done" for row in rows.values()):
                return "final_checks_passed" if self.final_check(lease, tuple(refs)) is True else "needs_evidence"
            checkpoint = json.loads(run_row["checkpoint_json"] or "{}")
            recovered = checkpoint.get("recovered_patch")
            ready = None
            resuming_patch = False
            resuming_waiting_test = False
            resuming_in_progress = False
            has_tester_commits = False
            if recovered:
                ready = next((
                    t for t in plan.tasks
                    if _task_key(refs[2], t.task_id) == recovered.get("task_id")
                    and rows[_task_key(refs[2], t.task_id)]["status"] == "waiting_test"
                ), None)
                if ready is not None:
                    resuming_patch = True
            if ready is None:
                ready = next((
                    t for t in plan.tasks
                    if rows[_task_key(refs[2], t.task_id)]["status"] == "waiting_test"
                    and all(rows[_task_key(refs[2], d)]["status"] == "done" for d in t.dependencies)
                ), None)
                if ready is not None:
                    resuming_waiting_test = True
            if ready is None:
                ready = next((
                    t for t in plan.tasks
                    if rows[_task_key(refs[2], t.task_id)]["status"] == "in_progress"
                    and all(rows[_task_key(refs[2], d)]["status"] == "done" for d in t.dependencies)
                    and self._can_resume_in_progress(
                        lease, workspace, _task_key(refs[2], t.task_id), rows[_task_key(refs[2], t.task_id)]["repair_round"]
                    )
                ), None)
                if ready is not None:
                    resuming_in_progress = True
            if ready is None:
                ready = next((t for t in plan.tasks if rows[_task_key(refs[2], t.task_id)]["status"] in {"todo","ready","rework"}
                              and all(rows[_task_key(refs[2], d)]["status"] == "done" for d in t.dependencies)), None)
            if ready is None:
                return "needs_evidence"
            key = _task_key(refs[2], ready.task_id)
            current, repairs = rows[key]["status"], rows[key]["repair_round"]
            if resuming_patch:
                receipt = workspace.operation_receipt(recovered["operation_id"])
                if (not receipt or workspace.head() != recovered["output_commit"]
                        or receipt.get("patch_hash") != recovered["patch_hash"]):
                    raise InvalidHandoff("Recovered patch evidence no longer matches workspace")
                changed = sorted(
                    f for f in workspace.git("diff", "--name-only", "-z",
                                             recovered["input_commit"], recovered["output_commit"]).strip("\0").split("\0")
                    if f
                )
                _, latest = self._snapshot(lease)
                patch_ref = self.store.put(
                    lease.project_id, lease.run_id, lease.token, "patch", receipt["diff"], created_by="Dev",
                    expected_previous_version=latest["patch"].version if "patch" in latest else 0,
                    parent_refs=refs,
                )
                dev_payload = DevResult(
                    task_id=key, input_commit=recovered["input_commit"], output_commit=recovered["output_commit"],
                    patch_sha256=recovered["patch_hash"], changed_files=changed,
                    summary="Recovered committed patch without replay",
                )
                dev_ref = self.store.put(
                    lease.project_id, lease.run_id, lease.token, "dev_result", dev_payload, created_by="Dev",
                    expected_previous_version=latest["dev_result"].version if "dev_result" in latest else 0,
                    parent_refs=refs,
                )
                dev = RoleOutput(payload=dev_payload, patch_ref=patch_ref)
                self._check_dev(lease, workspace, recovered["input_commit"], dev)
                self._update_checkpoint(lease, recovered_patch=None, output_commit=recovered["output_commit"])
                ctx = {**context, "task": ready.model_dump(), "attempt": repairs + 1,
                       "input_commit": recovered["input_commit"]}
            elif resuming_waiting_test:
                dev, dev_ref, has_tester_commits = self._recover_waiting_test(lease, workspace, key)
                ctx = {**context, "task": ready.model_dump(), "attempt": repairs + 1,
                       "input_commit": dev.payload.input_commit}
            else:
                if not resuming_in_progress:
                    if current == "todo":
                        current, repairs = self._move_task(lease, key, current, "dependencies_done", repairs)
                    current, repairs = self._move_task(lease, key, current, "start", repairs)
                self._stage(lease, "development")
                base = workspace.head()
                ctx = {**context, "task": ready.model_dump(), "attempt": repairs + 1, "input_commit": base}
                dev_inputs = list(refs)
                if repairs:
                    bug_ref, bug = self._latest_task_bug(lease, key)
                    if bug_ref and bug:
                        ctx["bug_report"] = bug.model_dump()
                        dev_inputs.append(bug_ref)
                self._call(lease, "Orchestrator", refs, {**ctx, "expected_role": "Dev"}, key)
                dev, dev_ref = self._call(lease, "Dev", dev_inputs, ctx, key)
                self._check_dev(lease, workspace, base, dev)
                current, repairs = self._move_task(lease, key, current, "patch_committed", repairs)
            self._stage(lease, "testing")

            max_infra_retries = context.get("config", {}).get("max_infra_retries", 2)
            if type(max_infra_retries) is not int or max_infra_retries < 0:
                raise ValueError("max_infra_retries must be a non-negative integer")
            run_row, _ = self._snapshot(lease)
            checkpoint = json.loads(run_row["checkpoint_json"] or "{}")
            infra_map = dict(checkpoint.get("infra_retries") or {})
            infra_retries = int(infra_map.get(key, 0))

            while not lost.is_set():
                tester_ctx = {
                    **ctx,
                    "input_commit": workspace.head(),
                    "dev_result": dev.payload.model_dump(),
                    "infra_retry": infra_retries,
                }
                if resuming_waiting_test and has_tester_commits:
                    tester_ctx["resume_tester"] = True
                tester, report_ref = self._call(lease, "Tester", [*refs, dev_ref, dev.patch_ref], tester_ctx, key)
                row = self._check_test(lease, workspace, dev.payload, tester)
                for fr in ready.requirement_ids:
                    self.audit.link_fr_chain(lease.project_id, lease.run_id, lease.token, fr_id=fr, task_id=key,
                                             patch_artifact_id=dev.patch_ref.artifact_id, test_report_id=row["id"],
                                             evidence_uri=row["report_uri"])
                if tester.payload.all_passed:
                    self._move_task(lease, key, current, "verified", repairs)
                    break
                if not tester.bug:
                    return "needs_evidence"
                bug = BugReport.model_validate(tester.bug)
                if bug.task_id != key or bug.commit != tester.payload.commit or bug.report not in {report_ref, tester.payload.runner_output}:
                    raise InvalidHandoff("Bug references another task, commit, or report")
                _, latest = self._snapshot(lease)
                bug_ref = self.store.put(
                    lease.project_id, lease.run_id, lease.token, "bug_report", bug, created_by="Tester",
                    expected_previous_version=latest["bug_report"].version if "bug_report" in latest else 0,
                    parent_refs=[report_ref],
                )
                self.audit.record_event(
                    lease.project_id, lease.run_id, lease.token, "bug.recorded",
                    {"task_id": key, "category": bug.category, "bug_artifact_id": bug_ref.artifact_id,
                     "bug_version": bug_ref.version, "repair_round": repairs, "infra_retry": infra_retries},
                    correlation_id=new_id(),
                )
                if bug.category == "code":
                    current, _ = self._move_task(lease, key, current, "code_bug", repairs)
                    if current == "blocked":
                        return "repairs_exhausted"
                    break
                if bug.category in {"requirements", "design"}:
                    route = "Requirement" if bug.category == "requirements" else "Architecture"
                    self._update_checkpoint(lease, revision_route=route, routing_bug=bug_ref.model_dump())
                    self.audit.record_event(
                        lease.project_id, lease.run_id, lease.token, "fault.routed",
                        {"task_id": key, "category": bug.category, "target_role": route,
                         "bug_artifact_id": bug_ref.artifact_id, "bug_version": bug_ref.version},
                        correlation_id=new_id(),
                    )
                    return self._pipeline(lease, lost)
                if bug.category == "infrastructure":
                    if infra_retries < max_infra_retries:
                        infra_retries += 1
                        infra_map[key] = infra_retries
                        self._update_checkpoint(lease, infra_retries=infra_map)
                        self.audit.record_event(
                            lease.project_id, lease.run_id, lease.token, "infra.retry",
                            {"task_id": key, "infra_retry": infra_retries, "max_infra_retries": max_infra_retries,
                             "repair_round": repairs, "bug_artifact_id": bug_ref.artifact_id},
                            correlation_id=new_id(), error_category="environment",
                        )
                        continue
                    self.audit.record_event(
                        lease.project_id, lease.run_id, lease.token, "infra.exhausted",
                        {"task_id": key, "infra_retries": infra_retries, "max_infra_retries": max_infra_retries,
                         "repair_round": repairs, "bug_artifact_id": bug_ref.artifact_id},
                        correlation_id=new_id(), error_category="environment",
                    )
                    return "needs_evidence"
                return "needs_evidence"
        raise StorageConflict("Worker lost ownership")

    def _pipeline(self, lease, lost):
        run, latest = self._snapshot(lease)
        checkpoint = json.loads(run["checkpoint_json"] or "{}")
        route = checkpoint.get("revision_route")
        routing_bug = None
        if checkpoint.get("routing_bug"):
            routing_bug = self._read(lease, ArtifactRef.model_validate(checkpoint["routing_bug"]), BugReport).model_dump()
        with self.database.transaction() as repo:
            project = repo.get_project(lease.project_id)
            rows = repo.for_run(lease.project_id, lease.run_id).records("events")
        context = {"project": project, "config": json.loads(run["config_json"]),
                   "feedback": [json.loads(r["payload_json"]) for r in rows
                                if r["event_type"] in {"clarification.recorded", "gate.revision_requested"}]}
        if routing_bug is not None:
            context["routing_bug"] = routing_bug
        self._call(lease, "Orchestrator", [], {**context, "expected_role": route or "Requirement"})
        req = latest.get("requirements")
        self._stage(lease, "requirements")
        if not req or route == "Requirement":
            _, req = self._call(lease, "Requirement", [req] if req else [], context)
            if route == "Requirement":
                self._update_checkpoint(lease, revision_route=None, routing_bug=None)
                route = None
        requirements = self._read(lease, req, Requirements)
        if not self.gates.is_gate_approved(lease.project_id, lease.run_id, "requirements", [req]):
            return self._gate(lease, "requirements", [req], requirements.questions)
        self._stage(lease, "architecture")
        arch = latest.get("architecture")
        if not arch or route == "Architecture" or self._read(lease, arch, Architecture).requirements != req:
            _, arch = self._call(lease, "Architecture", [req], {**context, "requirements": requirements.model_dump()})
            if route == "Architecture":
                self._update_checkpoint(lease, revision_route=None, routing_bug=None)
                route = None
        architecture = self._read(lease, arch, Architecture)
        self._stage(lease, "planning")
        plan_ref = latest.get("plan")
        plan = self._read(lease, plan_ref, Plan) if plan_ref else None
        if not plan or route == "Planning" or plan.requirements != req or plan.architecture != arch:
            _, plan_ref = self._call(lease, "Planning", [req, arch], {**context, "requirements": requirements.model_dump(),
                                                                     "architecture": architecture.model_dump()})
            plan = self._read(lease, plan_ref, Plan)
            if route == "Planning":
                self._update_checkpoint(lease, revision_route=None, routing_bug=None)
                route = None
        check_handoff(requirements, architecture, plan, req, arch)
        if not self.gates.is_gate_approved(lease.project_id, lease.run_id, "architecture_plan", [arch, plan_ref]):
            return self._gate(lease, "architecture_plan", [arch, plan_ref])
        return self._tasks(lease, lost, [req, arch, plan_ref], plan, context)

    def __call__(self, lease, lost):
        try:
            return self._pipeline(lease, lost)
        except OperationCancelled:
            raise
        except BudgetExceededError:
            return "quota_exceeded"
        except (InvalidHandoff, ValueError, KeyError) as exc:
            detail = str(exc).strip()[:240]
            payload = {"reason": type(exc).__name__}
            if detail:
                payload["detail"] = detail
            self.audit.record_event(lease.project_id, lease.run_id, lease.token, "handoff.rejected",
                                    payload, correlation_id=new_id(), error_category="schema")
            with self.database.transaction() as repo:
                steps = repo.for_run(lease.project_id, lease.run_id).records("agent_steps")
            if any(step["status"] == "started" for step in steps):
                return "effects_uncertain"
            return "invalid_handoff"
