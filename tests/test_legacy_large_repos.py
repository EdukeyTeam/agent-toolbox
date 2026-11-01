"""Large-repository defects reproduced with small, offline source fixtures."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unicodedata
import random
import re
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from local_context import chunk, discover, engine, freshness, search, store, vectors
from local_context.symbols import analyze, stem, words


class LargeRepoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.db = self.base / "index.sqlite"

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_git_tracked_output_names_remain_source(self):
        for folder in sorted(discover.OUTPUT_DIRS):
            self.write(f"src/{folder}/entry.ts", "export const sourceEntry = (x) => x;\n")
        self.write("node_modules/dependency/index.ts", "export function omitted() {}\n")
        self.write(".gitignore", "build/\ndist/\nout/\ntarget/\nbin/\nobj/\n")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "--force", "src", "node_modules", ".gitignore"], check=True)
        counters = {}
        rows = list(discover.inventory(discover.roots_for(self.root, []), counters=counters))
        paths = {row[1] for row in rows}
        self.assertTrue({f"src/{folder}/entry.ts" for folder in discover.OUTPUT_DIRS} <= paths)
        self.assertNotIn("node_modules/dependency/index.ts", paths)
        self.assertEqual(counters["prunedDirectories"][0]["fileCount"], 1)
        # --include uses the walk path; it must retain the same tracked sources
        # even when their basename also appears in .gitignore.
        rows = list(discover.inventory(discover.roots_for(self.root, []), includes=["src"]))
        self.assertTrue({f"src/{folder}/entry.ts" for folder in discover.OUTPUT_DIRS} <= {r[1] for r in rows})

    def test_non_git_source_build_and_generated_output_accounted(self):
        self.write("src/build/entry.ts", "export const buildSource = (x) => x;\n")
        self.write("bin/run.sh", "#!/bin/sh\nexit 0\n")
        self.write("obj/nested/a.o", "binary output")
        self.write("obj/b.class", "binary output")
        counters = {}
        rows = list(discover.inventory(discover.roots_for(self.root, []), counters=counters))
        self.assertEqual({r[1] for r in rows}, {"src/build/entry.ts", "bin/run.sh"})
        self.assertEqual(counters["prunedDirectories"], [{"rootId": "r0", "path": "obj", "fileCount": 2, "reason": "generated-output"}])
        included = list(discover.inventory(discover.roots_for(self.root, []), includes=["obj"]))
        self.assertIn("obj/nested/a.o", {r[1] for r in included})

    def test_expression_symbols_and_definition_units_in_both_tiers(self):
        text = """export const executeAccess = async (args) => {
  return args
}
export const combineQueries = (
  left,
  right,
) => left + right
const typed: Handler = (x) => x;
let expression = function(x) { return x; };
var asyncExpression = async function(x) { return x; };
export default function namedDefault(x) { return x; }
export interface Options { enabled: boolean }
export type Result = string | number;
export const api = {
  async load(x) { return x; },
  save: async (x) => { return x },
}
class Client {
  run = (x) => { return x }
}
const values = rows.map((row) => row.id);
const parenthesizedCall = (
  await loadRows({ eager: true })
).filter((row) => row.enabled);
const literalValue = 'fixture'
function afterLiteral() { return 1; }
// const commented = (x) => x;
  await invokeCall({ value: 1 });
  return invokeCall();
  ? await invokeCall({ value: 2 }) : undefined;
"""
        self.write("features.ts", text)
        expected = {"executeAccess", "combineQueries", "typed", "expression", "asyncExpression", "namedDefault", "Options", "Result", "api", "api.load", "api.save", "Client", "Client.run"}
        for tier in ("0", "1"):
            if tier == "1" and chunk.parser_tier("1") != "1":
                continue
            with self.subTest(tier=tier):
                freshness.index(self.root, self.db, "/local/fixture", parser=tier)
                with store.connect(self.db) as con:
                    names = {r[0] for r in con.execute("SELECT qualified_name FROM symbols")}
                    self.assertTrue(expected <= names, expected - names)
                    self.assertNotIn("values", names)
                    self.assertNotIn("parenthesizedCall", names)
                    self.assertNotIn("literalValue", names)
                    self.assertNotIn("commented", names)
                    self.assertNotIn("invokeCall", names)
                    for name in ("executeAccess", "combineQueries", "typed", "Client.run", "api.load"):
                        found = engine.query(con, name)
                        self.assertTrue(found["results"])
                        self.assertEqual(found["results"][0]["unitKind"], "code-definition")
                    definitions = chunk.generic_definitions(text, "typescript")
                    access = next(d for d in definitions if d.name == "executeAccess")
                    self.assertEqual((access.start, access.end), (1, 3))
                    combine = next(d for d in definitions if d.name == "combineQueries")
                    self.assertEqual((combine.start, combine.end), (4, 7))

    def test_other_language_expression_declarations(self):
        samples = {"go": "var process = func(x int) int { return x }\n", "kotlin": "val process = fun(x: Int): Int { return x }\n", "rust": "pub const LIMIT: usize = 5;\nstatic ENABLED: bool = true;\nstatic mut COUNTER: usize = 0;\n"}
        for language, source in samples.items():
            with self.subTest(language=language):
                expected = {"LIMIT", "ENABLED", "COUNTER"} if language == "rust" else {"process"}
                self.assertEqual({d.name for d in chunk.generic_definitions(source, language)}, expected)
                if chunk.parser_tier("1") == "1":
                    parsed, _, _ = chunk.syntax_definitions(source, language)
                    self.assertTrue(expected <= {d.name for d in parsed})

    def test_fts_topk_keeps_original_ties_and_filters(self):
        for n in reversed(range(12)):
            self.write(f"unit{n:02}.py", "def shared_name():\n    return 1\n")
        self.write("manual.md", "# shared_name\n\nUse shared_name.\n")
        freshness.index(self.root, self.db, "/local/fixture", parser="0")
        with store.connect(self.db) as con:
            name = store.fts_name("/local/fixture")
            for depth in (3, 600):
                for kind in (None, "code", "docs"):
                    where = "u.library_id=? AND u.searchable=1 AND u.redacted=0"
                    args = ["/local/fixture"]
                    if kind:
                        where += " AND f.kind=?"
                        args.append(kind)
                    for weights in (search.FTS_WEIGHTS, (0., 0., 0., 0., 1.)):
                        columns = ",".join(str(w) for w in weights)
                        expected = con.execute(f"SELECT u.id,bm25({name},{columns}) AS bm FROM {name} JOIN units u ON u.id={name}.rowid JOIN files f ON f.id=u.file_id WHERE {name} MATCH ? AND {where} ORDER BY bm,f.path,u.start_line,u.unit_uid LIMIT ?", ('"shared_name"', *args, depth)).fetchall()
                        with mock.patch.object(search, "DEPTH", depth):
                            actual = search.fts_candidates(con, name, '"shared_name"', where, args, weights)
                        self.assertEqual([r[0] for r in actual], [r[0] for r in expected])

    def test_query_word_coverage_and_unicode_folding_are_unchanged(self):
        rng = random.Random(17)
        for _ in range(10):
            value = "".join(chr(rng.randrange(65536)) for _ in range(500))
            folded = "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if unicodedata.category(c) != "Mn")
            self.assertEqual(words(value), re.findall(r"[^\W]+", folded))
        self.write("mixed.ts", "export const CamelCase = (café) => ({ file_name: café });\n// αβγ cafés Straße _private\n")
        freshness.index(self.root, self.db, "/local/fixture", parser="0")
        with store.connect(self.db) as con:
            lib = store.library(con)
            for question in ("CamelCase café file_name αβγ", "camelcase cafes strasse _private", "missing Café"):
                terms = set(analyze(question)[0])
                rows, _ = search.candidates(con, lib, question)
                for row in rows:
                    raw = set(words((row["text"] or "") + " " + row["title"] + " " + json.loads(row["header_json"])["text"] + " " + row["description"]))
                    split = set(row["split_tokens"].split())
                    stems = set(row["stem_tokens"].split())
                    expected = sum(1. if t in raw or t in split else .8 if stem(t) in stems else 0 for t in terms) / max(1, len(terms))
                    self.assertEqual(row["coverage"], expected)

    def test_external_fts_migration_refresh_and_integrity(self):
        self.write("entry.ts", "export const OldAction = (x) => x;\n")
        freshness.index(self.root, self.db, "/local/fixture", parser="0")
        name = store.fts_name("/local/fixture")
        with store.connect(self.db) as con:
            self.assertEqual(store.fts_payload_name(con, "/local/fixture"), name + "_source")
            self.assertEqual(store.metadata(con)["schema_fingerprint"], store.STORAGE_FINGERPRINT)
            self.assertNotEqual(store.STORAGE_FINGERPRINT, store.digest(store.SCHEMA.encode()), "Older writers must reject the new FTS storage layout")
            self.assertNotIn("body", {r[1] for r in con.execute(f"PRAGMA table_info({name}_source)")})
            rows = [tuple(r) for r in con.execute(f"SELECT rowid,* FROM {name} ORDER BY rowid")]
            con.execute("BEGIN IMMEDIATE")
            con.execute(f"DROP TABLE {name}")
            con.execute(f"CREATE VIRTUAL TABLE {name} USING fts5(title_symbols,identifier_tokens,path_tokens,body,stemmed,tokenize=\"unicode61 remove_diacritics 2 tokenchars '_'\")")
            con.executemany(f"INSERT INTO {name}(rowid,title_symbols,identifier_tokens,path_tokens,body,stemmed) VALUES(?,?,?,?,?,?)", rows)
            self.assertEqual(store.fts_payload_name(con, "/local/fixture"), name)
            store.put_meta(con, "schema_fingerprint", store.digest(store.SCHEMA.encode()))
            store.validate(con)  # Current readers still accept a legacy index.
            store.create_library_fts(con, "/local/fixture")
            self.assertEqual(store.metadata(con)["schema_fingerprint"], store.STORAGE_FINGERPRINT)
            self.assertEqual([tuple(r) for r in con.execute(f"SELECT rowid,* FROM {name} ORDER BY rowid")], rows)
            con.execute(f"INSERT INTO {name}({name},rank) VALUES('integrity-check',1)")
            con.commit()
        self.write("entry.ts", "export const NewAction = (x) => x;\n")
        freshness.refresh(self.db, verify_all=True)
        with store.connect(self.db) as con:
            self.assertFalse(con.execute(f"SELECT rowid FROM {name} WHERE {name} MATCH ?", ('"OldAction"',)).fetchall())
            self.assertFalse(con.execute("SELECT 1 FROM symbols WHERE name='OldAction'").fetchall())
            self.assertTrue(engine.query(con, "NewAction")["results"])
            con.execute(f"INSERT INTO {name}({name},rank) VALUES('integrity-check',1)")
            self.assertEqual(con.execute(f"SELECT count(*) FROM {name}_source").fetchone()[0], con.execute("SELECT count(*) FROM units WHERE searchable=1").fetchone()[0])

    def test_location_queries_prefer_code_to_isolated_comment_fragments(self):
        self.assertTrue(search.comment_fragment(" * Queued batches are flushed here.\n */", "typescript"))
        self.assertTrue(search.comment_fragment("/** Queue behavior. */", "java"))
        self.assertFalse(search.comment_fragment("/* Queue behavior. */\nflush(queue);", "typescript"))
        self.assertFalse(search.comment_fragment("*pointer = value;", "c"))
        self.write("contract.ts", "/* Queued batches are flushed by the worker. */\n")
        self.write("worker.ts", "export function processQueuedBatches(queuedBatches) {\n  flush(queuedBatches);\n  return queuedBatches;\n}\n")
        freshness.index(self.root, self.db, "/local/fixture", parser="0")
        with store.connect(self.db) as con:
            response = engine.query(con, "Where are queued batches flushed by the worker?")
            self.assertEqual(response["results"][0]["source"]["path"], "worker.ts")
            usage = engine.query(con, "How to use the worker to flush queued batches?")
            self.assertTrue(any(r["source"]["path"] == "contract.ts" for r in usage["results"]))

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "optional numpy")
    def test_cached_dense_exact_order_filters_generation_and_validation(self):
        class Owner:
            pass
        owner = Owner()
        rows = [(i, vectors.pack([float(i % 3) + 1., float(i % 7) + 1.])) for i in range(9000)]
        loader = mock.Mock(side_effect=lambda: iter(rows))
        expected = vectors.top_k([1., 2.], iter(rows), 20, "numpy")
        first = vectors.cached_top_k([1., 2.], loader, 20, owner, ("db", 1, None))
        self.assertEqual([i for i, _ in first], [i for i, _ in expected])
        self.assertLess(max(abs(a[1] - b[1]) for a, b in zip(first, expected)), 1e-12)
        self.assertEqual(first, vectors.cached_top_k([1., 2.], loader, 20, owner, ("db", 1, None)))
        self.assertEqual(loader.call_count, 1)
        vectors.cached_top_k([1., 2.], loader, 20, owner, ("db", 2, None))
        vectors.cached_top_k([1., 2.], loader, 20, owner, ("db", 2, "docs"))
        self.assertEqual(loader.call_count, 3)
        with self.assertRaises(ValueError):
            vectors.cached_top_k([1., 2.], lambda: iter([(1, vectors.pack([0., 0.]))]), 1, owner, ("bad",))
        with self.assertRaises(ValueError):
            vectors.cached_top_k([1., 2., 3.], loader, 1, owner, ("db", 2, "docs"))

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "optional numpy")
    def test_warm_engine_snapshot_tracks_refresh_and_filters(self):
        class Provider:
            identity = {"provider": "fixture", "dimension": 2}
            truncated = 0
            def embed_documents(self, texts):
                return [[1., 0.] for _ in texts]
            def embed_query(self, text):
                return [1., 0.]
            def close(self):
                pass
        provider = Provider()
        self.write("worker.ts", "export const Worker = (x) => x;\n")
        self.write("guide.md", "# Worker\n\nUse the worker.\n")
        with mock.patch.object(freshness, "provider_for", return_value=provider), mock.patch.object(engine, "provider_for", return_value=provider):
            freshness.index(self.root, self.db, "/local/fixture", parser="0", _saved={"provider": "fixture"})
            cache = {}
            with store.connect(self.db) as con:
                engine.query(con, "Worker", mode="hybrid", vector_engine="numpy", provider_cache=cache)
                first = provider._retrieval_vectors[0]
                engine.query(con, "worker", mode="semantic", kind="docs", vector_engine="numpy", provider_cache=cache)
                self.assertNotEqual(provider._retrieval_vectors[0], first)
            self.write("worker.ts", "export const WorkerUpdated = (x) => x * 2;\n")
            freshness.refresh(self.db, verify_all=True)
            with store.connect(self.db) as con:
                response = engine.query(con, "WorkerUpdated", mode="hybrid", vector_engine="numpy", provider_cache=cache)
                self.assertGreater(provider._retrieval_vectors[0][2], first[2])
                self.assertEqual(response["coverage"]["embeddingCoverage"], 1.)
                self.assertTrue(any("WorkerUpdated" in r["text"] for r in response["results"]))


if __name__ == "__main__":
    unittest.main()
