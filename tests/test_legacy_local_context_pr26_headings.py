"""ATX headings belong to Markdown; shell prompts in RST/AsciiDoc are prose."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context import freshness, store
from local_context.chunk import docs_units
from local_context.units import canonical, digest


class FormatHeadingTests(unittest.TestCase):
    def test_hash_lines_do_not_split_rst_or_asciidoc_sections(self):
        for suffix, fmt, title in (("rst", "rst", "Guide\n=====\n"),
                                   ("adoc", "asciidoc", "= Guide\n"),
                                   ("asciidoc", "asciidoc", "= Guide\n")):
            with self.subTest(suffix=suffix):
                text = title + "\n# shell prompt\n## still a prompt\nbody\n"
                units = docs_units(text, "guide." + suffix, fmt)
                self.assertEqual([unit.breadcrumb for unit in units], [("Guide",)])
                self.assertEqual((units[0].start, units[0].end), (1, len(text.splitlines())))
                self.assertEqual(units[0].text, text.rstrip("\n"))

    def test_markdown_and_mdx_atx_and_asciidoc_equals_headings_remain(self):
        for suffix, fmt, marker in (("md", "markdown", "#"), ("mdx", "markdown", "#"),
                                     ("adoc", "asciidoc", "=")):
            with self.subTest(suffix=suffix):
                units = docs_units(f"{marker} Guide\n\n{marker * 2} Usage\nbody\n", "guide." + suffix, fmt)
                self.assertEqual([unit.breadcrumb for unit in units], [("Guide",), ("Guide", "Usage")])

    def test_refresh_invalidates_revision_eight_chunks_without_source_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "docs"
            root.mkdir()
            (root / "guide.rst").write_text("Guide\n=====\n\n# shell prompt\nbody\n", encoding="utf-8")
            db = base / "index.sqlite"
            freshness.index(None, db, "/local/headings", docs_root=root, parser="0")
            with store.connect(db) as con:
                parser = json.loads(con.execute("SELECT parser_json FROM libraries").fetchone()[0])
                parser["chunker_revision"] = 8
                con.execute("UPDATE libraries SET parser_json=?", (canonical(parser),))
                con.execute("UPDATE files SET parser_fingerprint=?", (digest(canonical(parser).encode()),))
                con.commit()
            report = freshness.refresh(db)
            self.assertEqual(report["changed"], 1)
            with store.connect(db) as con:
                self.assertGreater(json.loads(con.execute("SELECT parser_json FROM libraries").fetchone()[0])["chunker_revision"], 8)
