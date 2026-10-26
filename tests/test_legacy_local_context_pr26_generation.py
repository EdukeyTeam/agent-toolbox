"""PR #26: vector publication invalidates warm coverage and dense snapshots."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
from local_context import engine, freshness, store
from test_legacy_local_context_review import FakeProvider


class GenerationTests(unittest.TestCase):
    def check_publication(self, vector_engine):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "source"
            root.mkdir()
            path = root / "worker.py"
            path.write_text("def worker(): return 1\n", encoding="utf-8")
            db = base / "index.sqlite"
            provider = FakeProvider()
            with mock.patch.object(freshness, "provider_for", return_value=provider):
                freshness.index(root, db, "/local/generation", parser="0", _saved={"provider": "fake"})
            path.write_text("def worker(): return 222\n", encoding="utf-8")
            candidate = freshness.refresh(db, candidate_paths={("r0", "worker.py")})
            cache = {}
            with store.connect(db) as warm, mock.patch.object(engine, "provider_for", return_value=provider):
                # Read-only server connections cache coverage and NumPy vectors.
                first = engine.query(warm, "worker", mode="hybrid", vector_engine=vector_engine, provider_cache=cache)
                self.assertEqual(first["coverage"]["embeddingCoverage"], 0.)
                self.assertEqual(warm.total_changes, 0)
                with mock.patch.object(freshness, "provider_for", return_value=provider):
                    published = freshness.refresh(db)
                self.assertEqual(published["corpusId"], candidate["corpusId"])
                self.assertGreater(published["generation"], candidate["generation"])
                self.assertTrue(published["refreshed"])
                result = engine.query(warm, "worker", mode="semantic", vector_engine=vector_engine, provider_cache=cache)
                self.assertEqual(result["coverage"]["embeddingCoverage"], 1.)
                self.assertIn("return 222", result["results"][0]["text"])
                if vector_engine == "numpy":
                    self.assertEqual(provider._retrieval_vectors[0][2], published["generation"])
                with mock.patch.object(freshness, "provider_for", side_effect=AssertionError("No-op refresh must not embed")):
                    unchanged = freshness.refresh(db)
                self.assertEqual(unchanged["generation"], published["generation"])
                self.assertFalse(unchanged["refreshed"])

    def test_pending_publication_invalidates_warm_embedding_coverage(self):
        self.check_publication("stdlib")

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "Optional NumPy adapter not installed")
    def test_pending_publication_invalidates_warm_numpy_snapshot(self):
        self.check_publication("numpy")


if __name__ == "__main__":
    unittest.main()
