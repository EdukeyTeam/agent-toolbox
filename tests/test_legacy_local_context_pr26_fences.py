"""PR #26: nested examples must not split documentation sections."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context.chunk import docs_units


class FenceTests(unittest.TestCase):
    def test_only_valid_closing_fence_ends_example(self):
        for marker in ("`", "~"):
            for length in (4, 5):
                for closer in (marker * (length - 1), marker * length + " invalid", ("~" if marker == "`" else "`") * length):
                    with self.subTest(marker=marker, length=length, closer=closer):
                        text = f"# Guide\n\n{marker * length}text\n{closer}\n# Inside example\nPretend heading\n---\n{marker * (length + 1)}\n\n## Real section\nBody\n"
                        units = docs_units(text, "guide.mdx", "markdown")
                        self.assertEqual([u.breadcrumb for u in units], [("Guide",), ("Guide", "Real section")])
                        self.assertEqual([(u.start, u.end) for u in units], [(1, 9), (10, 11)])


if __name__ == "__main__":
    unittest.main()
