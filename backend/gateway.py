"""Authenticate a host step and authorize each MCP operation before executing it."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from backend.storage import StorageConflict
from backend.workspace import Workspace


POLICY = json.loads((Path(__file__).resolve().parents[1] / "docs" / "quyen-cong-cu.json").read_text("utf-8"))
ROLES = {name.lower(): item for name, item in POLICY["roles"].items()}
FIELDS = {
    "workspace.list_files": set(),
    "workspace.read_file": {"path"},
    "workspace.apply_patch": {"input_commit", "edits"},
    "git.status": set(),
    "git.diff": {"before", "after"},
    "tests.run_suite": {"suite_id"},
    "project.read_artifact": {"artifact_id", "version", "sha256"},
}
PRIVATE_PARTS = {"credentials", "credentials.json", "secrets", "secrets.json", "id_rsa", "id_ed25519",
                 ".npmrc", ".pypirc", ".netrc", ".aws", ".ssh", ".docker", ".kube"}
PRIVATE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".kdbx")


class ToolDenied(PermissionError):
    pass


@dataclass(frozen=True)
class HostStep:
    project_id: str
    run_id: str
    step_id: str
    lease: str


def _audit_shape(value, depth=0):
    """Record counts/types, never arbitrary field names, code, values, tokens or exceptions."""
    if depth == 4:
        return {"type": "nested"}
    if isinstance(value, dict):
        return {"type": "object", "count": len(value),
                "fields": [_audit_shape(v, depth+1) for v in list(value.values())[:8]]}
    if isinstance(value, list):
        return {"type": "array", "count": len(value),
                "items": [_audit_shape(v, depth+1) for v in value[:4]]}
    return {"type": type(value).__name__}


def allowed_file(workspace, path):
    workspace._file(path)
    if any(part.casefold() in PRIVATE_PARTS or part.casefold().endswith(PRIVATE_SUFFIXES)
           for part in path.split("/")):
        raise ToolDenied("private_file")
    return path


class Gateway:
    def __init__(self, database, workspace_root):
        self.database = database
        self.root = workspace_root

    def call(self, host, operation_id, tool, args, dispatch):
        if not isinstance(operation_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", operation_id):
            raise ToolDenied("invalid_operation")
        started = monotonic()
        name = tool if tool in FIELDS else "unknown"
        workspace = Workspace(self.root, host.project_id, host.run_id)
        denied = None
        with self.database.transaction(write=True) as repo:
            try:
                worker = repo.worker_run(host.project_id, host.run_id, host.lease)
            except (KeyError, StorageConflict) as exc:
                logging.getLogger(__name__).warning("tool_denied: inactive host lease or mismatched run")
                raise ToolDenied("inactive_host") from exc
            step = next((s for s in worker.records("agent_steps") if s["id"] == host.step_id
                         and s["status"] == "started"), None)
            if step is None:
                worker.add_event("tool.denied", {"reason": "inactive_step", "tool": name})
                denied = "inactive_step"
            else:
                worker.add_tool_call(step["id"], operation_id, name, _audit_shape(args))
                try:
                    self._authorize(worker, step, workspace, tool, args)
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    denied = "tool_denied"
                    worker.finish_tool_call(operation_id, "denied", None, 0)
                    worker.add_event("tool.denied", {"tool": name, "reason": type(exc).__name__,
                                                     "operation_id": operation_id}, step["id"])
        if denied:
            raise ToolDenied(denied)
        try:
            result = dispatch(workspace, step, tool, args)
        except Exception:
            self._finish(host, operation_id, name, started, "error", {})
            raise RuntimeError("tool_error") from None
        self._finish(host, operation_id, name, started, "ok", _audit_shape(result))
        return result

    def _finish(self, host, operation, name, started, status, summary):
        with self.database.transaction(write=True) as repo:
            worker = repo.worker_run(host.project_id, host.run_id, host.lease)
            worker.finish_tool_call(operation, status, None, int((monotonic() - started) * 1000))
            worker.add_event("tool." + status, {"operation_id": operation, "tool": name, "result": summary},
                             host.step_id)

    def _authorize(self, worker, step, workspace, tool, args):
        role = ROLES[step["agent_role"]]
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
            if not any((r["id"], r["version"], r["sha256"]) ==
                       (args["artifact_id"], args["version"], args["sha256"]) for r in worker.records("artifacts")):
                raise ToolDenied("artifact_not_in_run")
