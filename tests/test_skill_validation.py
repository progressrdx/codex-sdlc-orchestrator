from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).resolve().parents[1] / "tools" / "validate_skill.py"
SPEC = importlib.util.spec_from_file_location("repository_skill_validation", VALIDATOR)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SkillValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_skill(self, frontmatter: str, body: str = "Use this skill for focused work.\n") -> None:
        (self.root / "SKILL.md").write_text(
            f"---\n{frontmatter}\n---\n{body}", encoding="utf-8"
        )

    def test_valid_metadata_and_fenced_examples(self) -> None:
        for fence in ("```", "~~~~", "- ```"):
            with self.subTest(fence=fence):
                self.write_skill(
                    "name: test-skill\ndescription: |\n  A useful skill.\nmetadata:\n  audience: developers",
                    f"{fence}\n[TODO: example only]\n{fence.lstrip('- ')}\n",
                )
                MODULE.validate_skill(self.root)

    def test_invalid_metadata_is_rejected(self) -> None:
        cases = [
            "[]", "name: [", "- name", "name: test-skill",
            "description: A useful skill.",
            "name: 123\ndescription: A useful skill.",
            "name: ''\ndescription: A useful skill.",
            "name: Bad_Name\ndescription: A useful skill.",
            "name: bad--name\ndescription: A useful skill.",
            f"name: {'a' * 65}\ndescription: A useful skill.",
            "name: test-skill\ndescription: 123",
            "name: test-skill\ndescription: ' '",
            "name: test-skill\ndescription: '<unsafe>'",
            "name: test-skill\ndescription: '[TODO: fill this]'",
            f"name: test-skill\ndescription: {'a' * 1025}",
            "name: test-skill\ndescription: A useful skill.\nunsupported: true",
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.write_skill(metadata)
                with self.assertRaises(ValueError):
                    MODULE.validate_skill(self.root)

    def test_missing_file_and_frontmatter_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_skill(self.root)
        for content in ("No header", "---\nname: incomplete", "---\nname: x\n---not-a-delimiter"):
            with self.subTest(content=content):
                (self.root / "SKILL.md").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    MODULE.validate_skill(self.root)

    def test_unfinished_body_is_rejected_including_after_fence(self) -> None:
        for body in ("[TODO: write instructions]", "```\nexample\n```\n[TODO: write instructions]"):
            with self.subTest(body=body):
                self.write_skill("name: test-skill\ndescription: A useful skill.", body)
                with self.assertRaises(ValueError):
                    MODULE.validate_skill(self.root)

    def test_cli_exit_codes(self) -> None:
        self.write_skill("name: test-skill\ndescription: A useful skill.")
        valid = subprocess.run([sys.executable, str(VALIDATOR), str(self.root)], capture_output=True, text=True)
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.write_skill("name: test-skill")
        invalid = subprocess.run([sys.executable, str(VALIDATOR), str(self.root)], capture_output=True, text=True)
        self.assertEqual(1, invalid.returncode)
        self.assertIn("description", invalid.stderr)
        missing_argument = subprocess.run([sys.executable, str(VALIDATOR)], capture_output=True)
        self.assertEqual(2, missing_argument.returncode)
