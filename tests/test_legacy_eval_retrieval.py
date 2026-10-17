"""Offline regression tests for the engine-independent retrieval evaluator."""

import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts/eval_retrieval.py"
spec = importlib.util.spec_from_file_location("eval_retrieval", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evaluation
spec.loader.exec_module(evaluation)
Result = evaluation.Result


def question(kind="concept", targets=None):
    return {"id": "q1", "corpus": "fixture", "kind": kind, "question": "Find the answer",
            "expected": targets if targets is not None else [{"path": "src/a.py", "start": 4, "end": 6}]}


class MetricTests(unittest.TestCase):
    def test_inclusive_overlap_and_normalized_paths(self):
        target = {"path": "src/a.py", "start": 4, "end": 6}
        self.assertTrue(evaluation.overlaps(Result(".\\src\\a.py", 1, 4, "x"), target))
        self.assertTrue(evaluation.overlaps(Result("src/a.py", 6, 9, "x"), target))
        self.assertFalse(evaluation.overlaps(Result("src/a.py", 1, 3, "x"), target))
        self.assertFalse(evaluation.overlaps(Result("src/other.py", 4, 6, "x"), target))
        self.assertFalse(evaluation.overlaps(Result("src/A.py", 4, 6, "x"), target))

    def test_rank_metrics_and_macro_micro_recall(self):
        targets = [{"path": "src/a.py", "start": 4, "end": 6}, {"path": "src/b.py", "start": 8, "end": 8}]
        results = [Result("wrong.py", 1, 1, "no"), Result("src/a.py", 4, 4, "yes")]
        score = evaluation.score_question(question(targets=targets), results, [2])
        self.assertEqual([score[f"hit@{k}"] for k in (1, 3, 5, 10)], [False, True, True, True])
        self.assertEqual(score["MRR@10"], .5)
        self.assertEqual(score["recall@10"], .5)
        other = evaluation.score_question(question(), [Result("src/a.py", 4, 4, "yes")], [2])
        records = [{"question": question(targets=targets), "metrics": score, "latency_seconds": .1},
                   {"question": question(), "metrics": other, "latency_seconds": .5}]
        summary = evaluation.summarize(records, [2])
        self.assertEqual(summary["recall@10"], .75)
        self.assertAlmostEqual(summary["micro_range_recall@10"], 2 / 3)

    def test_duplicate_results_do_not_inflate_range_recall(self):
        result = Result("src/a.py", 4, 4, "yes")
        score = evaluation.score_question(question(), [result] * 10, [100])
        self.assertEqual(score["matched_ranges@10"], 1)
        self.assertEqual(score["recall@10"], 1)

    def test_rank_eleven_is_not_a_hit(self):
        score = evaluation.score_question(question(), [Result("bad.py", 1, 1, "x")] * 10 + [Result("src/a.py", 4, 4, "y")], [100])
        self.assertEqual(score["MRR@10"], 0)
        self.assertFalse(score["hit@10"])
        self.assertFalse(score["budgets"]["100"]["hit"])

    def test_all_hit_cutoffs(self):
        for rank in (1, 2, 3, 4, 5, 6, 10):
            with self.subTest(rank=rank):
                rows = [Result("bad.py", 1, 1, "x")] * (rank - 1) + [Result("src/a.py", 4, 4, "yes")]
                score = evaluation.score_question(question(), rows, [100])
                for cutoff in (1, 3, 5, 10):
                    self.assertEqual(score[f"hit@{cutoff}"], rank <= cutoff)
                self.assertEqual(score["MRR@10"], 1 / rank)

    def test_budget_clips_last_result_and_tracks_actual_returned_lines(self):
        results = [Result("src/a.py", 3, 5, "bad\ngood\nrest")]
        expected = [{"path": "src/a.py", "start": 4, "end": 4}]
        first = evaluation.budget_context(results, expected, 1)
        self.assertFalse(first["hit"])
        self.assertEqual(first["returned_chars"], 4)
        second = evaluation.budget_context(results, expected, 2)
        self.assertTrue(second["hit"])
        self.assertEqual(second["character_precision"], .5)
        self.assertEqual(second["estimated_tokens"], 2)

    def test_budget_charges_rank_order_and_duplicates(self):
        results = [Result("bad.py", 1, 1, "a" * 8), Result("src/a.py", 4, 4, "yes")]
        self.assertFalse(evaluation.budget_context(results, question()["expected"], 2)["hit"])
        duplicate = Result("src/a.py", 4, 4, "yes")
        measured = evaluation.budget_context([duplicate, duplicate], question()["expected"], 10)
        self.assertEqual(measured["returned_chars"], 6)
        self.assertEqual(measured["relevant_chars"], 6)
        self.assertEqual(measured["estimated_tokens"], 2)

    def test_budget_union_does_not_double_count_overlapping_expected_ranges(self):
        targets = [{"path": "src/a.py", "start": 4, "end": 6}, {"path": "src/a.py", "start": 5, "end": 7}]
        score = evaluation.budget_context([Result("src/a.py", 5, 5, "abc")], targets, 10)
        self.assertEqual(score["character_precision"], 1)
        self.assertEqual(score["range_recall"], 1)

    def test_empty_budget_results(self):
        score = evaluation.budget_context([], question()["expected"], 10)
        self.assertEqual(score["estimated_tokens"], 0)
        self.assertEqual(score["character_precision"], 0)
        self.assertFalse(score["hit"])

    def test_unicode_and_crlf_characters(self):
        score = evaluation.budget_context([Result("src/a.py", 3, 4, "ą\r\nβ")], question()["expected"], 1)
        self.assertEqual(score["returned_chars"], 4)
        self.assertEqual(score["relevant_chars"], 1)
        self.assertEqual(score["character_precision"], .25)

    def test_absent_exact_token_case_and_rank_cutoff(self):
        q = question("absent", [])
        q["absentIdentifier"] = "NoSuchAPI"
        ok = Result("x.py", 1, 1, "NoSuchAPIExtra _NoSuchAPI NoSuchAPI_ $NoSuchAPI nosuchapi")
        bad = Result("x.py", 1, 1, "call(NoSuchAPI)")
        self.assertTrue(evaluation.score_question(q, [ok], [100])["absent_success"])
        self.assertFalse(evaluation.score_question(q, [bad], [100])["absent_success"])
        self.assertTrue(evaluation.score_question(q, [ok] * 5 + [bad], [100])["absent_success"])
        self.assertTrue(evaluation.score_question(q, [], [100])["absent_success"])
        self.assertFalse(evaluation.score_question(q, [], [100], "failure")["absent_success"])

    def test_absent_excluded_from_positive_metrics(self):
        q = question("absent", [])
        q["absentIdentifier"] = "NoSuchAPI"
        records = [{"question": q, "metrics": evaluation.score_question(q, [], [100]), "latency_seconds": .2}]
        score = evaluation.summarize(records, [100])
        self.assertIsNone(score["hit@1"])
        self.assertIsNone(score["recall@10"])
        self.assertEqual(score["absent_success"], 1)

    def test_nearest_rank_percentiles(self):
        self.assertEqual(evaluation.percentile(list(range(1, 21)), .95), 19)
        self.assertEqual(evaluation.percentile([3], .5), 3)
        self.assertIsNone(evaluation.percentile([], .5))


class InputAndAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_malformed_question_lines_include_line_number(self):
        path = self.root / "questions.jsonl"
        invalid = ["{", "[]", json.dumps({**question(), "kind": "oops"}),
                   json.dumps({**question(), "expected": [{"path": "x", "start": True, "end": 3}]}),
                   json.dumps({**question(), "expected": []}),
                   json.dumps({**question(), "kind": "absent", "expected": []}), ""]
        for line in invalid:
            with self.subTest(line=line):
                path.write_text(json.dumps(question()) + "\n" + line + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, r"line 2:"):
                    evaluation.load_questions(path)

    def test_duplicate_ids_rejected(self):
        path = self.root / "q.jsonl"
        path.write_text((json.dumps(question()) + "\n") * 2)
        with self.assertRaisesRegex(ValueError, "line 2: duplicate"):
            evaluation.load_questions(path)

    def test_question_path_and_absent_identifier(self):
        path = self.root / "q.jsonl"
        q = question(targets=[{"path": ".\\src\\a.py", "start": 1, "end": 2}])
        absent = {**question("absent", []), "id": "q2", "question": "NoSuchAPI"}
        path.write_text(json.dumps(q) + "\n" + json.dumps(absent) + "\n")
        loaded = evaluation.load_questions(path)
        self.assertEqual(loaded[0]["expected"][0]["path"], "src/a.py")
        self.assertEqual(loaded[1]["absentIdentifier"], "NoSuchAPI")

    def test_command_adapter_preserves_query_as_one_argument(self):
        query = 'hello "world"; $(touch bad) {limit} \\ path'
        code = 'import json,sys; print(json.dumps({"results":[{"path":"x.py","startLine":1,"endLine":1,"text":sys.argv[1]}]}))'
        adapter = evaluation.CommandAdapter([sys.executable, "-c", code, "{query}", "{limit}"])
        self.assertEqual(adapter.search(query, 10), [Result("x.py", 1, 1, query)])

    def test_command_invalid_output_and_exit_are_rejected(self):
        for code, error in [('print("not JSON")', "valid JSON"), ('print("{}")', "results array"),
                            ('import sys; sys.stderr.write("broken");sys.exit(7)', "exited 7: broken")]:
            adapter = evaluation.CommandAdapter([sys.executable, "-c", code, "{query}", "{limit}"])
            with self.assertRaisesRegex(ValueError, error):
                adapter.search("test", 10)

    def test_result_validation(self):
        good = {"path": "a", "startLine": 1, "endLine": 1, "text": "yes"}
        for row in [{**good, "endLine": 0}, {**good, "startLine": True}, {**good, "text": None},
                    {**good, "path": ""}, {**good, "text": "a\nb"}]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                evaluation.parse_results({"results": [row]})

    def test_trailing_line_terminator_is_not_an_extra_source_line(self):
        rows = [{"path": "a.py", "startLine": 2, "endLine": 2, "text": "answer\n"}]
        self.assertEqual(evaluation.parse_results({"results": rows}), [Result("a.py", 2, 2, "answer\n")])

    def test_timeout_recorded_as_error_and_absence_never_passes(self):
        adapter = mock.Mock()
        adapter.search.side_effect = subprocess.TimeoutExpired("fixture", 1)
        q = {**question("absent", []), "absentIdentifier": "NoSuchAPI"}
        report = evaluation.evaluate([q], adapter, [2000])
        self.assertEqual(report["overall"]["errors"], 1)
        self.assertEqual(report["overall"]["absent_success"], 0)

    def test_backend_mapping_nested_docs_and_subtree(self):
        root = self.root / "corpus"
        code = root / "src"
        docs = root / "docs"
        db = self.root / "db.sqlite"
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE meta(key TEXT,value TEXT)")
            con.executemany("INSERT INTO meta VALUES(?,?)", [("root", str(code)), ("docs_root", str(docs))])
        adapter = evaluation.Context7BackendAdapter(db, SCRIPT, corpus_root=root)
        payload = {"results": [{"source": {"kind": "docs", "path": "howto.md", "startLine": 3, "endLine": 3}, "text": "doc"},
                               {"source": {"kind": "code", "path": "a.py", "startLine": 1, "endLine": 1}, "text": "code"}]}
        with mock.patch.object(evaluation, "run_json", return_value=payload):
            results = adapter.search("query", 10)
        self.assertEqual([result.path for result in results], ["docs/howto.md", "src/a.py"])

    def test_backend_adapter_accepts_leading_dash_query_with_actual_backend(self):
        backend_script = SCRIPT.with_name("context7_backend.py")
        backend_spec = importlib.util.spec_from_file_location("eval_backend_fixture", backend_script)
        backend = importlib.util.module_from_spec(backend_spec)
        backend_spec.loader.exec_module(backend)
        root = self.root / "source"
        root.mkdir()
        (root / "marker.py").write_text("identifier_token = 1\n", encoding="utf-8")
        database = self.root / "index.sqlite"
        backend.index(root, database, "/eval/fixture", None, None, None)
        adapter = evaluation.Context7BackendAdapter(database, backend_script)
        results = adapter.search("--identifier_token", 10)
        self.assertTrue(results)
        self.assertEqual(results[0].path, "marker.py")

    def test_backend_adapter_uses_selected_library_roots_without_primary_meta(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from local_context import freshness, store
        code = self.root / "primary"
        docs = self.root / "secondary"
        code.mkdir()
        docs.mkdir()
        (code / "first.py").write_text("def primary(): pass\n", encoding="utf-8")
        (docs / "guide.md").write_text("# Secondary\nA unique secondary answer.\n", encoding="utf-8")
        database = self.root / "libraries.sqlite"
        freshness.index(code, database, "/eval/primary", parser="0")
        freshness.index(None, database, "/eval/secondary", docs_roots=[docs], parser="0")
        with store.connect(database) as con:
            con.execute("DELETE FROM meta WHERE key IN ('root','docs_root')")
        with self.assertRaisesRegex(ValueError, "library-id"):
            evaluation.Context7BackendAdapter(database, SCRIPT.with_name("context7_backend.py"))
        adapter = evaluation.Context7BackendAdapter(database, SCRIPT.with_name("context7_backend.py"), library_id="/eval/secondary")
        self.assertEqual(adapter.argv[adapter.argv.index("--library-id") + 1], "/eval/secondary")
        result = adapter.search("secondary answer", 10)
        self.assertTrue(result)
        self.assertEqual(result[0].path, "guide.md")

    def test_backend_adapter_docs_only_and_multiple_docs_root_namespaces(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from local_context import freshness
        docs = [self.root / "first", self.root / "second"]
        for root in docs:
            root.mkdir()
            (root / "guide.md").write_text("# Guide\nanswer marker\n", encoding="utf-8")
        database = self.root / "docs.sqlite"
        freshness.index(None, database, "/eval/docs", docs_roots=docs, parser="0")
        adapter = evaluation.Context7BackendAdapter(database, SCRIPT.with_name("context7_backend.py"), corpus_root=self.root)
        self.assertEqual({r.path for r in adapter.search("marker", 10)}, {"first/guide.md", "second/guide.md"})

    def test_cli_writes_json_and_markdown_for_command_engine(self):
        path = self.root / "q.jsonl"
        path.write_text(json.dumps(question()) + "\n")
        code = 'print(\'{"results":[{"path":"src/a.py","startLine":4,"endLine":4,"text":"answer"}]}\')'
        result = subprocess.run([sys.executable, str(SCRIPT), str(path), "--engine", "command", "--command-json",
                                 json.dumps([sys.executable, "-c", code, "{query}", "{limit}"]),
                                 "--json-output", str(self.root / "out.json"), "--markdown-output", str(self.root / "out.md")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / "out.json").read_text())
        self.assertEqual(report["overall"]["hit@1"], 1)
        self.assertIn("kind:concept", (self.root / "out.md").read_text())
        self.assertIn("corpus:fixture", (self.root / "out.md").read_text())


if __name__ == "__main__":
    unittest.main()
