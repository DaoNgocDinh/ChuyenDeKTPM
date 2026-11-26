import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from backend.docker_runner import DockerRunner, Interrupted, bounded_command, read_junit, snapshot


def git(root, *args):
    return subprocess.check_output(["git", "-C", root, *args], stderr=subprocess.DEVNULL, text=True).strip()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Runner fixture")
        git(self.repo, "config", "user.email", "test@example.invalid")
        for path, data in {"app/server.py": "value=1\n", "tests_dev/test_smoke.py": "def test_ok(): assert True\n",
                           "app/.env": "CODE=hidden", "evaluation/hidden.py": "protected"}.items():
            file = self.repo / path
            file.parent.mkdir(exist_ok=True)
            file.write_text(data, encoding="utf-8")
        self.commit = self.commit_fixture()

    def commit_fixture(self):
        git(self.repo, "add", "-f", ".")
        git(self.repo, "commit", "-qm", "runner fixture")
        return git(self.repo, "rev-parse", "HEAD")

    def test_snapshot_is_exact_commit_and_excludes_other_data(self):
        (self.repo / "app/server.py").write_text("uncommitted change", encoding="utf-8")
        (self.repo / "app/untracked").touch()
        target = self.root / "snapshot"
        snapshot(self.repo, self.commit, target)
        self.assertEqual((target / "app/server.py").read_text().strip(), "value=1")
        self.assertFalse(any((target / s).exists() for s in ("evaluation", "app/.env", "app/untracked", ".git")))

    def test_snapshot_refuses_expected_secret_before_mount(self):
        with self.assertRaisesRegex(ValueError, "credential detected"):
            snapshot(self.repo, self.commit, self.root / "snapshot", [b"value=1"])

    def test_junit_counts_each_test_and_redacts_output(self):
        data = b'<testsuite tests="4"><testcase name="successful"/><testcase><skipped/></testcase><testcase><error/></testcase><testcase><failure message="TOKEN"/></testcase><system-out>TOKEN</system-out></testsuite>'
        result, safe = read_junit(data, lambda s: s.replace("TOKEN", "[REDACTED]"))
        self.assertEqual(result, dict(passed=1, failed=1, errors=1, skipped=1))
        self.assertNotIn(b"TOKEN", safe)
        self.assertEqual(read_junit(b"<testsuite/>", str)[0]["passed"], 0)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            read_junit(b'<testsuite tests="7"><testcase/></testsuite>', str)

    def test_junit_rejects_document_type_declaration(self):
        with self.assertRaises(ValueError):
            read_junit(b"<!DOCTYPE x><testsuite/>", str)

    def test_unknown_suite_is_denied_and_cannot_create_output(self):
        root = self.root / "reports"
        runner = DockerRunner("sha256:" + "a" * 64, root)
        with self.assertRaisesRegex(ValueError, "tool_denied"):
            runner.run(self.repo, self.commit, "arbitrary")
        self.assertFalse(root.exists())

    def test_client_output_and_deadline_are_bounded(self):
        rc, data, truncated = bounded_command([sys.executable, "-c", "print('x' * 999)"],
                                               time.monotonic() + 10, threading.Event(), 10)
        self.assertEqual((rc, data, truncated), (0, b"x" * 10, True))
        with self.assertRaisesRegex(Interrupted, "timeout"):
            bounded_command([sys.executable, "-c", "import time; time.sleep(5)"],
                            time.monotonic() + 0.2, threading.Event(), 10)

    @unittest.skipUnless(os.environ.get("KTPM_RUNNER_IMAGE"), "set KTPM_RUNNER_IMAGE to an installed image ID or digest")
    def test_real_docker_suites_and_cleanup(self):
        frontend = self.repo / "app/frontend"
        frontend.mkdir()
        package = {"name": "fixture", "version": "1.0.0", "scripts": {"build": "node --check app.js"}}
        (frontend / "package.json").write_text(json.dumps(package), encoding="utf-8")
        lock = {"name": "fixture", "version": "1.0.0", "lockfileVersion": 3,
                "packages": {"": {"name": "fixture", "version": "1.0.0"}}}
        (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        (frontend / "app.js").write_text("const title = 'CRUD';", encoding="utf-8")
        (self.repo / "app/server.py").write_text(
            "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef health(): return {'ok': True}\n",
            encoding="utf-8")
        smoke = self.repo / "tests_dev/test_smoke.py"
        smoke.write_text("from app.server import app\nfrom fastapi.testclient import TestClient\n"
                         "import os\nfrom pathlib import Path\n"
                         "def test_health():\n assert TestClient(app).get('/health').json() == {'ok': True}\n"
                         " assert not os.getenv('KTPM_RUNNER_IMAGE') and not Path('/var/run/docker.sock').exists()\n"
                         " assert not Path('/input/evaluation').exists() and not Path('/workspace/app/.env').exists()\n",
                         encoding="utf-8")
        runner = DockerRunner(os.environ["KTPM_RUNNER_IMAGE"], self.root / "reports")
        evidence = []

        def record(label, report):
            item = dict(report)
            item["scenario"] = label
            item["log"] = (runner.report_root / item.pop("log_uri")).read_text(encoding="utf-8")
            junit = item.pop("junit_uri")
            item["junit"] = (runner.report_root / junit).read_text(encoding="utf-8") if junit else None
            evidence.append(item)

        commit = self.commit_fixture()
        for suite in ("build", "smoke", "development"):
            report = runner.run(self.repo, commit, suite)
            record("clean_" + suite, report)
            self.assertEqual(report["status"], "passed", report)
            self.assertGreater(report["passed"], 0)
            self.assertTrue((runner.report_root / report["junit_uri"]).is_file())
        for label, code, count in [
                ("skip", "import pytest\ndef test_skipped(): pytest.skip('fixture')\n", "skipped"),
                ("fail", "def test_fail(): assert False\n", "failed"),
                ("zero", "# no cases collected\n", None)]:
            smoke.write_text(code, encoding="utf-8")
            report = runner.run(self.repo, self.commit_fixture(), "smoke")
            record(label, report)
            self.assertEqual(report["status"], "failed", report)
            self.assertEqual(report[count] if count else report["passed"], 1 if count else 0)
        smoke.write_text("import time\ndef test_slow(): time.sleep(30)\n", encoding="utf-8")
        commit = self.commit_fixture()
        runner.profiles["smoke"] = replace(runner.profiles["smoke"], timeout_seconds=10)
        for label in ("timeout", "cancelled"):
            cancel = threading.Event()
            timer = threading.Timer(5, cancel.set) if label == "cancelled" else None
            if timer:
                timer.start()
            try:
                report = runner.run(self.repo, commit, "smoke", cancel=cancel)
            finally:
                if timer:
                    timer.cancel()
            self.assertEqual(report["status"], label, report)
            record(label, report)
            rc = subprocess.run(["docker", "container", "inspect", "ktpm-suite-" + report["report_id"]], capture_output=True)
            self.assertNotEqual(rc.returncode, 0)
        evidence_path = os.environ.get("KTPM_RUNNER_EVIDENCE")
        if evidence_path:
            Path(evidence_path).write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
