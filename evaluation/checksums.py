"""Deterministic SHA-256 checksum locking for immutable E01 evaluation assets."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EVAL_DIR / "checksums.json"

LOCKED_RELATIVE_PATHS = (
    "A1.json",
    "A2.json",
    "A3.json",
    "adapters.py",
    "checksums.py",
    "reporting.py",
    "suites.py",
    "ui_driver.py",
)


def normalized_sha256(path: Path) -> str:
    """Hash UTF-8 text with LF normalization so Windows and Linux Docker match."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def compute_manifest(eval_dir: Path = EVAL_DIR) -> dict[str, object]:
    files: dict[str, str] = {}
    for rel in LOCKED_RELATIVE_PATHS:
        target = eval_dir / rel
        if not target.is_file():
            raise FileNotFoundError(f"Missing locked evaluation file: {rel}")
        files[rel] = normalized_sha256(target)
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "1",
        "normalization": "lf_utf8",
        "files": files,
        "bundle_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def write_manifest(eval_dir: Path = EVAL_DIR, out_path: Path | None = None) -> dict[str, object]:
    manifest = compute_manifest(eval_dir)
    target = out_path or (eval_dir / "checksums.json")
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_manifest(
    eval_dir: Path = EVAL_DIR,
    manifest_path: Path | None = None,
) -> tuple[bool, list[str]]:
    path = manifest_path or (eval_dir / "checksums.json")
    if not path.is_file():
        return False, [f"Missing checksum manifest: {path.name}"]
    recorded = json.loads(path.read_text(encoding="utf-8"))
    actual = compute_manifest(eval_dir)
    mismatches: list[str] = []
    if recorded.get("files") != actual["files"]:
        rec_files = recorded.get("files", {})
        for rel in LOCKED_RELATIVE_PATHS:
            if rec_files.get(rel) != actual["files"][rel]:
                mismatches.append(f"{rel}: expected {rec_files.get(rel)}, got {actual['files'][rel]}")
    if recorded.get("bundle_sha256") != actual["bundle_sha256"]:
        mismatches.append(
            f"bundle_sha256: expected {recorded.get('bundle_sha256')}, got {actual['bundle_sha256']}"
        )
    return not mismatches, mismatches


def main(argv: list[str]) -> int:
    if "--write" in argv:
        manifest = write_manifest()
        print(f"Wrote {MANIFEST_PATH.name} bundle_sha256={manifest['bundle_sha256']}")
        return 0
    ok, mismatches = verify_manifest()
    if not ok:
        for item in mismatches:
            print(f"MISMATCH: {item}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"OK bundle_sha256={manifest['bundle_sha256']} files={len(manifest['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
