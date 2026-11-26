import json
import os
import subprocess
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from backend.llm import ModelError, decode_result, envelope_schema, invoke
from backend.artifacts import ArtifactStore
from backend.storage import Database


TITLE_SCHEMA = {
    "type": "object", "properties": {"title": {"type": "string", "minLength": 1}},
    "required": ["title"], "additionalProperties": False,
}
EMPTY_TOOLS = envelope_schema(TITLE_SCHEMA, {})


def response(data, usage=None):
    return "\n".join(json.dumps(event) for event in [
        {"event": "init", "init": {"permission_mode": "strict"}},
        {"event": "result", "result": {
            "status": "SUCCESS", "structured_output": data, "usage": usage,
        }},
    ])


class AdapterTest(unittest.TestCase):
    def test_identical_cli_json_retries_and_ambiguous_responses(self):
        data = {"output": {"title": "Tasks"}, "tool_proposals": []}
        events = [json.loads(line) for line in response(data).splitlines()]
        del events[1]["result"]["structured_output"]
        events[1]["result"]["response"] = (json.dumps(data, indent=2) + "\n") * 2
        def wire():
            return "\n".join(json.dumps(event) for event in events)
        self.assertEqual(decode_result(wire(), 0, EMPTY_TOOLS)[0], data)
        events[1]["result"]["response"] += "{}"
        with self.assertRaisesRegex(ModelError, "missing_structured_output"):
            decode_result(wire(), 0, EMPTY_TOOLS)

    def test_wrapped_local_schema_references_resolve(self):
        definition = {"$defs": {"title": {"type": "string"}},
                      "type": "object", "properties": {"name": {"$ref": "#/$defs/title"}}}
        schema = envelope_schema(definition, {})
        value = {"output": {"name": "A1"}, "tool_proposals": []}
        self.assertEqual(decode_result(response(value), 0, schema)[0], value)
        with self.assertRaises(ValueError):
            envelope_schema({"$ref": "https://example.com/schema"}, {})

    def test_missing_usage_remains_missing_and_tool_arguments_are_checked(self):
        tools = {"project.read_artifact": {
            "type": "object", "properties": {"version": {"type": "integer", "minimum": 1}},
            "required": ["version"], "additionalProperties": False,
        }}
        schema = envelope_schema(TITLE_SCHEMA, tools)
        proposal = {"name": "project.read_artifact", "arguments": {"version": 1}}
        data = {"output": {"title": "Task manager"}, "tool_proposals": [proposal]}
        self.assertEqual(decode_result(response(data), 0, schema), (data, {}))
        proposal["arguments"]["version"] = 0
        with self.assertRaisesRegex(ModelError, "schema_invalid"):
            decode_result(response(data), 0, schema)
        with self.assertRaisesRegex(ModelError, "schema_invalid"):
            decode_result(response(data), 0, EMPTY_TOOLS)

    def test_invalid_result_preserves_provider_usage(self):
        with self.assertRaisesRegex(ModelError, "schema_invalid") as error:
            decode_result(response({}, {"input_tokens": 2}), 0, EMPTY_TOOLS)
        self.assertEqual(error.exception.usage, {"input_tokens": 2})

    @patch("backend.llm.shutil.which", return_value="agy")
    @patch("backend.llm.subprocess.run", side_effect=subprocess.TimeoutExpired("agy", 3))
    def test_timeout_makes_one_attempt(self, run, _which):
        with self.assertRaisesRegex(ModelError, "provider_timeout"):
            invoke("test", TITLE_SCHEMA, timeout_seconds=1)
        self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(os.getenv("SDLC_LIVE_MODEL") == "1", "Set SDLC_LIVE_MODEL=1 to call agy")
    def test_live(self):
        result = invoke("A task manager needs a list of tasks. Give this brief a short title. "
                        "Return no tool proposals.", TITLE_SCHEMA)
        self.assertTrue(result.output["title"])
        self.assertEqual(result.tool_proposals, [])
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "metadata.sqlite3")
            db.migrate()
            with db.transaction(write=True) as repo:
                project = repo.create_project("I04 smoke", "brief")
                run = repo.create_run(project, "smoke", {}, {})
            with closing(sqlite3.connect(db.path)) as seed, seed:
                seed.execute("UPDATE runs SET status='running', worker_lease='smoke', "
                             "lease_expires_at=datetime('now','+5 minutes') WHERE id=?", (run,))
            store = ArtifactStore(Path(directory) / "workspaces", db)
            ref = result.persist(store, project, run, "smoke", "Requirement", 0)
            body = store.read(project, run, ref.artifact_id, ref.version, ref.sha256)
            self.assertEqual(json.loads(body), asdict(result))
        print(json.dumps({"reply": asdict(result), "artifact": ref.model_dump()}, ensure_ascii=True))
