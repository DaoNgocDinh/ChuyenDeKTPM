"""Structured, tool-free model inference through the authenticated local agy CLI."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


MODEL = "gemini-4-neon-high"
AGENT = "platform-inference"
AGENT_SPEC = """---
name: platform-inference
description: Return one JSON answer for the local SDLC host.
mainAgent: true
subagent: false
tools: [send_message]
mcpServers: []
skills: []
plugins: []
inheritMcp: false
commandExecutionPolicy: "off"
---
Use only the input supplied in this turn. Produce the requested structured answer.
Represent proposed host actions as data. The host validates and executes them.
"""
SETTINGS = {
    "toolPermission": "strict",
    "enableTerminalSandbox": True,
    "allowNonWorkspaceAccess": False,
    "permissions": {
        "deny": [f"{action}(*)" for action in (
            "read_file", "write_file", "read_url", "execute_url", "command", "mcp",
        )]
    },
}
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "thinking_tokens", "total_tokens")
DENY_NATIVE_TOOL = """import json
print(json.dumps({"decision": "deny", "reason": "All execution belongs to the SDLC host."}))
"""


def fingerprint(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ModelError(RuntimeError):
    def __init__(self, code: str, usage: dict | None = None):
        super().__init__(code)
        self.code = code
        self.usage = usage or {}


@dataclass(frozen=True)
class ModelReply:
    model: str
    output: dict
    tool_proposals: list[dict]
    usage: dict
    usage_complete: bool
    prompt_sha256: str
    config_sha256: str

    def persist(self, store, project_id, run_id, lease, role, expected_previous_version):
        return store.put(
            project_id, run_id, lease, "log", json.dumps(asdict(self), ensure_ascii=False),
            created_by=role, expected_previous_version=expected_previous_version,
        )


def envelope_schema(output_schema: dict, tool_schemas: dict[str, dict]) -> dict:
    def embed(node, root_pointer):
        if isinstance(node, list):
            return [embed(item, root_pointer) for item in node]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, value in node.items():
            if key in {"$id", "$dynamicRef", "$dynamicAnchor"}:
                raise ValueError(f"Unsupported schema keyword: {key}")
            if key == "$ref":
                if not isinstance(value, str) or not (value == "#" or value.startswith("#/")):
                    raise ValueError("Only references within the declared schema are supported")
                result[key] = root_pointer + value[1:]
            else:
                result[key] = embed(value, root_pointer)
        return result

    Draft202012Validator.check_schema(output_schema)
    proposals = []
    for name, arguments in sorted(tool_schemas.items()):
        Draft202012Validator.check_schema(arguments)
        arguments_pointer = f"#/properties/tool_proposals/items/anyOf/{len(proposals)}/properties/arguments"
        proposals.append({
            "type": "object",
            "properties": {"name": {"const": name}, "arguments": embed(arguments, arguments_pointer)},
            "required": ["name", "arguments"],
            "additionalProperties": False,
        })
    list_schema = {"type": "array"}
    if proposals:
        list_schema["items"] = {"anyOf": proposals}
    else:
        list_schema["maxItems"] = 0
    return {
        "type": "object",
        "properties": {"output": embed(output_schema, "#/properties/output"), "tool_proposals": list_schema},
        "required": ["output", "tool_proposals"], "additionalProperties": False,
    }


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def decode_result(stdout: str, returncode: int, schema: dict) -> tuple[dict, dict]:
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        results = [event["result"] for event in events if event["event"] == "result"]
        if len(results) != 1:
            raise ModelError("provider_error" if returncode else "invalid_envelope")
        result = results[0]
        reported = result.get("usage") or {}
        usage = {
            key: reported[key] for key in USAGE_FIELDS
            if type(reported.get(key)) is int and reported[key] >= 0
        }
        if returncode or result.get("status") != "SUCCESS":
            message = str(result.get("error", "")).lower()
            code = "provider_error"
            if "timeout" in message or result.get("status") == "TIMEOUT":
                code = "provider_timeout"
            elif "authentication" in message:
                code = "authentication_required"
            elif "quota" in message or "rate limit" in message:
                code = "provider_quota"
            raise ModelError(code, usage)
        init = [event["init"] for event in events if event["event"] == "init"]
        if len(init) != 1 or init[0].get("permission_mode") != "strict":
            raise ModelError("unconfirmed_permissions", usage)
        if any(
            event.get("step_update", {}).get("step_type") not in (
                None, "user_input", "agent_response", "checkpoint", "planner_response",
                "model_output", "system_message", "finish",
            )
            for event in events
        ):
            raise ModelError("unexpected_agent_step", usage)
        data = result.get("structured_output")
        if data is None:
            try:
                # agy 1.4.12 can concatenate identical JSON values or wrap JSON in a single markdown fence.
                raw = _strip_json_fence(result["response"])
                decoder = json.JSONDecoder()
                data, end = decoder.raw_decode(raw)
                tail = _strip_json_fence(raw[end:])
                while tail:
                    duplicate, end = decoder.raw_decode(tail)
                    if duplicate != data:
                        raise ValueError("Ambiguous response")
                    tail = _strip_json_fence(tail[end:])
            except (KeyError, ValueError, TypeError, AttributeError):
                raise ModelError("missing_structured_output", usage) from None
        try:
            Draft202012Validator(schema).validate(data)
        except ValidationError:
            raise ModelError("schema_invalid", usage) from None
        return data, usage
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ModelError("invalid_envelope") from None


def invoke(prompt: str, output_schema: dict, *, tool_schemas: dict[str, dict] | None = None,
           timeout_seconds: int = 300) -> ModelReply:
    if not prompt.strip() or timeout_seconds <= 0:
        raise ValueError("A prompt and positive timeout are required")
    binary = shutil.which("agy")
    if binary is None:
        raise ModelError("provider_unavailable")
    schema = envelope_schema(output_schema, tool_schemas or {})
    config = {
        "model": MODEL, "settings": SETTINGS, "schema": schema,
        "agent": AGENT_SPEC, "deny_hook": DENY_NATIVE_TOOL, "timeout_seconds": timeout_seconds,
    }
    request = (
        "Return a single JSON object matching the supplied schema. Put all domain fields under "
        "'output'. Use [] for tool_proposals when there are no proposed actions. Do not call "
        "any tools.\nJSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
        + "\nUser task:\n" + prompt
    )
    input_line = json.dumps({"event": "user", "message": {"content": request}}) + "\n"
    env_names = (
        "PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "SYSTEMROOT",
        "TEMP", "TMP", "TMPDIR", "LANG", "PATHEXT", "COMSPEC",
    )
    env = {name: os.environ[name] for name in env_names if name in os.environ}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="sdlc-inference-", ignore_cleanup_errors=True) as directory:
        workspace = Path(directory)
        agents = workspace / ".agents" / "agents"
        agents.mkdir(parents=True)
        (agents / f"{AGENT}.md").write_text(AGENT_SPEC, encoding="utf-8")
        (workspace / "deny_native_tools.py").write_text(DENY_NATIVE_TOOL, encoding="utf-8")
        hooks = {"sdlc-model-only": {"PreToolUse": [
            {"matcher": ".*", "hooks": [
                {"type": "command", "command": "python deny_native_tools.py", "timeout": 5},
            ]},
        ]}}
        (workspace / ".agents" / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
        schema_path = workspace / "response.schema.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        argv = [
            binary, "--agent", AGENT, "--model", MODEL, "--sandbox", "--disable-slash-commands",
            "--settings", json.dumps(SETTINGS), "--json-schema", str(schema_path),
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--print-timeout", f"{timeout_seconds}s", "--log-file", os.devnull,
        ]
        from backend.recovery import OperationCancelled, controlled_command
        started_at = time.monotonic()
        try:
            completed = controlled_command(
                argv, cwd=workspace, env=env, input=input_line, timeout=timeout_seconds + 10,
            )
        except OperationCancelled:
            raise
        except subprocess.TimeoutExpired:
            raise ModelError("provider_timeout") from None
        except OSError:
            raise ModelError("provider_unavailable") from None
        elapsed = time.monotonic() - started_at
    try:
        data, usage = decode_result(completed.stdout, completed.returncode, schema)
    except ModelError as exc:
        if (
            exc.code == "missing_structured_output"
            and elapsed >= max(1, timeout_seconds - 2)
            and not exc.usage.get("output_tokens")
        ):
            raise ModelError("provider_timeout", exc.usage) from None
        raise
    return ModelReply(
        model=MODEL, output=data["output"], tool_proposals=data["tool_proposals"],
        usage=usage, usage_complete={"input_tokens", "output_tokens"} <= usage.keys(),
        prompt_sha256=fingerprint(request), config_sha256=fingerprint(config),
    )
