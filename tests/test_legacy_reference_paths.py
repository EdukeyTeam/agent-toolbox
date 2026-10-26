"""Public instructions must point to skill or source-repository files."""
from pathlib import Path
import re
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows"


class ReferencePathTests(unittest.TestCase):
    def test_document_links_and_skill_file_paths_exist(self):
        for document in [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]:
            for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
                for target in re.findall(r"\]\(([^)]+)\)", line):
                    if "://" in target or target.startswith("#"):
                        continue
                    with self.subTest(document=document.name, line=number, target=target):
                        self.assertTrue((document.parent / target.split("#")[0]).exists())
                for target in re.findall(r"(?:/path/to/skill/)?(?:scripts|assets)/[\w./-]+|(?<![\w/-])requirements-[\w-]+\.txt", line):
                    target = target.removeprefix("/path/to/skill/").rstrip(".")
                    with self.subTest(document=document.name, line=number, target=target):
                        self.assertTrue(any((base / target).exists() for base in (SKILL, SKILL.parents[1])), f"Missing repository file: {target}")
