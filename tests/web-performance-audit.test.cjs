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

// Shape taken from a real Lighthouse 13.5.0 report: entities with isFirstParty, an entity name on every
// request, third-parties-insight instead of third-party-summary (which 13 removed).
function lhr13({ host, vendorHost }) {
  const lhr = fakeLhr({ lcp: 3000, tbt: 500, perf: 60, host });
  lhr.lighthouseVersion = '13.5.0';
  lhr.entities = [
    { name: 'Site', origins: [`https://${host}`], isFirstParty: true, isUnrecognized: true },
    { name: 'Vendor', origins: [`https://${vendorHost}`], category: 'ad' },
  ];
  lhr.audits['network-requests'].details.items = [
    { url: `https://${host}/`, entity: 'Site', resourceType: 'Document', transferSize: 10240, resourceSize: 40960 },
    { url: `https://${vendorHost}/t.js`, entity: 'Vendor', resourceType: 'Script', transferSize: 51200, resourceSize: 153600 },
  ];
  lhr.audits['third-parties-insight'] = { score: 1, scoreDisplayMode: 'informative', details: { type: 'table', isEntityGrouped: true, items: [
    { entity: 'Vendor', mainThreadTime: 412.7, transferSize: 51200, subItems: { type: 'subitems', items: [] } },
  ] } };
  return lhr;
}

test('summarizer reads Lighthouse 13 third parties and uses its first-party entity', async () => {
  const { summarizeRun, siteKey } = await load('scripts/summarize-lighthouse.mjs');
  for (const [host, vendorHost] of [['shop.example.co.uk', 'tags.vendor.co.uk'], ['foo.github.io', 'bar.github.io']]) {
    const run = summarizeRun(lhr13({ host, vendorHost }));
    assert.equal(Math.round(run.thirdPartyTransferKiB), 50, `${vendorHost} is third party for ${host}`);
    assert.equal(run.byHost[vendorHost].firstParty, false);
    assert.equal(run.byHost[host].firstParty, true);
    assert.deepEqual(run.thirdParties, [{ entity: 'Vendor', transferKiB: 50, mainThreadMs: 413 }]);
    assert.equal(run.metrics.TTFB, 200);
  }
  assert.equal(siteKey('shop.example.co.uk'), 'example.co.uk', 'fallback keeps ccTLD second levels');
  assert.notEqual(siteKey('tags.vendor.co.uk'), siteKey('shop.example.co.uk'));
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
  const attached = lighthouseArgs(opts, 'mobile', 1, 9333);
  assert.ok(attached.includes('--port=9333'));
  assert.ok(!attached.some((a) => a.startsWith('--chrome-flags')), 'flags are ignored when attaching');
});

test('runner never hands audit arguments to a Windows shell', async () => {
  const { npxCommand } = await load('scripts/run-lighthouse.mjs');
  assert.deepEqual(npxCommand('linux', '/usr/bin/node', () => true), { cmd: 'npx', pre: [] });
  const win = npxCommand('win32', 'C:\\Program Files\\nodejs\\node.exe', () => true);
  assert.deepEqual(win, { cmd: 'C:\\Program Files\\nodejs\\node.exe', pre: ['C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npx-cli.js'] });
  assert.throws(() => npxCommand('win32', 'C:\\node\\node.exe', () => false), /npx-cli\.js not found/);
  const source = fs.readFileSync(path.join(skillDir, 'scripts/run-lighthouse.mjs'), 'utf8');
  assert.doesNotMatch(source, /shell:/, 'no spawn may enable a shell');
});

test('runner refuses an output folder with earlier runs unless --clean', async () => {
  const { parseArgs, priorRunFiles } = await load('scripts/run-lighthouse.mjs');
  const dir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'wpa-test-'));
  try {
    for (const f of ['mobile-1.report.json', 'mobile-3.report.html', 'desktop-2.log', 'lighthouse-version.txt', 'notes.md']) fs.writeFileSync(path.join(dir, f), '');
    assert.deepEqual(priorRunFiles(dir).sort(), ['desktop-2.log', 'mobile-1.report.json', 'mobile-3.report.html']);
    assert.deepEqual(priorRunFiles(path.join(dir, 'missing')), []);
    assert.equal(parseArgs(['--url', 'https://a.test/', '--out', dir, '--clean']).clean, true);
    assert.equal(parseArgs(['--url', 'https://a.test/', '--out', dir]).clean, false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('runner launches Linux Chrome itself on WSL, never the Windows build', async () => {
  const { isWsl, findLinuxChrome } = await load('scripts/run-lighthouse.mjs');
  assert.equal(isWsl('6.18.54.1-microsoft-standard-WSL2', false), true);
  assert.equal(isWsl('6.18.54.1-microsoft-standard-WSL2', true), false, 'Docker on a WSL kernel is plain Linux');
  assert.equal(isWsl('6.8.0-45-generic', false), false);
  const files = new Set(['/usr/bin/google-chrome', '/mnt/c/Program Files/Google/Chrome/Application/google-chrome', '/opt/chrome']);
  const exists = (p) => files.has(p);
  assert.equal(findLinuxChrome({ PATH: '/mnt/c/Program Files/Google/Chrome/Application:/usr/bin' }, exists), '/usr/bin/google-chrome');
  assert.equal(findLinuxChrome({ PATH: '/usr/bin', CHROME_PATH: '/opt/chrome' }, exists), '/opt/chrome');
  assert.equal(findLinuxChrome({ PATH: '/mnt/c/Program Files/Google/Chrome/Application' }, exists), null);
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
