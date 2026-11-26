"""Dev and Tester consume trusted work orders and use real, step-bound MCP tools."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.approvals import ApprovalService
from backend.contracts import DevResult
from backend.llm import invoke as infer
from backend.mcp_tools import discover, invoke, step_client
from backend.gateway import HostStep
from backend.skill_registry import RunSkills


class FileChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    text: str | None


class PatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1)
    blocker: str | None
    files: list[FileChange] = Field(max_length=64)


class CodingAgents:
    def __init__(self, store, image, *, model=infer, skill_root=None):
        self.store = store
        self.db = store.database
        self.gates = ApprovalService(self.db)
        self.image = image
        self.model = model
        self.skill_root = Path(skill_root or Path(__file__).resolve().parents[1] / "skills")

    def __call__(self, order):
        from backend.orchestrator import RoleOutput
        return RoleOutput(**asyncio.run(self.execute(order)))

    def _check_inputs(self, order):
        if order.role != "Dev" or not order.task_id or len(order.inputs) < 3:
            raise ValueError("Dev requires an assigned task and three design references")
        project, run = order.project_id, order.run_id
        req, arch, plan = order.inputs[:3]
        if not (self.gates.is_gate_approved(project, run, "requirements", [req]) and
                self.gates.is_gate_approved(project, run, "architecture_plan", [arch, plan])):
            raise ValueError("missing current design approvals")
        with self.db.transaction() as repo:
            writer = repo.worker_run(project, run, order.lease_token)
            task = next((t for t in writer.records("tasks") if t["id"] == order.task_id), None)
            if not task or task["status"] != "in_progress" or task["plan_artifact_id"] != plan.artifact_id:
                raise ValueError("task is not active under this plan")
        if not self.image:
            raise ValueError("missing Docker runner image")

    def _artifact(self, order, kind, content):
        with self.db.transaction() as repo:
            prior = repo.for_run(order.project_id, order.run_id).latest_version(kind)
        return self.store.put(order.project_id, order.run_id, order.lease_token, kind, content,
                              created_by=order.role, expected_previous_version=prior, parent_refs=order.inputs)

    async def execute(self, order):
        self._check_inputs(order)
        host = HostStep(order.project_id, order.run_id, order.step_id, order.lease_token)
        run_dir = self.store.root / host.project_id / host.run_id
        skills = RunSkills(self.skill_root, enabled=order.context.get("config", {}).get("skills_enabled", True))
        skills.bind(run_dir / "skills.json")
        async with step_client(self.db.path, self.store.root, host, self.image) as client:
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
            paths = [p for p in task["files"] if p in existing]
            read_files = {}
            for p in paths:
                read_files[p] = await tool("workspace.read_file", path=p)
            artifacts = []
            for ref in order.inputs[:3]:
                doc = await tool("project.read_artifact", artifact_id=ref.artifact_id,
                                 version=ref.version, sha256=ref.sha256)
                artifacts.append(doc["text"])
            details = {"task": task, "source_artifacts":artifacts, "known_files":sorted(existing),
                       "files":read_files, "bug":order.context.get("bug_report")}
            if len(json.dumps(details, ensure_ascii=False)) > 220_000:
                raise ValueError("task exceeds model context allowance")
            prompt = (skills.context(order.role) + "\nImplement only the assigned task. Return summary, blocker "
                      "(null if implemented), and whole UTF-8 file replacements in files [{path,text}]. "
                      "Use null text only to delete an existing file you inspected. Only change app/. "
                      "For a frontend task include the reproducible npm lockfile. Respond with JSON and "
                      "empty tool_proposals. Host applies the patch and runs a real suite. Task data:\n"
                      + json.dumps(details, ensure_ascii=False))
            reply = await asyncio.to_thread(self.model, prompt, PatchPlan.model_json_schema())
            proposal = PatchPlan.model_validate(reply.output)
            self._artifact(order, "log", json.dumps({"model":reply.model, "usage":reply.usage,
                "usage_complete":reply.usage_complete, "prompt_sha256":reply.prompt_sha256,
                "config_sha256":reply.config_sha256, "tools_sha256":descriptor["tool_schema_sha256"]}))
            if proposal.blocker or not proposal.files:
                raise ValueError("Dev blocked: " + (proposal.blocker or "empty patch"))
            edits = []
            for item in proposal.files:
                if item.path in existing and item.path not in read_files:
                    raise ValueError("missing original file observation")
                edits.append({"path": item.path, "expected_hash":read_files.get(item.path, {}).get("sha256"),
                              "text":item.text})
            receipt = await tool("workspace.apply_patch", input_commit=base, edits=edits)
            patch = self._artifact(order, "patch", receipt["diff"])
            suite = "smoke" if "tests_dev/test_smoke.py" in existing else "build"
            check = await tool("tests.run_suite", suite_id=suite)
            self._artifact(order, "log", json.dumps({"self_check":check,"patch_id":receipt["patch_id"]}))
            payload = DevResult(task_id=order.task_id, input_commit=base, output_commit=receipt["output_commit"],
                                patch_sha256=receipt["patch_hash"], changed_files=[item.path for item in proposal.files],
                                summary=proposal.summary)
            usage = {**reply.usage, "usage_complete":reply.usage_complete,
                     "cached_tokens":reply.usage.get("cache_read_tokens")}
            return {"payload":payload,"usage":usage,"patch_ref":patch}
