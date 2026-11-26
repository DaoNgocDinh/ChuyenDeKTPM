"""Connect I15 Docker build evidence to the existing independent E01 evaluator."""

import json
import re
from contextlib import ExitStack
from pathlib import Path

from backend.docker_runner import DockerRunner, read_junit
from evaluation.checksums import verify_manifest
from evaluation.reporting import run_case_evaluation


class VerifiedBuildAdapter:
    """The evaluator still calls the application's own API and browser adapter for all criteria."""

    def __init__(self, case_id, adapter, build_ok, message):
        self.case_id = case_id
        self._adapter = adapter
        self._result = build_ok, message

    def build_check(self):
        return self._result

    def __getattr__(self, name):
        return getattr(self._adapter, name)


def build_evidence(report_root, report, commit):
    key = report.get("report_id", "")
    if not re.fullmatch(r"[a-f0-9]{32}", key) or report.get("suite_id") != "build" or report.get("commit") != commit:
        raise ValueError("build report does not identify the requested suite and commit")
    directory = report_root / key
    if json.loads((directory / "report.json").read_text(encoding="utf-8")) != report:
        raise ValueError("persisted and returned build evidence disagree")
    ok = report["status"] == "passed" and report["exit_code"] == 0
    if ok:
        if report["junit_uri"] != f"{key}/junit.xml":
            raise ValueError("invalid build JUnit reference")
        counts, _ = read_junit((directory / "junit.xml").read_bytes(), str)
        if counts["passed"] <= 0 or any(counts[k] for k in ("failed", "errors", "skipped")):
            raise ValueError("claimed build success contradicts JUnit")
        if any(report[k] != v for k, v in counts.items()):
            raise ValueError("claimed build counts contradict JUnit")
    return ok, f"I15 {key} {report['status']} ({report['image_digest']})"


def run_docker_evaluation(case_id, open_adapter, *, repo, code_commit, runner: DockerRunner, output_dir: Path):
    """open_adapter(commit) returns a context manager for the app deployed at that commit."""
    valid, problems = verify_manifest()
    if not valid:
        raise ValueError("E01 checksum mismatch: " + ", ".join(problems))
    raw = runner.run(repo, code_commit, "build")
    ok, message = build_evidence(runner.report_root, raw, code_commit)
    with ExitStack() as stack:
        app = stack.enter_context(open_adapter(code_commit)) if ok else None
        if ok and app.case_id != case_id:
            raise ValueError("wrong application adapter for case")
        adapter = VerifiedBuildAdapter(case_id, app, ok, message)
        return run_case_evaluation(case_id, adapter, code_commit=code_commit, output_dir=output_dir)
