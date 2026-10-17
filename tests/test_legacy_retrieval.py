"""Focused retrieval tests, runnable with python -m unittest discover -s tests."""

from contextlib import contextmanager
import errno
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# Format-8 integration tests live in test_legacy_local_context_*.py. These
# unchanged regressions exercise the retained, bounded helper protocol directly.
SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from local_context import protocol as backend
from local_context.vectors import pack, normalize
backend.pack_vector = lambda value: pack(normalize(value))

class RetrievalProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    @contextmanager
    def embedding_process_fixture(self, program, *, helper_path=None, wait_for_backpressure=False):
        target = backend.RETRIEVAL if helper_path is None else helper_path
        helper = Path(self.tmp.name).resolve() / "embedding-helper.py"
        helper.write_text(program, encoding="utf-8", newline="\n")
        self.assertEqual(helper.read_bytes(), program.encode("utf-8"))
        processes, readers, responses = [], [], []
        original_popen = subprocess.Popen
        original_thread = threading.Thread
        original_queue = backend.queue.Queue
        class ObservedQueue(original_queue):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.full_attempted = threading.Event()
            def put(self, item, *args, **kwargs):
                if self.full():
                    self.full_attempted.set()
                return super().put(item, *args, **kwargs)
            def get(self, *args, **kwargs):
                if wait_for_backpressure and not self.full_attempted.wait(timeout=2):
                    raise AssertionError("reader did not encounter backpressure")
                return super().get(*args, **kwargs)
        def launch(command, **kwargs):
            if len(command) < 2 or command[1] != str(target):
                return original_popen(command, **kwargs)
            proc = original_popen([sys.executable, "-u", str(helper)], **kwargs)
            processes.append(proc)
            return proc
        def reader(*args, **kwargs):
            thread = original_thread(*args, **kwargs)
            readers.append(thread)
            return thread
        def response_queue(*args, **kwargs):
            queue = ObservedQueue(*args, **kwargs)
            responses.append(queue)
            return queue
        try:
            with mock.patch.object(subprocess, "Popen", side_effect=launch), mock.patch.object(backend.threading, "Thread", side_effect=reader), mock.patch.object(backend.queue, "Queue", side_effect=response_queue):
                yield processes, readers, responses
        finally:
            # A failed assertion must not leave the controlled child running.
            for proc in processes:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)


    def assert_embedding_process_closed(self, processes, readers):
        self.assertTrue(processes)
        for proc in processes:
            self.assertIsNotNone(proc.poll())
            self.assertTrue(proc.stdin.closed)
            self.assertTrue(proc.stdout.closed)
        self.assertTrue(readers)
        self.assertTrue(all(not reader.is_alive() for reader in readers))


    def test_embedding_response_rejects_wide_continuous_and_unterminated_real_output(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        cases = (
            "import sys,json\nsys.stdin.readline()\nprint(json.dumps([[1.0]*128]),flush=True)\n",
            "import sys,os\nsys.stdin.readline()\nwhile True: os.write(1,b'9'*64)\n",
            "import sys\nsys.stdin.readline()\nsys.stdout.write('[[1.0]]')\nsys.stdout.flush()\n",
        )
        for program in cases:
            with self.subTest(program=program), self.embedding_process_fixture(program) as (processes, readers, _), mock.patch.object(backend, "MAX_EMBEDDING_RESPONSE_CHARS", 128):
                start = time.monotonic()
                with self.assertRaisesRegex(backend.RetrievalError, "response exceeds limit or is unterminated"):
                    list(backend.embedding_batches([["fixture"]], backend.DEFAULT_MODEL, backend.DEFAULT_MODEL_REVISION, cache, cache, download=False))
                self.assertLess(time.monotonic() - start, 5)
                self.assert_embedding_process_closed(processes, readers)


    def test_embedding_exact_response_ceiling_and_normal_real_multibatch(self):
        self.assertEqual(backend.MAX_EMBEDDING_RESPONSE_CHARS, 8 * 1024 * 1024)
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        program = "import sys,json\nfor line in sys.stdin:\n    vectors=[[1.0,0.0] for _ in json.loads(line)]\n    payload=json.dumps(vectors)\n    sys.stdout.write(payload+' '*(256-len(payload)-1)+'\\n')\n    sys.stdout.flush()\n"
        with self.embedding_process_fixture(program) as (processes, readers, _), mock.patch.object(backend, "MAX_EMBEDDING_RESPONSE_CHARS", 256):
            result = list(backend.embedding_batches([["one", "two"], ["three"]], backend.DEFAULT_MODEL, backend.DEFAULT_MODEL_REVISION, cache, cache, download=False))
            self.assertEqual(result, [[[1.0, 0.0], [1.0, 0.0]], [[1.0, 0.0]]])
            self.assert_embedding_process_closed(processes, readers)


    def test_embedding_unsolicited_real_flood_has_bounded_queue_and_early_close_cleanup(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        program = "import sys,os\nsys.stdin.readline()\nwhile True: os.write(1,b'[[1.0]]\\n'*128)\n"
        with self.embedding_process_fixture(program) as (processes, readers, responses):
            stream = backend.embedding_batches([["fixture"]], backend.DEFAULT_MODEL, backend.DEFAULT_MODEL_REVISION, cache, cache, download=False)
            self.addCleanup(stream.close)
            self.assertEqual(next(stream), [[1.0]])
            self.assertTrue(responses[0].full_attempted.wait(timeout=2), "reader did not encounter backpressure")
            self.assertEqual(responses[0].maxsize, 1)
            self.assertLessEqual(responses[0].qsize(), 1)
            start = time.monotonic()
            stream.close()
            self.assertLess(time.monotonic() - start, 2)
            self.assert_embedding_process_closed(processes, readers)


    def test_embedding_malformed_real_helper_shapes_raise_owned_errors_and_cleanup(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        for output in ("null", "3", "{}", "[[]]", "[[1.0]] trailing"):
            program = "import sys\nsys.stdin.readline()\nprint(" + repr(output) + ",flush=True)\n"
            with self.subTest(output=output), self.embedding_process_fixture(program) as (processes, readers, _):
                with self.assertRaisesRegex(backend.RetrievalError, "Invalid embedding output"):
                    list(backend.embedding_batches([["fixture"]], backend.DEFAULT_MODEL, backend.DEFAULT_MODEL_REVISION, cache, cache, download=False))
                self.assert_embedding_process_closed(processes, readers)


    def test_embedding_values_reject_real_malformed_numbers_before_yield_and_keep_normal_bits(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        for value in ("invalid", None, [1], True, False, math.nan, math.inf, -math.inf, 10 ** 400):
            output = json.dumps([[value]])
            program = "import sys\nsys.stdin.readline()\nprint(" + repr(output) + ",flush=True)\nsys.stdin.read()\n"
            with self.subTest(value=value), self.embedding_process_fixture(program) as (processes, readers, _):
                stream = backend.embedding_batches([["fixture"]], backend.DEFAULT_MODEL, backend.DEFAULT_MODEL_REVISION, cache, cache, download=False)
                self.addCleanup(stream.close)
                start = time.monotonic()
                with self.assertRaisesRegex(backend.RetrievalError, "Invalid embedding output: expected finite nonboolean numbers"):
                    next(stream)
                self.assertLess(time.monotonic() - start, 5)
                self.assert_embedding_process_closed(processes, readers)
        normal = "import sys\nfor line in sys.stdin: print('[[3,4.0]]',flush=True)\n"
        with self.embedding_process_fixture(normal) as (processes, readers, _):
            vectors = list(backend.embedding_batches([["fixture"]], backend.DEFAULT_MODEL, backend.DEFAULT_MODEL_REVISION, cache, cache, download=False))
            self.assertEqual(vectors, [[[3, 4.0]]])
            self.assertEqual(backend.pack_vector(vectors[0][0]).hex(), "9a99193fcdcc4c3f")
            self.assert_embedding_process_closed(processes, readers)


    def test_reranker_real_unsolicited_flood_reaches_backpressure_and_cleans_up(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        program = "import sys\nsys.stdin.readline()\nsys.stdout.write('[1.0]\\n'*256)\nsys.stdout.flush()\nsys.stdin.read()\n"
        with self.embedding_process_fixture(program, helper_path=backend.RERANK_HELPER, wait_for_backpressure=True) as (processes, readers, responses):
            start = time.monotonic()
            scores = backend.reranker_scores("query", ["passage"], backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, cache, cache, download=False)
            self.assertEqual(scores, [1.0])
            self.assertTrue(responses[0].full_attempted.is_set())
            self.assertEqual(responses[0].maxsize, 1)
            self.assertLessEqual(responses[0].qsize(), 1)
            self.assertLess(time.monotonic() - start, 5)
            self.assert_embedding_process_closed(processes, readers)


    def test_reranker_real_exact_boundary_multibatch_scores_and_cleanup(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        program = "import sys,json\nfor line in sys.stdin:\n    request=json.loads(line)\n    assert len(request['passages'])<=8\n    payload=json.dumps([float(len(p)) for p in request['passages']])\n    sys.stdout.write(payload+' '*(4096-len(payload)-1)+'\\n')\n    sys.stdout.flush()\n"
        passages = ["p" * size for size in range(1, 14)]
        with self.embedding_process_fixture(program, helper_path=backend.RERANK_HELPER) as (processes, readers, _):
            scores = backend.reranker_scores("query", passages, backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, cache, cache, download=False)
            self.assertEqual(scores, [float(size) for size in range(1, 14)])
            self.assert_embedding_process_closed(processes, readers)


    def test_reranker_real_invalid_replies_and_reader_failures_have_owned_errors_and_cleanup(self):
        cache = Path(self.tmp.name).resolve() / "cache"
        cache.mkdir()
        cases = [
            "import sys\nsys.stdin.readline()\nprint('9'*4096,flush=True)\n",
            "import sys\nsys.stdin.readline()\nsys.stdout.write('[1.0]')\nsys.stdout.flush()\n",
            "import sys,os\nsys.stdin.readline()\nos.write(1,b'\\xff\\n')\n",
        ]
        cases.extend("import sys\nsys.stdin.readline()\nprint(" + repr(output) + ",flush=True)\n" for output in ("null", "3", "{}", "[[1.0]]", "[true]", "[NaN]", "[" + str(10 ** 400) + "]"))
        for program in cases:
            with self.subTest(program=program), self.embedding_process_fixture(program, helper_path=backend.RERANK_HELPER) as (processes, readers, _):
                start = time.monotonic()
                with self.assertRaisesRegex(backend.RetrievalError, "Invalid reranker output"):
                    backend.reranker_scores("query", ["passage"], backend.DEFAULT_RERANKER, backend.DEFAULT_RERANKER_REVISION, cache, cache, download=False)
                self.assertLess(time.monotonic() - start, 5)
                self.assert_embedding_process_closed(processes, readers)


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
        # Windows os.environ normalizes keys to uppercase; OS equivalence
        # should not depend on the spelling retained by a plain mapping.
        normalized = {key.upper(): value for key, value in offline.items()}
        for key in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
            self.assertEqual(normalized[key.upper()], supplied[key])
        with mock.patch.object(os, "environ", supplied):
            normal_mapping = backend.inference_environment(cache, download=False)
        self.assertIn("SystemRoot", normal_mapping)
        self.assertNotIn("SYSTEMROOT", normal_mapping)
        self.assertEqual(normal_mapping["SystemRoot"], supplied["SystemRoot"])


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


    def test_lexical_terms_use_fts_unicode_normalization_order_and_cap(self):
        self.assertEqual(backend.lexical_terms("CAFÉ cafe cafe\u0301 你好 مرحبا ПРИВЕТ 404 \ue000"),
                         ["cafe", "你好", "مرحبا", "привет", "404", "\ue000"])
        self.assertEqual(backend.lexical_terms("the and OR café resume_upload café 404"),
                         ["cafe", "resume_upload", "404"])
        self.assertEqual(backend.lexical_terms(" ".join(str(i) for i in range(40))),
                         [str(i) for i in range(32)])
        for question in ("", " ", "?!:()[]\"*+-", "\u0301", "the AND OR"):
            with self.subTest(question=question):
                self.assertEqual(backend.lexical_terms(question), [])


if __name__ == "__main__":
    unittest.main()
