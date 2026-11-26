import unittest

from pydantic import ValidationError

from backend.contracts import (
    Architecture, ArtifactRef, BugReport, DevResult, Envelope, Plan, Requirements,
    Task, TestReport, check_handoff,
)


def ref(name):
    return ArtifactRef(run_id="a1", artifact_id=name, version=1, sha256="a" * 64)


def task(name, deps=()):
    return Task(task_id=name, requirement_ids=["FR1"], dependencies=list(deps),
                files=["app/tasks.py"], done_conditions=["reject empty title"], tests=["empty-title"])


class ContractsTest(unittest.TestCase):
    def test_handoff_versions_and_coverage(self):
        req = Requirements(actors=["owner"], functional=[{"id": "FR1", "description": "add task",
            "acceptance": ["reject empty title"]}], nonfunctional=[], assumptions=[], questions=[])
        arch = Architecture(requirements=ref("req"), adr=["sqlite"], components={"api": "FastAPI"},
            entities={"Task": "title"}, api_contract={"POST /tasks": "Task"}, frontend="form",
            test_strategy="test empty title", fr_components={"FR1": ["api"]})
        plan = Plan(requirements=ref("req"), architecture=ref("arch"), tasks=[task("t1")])
        check_handoff(req, arch, plan, ref("req"), ref("arch"))
        with self.assertRaisesRegex(ValueError, "stale"):
            check_handoff(req, arch, plan, ref("req").model_copy(update={"version": 2}), ref("arch"))
        with self.assertRaisesRegex(ValueError, "cover"):
            check_handoff(req, arch.model_copy(update={"fr_components": {}}), plan, ref("req"), ref("arch"))

    def test_bad_graph(self):
        for tasks in ([task("a", ["a"])], [task("a", ["x"])], [task("a"), task("a")]):
            with self.subTest(tasks=tasks), self.assertRaises(ValidationError):
                Plan(requirements=ref("req"), architecture=ref("arch"), tasks=tasks)

    def test_foreign_reference(self):
        with self.assertRaises(ValidationError):
            Envelope(message_id="m", run_id="foreign", from_role="Dev", to_role="Tester", kind="patch",
                     schema_version="1", input_refs=[ref("dev")], output_refs=[], correlation_id="job")

    def test_remaining_models_and_counts(self):
        patch = DevResult(task_id="a", input_commit="a"*40, output_commit="b"*40,
                          patch_sha256="9"*64, changed_files=["app/tasks.py"], summary="validate title")
        report = TestReport(task_id="a", commit=patch.output_commit, suite_id="smoke",
            runner_output=ref("junit"), exit_code=0, passed=1, failures=0, errors=0, skipped=0)
        self.assertTrue(report.all_passed)
        for change in ({"errors": 1}, {"passed": 0}, {"skipped": 1}, {"exit_code": 1}):
            self.assertFalse(report.model_copy(update=change).all_passed)
        bug = BugReport(task_id="a", commit=patch.output_commit, report=ref("junit"),
            requirement_ids=["FR1"], reproduce=["submit empty title"], expected="rejected",
            actual="created", category="code")
        self.assertEqual(bug.commit, report.commit)
