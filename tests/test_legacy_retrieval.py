"""Focused retrieval tests, runnable with python -m unittest discover -s tests."""

import importlib.util
import json
import math
import os
from pathlib import Path
import random
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


SCRIPT = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts/context7_backend.py"
spec = importlib.util.spec_from_file_location("local_retrieval", SCRIPT)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        git_environment = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        git_environment.start()
        self.addCleanup(git_environment.stop)
        base = Path(self.tmp.name).resolve()
        self.root = base / "source"
        self.docs = base / "docs"
        self.root.mkdir()
        self.docs.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src/service.py").write_text("class InvoiceMaker:\n    def create_invoice(self):\n        return 'invoice total'\n", encoding="utf-8", newline="\n")
        (self.docs / "guide.md").write_text("# Billing guide\nCall InvoiceMaker to create a customer invoice.\n", encoding="utf-8", newline="\n")
        (self.root / ".env").write_text("SECRET_SHOULD_NEVER_APPEAR=xyz\n", encoding="utf-8", newline="\n")
        (self.root / "outside.py").symlink_to(self.docs / "guide.md")
        (self.root / "linked-docs").symlink_to(self.docs, target_is_directory=True)
        self.db = base / "index.sqlite"

    def index(self):
        return backend.index(self.root, self.db, "/local/billing", self.docs, None, None)

    def require_sqlite_vec(self):
        with sqlite3.connect(":memory:", factory=backend.ClosingConnection) as con:
            try:
                backend.load_sqlite_vec(con)
            except backend.VectorAdapterUnavailable as error:
                if os.environ.get("LEGACY_REQUIRE_SQLITE_VEC") == "1":
                    self.fail(f"Required actual sqlite-vec acceptance unavailable: {error}")
                self.skipTest(str(error))

    def test_inference_environment_preserves_os_paths_and_excludes_provider_settings(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        supplied = {"PATH": "local-toolchain", "SystemRoot": "C:\\Windows", "WINDIR": "C:\\Windows", "TEMP": str(cache), "TMP": str(cache), "NODE_OPTIONS": "--inspect", "HF_TOKEN": "dummy-test-value", "OPENAI_API_KEY": "dummy-test-value", "ANTHROPIC_API_KEY": "dummy-test-value"}
        with mock.patch.dict(os.environ, supplied, clear=True):
            offline = backend.inference_environment(cache, download=False)
            online = backend.inference_environment(cache, download=True)
        self.assertEqual({key.upper() for key in offline}, {"PATH", "HOME", "HF_HUB_OFFLINE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"})
        self.assertEqual(offline["HOME"], str(cache))
        self.assertEqual(offline["HF_HUB_OFFLINE"], "1")
        self.assertEqual(online["HF_HUB_OFFLINE"], "0")
        for key in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
            self.assertEqual(offline[key], supplied[key])

    def test_runtime_without_sqlite_extension_api_falls_back_only_when_requested(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        def fake_batches(batches, *_args, **_kwargs):
            for batch in batches:
                yield [[1.0, 0.0] for _ in batch]
        with mock.patch.object(backend, "embedding_batches", side_effect=fake_batches):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        class NoExtensionAPI:
            def __init__(self, connection):
                self.connection = connection
            def __getattr__(self, name):
                if name in ("enable_load_extension", "load_extension"):
                    raise AttributeError(name)
                return getattr(self.connection, name)
        class InstalledPackage:
            @staticmethod
            def load(_connection):
                raise AssertionError("An unavailable runtime must be rejected before loading")
        with backend.connect(self.db) as con, mock.patch.dict(sys.modules, {"sqlite_vec": InstalledPackage}), mock.patch.object(backend, "embeddings", return_value=[[1.0, 0.0]]):
            limited = NoExtensionAPI(con)
            self.assertTrue(backend.query(limited, "invoice")["results"])
            exact = backend.query(limited, "invoice", mode="semantic", vector_engine="stdlib")
            automatic = backend.query(limited, "invoice", mode="semantic", vector_engine="auto")
            self.assertEqual(automatic["vectorEngine"], "stdlib")
            self.assertEqual(automatic["results"], exact["results"])
            with self.assertRaisesRegex(backend.VectorAdapterUnavailable, "runtime cannot load extensions.*Homebrew"):
                backend.query(limited, "invoice", mode="semantic", vector_engine="sqlite-vec")
            def cannot_enable(_enabled):
                raise sqlite3.OperationalError("extension loading disabled by build")
            limited.enable_load_extension = cannot_enable
            limited.load_extension = lambda _path: None
            with self.assertRaisesRegex(backend.VectorAdapterUnavailable, "cannot enable extension loading"):
                backend.load_sqlite_vec(limited)

    def test_broken_installed_sqlite_adapter_is_not_an_auto_fallback(self):
        class LoadableConnection:
            enabled = False
            def enable_load_extension(self, enabled):
                self.enabled = enabled
            def load_extension(self, _path):
                pass
        class BrokenPackage:
            @staticmethod
            def load(_connection):
                raise sqlite3.OperationalError("incompatible extension architecture")
        connection = LoadableConnection()
        with mock.patch.dict(sys.modules, {"sqlite_vec": BrokenPackage}):
            with self.assertRaisesRegex(backend.RetrievalError, "Installed sqlite-vec adapter failed to load") as raised:
                backend.load_sqlite_vec(connection)
            self.assertNotIsInstance(raised.exception, backend.VectorAdapterUnavailable)
        self.assertFalse(connection.enabled)

    def test_required_native_acceptance_fails_instead_of_skipping_missing_capability(self):
        with mock.patch.dict(os.environ, {"LEGACY_REQUIRE_SQLITE_VEC": "1"}), mock.patch.dict(sys.modules, {"sqlite_vec": None}):
            with self.assertRaisesRegex(self.failureException, "Required actual sqlite-vec acceptance unavailable"):
                self.require_sqlite_vec()
        with mock.patch.dict(os.environ, {"LEGACY_REQUIRE_SQLITE_VEC": "1"}), mock.patch.object(backend, "load_sqlite_vec", side_effect=backend.VectorAdapterUnavailable("SQLite runtime cannot load extensions")):
            with self.assertRaisesRegex(self.failureException, "runtime cannot load extensions"):
                self.require_sqlite_vec()
        with mock.patch.dict(os.environ, {"LEGACY_REQUIRE_SQLITE_VEC": "0"}), mock.patch.dict(sys.modules, {"sqlite_vec": None}):
            with self.assertRaisesRegex(unittest.SkipTest, "sqlite-vec 0.1.9 is required"):
                self.require_sqlite_vec()

    def test_whole_line_chunking_covers_source_without_gaps_or_duplicate_tail(self):
        rng = random.Random(20261007)
        for cap in (128, 400, 1200):
            lines = [f"line_{i}_" + "x" * rng.choice((0, 12, 90, 800, 3000)) for i in range(80)]
            text = "\r\n".join(lines) + "\r\n"
            rows = list(backend.chunks_for(text, cap))
            reconstructed = {}
            previous_start, previous_end = 0, 0
            for start, end, body, _ in rows:
                self.assertGreater(start, previous_start)
                self.assertGreater(end, previous_end)
                self.assertLessEqual(start, previous_end + 1)
                self.assertLessEqual(previous_end - start + 1, 8)
                self.assertLessEqual(end - start + 1, 48)
                self.assertEqual(body, "\n".join(lines[start - 1:end]))
                if len(body) > cap:
                    self.assertEqual(start, end)
                    self.assertGreater(len(lines[start - 1]), cap)
                for position in range(start, end + 1):
                    reconstructed[position] = lines[position - 1]
                previous_start, previous_end = start, end
            self.assertEqual([reconstructed[i] for i in range(1, len(lines) + 1)], lines)
            self.assertEqual(rows, list(backend.chunks_for(text, cap)))
        self.assertEqual(list(backend.chunks_for("")), [])
        self.assertEqual(len(list(backend.chunks_for("short\n" * 41))), 1)
        special = "first\fform feed stays here\r\nsecond\r\n"
        self.assertEqual(list(backend.chunks_for(special))[0][0:3], (1, 2, "first\fform feed stays here\nsecond"))

    def test_chunking_invalid_bounds_and_config_rebuilds_vectors(self):
        for invalid in (127, 12001, True, 128.0, "1200"):
            with self.assertRaisesRegex(backend.RetrievalError, "--chunk-chars"):
                list(backend.chunks_for("source", invalid))
            with self.assertRaisesRegex(backend.RetrievalError, "--chunk-chars"):
                backend.index(self.root, self.db, "/local/billing", None, None, None, chunk_chars=invalid)
        (self.root / "src/service.py").write_text("\n".join(f"const source_{i} = '" + "x" * 60 + "';" for i in range(70)), encoding="utf-8", newline="\n")
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        calls = []
        def fake_batches(batches, *_args, **_kwargs):
            calls.extend(body for batch in batches for body in batch)
            for batch in batches:
                yield [[1.0, 0.0] for _ in batch]
        with mock.patch.object(backend, "embedding_batches", side_effect=fake_batches):
            initial = backend.index(self.root, self.db, "/local/billing", None, backend.DEFAULT_MODEL, cache, runtime, chunk_chars=1200)
            self.assertTrue(calls)
            calls.clear()
            unchanged = backend.index(self.root, self.db, "/local/billing", None, backend.DEFAULT_MODEL, cache, runtime, chunk_chars=1200)
            self.assertEqual(unchanged["changed"], 0)
            self.assertEqual(calls, [])
            updated = backend.index(self.root, self.db, "/local/billing", None, backend.DEFAULT_MODEL, cache, runtime, chunk_chars=400)
            self.assertEqual(updated["changed"], 1)
            self.assertGreater(updated["chunks"], initial["chunks"])
            self.assertTrue(calls)
        with backend.connect(self.db) as con:
            meta = backend.metadata(con)
            self.assertEqual(meta["chunk_chars"], "400")
            self.assertEqual(meta["index_version"], "7")
            self.assertEqual(con.execute("SELECT count(*) FROM chunks").fetchone()[0], con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0])

    def test_oversized_whole_lines_are_reported_and_embedding_preflight_rolls_back(self):
        self.index()
        with backend.connect(self.db) as con:
            old_meta = backend.metadata(con)
            old_chunks = con.execute("SELECT * FROM chunks ORDER BY id").fetchall()
        (self.root / "src/service.py").write_text("class HugeLine: " + "x" * 13000 + "\n", encoding="utf-8", newline="\n")
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with mock.patch.object(backend, "embedding_batches", side_effect=AssertionError("inference must not run")), mock.patch.object(backend, "reranker_scores", side_effect=AssertionError("inference must not run")):
            with self.assertRaisesRegex(backend.RetrievalError, "code:src/service.py:L1-L1.*lexical"):
                backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, reranker_model=backend.DEFAULT_RERANKER)
        with backend.connect(self.db) as con:
            self.assertEqual(backend.metadata(con), old_meta)
            self.assertEqual(con.execute("SELECT * FROM chunks ORDER BY id").fetchall(), old_chunks)
        lexical = self.index()
        self.assertEqual(lexical["oversizedChunks"], 1)
        self.assertEqual(lexical["chunkChars"], 1200)
        with backend.connect(self.db) as con:
            result = backend.query(con, "HugeLine")
            self.assertEqual(result["oversizedChunks"], 1)
            self.assertEqual(result["results"][0]["text"], "class HugeLine: " + "x" * 13000)
        # JS text.length counts UTF-16 units. Preflight must match that helper
        # limit even when a single line has fewer Python Unicode characters.
        (self.root / "src/service.py").write_text("😀" * 6001 + "\n", encoding="utf-8", newline="\n")
        with mock.patch.object(backend, "embedding_batches", side_effect=AssertionError("inference must not run")):
            with self.assertRaisesRegex(backend.RetrievalError, "UTF-16"):
                backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)

    def test_configuration_files_and_candidate_limits(self):
        (self.root / "handler.properties").write_text("handler.class=InvoiceMaker\n", encoding="utf-8", newline="\n")
        self.index()
        with backend.connect(self.db) as con:
            self.assertTrue(any(x["source"]["path"] == "handler.properties" for x in backend.query(con, "handler.class")["results"]))
        with mock.patch.object(backend, "MAX_SOURCE_CANDIDATES", 1):
            with self.assertRaisesRegex(backend.RetrievalError, "Candidate limit"):
                self.index()

    def test_invalid_server_default_fails_before_binding(self):
        self.index()
        with self.assertRaisesRegex(backend.RetrievalError, "Semantic default"):
            backend.serve(self.db, "127.0.0.1", 0, "hybrid")
        with self.assertRaisesRegex(backend.RetrievalError, "Cross-encoder default"):
            backend.serve(self.db, "127.0.0.1", 0, default_rerank="cross-encoder")

    def test_provenance_and_separate_docs(self):
        meta = self.index()
        self.assertEqual(meta["files"], 2)
        with backend.connect(self.db) as con:
            code = backend.query(con, "InvoiceMaker")
            self.assertTrue(code["results"])
            first = code["results"][0]
            self.assertEqual(first["source"]["kind"], "code")
            self.assertEqual(first["source"]["path"], "src/service.py")
            self.assertEqual(first["source"]["startLine"], 1)
            self.assertEqual(first["source"]["fileSha256"], backend.digest((self.root / "src/service.py").read_bytes()))
            self.assertEqual(first["source"]["corpusId"], meta["corpusId"])
            result = backend.query(con, "Billing guide")
            self.assertTrue(any(r["source"]["kind"] == "docs" for r in result["results"]))
            self.assertFalse(any("SECRET_SHOULD" in r["text"] for r in result["results"]))

    def test_incremental_change_delete_and_freshness(self):
        first = self.index()
        unchanged = self.index()
        self.assertEqual(unchanged["changed"], 0)
        self.assertEqual(first["corpusId"], unchanged["corpusId"])
        source = self.root / "src/service.py"
        source.write_text("class RevisedInvoiceMaker:\n    pass\n", encoding="utf-8", newline="\n")
        with backend.connect(self.db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "changed"):
                backend.query(con, "invoice")
        self.assertEqual(self.index()["changed"], 1)
        source.unlink()
        with backend.connect(self.db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "disappeared"):
                backend.query(con, "invoice")
        self.assertEqual(self.index()["deleted"], 1)

    def test_new_file_and_negative_query(self):
        self.index()
        with backend.connect(self.db) as con:
            self.assertEqual(backend.query(con, "NeverExistingMagicType")["results"], [])
        (self.root / "new.py").write_text("def new_function(): pass\n", encoding="utf-8", newline="\n")
        with backend.connect(self.db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "appeared"):
                backend.query(con, "invoice")

    def test_gitignore_and_revision_change(self):
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        (self.root / ".gitignore").write_text("ignored.py\n", encoding="utf-8", newline="\n")
        (self.root / "ignored.py").write_text("SECRET_SHOULD_NOT_INDEX\n", encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(self.root), "add", "src/service.py", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"], check=True)
        first = self.index()
        self.assertEqual(first["files"], 2)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "revision"], check=True)
        with backend.connect(self.db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "revision changed"):
                backend.query(con, "invoice")
        second = self.index()
        self.assertEqual(second["changed"], 0)
        self.assertNotEqual(first["corpusId"], second["corpusId"])

    def test_module_root_keeps_git_revision_and_parent_ignores(self):
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        (self.root / ".gitignore").write_text("src/ignored.py\n", encoding="utf-8", newline="\n")
        (self.root / "src/ignored.py").write_text("class ShouldRemainIgnored: pass\n", encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(self.root), "add", ".gitignore", "src/service.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"], check=True)
        result = backend.index(self.root / "src", self.db, "/local/billing", None, None, None)
        expected_revision = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(result["revision"], expected_revision)
        self.assertEqual(result["files"], 1)
        with backend.connect(self.db) as con:
            self.assertEqual(backend.query(con, "ShouldRemainIgnored")["results"], [])
            found = backend.query(con, "InvoiceMaker")
            self.assertEqual(found["results"][0]["source"]["path"], "service.py")
            self.assertEqual(found["results"][0]["source"]["revision"], expected_revision)
        (self.root / "src/ignored.py").write_text("class ChangedIgnored: pass\n", encoding="utf-8", newline="\n")
        with backend.connect(self.db) as con:
            self.assertTrue(backend.query(con, "InvoiceMaker")["results"])

    def test_non_git_discovery_failure_preserves_index(self):
        self.index()
        with backend.connect(self.db) as con:
            previous = backend.metadata(con)
        with mock.patch("repo_files.MAX_DISCOVERY_ENTRIES", 1):
            with self.assertRaisesRegex(backend.RetrievalError, "discovery entry limit"):
                self.index()
        with backend.connect(self.db) as con:
            self.assertEqual(backend.metadata(con), previous)
            self.assertTrue(backend.query(con, "InvoiceMaker")["results"])

    def test_markdown_in_repo_has_doc_provenance(self):
        (self.root / "README.md").write_text("# Architecture\nThe billing operation runs from this entry point.\n", encoding="utf-8", newline="\n")
        self.index()
        with backend.connect(self.db) as con:
            result = backend.query(con, "Architecture")
            self.assertEqual(result["results"][0]["source"]["kind"], "repo-docs")
            self.assertEqual(len(backend.context_payload(result)["infoSnippets"]), 1)

    def test_caps_and_wrong_mode(self):
        self.index()
        with backend.connect(self.db) as con:
            for question in ("", "x" * 501):
                with self.assertRaises(backend.RetrievalError):
                    backend.query(con, question)
            with self.assertRaisesRegex(backend.RetrievalError, "Limit"):
                backend.query(con, "invoice", limit=11)
            with self.assertRaisesRegex(backend.RetrievalError, "requires"):
                backend.query(con, "invoice", mode="semantic")
            with self.assertRaisesRegex(backend.RetrievalError, "requires an index"):
                backend.query(con, "invoice", rerank="cross-encoder")
        with self.assertRaisesRegex(backend.RetrievalError, "outside"):
            backend.index(self.root, self.root / "bad.sqlite", "/local/billing", None, None, None)

    def test_reranker_configuration_and_lexical_only_candidates(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with self.assertRaisesRegex(backend.RetrievalError, "--reranker-revision"):
            backend.index(self.root, self.db, "/local/billing", self.docs, None, cache, runtime, reranker_model="custom/model")
        with self.assertRaisesRegex(backend.RetrievalError, "requires --reranker-model"):
            backend.index(self.root, self.db, "/local/billing", self.docs, None, cache, runtime, reranker_revision="a" * 40)
        with self.assertRaisesRegex(backend.RetrievalError, "outside"):
            backend.index(self.root, self.db, "/local/billing", self.docs, None, self.root / "cache", runtime, reranker_model=backend.DEFAULT_RERANKER)
        (self.root / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with self.assertRaisesRegex(backend.RetrievalError, "outside"):
            backend.index(self.root, self.db, "/local/billing", self.docs, None, cache, self.root, reranker_model=backend.DEFAULT_RERANKER)
        with self.assertRaisesRegex(backend.RetrievalError, "--embedding-runtime"):
            backend.index(self.root, self.db, "/local/billing", self.docs, None, cache, None, reranker_model=backend.DEFAULT_RERANKER)
        calls = []
        def fake_scores(question, passages, *_args, **kwargs):
            calls.append((question, passages, kwargs["download"]))
            return [float(len(text)) for text in passages]
        model_files = cache / backend.DEFAULT_RERANKER / backend.DEFAULT_RERANKER_REVISION
        (model_files / "onnx").mkdir(parents=True)
        for name in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx"):
            (model_files / name).touch()
        with mock.patch.object(backend, "reranker_scores", side_effect=fake_scores):
            result = backend.index(self.root, self.db, "/local/billing", self.docs, None, cache, runtime, reranker_model=backend.DEFAULT_RERANKER)
            self.assertEqual(result["rerankerRevision"], backend.DEFAULT_RERANKER_REVISION)
            with backend.connect(self.db) as con:
                self.assertEqual(backend.metadata(con)["reranker_model"], backend.DEFAULT_RERANKER)
                found = backend.query(con, "InvoiceMaker", rerank="cross-encoder")
                self.assertEqual(found["results"][0]["source"]["path"], "src/service.py")
                self.assertIsInstance(found["results"][0]["rerankScore"], float)
                self.assertEqual(backend.query(con, "ImaginaryGovernmentFramework", rerank="cross-encoder")["results"], [])
        self.assertEqual([call[2] for call in calls], [True, False])
        (self.root / "src/service.py").write_text("class Changed: pass\n", encoding="utf-8", newline="\n")
        with backend.connect(self.db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "changed"):
                backend.query(con, "InvoiceMaker", rerank="cross-encoder")
        (self.root / "src/service.py").unlink()
        with backend.connect(self.db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "disappeared"):
                backend.query(con, "InvoiceMaker", rerank="cross-encoder")

    def test_reranker_rejects_malformed_helper_output_and_cleans_up(self):
        helper = Path(self.tmp.name).resolve() / "fake-reranker.mjs"
        helper.write_text("import { createInterface } from 'node:readline';\nfor await (const line of createInterface({input: process.stdin})) console.log('{\"wrong\": 1}');\n", encoding="utf-8", newline="\n")
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        launched = []
        original = subprocess.Popen
        def capture(*args, **kwargs):
            proc = original(*args, **kwargs)
            launched.append(proc)
            return proc
        with mock.patch.object(backend, "RERANK_HELPER", helper), mock.patch.object(subprocess, "Popen", side_effect=capture):
            with self.assertRaisesRegex(backend.RetrievalError, "Invalid reranker output"):
                backend.reranker_scores("query", ["passage"], backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, cache, Path(self.tmp.name).resolve(), download=False)
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].poll())
        helper.write_text("import { createInterface } from 'node:readline';\nfor await (const line of createInterface({input: process.stdin})) { const request=JSON.parse(line); if(request.passages.length>8) process.exit(3); console.log(JSON.stringify(request.passages.map(()=>1))); }\n", encoding="utf-8", newline="\n")
        with mock.patch.object(backend, "RERANK_HELPER", helper):
            scores = backend.reranker_scores("query", ["passage"] * 9, backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, cache, Path(self.tmp.name).resolve(), download=False)
            self.assertEqual(scores, [1.0] * 9)
            with self.assertRaisesRegex(backend.RetrievalError, "candidate limit"):
                backend.reranker_scores("query", ["passage"] * 61, backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, cache, Path(self.tmp.name).resolve(), download=False)

    def test_reranker_rejects_wrong_classification_dimension(self):
        runtime = Path(self.tmp.name).resolve() / "fake-runtime"
        package = runtime / "node_modules/@huggingface/transformers"
        (package / "src").mkdir(parents=True)
        (package / "package.json").write_text('{"type":"module"}', encoding="utf-8", newline="\n")
        (package / "src/transformers.js").write_text(
            "export const env = {};\n"
            "export const AutoTokenizer = { from_pretrained: async () => () => ({}) };\n"
            "export const AutoModelForSequenceClassification = { from_pretrained: async () => "
            "Object.assign(async () => ({ logits: { dims: [1, 2], data: [1, 2] } }), "
            "{ config: { num_labels: 2 } }) };\n"
        , encoding="utf-8", newline="\n")
        result = subprocess.run(["node", str(backend.RERANK_HELPER), "custom/model", "a" * 40, str(Path(self.tmp.name).resolve() / "cache"), str(runtime), "offline"], input="", text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("single-logit", result.stderr)
        module = package / "src/transformers.js"
        module.write_text(module.read_text(encoding="utf-8").replace("num_labels: 2", "num_labels: 1"), encoding="utf-8", newline="\n")
        result = subprocess.run(["node", str(backend.RERANK_HELPER), "custom/model", "a" * 40, str(Path(self.tmp.name).resolve() / "cache"), str(runtime), "offline"], input=json.dumps({"query": "q", "passages": ["p"]}) + "\n", text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one scalar logit", result.stderr)

    def test_large_and_non_utf8_files_are_reported(self):
        (self.root / "large.py").write_bytes(b"x" * (backend.MAX_FILE_BYTES + 1))
        (self.root / "binary.py").write_bytes(b"\xff\xfe")
        result = self.index()
        self.assertEqual(result["skippedCount"], 2)
        self.assertEqual({entry["path"] for entry in result["skipped"]}, {"large.py", "binary.py"})

    def test_parent_symlink_and_git_fsmonitor_are_not_used(self):
        outside = Path(self.tmp.name).resolve() / "outside"
        outside.mkdir()
        (outside / "stolen.py").write_text("PRIVATE_SOURCE_MARKER\n", encoding="utf-8", newline="\n")
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        marker = Path(self.tmp.name).resolve() / "fsmonitor-ran"
        hook = Path(self.tmp.name).resolve() / "fsmonitor.sh"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)
        subprocess.run(["git", "-C", str(self.root), "config", "core.fsmonitor", str(hook)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "src/service.py"], check=True)
        marker.unlink(missing_ok=True)
        (self.root / "src/service.py").unlink()
        (self.root / "src").rmdir()
        (self.root / "src").symlink_to(outside, target_is_directory=True)
        (outside / "service.py").write_text("PRIVATE_SOURCE_MARKER\n", encoding="utf-8", newline="\n")
        result = self.index()
        self.assertEqual(result["files"], 1)
        self.assertFalse(marker.exists())
        with backend.connect(self.db) as con:
            self.assertFalse(any("PRIVATE_SOURCE_MARKER" in row[0] for row in con.execute("SELECT body FROM chunks")))

    def test_vector_engines_agree_and_failed_update_rolls_back(self):
        self.require_sqlite_vec()
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        def fake_batches(batches, *_args, **_kwargs):
            for batch in batches:
                yield [[1.0, 0.0] if "InvoiceMaker" in text else [0.0, 1.0] for text in batch]
        results = []
        for engine in ("stdlib", "sqlite-vec"):
            db = Path(self.tmp.name).resolve() / f"{engine}.sqlite"
            with mock.patch.object(backend, "embedding_batches", side_effect=fake_batches):
                backend.index(self.root, db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, vector_engine=engine)
            with mock.patch.object(backend, "embeddings", return_value=[[1.0, 0.0]]):
                with backend.connect(db) as con:
                    result = backend.query(con, "InvoiceMaker", mode="semantic", vector_engine=engine)
                    self.assertEqual(result["vectorEngine"], engine)
                    results.append([(item["source"]["kind"], item["source"]["path"]) for item in result["results"]])
            (self.root / "src/service.py").write_text("class InvoiceMaker:\n    def updated(self): pass\n", encoding="utf-8", newline="\n")
            def fail_batches(*_args, **_kwargs):
                raise backend.RetrievalError("model failed")
                yield []
            with mock.patch.object(backend, "embedding_batches", side_effect=fail_batches):
                with self.assertRaisesRegex(backend.RetrievalError, "model failed"):
                    backend.index(self.root, db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, vector_engine=engine)
            with backend.connect(db) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM chunks").fetchone()[0], 2)
                self.assertEqual(con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0], 2)
            (self.root / "src/service.py").write_text("class InvoiceMaker:\n    def create_invoice(self):\n        return 'invoice total'\n", encoding="utf-8", newline="\n")
            guide = self.docs / "guide.md"
            guide_text = guide.read_text(encoding="utf-8")
            guide.unlink()
            with mock.patch.object(backend, "embedding_batches", side_effect=fake_batches):
                self.assertEqual(backend.index(self.root, db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, vector_engine=engine)["deleted"], 1)
            with backend.connect(db) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM chunks").fetchone()[0], 1)
                self.assertEqual(con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0], 1)
            guide.write_text(guide_text, encoding="utf-8", newline="\n")
            with mock.patch.object(backend, "embedding_batches", side_effect=fake_batches):
                rebuilt = backend.index(self.root, db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, model_revision="a" * 40, vector_engine=engine)
            self.assertEqual(rebuilt["changed"], 2)
            with backend.connect(db) as con:
                self.assertEqual(backend.metadata(con)["model_revision"], "a" * 40)
        self.assertEqual(results[0], results[1])

    def test_sqlite_vec_index_requires_optional_package(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with mock.patch.dict(sys.modules, {"sqlite_vec": None}):
            with self.assertRaisesRegex(backend.RetrievalError, "sqlite-vec 0.1.9 is required"):
                backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, vector_engine="sqlite-vec")

    def test_vector_preference_changes_without_reembedding_or_schema_copy(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with mock.patch.object(backend, "embedding_batches", return_value=iter([[[1.0, 0.0], [0.0, 1.0]]])):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with backend.connect(self.db) as con:
            before = con.execute("SELECT chunk_id,embedding FROM chunk_vectors ORDER BY chunk_id").fetchall()
            self.assertEqual(len(before), 2)
            self.assertNotIn("vector", [row[1] for row in con.execute("PRAGMA table_info(chunks)")])
        with mock.patch.object(backend, "load_sqlite_vec"):
            with mock.patch.object(backend, "embedding_batches", side_effect=AssertionError("unexpected re-embedding")):
                result = backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, vector_engine="sqlite-vec")
        self.assertEqual(result["changed"], 0)
        with backend.connect(self.db) as con:
            self.assertEqual(before, con.execute("SELECT chunk_id,embedding FROM chunk_vectors ORDER BY chunk_id").fetchall())
            self.assertEqual(backend.metadata(con)["vector_engine"], "sqlite-vec")
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec'").fetchone())
            with mock.patch.dict(sys.modules, {"sqlite_vec": None}):
                self.assertEqual(backend.query(con, "invoice")["vectorEngine"], None)
                with mock.patch.object(backend, "embeddings", return_value=[[1.0, 0.0]]):
                    self.assertEqual(backend.query(con, "invoice", mode="semantic", vector_engine="stdlib")["vectorEngine"], "stdlib")
                    self.assertEqual(backend.query(con, "invoice", mode="semantic", vector_engine="auto")["vectorEngine"], "stdlib")
                    with self.assertRaisesRegex(backend.RetrievalError, "sqlite-vec 0.1.9 is required"):
                        backend.query(con, "invoice", mode="semantic")
                    with self.assertRaisesRegex(backend.RetrievalError, "sqlite-vec 0.1.9 is required"):
                        backend.query(con, "invoice", mode="semantic", vector_engine="sqlite-vec")
            with mock.patch.object(backend, "load_sqlite_vec", side_effect=backend.RetrievalError("sqlite-vec 0.1.9 required; found v0.2.0")):
                with self.assertRaisesRegex(backend.RetrievalError, "found v0.2.0"):
                    backend.query(con, "invoice", mode="semantic", vector_engine="auto")

    def test_vector_rows_cascade_and_failed_update_preserves_metadata(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        def batches(batch_groups, *_args, **_kwargs):
            for batch in batch_groups:
                yield [[1.0, 0.0] for _ in batch]
        with mock.patch.object(backend, "embedding_batches", side_effect=batches):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with backend.connect(self.db) as con:
            old_meta = backend.metadata(con)
            old_rows = con.execute("SELECT chunk_id,embedding FROM chunk_vectors ORDER BY chunk_id").fetchall()
        (self.root / "src/service.py").write_text("class ChangedInvoiceMaker: pass\n", encoding="utf-8", newline="\n")
        def fail_after_write(batch_groups, *_args, **_kwargs):
            yield [[1.0, 0.0] for _ in batch_groups[0]]
            raise backend.RetrievalError("second batch failed")
        (self.docs / "extra.md").write_text("Extra source\n", encoding="utf-8", newline="\n")
        with mock.patch.object(backend, "MODEL_BATCH", 1), mock.patch.object(backend, "embedding_batches", side_effect=fail_after_write):
            with self.assertRaisesRegex(backend.RetrievalError, "second batch failed"):
                backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with backend.connect(self.db) as con:
            self.assertEqual(backend.metadata(con), old_meta)
            self.assertEqual(con.execute("SELECT chunk_id,embedding FROM chunk_vectors ORDER BY chunk_id").fetchall(), old_rows)
        with mock.patch.object(backend, "embedding_batches", side_effect=batches):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with backend.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM chunks").fetchone()[0], con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0])
            self.assertEqual(con.execute("SELECT count(*) FROM chunk_vectors v LEFT JOIN chunks c ON c.id=v.chunk_id WHERE c.id IS NULL").fetchone()[0], 0)
        (self.docs / "guide.md").unlink()
        with mock.patch.object(backend, "embedding_batches", side_effect=batches):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with backend.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM chunks").fetchone()[0], con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0])

    def test_model_removal_clears_vector_metadata(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with mock.patch.object(backend, "embedding_batches", return_value=iter([[[1.0, 0.0], [0.0, 1.0]]])):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        self.index()
        with backend.connect(self.db) as con:
            self.assertNotIn("vector_dim", backend.metadata(con))
            self.assertEqual(con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0], 0)

    def test_old_index_reindexes_and_failed_migration_rolls_back_schema(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        runtime = Path(self.tmp.name).resolve() / "runtime"
        (runtime / "node_modules/@huggingface/transformers").mkdir(parents=True)
        with sqlite3.connect(self.db, factory=backend.ClosingConnection) as con:
            con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            con.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY,kind TEXT,path TEXT,start INTEGER,end INTEGER,body TEXT,symbols TEXT,vector BLOB)")
            con.execute("INSERT INTO meta VALUES('index_version','5')")
            for key, value in (("root", str(self.root)), ("docs_root", str(self.docs)), ("library_id", "/local/billing")):
                con.execute("INSERT INTO meta VALUES(?,?)", (key, value))
            con.execute("INSERT INTO chunks VALUES(1,'code','obsolete.py',1,1,'obsolete','',?)", (backend.pack_vector([1.0, 0.0]),))
        def fail_batches(*_args, **_kwargs):
            raise backend.RetrievalError("migration failed")
            yield []
        with mock.patch.object(backend, "embedding_batches", side_effect=fail_batches):
            with self.assertRaisesRegex(backend.RetrievalError, "migration failed"):
                backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with sqlite3.connect(self.db, factory=backend.ClosingConnection) as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()[0], "5")
            self.assertIn("vector", [row[1] for row in con.execute("PRAGMA table_info(chunks)")])
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='chunk_vectors'").fetchone())
        def batches(batch_groups, *_args, **_kwargs):
            for batch in batch_groups:
                yield [[1.0, 0.0] for _ in batch]
        with mock.patch.object(backend, "embedding_batches", side_effect=batches):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        with backend.connect(self.db) as con:
            self.assertEqual(backend.metadata(con)["index_version"], "7")
            self.assertNotIn("vector", [row[1] for row in con.execute("PRAGMA table_info(chunks)")])
            self.assertEqual(con.execute("SELECT count(*) FROM chunks").fetchone()[0], con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0])

    def test_old_vec0_index_requires_package_once_for_reindex(self):
        self.require_sqlite_vec()
        with sqlite3.connect(self.db, factory=backend.ClosingConnection) as con:
            backend.load_sqlite_vec(con)
            con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            con.execute("INSERT INTO meta VALUES('index_version','5')")
            for key, value in (("root", str(self.root)), ("docs_root", str(self.docs)), ("library_id", "/local/billing")):
                con.execute("INSERT INTO meta VALUES(?,?)", (key, value))
            con.execute("CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[2] distance_metric=cosine)")
            con.execute("INSERT INTO chunks_vec(chunk_id,embedding) VALUES(1,?)", (backend.pack_vector([1.0, 0.0]),))
        with mock.patch.dict(sys.modules, {"sqlite_vec": None}):
            with self.assertRaisesRegex(backend.RetrievalError, "use a fresh database path"):
                self.index()
        with sqlite3.connect(self.db, factory=backend.ClosingConnection) as con:
            backend.load_sqlite_vec(con)
            self.assertEqual(con.execute("SELECT count(*) FROM chunks_vec").fetchone()[0], 1)
        self.index()
        with backend.connect(self.db) as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec'").fetchone())
            self.assertEqual(backend.metadata(con)["index_version"], "7")

    def test_empty_and_single_chunk_semantic_scan(self):
        self.require_sqlite_vec()
        with sqlite3.connect(":memory:", factory=backend.ClosingConnection) as con:
            con.row_factory = sqlite3.Row
            backend.setup(con)
            backend.load_sqlite_vec(con)
            with mock.patch.object(backend, "embeddings", return_value=[[1.0, 0.0]]):
                self.assertEqual(backend.semantic(con, "x", "model", "revision", self.root, self.root, 10, "sqlite-vec"), [])
                con.execute("INSERT INTO chunks(kind,path,start,end,body,symbols) VALUES('code','x.py',1,1,'x','')")
                con.execute("INSERT INTO chunk_vectors VALUES(1,?)", (backend.pack_vector([1.0, 0.0]),))
                self.assertEqual(backend.semantic(con, "x", "model", "revision", self.root, self.root, 10, "sqlite-vec"), [(1, 1.0)])
                con.execute("INSERT INTO chunks(kind,path,start,end,body,symbols) VALUES('code','y.py',1,1,'y','')")
                con.execute("INSERT INTO chunk_vectors VALUES(2,?)", (backend.pack_vector([1.0, 0.0]),))
                for engine in ("stdlib", "sqlite-vec"):
                    self.assertEqual([cid for cid, _ in backend.semantic(con, "x", "model", "revision", self.root, self.root, 10, engine)], [1, 2])

    def test_fixed_seed_float64_oracle_matches_both_engines(self):
        self.require_sqlite_vec()
        rng = random.Random(20261007)
        with sqlite3.connect(":memory:", factory=backend.ClosingConnection) as con:
            con.row_factory = sqlite3.Row
            backend.setup(con)
            backend.load_sqlite_vec(con)
            vectors = []
            for cid in range(1, 1001):
                source = [rng.gauss(0, 1) for _ in range(384)]
                blob = backend.pack_vector(source)
                self.assertEqual(len(blob), 384 * 4)
                vector = struct.unpack("<384f", blob)
                self.assertAlmostEqual(math.sumprod(vector, vector), 1.0, delta=1e-3)
                vectors.append(vector)
                con.execute("INSERT INTO chunks(id,kind,path,start,end,body,symbols) VALUES(?,'code','x.py',1,1,'x','')", (cid,))
                con.execute("INSERT INTO chunk_vectors VALUES(?,?)", (cid, blob))
            with mock.patch.object(backend, "MIN_SEMANTIC_SCORE", -1.0):
                for query_number in range(30):
                    source = [rng.gauss(0, 1) for _ in range(384)]
                    # Blend with one stored vector so the top result is unambiguous.
                    source = [x + 2 * y for x, y in zip(source, vectors[query_number], strict=True)]
                    q = struct.unpack("<384f", backend.pack_vector(source))
                    oracle = sorted(range(1, 1001), key=lambda cid: (-math.sumprod(vectors[cid - 1], q), cid))[:10]
                    with mock.patch.object(backend, "embeddings", return_value=[source]):
                        stdlib = backend.semantic(con, "x", "model", "revision", self.root, self.root, 10, "stdlib")
                        native = backend.semantic(con, "x", "model", "revision", self.root, self.root, 10, "sqlite-vec")
                    self.assertEqual([cid for cid, _ in stdlib], oracle)
                    self.assertEqual([cid for cid, _ in native], oracle)
                    for (_, exact), (_, accelerated) in zip(stdlib, native, strict=True):
                        self.assertAlmostEqual(exact, accelerated, delta=1e-5)

    def test_http_contract_and_stale_error(self):
        self.index()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--database", str(self.db), "--port", str(port), "--default-rerank", "lexical-symbol"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
        self.assertIn("Local Context7", proc.stdout.readline())
        base = f"http://127.0.0.1:{port}"
        with urlopen(base + "/api/v2/libs/search?libraryName=billing") as response:
            self.assertEqual(json.load(response)["results"][0]["id"], "/local/billing")
        with urlopen(base + "/api/v2/libs/search?libraryName=other") as response:
            self.assertEqual(json.load(response), {"results": []})
        with urlopen(base + "/api/v2/context?" + urlencode({"libraryId": "/local/billing", "query": "InvoiceMaker", "type": "json"})) as response:
            payload = json.load(response)
            self.assertTrue(payload["codeSnippets"])
            self.assertIn("sha256:", payload["codeSnippets"][0]["codeDescription"])
        with urlopen(base + "/api/v2/context?" + urlencode({"libraryId": "/local/billing", "query": "InvoiceMaker", "type": "txt"})) as response:
            text = response.read().decode("utf-8")
            self.assertIn("return 'invoice total'\n\ndocs:guide.md:L1", text)
            self.assertNotIn("return 'invoice total'docs:", text)
        with self.assertRaises(HTTPError) as error:
            urlopen(base + "/api/v2/context?libraryId=/public/unknown&query=invoice")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()
        (self.root / "src/service.py").write_text("changed\n", encoding="utf-8", newline="\n")
        with self.assertRaises(HTTPError) as error:
            urlopen(base + "/api/v2/context?libraryId=/local/billing&query=invoice")
        self.assertEqual(error.exception.code, 409)
        error.exception.close()
        proc.terminate()
        proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()

    @unittest.skipUnless(os.environ.get("LEGACY_CTX7_CLI"), "optional ctx7 CLI not installed")
    def test_real_ctx7_cli_against_local_server(self):
        self.index()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--database", str(self.db), "--port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertIn("Local Context7", proc.stdout.readline())
            config = Path(self.tmp.name).resolve() / "isolated-cli"
            (config / "context7").mkdir(parents=True)
            (config / "context7/credentials.json").write_text("null\n", encoding="utf-8", newline="\n")
            env = backend.inference_environment(config, download=False)
            env.update({"HOME": str(config), "XDG_CONFIG_HOME": str(config), "XDG_STATE_HOME": str(config / "state"), "XDG_CACHE_HOME": str(config / "cache"), "CTX7_TELEMETRY_DISABLED": "1", "CI": "1", "NO_UPDATE_NOTIFIER": "1"})
            prefix = ["node", os.environ["LEGACY_CTX7_CLI"], "--base-url", f"http://127.0.0.1:{port}"]
            found = subprocess.run(prefix + ["library", "billing", "local source", "--json"], env=env, text=True, capture_output=True, timeout=20, check=True)
            self.assertEqual(json.loads(found.stdout)[0]["id"], "/local/billing")
            positive = subprocess.run(prefix + ["docs", "/local/billing", "InvoiceMaker", "--json"], env=env, text=True, capture_output=True, timeout=20, check=True)
            snippets = json.loads(positive.stdout)["codeSnippets"]
            self.assertTrue(snippets)
            self.assertIn("sha256:", snippets[0]["codeDescription"])
            negative = subprocess.run(prefix + ["docs", "/local/billing", "ImaginaryGovernmentFramework", "--json"], env=env, text=True, capture_output=True, timeout=20, check=True)
            self.assertIn("No documentation found", negative.stdout)
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()

    @unittest.skipUnless(os.environ.get("LEGACY_RETRIEVAL_TEST_RUNTIME"), "optional local model runtime not installed")
    def test_actual_cross_encoder_warmup_and_offline_query(self):
        cache = Path(os.environ["LEGACY_RETRIEVAL_TEST_CACHE"])
        runtime = Path(os.environ["LEGACY_RETRIEVAL_TEST_RUNTIME"])
        (self.root / "src/service.py").write_text("class PayrollEngine:\n    def calculate_salary(self):\n        return withholding\n", encoding="utf-8", newline="\n")
        (self.docs / "guide.md").write_text("The PayrollEngine computes compensation and applies withholding before the pay statement.\n", encoding="utf-8", newline="\n")
        (self.docs / "cleanup.md").write_text("A scheduled cleanup job purges obsolete files at midnight.\n", encoding="utf-8", newline="\n")
        result = backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, reranker_model=backend.DEFAULT_RERANKER)
        self.assertEqual(result["rerankerRevision"], backend.DEFAULT_RERANKER_REVISION)
        with backend.connect(self.db) as con:
            ranked = backend.query(con, "Who computes compensation deductions?", mode="hybrid", rerank="cross-encoder")
            self.assertTrue(ranked["results"])
            self.assertTrue(all(isinstance(hit["rerankScore"], float) for hit in ranked["results"]))
            self.assertEqual(backend.query(con, "ImaginaryGovernmentFramework", mode="hybrid", rerank="cross-encoder")["results"], [])
            with mock.patch.object(backend, "reranker_scores", side_effect=backend.RetrievalError("offline reranker unavailable")):
                with self.assertRaisesRegex(backend.RetrievalError, "offline reranker unavailable"):
                    backend.query(con, "PayrollEngine", rerank="cross-encoder")
        missing_cache = Path(self.tmp.name).resolve() / "empty-cache"
        missing_cache.mkdir()
        with self.assertRaisesRegex(backend.RetrievalError, "Local reranker helper failed"):
            backend.reranker_scores("payroll", ["payroll document"], backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, missing_cache, runtime, download=False)
        lexical_db = Path(self.tmp.name).resolve() / "lexical-only.sqlite"
        backend.index(self.root, lexical_db, "/local/billing", self.docs, None, cache, runtime, reranker_model=backend.DEFAULT_RERANKER)
        with backend.connect(lexical_db) as con:
            self.assertFalse(backend.metadata(con)["embed_model"])
            self.assertTrue(backend.query(con, "PayrollEngine", rerank="cross-encoder")["results"])
            backend.put_meta(con, "model_cache", str(missing_cache))
        with backend.connect(lexical_db) as con:
            with self.assertRaisesRegex(backend.RetrievalError, "Local reranker model is unavailable"):
                backend.query(con, "PayrollEngine", rerank="cross-encoder")

    @unittest.skipUnless(os.environ.get("LEGACY_RETRIEVAL_TEST_RUNTIME") and os.environ.get("LEGACY_CTX7_CLI"), "requires optional inference runtime and stock ctx7 client")
    def test_stock_ctx7_uses_configured_hybrid_and_learned_reranker(self):
        (self.root / "src/service.py").write_text("class PayrollEngine:\n    def calculate_salary(self):\n        return withholding\n", encoding="utf-8", newline="\n")
        (self.docs / "guide.md").write_text("The PayrollEngine calculates salaries and applies withholding before the pay statement.\n", encoding="utf-8", newline="\n")
        cache = Path(os.environ["LEGACY_RETRIEVAL_TEST_CACHE"])
        runtime = Path(os.environ["LEGACY_RETRIEVAL_TEST_RUNTIME"])
        backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, reranker_model=backend.DEFAULT_RERANKER)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--database", str(self.db), "--port", str(port), "--default-mode", "hybrid", "--default-rerank", "cross-encoder"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertIn("mode=hybrid rerank=cross-encoder", proc.stdout.readline())
            config = Path(self.tmp.name).resolve() / "hybrid-client"
            (config / "context7").mkdir(parents=True)
            (config / "context7/credentials.json").write_text("null\n", encoding="utf-8", newline="\n")
            env = backend.inference_environment(config, download=False)
            env.update({"HOME": str(config), "XDG_CONFIG_HOME": str(config), "XDG_CACHE_HOME": str(config / "cache"), "XDG_STATE_HOME": str(config / "state"), "CTX7_TELEMETRY_DISABLED": "1", "CI": "1", "NO_UPDATE_NOTIFIER": "1"})
            result = subprocess.run(["node", os.environ["LEGACY_CTX7_CLI"], "--base-url", f"http://127.0.0.1:{port}", "docs", "/local/billing", "Who computes compensation deductions?", "--json"], env=env, capture_output=True, text=True, timeout=30, check=True)
            snippets = json.loads(result.stdout)["infoSnippets"]
            self.assertTrue(any(x["pageTitle"] == "guide.md" for x in snippets))
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()

    @unittest.skipUnless(os.environ.get("LEGACY_RETRIEVAL_TEST_RUNTIME"), "optional local model runtime not installed")
    def test_actual_semantic_hybrid_and_reranking(self):
        (self.root / "src/service.py").write_text("class PayrollEngine:\n    def calculate_salary(self):\n        return withholding\n", encoding="utf-8", newline="\n")
        (self.docs / "guide.md").write_text("The PayrollEngine calculates salaries and applies withholding before the pay statement.\n", encoding="utf-8", newline="\n")
        (self.docs / "cleanup.md").write_text("A scheduled cleanup job removes obsolete files at midnight.\n", encoding="utf-8", newline="\n")
        cache = Path(os.environ["LEGACY_RETRIEVAL_TEST_CACHE"])
        runtime = Path(os.environ["LEGACY_RETRIEVAL_TEST_RUNTIME"])
        backend.index(self.root, self.db, "/local/billing", self.docs, "Xenova/all-MiniLM-L6-v2", cache, runtime)
        with backend.connect(self.db) as con:
            self.assertEqual(backend.query(con, "Who computes compensation deductions?")["results"], [])
            result = backend.query(con, "Who computes compensation deductions?", mode="semantic")
            self.assertIn("guide.md", result["results"][0]["source"]["path"])
            result = backend.query(con, "Which process purges expired artifacts overnight?", mode="hybrid", rerank="lexical-symbol")
            self.assertEqual(result["results"][0]["source"]["path"], "cleanup.md")
            for mode in ("lexical", "semantic", "hybrid"):
                self.assertEqual(backend.query(con, "ImaginaryGovernmentFramework", mode=mode)["results"], [])

    @unittest.skipUnless(os.environ.get("LEGACY_RETRIEVAL_TEST_RUNTIME"), "optional local model runtime not installed")
    def test_actual_model_loads_once_over_32_chunks_and_queries_offline(self):
        cache = Path(os.environ["LEGACY_RETRIEVAL_TEST_CACHE"])
        runtime = Path(os.environ["LEGACY_RETRIEVAL_TEST_RUNTIME"])
        for n in range(35):
            (self.docs / f"topic-{n:02d}.md").write_text(f"A scheduled cleanup job removes obsolete file group {n} at midnight.\n", encoding="utf-8", newline="\n")
        original = subprocess.Popen
        launched = []
        def count_process(*args, **kwargs):
            if args[0][0] == "node":
                launched.append(args[0])
            return original(*args, **kwargs)
        with mock.patch.object(subprocess, "Popen", side_effect=count_process):
            backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)
        self.assertEqual(len(launched), 1)
        with backend.connect(self.db) as con:
            vectors = [row[0] for row in con.execute("SELECT embedding FROM chunk_vectors ORDER BY chunk_id")]
            self.assertEqual(len(vectors), 37)
            self.assertTrue(all(len(vector) == 384 * 4 for vector in vectors))
            self.assertEqual(backend.metadata(con)["model_revision"], backend.DEFAULT_MODEL_REVISION)
            result = backend.query(con, "Which process purges expired artifacts overnight?", mode="semantic")
            self.assertTrue(result["results"])
        self.assertEqual(backend.index(self.root, self.db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime)["changed"], 0)
        with backend.connect(self.db) as con:
            self.assertEqual(vectors, [row[0] for row in con.execute("SELECT embedding FROM chunk_vectors ORDER BY chunk_id")])

    @unittest.skipUnless(os.environ.get("LEGACY_RETRIEVAL_TEST_RUNTIME"), "optional local model runtime not installed")
    def test_actual_sqlite_vec_matches_stdlib_top_k(self):
        self.require_sqlite_vec()
        cache = Path(os.environ["LEGACY_RETRIEVAL_TEST_CACHE"])
        runtime = Path(os.environ["LEGACY_RETRIEVAL_TEST_RUNTIME"])
        (self.docs / "cleanup.md").write_text("A scheduled cleanup job removes obsolete files at midnight.\n", encoding="utf-8", newline="\n")
        ranked = []
        for engine in ("stdlib", "sqlite-vec"):
            db = Path(self.tmp.name).resolve() / f"actual-{engine}.sqlite"
            backend.index(self.root, db, "/local/billing", self.docs, backend.DEFAULT_MODEL, cache, runtime, vector_engine=engine)
            with backend.connect(db) as con:
                result = backend.query(con, "Who computes compensation deductions?", mode="semantic", limit=3, vector_engine=engine)
                ranked.append([(item["source"]["kind"], item["source"]["path"]) for item in result["results"]])
        self.assertEqual(ranked[0], ranked[1])


if __name__ == "__main__":
    unittest.main()
