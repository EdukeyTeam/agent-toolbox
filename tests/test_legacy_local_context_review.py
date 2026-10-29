"""Offline regressions for the independent local-retrieval code reviews."""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from local_context import assemble, chunk, decode, discover, engine, freshness, search, store
from local_context.units import RetrievalError


class FakeProvider:
    identity = {"provider": "fake", "model": "review-fixture", "dimension": 2}
    truncated = 0

    def embed_documents(self, texts):
        return [[0., 1.] if "TargetWorker" in text else [1., 0.] for text in texts]

    def embed_query(self, text):
        return [1., 0.]

    def close(self):
        pass


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.db = self.base / "index.sqlite"
        (self.root / "service.py").write_text('def TargetWorker():\n    """zażółć 中文"""\n    return 1\n', encoding="utf-8")

    def index(self, **kwargs):
        return freshness.index(self.root, self.db, "/local/review", parser="0", **kwargs)

    def embed(self):
        provider = FakeProvider()
        with mock.patch.object(freshness, "provider_for", return_value=provider):
            self.index(_saved={"provider": "fake"})
        return provider

    def test_hash_comment_apostrophes_do_not_swallow_function_braces(self):
        for language in ("powershell", "php", "bash", "ruby", "perl", "r"):
            with self.subTest(language=language):
                text = "# Don't retry here\nfunction First() {\n  echo 'ok';\n}\n# Don't repeat\nfunction Second() {\n  echo 'ok';\n}\n"
                definitions = chunk.generic_definitions(text, language)
                self.assertEqual([(d.name, d.start, d.end) for d in definitions], [("First", 2, 4), ("Second", 6, 8)])
        text = "function First() {\n  unmatched = 'value\n}\nfunction Second() {\n  print('other');\n}\n"
        self.assertEqual([d.end for d in chunk.generic_definitions(text, "javascript")], [3, 6])

    def test_git_inventory_works_without_new_git_flag_and_deduplicates(self):
        roots = discover.roots_for(self.root, [])
        process = mock.Mock()
        process.stdout = io.BytesIO(b"service.py\0service.py\0")
        process.wait.return_value = 0
        process.poll.return_value = 0

        def old_git(argv, **kwargs):
            self.assertNotIn("--deduplicate", argv)
            return process

        counters = {}
        with mock.patch.object(discover, "git_context", return_value=True), mock.patch.object(discover.subprocess, "Popen", side_effect=old_git):
            files = list(discover.inventory(roots, counters=counters))
        self.assertEqual([f[1] for f in files], ["service.py"])
        self.assertEqual(counters["eligible"], 1)

    def test_definition_partition_uses_linear_metadata_visits(self):
        visits = 0

        class Counted:
            def __init__(self, definition):
                self.definition = definition

            def __getattr__(self, name):
                nonlocal visits
                visits += 1
                return getattr(self.definition, name)

        count = 2000
        text = "".join(f"def f{i}():\n    return {i}\n" for i in range(count))
        definitions = [Counted(d) for d in chunk.python_definitions(text)]
        with mock.patch.object(chunk, "python_definitions", return_value=definitions):
            units, _ = chunk.code_units(text, "large.py", "python")
        self.assertEqual(len(units), count)
        self.assertLess(visits, count * 100, "Definition metadata must not be rescanned per piece")
        self.assertEqual([(u.start, u.end) for u in units], [(2 * i + 1, 2 * i + 2) for i in range(count)])

    def test_nested_partition_attaches_innermost_oversized_parent(self):
        text = "class Outer:\n    def worker(self):\n" + "".join(f"        value{i} = {i}\n" for i in range(100)) + "    def small(self):\n        return 1\n"
        units, _ = chunk.code_units(text, "nested.py", "python", target=128)
        for unit in units:
            if unit.searchable and unit.parent is not None:
                parent = units[unit.parent]
                self.assertLessEqual(parent.start, unit.start)
                self.assertGreaterEqual(parent.end, unit.end)
                enclosing = [p for p in units if not p.searchable and p.start <= unit.start and p.end >= unit.end]
                self.assertEqual(parent.end - parent.start, min(p.end - p.start for p in enclosing))
        self.assertEqual(set(n for u in units if u.searchable for n in range(u.start, u.end + 1)), set(range(1, len(text.splitlines()) + 1)))

    def test_cli_redirected_legacy_code_page_emits_utf8_source(self):
        self.index()
        for format_name in ("json", "text", "context7-json"):
            with self.subTest(format_name=format_name):
                process = subprocess.run([sys.executable, str(SCRIPTS / "context7_backend.py"), "query", "--database", str(self.db), "--query", "TargetWorker", "--format", format_name], capture_output=True, env={**os.environ, "PYTHONIOENCODING": "cp1252"}, timeout=20)
                self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
                self.assertIn("zażółć 中文", process.stdout.decode("utf-8"))

    def test_encoding_declarations_are_limited_to_prologs(self):
        examples = {
            "late.py": '\n\n\n"""coding: cp1250\nzażółć\n"""\n',
            "body.html": '<html><body><p>charset=cp1250 zażółć</p></body></html>',
            "comment.html": '<!-- <meta charset=cp1250> --><html><body>zażółć</body></html>',
            "body.xml": '<root encoding="cp1250">zażółć</root>',
            "body.config": '<root>encoding="cp1250" zażółć</root>',
        }
        for name, text in examples.items():
            with self.subTest(name=name):
                (self.root / name).write_bytes(text.encode("utf-8"))
                source = decode.read_source(self.root, name)
                self.assertEqual(source.encoding, "utf-8")
                self.assertEqual(source.text, text)
        valid = {"cookie.py": '#!/usr/bin/python\n# coding: cp1250\n# zażółć\n', "meta.html": '<!doctype html><html><head><meta charset="cp1250"></head><body>zażółć</body>', "prolog.xml": '<?xml version="1.0" encoding="cp1250"?><root>zażółć</root>'}
        for name, text in valid.items():
            with self.subTest(name=name):
                (self.root / name).write_bytes(text.encode("cp1250"))
                source = decode.read_source(self.root, name)
                self.assertEqual(source.encoding, "cp1250")
                self.assertEqual(source.text, text)

    def test_markdown_bare_fence_is_not_a_setext_heading(self):
        for fence in ("```", "~~~"):
            text = f"# Guide\nA paragraph\n{fence}\n# code heading\n{fence}\nMore prose\n"
            units = chunk.docs_units(text, "guide.md", "markdown")
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].breadcrumb, ("Guide",))
        for underline in (":::" , "###", "+++", "^^^", "***"):
            units = chunk.docs_units("# Guide\nParagraph\n" + underline + "\n", "guide.md", "markdown")
            self.assertEqual(len(units), 1)
        self.assertEqual(chunk.docs_units("Title\n===\nChild\n---\n", "guide.md", "markdown")[-1].breadcrumb, ("Title", "Child"))

    def test_symlinked_ancestor_is_canonical_but_symlink_root_rejected(self):
        alias = self.base / "alias"
        try:
            alias.symlink_to(self.base, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is unavailable")
        self.assertEqual(discover.roots_for(alias / "source", [])[0].path, str(self.root))
        with self.assertRaisesRegex(RetrievalError, "nonsymlink"):
            discover.roots_for(alias, [])

    def test_failed_first_index_can_retry_same_database(self):
        (self.root / "second.py").write_text("def other(): pass\n", encoding="utf-8")
        with self.assertRaisesRegex(RetrievalError, "Discovery entry limit"):
            self.index(discovery_limit=1)
        self.assertTrue(self.db.exists())
        self.assertEqual(self.index()["files"], 2)
        with store.connect(self.db) as con:
            self.assertTrue(engine.query(con, "TargetWorker")["results"])

    def test_incomplete_embedding_coverage_is_library_and_filter_scoped(self):
        (self.root / "other.js").write_text("function unrelated() {}\n", encoding="utf-8")
        provider = self.embed()
        with store.connect(self.db) as con:
            con.execute("DELETE FROM unit_vectors WHERE unit_id IN (SELECT id FROM units WHERE language='javascript')")
            with mock.patch.object(engine, "provider_for", return_value=provider):
                hybrid = engine.query(con, "TargetWorker", mode="hybrid", vector_engine="stdlib")
                with self.assertRaises(RetrievalError) as incomplete:
                    engine.query(con, "TargetWorker", mode="semantic", vector_engine="stdlib")
                filtered = engine.query(con, "TargetWorker", mode="semantic", language="python", vector_engine="stdlib")
            self.assertEqual(hybrid["coverage"]["embeddingCoverage"], .5)
            self.assertTrue(any("incomplete" in warning for warning in hybrid["warnings"]))
            self.assertEqual(incomplete.exception.code, "embedding_incomplete")
            self.assertEqual(incomplete.exception.status, 409)
            self.assertEqual(filtered["coverage"]["embeddingCoverage"], 1.)
            self.assertTrue(filtered["results"])
            self.assertEqual(engine.status(con)["libraries"][0]["embeddingCoverage"], .5)
            con.execute("DELETE FROM unit_vectors")
            with self.assertRaises(RetrievalError) as incomplete:
                engine.query(con, "TargetWorker", mode="semantic")
            self.assertEqual(incomplete.exception.code, "embedding_incomplete")

    def test_secret_spans_do_not_recount_prefix_for_every_match(self):
        class NoPrefixCount(str):
            def count(self, *args):
                raise AssertionError("Secret scan must not recount source prefixes")

        text = NoPrefixCount("safe\n" + "\n".join("ghp_" + "x" * 36 for _ in range(1000)))
        spans = decode.secret_spans(text)
        self.assertEqual(spans, [(n, n) for n in range(2, 1002)])

    def test_python_header_contains_leading_comments_and_docstring(self):
        text = '# Routing contract\n# Keep the route stable\n@decorator\ndef operation():\n    """Execute the request."""\n    return 1\n'
        definition = chunk.python_definitions(text)[0]
        self.assertIn("# Routing contract", definition.description)
        self.assertIn("Execute the request.", definition.description)
        units, _ = chunk.code_units(text, "route.py", "python")
        unit = next(u for u in units if u.title == "operation")
        self.assertIn("# Routing contract", unit.header)
        self.assertIn("Execute the request.", unit.header)

    def test_nested_retrieval_helpers_are_in_runtime_manifest(self):
        import setup_context7
        nested = self.base / "skill/scripts/retrieval/nested/helper.mjs"
        nested.parent.mkdir(parents=True)
        nested.write_text("export const helper = true;\n", encoding="utf-8")
        modules = self.base / "skill/scripts/retrieval/node_modules/dependency"
        modules.mkdir(parents=True)
        (modules / "package.json").write_text("{}", encoding="utf-8")
        files = setup_context7.backend_files(self.base / "skill")
        self.assertIn("scripts/retrieval/nested/helper.mjs", files)
        self.assertFalse(any("node_modules" in path for path in files))

    def test_hybrid_exact_symbols_and_paths_precede_dense_only_hits(self):
        (self.root / "settings.yaml").write_text("target: 42\n", encoding="utf-8")
        (self.root / "Buildfile").write_text("target build\n", encoding="utf-8")
        (self.root / "unrelated.py").write_text("def zebra():\n    return 'meadow orchard'\n", encoding="utf-8")
        for n in range(8):
            (self.root / f"noise{n}.py").write_text(f'def incidental{n}():\n    """Worker factory service requests."""\n    return 2\n', encoding="utf-8")
        provider = self.embed()
        with store.connect(self.db) as con:
            for question, path in (("Where is TargetWorker defined?", "service.py"), ("Where is service.py?", "service.py"), ("TargetWorker", "service.py"), ("settings.yaml", "settings.yaml"), ("Buildfile", "Buildfile")):
                with self.subTest(question=question), mock.patch.object(engine, "provider_for", return_value=provider):
                    lexical = engine.query(con, question)
                    hybrid = engine.query(con, question, mode="hybrid", vector_engine="stdlib")
                    self.assertEqual(hybrid["results"][0]["source"]["path"], path)
                    self.assertEqual(lexical["results"][0]["source"]["path"], path)
                    rows, _ = search.candidates(con, store.library(con), question, mode="hybrid", provider=provider, vector_engine="stdlib")
                    anchors = [i for i, r in enumerate(rows) if "symbol" in r["channels"] or "path" in r["channels"]]
                    dense_only = [i for i, r in enumerate(rows) if set(r["channels"]) == {"vector"}]
                    self.assertTrue(anchors)
                    self.assertTrue(dense_only)
                    self.assertLess(max(anchors), min(dense_only))

    def test_hybrid_preserves_leading_exact_hits_against_dense_lexical_neighbors(self):
        (self.root / "service.py").rename(self.root / "000.py")
        text = (self.root / "000.py").read_text(encoding="utf-8")
        for n in range(40):
            (self.root / f"noise{n}.py").write_text(text, encoding="utf-8")

        provider = self.embed()
        with store.connect(self.db) as con, mock.patch.object(engine, "provider_for", return_value=provider):
            from local_context.vectors import pack
            lexical = engine.query(con, "TargetWorker")
            con.execute("UPDATE unit_vectors SET embedding=?", (pack([1., 0.]),))
            for item in lexical["results"]:
                con.execute("UPDATE unit_vectors SET embedding=? WHERE unit_id=(SELECT id FROM units WHERE unit_uid=?)", (pack([0., 1.]), item["unitId"]))
            hybrid = engine.query(con, "TargetWorker", mode="hybrid", vector_engine="stdlib")
        self.assertEqual({r["unitId"] for r in lexical["results"]}, {r["unitId"] for r in hybrid["results"]})

    def test_exact_window_rescue_keeps_all_lexical_hits_above_dense_only(self):
        rows = [{"id": n, "root_id": "r0", "path": "source.py" if n < 6 else f"noise{n}.py", "cell_index": None, "start_line": n + 1, "end_line": n + 1, "lexical_score": 1. if n < 6 else 0.} for n in range(8)]
        rescued = search.preserve_exact_window(rows, rows[3:6])
        selected = {r["id"] for r in assemble.candidate_window(rescued, 5)}
        self.assertTrue({3, 4, 5} <= selected)
        positions = {r["id"]: i for i, r in enumerate(rescued)}
        self.assertLess(max(positions[n] for n in range(6)), min(positions[n] for n in (6, 7)))


class ArgonTests(unittest.TestCase):
    setUp = ReviewTests.setUp
    index = ReviewTests.index
    embed = ReviewTests.embed

    def test_partial_refresh_preserves_inventory_revision_and_full_report(self):
        def git(*args):
            return subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args], cwd=self.root, capture_output=True, check=True).stdout
        git("init", "-q")
        git("add", "service.py")
        git("commit", "-qm", "Initial fixture")
        self.index()
        with store.connect(self.db) as con:
            old = store.library(con)
            roots = old["roots_json"]
            report = con.execute("SELECT last_report_json FROM libraries").fetchone()[0]
        path = self.root / "service.py"
        path.write_text(path.read_text(encoding="utf-8").replace("return 1", "return 2"), encoding="utf-8")
        (self.root / "new.py").write_text("def new_api(): pass\n", encoding="utf-8")
        git("add", "service.py", "new.py")
        git("commit", "-qm", "Changed fixture")
        with store.connect(self.db) as con:
            response = engine.query(con, "TargetWorker")
            self.assertEqual(response["freshness"]["state"], "stale")
            self.assertEqual(store.library(con)["roots_json"], roots)
            self.assertEqual(con.execute("SELECT last_report_json FROM libraries").fetchone()[0], report)
            self.assertEqual(con.execute("SELECT count(*) FROM files WHERE path='new.py'").fetchone()[0], 0)
        freshness.refresh(self.db)
        with store.connect(self.db) as con:
            self.assertNotEqual(store.library(con)["roots_json"], roots)
            self.assertEqual(con.execute("SELECT count(*) FROM files WHERE path='new.py'").fetchone()[0], 1)

    def test_lexical_candidate_refresh_never_embeds_and_manual_refresh_fills_pending(self):
        provider = self.embed()
        path = self.root / "service.py"
        path.write_text(path.read_text(encoding="utf-8").replace("return 1", "return 2"), encoding="utf-8")
        with mock.patch.object(freshness, "provider_for", side_effect=AssertionError("lexical refresh must stay offline")), store.connect(self.db) as con:
            response = engine.query(con, "TargetWorker")
            self.assertIn("return 2", response["results"][0]["text"])
            self.assertEqual(response["coverage"]["embeddingCoverage"], 0.)
            self.assertEqual(con.execute("SELECT embedding_status FROM files").fetchone()[0], "pending")
            self.assertEqual(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 0)
        with mock.patch.object(freshness, "provider_for", return_value=provider):
            freshness.refresh(self.db)
        with store.connect(self.db) as con:
            self.assertEqual(engine.embedding_coverage(con, store.library(con)), 1.)

    def test_partial_refresh_removes_symlink_candidate_without_global_file_scan(self):
        self.index()
        path = self.root / "service.py"
        path.unlink()
        outside = self.base / "outside.py"
        outside.write_text("def outside(): pass\n", encoding="utf-8")
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable")
        traces = []
        original_connect = freshness.sqlite3.connect
        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            connection.set_trace_callback(traces.append)
            return connection
        with mock.patch.object(freshness.sqlite3, "connect", side_effect=connect):
            freshness.refresh(self.db, candidate_paths={("r0", "service.py")})
        deletion_probes = [statement for statement in traces if "SELECT id,root_id,path FROM files" in statement]
        self.assertTrue(deletion_probes)
        self.assertTrue(all("AND root_id=" in statement and "AND path=" in statement for statement in deletion_probes))
        with store.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM files").fetchone()[0], 0)

    def test_multiline_signature_docstring_secret_cannot_leak_header_prefix(self):
        source = 'def TargetWorker(\n    first,\n    second,\n):\n    """' + "description " * 15 + "ghp_" + "A" * 36 + '"""\n' + "    work = 1\n" * 50
        (self.root / "service.py").write_text(source, encoding="utf-8")
        self.index(chunk_chars=128)
        with store.connect(self.db) as con:
            for row in con.execute("SELECT header_json,description,text FROM units"):
                self.assertNotIn("ghp_", " ".join(str(v or "") for v in row))
            self.assertGreater(con.execute("SELECT count(*) FROM units WHERE redacted=1").fetchone()[0], 0)

    def test_braceless_prototypes_and_sql_siblings_have_bounded_spans(self):
        java = "interface Service {\n  public void first();\n  public void second();\n}\nclass Other {\n}\n"
        definitions = chunk.generic_definitions(java, "java")
        self.assertEqual([(d.name, d.start, d.end) for d in definitions if d.name in {"first", "second"}], [("first", 2, 2), ("second", 3, 3)])
        sql = "CREATE VIEW first AS SELECT 1;\nCREATE VIEW second AS SELECT 2;\n"
        self.assertEqual([d.end for d in chunk.generic_definitions(sql, "sql")], [1, 2])
        procedures = "CREATE PROCEDURE first AS\nBEGIN\n SELECT 1;\n SELECT 2;\nEND;\nCREATE PROCEDURE second AS\nBEGIN\n SELECT 3;\nEND;\n"
        self.assertEqual([d.end for d in chunk.generic_definitions(procedures, "sql")], [5, 9])

    def test_index_preserves_embedding_config_until_explicit_disable(self):
        self.embed()
        with mock.patch.object(freshness, "provider_for", side_effect=AssertionError("unchanged provider")):
            self.index(title="Updated title")
        with store.connect(self.db) as con:
            self.assertEqual(json.loads(store.library(con)["embedding_json"])["config"]["provider"], "fake")
            self.assertGreater(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 0)
        self.index(embed_provider="none")
        with store.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 0)

    def test_explicit_endpoint_does_not_inherit_other_endpoint_credential(self):
        with mock.patch.dict(os.environ, {"LEGACY_EMBED_PROVIDER":"openai-compatible", "LEGACY_EMBED_BASE_URL":"https://remote.example/v1", "LEGACY_EMBED_API_KEY_ENV":"PRIVATE_FIXTURE_KEY"}):
            config = freshness.embedding_config(embed_provider="openai-compatible", embed_base_url="http://127.0.0.1:1234/v1", embed_model="fixture")
        self.assertIsNone(config["api_key_env"])

    def test_split_notebook_secret_is_withheld_by_raw_range_expand(self):
        source = ["ghp_" + "A" * 15, "A" * 21]
        (self.root / "lesson.ipynb").write_text(json.dumps({"cells":[{"cell_type":"code", "source":source}]}), encoding="utf-8")
        self.index()
        with store.connect(self.db) as con, self.assertRaisesRegex(RetrievalError, "Secret-bearing"):
            engine.expand(con, root_id="r0", path="lesson.ipynb", start_line=1, end_line=1)

    def test_config_window_header_has_separator_and_nearby_section(self):
        text = "[alpha]\n" + "x" * 180 + "\n[beta]\n" + "y" * 180 + "\n"
        units, _ = chunk.code_units(text, "settings.ini", "ini", target=128, kind="config")
        self.assertTrue(all(u.header.startswith("settings.ini\n") for u in units))
        self.assertTrue(any("[beta]" in u.header for u in units))

    def test_code_txt_build_inputs_keep_code_provenance_and_rst_is_detected(self):
        (self.root / "requirements.txt").write_text("fixture==1\n", encoding="utf-8")
        (self.root / "manual.txt").write_text("Example\n=======\n\nUse this API.\n", encoding="utf-8")
        self.index()
        with store.connect(self.db) as con:
            self.assertEqual(tuple(con.execute("SELECT kind,language FROM files WHERE path='requirements.txt'").fetchone()), ("code", "text"))
            self.assertEqual(tuple(con.execute("SELECT kind,format FROM files WHERE path='manual.txt'").fetchone()), ("docs", "rst"))

    def test_non_utf8_ignore_comments_and_scoped_include_pruning(self):
        (self.root / ".gitignore").write_bytes(b"# legacy comment \xa3\nignored.py\n")
        (self.root / "ignored.py").write_text("def ignored(): pass\n", encoding="utf-8")
        generated = self.root / "generated"
        generated.mkdir()
        (generated / "chosen.py").write_text("def chosen(): pass\n", encoding="utf-8")
        modules = self.root / "node_modules"
        modules.mkdir()
        (modules / "hidden.py").write_text("def hidden(): pass\n", encoding="utf-8")
        self.index(includes=["generated/chosen.py"])
        with store.connect(self.db) as con:
            paths = {r[0] for r in con.execute("SELECT path FROM files")}
            self.assertIn("generated/chosen.py", paths)
            self.assertNotIn("ignored.py", paths)
            self.assertNotIn("node_modules/hidden.py", paths)

    def test_unreadable_directory_is_reported_without_losing_other_files(self):
        blocked = self.root / "blocked"
        blocked.mkdir()
        original = discover.os.scandir
        def scan(path):
            if Path(path) == blocked:
                raise PermissionError("fixture")
            return original(path)
        with mock.patch.object(discover.os, "scandir", side_effect=scan):
            report = self.index()
        self.assertEqual(report["files"], 1)
        self.assertIn("blocked", report["discovery"]["unreadableDirectories"])

    def test_prose_capitals_do_not_anchor_lowercase_verbs(self):
        (self.root / "verbs.py").write_text("def find(): pass\ndef check(): pass\ndef dispatch(): pass\n", encoding="utf-8")
        self.index()
        with store.connect(self.db) as con:
            lib = store.library(con)
            for question in ("Find where retry is configured", "Check how validation works"):
                rows, _ = search.candidates(con, lib, question)
                self.assertFalse(any("symbol" in row["channels"] for row in rows))
            rows, _ = search.candidates(con, lib, "Where is `find` defined?")
            self.assertTrue(any("symbol" in row["channels"] for row in rows))
            rows, _ = search.candidates(con, lib, "Trace the Dispatch menu action")
            self.assertTrue(any("symbol" in row["channels"] for row in rows))
            traces = []
            con.set_trace_callback(traces.append)
            search.candidates(con, lib, "Where is `find` defined?")
            anchors = [statement for statement in traces if "u.title=" in statement]
            self.assertTrue(anchors)
            self.assertTrue(all("u.file_id IN" in statement for statement in anchors))

    def test_small_outer_definition_keeps_nested_helper_and_metadata(self):
        text = 'def outer():\n    """Outer contract."""\n    before = 1\n    def inner():\n        """Inner contract."""\n        return 2\n    return inner() + before\n'
        units, _ = chunk.code_units(text, "nested.py", "python")
        self.assertEqual(len(units), 1)
        self.assertEqual((units[0].start, units[0].end), (1, 7))
        self.assertEqual({d.name for d in units[0].definitions}, {"outer", "inner"})
        self.assertIn("Inner contract", units[0].header)

    def test_explicit_utf16_decodes_short_and_non_latin_files(self):
        for name,text in (("short.txt", "foo"), ("nonlatin.txt", "中文中文中文\n")):
            (self.root / name).write_bytes(text.encode("utf-16-le"))
            self.assertEqual(decode.read_source(self.root, name, encodings=["utf-16-le"]).text, text)

    def test_exclusion_brackets_are_literal_and_globs_are_rejected(self):
        self.assertTrue(discover.matches("pages/[id].tsx", ["[id].tsx"]))
        self.assertFalse(discover.matches("pages/i.tsx", ["[id].tsx"]))
        with self.assertRaisesRegex(RetrievalError, "Wildcards"):
            discover.normalize_excludes(["*.py"])

    def test_path_channel_deduplicates_caps_and_ignores_sentence_periods(self):
        self.index()
        with store.connect(self.db) as con:
            traces = []
            con.set_trace_callback(traces.append)
            search.candidates(con, store.library(con), "Where configured. How does backoff work.")
            self.assertFalse(any("SELECT u.id,f.path" in statement for statement in traces))
            traces.clear()
            search.candidates(con, store.library(con), " ".join(["service.py"] * 100))
            self.assertEqual(sum("SELECT u.id,f.path" in statement for statement in traces), 1)

    def test_hook_bootstrap_outside_project_exits_cleanly(self):
        import setup_context7
        process = subprocess.run([sys.executable, "-c", setup_context7.bootstrap("context7_refresh_hook.py")], cwd=self.base, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(process.stderr)

    def test_setup_assets_are_read_explicitly_as_utf8(self):
        import setup_context7
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.parent == setup_context7.ASSETS:
                self.assertEqual(kwargs.get("encoding"), "utf-8")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "read_text", read), mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(setup_context7.main([str(self.root), "--library-id", "/local/setup", "--dry-run"]), 0)

    def test_git_subtree_trigger_path_is_canonical(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        nested = self.root / "nested"
        nested.mkdir()
        root = discover.roots_for(nested, [])[0]
        self.assertEqual(root.index_path, str(Path(root.index_path).resolve()))

    def test_lexical_symbol_option_is_documented_compatibility_alias(self):
        self.index()
        with store.connect(self.db) as con:
            plain = engine.query(con, "TargetWorker")
            alias = engine.query(con, "TargetWorker", rerank="lexical-symbol")
            self.assertEqual([r["unitId"] for r in plain["results"]], [r["unitId"] for r in alias["results"]])

    def test_old_chunker_fingerprint_rebuilds_unchanged_source_on_refresh(self):
        self.index()
        with store.connect(self.db) as con:
            from local_context.units import canonical, digest
            previous = json.loads(store.library(con)["parser_json"])
            current_revision = previous["chunker_revision"]
            previous['chunker_revision'] = current_revision - 1
            con.execute("UPDATE files SET parser_fingerprint=?", (digest(canonical(previous).encode()),))
            con.execute("UPDATE libraries SET parser_json=?", (canonical(previous),))
        result = freshness.refresh(self.db)
        self.assertEqual(result["changed"], 1)
        with store.connect(self.db) as con:
            self.assertEqual(json.loads(store.library(con)["parser_json"])["chunker_revision"], current_revision)


if __name__ == "__main__":
    unittest.main()
