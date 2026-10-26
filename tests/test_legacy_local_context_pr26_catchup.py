"""Local semantic candidate refresh publishes vectors without scanning the corpus."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context import engine, freshness, store
from test_legacy_local_context_review import FakeProvider

LOCAL_CONFIGS = [{"provider": "local-python"}, {"provider": "transformers-js"},
                 *({"provider": "openai-compatible", "base_url": endpoint} for endpoint in
                   ("http://localhost:8080/v1", "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1"))]


class LocalCandidateCatchupTests(unittest.TestCase):
    def test_changed_semantic_candidates_are_reembedded_locally_in_one_batch(self):
        for config in LOCAL_CONFIGS:
            for mode in ("semantic", "hybrid"):
                with self.subTest(config=config, mode=mode), tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary).resolve()
                    root = base / "src"
                    root.mkdir()
                    source = root / "worker.py"
                    source.write_text("def worker(): return 1\n", encoding="utf-8")
                    (root / "other.py").write_text("def other(): return 1\n", encoding="utf-8")
                    db = base / "index.sqlite"
                    provider = FakeProvider()
                    with mock.patch.object(freshness, "provider_for", return_value=provider):
                        freshness.index(root, db, "/local/catchup", parser="0", _saved=config)
                    source.write_text("def worker(): return 222\n", encoding="utf-8")
                    with store.connect(db) as con, mock.patch.object(engine, "provider_for", return_value=provider), \
                            mock.patch.object(freshness, "provider_for", return_value=provider) as factory, \
                            mock.patch.object(provider, "embed_documents", wraps=provider.embed_documents) as embed, \
                            mock.patch.object(freshness, "inventory", side_effect=AssertionError("candidate refresh must not inventory")):
                        answer = engine.query(con, "worker", mode=mode, provider_cache={})
                        self.assertTrue(any("return 222" in row["text"] for row in answer["results"]))
                        self.assertEqual(answer["coverage"]["embeddingCoverage"], 1)
                        self.assertTrue(all(row["source"]["freshness"] == "fresh" for row in answer["results"]))
                        self.assertFalse(any("incomplete" in warning.lower() for warning in answer["warnings"]))
                        factory.assert_called_once_with(config, download=False)
                        embed.assert_called_once()
                        self.assertEqual(len(embed.call_args.args[0]), 1)
                        self.assertIn("return 222", embed.call_args.args[0][0])
                        self.assertEqual(con.execute("SELECT count(*) FROM files WHERE embedding_status='pending'").fetchone()[0], 0)
                        self.assertEqual(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 2)

    def test_changed_lexical_candidates_defer_local_and_remote_embeddings(self):
        remote = {"provider": "openai-compatible", "base_url": "https://remote.example/v1", "allow_remote": True}
        for config in [*LOCAL_CONFIGS, remote]:
            with self.subTest(config=config), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "src"
                root.mkdir()
                source = root / "worker.py"
                source.write_text("def worker(): return 1\n", encoding="utf-8")
                db = base / "index.sqlite"
                provider = FakeProvider()
                with mock.patch.object(freshness, "provider_for", return_value=provider):
                    freshness.index(root, db, "/local/catchup", parser="0", _saved=config, allow_remote_embeddings=True)
                source.write_text("def worker(): return 222\n", encoding="utf-8")
                with store.connect(db) as con, \
                        mock.patch.object(engine, "provider_for", side_effect=AssertionError("Lexical query must not load a provider")), \
                        mock.patch.object(freshness, "provider_for", side_effect=AssertionError("Lexical catch-up must not embed")), \
                        mock.patch.object(freshness, "inventory", side_effect=AssertionError("Candidate refresh must not inventory")):
                    answer = engine.query(con, "worker", mode="lexical")
                    self.assertIn("return 222", answer["results"][0]["text"])
                    self.assertEqual(answer["coverage"]["embeddingCoverage"], 0.)
                    self.assertEqual(answer["results"][0]["source"]["freshness"], "fresh")
                    self.assertEqual(con.execute("SELECT embedding_status FROM files").fetchone()[0], "pending")
                    self.assertEqual(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 0)

    def test_remote_candidate_refresh_defers_every_query_mode_even_with_consent(self):
        # Remote vector queries are forbidden by the engine; exercise the
        # refresh boundary directly to verify its independent consent guard.
        config = {"provider": "openai-compatible", "base_url": "https://remote.example/v1", "allow_remote": True}
        for mode in (None, "lexical", "semantic", "hybrid"):
            for consent in (False, True):
                with self.subTest(mode=mode, consent=consent), tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary).resolve()
                    root = base / "src"
                    root.mkdir()
                    source = root / "worker.py"
                    source.write_text("def worker(): return 1\n", encoding="utf-8")
                    db = base / "index.sqlite"
                    with mock.patch.object(freshness, "provider_for", return_value=FakeProvider()):
                        freshness.index(root, db, "/local/catchup", parser="0", _saved=config, allow_remote_embeddings=True)
                    source.write_text("def worker(): return 222\n", encoding="utf-8")
                    with mock.patch.object(freshness, "provider_for", side_effect=AssertionError("Remote catch-up must defer")), \
                            mock.patch.object(freshness, "inventory", side_effect=AssertionError("Candidate refresh must not inventory")):
                        report = freshness.refresh(db, candidate_paths={("r0", "worker.py")}, query_mode=mode,
                                                   allow_remote_embeddings=consent)
                    self.assertEqual(report["pendingEmbeddings"], 1)
                    self.assertTrue(report["remoteEmbeddingsDeferred"])
                    with store.connect(db) as con:
                        self.assertEqual(con.execute("SELECT embedding_status FROM files").fetchone()[0], "pending")
                        self.assertEqual(con.execute("SELECT count(*) FROM unit_vectors").fetchone()[0], 0)
