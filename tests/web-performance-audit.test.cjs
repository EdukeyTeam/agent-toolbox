const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const skillDir = path.resolve(__dirname, '../skills/web-performance-audit');
const load = (rel) => import(pathToFileURL(path.join(skillDir, rel)).href);
const example = () => JSON.parse(fs.readFileSync(path.join(skillDir, 'assets/report-data.example.json'), 'utf8'));
const assets = () => ({
  css: fs.readFileSync(path.join(skillDir, 'assets/report.css'), 'utf8'),
  client: fs.readFileSync(path.join(skillDir, 'assets/report-client.js'), 'utf8'),
});

function fakeLhr({ lcp, tbt, perf, host = 'www.example.com' }) {
  return {
    finalDisplayedUrl: `https://${host}/`,
    lighthouseVersion: '13.0.0',
    configSettings: { formFactor: 'mobile' },
    categories: {
      performance: { score: perf / 100, auditRefs: [{ id: 'largest-contentful-paint' }, { id: 'unused-css-rules' }] },
      seo: { score: 1, auditRefs: [] },
    },
    audits: {
      'first-contentful-paint': { numericValue: 1000 },
      'largest-contentful-paint': { id: 'largest-contentful-paint', numericValue: lcp, score: 0.5, scoreDisplayMode: 'numeric' },
      'total-blocking-time': { numericValue: tbt },
      'cumulative-layout-shift': { numericValue: 0.01 },
      'speed-index': { numericValue: 2000 },
      'server-response-time': { numericValue: 200 },
      'unused-css-rules': { id: 'unused-css-rules', title: 'Reduce unused CSS', score: 0, scoreDisplayMode: 'metricSavings', displayValue: 'Est savings of 100 KiB', metricSavings: { FCP: 300 } },
      'network-requests': { details: { items: [
        { url: `https://${host}/`, resourceType: 'Document', transferSize: 10240, resourceSize: 40960 },
        { url: 'https://cdn.example.com/app.js', resourceType: 'Script', transferSize: 20480, resourceSize: 81920 },
        { url: 'https://tags.vendor.test/t.js', resourceType: 'Script', transferSize: 51200, resourceSize: 153600 },
      ] } },
    },
  };
}

test('summarizer computes medians, picks the median-LCP run and splits first/third party', async () => {
  const { summarizeRun, aggregate, median, siteKey } = await load('scripts/summarize-lighthouse.mjs');
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 2, 3]), 2.5);
  assert.equal(siteKey('cdn.example.com'), 'example.com');
  const runs = [fakeLhr({ lcp: 4000, tbt: 900, perf: 50 }), fakeLhr({ lcp: 7000, tbt: 1100, perf: 40 }), fakeLhr({ lcp: 4200, tbt: 1000, perf: 52 })].map(summarizeRun);
  const agg = aggregate(runs);
  assert.equal(agg.runs, 3);
  assert.equal(agg.metrics.LCP.median, 4200);
  assert.equal(agg.metrics.LCP.min, 4000);
  assert.equal(agg.metrics.LCP.max, 7000);
  assert.equal(agg.scores.performance.median, 50);
  assert.equal(agg.representative.metrics.LCP, 4200);
  assert.equal(Math.round(agg.representative.thirdPartyTransferKiB), 50);
  assert.deepEqual(agg.representative.failing.map((f) => f.id), ['unused-css-rules']);
});

test('lighthouse runner validates arguments and adds the desktop preset', async () => {
  const { parseArgs, lighthouseArgs } = await load('scripts/run-lighthouse.mjs');
  assert.throws(() => parseArgs(['--out', 'x']), /--url/);
  assert.throws(() => parseArgs(['--url', 'https://a.test/', '--out', 'x', '--forms', 'tablet']), /tablet/);
  const opts = parseArgs(['--url', 'https://a.test/', '--out', 'out', '--runs', '2', '--lighthouse', '13.5.0']);
  assert.equal(opts.runs, 2);
  const desktop = lighthouseArgs(opts, 'desktop', 1);
  assert.ok(desktop.includes('lighthouse@13.5.0'));
  assert.ok(desktop.includes('--preset=desktop'));
  assert.ok(!lighthouseArgs(opts, 'mobile', 1).includes('--preset=desktop'));
});

test('renderer produces a self-contained report with every section of the example', async () => {
  const { renderReport } = await load('scripts/render-html-report.mjs');
  const html = renderReport(example(), assets());
  for (const id of ['overview', 'lcp', 'main-thread', 'payload', 'inp', 'memory', 'todo', 'method']) {
    assert.match(html, new RegExp(`id="${id}" role="tabpanel"`));
  }
  assert.match(html, /\[hidden\] \{ display: none !important; \}/, 'panels must hide even with display:grid');
  assert.doesNotMatch(html, /<summary>\s*<input/, 'no interactive control inside <summary>');
  assert.equal((html.match(/class="task"/g) || []).length, 3);
  assert.doesNotMatch(html, /<script src=/, 'no external scripts');
});

test('renderer escapes text and keeps embedded JSON from closing the script tag', async () => {
  const { renderReport, inline } = await load('scripts/render-html-report.mjs');
  assert.equal(inline('use `a<b` and **bold**'), 'use <code>a&lt;b</code> and <b>bold</b>');
  const data = example();
  data.meta.lede = '<img src=x onerror=alert(1)>';
  data.todos[0].title = '</script><script>alert(1)</script>';
  const html = renderReport(data, assets());
  assert.doesNotMatch(html, /<img src=x/);
  assert.equal((html.match(/<\/script>/g) || []).length, 2, 'only the two real closing script tags');
  assert.ok(!html.includes('</script><script>alert'), 'payload is escaped');
});

test('renderer omits tabs for sections without data', async () => {
  const { renderReport } = await load('scripts/render-html-report.mjs');
  const data = example();
  delete data.memory;
  delete data.inp;
  const html = renderReport(data, assets());
  assert.doesNotMatch(html, /aria-controls="memory"/);
  assert.doesNotMatch(html, /aria-controls="inp"/);
  assert.throws(() => renderReport({}, assets()), /meta.title/);
});
