"""Host-owned role mapping; a frozen run never rereads prompts to assemble context."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from backend.skills import load_skill, skill_manifest


ROLE_SKILLS = {
    "Orchestrator": "workflow-coordination",
    "Requirement": "requirements-analysis",
    "Architecture": "architecture-design",
    "Planning": "task-planning",
    "Dev": "implementation",
    "Tester": "testing-review",
}


class RunSkills:
    def __init__(self, root: Path, *, enabled: bool):
        self._enabled = enabled
        self._skills = {}
        self._manifest = {}
        for role, name in ROLE_SKILLS.items():
            folder = root / name
            stamp = skill_manifest(folder, enabled=enabled)
            skill = load_skill(folder)
            if skill.sha256 != stamp["sha256"]:
                raise ValueError("Skill changed while loading")
            self._skills[role] = skill
            self._manifest[role] = stamp
        if len({item["commit"] for item in self._manifest.values()}) != 1:
            raise ValueError("Skills must originate from one system commit")

    def context(self, role: str, *resources: str) -> str:
        return self._skills[role].context(enabled=self._enabled, resources=resources)

    def bind(self, manifest_path: Path) -> None:
        """Persist the first role manifest, or verify it on worker restart."""
        data = json.dumps(self._manifest, sort_keys=True, indent=2).encode() + b"\n"
        with tempfile.NamedTemporaryFile(dir=manifest_path.parent, delete=False) as f:
            tmp = Path(f.name)
            try:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            except BaseException:
                f.close()
                tmp.unlink(missing_ok=True)
                raise
        try:
            try:
                os.link(tmp, manifest_path)
            except FileExistsError:
                if manifest_path.read_bytes() != data:
                    raise ValueError("Run is bound to a different skill manifest") from None
        finally:
            tmp.unlink(missing_ok=True)
