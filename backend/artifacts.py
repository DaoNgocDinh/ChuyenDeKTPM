"""Host-owned, versioned content store for one project/run at a time."""

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from .contracts import (
    Architecture, ArtifactRef, BugReport, DevResult, Plan, Requirements, TestReport,
)
from .storage import Database, StorageConflict, new_id


STRUCTURED = {"requirements": Requirements, "architecture": Architecture, "plan": Plan,
              "dev_result": DevResult, "test_report": TestReport, "bug_report": BugReport}
TEXT_KINDS = {"requirements_markdown", "document", "log", "runner_output", "patch"}
SEGMENT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}")


def publish_file(source, target):
    if os.name == "nt":
        # Windows rename fails on an existing destination and needs no hard-link privilege.
        os.rename(source, target)
    else:
        os.link(source, target)


def check_file_type(path, *, directory):
    info = path.lstat()
    reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    allowed = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if reparse or not allowed:
        raise ValueError("Artifact store contains an unexpected file type")


def serialize(kind, content):
    if kind in TEXT_KINDS:
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Expected nonempty UTF-8 text")
        return content.encode("utf-8"), []
    schema = STRUCTURED.get(kind)
    if schema is None:
        raise ValueError("Unregistered artifact type")
    if isinstance(content, (str, bytes)):
        payload = schema.model_validate_json(content)
    else:
        payload = schema.model_validate(content.model_dump() if isinstance(content, schema) else content)
    refs = [getattr(payload, field) for field in type(payload).model_fields
            if isinstance(getattr(payload, field), ArtifactRef)]
    data = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return data, refs


class ArtifactStore:
    def __init__(self, root, database: Database):
        self.root = Path(root).absolute()
        self.database = database

    def _directory(self, project_id, run_id, *, create):
        for part in (project_id, run_id):
            if not isinstance(part, str) or not SEGMENT.fullmatch(part):
                raise ValueError("Invalid workspace identifier")
        path = self.root
        if create:
            path.mkdir(parents=True, exist_ok=True)
        check_file_type(path, directory=True)
        for part in (project_id, run_id, "artifacts"):
            path = path / part
            if create:
                path.mkdir(exist_ok=True)
            check_file_type(path, directory=True)
        return path

    @staticmethod
    def _publish(directory, filename, data):
        # A hard link publishes a complete blob without replacing an existing destination.
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".pending-", delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            except BaseException:
                temp.close()
                temp_path.unlink(missing_ok=True)
                raise
        target = directory / filename
        try:
            try:
                publish_file(temp_path, target)
            except FileExistsError:
                check_file_type(target, directory=False)
                if target.read_bytes() != data:
                    raise StorageConflict("Existing blob differs from its digest")
        finally:
            temp_path.unlink(missing_ok=True)

    def put(self, project_id, run_id, lease, kind, content, *, created_by,
            expected_previous_version=0, schema_version="1", parent_refs=()):
        if schema_version != "1" or type(expected_previous_version) is not int or expected_previous_version < 0:
            raise ValueError("Unsupported schema or predecessor version")
        if not isinstance(created_by, str) or not created_by.strip():
            raise ValueError("Missing artifact author")
        data, embedded = serialize(kind, content)
        parents = []
        for raw in [*parent_refs, *embedded]:
            ref = ArtifactRef.model_validate(raw)
            if ref.run_id != run_id:
                raise ValueError("Parent belongs to a different run")
            if ref not in parents:
                parents.append(ref)
        digest = hashlib.sha256(data).hexdigest()
        filename = digest + ".blob"

        def verify_inputs(view):
            if view.latest_version(kind) != expected_previous_version:
                raise StorageConflict("Artifact predecessor has changed")
            for ref in parents:
                row = view.artifact(ref.artifact_id, ref.version)
                if row["sha256"] != ref.sha256:
                    raise StorageConflict("Parent hash does not match stored version")

        with self.database.transaction() as repo:
            verify_inputs(repo.worker_run(project_id, run_id, lease))
        directory = self._directory(project_id, run_id, create=True)
        self._publish(directory, filename, data)
        version = expected_previous_version + 1
        artifact_id = new_id()
        # Read/write scope again after file I/O. Concurrent publishers cannot win the same version.
        with self.database.transaction(write=True) as repo:
            writer = repo.worker_run(project_id, run_id, lease)
            verify_inputs(writer)
            writer.add_artifact(artifact_id, kind, version, schema_version, "artifacts/" + filename,
                                digest, created_by, [ref.model_dump() for ref in parents])
        return ArtifactRef(run_id=run_id, artifact_id=artifact_id, version=version, sha256=digest)

    def read(self, project_id, run_id, artifact_id, version, sha256=None):
        with self.database.transaction() as repo:
            row = repo.for_run(project_id, run_id).artifact(artifact_id, version)
        digest = row["sha256"]
        if sha256 is not None and sha256 != digest:
            raise StorageConflict("Requested digest does not match stored reference")
        filename = digest + ".blob"
        if not re.fullmatch("[a-f0-9]{64}", digest) or row["uri"] != "artifacts/" + filename:
            raise StorageConflict("Invalid stored artifact URI")
        blob = self._directory(project_id, run_id, create=False) / filename
        check_file_type(blob, directory=False)
        data = blob.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise StorageConflict("Artifact content hash mismatch")
        return data
