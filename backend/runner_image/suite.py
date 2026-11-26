"""Trusted image entry point. Run inside Docker only."""

import os
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


WORKSPACE = Path("/workspace")
JUNIT = WORKSPACE / "runner-junit.xml"


def build_project():
    suite = ET.Element("testsuite", name="build")
    checks = [
        ("backend.compile", any(Path("app").rglob("*.py")), [[sys.executable, "-m", "compileall", "-q", "app"]], WORKSPACE),
        ("frontend.build", Path("app/frontend/package-lock.json").is_file(),
         [["npm", "ci", "--no-audit", "--no-fund"], ["npm", "run", "build"]], WORKSPACE / "app/frontend"),
    ]
    failed = 0
    for name, available, commands, cwd in checks:
        case = ET.SubElement(suite, "testcase", name=name)
        try:
            if not available:
                raise FileNotFoundError(f"missing source or lockfile for {name}")
            for args in commands:
                subprocess.run(args, cwd=cwd, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            failed += 1
            ET.SubElement(case, "failure", message=str(exc))
    ET.ElementTree(suite).write(JUNIT, encoding="utf-8", xml_declaration=True)
    return int(bool(failed))


def emit_report(max_bytes):
    # Ignore symlinks, FIFOs and devices. Never stream an unbounded file to the host.
    fd = os.open(JUNIT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
            raise ValueError("invalid JUnit file or size")
        data = source.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("JUnit file exceeds size limit")
        sys.stdout.buffer.write(data)


def main():
    suite_id = sys.argv[1]
    if suite_id == "report":
        emit_report(int(sys.argv[2]))
        return 0
    if suite_id not in {"smoke", "development", "build"}:
        raise ValueError("unrecognized suite")
    os.environ.update(HOME="/tmp", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(WORKSPACE))
    for name in ("app", "tests_dev"):
        source = Path("/input") / name
        if source.is_dir():
            shutil.copytree(source, WORKSPACE / name)
    os.chdir(WORKSPACE)
    if suite_id == "build":
        return build_project()
    selection = "tests_dev/test_smoke.py" if suite_id == "smoke" else "tests_dev"
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                           "--junitxml=" + str(JUNIT), selection], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
