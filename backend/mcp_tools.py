"""The seven local SDLC tools. Each stdio subprocess belongs to one host step."""

import asyncio
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import mcp_types as mt
from mcp import Client, StdioServerParameters
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ConfigDict, Field

from backend.artifacts import ArtifactStore
from backend.gateway import CURRENT_OPERATION, Gateway, HostStep, ToolDenied, allowed_file
from backend.recovery import RunSignal
from backend.storage import Database
from backend.workspace import Edit, content_hash


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReadFile(Args):
    path: str


class Change(Args):
    path: str
    text: str | None
    expected_hash: str | None


class Changes(Args):
    input_commit: str
    edits: list[Change] = Field(min_length=1, max_length=64)


class Diff(Args):
    before: str
    after: str


class Suite(Args):
    suite_id: Literal["build", "smoke", "development"]


class ReadArtifact(Args):
    artifact_id: str
    version: int = Field(ge=1)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")


TOOLS = {
    "workspace.list_files": (Args, "List tracked application and development test files."),
    "workspace.read_file": (ReadFile, "Read a UTF-8 file and compute its current SHA-256."),
    "workspace.apply_patch": (Changes, "Apply expected-hash edits at a specific input commit."),
    "git.status": (Args, "Read the workspace HEAD and its short status."),
    "git.diff": (Diff, "Read the application and test changes between two commits."),
    "tests.run_suite": (Suite, "Execute one host-approved Docker suite on the current commit."),
    "project.read_artifact": (ReadArtifact, "Read an immutable artifact in the calling run."),
}
SCHEMAS = {name: model.model_json_schema() for name, (model, _) in TOOLS.items()}
SERVER_VERSION = "1.0"
OP_KEY = "ktpm/op"
CONFIG_VAR = "KTPM_STEP_TRANSPORT"


@asynccontextmanager
async def step_client(database_path, root, host: HostStep, image=None):
    config = {"database": str(Path(database_path).resolve()), "root": str(Path(root).resolve()),
              "host": asdict(host), "image": image}
    env = {key: val for key, val in os.environ.items()
           if key.upper() in {
               "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
               "LOCALAPPDATA", "USERPROFILE", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT",
           }}
    env[CONFIG_VAR] = json.dumps(config)
    transport = StdioServerParameters(command=sys.executable, args=["-m", "backend.mcp_tools"],
                                      cwd=Path(__file__).resolve().parents[1], env=env)
    async with Client(transport, read_timeout_seconds=215) as client:
        yield client


async def discover(client):
    listing = (await client.list_tools()).tools
    schemas = {tool.name: tool.input_schema for tool in listing}
    payload = json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()
    return {"sdk": version("mcp"), "server": SERVER_VERSION, "protocol": client.protocol_version,
            "tool_schema_sha256": hashlib.sha256(payload).hexdigest(), "tools": schemas}


async def invoke(client, operation_id, tool, args):
    reply = await client.call_tool(tool, args, meta={OP_KEY: operation_id})
    if reply.is_error:
        raise RuntimeError(reply.content[0].text if reply.content else "tool_error")
    if not isinstance(reply.structured_content, dict):
        raise RuntimeError("missing_tool_result")
    return reply.structured_content


class ToolSession:
    def __init__(self, config):
        self.host = HostStep(**config["host"])
        self.database = Database(config["database"])
        self.root = config["root"]
        self.gateway = Gateway(self.database, self.root)
        self.artifacts = ArtifactStore(self.root, self.database)
        self.image = config.get("image")

    def dispatch(self, ws, step, name, args):
        model = TOOLS[name][0].model_validate(args)
        if name == "workspace.list_files":
            names = []
            for path in ws.git("ls-files", "-z", "--", "app", "tests_dev").split("\0"):
                if path:
                    try:
                        names.append(allowed_file(ws, path))
                    except (PermissionError, ValueError):
                        continue
            return {"files": names[:1000], "truncated": len(names) > 1000}
        if name == "workspace.read_file":
            data = ws.read(model.path)
            return {"text": data.decode("utf-8"), "sha256": content_hash(data)}
        if name == "workspace.apply_patch":
            return ws.apply(step["task_id"], model.input_commit, [Edit(**e.model_dump()) for e in model.edits],
                            operation_id=CURRENT_OPERATION.get())
        if name == "git.status":
            return {"head": ws.head(), "status": ws.status()}
        if name == "git.diff":
            data = ws.diff(model.before, model.after)
            return {"diff": data[:ws.patch_limit], "truncated": len(data) > ws.patch_limit}
        if name == "project.read_artifact":
            data = self.artifacts.read(self.host.project_id, self.host.run_id, model.artifact_id,
                                       model.version, model.sha256)
            if len(data) > ws.patch_limit:
                raise ValueError("artifact exceeds tool response limit")
            return {"text": data.decode("utf-8"), "sha256": model.sha256, "version": model.version}
        if not self.image:
            raise RuntimeError("runner profile not configured")
        from backend.docker_runner import DockerRunner
        host = self.host
        runner = DockerRunner(self.image, ws.path / "logs" / "suites")
        sig = RunSignal(self.database, host.project_id, host.run_id, host.lease)
        res_key = sig.started("docker_runner")
        report = None
        try:
            report = runner.run(ws.path, ws.head(), model.suite_id, cancel=sig)
        finally:
            sig.stopped(res_key, confirmed=(report is not None and report.get("status") != "cleanup_error"))
        with self.database.transaction() as repo:
            previous = repo.for_run(host.project_id, host.run_id).latest_version("runner_output")
        ref = self.artifacts.put(host.project_id, host.run_id, host.lease, "runner_output",
                                 json.dumps(report), created_by="runner", expected_previous_version=previous)
        # No process exit code exists if Docker failed before the test process started.
        report_id = None
        if report["exit_code"] is not None:
            with self.database.transaction(write=True) as repo:
                writer = repo.worker_run(host.project_id, host.run_id, host.lease)
                report_id = writer.add_report(step["task_id"], report["commit"], model.suite_id,
                    "logs/suites/" + report["report_id"] + "/report.json", report["exit_code"],
                    report["passed"], report["failed"], report["skipped"], report["errors"],
                    int(report["duration_seconds"] * 1000))
        # DockerRunner writes a bounded, redacted log to this operation's host-owned directory.
        tail = (runner.report_root / report["report_id"] / "runner.log").read_bytes()[-8192:]
        return {"report": report, "report_id": report_id, "runner_output": ref.model_dump(),
                "log_tail": tail.decode("utf-8", errors="replace")}

    def make_server(self):
        async def list_tools(ctx, params):
            return mt.ListToolsResult(tools=[mt.Tool(name=k, description=v[1], input_schema=SCHEMAS[k])
                                             for k, v in TOOLS.items()])

        async def call(ctx, params):
            operation = (params.meta or {}).get(OP_KEY, "")
            try:
                result = await asyncio.to_thread(self.gateway.call, self.host, operation, params.name,
                                                 params.arguments or {}, self.dispatch)
            except (ToolDenied, ValueError):
                return mt.CallToolResult(is_error=True, content=[mt.TextContent(type="text", text="tool_denied")])
            except Exception:
                return mt.CallToolResult(is_error=True, content=[mt.TextContent(type="text", text="tool_error")])
            return mt.CallToolResult(content=[mt.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                                     structured_content=result)
        return Server("ktpm-workspace", version=SERVER_VERSION, on_list_tools=list_tools, on_call_tool=call)


async def main():
    session = ToolSession(json.loads(os.environ.pop(CONFIG_VAR)))
    server = session.make_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
