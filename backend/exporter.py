"""SUPPORT MODULE (draft prior to I21/I22/I15) for I25 secret-filtered ZIP export.

Packages tracked application code at a pinned Git commit, run-scoped artifacts
verified by SHA-256, test report summaries, and EXPORT_MANIFEST.json while
enforcing path-traversal protection and canary/secret leak prevention (FR10, NFR06).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.artifacts import ArtifactStore
from backend.storage import Database
from backend.workspace import Workspace


FORBIDDEN_SEGMENTS = frozenset(
    {
        ".git",
        ".env",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".venv",
        ".mypy_cache",
        ".ruff_cache",
        "credentials",
        "credentials.json",
        "secrets",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".aws",
        ".ssh",
        ".docker",
        ".kube",
    }
)
FORBIDDEN_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".kdbx", ".pyc", ".pyo")

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{24,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class SecretLeakError(ValueError):
    """Raised when a secret or canary string would leak into the exported ZIP."""


class ExportPathError(ValueError):
    """Raised when an export entry path is unsafe or attempts path traversal."""


@dataclass(frozen=True)
class ExportResult:
    zip_path: Path
    project_id: str
    run_id: str
    code_commit: str
    file_count: int
    manifest_sha256: str


def is_forbidden_path(rel_path: str) -> bool:
    if not rel_path or "\\" in rel_path or ":" in rel_path or rel_path.startswith("/"):
        return True
    parts = rel_path.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        return True
    for part in parts:
        low = part.casefold()
        if low in FORBIDDEN_SEGMENTS or low.startswith(".env.") or low.endswith(FORBIDDEN_SUFFIXES):
            return True
    return False


def assert_safe_zip_member(member_name: str) -> str:
    if not member_name or "\\" in member_name or ":" in member_name or member_name.startswith("/"):
        raise ExportPathError(f"Unsafe ZIP member path: {member_name!r}")
    normalized = posixpath.normpath(member_name)
    if normalized != member_name or normalized in {".", ".."} or normalized.startswith("../"):
        raise ExportPathError(f"ZIP path traversal detected: {member_name!r}")
    if ".." in member_name.split("/"):
        raise ExportPathError(f"ZIP path traversal detected: {member_name!r}")
    return member_name


def scan_for_secrets(data: bytes, *, source_name: str, secrets: Iterable[str] = ()) -> None:
    text = data.decode("utf-8", errors="ignore")
    for secret in secrets:
        if secret and secret in text:
            raise SecretLeakError(f"Canary/secret detected in export entry {source_name!r}")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise SecretLeakError(f"Credential pattern detected in export entry {source_name!r}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _list_tracked_app_files(workspace: Workspace, commit: str) -> list[str]:
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise ValueError("Expected full Git commit hash for export")
    output = workspace.git("ls-tree", "-r", commit, "--", "app")
    tracked: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        mode = meta.split()[0]
        if mode == "120000":
            raise ExportPathError(f"Symlink forbidden in exported commit: {path!r}")
        if is_forbidden_path(path):
            continue
        tracked.append(path)
    return sorted(tracked)


def build_export_zip(
    database: Database,
    artifact_store: ArtifactStore,
    workspace_root: Path,
    project_id: str,
    run_id: str,
    output_zip: Path,
    *,
    commit: str | None = None,
    secrets: Iterable[str] = (),
) -> ExportResult:
    """Build a verified, secret-filtered export ZIP for one project/run."""
    secret_tuple = tuple(s for s in secrets if s)
    workspace = Workspace(workspace_root, project_id, run_id)
    target_commit = commit or workspace.head()

    with database.transaction() as repo:
        run_row = repo.get_run(project_id, run_id)
        reader = repo.for_run(project_id, run_id)
        artifacts = sorted(reader.records("artifacts"), key=lambda a: (a["type"], a["version"], a["id"]))
        approvals = reader.records("approvals")
        reports = sorted(reader.records("test_reports"), key=lambda r: r["id"])
        traces = reader.records("trace_links")

    approved_triples = {
        (a["artifact_id"], a["artifact_version"], a["artifact_sha256"])
        for a in approvals
        if a["decision"] == "approve"
    }

    entries: dict[str, bytes] = {}

    # 1. Tracked application code at exact commit (never reads untracked .env/cache)
    for rel_path in _list_tracked_app_files(workspace, target_commit):
        raw = workspace.git("show", f"{target_commit}:{rel_path}").encode("utf-8")
        scan_for_secrets(raw, source_name=rel_path, secrets=secret_tuple)
        entries[assert_safe_zip_member(rel_path)] = raw

    # 2. Run-scoped artifacts verified against SHA-256
    exported_artifacts: list[dict[str, object]] = []
    for art in artifacts:
        blob = artifact_store.read(project_id, run_id, art["id"], art["version"], art["sha256"])
        ext = "json" if art["type"] in {
            "requirements", "architecture", "plan", "dev_result", "test_report", "bug_report",
        } else "txt"
        member = assert_safe_zip_member(f"artifacts/{art['type']}_v{art['version']}_{art['id']}.{ext}")
        scan_for_secrets(blob, source_name=member, secrets=secret_tuple)
        entries[member] = blob
        exported_artifacts.append(
            {
                "artifact_id": art["id"],
                "type": art["type"],
                "version": art["version"],
                "sha256": art["sha256"],
                "approved": (art["id"], art["version"], art["sha256"]) in approved_triples,
                "zip_path": member,
            }
        )

    # 3. Test reports and trace links metadata
    reports_bytes = (
        json.dumps({"test_reports": reports, "trace_links": traces}, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    scan_for_secrets(reports_bytes, source_name="reports/test_reports.json", secrets=secret_tuple)
    entries[assert_safe_zip_member("reports/test_reports.json")] = reports_bytes

    # 4. Ensure README exists at archive root
    if "app/README.md" not in entries and "README.md" not in entries:
        readme_text = (
            f"# Gói bàn giao run {run_id}\n\n"
            f"- Project ID: `{project_id}`\n"
            f"- Run ID: `{run_id}`\n"
            f"- Trạng thái run lúc xuất: `{run_row['status']}`\n"
            f"- Commit mã ứng dụng: `{target_commit}`\n\n"
            "Đối chiếu hash từng tệp bằng `EXPORT_MANIFEST.json`.\n"
        ).encode("utf-8")
        entries[assert_safe_zip_member("README.md")] = readme_text

    # 5. Deterministic EXPORT_MANIFEST.json
    file_hashes = {name: _sha256_bytes(data) for name, data in sorted(entries.items())}
    manifest_payload = {
        "schema_version": "1",
        "project_id": project_id,
        "run_id": run_id,
        "run_status": run_row["status"],
        "code_commit": target_commit,
        "artifacts": exported_artifacts,
        "test_report_ids": [r["id"] for r in reports],
        "files": file_hashes,
    }
    manifest_bytes = (json.dumps(manifest_payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    scan_for_secrets(manifest_bytes, source_name="EXPORT_MANIFEST.json", secrets=secret_tuple)
    manifest_sha = _sha256_bytes(manifest_bytes)

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(entries.items()):
            zf.writestr(assert_safe_zip_member(name), data)
        zf.writestr("EXPORT_MANIFEST.json", manifest_bytes)

    return ExportResult(
        zip_path=output_zip,
        project_id=project_id,
        run_id=run_id,
        code_commit=target_commit,
        file_count=len(entries) + 1,
        manifest_sha256=manifest_sha,
    )


def verify_export_zip(zip_path: Path, *, forbidden_canaries: Iterable[str] = ()) -> dict[str, object]:
    """Validate an export ZIP against traversal, manifest hash mismatches, and secret leaks."""
    canaries = tuple(c for c in forbidden_canaries if c)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        for name in names:
            assert_safe_zip_member(name)
            if name != "EXPORT_MANIFEST.json" and is_forbidden_path(name):
                raise ExportPathError(f"Forbidden file inside ZIP: {name!r}")
        if "EXPORT_MANIFEST.json" not in names:
            raise ValueError("Missing EXPORT_MANIFEST.json")
        manifest = json.loads(zf.read("EXPORT_MANIFEST.json").decode("utf-8"))
        recorded_files: dict[str, str] = manifest["files"]
        actual_non_manifest = sorted(n for n in names if n != "EXPORT_MANIFEST.json")
        if actual_non_manifest != sorted(recorded_files.keys()):
            raise ValueError("ZIP entries do not match EXPORT_MANIFEST.json file list")
        for name in actual_non_manifest:
            raw = zf.read(name)
            scan_for_secrets(raw, source_name=name, secrets=canaries)
            if _sha256_bytes(raw) != recorded_files[name]:
                raise ValueError(f"Hash mismatch for ZIP member {name!r}")
        return manifest
