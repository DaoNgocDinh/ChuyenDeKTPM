"""Run named host-approved suites on a Git commit. The caller owns repo and report paths."""

import json
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from backend.runner_profile import RunnerProfile


POLICY_PATH = Path(__file__).resolve().parents[1] / "docs/quyen-cong-cu.json"
SUITES = frozenset({"build", "smoke", "development"})
BOOTSTRAP = "/opt/ktpm/suite.py"


class Interrupted(Exception):
    pass


def snapshot(repo, commit, stage, secrets=()):
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", commit):
        raise ValueError("full Git commit ID required")
    resolved = subprocess.check_output(["git", "-C", repo, "rev-parse", "--verify", commit + "^{commit}"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    if resolved != commit:
        raise ValueError("object is not a commit")
    tracked = subprocess.check_output(["git", "-C", repo, "ls-tree", "-z", "--name-only", commit, "--", "app", "tests_dev"])
    roots = [entry.decode() for entry in tracked.split(b"\0") if entry]
    if "app" not in roots:
        raise ValueError("no app in the requested commit")
    archive = stage.parent / "source.zip"
    subprocess.run(["git", "-C", repo, "archive", "--format=zip", "--output", archive, commit, "--", *roots],
                   check=True, stderr=subprocess.DEVNULL)
    stage.mkdir()
    try:
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                name = entry.filename
                parts = PurePosixPath(name).parts
                if not parts or parts[0] not in roots or ".." in parts or "\\" in name or ":" in name:
                    raise ValueError("unsafe snapshot entry")
                if any(piece.startswith(".") or piece.lower().endswith((".pem", ".key", ".p12", ".pfx"))
                       or piece.lower().split(".")[0] in {"credentials", "secrets"} for piece in parts):
                    continue
                for piece in parts:
                    if piece.endswith((".", " ")):
                        raise ValueError("nonportable snapshot entry")
                    check_reserved = getattr(os.path, "isreserved", None)
                    if os.name == "nt" and (check_reserved(piece) if check_reserved else Path(piece).is_reserved()):
                        raise ValueError("reserved path in snapshot")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("symbolic links are excluded from the runner snapshot")
                target = stage.joinpath(*parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(entry) as raw, target.open("xb") as out:
                        overlap = b""
                        longest = max((len(key) for key in secrets), default=1)
                        while chunk := raw.read(64 * 1024):
                            window = overlap + chunk
                            if any(key in window for key in secrets):
                                raise ValueError("credential detected in tracked source")
                            overlap = window[-(longest - 1):] if longest > 1 else b""
                            out.write(chunk)
    finally:
        archive.unlink(missing_ok=True)


def bounded_command(command, deadline, cancelled, limit):
    """Drain the pipe past the capture limit and preserve a single deadline across Docker operations."""
    if cancelled.is_set() or time.monotonic() >= deadline:
        raise Interrupted("cancelled" if cancelled.is_set() else "timeout")
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    retained = bytearray()
    truncated = False

    def drain():
        nonlocal truncated
        with proc.stdout:
            while chunk := proc.stdout.read(8192):
                available = limit - len(retained)
                retained.extend(chunk[:available])
                if len(chunk) > available:
                    truncated = True

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            if cancelled.wait(0.05) or time.monotonic() >= deadline:
                raise Interrupted("cancelled" if cancelled.is_set() else "timeout")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        reader.join()
    return proc.returncode, bytes(retained), truncated


def read_junit(content, redact):
    text = content.decode("utf-8-sig")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("unsupported XML declaration")
    root = ET.fromstring(text)
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("expected a JUnit report")
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    safe = ET.Element("testsuite")
    for case in root.iter("testcase"):
        copy = ET.SubElement(safe, "testcase", {k: redact(v) for k, v in case.attrib.items() if k in {"name", "classname", "time"}})
        for tag, outcome in (("error", "errors"), ("failure", "failed"), ("skipped", "skipped")):
            marker = case.find(tag)
            if marker is not None:
                counts[outcome] += 1
                ET.SubElement(copy, tag, message=redact(marker.get("message", "")))
                break
        else:
            counts["passed"] += 1
    declared = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    for attribute, key in (("failures", "failed"), ("errors", "errors"), ("skipped", "skipped"), ("tests", None)):
        if declared and all(attribute in suite.attrib for suite in declared):
            expected = counts[key] if key else sum(counts.values())
            if sum(int(suite.attrib[attribute]) for suite in declared) != expected:
                raise ValueError("JUnit aggregate disagrees with case records")
    safe.attrib.update(tests=str(sum(counts.values())), failures=str(counts["failed"]),
                       errors=str(counts["errors"]), skipped=str(counts["skipped"]))
    return counts, ET.tostring(safe, encoding="utf-8", xml_declaration=True)


class DockerRunner:
    def __init__(self, image_digest, report_root, *, secrets=(), docker="docker"):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))["runner"]
        self.profiles = {
            suite: RunnerProfile(suite, image_digest, "/usr/local/bin/python", ("-I", "-B", BOOTSTRAP, suite),
                                 "/workspace", policy["network"]["test_egress"], **policy["resource_limits"])
            for suite in SUITES
        }
        self.report_root = Path(report_root)
        self.secrets = tuple(secret for secret in secrets if secret)
        self.docker = docker

    def redact(self, value):
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", value)
        return re.sub(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", value)

    def run(self, repo, commit, suite_id, *, cancel=None):
        if suite_id not in self.profiles:
            raise ValueError("tool_denied: suite is not on the allowlist")
        profile = self.profiles[suite_id]
        cancelled = cancel if cancel is not None else threading.Event()
        key = uuid.uuid4().hex
        name = "ktpm-suite-" + key
        start = time.monotonic()
        deadline = start + profile.timeout_seconds
        limits = profile.output_limit_bytes
        folder = self.report_root / key
        folder.mkdir(parents=True)
        log = ""
        report = dict(report_id=key, suite_id=suite_id, commit=commit, image_digest=profile.image_digest,
                      status="infrastructure_error", exit_code=None, passed=0, failed=0, errors=0, skipped=0,
                      duration_seconds=0, log_uri=key + "/runner.log", junit_uri=None, log_truncated=False)

        def docker(*args):
            return bounded_command([self.docker, *args], deadline, cancelled, limits)

        container_requested = False
        with tempfile.TemporaryDirectory() as temporary:
            try:
                stage = Path(temporary, "snapshot")
                snapshot(repo, commit, stage, [v.encode() for v in self.secrets])
                if "," in str(stage):
                    raise ValueError("Docker mount path contains a comma")
                endpoint = os.environ.get("DOCKER_HOST")
                if not endpoint:
                    rc, data, _ = docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
                    if rc:
                        raise RuntimeError(data.decode(errors="replace"))
                    endpoint = data.decode().strip()
                if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
                    raise ValueError("a local Docker socket or named pipe is required")
                container_requested = True
                rc, data, _ = docker("run", "-d", "--pull=never", "--name", name, "--log-driver", "none",
                                     "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777",
                                     "--tmpfs", "/workspace:rw,nosuid,nodev,mode=1777",
                                     "--mount", f"type=bind,source={stage},target=/input,readonly",
                                     *profile.docker_options(), profile.image_digest,
                                     "-I", "-S", "-c", "import signal; signal.pause()")
                if rc:
                    raise RuntimeError(data.decode(errors="replace"))
                rc, data, truncated = docker("exec", name, profile.executable, *profile.argv)
                report.update(exit_code=rc, log_truncated=truncated)
                log = data.decode(errors="replace")
                rc, data, truncated = docker("exec", name, profile.executable, "-I", "-B", BOOTSTRAP, "report", str(limits))
                if rc or truncated:
                    raise ValueError("JUnit report unavailable or exceeds capture limit")
                counts, xml = read_junit(data, self.redact)
                report.update(counts)
                (folder / "junit.xml").write_bytes(xml)
                report["junit_uri"] = key + "/junit.xml"
                report["status"] = "passed" if (report["exit_code"] == 0 and counts["passed"] > 0
                                                and not any(counts[k] for k in ("failed", "errors", "skipped"))) else "failed"
            except Interrupted as exc:
                report["status"] = str(exc)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile, ET.ParseError) as exc:
                log += "\n" + str(exc)
            finally:
                if container_requested:
                    try:
                        removed = subprocess.run([self.docker, "rm", "-f", "-v", name], capture_output=True, timeout=15)
                        if removed.returncode and b"no such container" not in removed.stderr.lower():
                            report["status"] = "cleanup_error"
                            log += "\nDocker could not verify container cleanup"
                    except (OSError, subprocess.SubprocessError):
                        report["status"] = "cleanup_error"
                        log += "\nDocker cleanup unavailable"

        # A truncated prefix can split a secret. Only keep complete lines before redaction.
        if report["log_truncated"]:
            log = log.rpartition("\n")[0]
        clean_log = self.redact(log).encode("utf-8")
        report["log_truncated"] |= len(clean_log) > limits
        (folder / "runner.log").write_bytes(clean_log[:limits])
        report["duration_seconds"] = round(time.monotonic() - start, 6)
        (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
