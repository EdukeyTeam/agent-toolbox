"""CommonMark indented code and paragraph continuation heading regressions."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/legacy-codebase-workflows/scripts'))
from local_context.chunk import docs_units


class MarkdownIndentTests(unittest.TestCase):
    def test_indented_examples_are_not_headings(self):
        for indent in ('    ', '\t'):
            for extension in ('md', 'mdx'):
                text = f'# Guide\n\n{indent}Pretend\n{indent}-------\n\n{indent}# Still code\n\n## Real\nBody\n'
                with self.subTest(indent=indent, extension=extension):
                    units = docs_units(text, f'guide.{extension}', 'markdown')
                    self.assertEqual([u.breadcrumb for u in units], [('Guide',), ('Guide', 'Real')])
                    self.assertEqual([(u.start, u.end) for u in units], [(1, 7), (8, 9)])
                    self.assertEqual('\n'.join(u.text for u in units), text.rstrip('\n'))

    def test_indented_code_cannot_interrupt_paragraph(self):
        text = '# Guide\n\nParagraph\n    continued\n---\n\n## Real\nBody\n'
        units = docs_units(text, 'guide.md', 'markdown')
        self.assertIn(('Guide', 'continued'), [u.breadcrumb for u in units])
        # Four-space underlines do not form Setext headings, even in paragraphs.
        units = docs_units('# Guide\n\nParagraph\n    -------\n\n## Real\nBody\n', 'guide.md', 'markdown')
        self.assertEqual([u.breadcrumb for u in units], [('Guide',), ('Guide', 'Real')])

    def test_blank_line_ends_paragraph_and_dedent_ends_code(self):
        text = '# Guide\n\nParagraph\n\n    Pretend\n    ---\n\nReal\n---\nBody\n'
        units = docs_units(text, 'guide.md', 'markdown')
        self.assertEqual([u.breadcrumb for u in units], [('Guide',), ('Guide', 'Real')])
