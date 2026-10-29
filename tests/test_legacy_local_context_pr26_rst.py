"""PR #26: literal and directive bodies are not RST headings."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context.chunk import docs_units


class RstTests(unittest.TestCase):
    def test_literal_and_directive_blocks_preserve_real_breadcrumbs(self):
        for introduction in ("Example::", ".. code-block:: text", ".. note::"):
            for indent in ("    ", "\t"):
                with self.subTest(introduction=introduction, indent=indent):
                    text = "Guide\n=====\n\n" + introduction + "\n\n" + indent + "Pretend heading\n" + indent + "===============\n\n" + indent + "# Also literal\n\nReal section\n------------\nBody\n"
                    units = docs_units(text, "guide.rst", "rst")
                    self.assertEqual([u.breadcrumb for u in units], [("Guide",), ("Guide", "Real section")])
                    self.assertEqual([(u.start, u.end) for u in units], [(1, 10), (11, 13)])

    def test_nested_literal_ends_on_dedent_and_keeps_indented_real_headings(self):
        text = "Guide\n=====\n\n  Example::\n\n      Pretend heading\n      ===============\n\n  Real section\n  ------------\n  Body\n"
        units = docs_units(text, "guide.rst", "rst")
        self.assertEqual([u.breadcrumb for u in units], [("Guide",), ("Guide", "Real section")])


if __name__ == "__main__":
    unittest.main()
