import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.approvals import InvalidGateTransition
from backend.artifacts import ArtifactStore
from backend.contracts import ArtifactRef
from backend.orchestrator import Orchestrator, RoleOutput
from backend.storage import Database
from backend.worker import Queue, Worker
from backend.workspace import Edit, Workspace


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = Database(root / "db.sqlite")
        self.db.migrate()
        self.store = ArtifactStore(root / "workspaces", self.db)
        self.queue = Queue(self.db)
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1", "brief/A1")
        self.run = self.queue.enqueue(self.project, "one", {}, {})
        self.calls = []
        self.ask = False
        self.fault = None
        self.host = Orchestrator(self.queue, self.store, self.dispatch, lambda lease, refs: True)
        self.worker = Worker(self.queue, self.host)

    def data(self):
        with self.db.transaction() as repo:
            return repo.get_run(self.project, self.run)

    def gate(self, name):
        checkpoint = json.loads(self.data()["checkpoint_json"])
        gate = checkpoint["pending_gate"]
        self.assertEqual(gate["gate"], name)
        return [ArtifactRef.model_validate(r) for r in gate["artifacts"]]

    def approve(self, name):
        refs = self.gate(name)
        self.host.gates.decide_gate(self.project, self.run, name, refs, "approve")

    def put(self, order, kind, content):
        with self.db.transaction() as repo:
            version = repo.for_run(self.project, self.run).latest_version(kind)
        return self.store.put(self.project, self.run, order.lease_token, kind, content, created_by="host",
                              expected_previous_version=version)

    def dispatch(self, order):
        role = order.role
        self.calls.append(role)
        if role == "Orchestrator":
            return RoleOutput({"requested_role": "Dev", "decision": "approve"})
        if role == "Requirement":
            return RoleOutput({"actors":["Owner"], "functional":[{"id":"FR1","description":"Create","acceptance":["OK"]}],
                               "nonfunctional":[],"assumptions":[],"questions":["Which title?"] if self.ask else []},
                              markdown="# Requirements")
        if role == "Architecture":
            return RoleOutput({"requirements":order.inputs[0].model_dump(), "adr":["SQLite"], "components":{"api":"API"},
                               "entities":{"Task":"id"}, "api_contract":{"GET /":"list"}, "frontend":"web",
                               "test_strategy":"unit","fr_components":{"FR1":["api"]}})
        if role == "Planning":
            tasks = [{"task_id":k, "requirement_ids":["FR1"], "dependencies":deps, "files":[f"app/{k}.py"],
                      "done_conditions":["works"], "tests":[k]} for k,deps in [("filter",["title"]),("title",[])]]
            return RoleOutput({"requirements":order.inputs[0].model_dump(), "architecture":order.inputs[1].model_dump(),
                               "tasks":tasks})
        workspace = Workspace(self.store.root, self.project, self.run)
        label = order.context["task"]["task_id"]
        if role == "Dev":
            receipt = workspace.apply(order.task_id, workspace.head(), [Edit(f"app/{label}.py", None, "OK = True\n")])
            patch = self.put(order, "patch", receipt["diff"])
            result = {"task_id":order.task_id, "input_commit":receipt["input_commit"],
                      "output_commit":receipt["output_commit"], "patch_sha256":receipt["patch_hash"],
                      "changed_files":[f"app/{label}.py"], "summary":label}
            return RoleOutput(result, patch_ref=patch)
        path = f"tests_dev/test_{label}.py"
        test = f"from app.{label} import OK\nassert OK\n"
        if self.fault == "app_write":
            workspace.apply(order.task_id, workspace.head(), [Edit("app/unexpected.py", None, "# changed")])
        else:
            workspace.apply(order.task_id, workspace.head(), [Edit(path, None, test)])
        commit = workspace.head()
        result = subprocess.run([sys.executable, "-B", "-c", test], cwd=workspace.path, capture_output=True)
        passed = int(result.returncode == 0)
        raw = self.put(order, "runner_output", json.dumps({"exit_code":result.returncode,"passed":passed}))
        with self.db.transaction(write=True) as repo:
            writer = repo.worker_run(self.project, self.run, order.lease_token)
            report_id = writer.add_report(order.task_id, commit,"unit","reports/"+label,result.returncode,
                                          passed,1-passed,0,0,1)
        return RoleOutput({"task_id":order.task_id,"commit":commit,"suite_id":"unit","runner_output":raw.model_dump(),
                           "exit_code":result.returncode,"passed":passed,"failures":1-passed,"errors":0,"skipped":0},
                          report_id=report_id if self.fault != "missing_report" else None)

    def test_six_roles_two_real_owner_gates_and_dependency_order(self):
        self.worker.run_one()
        self.assertEqual(self.data()["status"], "waiting_approval")
        self.assertNotIn("Architecture", self.calls)
        self.approve("requirements")
        self.worker.run_one()
        self.assertNotIn("Dev", self.calls)
        self.approve("architecture_plan")
        self.worker.run_one()
        self.assertEqual(self.data()["status"], "completed")
        self.assertEqual(set(self.calls), {"Requirement","Architecture","Planning","Dev","Tester","Orchestrator"})
        with self.db.transaction() as repo:
            view = repo.for_run(self.project, self.run)
            tasks = {t["id"]: t for t in view.records("tasks")}
            dev = [step for step in view.records("agent_steps") if step["agent_role"] == "dev"]
            self.assertEqual([tasks[step["task_id"]]["description"] for step in dev], ["title","filter"])
            self.assertTrue(all(t["status"] == "done" for t in tasks.values()))
            self.assertEqual(len(view.records("approvals")), 3)
            self.assertEqual(view.latest_version("requirements_markdown"), 1)
        self.assertTrue(self.host.audit.trace_requirement(self.project, self.run, "FR1").complete)
        self.assertEqual(self.queue.enqueue(self.project, "one", {}, {}), self.run)

    def test_version_bound_clarification_must_be_answered_before_approval(self):
        self.ask = True
        self.worker.run_one()
        refs = self.gate("requirements")
        with self.assertRaises(InvalidGateTransition):
            self.host.gates.decide_gate(self.project, self.run, "requirements", refs, "approve")
        self.host.gates.record_clarification(self.project, self.run, refs[0], [{"question_id":"Q1","answer":"Task title"}])
        self.ask = False
        self.worker.run_one()
        replacement = self.gate("requirements")
        self.assertEqual(replacement[0].version, 2)
        self.assertNotIn("Architecture", self.calls)

    def test_tester_cannot_change_app_or_claim_evidence_without_runner(self):
        for fault in ("missing_report", "app_write"):
            with self.subTest(fault=fault):
                self.run = self.queue.enqueue(self.project, fault, {}, {})
                # Isolate the first fixture's unclaimed run.
                with self.db.transaction(write=True) as repo:
                    repo._db.execute("UPDATE runs SET status='cancelled' WHERE status='queued' AND id<>?", (self.run,))
                self.fault = fault
                self.worker.run_one()
                self.approve("requirements")
                self.worker.run_one()
                self.approve("architecture_plan")
                self.worker.run_one()
                self.assertEqual(self.data()["status"], "needs_human_review")

    def test_exhausted_budget_blocks_first_model_call(self):
        with self.db.transaction(write=True) as repo:
            repo._db.execute("UPDATE runs SET budget_json=? WHERE id=?", (json.dumps({"max_total_tokens":0}), self.run))
        self.worker.run_one()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.data()["status"], "needs_human_review")
