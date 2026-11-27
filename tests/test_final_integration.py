"""End-to-end integration test exercising the unified Final-Test stack across all 6 roles and HTTP API."""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.exporter import verify_export_zip
from backend.llm import MODEL, ModelReply
from backend.platform_runtime import build_platform
from tests.test_tester_agent import make_gateway_client_factory


class FinalUnifiedIntegrationTests(unittest.TestCase):
    def test_full_six_agent_http_gate_repair_trace_and_export_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dev_attempt = 0

            def unified_model(prompt, schema):
                nonlocal dev_attempt
                props = schema.get("properties", {})
                # 1. Requirement (I09)
                if "actors" in props and "functional" in props:
                    self.assertIn("Quản lý phép chia an toàn", prompt)
                    return ModelReply(MODEL, {
                        "actors": ["Người dùng"],
                        "functional": [{
                            "id": "FR1",
                            "description": "Chia hai số và từ chối chia cho 0",
                            "acceptance": ["divide(10, 2) == 5", "divide(10, 0) raises ValueError"],
                        }],
                        "nonfunctional": [], "assumptions": [], "questions": [],
                    }, [], {"input_tokens": 50, "output_tokens": 25}, True, "1" * 64, "2" * 64)

                # 2. Architecture (I10) — schema uses anyOf([arch_schema, blocker_schema])
                if "anyOf" in schema:
                    return ModelReply(MODEL, {
                        "blocker": None,
                        "adr": ["Dùng FastAPI + React + SQLite theo P01."],
                        "components": {"api": "FastAPI service", "db": "SQLite store", "web": "React UI"},
                        "entities": {"calc": "a REAL, b REAL"},
                        "api_contract": {
                            "POST /divide": json.dumps({
                                "summary": "Chia hai số",
                                "responses": {"200": {"description": "OK"}, "422": {"description": "Chia cho 0"}},
                            }),
                        },
                        "frontend": "Form nhập hai số và hiển thị kết quả hoặc lỗi.",
                        "test_strategy": "Chạy kiểm thử development cho trường hợp hợp lệ và b == 0.",
                        "fr_components": {"FR1": ["api", "db", "web"]},
                    }, [], {"input_tokens": 60, "output_tokens": 30}, True, "1" * 64, "2" * 64)

                # 3. Planning (I11)
                if "tasks" in props:
                    return ModelReply(MODEL, {
                        "tasks": [{
                            "task_id": "T_CALC",
                            "requirement_ids": ["FR1"],
                            "dependencies": [],
                            "files": ["app/calc.py"],
                            "done_conditions": ["divide(a, b) returns a / b and raises ValueError on b == 0"],
                            "tests": ["development"],
                        }],
                    }, [], {"input_tokens": 45, "output_tokens": 25}, True, "1" * 64, "2" * 64)

                # 4. Dev (I16 + I18 rework)
                if "blocker" in props and "files" in props:
                    dev_attempt += 1
                    if dev_attempt == 1:
                        code = "def divide(a, b):\n    return 0 if b == 0 else a / b\n"
                    else:
                        self.assertIn("expected ValueError", prompt)
                        code = "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"
                    return ModelReply(MODEL, {
                        "summary": f"divide round {dev_attempt}",
                        "blocker": None,
                        "files": [{"path": "app/calc.py", "text": code}],
                    }, [], {"input_tokens": 70, "output_tokens": 35}, True, "1" * 64, "2" * 64)

                # 5. Tester BugDiagnosis (I17)
                if "severity" in props and "category" in props:
                    return ModelReply(MODEL, {
                        "summary": "Zero divisor bug confirmed",
                        "severity": "high",
                        "category": "code",
                        "requirement_ids": ["FR1"],
                        "reproduce": ["Run suite development"],
                        "expected": "divide(10, 0) raises ValueError",
                        "actual": "AssertionError: expected ValueError",
                        "findings": [{
                            "severity": "high", "file": "app/calc.py",
                            "message": "divide(a, 0) returned 0", "requirement_id": "FR1",
                        }],
                    }, [], {"input_tokens": 40, "output_tokens": 20}, True, "3" * 64, "4" * 64)

                # 6. Tester Plan (I17 + I18 retest)
                test_files = [] if "tests_dev/test_calc.py" in prompt else [{
                    "path": "tests_dev/test_calc.py",
                    "text": (
                        "from app.calc import divide\n\n"
                        "def test_ok():\n    assert divide(10, 2) == 5\n\n"
                        "def test_zero():\n    try:\n        divide(10, 0)\n    except ValueError:\n        return\n"
                        "    raise AssertionError('expected ValueError')\n"
                    ),
                }]
                return ModelReply(MODEL, {
                    "summary": "Verify divide happy path and zero boundary",
                    "suite_id": "development",
                    "test_files": test_files,
                    "review_findings": [],
                }, [], {"input_tokens": 55, "output_tokens": 25}, True, "1" * 64, "2" * 64)

            bundle = build_platform(
                root / "platform.sqlite",
                root / "workspaces",
                image="local-python-test",
                model=unified_model,
                client_factory=make_gateway_client_factory(),
            )
            client = TestClient(bundle.app)

            # 1. Create project + enqueue run via HTTP API (I22)
            proj = client.post("/projects", json={
                "name": "Demo 6 Agents",
                "brief": "Quản lý phép chia an toàn, từ chối chia cho 0.",
                "constraints": ["FastAPI", "React", "SQLite"],
            })
            self.assertEqual(proj.status_code, 201)
            pid = proj.json()["project_id"]

            run_resp = client.post(f"/projects/{pid}/runs", json={"idempotency_key": "e2e-1"})
            self.assertEqual(run_resp.status_code, 202)
            rid = run_resp.json()["run_id"]

            # 2. Worker executes Requirement -> pauses at Gate 1
            self.assertTrue(bundle.worker.run_one())
            state1 = client.get(f"/runs/{rid}").json()
            self.assertEqual(state1["status"], "waiting_approval")
            req_art = client.get(f"/runs/{rid}/artifacts?kind=requirements").json()[-1]
            gate1 = client.post(f"/runs/{rid}/approvals", json={
                "gate": "requirements",
                "artifacts": [{"artifact_id": req_art["artifact_id"], "version": req_art["version"], "sha256": req_art["sha256"]}],
                "decision": "approve",
                "comment": "Duyệt yêu cầu",
            })
            self.assertEqual(gate1.status_code, 200)

            # 3. Worker executes Architecture + Planning -> pauses at Gate 2
            self.assertTrue(bundle.worker.run_one())
            state2 = client.get(f"/runs/{rid}").json()
            self.assertEqual(state2["status"], "waiting_approval")
            arch_art = client.get(f"/runs/{rid}/artifacts?kind=architecture").json()[-1]
            plan_art = client.get(f"/runs/{rid}/artifacts?kind=plan").json()[-1]
            gate2 = client.post(f"/runs/{rid}/approvals", json={
                "gate": "architecture_plan",
                "artifacts": [
                    {"artifact_id": arch_art["artifact_id"], "version": arch_art["version"], "sha256": arch_art["sha256"]},
                    {"artifact_id": plan_art["artifact_id"], "version": plan_art["version"], "sha256": plan_art["sha256"]},
                ],
                "decision": "approve",
                "comment": "Duyệt kiến trúc và kế hoạch",
            })
            self.assertEqual(gate2.status_code, 200)

            # 4. Worker executes Dev (buggy) -> Tester (fails + BugReport) -> Dev (fix) -> Tester (passes) -> completed!
            self.assertTrue(bundle.worker.run_one())
            final = client.get(f"/runs/{rid}").json()
            self.assertEqual(final["status"], "completed")
            self.assertEqual(dev_attempt, 2)
            self.assertTrue(final["quota"]["usage_complete"])
            self.assertGreater(final["quota"]["input_tokens"], 0)
            self.assertGreater(final["quota"]["tool_calls"], 0)

            # 5. Verify tasks, test reports, events, trace, secret-filtered ZIP export, and final acceptance.
            tasks = client.get(f"/runs/{rid}/tasks").json()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["status"], "done")
            self.assertEqual(len(tasks[0]["patch_artifact_ids"]), 2)

            reports = client.get(f"/runs/{rid}/test-reports").json()
            self.assertGreaterEqual(len(reports), 2)
            self.assertEqual(reports[-1]["passed"], 2)
            self.assertEqual(reports[-1]["failed"], 0)

            events = client.get(f"/runs/{rid}/events?after=0").json()
            self.assertGreater(len(events["items"]), 5)
            self.assertTrue(bundle.orchestrator.audit.trace_requirement(pid, rid, "FR1").complete)

            exported = client.get(f"/runs/{rid}/export")
            self.assertEqual(exported.status_code, 200)
            zip_file = root / "final_export.zip"
            zip_file.write_bytes(exported.content)
            manifest = verify_export_zip(zip_file)
            self.assertEqual(manifest["run_id"], rid)
            self.assertIn("app/calc.py", manifest["files"])

            latest_test = client.get(f"/runs/{rid}/artifacts?kind=test_report").json()[-1]
            acc = client.post(f"/runs/{rid}/acceptance", json={
                "manifest": {
                    "artifact_id": latest_test["artifact_id"],
                    "version": latest_test["version"],
                    "sha256": latest_test["sha256"],
                },
                "decision": "accept",
                "comment": "Nghiệm thu bản tích hợp Final-Test",
            })
            self.assertEqual(acc.status_code, 200)
