"""Load a host-selected skill and record the exact files behind its instructions."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    version: str
    sha256: str
    instructions: str
    resources: Mapping[str, bytes]

    def context(self, *, enabled: bool, resources: tuple[str, ...] = ()) -> str:
        if not enabled:
            return ""
        excerpts = [self.instructions]
        for name in resources:
            if name not in self.resources:
                raise ValueError(f"Unknown skill resource: {name}")
            excerpts.append(self.resources[name].decode("utf-8"))
        return "\n\n".join(excerpts)


def _files(folder: Path):
    for path in sorted(folder.iterdir()):
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Linked skill path: {path.name}")
        if path.is_dir():
            yield from _files(path)
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"Unsupported skill file: {path.name}")


def load_skill(folder: Path) -> Skill:
    if folder.is_symlink() or getattr(folder.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("Linked skill directory")
    files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in _files(folder)}
    lines = files["SKILL.md"].decode("utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = lines.index("---", 1)
    meta = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(meta, dict) or not isinstance(meta.get("metadata"), dict):
        raise ValueError("Missing skill metadata")
    name = meta.get("name")
    if name != folder.name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("Invalid skill name")
    version = meta["metadata"].get("version")
    description = meta.get("description")
    body = "\n".join(lines[end + 1:]).strip()
    if not isinstance(version, str) or not version.strip():
        raise ValueError("A version string is required")
    if not isinstance(description, str) or not (1 <= len(description.strip()) <= 1024) or not body:
        raise ValueError("Description and instructions are required")
    hashes = [(name, hashlib.sha256(data).hexdigest()) for name, data in sorted(files.items())]
    digest = hashlib.sha256(json.dumps(hashes, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    del files["SKILL.md"]
    return Skill(name, description, version, digest, body, files)


def skill_manifest(folder: Path, *, enabled: bool) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(folder), *args], text=True).strip()

    commit = git("rev-parse", "HEAD")
    if git("status", "--porcelain", "--untracked-files=all", "--ignored", "--", "."):
        raise ValueError("Commit skill changes before recording a run")
    git("ls-files", "--error-unmatch", "--", "SKILL.md")
    skill = load_skill(folder)
    return {"name": skill.name, "version": skill.version, "sha256": skill.sha256,
            "commit": commit, "enabled": enabled}
