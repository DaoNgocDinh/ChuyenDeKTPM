import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager, closing
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import mcp_types as mt

from backend.artifacts import ArtifactStore
from backend.coding_agents import BugDiagnosis, CodingAgents, ReviewReport, TesterPlan
from backend.contracts import DevResult
from backend.docker_runner import snapshot
from backend.gateway import HostStep, ToolDenied
from backend.llm import ModelReply, envelope_schema, invoke
from backend.mcp_tools import OP_KEY, SCHEMAS, TOOLS, ToolSession, step_client
from backend.storage import Database
from backend.workspace import Edit, Workspace


def _run_local_python_suite(ws, commit, suite_id, *, force_infra=False):
    """Execute real Python tests from a Git commit snapshot for non-Docker unit tests."""
    key = uuid4().hex
    folder = ws.path / "logs" / "suites" / key
    folder.mkdir(parents=True, exist_ok=True)
    report = dict(
        report_id=key, suite_id=suite_id, commit=commit, image_digest="local-python-test",
        status="infrastructure_error", exit_code=None, passed=0, failed=0, errors=0, skipped=0,
        duration_seconds=0.01, log_uri=key + "/runner.log", junit_uri=None, log_truncated=False,
    )
    if force_infra:
        log = "Simulated runner timeout / container infrastructure failure\n"
        report.update(status="infrastructure_error", exit_code=125)
        (folder / "runner.log").write_text(log, encoding="utf-8")
        (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report, log

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "snapshot"
        snapshot(ws.path, commit, stage)
        script = """
import importlib.util, json, pathlib, sys, traceback
sys.path.insert(0, str(pathlib.Path.cwd()))
suite = sys.argv[1]
root = pathlib.Path("tests_dev")
files = sorted(root.glob("test_*.py")) if root.exists() else []
if suite == "smoke":
    files = [f for f in files if f.name == "test_smoke.py"]
passed = failed = errors = skipped = 0
logs = []
for path in files:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        errors += 1
        logs.append(f"ERROR importing {path}:\\n" + traceback.format_exc())
        continue
    for name in sorted(dir(mod)):
        fn = getattr(mod, name)
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                logs.append(f"PASS {path.name}::{name}")
            except AssertionError:
                failed += 1
                logs.append(f"FAIL {path.name}::{name}\\n" + traceback.format_exc())
            except Exception:
                errors += 1
                logs.append(f"ERROR {path.name}::{name}\\n" + traceback.format_exc())
summary = {"passed": passed, "failed": failed, "errors": errors, "skipped": skipped, "log": "\\n".join(logs)}
print(json.dumps(summary))
sys.exit(0 if (passed > 0 and failed == 0 and errors == 0 and skipped == 0) else 1)
"""
        proc = subprocess.run(
            [sys.executable, "-B", "-c", script, suite_id],
            cwd=stage, capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {
            "passed": 0, "failed": 0, "errors": 1, "skipped": 0, "log": proc.stderr
        }
        report.update(
            exit_code=proc.returncode,
            passed=data["passed"],
            failed=data["failed"],
            errors=data["errors"],
            skipped=data["skipped"],
            status="passed" if (proc.returncode == 0 and data["passed"] > 0
                                and not (data["failed"] or data["errors"] or data["skipped"])) else "failed",
        )
        log = data["log"] + ("\n" + proc.stderr if proc.stderr else "")
    (folder / "runner.log").write_text(log, encoding="utf-8")
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, log


def make_gateway_client_factory(*, force_infra=False):
    """In-process MCP client using the real Gateway, ToolSession, Workspace, and SQLite."""
    @asynccontextmanager
    async def factory(database_path, root, host: HostStep, image=None):
        session = ToolSession({
            "database": str(Path(database_path).resolve()),
            "root": str(Path(root).resolve()),
            "host": asdict(host),
            "image": image,
        })

        def dispatch(ws, step, name, args):
            if name != "tests.run_suite":
                return session.dispatch(ws, step, name, args)
            model = TOOLS[name][0].model_validate(args)
            report, log = _run_local_python_suite(ws, ws.head(), model.suite_id, force_infra=force_infra)
            with session.database.transaction() as repo:
                previous = repo.for_run(host.project_id, host.run_id).latest_version("runner_output")
            ref = session.artifacts.put(
                host.project_id, host.run_id, host.lease, "runner_output",
                json.dumps(report), created_by="runner", expected_previous_version=previous,
            )
            report_id = None
            if report["exit_code"] is not None:
                with session.database.transaction(write=True) as repo:
                    writer = repo.worker_run(host.project_id, host.run_id, host.lease)
                    report_id = writer.add_report(
                        step["task_id"], report["commit"], model.suite_id,
                        "logs/suites/" + report["report_id"] + "/report.json", report["exit_code"],
                        report["passed"], report["failed"], report["skipped"], report["errors"],
                        int(report["duration_seconds"] * 1000),
                    )
            return {
                "report": report,
                "report_id": report_id,
                "runner_output": ref.model_dump(),
                "log_tail": log[-8192:],
            }

        class LocalClient:
            protocol_version = "local-gateway"

            async def list_tools(self):
                return mt.ListToolsResult(tools=[
                    mt.Tool(name=k, description=v[1], input_schema=SCHEMAS[k]) for k, v in TOOLS.items()
                ])

            async def call_tool(self, name, args, meta=None):
                op = (meta or {}).get(OP_KEY, "")
                try:
                    result = await asyncio.to_thread(session.gateway.call, host, op, name, args or {}, dispatch)
                except (ToolDenied, ValueError):
                    return mt.CallToolResult(is_error=True, content=[mt.TextContent(type="text", text="tool_denied")])
                except Exception:
                    return mt.CallToolResult(is_error=True, content=[mt.TextContent(type="text", text="tool_error")])
                return mt.CallToolResult(
                    content=[mt.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                    structured_content=result,
                )

        yield LocalClient()

    return factory


class TesterAgentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(Path(tmp.name) / "platform.db")
        self.db.migrate()
        self.root = Path(tmp.name) / "workspaces"
        self.store = ArtifactStore(self.root, self.db)
        with self.db.transaction(write=True) as repo:
            self.p = repo.create_project("Calculator demo", "brief")
            self.r = repo.create_run(self.p, "tester-test", {}, {})
        with closing(sqlite3.connect(self.db.path)) as con, con:
            con.execute("UPDATE runs SET status='running',worker_lease='w',lease_expires_at=datetime('now','+20 minutes')")
        self.ws = Workspace(self.root, self.p, self.r)
        self.start = self.ws.initialize()
        self.req = self._put("requirements", dict(
            actors=["user"],
            functional=[{"id": "FR1", "description": "Divide two numbers safely",
                         "acceptance": ["divide(10, 2) returns 5", "divide(10, 0) raises ValueError"]}],
            nonfunctional=[], assumptions=[], questions=[],
        ))
        self.arch = self._put("architecture", dict(
            requirements=self.req.model_dump(), adr=["Python module"],
            components={"app": "python"}, entities={"result": "float"},
            api_contract={"function": "divide(a, b)"},
            frontend="out of scope", test_strategy="development unit tests",
            fr_components={"FR1": ["app"]},
        ))
        self.task = dict(
            task_id="T1", requirement_ids=["FR1"], dependencies=[], files=["app/calc.py"],
            done_conditions=["divide(a, b) returns a / b and raises ValueError on b == 0"],
            tests=["development"],
        )
        self.plan = self._put("plan", dict(
            requirements=self.req.model_dump(), architecture=self.arch.model_dump(), tasks=[self.task],
        ))

    def _put(self, kind, value):
        with self.db.transaction() as repo:
            prior = repo.for_run(self.p, self.r).latest_version(kind)
        return self.store.put(self.p, self.r, "w", kind, value, created_by="fixture", expected_previous_version=prior)

    def _prepare_dev_delivery(self, code, *, approve=True, status="waiting_test"):
        receipt = self.ws.apply("t1", self.start, [Edit("app/calc.py", None, code)])
        patch_ref = self._put("patch", receipt["diff"])
        dev_payload = DevResult(
            task_id="t1", input_commit=self.start, output_commit=receipt["output_commit"],
            patch_sha256=receipt["patch_hash"], changed_files=["app/calc.py"], summary="implement divide",
        )
        dev_ref = self._put("dev_result", dev_payload)
        with self.db.transaction(write=True) as repo:
            w = repo.worker_run(self.p, self.r, "w")
            if approve:
                for ref in (self.req, self.arch, self.plan):
                    repo.record_approval(self.p, self.r, ref.artifact_id, ref.version, ref.sha256, "approve", "fixture")
            w.add_task("t1", self.plan.artifact_id, "divide", ["FR1"], ["development"])
            if status != "todo":
                w.update_task("t1", "todo", status, 0)
            w.start_step("s-tester", "Tester", 1, [], "t1")
        return SimpleNamespace(
            role="Tester", project_id=self.p, run_id=self.r, lease_token="w", step_id="s-tester", task_id="t1",
            inputs=(self.req, self.arch, self.plan, dev_ref, patch_ref),
            context={"input_commit": receipt["output_commit"], "task": self.task,
                     "dev_result": dev_payload.model_dump(), "config": {}, "attempt": 1},
        )

    def test_tester_schemas_compatible_with_llm_envelope(self):
        for schema in (TesterPlan.model_json_schema(), BugDiagnosis.model_json_schema()):
            wrapped = envelope_schema(schema, {})
            self.assertIn("output", wrapped["properties"])

    async def test_missing_approval_or_wrong_state_stops_before_model(self):
        order = self._prepare_dev_delivery("def divide(a, b):\n    return a / b\n", approve=False)
        coding = CodingAgents(self.store, "fixture", model=lambda *_: self.fail("unexpected model call"))
        with self.assertRaisesRegex(ValueError, "approval"):
            await coding.execute(order)

    async def test_tester_cannot_edit_app_or_evaluation_over_real_mcp_stdio(self):
        order = self._prepare_dev_delivery("def divide(a, b):\n    return a / b\n")
        for forbidden_path in ("app/calc.py", "evaluation/eval_hidden.py"):
            with self.subTest(path=forbidden_path):
                def rogue_model(prompt, schema):
                    return ModelReply("fixture", {
                        "summary": "attempted forbidden edit",
                        "suite_id": "development",
                        "test_files": [{"path": forbidden_path, "text": "# unauthorized\n"}],
                        "review_findings": [],
                    }, [], {"input_tokens": 10, "output_tokens": 5}, True, "1" * 64, "2" * 64)

                # Uses the real step_client MCP stdio subprocess without needing Docker.
                coding = CodingAgents(self.store, "fixture", model=rogue_model, client_factory=step_client)
                with self.assertRaisesRegex(RuntimeError, "tool_denied"):
                    await coding.execute(order)
                self.assertEqual(self.ws.read("app/calc.py").decode(), "def divide(a, b):\n    return a / b\n")
        with self.db.transaction() as repo:
            denied = [r for r in repo.for_run(self.p, self.r).records("tool_calls") if r["status"] == "denied"]
            self.assertEqual(len(denied), 2)

    async def test_tester_reproduces_bug_and_emits_review_and_bug_report(self):
        # Buggy implementation: returns 0 instead of raising ValueError on zero divisor.
        order = self._prepare_dev_delivery("def divide(a, b):\n    return 0 if b == 0 else a / b\n")
        calls = []

        def model(prompt, schema):
            calls.append(prompt)
            if len(calls) == 1:
                self.assertIn("app/calc.py", prompt)
                self.assertIn("Quy trình chuẩn cho Tester Agent", prompt)
                return ModelReply("fixture", {
                    "summary": "Added happy-path and zero-division boundary tests",
                    "suite_id": "development",
                    "test_files": [{
                        "path": "tests_dev/test_calc.py",
                        "text": (
                            "from app.calc import divide\n\n"
                            "def test_divide_happy():\n    assert divide(10, 2) == 5\n\n"
                            "def test_divide_zero_raises():\n"
                            "    try:\n        divide(10, 0)\n    except ValueError:\n        return\n"
                            "    raise AssertionError('expected ValueError on division by zero')\n"
                        ),
                    }],
                    "review_findings": [{
                        "severity": "high",
                        "file": "app/calc.py",
                        "message": "divide(a, 0) returns 0 instead of raising ValueError per FR1",
                        "requirement_id": "FR1",
                    }],
                }, [], {"input_tokens": 120, "output_tokens": 60, "cache_read_tokens": 10}, True, "1" * 64, "2" * 64)
            self.assertIn("expected ValueError on division by zero", prompt)
            return ModelReply("fixture", {
                "summary": "Boundary test failed because divide(10, 0) returned 0",
                "severity": "high",
                "category": "code",
                "requirement_ids": ["FR1"],
                "reproduce": ["Run suite development", "Execute tests_dev/test_calc.py::test_divide_zero_raises"],
                "expected": "divide(10, 0) raises ValueError",
                "actual": "AssertionError: expected ValueError on division by zero",
                "findings": [{
                    "severity": "high",
                    "file": "app/calc.py",
                    "message": "Missing ValueError on b == 0 confirmed by failing test",
                    "requirement_id": "FR1",
                }],
            }, [], {"input_tokens": 80, "output_tokens": 40, "cache_read_tokens": 5}, True, "3" * 64, "4" * 64)

        coding = CodingAgents(self.store, "local-python-test", model=model, client_factory=make_gateway_client_factory())
        result = await coding.execute(order)
        report = result["payload"]
        bug = result["bug"]

        self.assertFalse(report.all_passed)
        self.assertEqual((report.passed, report.failures, report.errors, report.skipped), (1, 1, 0, 0))
        self.assertEqual(report.commit, self.ws.head())
        self.assertTrue(result["report_id"])
        self.assertIsNotNone(bug)
        self.assertEqual(bug.category, "code")
        self.assertEqual(bug.commit, report.commit)
        self.assertEqual(bug.report, report.runner_output)
        self.assertEqual(bug.requirement_ids, ["FR1"])
        self.assertEqual(result["usage"]["input_tokens"], 200)
        self.assertEqual(result["usage"]["output_tokens"], 100)
        self.assertEqual(result["usage"]["cached_tokens"], 15)
        self.assertTrue(result["usage"]["usage_complete"])

        # Verify ReviewReport persisted via I03's "document" artifact kind.
        with self.db.transaction() as repo:
            docs = [a for a in repo.for_run(self.p, self.r).records("artifacts") if a["type"] == "document"]
        self.assertEqual(len(docs), 1)
        review = ReviewReport.model_validate_json(
            self.store.read(self.p, self.r, docs[0]["id"], docs[0]["version"], docs[0]["sha256"])
        )
        self.assertEqual(review.verdict, "fail")
        self.assertEqual(review.severity, "high")
        self.assertEqual(review.dev_commit, order.context["input_commit"])
        self.assertEqual(review.commit, report.commit)
        self.assertGreaterEqual(len(review.findings), 2)

    async def test_tester_passes_valid_code_without_bug_report(self):
        order = self._prepare_dev_delivery(
            "def divide(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"
        )
        calls = 0

        def model(prompt, schema):
            nonlocal calls
            calls += 1
            return ModelReply("fixture", {
                "summary": "Verified happy path and boundary check",
                "suite_id": "development",
                "test_files": [{
                    "path": "tests_dev/test_calc.py",
                    "text": (
                        "from app.calc import divide\n\n"
                        "def test_divide_happy():\n    assert divide(10, 2) == 5\n\n"
                        "def test_divide_zero():\n"
                        "    try:\n        divide(10, 0)\n    except ValueError:\n        return\n"
                        "    raise AssertionError('expected ValueError')\n"
                    ),
                }],
                "review_findings": [],
            }, [], {"input_tokens": 90, "output_tokens": 35}, True, "1" * 64, "2" * 64)

        coding = CodingAgents(self.store, "local-python-test", model=model, client_factory=make_gateway_client_factory())
        result = await coding.execute(order)
        self.assertEqual(calls, 1)
        self.assertTrue(result["payload"].all_passed)
        self.assertEqual(result["payload"].passed, 2)
        self.assertIsNone(result["bug"])

        with self.db.transaction() as repo:
            docs = [a for a in repo.for_run(self.p, self.r).records("artifacts") if a["type"] == "document"]
        review = ReviewReport.model_validate_json(
            self.store.read(self.p, self.r, docs[0]["id"], docs[0]["version"], docs[0]["sha256"])
        )
        self.assertEqual(review.verdict, "pass")
        self.assertIsNone(review.severity)

    async def test_infrastructure_runner_status_forces_infrastructure_category(self):
        order = self._prepare_dev_delivery("def divide(a, b):\n    return a / b\n")
        calls = 0

        def model(prompt, schema):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ModelReply("fixture", {
                    "summary": "Add calc test",
                    "suite_id": "development",
                    "test_files": [{"path": "tests_dev/test_calc.py", "text": "def test_ok():\n    assert True\n"}],
                    "review_findings": [],
                }, [], {"input_tokens": 40, "output_tokens": 20}, True, "1" * 64, "2" * 64)
            # Even if model guesses "code", host guard overrides to "infrastructure" when runner reports infra error.
            return ModelReply("fixture", {
                "summary": "Runner timed out",
                "severity": "critical",
                "category": "code",
                "requirement_ids": ["FR1"],
                "reproduce": ["Run suite development"],
                "expected": "Suite executes inside runner",
                "actual": "Simulated runner timeout / container infrastructure failure",
                "findings": [],
            }, [], {"input_tokens": 40, "output_tokens": 20}, True, "3" * 64, "4" * 64)

        coding = CodingAgents(
            self.store, "local-python-test", model=model,
            client_factory=make_gateway_client_factory(force_infra=True),
        )
        result = await coding.execute(order)
        self.assertFalse(result["payload"].all_passed)
        self.assertEqual(result["bug"].category, "infrastructure")

    @unittest.skipUnless(os.getenv("KTPM_TEST_RUNNER_IMAGE"), "requires a local Docker test image")
    async def test_tester_with_real_docker_runner(self):
        order = self._prepare_dev_delivery("def divide(a, b):\n    return 0 if b == 0 else a / b\n")
        turn = 0

        def fixture(prompt, schema):
            nonlocal turn
            turn += 1
            if turn == 1:
                return ModelReply("fixture", {
                    "summary": "Boundary test for zero divisor",
                    "suite_id": "development",
                    "test_files": [{
                        "path": "tests_dev/test_calc.py",
                        "text": (
                            "import pytest\nfrom app.calc import divide\n\n"
                            "def test_divide():\n    assert divide(10, 2) == 5\n\n"
                            "def test_divide_zero():\n    with pytest.raises(ValueError):\n        divide(10, 0)\n"
                        ),
                    }],
                    "review_findings": [{
                        "severity": "high", "file": "app/calc.py",
                        "message": "divide(a, 0) returns 0 instead of ValueError", "requirement_id": "FR1",
                    }],
                }, [], {}, False, "1" * 64, "2" * 64)
            return ModelReply("fixture", {
                "summary": "Zero divisor bug confirmed by Docker runner",
                "severity": "high", "category": "code", "requirement_ids": ["FR1"],
                "reproduce": ["pytest tests_dev/test_calc.py"],
                "expected": "ValueError raised for b == 0",
                "actual": "divide(10, 0) returned 0",
                "findings": [],
            }, [], {}, False, "3" * 64, "4" * 64)

        model = invoke if os.getenv("KTPM_LIVE_MODEL") == "1" else fixture
        result = await CodingAgents(self.store, os.environ["KTPM_TEST_RUNNER_IMAGE"], model=model).execute(order)
        self.assertFalse(result["payload"].all_passed)
        self.assertIsNotNone(result["bug"])
        self.assertEqual(result["bug"].commit, self.ws.head())
        print("model", "Neon High" if model is invoke else "fixture", "usage", result["usage"],
              "commit", result["payload"].commit, "passed", result["payload"].passed,
              "failures", result["payload"].failures, "bug", result["bug"].category)
