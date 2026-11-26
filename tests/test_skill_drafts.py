"""Validation tests for the 6 proposed detailed SKILL.md drafts (support branch)."""

from __future__ import annotations

import unittest
from pathlib import Path

from backend.skill_registry import ROLE_SKILLS
from backend.skills import load_skill


ROOT = Path(__file__).resolve().parents[1]
DRAFT_ROOT = ROOT / "docs" / "de-xuat-skills"
ORIG_ROOT = ROOT / "skills"


class ProposedSkillDraftsTests(unittest.TestCase):
    def test_all_six_proposed_drafts_parse_with_strict_skill_loader(self) -> None:
        for role, skill_name in ROLE_SKILLS.items():
            folder = DRAFT_ROOT / skill_name
            self.assertTrue((folder / "SKILL.md").is_file(), f"Missing draft for {role}: {skill_name}")
            skill = load_skill(folder)
            self.assertEqual(skill.name, skill_name)
            self.assertEqual(skill.version, "0.2.0-draft")
            self.assertIn("Điều cấm tuyệt đối", skill.instructions)
            self.assertEqual(skill.context(enabled=False), "")
            self.assertTrue(len(skill.context(enabled=True)) > 200)

    def test_original_i08_skills_remain_untouched(self) -> None:
        for skill_name in ROLE_SKILLS.values():
            orig = load_skill(ORIG_ROOT / skill_name)
            self.assertNotEqual(orig.version, "0.2.0-draft")


if __name__ == "__main__":
    unittest.main()
