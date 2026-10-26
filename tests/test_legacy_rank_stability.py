"""Offline regressions for diverse source evidence and float32 scan parity."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import random
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/legacy-codebase-workflows/scripts'
sys.path.insert(0, str(SCRIPTS))
from local_context import assemble, engine, freshness, search, store, vectors


class RankStabilityTests(unittest.TestCase):
    def row(self, number, path='worker.py', score=1., channels=None, root='r0', start=None, end=None, coverage=.5):
        return dict(id=number, unit_uid=str(number), root_id=root, path=path,
                    start_line=start or number * 10 + 1, end_line=end or number * 10 + 3,
                    cell_index=None, score=score, lexical_score=score, coverage=coverage,
                    channels={'fts': number + 1} if channels is None else channels)

    def test_import_preambles_across_source_languages(self):
        examples = {
            'python': '# License\n"""Module header."""\nfrom worker import (\n    launch,\n    stop,\n)\nimport sys as system\n',
            'typescript': '/* License */\nimport type {\n  Options,\n} from "./options";\nexport { worker as run } from "./worker";\nexport * from "./more";\n',
            'javascript': 'import "./setup";\nconst { run } = require("./worker");\n',
            'java': '/* License */\npackage example.worker;\nimport static example.Worker.run;\n',
            'c_sharp': 'using System.IO;\nusing System.Text;\n',
            'c': '#include <stdio.h>\n#include "worker.h"\n',
            'go': 'package worker\nimport (\n  "fmt"\n  "os"\n)\n',
            'rust': 'use std::io;\n',
        }
        for language, text in examples.items():
            with self.subTest(language=language):
                self.assertTrue(search.preamble_fragment(text, language))

    def test_comment_and_license_headers_are_preambles(self):
        for language, text in [('python', '# License\n# Copyright example\n'), ('python', '"""Module documentation."""\n'), ('typescript', '/* Copyright example */\n'), ('java', ' * Licensed under example terms.\n */')]:
            with self.subTest(language=language, text=text):
                self.assertTrue(search.preamble_fragment(text, language))

    def test_executable_or_incomplete_fragments_are_not_import_only(self):
        examples = [('python', 'import worker\nworker.run()\n'), ('python', 'def worker():\n    import os\n    return os.getcwd()\n'), ('typescript', 'import { run } from "./worker";\nrun();\n'), ('typescript', 'const worker = require("worker").create();'), ('typescript', 'const text = "import worker from module";'), ('typescript', 'await import("worker");'), ('c_sharp', 'using (var file = Open()) { file.Read(); }'), ('python', 'from worker import (\n'), ('text', 'import worker'), ('python', '')]
        for language, text in examples:
            with self.subTest(language=language, text=text):
                self.assertFalse(search.preamble_fragment(text, language))

    def test_import_urls_do_not_become_comments(self):
        self.assertTrue(search.preamble_fragment('import worker from "https://example.invalid/worker.js";', 'javascript'))
        self.assertFalse(search.preamble_fragment('const url = "https://example.invalid";\nrun(url);', 'javascript'))

    def test_near_tied_duplicate_yields_to_an_unseen_file(self):
        rows = [self.row(0), self.row(1, score=.994), self.row(2, 'peer.py', .99)]
        selected = search.diverse_candidates(rows)
        self.assertEqual([r['id'] for r in selected], [0, 2, 1])

    def test_duplicate_with_more_query_coverage_stays_ahead(self):
        rows = [self.row(0), self.row(1, score=.995, coverage=.8), self.row(2, 'peer.py', .99, coverage=.5)]
        self.assertEqual([r['id'] for r in search.diverse_candidates(rows)], [0, 1, 2])

    def test_clearly_higher_duplicate_stays_ahead(self):
        rows = [self.row(0, score=2.), self.row(1, score=1.8), self.row(2, 'peer.py', .8)]
        self.assertEqual([r['id'] for r in search.diverse_candidates(rows)], [0, 1, 2])

    def test_exact_symbol_and_path_rows_are_not_demoted(self):
        for channel in ('symbol', 'path'):
            with self.subTest(channel=channel):
                rows = [self.row(0), self.row(1, score=.95, channels={channel: 1}), self.row(2, 'peer.py', .9)]
                self.assertEqual([r['id'] for r in search.diverse_candidates(rows)], [0, 1, 2])

    def test_duplicate_overlap_does_not_consume_a_diversity_slot(self):
        rows = [self.row(0, start=1, end=20), self.row(1, score=.99, start=2, end=18), self.row(2, score=.994, start=30, end=40), self.row(3, 'peer.py', .99)]
        selected = search.diverse_candidates(rows)
        self.assertEqual([r['id'] for r in assemble.candidate_window(selected, 3)], [0, 3, 2])

    def test_root_identity_and_original_tie_order_are_preserved(self):
        rows = [self.row(0), self.row(1, root='r1'), self.row(2, 'other.py')]
        self.assertEqual([r['id'] for r in search.diverse_candidates(rows)], [0, 1, 2])
        self.assertEqual([r['id'] for r in search.diverse_candidates(rows)], [0, 1, 2])

    def test_hybrid_lexical_fence_survives_diversity(self):
        rows = [self.row(0), self.row(1, score=.1), self.row(2, 'dense.py', 5., {'vector': 1})]
        rows[-1]['lexical_score'] = 0.
        selected = search.diverse_candidates(rows, anchored=True)
        self.assertEqual([r['id'] for r in selected], [0, 1, 2])

    def test_engine_demotes_imports_but_preserves_explicit_path_and_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            root.mkdir()
            (root / 'imports.py').write_text('from worker import queued, batches, flushed, processing\n', encoding='utf-8')
            (root / 'worker.py').write_text('def process_queue(items):\n    """Queued batches are flushed during processing."""\n    return [item.flush() for item in items]\n', encoding='utf-8')
            db = Path(folder) / 'index.sqlite'
            freshness.index(root, db, '/local/fixture', parser='0')
            with store.connect(db) as con:
                question = 'Where are queued batches flushed during processing?'
                lib = store.library(con)
                baseline, _ = search.candidates(con, lib, question, ablations=('preambles', 'diversity'))
                demoted, _ = search.candidates(con, lib, question)
                before = next(r for r in baseline if r['path'] == 'imports.py')
                after = next(r for r in demoted if r['path'] == 'imports.py')
                self.assertAlmostEqual(after['score'], before['score'] * search.W_PREAMBLE)
                named_before, _ = search.candidates(con, lib, 'imports.py', ablations=('preambles', 'diversity'))
                named_after, _ = search.candidates(con, lib, 'imports.py')
                self.assertEqual(named_before[0]['score'], named_after[0]['score'])
                # Native JSON now charges its complete provenance envelope.
                answer = engine.query(con, question, tokens=1000)
                self.assertEqual(answer['results'][0]['source']['path'], 'worker.py')
                self.assertLessEqual(answer['budget']['usedEstimatedTokens'], 1000)
                explicit = engine.query(con, 'imports.py')
                self.assertEqual(explicit['results'][0]['source']['path'], 'imports.py')
                self.assertIn('from worker import', explicit['results'][0]['text'])

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional numpy')
    def test_cached_float32_scores_match_exact_scan_across_batches(self):
        class Owner:
            pass
        rng = random.Random(812)
        rows = [(i, vectors.pack([rng.uniform(-2., 2.) * 10 ** (i % 5 - 2) for _ in range(16)])) for i in range(4200)]
        # Include close neighbors whose differences int8 quantization would lose.
        rows.extend((4200 + i, vectors.pack([1., 1e-4 * i] + [0.] * 14)) for i in range(5))
        owner = Owner()
        for query in ([1., 0.] + [0.] * 14, [rng.uniform(-1., 1.) for _ in range(16)]):
            expected = vectors.top_k(query, iter(rows), 100, 'numpy')
            actual = vectors.cached_top_k(query, lambda: iter(rows), 100, owner, ('db', 1))
            self.assertEqual([i for i, _ in actual], [i for i, _ in expected])
            self.assertEqual([round(s, 6) for _, s in actual], [round(s, 6) for _, s in expected])
            self.assertLess(max(abs(a[1] - b[1]) for a, b in zip(actual, expected)), 1e-12)
