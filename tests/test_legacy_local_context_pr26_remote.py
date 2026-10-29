"""PR #26: persisted indexing consent never authorizes remote queries."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context import engine, freshness, store
from local_context.units import RetrievalError, canonical
from test_legacy_local_context_review import FakeProvider


class RemoteQueryTests(unittest.TestCase):
    def test_remote_query_is_rejected_before_loading_or_reusing_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "source"
            root.mkdir()
            (root / "worker.py").write_text("def worker(): return 1\n", encoding="utf-8")
            db = base / "index.sqlite"
            config = {"provider": "openai-compatible", "base_url": "https://remote.example/v1", "allow_remote": True}
            provider = FakeProvider()
            with mock.patch.object(freshness, "provider_for", return_value=provider) as factory:
                freshness.index(root, db, "/local/remote", parser="0", _saved=config, allow_remote_embeddings=True)
                self.assertTrue(factory.called, "Explicit indexing must still support its authorized provider")
            key = "/local/remote/" + canonical({"config": config, "identity": provider.identity})
            for mode in ("semantic", "hybrid"):
                for cache in (None, {}, {key: provider}):
                    with self.subTest(mode=mode, cache=cache), store.connect(db) as con:
                        with mock.patch.object(engine, "provider_for", return_value=provider) as factory, mock.patch.object(provider, "embed_query", wraps=provider.embed_query) as send:
                            with self.assertRaises(RetrievalError) as caught:
                                engine.query(con, "worker", mode=mode, provider_cache=cache)
                            self.assertEqual(caught.exception.code, "remote_query_forbidden")
                            factory.assert_not_called()
                            send.assert_not_called()
            with store.connect(db) as con, mock.patch.object(engine, "provider_for") as factory:
                self.assertTrue(engine.query(con, "worker")["results"])
                factory.assert_not_called()

    def test_loopback_provider_remains_available_for_queries(self):
        for endpoint in ("http://localhost:8080/v1", "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1"):
            with self.subTest(endpoint=endpoint), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "source"
                root.mkdir()
                (root / "worker.py").write_text("def worker(): return 1\n", encoding="utf-8")
                db = base / "index.sqlite"
                provider = FakeProvider()
                with mock.patch.object(freshness, "provider_for", return_value=provider):
                    freshness.index(root, db, "/local/local", parser="0", _saved={"provider": "openai-compatible", "base_url": endpoint})
                with store.connect(db) as con, mock.patch.object(engine, "provider_for", return_value=provider):
                    self.assertTrue(engine.query(con, "worker", mode="semantic")["results"])


if __name__ == "__main__":
    unittest.main()
