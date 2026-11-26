import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.docker_runner import DockerRunner
from evaluation.docker_build import build_evidence, run_docker_evaluation


class DockerEvaluationTests(unittest.TestCase):
    def test_build_evidence_must_belong_to_same_commit(self):
        with self.assertRaisesRegex(ValueError, "commit"):
            build_evidence(Path("."), {"report_id": "a" * 32, "suite_id": "build", "commit": "b" * 40}, "c" * 40)

    def test_claimed_success_requires_matching_junit_counts(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            key = "a" * 32
            commit = "b" * 40
            folder = root / key
            folder.mkdir()
            report = dict(report_id=key, suite_id="build", commit=commit, image_digest="sha256:" + "c" * 64,
                          status="passed", exit_code=0, passed=1, failed=0, errors=0, skipped=0, junit_uri=key+"/junit.xml")
            (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
            (folder / "junit.xml").write_text("<testsuite><testcase><failure/></testcase></testsuite>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contradicts JUnit"):
                build_evidence(root, report, commit)

    @unittest.skipUnless(os.environ.get("KTPM_RUNNER_IMAGE"), "requires pinned local I15 image")
    def test_failed_real_docker_build_scores_zero_before_any_criterion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / "app").mkdir(parents=True)
            (repo / "app/broken.py").write_text("def broken(:", encoding="utf-8")
            def git(*args):
                return subprocess.check_output(["git", "-C", repo, *args], text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-q")
            git("add", "app")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "broken app")
            target = git("rev-parse", "HEAD")
            runner = DockerRunner(os.environ["KTPM_RUNNER_IMAGE"], root / "builds")
            def must_not_launch(_):
                self.fail("app adapter launched after failed build")
            result = run_docker_evaluation("A1", must_not_launch, repo=repo, code_commit=target, runner=runner,
                                           output_dir=root / "evaluation")
            self.assertFalse(result.build_ok)
            self.assertEqual((result.acceptance_passed, result.acceptance_total, result.failed), (0, 10, 10))
            self.assertEqual(result.code_commit, target)
            self.assertTrue((root / "evaluation/A1_junit.xml").is_file())
