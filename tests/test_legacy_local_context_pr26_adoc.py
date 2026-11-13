"""AsciiDoc examples preserve source lines without creating sections."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/legacy-codebase-workflows/scripts'))
from local_context.chunk import docs_units


class AsciiDocBlockTests(unittest.TestCase):
    def test_listing_literal_and_passthrough_blocks(self):
        for fmt in ('asciidoc',):
            for delimiter in ('----', '....', '++++', '------', '......', '++++++'):
                for suffix in ('adoc', 'asciidoc'):
                    with self.subTest(delimiter=delimiter, suffix=suffix):
                        text = f'= Guide\n\n{delimiter}\n= Example output\nPretend\n-------\n{delimiter}\n\n== Real section\nBody\n'
                        units = docs_units(text, f'guide.{suffix}', fmt)
                        self.assertEqual([u.breadcrumb for u in units], [('Guide',), ('Guide', 'Real section')])
                        self.assertEqual([(u.start, u.end) for u in units], [(1, 8), (9, 10)])
                        self.assertEqual('\n'.join(u.text for u in units), text.rstrip('\n'))
