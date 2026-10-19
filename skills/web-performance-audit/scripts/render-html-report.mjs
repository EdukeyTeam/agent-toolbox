#!/usr/bin/env node
// Renders report-data.json into one self-contained, theme-aware HTML report (tabs, SVG charts, to-do list).
// Usage: node render-html-report.mjs <report-data.json> <report.html>
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ASSETS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'assets');

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Plain text with two inline marks: `code` and **bold**. Everything else is escaped.
export function inline(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
}

// JSON inside <script> must not be able to close the tag.
export function safeJson(data) {
  return JSON.stringify(data)
    .replace(/</g, '\\u003c')
    .replace(new RegExp(String.fromCharCode(0x2028), 'g'), '\\u2028')
    .replace(new RegExp(String.fromCharCode(0x2029), 'g'), '\\u2029');
}

const list = (items, tag = 'ul') => (items && items.length ? `<${tag}>${items.map((i) => `<li>${inline(i)}</li>`).join('')}</${tag}>` : '');
const status = (v, good, poor) => (v <= good ? 'good' : v <= poor ? 'warn' : 'poor');
const STATUS_TEXT = { good: 'Good', warn: 'Needs improvement', poor: 'Poor' };
const fmt = (n) => Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 });
const legendChart = '<details class="tbl"><summary>Show as table</summary><div class="tbl-wrap" id="%ID%"></div></details>';
const tableToggle = (id) => legendChart.replace('%ID%', id);

function staticTable(head, rows, numericFrom = 99) {
  return `<div class="tbl-wrap"><table><thead><tr>${head.map((h, i) => `<th${i >= numericFrom ? ' class="num"' : ''}>${inline(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${i >= numericFrom ? ' class="num"' : ''}>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function sectionOverview(d) {
  const field = d.field ? `
  <div class="panel-head"><h2>Field: real users (CrUX p75)</h2><p class="note">${inline(d.field.note || '')}</p></div>
  <div class="tiles">${d.field.rows.flatMap((m) => ['phone', 'desktop'].filter((f) => m[f] !== undefined && m[f] !== null).map((f) => {
    const v = m[f]; const s = status(v, m.good, m.poor);
    const value = m.unit ? `${fmt(v)}<small> ${escapeHtml(m.unit)}</small>` : Number(v).toFixed(2);
    return `<div class="tile"><span class="label">${escapeHtml(m.metric)} / ${f}</span><span class="value">${value}</span><span class="pill ${s}">${STATUS_TEXT[s]}</span></div>`;
  })).join('')}</div>` : '';
  const forms = Object.keys(d.lab || {});
  const lab = forms.length ? `
  <div class="panel-head"><h2>Lab: controlled runs (median)</h2><p class="note">${inline(d.labNote || '')}</p></div>
  <div class="card">
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Form factor">${forms.map((f, i) => `<button type="button" data-form="${escapeHtml(f)}" aria-pressed="${i === 0}">${escapeHtml(f[0].toUpperCase() + f.slice(1))}</button>`).join('')}</div>
      <div class="legend"><span><i style="background:var(--band-good);border:1px solid var(--good)"></i>Good</span><span><i style="background:var(--band-warn);border:1px solid var(--warn)"></i>Needs improvement</span><span><i style="background:var(--band-poor);border:1px solid var(--critical)"></i>Poor</span><span><i style="background:var(--s1);border-radius:50%"></i>Run</span><span><i style="background:var(--fg);width:3px;border-radius:1px"></i>Median</span></div>
    </div>
    <div class="tiles" id="score-tiles" style="margin-bottom:14px"></div>
    <div class="chart" id="lab-dots"></div>
    ${tableToggle('lab-table')}
  </div>` : '';
  const verdict = d.verdict ? `
  <div class="card verdict"><h2>What this means</h2>${list(d.verdict.items, 'ol')}${d.verdict.callout ? `<p class="callout">${inline(d.verdict.callout)}</p>` : ''}</div>` : '';
  return field + lab + verdict;
}

function sectionLcp(d) {
  return `
  <div class="panel-head"><h2>Where the LCP time goes</h2><p class="note">${inline(d.lcp.note || '')}</p></div>
  <div class="card">
    <div class="toolbar"><div class="seg" role="group" aria-label="Scale"><button type="button" data-lcpscale="pct" aria-pressed="true">Share of LCP</button><button type="button" data-lcpscale="ms" aria-pressed="false">Milliseconds</button></div><div class="legend" id="lcp-legend"></div></div>
    <div class="chart" id="lcp-chart"></div>
    ${tableToggle('lcp-table')}
  </div>
  ${d.lcp.findings && d.lcp.findings.length ? `<div class="grid-2">${d.lcp.findings.map((f) => `<div class="card"><h3>${inline(f.title)}</h3><p>${inline(f.body)}</p></div>`).join('')}</div>` : ''}`;
}

function sectionMain(d) {
  const tp = d.thirdParties ? `
  <div class="card">
    <h3>Third parties by visitor state</h3>
    <div class="toolbar"><div class="seg" role="group" aria-label="Measure"><button type="button" data-tp="main" aria-pressed="true">Main thread</button><button type="button" data-tp="bytes" aria-pressed="false">Transfer size</button></div><div class="legend" id="tp-legend"></div></div>
    <div class="chart" id="tp-chart"></div>
    ${d.thirdPartyNote ? `<p class="note">${inline(d.thirdPartyNote)}</p>` : ''}
    ${tableToggle('tp-table')}
  </div>` : '';
  return `
  <div class="panel-head"><h2>Main-thread work</h2><p class="note">${inline(d.mainThreadNote || '')}</p></div>
  <div class="grid-2">
    ${d.mainThread ? '<div class="card"><h3>By category</h3><div class="chart" id="mt-chart"></div></div>' : ''}
    ${d.scripts ? '<div class="card"><h3>Heaviest scripts (CPU ms)</h3><div class="chart" id="boot-chart"></div></div>' : ''}
  </div>${tp}`;
}

function sectionPayload(d) {
  return `
  <div class="panel-head"><h2>Payload vs budget</h2><p class="note">${inline(d.budgetNote || 'Transfer sizes compared with budgets. The tick marks the budget.')}</p></div>
  <div class="card">
    <div class="legend" style="margin-bottom:10px"><span><i style="background:var(--s1)"></i>Actual</span><span><i style="background:var(--fg);width:3px;border-radius:1px"></i>Budget</span></div>
    <div class="chart" id="budget-chart"></div>
    ${tableToggle('budget-table')}
  </div>
  ${d.waste && d.waste.length ? `<div class="card"><h3>Specific waste</h3>${staticTable(['Item', 'Evidence', 'Saving'], d.waste.map((w) => [w.item, w.evidence, w.saving]), 2)}</div>` : ''}`;
}

function sectionInp(d) {
  return `
  <div class="panel-head"><h2>Interaction to Next Paint</h2><p class="note">${inline(d.inp.note || '')}</p></div>
  <div class="card"><div class="legend" id="inp-legend" style="margin-bottom:10px"></div><div class="chart" id="inp-chart"></div>${tableToggle('inp-table')}</div>
  ${d.inp.diagnosis && d.inp.diagnosis.length ? `<div class="card"><h3>Diagnosis</h3>${list(d.inp.diagnosis)}</div>` : ''}`;
}

function sectionMemory(d) {
  const m = d.memory;
  return `
  <div class="panel-head"><h2>${inline(m.title || 'Memory')}</h2><p class="note">${inline(m.note || '')}</p></div>
  ${m.tiles ? `<div class="tiles">${m.tiles.map((t) => `<div class="tile"><span class="label">${inline(t.label)}</span><span class="value">${inline(t.value)}</span><span class="sub">${inline(t.sub || '')}</span></div>`).join('')}</div>` : ''}
  ${m.retained ? `<div class="card"><h3>What the heap holds (retained size)</h3><div class="chart" id="mem-chart"></div>${m.footnote ? `<p class="note">${inline(m.footnote)}</p>` : ''}</div>` : ''}`;
}

function task(t, i) {
  const code = (t.code || []).map((c) => `<div class="code"><button type="button">Copy</button><pre>${escapeHtml(c.code ?? c)}</pre></div>`).join('');
  return `
    <details class="task" data-p="${escapeHtml(t.priority)}" data-id="${escapeHtml(t.id)}"${i === 0 ? ' open' : ''}>
      <summary><span class="pri">${escapeHtml(t.id)}</span><span class="ttl">${inline(t.title)}<small>${inline(t.impact || '')}</small></span><span class="eff">${inline([t.effort && `Effort ${t.effort}`, t.owner].filter(Boolean).join(' / '))}</span></summary>
      <div class="body">
        <label class="mark"><input type="checkbox" id="done-${escapeHtml(t.id)}"> Mark as done</label>
        ${t.evidence && t.evidence.length ? `<h4>Evidence</h4>${list(t.evidence)}` : ''}
        ${t.how && t.how.length ? `<h4>How</h4>${list(t.how, 'ol')}` : ''}
        ${code}
        ${t.verify ? `<h4>Verify</h4><p>${inline(t.verify)}</p>` : ''}
      </div>
    </details>`;
}

function sectionTodo(d) {
  const priorities = [...new Set(d.todos.map((t) => t.priority))].sort();
  return `
  <div class="panel-head"><h2>Prioritized to-do</h2><p class="note">Priority = impact x confidence / effort. Verify each item with the same lab runs and compare medians. Ticks are saved only in this browser.</p></div>
  <div class="filters" role="group" aria-label="Filter by priority">
    <button type="button" class="chip" data-f="all" aria-pressed="true">All</button>
    ${priorities.map((p) => `<button type="button" class="chip" data-f="${escapeHtml(p)}" aria-pressed="false">${escapeHtml(p)}</button>`).join('')}
    <span class="progress" id="progress"></span>
  </div>
  <div class="todo">${d.todos.map(task).join('')}</div>
  ${d.targets ? `<div class="card"><h3>Budget targets</h3>${staticTable(d.targets.head, d.targets.rows, 1)}</div>` : ''}`;
}

function sectionMethod(d) {
  const m = d.method;
  return `
  <div class="panel-head"><h2>How this was measured</h2><p class="note">${inline(m.intro || '')}</p></div>
  ${m.rows ? `<div class="card">${staticTable(m.head || ['Run', 'Browser / profile', 'Device + throttling', 'Cache', 'State', 'Purpose'], m.rows)}</div>` : ''}
  ${m.notes && m.notes.length ? `<div class="grid-2">${m.notes.map((n) => `<div class="card"><h3>${inline(n.title)}</h3><p>${inline(n.body)}</p></div>`).join('')}</div>` : ''}`;
}

export function renderReport(d, { css, client }) {
  if (!d || !d.meta || !d.meta.title) throw new Error('report data needs meta.title');
  const sections = [
    ['overview', 'Overview', d.field || d.lab || d.verdict, sectionOverview],
    ['lcp', 'LCP', d.lcp, sectionLcp],
    ['main-thread', 'Main thread & tags', d.mainThread || d.scripts || d.thirdParties, sectionMain],
    ['payload', 'Payload', d.budget, sectionPayload],
    ['inp', 'Interactions', d.inp, sectionInp],
    ['memory', 'Memory', d.memory, sectionMemory],
    ['todo', 'To-do', d.todos && d.todos.length, sectionTodo],
    ['method', 'Method', d.method, sectionMethod],
  ].filter(([, , present]) => present);
  const m = d.meta;
  return `<!doctype html>
<html lang="${escapeHtml(m.lang || 'en')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${escapeHtml(m.title)}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
${css}
</style>
</head>
<body>
<header class="top wrap">
  <div class="eyebrow">${inline(m.eyebrow || 'Web performance audit')}</div>
  <h1>${inline(m.headline || m.title)}</h1>
  ${m.lede ? `<p class="lede">${inline(m.lede)}</p>` : ''}
  <div class="meta">${[m.url, m.date, ...(m.tools || [])].filter(Boolean).map((x) => `<span>${escapeHtml(x)}</span>`).join('')}</div>
</header>
<nav class="tabs" aria-label="Report sections">
  <div class="wrap" role="tablist">
    ${sections.map(([id, label], i) => `<button role="tab" id="t-${id}" aria-controls="${id}" aria-selected="${i === 0}">${escapeHtml(label)}</button>`).join('\n    ')}
  </div>
</nav>
<main class="wrap">
${sections.map(([id, , , render], i) => `<section class="panel" id="${id}" role="tabpanel" aria-labelledby="t-${id}"${i === 0 ? '' : ' hidden'}>${render(d)}
</section>`).join('\n')}
</main>
<div id="tip" hidden></div>
<script type="application/json" id="report-data">${safeJson(d)}</script>
<script>
${client}
</script>
</body>
</html>
`;
}

function main() {
  const [input, output] = process.argv.slice(2);
  if (!input || !output) {
    console.error('Usage: node render-html-report.mjs <report-data.json> <report.html>');
    process.exitCode = 2;
    return;
  }
  const data = JSON.parse(fs.readFileSync(input, 'utf8'));
  const html = renderReport(data, {
    css: fs.readFileSync(path.join(ASSETS, 'report.css'), 'utf8'),
    client: fs.readFileSync(path.join(ASSETS, 'report-client.js'), 'utf8'),
  });
  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
  fs.writeFileSync(output, html);
  console.log(`Wrote ${output} (${Math.round(html.length / 1024)} KiB)`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
