import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager, closing
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import mcp_types as mt

from backend.artifacts import ArtifactStore
from backend.baseline_single_agent import (
    SINGLE_AGENT_POLICY,
    BaselineDesignPlanOutput,
    BaselineRequirementsOutput,
    BaselineTaskDelivery,
    SingleAgentBaseline,
    SingleAgentGateway,
    assert_fair_baseline_parity,
    baseline_step_client,
)
from backend.contracts import ArtifactRef
from backend.gateway import HostStep, ToolDenied
from backend.llm import ModelReply, envelope_schema
from backend.mcp_tools import OP_KEY, SCHEMAS, TOOLS, ToolSession, discover, invoke
from backend.storage import Database
from backend.worker import Queue, Worker
from backend.workspace import Workspace
from evaluation.fixtures.reference_apps import ReferenceA1Adapter
from evaluation.reporting import run_case_evaluation
from tests.test_tester_agent import _run_local_python_suite


def make_baseline_gateway_client():
    """In-process MCP client using real SingleAgentGateway, ToolSession, Workspace, and SQLite."""
    @asynccontextmanager
    async def factory(database_path, root, host: HostStep, image=None):
        session = ToolSession({
            "database": str(Path(database_path).resolve()),
            "root": str(Path(root).resolve()),
            "host": asdict(host),
            "image": image,
        })
        session.gateway = SingleAgentGateway(session.database, session.root)

        def dispatch(ws, step, name, args):
            if name != "tests.run_suite":
                return session.dispatch(ws, step, name, args)
            model = TOOLS[name][0].model_validate(args)
            report, log = _run_local_python_suite(ws, ws.head(), model.suite_id)
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
            protocol_version = "local-baseline-gateway"

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


class SingleAgentBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "baseline.db")
        self.db.migrate()
        self.ws_root = root / "workspaces"
        self.store = ArtifactStore(self.ws_root, self.db)
        self.queue = Queue(self.db)
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1 Baseline", "brief/A1")

    def _run_row(self, run_id):
        with self.db.transaction() as repo:
            return repo.get_run(self.project, run_id)

    def _approve_gate(self, baseline, run_id, expected_gate):
        checkpoint = json.loads(self._run_row(run_id)["checkpoint_json"])
        pending = checkpoint["pending_gate"]
        self.assertEqual(pending["gate"], expected_gate)
        refs = [ArtifactRef.model_validate(item) for item in pending["artifacts"]]
        baseline.gates.decide_gate(self.project, run_id, expected_gate, refs, "approve")
        return refs

    def test_fairness_parity_policy_and_schemas(self):
        self.assertEqual(SINGLE_AGENT_POLICY["write"], ["app", "tests_dev"])
        self.assertEqual(SINGLE_AGENT_POLICY["suites"], ["build", "development", "smoke"])
        self.assertNotIn("evaluation", SINGLE_AGENT_POLICY["write"])
        self.assertNotIn("skills", SINGLE_AGENT_POLICY["write"])

        for schema in (
            BaselineRequirementsOutput.model_json_schema(),
            BaselineDesignPlanOutput.model_json_schema(),
            BaselineTaskDelivery.model_json_schema(),
        ):
            self.assertIn("output", envelope_schema(schema, {})["properties"])

        base_cfg = {"model": "gemini-4-neon-high", "skills_enabled": True, "runner_image": "img", "case_id": "A1"}
        base_budget = {"max_total_tokens": 50000, "max_tool_calls": 100, "max_auto_seconds": 600, "max_repair_rounds": 3}
        assert_fair_baseline_parity(base_cfg, dict(base_cfg), base_budget, dict(base_budget))

        # Giving M 6x token budget MUST fail fairness parity check.
        unfair_m = {**base_budget, "max_total_tokens": 300000}
        with self.assertRaisesRegex(ValueError, "max_total_tokens"):
            assert_fair_baseline_parity(base_cfg, dict(base_cfg), base_budget, unfair_m)

    def test_baseline_mcp_stdio_allows_app_and_tests_dev_but_blocks_evaluation_and_policy(self):
        run_id = self.queue.enqueue(self.project, "stdio-perm", {"mode": "single_agent"}, {})
        with closing(sqlite3.connect(self.db.path)) as conn, conn:
            conn.execute(
                "UPDATE runs SET status='running', worker_lease='w', lease_expires_at=datetime('now','+10 minutes') WHERE id=?",
                (run_id,),
            )
        with self.db.transaction(write=True) as repo:
            w = repo.worker_run(self.project, run_id, "w")
            w.add_artifact("plan1", "plan", 1, "1", "fixture", "a" * 64, "SingleAgent")
            w.add_task("t1", "plan1", "task", ["FR1"], ["development"])
            w.start_step("s1", "Dev", 1, [], "t1")
        ws = Workspace(self.ws_root, self.project, run_id)
        first = ws.initialize()

        async def exercise():
            host = HostStep(self.project, run_id, "s1", "w")
            async with baseline_step_client(self.db.path, self.ws_root, host) as client:
                manifest = await discover(client)
                self.assertEqual(set(TOOLS), set(manifest["tools"]))
                # Union permission: SingleAgent writes BOTH app/ and tests_dev/ in one atomic patch.
                res = await invoke(client, uuid4().hex, "workspace.apply_patch", {
                    "input_commit": first,
                    "edits": [
                        {"path": "app/mod.py", "expected_hash": None, "text": "VAL = 1\n"},
                        {"path": "tests_dev/test_mod.py", "expected_hash": None, "text": "from app.mod import VAL\ndef test_v(): assert VAL == 1\n"},
                    ],
                })
                head = res["output_commit"]
                # Still strictly forbidden: evaluation/, skills/, docs/, .env.
                for forbidden in ("evaluation/A1.json", "skills/implementation/SKILL.md", "docs/quyen-cong-cu.json", "app/.env"):
                    with self.assertRaisesRegex(RuntimeError, "tool_denied"):
                        await invoke(client, uuid4().hex, "workspace.apply_patch", {
                            "input_commit": head,
                            "edits": [{"path": forbidden, "expected_hash": None, "text": "x"}],
                        })
                    with self.assertRaisesRegex(RuntimeError, "tool_denied"):
                        await invoke(client, uuid4().hex, "workspace.read_file", {"path": forbidden})

        asyncio.run(exercise())
        with self.db.transaction() as repo:
            denied = [r for r in repo.for_run(self.project, run_id).records("tool_calls") if r["status"] == "denied"]
        self.assertEqual(len(denied), 8)

    def test_baseline_full_run_with_two_gates_self_repair_quota_and_e01_evaluation(self):
        budget = {"max_total_tokens": 50_000, "max_tool_calls": 100, "max_repair_rounds": 3}
        config = {"mode": "single_agent", "skills_enabled": True, "case_id": "A1"}
        run_id = self.queue.enqueue(self.project, "s-full-a1", config, budget)
        placeholder_ref = {
            "run_id": run_id, "artifact_id": "placeholder", "version": 1, "sha256": "0" * 64,
        }
        coding_turns = 0

        def model(prompt, schema):
            nonlocal coding_turns
            props = schema.get("properties", {})
            if "requirements" in props and "markdown" in props:
                return ModelReply("fixture", {
                    "requirements": {
                        "actors": ["Owner"],
                        "functional": [{"id": "FR1", "description": "Manage tasks", "acceptance": ["CRUD works"]}],
                        "nonfunctional": [], "assumptions": [], "questions": [],
                    },
                    "markdown": "# SRS Baseline S",
                }, [], {"input_tokens": 100, "output_tokens": 50}, True, "1" * 64, "2" * 64)
            if "architecture" in props and "plan" in props:
                # Extract exact req ref from prompt payload.
                payload_json = prompt.split("empty tool_proposals:\n", 1)[1]
                req_ref = json.loads(payload_json)["requirements_ref"]
                return ModelReply("fixture", {
                    "architecture": {
                        "requirements": req_ref,
                        "adr": ["Python + SQLite"],
                        "components": {"tasks": "task module"},
                        "entities": {"Task": "id,title,status,due"},
                        "api_contract": {"create": "task"},
                        "frontend": "web",
                        "test_strategy": "development tests",
                        "fr_components": {"FR1": ["tasks"]},
                    },
                    "plan": {
                        "requirements": req_ref,
                        "architecture": placeholder_ref,
                        "tasks": [{
                            "task_id": "T1",
                            "requirement_ids": ["FR1"],
                            "dependencies": [],
                            "files": ["app/tasks.py"],
                            "done_conditions": ["validate non-empty title"],
                            "tests": ["development"],
                        }],
                    },
                }, [], {"input_tokens": 120, "output_tokens": 60}, True, "3" * 64, "4" * 64)
            if "severity" in props:
                return ModelReply("fixture", {
                    "summary": "Empty title was accepted on round 1",
                    "severity": "high",
                    "category": "code",
                    "requirement_ids": ["FR1"],
                    "reproduce": ["Run development suite"],
                    "expected": "validate_title('') raises ValueError",
                    "actual": "AssertionError: expected ValueError",
                    "findings": [],
                }, [], {"input_tokens": 40, "output_tokens": 25}, True, "5" * 64, "6" * 64)

            coding_turns += 1
            if coding_turns == 1:
                # Round 0: writes both app/ and tests_dev/, fails boundary test -> triggers self-repair.
                return ModelReply("fixture", {
                    "summary": "Initial task validation + tests",
                    "blocker": None,
                    "suite_id": "development",
                    "files": [
                        {"path": "app/tasks.py", "text": "def validate_title(t):\n    return t\n"},
                        {"path": "tests_dev/test_tasks.py", "text": (
                            "from app.tasks import validate_title\n\n"
                            "def test_ok():\n    assert validate_title('Demo') == 'Demo'\n\n"
                            "def test_empty():\n    try:\n        validate_title('')\n    except ValueError:\n        return\n"
                            "    raise AssertionError('expected ValueError')\n"
                        )},
                    ],
                    "review_findings": [],
                }, [], {"input_tokens": 80, "output_tokens": 40}, True, "7" * 64, "8" * 64)
            # Repair round 1: receives BugReport and fixes app/tasks.py.
            self.assertIn("expected ValueError", prompt)
            return ModelReply("fixture", {
                "summary": "Fix empty title validation",
                "blocker": None,
                "suite_id": "development",
                "files": [{
                    "path": "app/tasks.py",
                    "text": "def validate_title(t):\n    if not t.strip():\n        raise ValueError('empty')\n    return t\n",
                }],
                "review_findings": [],
            }, [], {"input_tokens": 70, "output_tokens": 35}, True, "9" * 64, "a" * 64)

        baseline = SingleAgentBaseline(
            self.queue, self.store, "local-python-test", model=model, client_factory=make_baseline_gateway_client(),
        )
        worker = Worker(self.queue, baseline)
        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "waiting_approval")
        self._approve_gate(baseline, run_id, "requirements")

        worker.run_one()
        self.assertEqual(self._run_row(run_id)["status"], "waiting_approval")
        self._approve_gate(baseline, run_id, "architecture_plan")

        worker.run_one()
        row = self._run_row(run_id)
        self.assertEqual(row["status"], "completed")

        # Verify shared artifacts, quota snapshot, trace chain, and repair round = 1.
        persisted_quota = json.loads(row["budget_json"])
        self.assertGreater(persisted_quota["total_tokens"], 0)
        self.assertTrue(persisted_quota["usage_complete"])
        self.assertGreater(persisted_quota["tool_calls"], 0)
        self.assertTrue(baseline.audit.trace_requirement(self.project, run_id, "FR1").complete)

        with self.db.transaction() as repo:
            view = repo.for_run(self.project, run_id)
            kinds = {a["type"] for a in view.records("artifacts")}
            self.assertTrue({"requirements", "architecture", "plan", "dev_result", "patch", "test_report", "bug_report", "document"} <= kinds)
            tasks = view.records("tasks")
            self.assertEqual(tasks[0]["repair_round"], 1)

        # Evaluate the pinned baseline commit through the SAME E01 evaluation harness used for M.
        ws = Workspace(self.ws_root, self.project, run_id)
        code_commit = ws.head()
        with tempfile.TemporaryDirectory() as eval_dir:
            adapter = ReferenceA1Adapter(Path(eval_dir))
            try:
                eval_report = run_case_evaluation("A1", adapter, code_commit=code_commit, output_dir=Path(eval_dir) / "reports")
            finally:
                adapter.close()
            self.assertEqual(eval_report.code_commit, code_commit)
            self.assertEqual(eval_report.acceptance_passed, 10)
            self.assertTrue((Path(eval_dir) / "reports" / "A1_report.json").exists())
            self.assertTrue((Path(eval_dir) / "reports" / "A1_junit.xml").exists())

    def test_baseline_stops_on_budget_exceeded(self):
        run_id = self.queue.enqueue(
            self.project, "s-budget", {"mode": "single_agent"}, {"max_total_tokens": 0},
        )
        baseline = SingleAgentBaseline(
            self.queue, self.store, "local-python-test",
            model=lambda *_: self.fail("should stop before model call on zero budget"),
            client_factory=make_baseline_gateway_client(),
        )
        Worker(self.queue, baseline).run_one()
        self.assertEqual(self._run_row(run_id)["status"], "needs_human_review")
