import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.skills import load_skill, skill_manifest


SAMPLE = Path(__file__).resolve().parents[1] / "skills" / "requirements-analysis"


class SkillTest(unittest.TestCase):
    def test_context_and_hash_include_only_requested_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = shutil.copytree(SAMPLE, Path(tmp) / SAMPLE.name)
            original = load_skill(folder)
            resource = folder / "example.md"
            resource.write_text("unique-example", encoding="utf-8")
            revised = load_skill(folder)
            self.assertNotEqual(original.sha256, revised.sha256)
            self.assertNotIn("unique-example", revised.context(enabled=True))
            self.assertIn("unique-example", revised.context(enabled=True, resources=("example.md",)))
            self.assertEqual("", revised.context(enabled=False, resources=("example.md",)))
            with self.assertRaises(ValueError):
                revised.context(enabled=True, resources=("../outside.md",))
            resource.rename(folder / "renamed.md")
            self.assertNotEqual(revised.sha256, load_skill(folder).sha256)

    def test_manifest_identifies_committed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = shutil.copytree(SAMPLE, Path(tmp) / SAMPLE.name)
            def git(*args):
                return subprocess.check_output(["git", "-C", tmp, *args], text=True).strip()
            git("init", "-q")
            git("add", "--", SAMPLE.name)
            git("-c", "user.name=test", "-c", "user.email=test@example.org", "commit", "-qm", "sample")
            stamp = skill_manifest(folder, enabled=False)
            self.assertEqual(git("rev-parse", "HEAD"), stamp["commit"])
            self.assertEqual("1.1.0", stamp["version"])
            self.assertFalse(stamp["enabled"])
            (folder / "example.md").write_text("pending", encoding="utf-8")
            with self.assertRaises(ValueError):
                skill_manifest(folder, enabled=True)

    def test_invalid_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = shutil.copytree(SAMPLE, Path(tmp) / SAMPLE.name)
            source = folder / "SKILL.md"
            source.write_text(source.read_text(encoding="utf-8").replace('"1.1.0"', '""'), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_skill(folder)
