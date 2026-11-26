"""Tests for I25 support secret-filtered ZIP exporter on real SQLite + ArtifactStore + Git."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.artifacts import ArtifactStore
from backend.contracts import RequirementItem, Requirements
from backend.exporter import (
    ExportPathError,
    SecretLeakError,
    build_export_zip,
    verify_export_zip,
)
from backend.storage import Database
from backend.workspace import Edit, Workspace


class ExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = Database(self.root / "platform.sqlite")
        self.db.migrate()
        self.ws_root = self.root / "workspaces"
        self.store = ArtifactStore(self.ws_root, self.db)
        with self.db.transaction(write=True) as repo:
            self.project_id = repo.create_project("A1", "brief/A1")
            self.run_id = repo.create_run(self.project_id, "exp-1", {"model": "test"}, {})
            repo._db.execute(
                "UPDATE runs SET status='running', worker_lease='lease-1', "
                "lease_expires_at=datetime('now', '+5 minutes') WHERE id=?",
                (self.run_id,),
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_builds_and_verifies_clean_zip_excluding_untracked_env(self) -> None:
        ws = Workspace(self.ws_root, self.project_id, self.run_id)
        base = ws.initialize()
        receipt = ws.apply(
            "T1",
            base,
            [
                Edit("app/main.py", None, "print('hello A1')\n"),
                Edit("app/README.md", None, "# A1 App\nRun python app/main.py\n"),
            ],
        )
        # Drop an untracked .env file inside workspace/app that must NEVER enter the ZIP
        (ws.path / "app" / ".env").write_text("API_KEY=CANARY_UNTRACKED_999\n", encoding="utf-8")

        req_ref = self.store.put(
            self.project_id,
            self.run_id,
            "lease-1",
            "requirements",
            Requirements(
                actors=["User"],
                functional=[RequirementItem(id="FR-1", description="CRUD", acceptance=["ok"])],
                nonfunctional=[],
                assumptions=[],
                questions=[],
            ),
            created_by="Requirement",
        )
        with self.db.transaction(write=True) as repo:
            repo.record_approval(
                self.project_id, self.run_id, req_ref.artifact_id, req_ref.version, req_ref.sha256, "approve", "ok"
            )
            w = repo.worker_run(self.project_id, self.run_id, "lease-1")
            w.add_report(None, receipt["output_commit"], "development", "reports/r1.json", 0, 5, 0, 0, 0, 120)

        out_zip = self.root / "export.zip"
        result = build_export_zip(
            self.db,
            self.store,
            self.ws_root,
            self.project_id,
            self.run_id,
            out_zip,
            secrets=("CANARY_UNTRACKED_999",),
        )
        self.assertEqual(result.code_commit, receipt["output_commit"])
        manifest = verify_export_zip(out_zip, forbidden_canaries=("CANARY_UNTRACKED_999",))
        self.assertIn("app/main.py", manifest["files"])
        self.assertIn("app/README.md", manifest["files"])
        self.assertNotIn("app/.env", manifest["files"])
        self.assertTrue(manifest["artifacts"][0]["approved"])

    def test_blocks_canary_secret_leaked_into_tracked_code_or_artifact(self) -> None:
        canary = "CANARY_SECRET_TOKEN_XYZ_987654"
        ws = Workspace(self.ws_root, self.project_id, self.run_id)
        base = ws.initialize()
        ws.apply("T1", base, [Edit("app/config.py", None, f"KEY = '{canary}'\n")])

        with self.assertRaises(SecretLeakError):
            build_export_zip(
                self.db,
                self.store,
                self.ws_root,
                self.project_id,
                self.run_id,
                self.root / "leaked.zip",
                secrets=(canary,),
            )

    def test_verify_rejects_zip_slip_path_traversal(self) -> None:
        bad_zip = self.root / "bad.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("../escape.txt", "oops")
            zf.writestr("EXPORT_MANIFEST.json", '{"files":{}}')
        with self.assertRaises(ExportPathError):
            verify_export_zip(bad_zip)


if __name__ == "__main__":
    unittest.main()
