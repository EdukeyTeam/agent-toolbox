"""Large extracted HTML/notebook evidence remains cited and budgetable."""
import contextlib
import hashlib
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
from local_context import assemble, chunk, cli, engine, freshness, store
from local_context.units import RetrievalError
import test_legacy_local_context_http as http_fixture


def fixtures(root, docs):
    paragraphs = [f'<p>Paragraph {i}: ' + 'ordinary documentation prose ' * 8 + '</p>' for i in range(300)]
    paragraphs[240] = '<p>html_deep_marker uses &amp; preserves <strong>nested evidence</strong>.</p>'
    html = '\n'.join(['<html><body>', '<h1>Manual</h1>', '<p>Introduction.</p>',
                      '<h2>Operations</h2>', '<h5>Deep details</h5>', *paragraphs,
                      '<h6>Appendix</h6>', '<p>End.</p>', '</body></html>'])
    (docs / 'manual.html').write_text(html, encoding='utf-8')
    source = [f'row_{i} = "' + 'ordinary notebook content ' * 8 + '"\n' for i in range(300)]
    source[240] = 'notebook_deep_marker = "é\\\\\\\""\n'
    notebook = {'cells': [{'cell_type': 'markdown', 'source': ['Short introduction.\n']},
                          {'cell_type': 'code', 'source': source, 'outputs': [{'text': 'ignored output'}]}],
                'metadata': {'language_info': {'name': 'python'}}}
    (root / 'large.ipynb').write_text(json.dumps(notebook, indent=2), encoding='utf-8')


class TransformedUnitsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.docs = self.base / 'src', self.base / 'docs'
        self.root.mkdir()
        self.docs.mkdir()
        fixtures(self.root, self.docs)
        self.db = self.base / 'index.sqlite'
        freshness.index(self.root, self.db, '/local/large', docs_root=self.docs, parser='0')

    def query(self, query, **options):
        with store.connect(self.db) as con:
            return engine.query(con, query, **options)

    def test_large_html_and_notebook_deep_matches_fit_default_budget(self):
        for query, folder, path, title in (
                ('html_deep_marker', self.docs, 'manual.html', 'Manual > Operations > Deep details'),
                ('notebook_deep_marker', self.root, 'large.ipynb', 'cell 1')):
            with self.subTest(path=path):
                result = self.query(query, tokens=4000)
                self.assertTrue(result['results'], result)
                item = result['results'][0]
                self.assertIn(query, item['text'])
                self.assertIn(title, item['title'])
                self.assertGreater(item['partCount'], 1)
                self.assertLessEqual(math.ceil(len(assemble.serialize(result)) / 4), 4000)
                source = item['source']
                raw = (folder / path).read_text(encoding='utf-8')
                marker_line = next(i for i, line in enumerate(raw.splitlines(), 1) if query in line)
                self.assertLessEqual(source['startLine'], marker_line)
                self.assertGreaterEqual(source['endLine'], marker_line)
                self.assertEqual(source['fileSha256'], hashlib.sha256((folder / path).read_bytes()).hexdigest())
                self.assertEqual(source['fileSha256'], source['liveFileSha256'])
                self.assertEqual(source['freshness'], 'fresh')
                self.assertEqual(source['lineMapping'], 'approximate')
                self.assertGreater(source['startLine'], 1)
                self.assertLess(source['endLine'], len(raw.splitlines()))
                if path.endswith('.html'):
                    self.assertIn('& preserves', item['text'])
                    self.assertLess(source['endLine'] - source['startLine'], 20)
                else:
                    self.assertEqual(source['cellIndex'], 1)

    def test_cli_transformed_results_and_receipts_at_smaller_budgets(self):
        for fmt in ('json', 'context7-json', 'text'):
            for tokens in (1000, 4000):
                for query in ('html_deep_marker', 'notebook_deep_marker'):
                    with self.subTest(fmt=fmt, tokens=tokens, query=query):
                        output, errors = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                            code = cli.main(['query', '--database', str(self.db), '--query', query,
                                             '--tokens', str(tokens), '--format', fmt])
                        self.assertEqual(code, 0, errors.getvalue())
                        raw = output.getvalue()
                        self.assertIn(query, raw)
                        self.assertLessEqual(math.ceil(len(raw) / 4), tokens)
                        if fmt != 'text':
                            value = json.loads(raw)
                            budget = value['budget'] if fmt == 'json' else value['local']['budget']
                            self.assertEqual(budget['characters'], len(raw))
                            self.assertEqual(budget['usedEstimatedTokens'], math.ceil(len(raw) / 4))
        for query in ('html_deep_marker', 'notebook_deep_marker'):
            result = self.query(query, tokens=256)
            self.assertFalse(result['results'])
            self.assertEqual(result['reason'], 'budget_omitted')
            self.assertLessEqual(math.ceil(len(assemble.serialize(result)) / 4), 256)

    def test_transformed_hashes_use_physical_crlf_bytes(self):
        for query, folder, path in (('html_deep_marker', self.docs, 'manual.html'),
                                    ('notebook_deep_marker', self.root, 'large.ipynb')):
            with self.subTest(path=path):
                file = folder / path
                raw = file.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8')
                file.write_bytes(raw)
                freshness.refresh(self.db)
                source = self.query(query, tokens=4000)['results'][0]['source']
                self.assertEqual(source['fileSha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(source['liveFileSha256'], source['fileSha256'])
                self.assertNotEqual(source['fileSha256'], hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest())

    def test_html_structure_entities_hidden_headings_and_original_ranges(self):
        text = '<h1>Guide &amp; setup</h1>\n<script>hidden <h2>False</h2></script>\n'
        text += '<style>hidden style</style>\n<h2>Usage <em>notes</em></h2>\n<p>zażółć &#10; marker</p>\n'
        text += '<h3>Third</h3><h4>Fourth</h4><h5>Fifth</h5><h6>Sixth</h6>tail'
        units = chunk.docs_units(text, 'guide.html', 'html')
        self.assertEqual(units[-1].breadcrumb, ('Guide & setup', 'Usage notes', 'Third', 'Fourth', 'Fifth', 'Sixth'))
        selected = next(unit for unit in units if 'marker' in unit.text)
        self.assertEqual((selected.start, selected.end), (4, 5))
        self.assertNotIn('hidden', ''.join(unit.text for unit in units))
        self.assertFalse(any('False' in unit.title for unit in units))

    def test_small_bodies_and_notebook_metadata_stay_intact(self):
        html = '<p>Invoice &amp; billing.</p>'
        units = chunk.docs_units(html, 'small.html', 'html')
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].text, 'Invoice & billing.')
        self.assertEqual((units[0].start, units[0].end, units[0].part, units[0].parts), (1, 1, 1, 1))
        for raw, expected in (('&unknown name', '&unknown name'), ('&unknown; name', '&unknown; name'),
                              ('&copy name', '© name'), ('&#65 name', 'A name'), ('&amp; name', '& name')):
            self.assertEqual(chunk.docs_units('<p>' + raw + '</p>', 'small.html', 'html')[0].text, expected)
        for source in ('print("small")\n', ['print("small")\n']):
            text = json.dumps({'cells': [{'cell_type': 'code', 'source': source, 'outputs': ['ignored']}]})
            units, fallback = chunk.notebook_units(text, 'small.ipynb', 1500, '0')
            self.assertIsNone(fallback)
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].text, 'print("small")\n')
            self.assertEqual(units[0].cell_index, 0)
            self.assertEqual(units[0].parts, 1)
            self.assertNotIn('ignored', units[0].text)

    def test_changed_transformed_source_is_never_silently_fresh(self):
        for query, folder, path in (('html_deep_marker', self.docs, 'manual.html'),
                                    ('notebook_deep_marker', self.root, 'large.ipynb')):
            file = folder / path
            file.write_text(file.read_text(encoding='utf-8').replace(query, 'removed_marker'), encoding='utf-8')
            with self.assertRaises(RetrievalError) as caught:
                self.query(query, tokens=4000, refresh_policy='strict')
            self.assertEqual(caught.exception.code, 'source_changed')
            stale = self.query(query, tokens=4000, refresh_policy='off')['results'][0]
            self.assertEqual(stale['source']['freshness'], 'stale')
            self.assertNotEqual(stale['source']['fileSha256'], stale['source']['liveFileSha256'])
            refreshed = self.query(query, tokens=4000)['results']
            self.assertTrue(all(query not in item['text'] for item in refreshed))
            self.assertTrue(all(item['source']['freshness'] == 'fresh' for item in refreshed))

    def test_transformed_parts_bound_whitespace_escaping_and_single_lines(self):
        for value in ('word ' * 2000, '\t\\\"' * 2000, 'x' * 10000):
            for target in (128, 1500, 12000):
                with self.subTest(target=target, value=value[:12]):
                    spans = list(chunk.transformed_spans(value, target))
                    self.assertEqual(''.join(value[a:b] for a, b in spans), value)
                    self.assertTrue(all(len(json.dumps(value[a:b], ensure_ascii=False)) - 2 <= min(target, 1500)
                                        for a, b in spans))
        html = '<h1>Guide</h1><p>' + ('padding ' * 600) + 'longline_marker ' + ('padding ' * 600) + '</p>'
        (self.docs / 'long.html').write_text(html, encoding='utf-8')
        freshness.refresh(self.db)
        result = self.query('longline_marker', tokens=750, limit=1)
        self.assertTrue(result['results'])
        item = result['results'][0]
        self.assertIn('longline_marker', item['text'])
        self.assertTrue(item['excerpt'])
        self.assertEqual((item['source']['startLine'], item['source']['endLine']), (1, 1))
        self.assertIn(item['text'], html)
        self.assertLessEqual(math.ceil(len(assemble.serialize(result)) / 4), 750)

    def test_distinct_cell_parts_survive_shared_source_envelope(self):
        notebook = {'cells': [{'cell_type': 'code', 'source': ''.join(
            f'cellpart_marker_{i} = "' + 'content ' * 160 + '"\n' for i in range(3))}]}
        (self.root / 'parts.ipynb').write_text(json.dumps(notebook), encoding='utf-8')
        freshness.refresh(self.db)
        result = self.query('cellpart_marker', tokens=4000)
        items = [item for item in result['results'] if item['source']['path'] == 'parts.ipynb']
        self.assertEqual(len(items), 3)
        self.assertEqual(len({item['partIndex'] for item in items}), 3)
        self.assertTrue(all(item['source']['cellIndex'] == 0 for item in items))

    def test_large_configured_target_still_fits_default_and_markdown_cells_split(self):
        freshness.index(self.root, self.db, '/local/large', docs_root=self.docs, parser='0', chunk_chars=12000)
        for query in ('html_deep_marker', 'notebook_deep_marker'):
            result = self.query(query, tokens=4000)
            self.assertTrue(result['results'])
            self.assertIn(query, result['results'][0]['text'])
            self.assertLessEqual(math.ceil(len(assemble.serialize(result)) / 4), 4000)
        source = '\n'.join('Markdown cell prose ' * 20 for _ in range(40))
        text = json.dumps({'metadata': {'source': 'decoy', 'cells': []}, 'cells': [
            {'metadata': {'source': 'nested decoy'}, 'source': source, 'cell_type': 'markdown'}]}, indent=2)
        units, fallback = chunk.notebook_units(text, 'prose.ipynb', 12000, '0')
        self.assertIsNone(fallback)
        self.assertGreater(len(units), 1)
        self.assertEqual(''.join(unit.text for unit in units), source)
        self.assertTrue(all(unit.breadcrumb == ('cell 0',) and unit.language == 'markdown' for unit in units))
        self.assertTrue(all(unit.start == unit.end and unit.start > 1 for unit in units))
        self.assertIn('"source": "Markdown', text.splitlines()[units[0].start - 1])


class HTTPTransformedUnitsTests(unittest.TestCase):
    setUp = http_fixture.HTTPTests.setUp
    stop = http_fixture.HTTPTests.stop

    def test_http_large_extracted_units_default_and_explicit_budget(self):
        fixtures(self.root, self.docs)
        freshness.refresh(self.db)
        for query in ('html_deep_marker', 'notebook_deep_marker'):
            for fmt in ('json', 'txt'):
                for tokens in (None, 1000):
                    params = dict(libraryId='/local/demo', query=query, type=fmt)
                    if tokens is not None:
                        params['tokens'] = tokens
                    with self.subTest(query=query, fmt=fmt, tokens=tokens):
                        with urlopen(self.url + '/api/v2/context?' + urlencode(params), timeout=5) as response:
                            raw = response.read().decode('utf-8')
                        self.assertIn(query, raw)
                        self.assertLessEqual(math.ceil(len(raw) / 4), tokens or 4000)
                        if fmt == 'json':
                            receipt = json.loads(raw)['local']['budget']
                            self.assertEqual(receipt['characters'], len(raw))
                            self.assertEqual(receipt['usedEstimatedTokens'], math.ceil(len(raw) / 4))
