"""Evaluation accepts transformed evidence while retaining exact-range validation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context import freshness
import eval_retrieval as evaluation

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"


class ApproximateEvaluationTests(unittest.TestCase):
    def test_adapter_preserves_mapping_for_multiline_html_and_compact_notebook(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "src"
            root.mkdir()
            docs = root / "docs"
            docs.mkdir()
            (docs / "manual.html").write_text("<h1>Guide</h1><p>html_marker</p><p>second</p><p>third</p>", encoding="utf-8")
            (root / "example.ipynb").write_text(json.dumps({"cells": [{"cell_type": "code", "source":
                ["notebook_marker = 1\n", "second = 2\n", "third = 3\n"]}]}), encoding="utf-8")
            (root / "plain.py").write_text("def exact_marker(): return 1\n", encoding="utf-8")
            db = base / "index.sqlite"
            freshness.index(root, db, "/local/mapping", docs_root=docs, parser="0")
            adapter = evaluation.Context7BackendAdapter(db, SCRIPTS / "context7_backend.py")
            for query, path in (("html_marker", "docs/manual.html"), ("notebook_marker", "example.ipynb")):
                with self.subTest(query=query):
                    results = adapter.search(query, 1)
                    self.assertEqual(len(results), 1)
                    result = results[0]
                    self.assertEqual(result.path, path)
                    self.assertEqual(result.lineMapping, "approximate")
                    self.assertGreater(len(result.text.splitlines()), result.endLine - result.startLine + 1)
            self.assertEqual(adapter.search("exact_marker", 1)[0].lineMapping, "exact")

    def test_only_approximate_mapping_relaxes_line_count_not_other_validation(self):
        row = {"path": "manual.html", "startLine": 1, "endLine": 1, "text": "first\nsecond\nthird"}
        result = evaluation.parse_results({"results": [{**row, "lineMapping": "approximate"}]})[0]
        self.assertEqual(result.lineMapping, "approximate")
        for mapping in (None, "exact", "unknown"):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                evaluation.parse_results({"results": [{**row, "lineMapping": mapping}]})
        for changes in ({"startLine": 0}, {"endLine": 0}, {"startLine": True}, {"text": None}, {"path": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                evaluation.parse_results({"results": [{**row, "lineMapping": "approximate", **changes}]})
