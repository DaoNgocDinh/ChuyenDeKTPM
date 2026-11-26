"""Dev and Tester consume trusted work orders and use real, step-bound MCP tools."""

import asyncio
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.approvals import ApprovalService
from backend.contracts import ArtifactRef, BugReport, DevResult, TestReport
from backend.gateway import HostStep
from backend.llm import invoke as infer
from backend.mcp_tools import discover, invoke, step_client
from backend.skill_registry import RunSkills


Severity = Literal["critical", "high", "medium", "low"]
BugCategory = Literal["code", "requirements", "design", "infrastructure"]
INFRA_STATUSES = frozenset({"infrastructure_error", "timeout", "cancelled", "cleanup_error"})
SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


class FileChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    text: str | None


class PatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1)
    blocker: str | None
    files: list[FileChange] = Field(max_length=64)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    severity: Severity
    file: str = Field(min_length=1)
    message: str = Field(min_length=1)
    requirement_id: str | None


class TesterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1)
    suite_id: Literal["build", "smoke", "development"]
    test_files: list[FileChange] = Field(max_length=64)
    review_findings: list[ReviewFinding] = Field(max_length=64)


class BugDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1)
    severity: Severity
    category: BugCategory
    requirement_ids: list[str] = Field(min_length=1)
    reproduce: list[str] = Field(min_length=1)
    expected: str = Field(min_length=1)
    actual: str = Field(min_length=1)
    findings: list[ReviewFinding] = Field(max_length=64)


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["review_report"] = "review_report"
    task_id: str = Field(min_length=1)
    commit: str = Field(min_length=1)
    dev_commit: str = Field(min_length=1)
    suite_id: str = Field(min_length=1)
    runner_output: ArtifactRef
    requirement_ids: list[str] = Field(min_length=1)
    verdict: Literal["pass", "fail"]
    severity: Severity | None
    summary: str = Field(min_length=1)
    findings: list[ReviewFinding]


def _merge_usage(replies):
    usage = {}
    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "thinking_tokens", "total_tokens"):
        values = [r.usage[key] for r in replies if key in r.usage and isinstance(r.usage[key], int)]
        if values:
            usage[key] = sum(values)
    usage["usage_complete"] = all(r.usage_complete for r in replies)
    usage["cached_tokens"] = usage.get("cache_read_tokens")
    return usage


def _max_severity(findings, fallback=None):
    ranked = [f.severity for f in findings]
    if fallback is not None:
        ranked.append(fallback)
    if not ranked:
        return None
    return max(ranked, key=lambda item: SEVERITY_ORDER[item])


def _dedupe_findings(*groups):
    seen = set()
    merged = []
    for group in groups:
        for finding in group:
            key = (finding.severity, finding.file, finding.message, finding.requirement_id)
            if key not in seen:
                seen.add(key)
                merged.append(finding)
    return merged


def _unwrap_group(exc):
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


class CodingAgents:
    def __init__(self, store, image, *, model=infer, skill_root=None, client_factory=step_client):
        self.store = store
        self.db = store.database
        self.gates = ApprovalService(self.db)
        self.image = image
        self.model = model
        self.skill_root = Path(skill_root or Path(__file__).resolve().parents[1] / "skills")
        self.client_factory = client_factory

    def __call__(self, order):
        from backend.orchestrator import RoleOutput
        return RoleOutput(**asyncio.run(self.execute(order)))

    def _check_design_approvals(self, order):
        project, run = order.project_id, order.run_id
        req, arch, plan = order.inputs[:3]
        if not (self.gates.is_gate_approved(project, run, "requirements", [req]) and
                self.gates.is_gate_approved(project, run, "architecture_plan", [arch, plan])):
            raise ValueError("missing current design approvals")
        return req, arch, plan

    def _check_inputs(self, order):
        if order.role != "Dev" or not order.task_id or len(order.inputs) < 3:
            raise ValueError("Dev requires an assigned task and three design references")
        _, _, plan = self._check_design_approvals(order)
        with self.db.transaction() as repo:
            writer = repo.worker_run(order.project_id, order.run_id, order.lease_token)
            task = next((t for t in writer.records("tasks") if t["id"] == order.task_id), None)
            if not task or task["status"] != "in_progress" or task["plan_artifact_id"] != plan.artifact_id:
                raise ValueError("task is not active under this plan")
        if not self.image:
            raise ValueError("missing Docker runner image")

    def _check_tester_inputs(self, order):
        if order.role != "Tester" or not order.task_id or len(order.inputs) < 5:
            raise ValueError("Tester requires an assigned task, design references, DevResult, and patch")
        _, _, plan = self._check_design_approvals(order)
        with self.db.transaction() as repo:
            writer = repo.worker_run(order.project_id, order.run_id, order.lease_token)
            task = next((t for t in writer.records("tasks") if t["id"] == order.task_id), None)
            if not task or task["status"] != "waiting_test" or task["plan_artifact_id"] != plan.artifact_id:
                raise ValueError("task is not awaiting test under this plan")
        raw_dev = order.context.get("dev_result")
        if not raw_dev:
            raise ValueError("Tester requires DevResult context")
        dev = DevResult.model_validate(raw_dev)
        infra_retry = int(order.context.get("infra_retry", 0) or 0)
        input_commit = order.context.get("input_commit")
        if dev.task_id != order.task_id or not input_commit or (infra_retry == 0 and dev.output_commit != input_commit):
            raise ValueError("DevResult does not match assigned task or commit")
        if not self.image:
            raise ValueError("missing Docker runner image")
        return dev

    def _artifact(self, order, kind, content, *, extra_parents=()):
        with self.db.transaction() as repo:
            prior = repo.for_run(order.project_id, order.run_id).latest_version(kind)
        parents = [*order.inputs, *extra_parents]
        return self.store.put(order.project_id, order.run_id, order.lease_token, kind, content,
                              created_by=order.role, expected_previous_version=prior, parent_refs=parents)

    def _log_model(self, order, reply, descriptor, *, phase):
        self._artifact(order, "log", json.dumps({
            "phase": phase, "model": reply.model, "usage": reply.usage,
            "usage_complete": reply.usage_complete, "prompt_sha256": reply.prompt_sha256,
            "config_sha256": reply.config_sha256, "tools_sha256": descriptor["tool_schema_sha256"],
        }))

    async def execute(self, order):
        try:
            if order.role == "Dev":
                return await self._execute_dev(order)
            if order.role == "Tester":
                return await self._execute_tester(order)
        except BaseExceptionGroup as eg:
            leaf = _unwrap_group(eg)
            if leaf is not eg:
                raise leaf from None
            raise
        raise ValueError("unsupported coding role: " + str(order.role))

    async def _execute_dev(self, order):
        self._check_inputs(order)
        host = HostStep(order.project_id, order.run_id, order.step_id, order.lease_token)
        run_dir = self.store.root / host.project_id / host.run_id
        skills = RunSkills(self.skill_root, enabled=order.context.get("config", {}).get("skills_enabled", True))
        skills.bind(run_dir / "skills.json")
        async with self.client_factory(self.db.path, self.store.root, host, self.image) as client:
            async def tool(name, **args):
                return await invoke(client, uuid4().hex, name, args)
            descriptor = await discover(client)
            base = (await tool("git.status"))["head"]
            if base != order.context["input_commit"]:
                raise ValueError("workspace commit changed before dispatch")
            catalog = await tool("workspace.list_files")
            if catalog["truncated"]:
                raise ValueError("file catalog exceeds limit")
            existing = set(catalog["files"])
            task = order.context["task"]
            bug_report = order.context.get("bug_report")
            paths = [p for p in task["files"] if p in existing]
            read_files = {}
            for p in paths:
                read_files[p] = await tool("workspace.read_file", path=p)
            test_files = {}
            if bug_report:
                read_size = len(json.dumps(read_files, ensure_ascii=False))
                for p in sorted(f for f in existing if f.startswith("tests_dev/")):
                    observed = await tool("workspace.read_file", path=p)
                    entry_size = len(json.dumps({p: observed}, ensure_ascii=False))
                    if read_size + entry_size > 140_000:
                        break
                    test_files[p] = observed
                    read_size += entry_size
            artifacts = []
            for ref in order.inputs[:3]:
                doc = await tool("project.read_artifact", artifact_id=ref.artifact_id,
                                 version=ref.version, sha256=ref.sha256)
                artifacts.append(doc["text"])
            details = {"task": task, "source_artifacts": artifacts, "known_files": sorted(existing),
                       "files": read_files, "bug": bug_report}
            if test_files:
                details["test_files"] = test_files
            if len(json.dumps(details, ensure_ascii=False)) > 220_000:
                raise ValueError("task exceeds model context allowance")
            rework_hint = (
                " This is a repair round for the attached bug report: fix the root cause in app/ "
                "and keep all existing regression tests in tests_dev/ passing." if bug_report else ""
            )
            prompt = (skills.context(order.role) + "\nImplement only the assigned task." + rework_hint
                      + " Return summary, blocker "
                      "(null if implemented), and whole UTF-8 file replacements in files [{path,text}]. "
                      "Use null text only to delete an existing file you inspected. Only change app/. "
                      "For a frontend task include the reproducible npm lockfile. Respond with JSON and "
                      "empty tool_proposals. Host applies the patch and runs a real suite. Task data:\n"
                      + json.dumps(details, ensure_ascii=False))
            reply = await asyncio.to_thread(self.model, prompt, PatchPlan.model_json_schema())
            proposal = PatchPlan.model_validate(reply.output)
            self._log_model(order, reply, descriptor, phase="dev")
            if proposal.blocker or not proposal.files:
                raise ValueError("Dev blocked: " + (proposal.blocker or "empty patch"))
            edits = []
            for item in proposal.files:
                if item.path in existing and item.path not in read_files:
                    raise ValueError("missing original file observation")
                edits.append({"path": item.path, "expected_hash": read_files.get(item.path, {}).get("sha256"),
                              "text": item.text})
            receipt = await tool("workspace.apply_patch", input_commit=base, edits=edits)
            patch = self._artifact(order, "patch", receipt["diff"])
            if bug_report and any(p.startswith("tests_dev/") for p in existing):
                suite = "development"
            else:
                suite = "smoke" if "tests_dev/test_smoke.py" in existing else "build"
            check = await tool("tests.run_suite", suite_id=suite)
            self._artifact(order, "log", json.dumps({"self_check": check, "patch_id": receipt["patch_id"]}))
            payload = DevResult(task_id=order.task_id, input_commit=base, output_commit=receipt["output_commit"],
                                patch_sha256=receipt["patch_hash"], changed_files=[item.path for item in proposal.files],
                                summary=proposal.summary)
            return {"payload": payload, "usage": _merge_usage([reply]), "patch_ref": patch}

    async def _execute_tester(self, order):
        dev = self._check_tester_inputs(order)
        host = HostStep(order.project_id, order.run_id, order.step_id, order.lease_token)
        run_dir = self.store.root / host.project_id / host.run_id
        skills = RunSkills(self.skill_root, enabled=order.context.get("config", {}).get("skills_enabled", True))
        skills.bind(run_dir / "skills.json")
        async with self.client_factory(self.db.path, self.store.root, host, self.image) as client:
            async def tool(name, **args):
                return await invoke(client, uuid4().hex, name, args)
            descriptor = await discover(client)
            base = (await tool("git.status"))["head"]
            if base != order.context["input_commit"]:
                raise ValueError("workspace commit changed before Tester dispatch")
            diff_res = await tool("git.diff", before=dev.input_commit, after=dev.output_commit)
            catalog = await tool("workspace.list_files")
            if catalog["truncated"]:
                raise ValueError("file catalog exceeds limit")
            existing = set(catalog["files"])
            task = order.context["task"]
            primary_paths = []
            for p in [*dev.changed_files, *task.get("files", [])]:
                if p in existing and p not in primary_paths:
                    primary_paths.append(p)
            test_paths = sorted(p for p in existing if p.startswith("tests_dev/") and p not in primary_paths)
            read_files = {}
            for p in primary_paths:
                read_files[p] = await tool("workspace.read_file", path=p)
            read_size = len(json.dumps(read_files, ensure_ascii=False))
            for p in test_paths:
                observed = await tool("workspace.read_file", path=p)
                entry_size = len(json.dumps({p: observed}, ensure_ascii=False))
                if read_size + entry_size > 140_000:
                    break
                read_files[p] = observed
                read_size += entry_size
            artifacts = []
            for ref in order.inputs[:5]:
                doc = await tool("project.read_artifact", artifact_id=ref.artifact_id,
                                 version=ref.version, sha256=ref.sha256)
                artifacts.append(doc["text"])
            details = {
                "task": task,
                "dev_result": dev.model_dump(),
                "diff": diff_res["diff"],
                "diff_truncated": diff_res["truncated"],
                "source_artifacts": artifacts,
                "known_files": sorted(existing),
                "files": read_files,
                "attempt": order.context.get("attempt", 1),
            }
            if len(json.dumps(details, ensure_ascii=False)) > 220_000:
                raise ValueError("Tester context exceeds model allowance")
            plan_prompt = (
                skills.context(order.role)
                + "\nReview the Dev diff and source files against the FRs, acceptance criteria, architecture, "
                "and task done conditions. Author or update development tests ONLY under tests_dev/ covering "
                "happy path, invalid input, boundary cases, and regression for prior tasks. Never edit app/ "
                "or reference evaluation/. Return summary, suite_id ('development' to run all tests_dev/ "
                "tests including regression, or 'smoke'/'build'), whole UTF-8 replacements in test_files "
                "(empty list [] if existing tests_dev/ already covers the task on retest), and structured "
                "review_findings [{severity,file,message,requirement_id}]. Respond with JSON and empty "
                "tool_proposals. Host applies the patch and runs the real suite. Review data:\n"
                + json.dumps(details, ensure_ascii=False)
            )
            plan_reply = await asyncio.to_thread(self.model, plan_prompt, TesterPlan.model_json_schema())
            plan_out = TesterPlan.model_validate(plan_reply.output)
            self._log_model(order, plan_reply, descriptor, phase="tester_plan")
            replies = [plan_reply]

            edits = []
            for item in plan_out.test_files:
                if (item.path.startswith("tests_dev/") and item.path in read_files
                        and item.text == read_files[item.path]["text"]):
                    continue
                if item.path.startswith("tests_dev/") and item.path in existing and item.path not in read_files:
                    raise ValueError("missing original file observation")
                edits.append({
                    "path": item.path,
                    "expected_hash": read_files.get(item.path, {}).get("sha256"),
                    "text": item.text,
                })

            tested_commit = base
            test_patch_id = None
            if edits:
                receipt = await tool("workspace.apply_patch", input_commit=base, edits=edits)
                tested_commit = receipt["output_commit"]
                test_patch_id = receipt["patch_id"]
            elif plan_out.suite_id in {"smoke", "development"} and not any(
                p.startswith("tests_dev/") for p in existing
            ):
                raise ValueError("Tester must provide development tests before running test suite")

            suite_res = await tool("tests.run_suite", suite_id=plan_out.suite_id)
            report = suite_res["report"]
            report_id = suite_res["report_id"]
            runner_ref = ArtifactRef.model_validate(suite_res["runner_output"])
            log_tail = suite_res.get("log_tail", "")
            self._artifact(order, "log", json.dumps({
                "phase": "tester_run",
                "suite_id": plan_out.suite_id,
                "test_patch_id": test_patch_id,
                "report_id": report_id,
                "report": report,
                "runner_output": runner_ref.model_dump(),
            }), extra_parents=(runner_ref,))
            if report.get("commit") != tested_commit:
                raise ValueError("runner report commit does not match tested workspace commit")

            requirement_ids = list(task.get("requirement_ids") or [])
            if not requirement_ids:
                raise ValueError("task missing requirement_ids")

            if report.get("exit_code") is None or not report_id:
                infra_finding = ReviewFinding(
                    severity="critical",
                    file="tests_dev/",
                    message=f"Runner failed before test process exit ({report.get('status')}): {log_tail[-400:].strip() or 'no log'}",
                    requirement_id=requirement_ids[0],
                )
                review = ReviewReport(
                    task_id=order.task_id,
                    commit=tested_commit,
                    dev_commit=dev.output_commit,
                    suite_id=plan_out.suite_id,
                    runner_output=runner_ref,
                    requirement_ids=requirement_ids,
                    verdict="fail",
                    severity="critical",
                    summary=f"Runner infrastructure failure ({report.get('status')}).",
                    findings=_dedupe_findings(plan_out.review_findings, [infra_finding]),
                )
                self._artifact(order, "document", review.model_dump_json(indent=2), extra_parents=(runner_ref,))
                raise ValueError("Tester runner infrastructure error: " + str(report.get("status")))

            test_report = TestReport(
                task_id=order.task_id,
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
            findings = list(plan_out.review_findings)
            review_summary = plan_out.summary
            review_severity = _max_severity(findings)
            verdict: Literal["pass", "fail"] = "pass" if test_report.all_passed else "fail"

            if not test_report.all_passed:
                diag_data = {
                    "task": task,
                    "dev_result": dev.model_dump(),
                    "test_report": test_report.model_dump(),
                    "runner_status": report.get("status"),
                    "log_tail": log_tail[-8192:],
                    "initial_findings": [f.model_dump() for f in plan_out.review_findings],
                    "diff": diff_res["diff"][:40_000],
                }
                diag_prompt = (
                    skills.context(order.role)
                    + "\nThe real test suite did NOT pass. Diagnose the failure strictly from the runner "
                    "report and log_tail. Classify category accurately: 'code' for an implementation bug "
                    "in app/, 'requirements' if the FR/acceptance criteria are contradictory or ambiguous, "
                    "'design' if the architecture/API/plan contract is inconsistent, or 'infrastructure' "
                    "for runner/environment/timeout/dependency failures (not app logic). Provide concrete "
                    "reproduce steps, expected behavior, actual observed output from runner/log_tail, "
                    "affected requirement_ids, severity, summary, and findings. Respond with JSON and empty "
                    "tool_proposals. Failure evidence:\n"
                    + json.dumps(diag_data, ensure_ascii=False)
                )
                diag_reply = await asyncio.to_thread(self.model, diag_prompt, BugDiagnosis.model_json_schema())
                diagnosis = BugDiagnosis.model_validate(diag_reply.output)
                self._log_model(order, diag_reply, descriptor, phase="tester_diagnosis")
                replies.append(diag_reply)

                category: BugCategory = diagnosis.category
                if report.get("status") in INFRA_STATUSES:
                    category = "infrastructure"

                bug = BugReport(
                    task_id=order.task_id,
                    commit=test_report.commit,
                    report=runner_ref,
                    requirement_ids=diagnosis.requirement_ids,
                    reproduce=diagnosis.reproduce,
                    expected=diagnosis.expected,
                    actual=diagnosis.actual,
                    category=category,
                )
                findings = _dedupe_findings(plan_out.review_findings, diagnosis.findings)
                review_summary = diagnosis.summary
                review_severity = _max_severity(findings, fallback=diagnosis.severity)

            review = ReviewReport(
                task_id=order.task_id,
                commit=test_report.commit,
                dev_commit=dev.output_commit,
                suite_id=test_report.suite_id,
                runner_output=runner_ref,
                requirement_ids=requirement_ids,
                verdict=verdict,
                severity=review_severity,
                summary=review_summary,
                findings=findings,
            )
            self._artifact(order, "document", review.model_dump_json(indent=2), extra_parents=(runner_ref,))

            return {
                "payload": test_report,
                "usage": _merge_usage(replies),
                "report_id": report_id,
                "bug": bug,
            }
