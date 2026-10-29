"""Budget receipts count actual CLI and HTTP serialization, including metadata."""
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/legacy-codebase-workflows/scripts'))
from local_context import cli, engine, freshness, store
from local_context.units import RetrievalError
import test_legacy_local_context_http as http_fixture


class SerializationBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'src'
        self.root.mkdir()
        self.db = self.root.parent / 'index.sqlite'
        for i in range(5):
            (self.root / f'file{i}.py').write_text(f'def invoice_{i}(): return "é\\\\\\\""\n', encoding='utf-8')
        freshness.index(self.root, self.db, '/local/budget', parser='0')

    def output(self, command='query', fmt='json', tokens=500, *extra):
        out, err = io.StringIO(), io.StringIO()
        args = [command, '--database', str(self.db), '--tokens', str(tokens), '--format', fmt]
        args += ['--query', 'invoice'] if command == 'query' else ['--root-id', 'r0', '--path', 'file0.py', '--start-line', '1', '--end-line', '1']
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([*args, *extra])
        return code, out.getvalue(), err.getvalue()

    def assert_receipt(self, raw, fmt):
        if fmt == 'text':
            return
        result = json.loads(raw)
        budget = result['budget'] if fmt == 'json' else result['local']['budget']
        self.assertEqual(budget['characters'], len(raw))
        self.assertEqual(budget['usedEstimatedTokens'], math.ceil(len(raw) / 4))

    def test_cli_every_format_uses_complete_emitted_output(self):
        for fmt in ('json', 'context7-json', 'text'):
            for tokens in (256, 500, 2000):
                with self.subTest(fmt=fmt, tokens=tokens):
                    code, raw, err = self.output(fmt=fmt, tokens=tokens)
                    self.assertEqual(code, 0, err)
                    self.assertLessEqual(math.ceil(len(raw) / 4), tokens)
                    self.assertTrue(raw.endswith('\n'))
                    self.assert_receipt(raw, fmt)

    def test_metadata_warnings_explanations_and_no_match_are_charged(self):
        for query, options in (("invoice", {"explain": True}), ("absent_unfindable", {})):
            with store.connect(self.db) as con:
                result = engine.query(con, query, tokens=2000, **options)
            from local_context import assemble
            raw = assemble.serialize(result)
            self.assertLessEqual(math.ceil(len(raw) / 4), 2000)
            self.assert_receipt(raw, 'json')
        (self.root / 'file0.py').write_text('def invoice_0(): return 999\n', encoding='utf-8')
        with store.connect(self.db) as con:
            result = engine.query(con, 'invoice', tokens=2000, refresh_policy='off')
        self.assertTrue(result['warnings'])
        self.assert_receipt(assemble.serialize(result), 'json')

    def test_expansion_is_all_or_error_in_requested_format(self):
        code, raw, err = self.output(command='expand', fmt='json', tokens=256)
        self.assertNotEqual(code, 0)
        self.assertFalse(raw)
        self.assertEqual(json.loads(err)['code'], 'range_too_large')
        for fmt in ('json', 'context7-json', 'text'):
            code, raw, err = self.output(command='expand', fmt=fmt, tokens=2000)
            self.assertEqual(code, 0, err)
            self.assertLessEqual(math.ceil(len(raw) / 4), 2000)
            self.assert_receipt(raw, fmt)

    def test_excerpts_preserve_whole_source_lines_with_escaping_and_fences(self):
        source = self.root / 'large.py'
        source.write_text('def invoice_large():\n' + ''.join(f'    item_{i} = "é\\\\\\\"```"  # invoice\n' for i in range(150)), encoding='utf-8')
        freshness.refresh(self.db)
        code, raw, err = self.output(fmt='json', tokens=1000)
        self.assertEqual(code, 0, err)
        result = json.loads(raw)
        self.assertTrue(result['results'])
        self.assertTrue(any(item.get('excerpt') for item in result['results']))
        self.assertLessEqual(math.ceil(len(raw) / 4), 1000)
        self.assert_receipt(raw, 'json')
        for item in result['results']:
            s = item['source']
            lines = (self.root / s['path']).read_text(encoding='utf-8').splitlines()
            self.assertEqual(item['text'], '\n'.join(lines[s['startLine'] - 1:s['endLine']]))

    def test_empty_envelope_too_large_reports_budget_error(self):
        database = self.db.parent / 'long.sqlite'
        freshness.index(self.root, database, '/local/' + 'x' * 2000, parser='0')
        with store.connect(database) as con:
            with self.assertRaises(RetrievalError) as caught:
                engine.query(con, 'no_match', tokens=256)
            self.assertEqual(caught.exception.code, 'budget_too_small')


class HTTPSerializationBudgetTests(unittest.TestCase):
    setUp = http_fixture.HTTPTests.setUp
    stop = http_fixture.HTTPTests.stop

    def test_http_text_context_json_and_native_expand_wire_sizes(self):
        for output in ('json', 'txt'):
            for tokens in (256, 500, 2000):
                params = urlencode(dict(libraryId='/local/demo', query='retry_transfer', type=output, tokens=tokens))
                with self.subTest(output=output, tokens=tokens), urlopen(self.url + '/api/v2/context?' + params, timeout=5) as response:
                    raw = response.read().decode('utf-8')
                    self.assertLessEqual(math.ceil(len(raw) / 4), tokens)
                    if output == 'json':
                        budget = json.loads(raw)['local']['budget']
                        self.assertEqual(budget['characters'], len(raw))
                        self.assertEqual(budget['usedEstimatedTokens'], math.ceil(len(raw) / 4))
        params = urlencode(dict(rootId='r0', path='service.py', startLine=1, endLine=3, tokens=2000))
        with urlopen(self.url + '/api/v2/local/expand?' + params, timeout=5) as response:
            raw = response.read().decode('utf-8')
            self.assertEqual(json.loads(raw)['budget']['characters'], len(raw))
            self.assertLessEqual(math.ceil(len(raw) / 4), 2000)
