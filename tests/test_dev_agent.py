import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from backend.artifacts import ArtifactStore
from backend.coding_agents import CodingAgents
from backend.llm import ModelReply, invoke
from backend.storage import Database
from backend.workspace import Edit, Workspace
from tests.test_tester_agent import make_gateway_client_factory


class DevAgentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(Path(tmp.name) / "platform.db")
        self.db.migrate()
        self.root = Path(tmp.name) / "workspaces"
        self.store = ArtifactStore(self.root,self.db)
        with self.db.transaction(write=True) as repo:
            self.p = repo.create_project("Smoke demo","brief")
            self.r = repo.create_run(self.p,"test",{}, {})
        with closing(sqlite3.connect(self.db.path)) as con, con:
            con.execute("UPDATE runs SET status='running',worker_lease='w',lease_expires_at=datetime('now','+20 minutes')")
        self.ws = Workspace(self.root,self.p,self.r)
        start = self.ws.initialize()
        self.base = self.ws.apply("seed",start,[Edit("tests_dev/test_smoke.py",None,
            "from app.message import greeting\n\ndef test_greeting():\n    assert greeting() == 'hello'\n")])["output_commit"]
        def put(kind, value):
            return self.store.put(self.p,self.r,"w",kind,value,created_by="fixture")
        self.req = put("requirements",dict(actors=["visitor"],functional=[{"id":"FR1","description":"greeting",
             "acceptance":["greeting() returns hello"]}],nonfunctional=[],assumptions=[],questions=[]))
        self.arch = put("architecture",dict(requirements=self.req.model_dump(),adr=["Python function"],
            components={"app":"python"},entities={"message":"text"},api_contract={"function":"greeting"},
            frontend="out of scope for this task",test_strategy="smoke",fr_components={"FR1":["app"]}))
        self.task = dict(task_id="T1",requirement_ids=["FR1"],dependencies=[],files=["app/message.py"],
                         done_conditions=["Implement greeting() with no arguments returning exactly the string hello."],
                         tests=["smoke"])
        self.plan = put("plan",dict(requirements=self.req.model_dump(),architecture=self.arch.model_dump(),tasks=[self.task]))
        self.order = SimpleNamespace(role="Dev",project_id=self.p,run_id=self.r,lease_token="w",step_id="s",
            task_id="t",inputs=(self.req,self.arch,self.plan),
            context={"input_commit":self.base,"task":self.task,"config":{}})

    def activate_fixture(self):
        with self.db.transaction(write=True) as repo:
            w = repo.worker_run(self.p,self.r,"w")
            for ref in self.order.inputs:
                repo.record_approval(self.p,self.r,ref.artifact_id,ref.version,ref.sha256,"approve","test fixture")
            w.add_task("t",self.plan.artifact_id,"greeting",["FR1"],["smoke"])
            w.update_task("t","todo","in_progress",0)
            w.start_step("s","Dev",1,[],"t")

    async def test_missing_approval_stops_before_model(self):
        coding = CodingAgents(self.store,"fixture",model=lambda *_: self.fail("unexpected model call"))
        with self.assertRaisesRegex(ValueError,"approval"):
            await coding.execute(self.order)

    async def test_dependent_dev_task_receives_existing_prior_app_files(self):
        prior_commit = self.ws.apply(
            "t0", self.base, [Edit("app/db.py", None, "def init_db():\n    return 'ready'\n")],
        )["output_commit"]
        self.activate_fixture()
        order = SimpleNamespace(**{**vars(self.order), "context": {**self.order.context, "input_commit": prior_commit}})
        seen_prompts = []

        def fixture(prompt, schema):
            seen_prompts.append(prompt)
            return ModelReply("fixture", {
                "summary": "implement message using db",
                "blocker": None,
                "files": [{"path": "app/message.py", "text": "from app.db import init_db\n\ndef greeting():\n    return 'hello'\n"}],
            }, [], {"input_tokens": 20, "output_tokens": 10}, True, "1" * 64, "2" * 64)

        coding = CodingAgents(self.store, "local-python-test", model=fixture, client_factory=make_gateway_client_factory())
        result = await coding.execute(order)
        self.assertEqual(len(seen_prompts), 1)
        self.assertIn("app/db.py", seen_prompts[0])
        self.assertIn("def init_db()", seen_prompts[0])
        self.assertEqual(result["payload"].changed_files, ["app/message.py"])

    @unittest.skipUnless(os.getenv("KTPM_TEST_RUNNER_IMAGE"),"requires a local Docker test image")
    async def test_commit_and_real_runner(self):
        self.activate_fixture()
        def fixture(prompt, schema):
            self.assertIn("app/message.py",prompt)
            return ModelReply("fixture",{"summary":"greeting","blocker":None,"files":[{"path":"app/message.py",
                "text":"def greeting():\n    return 'hello'\n"}]},[],{},False,"1"*64,"2"*64)
        model = invoke if os.getenv("KTPM_LIVE_MODEL") == "1" else fixture
        result = await CodingAgents(self.store,os.environ["KTPM_TEST_RUNNER_IMAGE"],model=model).execute(self.order)
        self.assertEqual(self.ws.head(), result["payload"].output_commit)
        self.assertEqual(["app/message.py"],result["payload"].changed_files)
        self.assertEqual(result["patch_ref"].run_id,self.r)
        with self.db.transaction() as repo:
            view = repo.for_run(self.p,self.r)
            report = view.records("test_reports")[0]
            self.assertEqual((self.ws.head(),1,0),(report["commit_hash"],report["passed"],report["failed"]))
        print("model", "Neon High" if model is invoke else "fixture", "usage",result["usage"],
              "commit",report["commit_hash"],"suite",report["suite_id"],"passed",report["passed"])
