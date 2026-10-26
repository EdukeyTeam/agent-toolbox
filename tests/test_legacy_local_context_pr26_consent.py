"""Refresh consent is per invocation; all embedding calls are mocked offline."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context import cli, engine, freshness, store
from local_context.units import RetrievalError
from test_legacy_local_context_review import FakeProvider


class RemoteRefreshConsentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.source = self.root / "worker.py"
        self.source.write_text("def worker(): return 1\n", encoding="utf-8")
        self.db = self.base / "index.sqlite"
        self.provider = FakeProvider()

    def seed(self, endpoint="https://remote.example/v1"):
        self.source.write_text("def worker(): return 1\n", encoding="utf-8")
        config = {"provider": "openai-compatible", "base_url": endpoint, "allow_remote": True}
        with mock.patch.object(freshness, "provider_for", return_value=self.provider):
            freshness.index(self.root, self.db, "/local/remote", parser="0", _saved=config, allow_remote_embeddings=True)
        self.source.write_text("def worker(): return 222\n", encoding="utf-8")

    def test_manual_refresh_refuses_saved_consent_before_any_provider_call(self):
        self.seed()
        with store.connect(self.db) as con:
            before = tuple(con.execute("SELECT generation,corpus_hash,embedding_json FROM libraries").fetchone())
        with mock.patch.object(freshness, "provider_for") as factory, mock.patch.object(self.provider, "embed_documents") as send:
            with self.assertRaises(RetrievalError) as caught:
                freshness.refresh(self.db)
            self.assertEqual((caught.exception.code, caught.exception.status), ("consent_required", 403))
            self.assertIn("--allow-remote-embeddings", str(caught.exception))
            factory.assert_not_called()
            send.assert_not_called()
        with store.connect(self.db) as con:
            self.assertEqual(before, tuple(con.execute("SELECT generation,corpus_hash,embedding_json FROM libraries").fetchone()))

    def test_flag_authorizes_one_manual_refresh_only(self):
        self.seed()
        with mock.patch.object(freshness, "provider_for", return_value=self.provider) as factory, mock.patch.object(self.provider, "embed_documents", wraps=self.provider.embed_documents) as send:
            result = freshness.refresh(self.db, allow_remote_embeddings=True)
            self.assertEqual(result["pendingEmbeddings"], 0)
            self.assertTrue(factory.called)
            self.assertTrue(send.called)
            factory.reset_mock()
            # Even a no-op full refresh must not reuse the last invocation's flag.
            with self.assertRaises(RetrievalError):
                freshness.refresh(self.db)
            factory.assert_not_called()

    def test_automatic_and_candidate_refresh_never_embed_remotely_even_with_flag(self):
        for options in ({"automatic": True}, {"candidate_paths": {("r0", "worker.py")}}):
            for flag in (False, True):
                with self.subTest(options=options, flag=flag):
                    self.seed()
                    with mock.patch.object(freshness, "provider_for") as factory, mock.patch.object(self.provider, "embed_documents") as send:
                        result = freshness.refresh(self.db, allow_remote_embeddings=flag, **options)
                        factory.assert_not_called()
                        send.assert_not_called()
                    self.assertEqual(result["pendingEmbeddings"], 1)
                    self.assertTrue(result["remoteEmbeddingsDeferred"])
                    self.assertIn("--allow-remote-embeddings", " ".join(result["warnings"]))
                    with store.connect(self.db) as con:
                        self.assertEqual(con.execute("SELECT embedding_status FROM files").fetchone()[0], "pending")
                        self.assertEqual(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 0)
                        answer = engine.query(con, "worker")
                        self.assertTrue(answer["results"])
                        self.assertIn("--allow-remote-embeddings", " ".join(answer["warnings"]))
                    with mock.patch.object(freshness, "provider_for", return_value=self.provider):
                        self.assertEqual(freshness.refresh(self.db, allow_remote_embeddings=True)["pendingEmbeddings"], 0)

    def test_loopback_manual_and_automatic_refresh_embed_without_flag(self):
        for endpoint in ("http://localhost:8080/v1", "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1"):
            for automatic in (False, True):
                with self.subTest(endpoint=endpoint, automatic=automatic):
                    self.seed(endpoint)
                    with mock.patch.object(freshness, "provider_for", return_value=self.provider), mock.patch.object(self.provider, "embed_documents", wraps=self.provider.embed_documents) as send:
                        result = freshness.refresh(self.db, automatic=automatic)
                        self.assertTrue(send.called)
                        self.assertEqual(result["pendingEmbeddings"], 0)

    def test_cli_error_is_machine_readable_and_flag_works_for_single_and_all(self):
        self.seed()
        for selection in (["--library-id", "/local/remote"], ["--all"]):
            argv = ["refresh", "--database", str(self.db), *selection]
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(freshness, "provider_for") as factory:
                self.assertEqual(cli.main(argv), 5)
                self.assertEqual(json.loads(err.getvalue())["code"], "consent_required")
                factory.assert_not_called()
            with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(freshness, "provider_for", return_value=self.provider):
                self.assertEqual(cli.main([*argv, "--allow-remote-embeddings"]), 0)

    def test_candidate_auto_query_reports_pending_without_a_provider_call(self):
        self.seed()
        with store.connect(self.db) as con, mock.patch.object(freshness, "provider_for") as factory:
            answer = engine.query(con, "worker")
            self.assertTrue(answer["results"])
            self.assertIn("--allow-remote-embeddings", " ".join(answer["warnings"]))
            self.assertEqual(con.execute("SELECT embedding_status FROM files").fetchone()[0], "pending")
            factory.assert_not_called()
