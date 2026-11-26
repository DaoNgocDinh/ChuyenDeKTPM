import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.artifacts import ArtifactStore
from backend.coding_agents import CodingAgents, ReviewReport
from backend.contracts import ArtifactRef
from backend.llm import ModelReply, invoke
from backend.orchestrator import Orchestrator, RoleOutput
from backend.storage import Database
from backend.worker import Queue, Worker
from tests.test_tester_agent import make_gateway_client_factory


class RepairLoopAndRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "platform.db")
        self.db.migrate()
        self.store = ArtifactStore(root / "workspaces", self.db)
        self.queue = Queue(self.db)
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("Repair loop demo", "brief")

    def _run_row(self, run_id):
        with self.db.transaction() as repo:
            return repo.get_run(self.project, run_id)

    def _approve_gate(self, host, run_id, expected_gate):
        checkpoint = json.loads(self._run_row(run_id)["checkpoint_json"])
        pending = checkpoint["pending_gate"]
        self.assertEqual(pending["gate"], expected_gate)
        refs = [ArtifactRef.model_validate(item) for item in pending["artifacts"]]
        host.gates.decide_gate(self.project, run_id, expected_gate, refs, "approve")
        return refs

    def _build_harness(self, *, dev_model, tester_model, config=None, force_infra_fn=None):
        run_id = self.queue.enqueue(self.project, f"run-{os.urandom(4).hex()}", config or {}, {})
        calls = []
        routing_bugs = []
        req_version = 0
        arch_version = 0
        plan_version = 0

        def client_factory_selector(database_path, root, host, image=None):
            flag = force_infra_fn(host) if force_infra_fn else False
            return make_gateway_client_factory(force_infra=flag)(database_path, root, host, image)

        def combined_model(prompt, schema):
            props = schema.get("properties", {})
            if "blocker" in props:
                return dev_model(prompt, schema)
            return tester_model(prompt, schema)

        coding = CodingAgents(
            self.store, "local-python-test", model=combined_model, client_factory=client_factory_selector,
        )

        def dispatch(order):
            nonlocal req_version, arch_version, plan_version
            calls.append((order.role, order.context.get("attempt"), order.context.get("infra_retry")))
            if order.role == "Orchestrator":
                return RoleOutput({"decision": "approve", "requested_role": order.context.get("expected_role")})
            if order.role == "Requirement":
                req_version += 1
                if "routing_bug" in order.context:
                    routing_bugs.append(("Requirement", order.context["routing_bug"]))
                return RoleOutput({
                    "actors": ["user"],
                    "functional": [
                        {"id": "FR1", "description": f"Base helper v{req_version}",
                         "acceptance": ["double(3) returns 6"]},
                        {"id": "FR2", "description": f"Safe divide v{req_version}",
                         "acceptance": ["divide(10, 2) returns 5", "divide(10, 0) raises ValueError"]},
                    ],
                    "nonfunctional": [], "assumptions": [], "questions": [],
                }, markdown=f"# Requirements v{req_version}")
            if order.role == "Architecture":
                arch_version += 1
                if "routing_bug" in order.context:
                    routing_bugs.append(("Architecture", order.context["routing_bug"]))
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "adr": [f"Python modules v{arch_version}"],
                    "components": {"base": "base helper", "calc": "calculator"},
                    "entities": {"Number": "float"},
                    "api_contract": {"base.double": "int->int", "calc.divide": "a,b->float"},
                    "frontend": "out of scope",
                    "test_strategy": "development unit and regression tests",
                    "fr_components": {"FR1": ["base"], "FR2": ["calc"]},
                })
            if order.role == "Planning":
                plan_version += 1
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(),
                    "architecture": order.inputs[1].model_dump(),
                    "tasks": [
                        {"task_id": "base", "requirement_ids": ["FR1"], "dependencies": [],
                         "files": ["app/base.py"], "done_conditions": ["double(x) returns x * 2"],
                         "tests": ["development"]},
                        {"task_id": "calc", "requirement_ids": ["FR2"], "dependencies": ["base"],
                         "files": ["app/calc.py"],
                         "done_conditions": ["divide(a, b) returns a / b and raises ValueError on b == 0"],
                         "tests": ["development"]},
                    ],
                })
            return coding(order)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        return run_id, host, worker, calls, routing_bugs

    def test_fail_fix_retest_with_regression_and_full_artifact_lineage(self):
        dev_prompts = []

        def dev_model(prompt, schema):
            dev_prompts.append(prompt)
            if '"task_id": "base"' in prompt:
                return ModelReply("fixture", {
                    "summary": "Implement double()",
                    "blocker": None,
                    "files": [{"path": "app/base.py", "text": "def double(x):\n    return x * 2\n"}],
                }, [], {"input_tokens": 50, "output_tokens": 20}, True, "1" * 64, "2" * 64)
            if '"bug": null' in prompt:
                # Initial delivery for calc has a deliberate bug on b == 0.
                return ModelReply("fixture", {
                    "summary": "Initial divide implementation",
                    "blocker": None,
                    "files": [{"path": "app/calc.py", "text": "def divide(a, b):\n    return 0 if b == 0 else a / b\n"}],
                }, [], {"input_tokens": 60, "output_tokens": 25}, True, "1" * 64, "2" * 64)
            # Rework round receives BugReport + existing tests_dev/ files.
            self.assertIn("expected ValueError on division by zero", prompt)
            self.assertIn("tests_dev/test_calc.py", prompt)
            return ModelReply("fixture", {
                "summary": "Fix divide(a, 0) to raise ValueError",
                "blocker": None,
                "files": [{"path": "app/calc.py",
                           "text": "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"}],
            }, [], {"input_tokens": 70, "output_tokens": 30}, True, "1" * 64, "2" * 64)

        def tester_model(prompt, schema):
            if "severity" in schema.get("properties", {}):
                return ModelReply("fixture", {
                    "summary": "Zero divisor bug confirmed",
                    "severity": "high",
                    "category": "code",
                    "requirement_ids": ["FR2"],
                    "reproduce": ["Run suite development", "Execute tests_dev/test_calc.py::test_divide_zero"],
                    "expected": "divide(10, 0) raises ValueError",
                    "actual": "AssertionError: expected ValueError on division by zero",
                    "findings": [{"severity": "high", "file": "app/calc.py",
                                  "message": "returns 0 instead of ValueError", "requirement_id": "FR2"}],
                }, [], {"input_tokens": 40, "output_tokens": 25}, True, "3" * 64, "4" * 64)
            if '"task_id": "base"' in prompt:
                return ModelReply("fixture", {
                    "summary": "Test base.double",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_base.py",
                                    "text": "from app.base import double\n\ndef test_double():\n    assert double(3) == 6\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 45, "output_tokens": 20}, True, "1" * 64, "2" * 64)
            # On retest (attempt 2), tests_dev/test_calc.py already exists; return [] to rerun suite + regression.
            test_files = [] if '"attempt": 2' in prompt else [{
                "path": "tests_dev/test_calc.py",
                "text": (
                    "from app.calc import divide\n\n"
                    "def test_divide_ok():\n    assert divide(10, 2) == 5\n\n"
                    "def test_divide_zero():\n    try:\n        divide(10, 0)\n    except ValueError:\n        return\n"
                    "    raise AssertionError('expected ValueError on division by zero')\n"
                ),
            }]
            return ModelReply("fixture", {
                "summary": "Verify calc and regression suite",
                "suite_id": "development",
                "test_files": test_files,
                "review_findings": [],
            }, [], {"input_tokens": 50, "output_tokens": 25}, True, "1" * 64, "2" * 64)

        run_id, host, worker, calls, _ = self._build_harness(dev_model=dev_model, tester_model=tester_model)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()

        self.assertEqual(self._run_row(run_id)["status"], "completed")
        with self.db.transaction() as repo:
            view = repo.for_run(self.project, run_id)
            tasks = {t["description"]: t for t in view.records("tasks")}
            self.assertEqual(tasks["base"]["status"], "done")
            self.assertEqual(tasks["base"]["repair_round"], 0)
            self.assertEqual(tasks["calc"]["status"], "done")
            self.assertEqual(tasks["calc"]["repair_round"], 1)

            artifacts = view.records("artifacts")
            by_type = {}
            for art in artifacts:
                by_type.setdefault(art["type"], []).append(art)
            self.assertEqual(len(by_type["dev_result"]), 3)
            self.assertEqual(len(by_type["patch"]), 3)
            self.assertEqual(len(by_type["test_report"]), 3)
            self.assertEqual(len(by_type["bug_report"]), 1)
            self.assertEqual(len(by_type["document"]), 3)

            # Rework DevResult and patch must reference the triggering BugReport in parent_refs.
            bug_id = by_type["bug_report"][0]["id"]
            rework_dev_parents = [p["artifact_id"] for p in json.loads(by_type["dev_result"][-1]["parent_refs_json"])]
            rework_patch_parents = [p["artifact_id"] for p in json.loads(by_type["patch"][-1]["parent_refs_json"])]
            self.assertIn(bug_id, rework_dev_parents)
            self.assertIn(bug_id, rework_patch_parents)

            # Last Tester test_report ran all 3 tests (1 regression in test_base.py + 2 in test_calc.py).
            last_report = json.loads(
                self.store.read(self.project, run_id, by_type["test_report"][-1]["id"],
                                by_type["test_report"][-1]["version"], by_type["test_report"][-1]["sha256"])
            )
            self.assertEqual((last_report["passed"], last_report["failures"]), (3, 0))
            last_review = ReviewReport.model_validate_json(
                self.store.read(self.project, run_id, by_type["document"][-1]["id"],
                                by_type["document"][-1]["version"], by_type["document"][-1]["sha256"])
            )
            self.assertEqual(last_review.verdict, "pass")

        self.assertTrue(host.audit.trace_requirement(self.project, run_id, "FR1").complete)
        self.assertTrue(host.audit.trace_requirement(self.project, run_id, "FR2").complete)

    def test_three_repair_rounds_limit_blocks_task_and_stops_run(self):
        attempt_counter = 0

        def dev_model(prompt, schema):
            nonlocal attempt_counter
            if '"task_id": "base"' in prompt:
                return ModelReply("fixture", {
                    "summary": "Implement double",
                    "blocker": None,
                    "files": [{"path": "app/base.py", "text": "def double(x):\n    return x * 2\n"}],
                }, [], {"input_tokens": 30, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            attempt_counter += 1
            return ModelReply("fixture", {
                "summary": f"Still buggy attempt {attempt_counter}",
                "blocker": None,
                "files": [{"path": "app/calc.py",
                           "text": f"def divide(a, b):\n    # attempt {attempt_counter}\n    return 0 if b == 0 else a / b\n"}],
            }, [], {"input_tokens": 30, "output_tokens": 15}, True, "1" * 64, "2" * 64)

        def tester_model(prompt, schema):
            if "severity" in schema.get("properties", {}):
                return ModelReply("fixture", {
                    "summary": "Still failing on zero divisor",
                    "severity": "high",
                    "category": "code",
                    "requirement_ids": ["FR2"],
                    "reproduce": ["Run development suite"],
                    "expected": "ValueError on b == 0",
                    "actual": "divide(10, 0) returned 0",
                    "findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "3" * 64, "4" * 64)
            if '"task_id": "base"' in prompt:
                return ModelReply("fixture", {
                    "summary": "Test base",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_base.py",
                                    "text": "from app.base import double\n\ndef test_double():\n    assert double(3) == 6\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            test_files = [] if "tests_dev/test_calc.py" in prompt else [{
                "path": "tests_dev/test_calc.py",
                "text": (
                    "from app.calc import divide\n\n"
                    "def test_zero():\n    try:\n        divide(10, 0)\n    except ValueError:\n        return\n"
                    "    raise AssertionError('still broken')\n"
                ),
            }]
            return ModelReply("fixture", {
                "summary": "Test calc",
                "suite_id": "development",
                "test_files": test_files,
                "review_findings": [],
            }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)

        run_id, host, worker, _, _ = self._build_harness(dev_model=dev_model, tester_model=tester_model)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()

        # Initial + 3 repairs = 4 attempts total, NEVER a 4th repair round (5th attempt).
        self.assertEqual(attempt_counter, 4)
        self.assertEqual(self._run_row(run_id)["status"], "needs_human_review")
        with self.db.transaction() as repo:
            view = repo.for_run(self.project, run_id)
            tasks = {t["description"]: t for t in view.records("tasks")}
            self.assertEqual(tasks["calc"]["status"], "blocked")
            self.assertEqual(tasks["calc"]["repair_round"], 3)
            bugs = [a for a in view.records("artifacts") if a["type"] == "bug_report"]
            self.assertEqual(len(bugs), 4)

    def test_requirements_bug_routes_to_requirement_and_reopens_gate_1(self):
        triggered = False

        def dev_model(prompt, schema):
            if '"task_id": "base"' in prompt:
                body = (
                    "def double(x):\n    return x * 2\n"
                    if not triggered
                    else "# updated after requirements v2\ndef double(x):\n    return x * 2\n"
                )
                return ModelReply("fixture", {
                    "summary": "Implement double",
                    "blocker": None,
                    "files": [{"path": "app/base.py", "text": body}],
                }, [], {"input_tokens": 25, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            return ModelReply("fixture", {
                "summary": "Implement divide",
                "blocker": None,
                "files": [{"path": "app/calc.py",
                           "text": "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"}],
            }, [], {"input_tokens": 25, "output_tokens": 15}, True, "1" * 64, "2" * 64)

        def tester_model(prompt, schema):
            nonlocal triggered
            if "severity" in schema.get("properties", {}):
                triggered = True
                return ModelReply("fixture", {
                    "summary": "Ambiguous FR1 behavior for negative inputs",
                    "severity": "high",
                    "category": "requirements",
                    "requirement_ids": ["FR1"],
                    "reproduce": ["Inspect FR1 acceptance criteria"],
                    "expected": "Clarified specification for negative inputs",
                    "actual": "FR1 omits negative number rule",
                    "findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "3" * 64, "4" * 64)
            if '"task_id": "base"' in prompt and not triggered:
                return ModelReply("fixture", {
                    "summary": "Failing spec test",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_base.py",
                                    "text": "def test_ambiguous():\n    assert False, 'spec unclear'\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            if '"task_id": "base"' in prompt:
                return ModelReply("fixture", {
                    "summary": "Verified updated FR1",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_base.py",
                                    "text": "from app.base import double\n\ndef test_double():\n    assert double(3) == 6\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            return ModelReply("fixture", {
                "summary": "Verified calc",
                "suite_id": "development",
                "test_files": [{"path": "tests_dev/test_calc.py",
                                "text": "from app.calc import divide\n\ndef test_div():\n    assert divide(10, 2) == 5\n"}],
                "review_findings": [],
            }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)

        run_id, host, worker, _, routing_bugs = self._build_harness(dev_model=dev_model, tester_model=tester_model)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()

        # Must stop at Gate 1 with requirements v2 (never run Dev again before approval).
        self.assertEqual(self._run_row(run_id)["status"], "waiting_approval")
        refs_v2 = self._approve_gate(host, run_id, "requirements")
        self.assertEqual(refs_v2[0].version, 2)
        self.assertEqual(len(routing_bugs), 1)
        self.assertEqual(routing_bugs[0][0], "Requirement")
        self.assertEqual(routing_bugs[0][1]["category"], "requirements")

        # After Gate 1 approval, Architecture + Planning regenerate v2 and stop at Gate 2 (no infinite loop).
        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "waiting_approval")
        gate2_v2 = self._approve_gate(host, run_id, "architecture_plan")
        self.assertEqual([r.version for r in gate2_v2], [2, 2])

        # Verify fault.routed event recorded, then complete run on plan v2.
        with self.db.transaction() as repo:
            events = [e for e in repo.for_run(self.project, run_id).records("events") if e["event_type"] == "fault.routed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0]["payload_json"])["target_role"], "Requirement")

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "completed")

    def test_design_bug_routes_to_architecture_and_reopens_gate_2(self):
        triggered = False

        def dev_model(prompt, schema):
            if '"task_id": "base"' in prompt:
                body = (
                    "def double(x):\n    return x * 2\n"
                    if not triggered
                    else "# updated after requirements v2\ndef double(x):\n    return x * 2\n"
                )
                return ModelReply("fixture", {
                    "summary": "Implement double",
                    "blocker": None,
                    "files": [{"path": "app/base.py", "text": body}],
                }, [], {"input_tokens": 25, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            return ModelReply("fixture", {
                "summary": "Implement divide",
                "blocker": None,
                "files": [{"path": "app/calc.py",
                           "text": "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"}],
            }, [], {"input_tokens": 25, "output_tokens": 15}, True, "1" * 64, "2" * 64)

        def tester_model(prompt, schema):
            nonlocal triggered
            if "severity" in schema.get("properties", {}):
                triggered = True
                return ModelReply("fixture", {
                    "summary": "API contract mismatch between architecture and modules",
                    "severity": "high",
                    "category": "design",
                    "requirement_ids": ["FR1"],
                    "reproduce": ["Compare architecture api_contract with module signature"],
                    "expected": "Consistent API signature in architecture",
                    "actual": "Contract mismatch requires architecture update",
                    "findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "3" * 64, "4" * 64)
            if '"task_id": "base"' in prompt and not triggered:
                return ModelReply("fixture", {
                    "summary": "Failing contract check",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_base.py",
                                    "text": "def test_contract():\n    assert False, 'design conflict'\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            if '"task_id": "base"' in prompt:
                return ModelReply("fixture", {
                    "summary": "Verified updated architecture",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_base.py",
                                    "text": "from app.base import double\n\ndef test_double():\n    assert double(3) == 6\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)
            return ModelReply("fixture", {
                "summary": "Verified calc",
                "suite_id": "development",
                "test_files": [{"path": "tests_dev/test_calc.py",
                                "text": "from app.calc import divide\n\ndef test_div():\n    assert divide(10, 2) == 5\n"}],
                "review_findings": [],
            }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)

        run_id, host, worker, calls, routing_bugs = self._build_harness(dev_model=dev_model, tester_model=tester_model)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()

        # Must regenerate architecture v2 + plan v2 and stop at Gate 2 without re-running Requirement or Dev.
        self.assertEqual(self._run_row(run_id)["status"], "waiting_approval")
        self.assertEqual(sum(1 for role, _, _ in calls if role == "Requirement"), 1)
        gate2_v2 = self._approve_gate(host, run_id, "architecture_plan")
        self.assertEqual([r.version for r in gate2_v2], [2, 2])
        self.assertEqual(len(routing_bugs), 1)
        self.assertEqual(routing_bugs[0][0], "Architecture")

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "completed")

    def test_infrastructure_bug_retries_bounded_without_consuming_code_repairs(self):
        for recover_on_retry in (True, False):
            with self.subTest(recover_on_retry=recover_on_retry):
                tester_suite_calls = 0

                def force_infra(host):
                    nonlocal tester_suite_calls
                    with self.db.transaction() as repo:
                        steps = repo.for_run(host.project_id, host.run_id).records("agent_steps")
                        step = next(s for s in steps if s["id"] == host.step_id)
                    if step["agent_role"] != "tester":
                        return False
                    tester_suite_calls += 1
                    if recover_on_retry:
                        return tester_suite_calls == 1
                    return True

                def dev_model(prompt, schema):
                    if '"task_id": "base"' in prompt:
                        return ModelReply("fixture", {
                            "summary": "Implement double",
                            "blocker": None,
                            "files": [{"path": "app/base.py", "text": "def double(x):\n    return x * 2\n"}],
                        }, [], {"input_tokens": 25, "output_tokens": 15}, True, "1" * 64, "2" * 64)
                    return ModelReply("fixture", {
                        "summary": "Implement divide",
                        "blocker": None,
                        "files": [{"path": "app/calc.py",
                                   "text": "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"}],
                    }, [], {"input_tokens": 25, "output_tokens": 15}, True, "1" * 64, "2" * 64)

                def tester_model(prompt, schema):
                    if "severity" in schema.get("properties", {}):
                        return ModelReply("fixture", {
                            "summary": "Container runner timeout",
                            "severity": "critical",
                            "category": "infrastructure",
                            "requirement_ids": ["FR1"],
                            "reproduce": ["Run suite development"],
                            "expected": "Suite finishes normally",
                            "actual": "Simulated runner timeout / container infrastructure failure",
                            "findings": [],
                        }, [], {"input_tokens": 20, "output_tokens": 15}, True, "3" * 64, "4" * 64)
                    if '"task_id": "base"' in prompt:
                        test_files = [] if "tests_dev/test_base.py" in prompt else [{
                            "path": "tests_dev/test_base.py",
                            "text": "from app.base import double\n\ndef test_double():\n    assert double(3) == 6\n",
                        }]
                        return ModelReply("fixture", {
                            "summary": "Test base",
                            "suite_id": "development",
                            "test_files": test_files,
                            "review_findings": [],
                        }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)
                    return ModelReply("fixture", {
                        "summary": "Test calc",
                        "suite_id": "development",
                        "test_files": [{"path": "tests_dev/test_calc.py",
                                        "text": "from app.calc import divide\n\ndef test_div():\n    assert divide(10, 2) == 5\n"}],
                        "review_findings": [],
                    }, [], {"input_tokens": 20, "output_tokens": 15}, True, "1" * 64, "2" * 64)

                run_id, host, worker, calls, _ = self._build_harness(
                    dev_model=dev_model, tester_model=tester_model,
                    config={"max_infra_retries": 2}, force_infra_fn=force_infra,
                )
                worker.run_one()
                self._approve_gate(host, run_id, "requirements")
                worker.run_one()
                self._approve_gate(host, run_id, "architecture_plan")
                worker.run_one()

                with self.db.transaction() as repo:
                    view = repo.for_run(self.project, run_id)
                    tasks = {t["description"]: t for t in view.records("tasks")}
                    events = [e["event_type"] for e in view.records("events")]

                if recover_on_retry:
                    self.assertEqual(self._run_row(run_id)["status"], "completed")
                    # Code repair_round stayed 0 even though Tester retried once for infra!
                    self.assertEqual(tasks["base"]["repair_round"], 0)
                    self.assertEqual(sum(1 for role, _, _ in calls if role == "Dev"), 2)
                    self.assertEqual(events.count("infra.retry"), 1)
                    self.assertNotIn("infra.exhausted", events)
                else:
                    self.assertEqual(self._run_row(run_id)["status"], "needs_human_review")
                    # Dev ran ONLY once for base; Tester ran 1 initial + 2 infra retries = 3 times; repair_round stayed 0.
                    self.assertEqual(tasks["base"]["repair_round"], 0)
                    self.assertEqual(sum(1 for role, _, _ in calls if role == "Dev"), 1)
                    self.assertEqual(sum(1 for role, _, _ in calls if role == "Tester"), 3)
                    self.assertEqual(events.count("infra.retry"), 2)
                    self.assertEqual(events.count("infra.exhausted"), 1)

    @unittest.skipUnless(os.getenv("KTPM_TEST_RUNNER_IMAGE"), "requires a local Docker test image")
    def test_real_docker_fail_fix_retest_loop(self):
        run_id = self.queue.enqueue(self.project, "docker-repair-demo", {}, {})
        dev_turn = 0
        tester_turn = 0

        def fixture_model(prompt, schema):
            nonlocal dev_turn, tester_turn
            props = schema.get("properties", {})
            if "blocker" in props:
                dev_turn += 1
                code = (
                    "def divide(a, b):\n    return 0 if b == 0 else a / b\n"
                    if dev_turn == 1
                    else "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"
                )
                return ModelReply("fixture", {
                    "summary": f"divide round {dev_turn}",
                    "blocker": None,
                    "files": [{"path": "app/calc.py", "text": code}],
                }, [], {}, False, "1" * 64, "2" * 64)
            if "severity" in props:
                return ModelReply("fixture", {
                    "summary": "Zero divisor failed in Docker",
                    "severity": "high", "category": "code", "requirement_ids": ["FR1"],
                    "reproduce": ["pytest tests_dev/test_calc.py"],
                    "expected": "ValueError on division by zero",
                    "actual": "divide(10, 0) returned 0", "findings": [],
                }, [], {}, False, "3" * 64, "4" * 64)
            tester_turn += 1
            test_files = [] if tester_turn > 1 else [{
                "path": "tests_dev/test_calc.py",
                "text": (
                    "import pytest\nfrom app.calc import divide\n\n"
                    "def test_divide():\n    assert divide(10, 2) == 5\n\n"
                    "def test_divide_zero():\n    with pytest.raises(ValueError):\n        divide(10, 0)\n"
                ),
            }]
            return ModelReply("fixture", {
                "summary": "Docker boundary test",
                "suite_id": "development", "test_files": test_files, "review_findings": [],
            }, [], {}, False, "1" * 64, "2" * 64)

        model = invoke if os.getenv("KTPM_LIVE_MODEL") == "1" else fixture_model
        coding = CodingAgents(self.store, os.environ["KTPM_TEST_RUNNER_IMAGE"], model=model)

        def dispatch(order):
            if order.role == "Orchestrator":
                return RoleOutput({"decision": "approve"})
            if order.role == "Requirement":
                return RoleOutput({
                    "actors": ["user"],
                    "functional": [{"id": "FR1", "description": "Safe divide",
                                    "acceptance": ["divide(10, 2) == 5", "divide(10, 0) raises ValueError"]}],
                    "nonfunctional": [], "assumptions": [], "questions": [],
                })
            if order.role == "Architecture":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(), "adr": ["Python"],
                    "components": {"calc": "calc"}, "entities": {"num": "float"},
                    "api_contract": {"divide": "a,b->float"}, "frontend": "out of scope",
                    "test_strategy": "pytest", "fr_components": {"FR1": ["calc"]},
                })
            if order.role == "Planning":
                return RoleOutput({
                    "requirements": order.inputs[0].model_dump(), "architecture": order.inputs[1].model_dump(),
                    "tasks": [{"task_id": "calc", "requirement_ids": ["FR1"], "dependencies": [],
                               "files": ["app/calc.py"],
                               "done_conditions": ["divide(a, b) returns a / b and raises ValueError on b == 0"],
                               "tests": ["development"]}],
                })
            return coding(order)

        host = Orchestrator(self.queue, self.store, dispatch, lambda lease, refs: True)
        worker = Worker(self.queue, host)
        worker.run_one()
        self._approve_gate(host, run_id, "requirements")
        worker.run_one()
        self._approve_gate(host, run_id, "architecture_plan")
        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "completed")
