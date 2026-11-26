import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.skill_registry import ROLE_SKILLS, RunSkills


class RegistryTest(unittest.TestCase):
    def test_freeze_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            root = shutil.copytree(Path(__file__).resolve().parents[1] / "skills", folder / "skills")
            def git(*args):
                subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True)
            git("init", "-q")
            git("add", "skills")
            git("-c", "user.name=fixture", "-c", "user.email=test@example.org", "commit", "-qm", "skills")
            run = RunSkills(root, enabled=True)
            manifest = folder / "manifest.json"
            run.bind(manifest)
            original = manifest.read_bytes()
            self.assertEqual(set(json.loads(original)), set(ROLE_SKILLS))
            self.assertEqual(6, len({run.context(role) for role in ROLE_SKILLS}))
            RunSkills(root, enabled=True).bind(manifest)
            disabled = RunSkills(root, enabled=False)
            self.assertTrue(all(disabled.context(role) == "" for role in ROLE_SKILLS))
            with self.assertRaises(ValueError):
                disabled.bind(manifest)
            doc = root / ROLE_SKILLS["Dev"] / "SKILL.md"
            previous = run.context("Dev")
            doc.write_bytes(doc.read_bytes() + b"\nChanged")
            self.assertEqual(run.context("Dev"), previous)
            with self.assertRaises(ValueError):
                RunSkills(root, enabled=True)
            self.assertEqual(manifest.read_bytes(), original)
