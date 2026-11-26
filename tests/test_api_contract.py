import json
import re
import unittest
from pathlib import Path


SPEC = json.loads((Path(__file__).parents[1] / "docs/openapi.json").read_text(encoding="utf-8"))
PATHS = SPEC["paths"]
SCHEMAS = SPEC["components"]["schemas"]


class PlatformContractTests(unittest.TestCase):
    def test_local_references_resolve(self):
        for pointer in re.findall(r'"\$ref":\s*"(#[^"]+)"', json.dumps(SPEC)):
            target = SPEC
            for segment in pointer[2:].split("/"):
                target = target[segment]
            self.assertTrue(target, pointer)

    def test_operations_and_path_parameters(self):
        seen = set()
        for path, methods in PATHS.items():
            for method, op in methods.items():
                with self.subTest(path=path, method=method):
                    self.assertNotIn(op["operationId"], seen)
                    seen.add(op["operationId"])
                    params = {p["name"] for p in op.get("parameters", []) if p["in"] == "path" and p["required"]}
                    self.assertEqual(params, set(re.findall(r"{([^}]+)}", path)))
        self.assertTrue({"createRun", "answerQuestions", "reviewGate", "reviewOutput", "exportRun"} <= seen)

    def test_run_ticket_and_scope(self):
        self.assertIn("202", PATHS["/projects/{project_id}/runs"]["post"]["responses"])
        self.assertIn("idempotency_key", SCHEMAS["CreateRun"]["required"])
        op = PATHS["/artifacts/{artifact_id}"]["get"]
        self.assertTrue(any(p["name"] == "run_id" and p["in"] == "query" and p["required"] for p in op["parameters"]))
        self.assertIn("404", op["responses"])

    def test_approval_binds_exact_versions(self):
        self.assertEqual(set(SCHEMAS["ArtifactRef"]["required"]), {"artifact_id", "version", "sha256"})
        gate = SCHEMAS["Approval"]["allOf"][0]
        self.assertEqual(gate["if"]["properties"]["gate"]["const"], "requirements")
        self.assertEqual(gate["then"]["properties"]["artifacts"]["maxItems"], 1)
        self.assertEqual(gate["else"]["properties"]["artifacts"]["minItems"], 2)
        self.assertIn("409", PATHS["/runs/{run_id}/approvals"]["post"]["responses"])
