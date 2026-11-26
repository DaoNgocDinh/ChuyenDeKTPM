import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.artifacts import ArtifactStore
from backend.storage import Database, StorageConflict


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspaces"
        self.db = Database(Path(self.tmp.name) / "metadata.db")
        self.db.migrate()
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1", "brief")
            self.other = repo.create_project("A2", "brief")
            self.run = repo.create_run(self.project, "first", {}, {})
            self.second = repo.create_run(self.project, "second", {}, {})
        with closing(sqlite3.connect(self.db.path)) as seed, seed:
            seed.execute("UPDATE runs SET status='running',worker_lease='worker',"
                         "lease_expires_at=datetime('now','+5 minutes') WHERE id=?", (self.run,))
        self.store = ArtifactStore(self.root, self.db)
        self.req = {"actors": ["Owner"], "functional": [
            {"id": "FR1", "description": "Add task", "acceptance": ["Title saved"]}],
            "nonfunctional": [], "assumptions": [], "questions": []}

    def put(self, kind, content, **options):
        return self.store.put(self.project, self.run, "worker", kind, content, created_by="Requirement", **options)

    def read(self, ref):
        return self.store.read(self.project, self.run, ref.artifact_id, ref.version, ref.sha256)

    def test_versions_remain_readable_after_approval_and_restart(self):
        first = self.put("requirements", self.req)
        with self.db.transaction(write=True) as repo:
            repo.record_approval(self.project, self.run, first.artifact_id, 1, first.sha256, "approve")
        second = self.put("requirements", {**self.req, "questions": ["What deadline?"]},
                          expected_previous_version=1, parent_refs=[first])
        self.store = ArtifactStore(self.root, Database(self.db.path))
        self.assertEqual(json.loads(self.read(first)), self.req)
        self.assertEqual(hashlib.sha256(self.read(second)).hexdigest(), second.sha256)
        with self.db.transaction() as repo:
            view = repo.for_run(self.project, self.run)
            self.assertEqual(view.latest_version("requirements"), 2)
            self.assertEqual(json.loads(view.artifact(second.artifact_id, 2)["parent_refs_json"]), [first.model_dump()])
            self.assertEqual(view.records("approvals")[0]["artifact_id"], first.artifact_id)

    def test_wrong_scope_version_hash_or_path_is_denied(self):
        ref = self.put("document", "brief")
        for project, run, artifact_id, version in [
            (self.other, self.run, ref.artifact_id, 1), (self.project, self.second, ref.artifact_id, 1),
            (self.project, self.run, ref.artifact_id, 2), (self.project, self.run, str(self.db.path), 1),
        ]:
            with self.subTest(project=project, run=run), self.assertRaises(KeyError):
                self.store.read(project, run, artifact_id, version)
        with self.assertRaises(StorageConflict):
            self.store.read(self.project, self.run, ref.artifact_id, 1, "b" * 64)

    def test_schema_and_embedded_parent_validation(self):
        for kind, content in (("requirements", {}), ("plan", b"not json"), ("document", ""), ("unknown", {})):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.put(kind, content)
        ref = self.put("requirements", self.req)
        arch = {"requirements": ref.model_dump(), "adr": ["SQLite"], "components": {"api": "API"},
                "entities": {"Task": "task"}, "api_contract": {"GET /": "list"}, "frontend": "web",
                "test_strategy": "unit", "fr_components": {"FR1": ["api"]}}
        result = self.put("architecture", arch)
        with self.db.transaction() as repo:
            row = repo.for_run(self.project, self.run).artifact(result.artifact_id, 1)
            self.assertEqual(json.loads(row["parent_refs_json"]), [ref.model_dump()])
        for invalid in [{**ref.model_dump(), "run_id": self.second}, {**ref.model_dump(), "sha256": "b" * 64}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.put("architecture", {**arch, "requirements": invalid}, expected_previous_version=1)

    def test_conflicting_writers_and_unpublished_files(self):
        def create(text):
            try:
                return self.put("log", text)
            except StorageConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            refs = list(pool.map(create, ["one", "two"]))
        self.assertEqual(sum(r is not None for r in refs), 1)
        winner = next(r for r in refs if r)
        with self.assertRaises(StorageConflict):
            self.put("log", "retry")
        self.assertIn(self.read(winner), [b"one", b"two"])
        with patch("backend.artifacts.os.link", side_effect=OSError("disk unavailable")), self.assertRaises(OSError):
            self.put("document", "not published")
        with self.db.transaction() as repo:
            self.assertEqual(repo.for_run(self.project, self.run).latest_version("document"), 0)
        self.assertFalse(list(self.root.rglob(".pending-*")))

    def test_detects_corrupted_blob_and_refuses_to_replace_it(self):
        ref = self.put("log", "original")
        blob = self.root / self.project / self.run / "artifacts" / (ref.sha256 + ".blob")
        blob.write_bytes(b"changed")
        with self.assertRaises(StorageConflict):
            self.read(ref)
        with self.assertRaises(StorageConflict):
            self.put("document", "original")
        self.assertEqual(blob.read_bytes(), b"changed")
