import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.workspace import Edit, PendingRecovery, Workspace, content_hash


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(self.tmp.name, "p", "run1")
        self.base = self.ws.initialize()

    def test_versioned_patch_delete_and_run_isolation(self):
        new = self.ws.apply("t1", self.base, [Edit("app/a.py", None, "one\n")])
        self.assertEqual("one\n", self.ws.read("app/a.py").decode())
        self.assertIn("+one", new["diff"])
        other = Workspace(self.tmp.name, "p", "run2")
        other.initialize()
        with self.assertRaises(FileNotFoundError):
            other.read("app/a.py")
        removed = self.ws.apply("t2", new["output_commit"], [Edit("app/a.py", content_hash(b"one\n"), None)])
        self.assertIn("-one", removed["diff"])
        self.assertIn("+one", self.ws.diff(self.base, new["output_commit"]))
        self.assertEqual("", self.ws.status())

    def test_preconditions_prevent_partial_write(self):
        for invalid in ("app/../docs/x", "app/.git/config", "app/C:/x", "artifacts/x", "app/CON"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.ws.read(invalid)
        for commit, edits in [
                ("0"*40, [Edit("app/a", None, "x")]),
                (self.base, [Edit("app/a", None, "ok"), Edit("app/b", "wrong", "fail")]),
                (self.base, [Edit("app/a", None, "ok"), Edit("app/A", None, "duplicate")]),
                (self.base, [Edit("app/a", None, "ok"), Edit("app/a/b", None, "overlap")])]:
            with self.assertRaises(ValueError):
                self.ws.apply("t", commit, edits)
        self.assertEqual("", self.ws.status())
        self.assertEqual(self.base, self.ws.head())

    def test_ambiguous_failure_blocks_replay(self):
        with patch.object(Path, "write_bytes", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.ws.apply("t", self.base, [Edit("app/a", None, "x")])
        with self.assertRaises(PendingRecovery):
            self.ws.apply("t", self.base, [Edit("app/a", None, "x")])
