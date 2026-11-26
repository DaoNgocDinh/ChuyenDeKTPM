"""Host-owned Docker profile. The MCP interface accepts a suite ID only."""

import math
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


def _positive_limit(name, value):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class RunnerProfile:
    suite_id: str
    image_digest: str
    executable: str
    argv: tuple[str, ...]
    cwd: str
    network_policy: str
    timeout_seconds: int
    cpu_limit: float
    memory_bytes: int
    pids_limit: int
    output_limit_bytes: int

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", self.suite_id):
            raise ValueError("invalid suite ID")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.:/_-]*@sha256:[0-9a-f]{64}", self.image_digest):
            raise ValueError("the image must be pinned by SHA256 digest")
        executable = PurePosixPath(self.executable)
        if not executable.is_absolute() or ".." in executable.parts or "\x00" in self.executable:
            raise ValueError("the host profile must name an absolute executable")
        cwd = PurePosixPath(self.cwd)
        if not cwd.is_relative_to("/workspace") or ".." in cwd.parts or "\x00" in self.cwd:
            raise ValueError("cwd must point inside /workspace")
        if type(self.argv) is not tuple or any(type(arg) is not str or "\x00" in arg for arg in self.argv):
            raise ValueError("argv must contain fixed strings")
        if self.network_policy != "docker_bridge_outbound_internet":
            raise ValueError("only the approved outbound Docker bridge is supported")
        if type(self.cpu_limit) not in (int, float) or not math.isfinite(self.cpu_limit) or self.cpu_limit <= 0:
            raise ValueError("cpu_limit must be a positive finite number")
        for field in ("timeout_seconds", "memory_bytes", "pids_limit", "output_limit_bytes"):
            _positive_limit(field, getattr(self, field))

    def docker_options(self):
        """Arguments before IMAGE. The runner supplies verified mounts and supervises limits."""
        return (
            "--network", "bridge", "--read-only", "--user", "65534:65534",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--cpus", str(self.cpu_limit), "--memory", str(self.memory_bytes),
            "--pids-limit", str(self.pids_limit), "--workdir", self.cwd,
            "--entrypoint", self.executable,
        )
