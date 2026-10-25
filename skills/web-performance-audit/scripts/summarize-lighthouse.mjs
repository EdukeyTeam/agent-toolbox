#!/usr/bin/env node
// Aggregates Lighthouse JSON runs (<form>-<n>.report.json) into medians, ranges and the details a report needs.
// Usage: node summarize-lighthouse.mjs <lighthouseDir> <outJson>
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const METRICS = {
  FCP: 'first-contentful-paint',
  LCP: 'largest-contentful-paint',
  TBT: 'total-blocking-time',
  CLS: 'cumulative-layout-shift',
  SI: 'speed-index',
  TTFB: 'server-response-time',
};

export function median(values) {
  const s = [...values].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// Fallback first-party key for reports without lhr.entities (Lighthouse < 10): last two labels, or three
// under common ccTLD second levels such as co.uk. Not PSL-aware; Lighthouse's own entity classification wins.
const CCTLD_SECOND_LEVELS = new Set(['ac', 'co', 'com', 'edu', 'gov', 'net', 'org']);
export function siteKey(host) {
  const parts = String(host).toLowerCase().split('.').filter(Boolean);
  const n = parts.length >= 3 && parts.at(-1).length === 2 && CCTLD_SECOND_LEVELS.has(parts.at(-2)) ? 3 : 2;
  return parts.slice(-n).join('.');
}

function hostOf(url) {
  try { return new URL(url).hostname; } catch { return 'other'; }
}

// Lighthouse tags every request with an entity and marks the page's own entity isFirstParty (PSL-aware).
export function firstPartyTest(lhr) {
  const firstParty = new Set((lhr.entities ?? []).filter((e) => e.isFirstParty).map((e) => e.name));
  const site = siteKey(hostOf(lhr.finalDisplayedUrl || lhr.finalUrl || lhr.requestedUrl));
  return (r) => (firstParty.size && r.entity ? firstParty.has(r.entity) : siteKey(hostOf(r.url)) === site);
}

export function summarizeRun(lhr) {
  const a = lhr.audits;
  const isFirstParty = firstPartyTest(lhr);
  const metrics = Object.fromEntries(Object.entries(METRICS).map(([k, id]) => [k, a[id]?.numericValue ?? null]));
  const scores = Object.fromEntries(Object.entries(lhr.categories).map(([k, c]) => [k, Math.round((c.score ?? 0) * 100)]));
  const requests = a['network-requests']?.details?.items ?? [];
  const byType = {};
  const byHost = {};
  for (const r of requests) {
    const type = r.resourceType ?? 'Other';
    const host = hostOf(r.url);
    byType[type] ??= { count: 0, transferKiB: 0, resourceKiB: 0 };
    byType[type].count += 1;
    byType[type].transferKiB += (r.transferSize ?? 0) / 1024;
    byType[type].resourceKiB += (r.resourceSize ?? 0) / 1024;
    byHost[host] ??= { count: 0, transferKiB: 0, firstParty: isFirstParty(r) };
    byHost[host].count += 1;
    byHost[host].transferKiB += (r.transferSize ?? 0) / 1024;
  }
  const metricIds = new Set(Object.values(METRICS));
  const perfIds = (lhr.categories.performance?.auditRefs ?? []).map((r) => r.id);
  const failing = perfIds
    .map((id) => a[id])
    .filter((x) => x && x.score !== null && x.score < 0.9 && x.scoreDisplayMode !== 'informative' && !metricIds.has(x.id))
    .map((x) => ({ id: x.id, title: x.title, score: x.score, displayValue: x.displayValue ?? '', metricSavings: x.metricSavings ?? {} }));
  const otherFailing = ['accessibility', 'best-practices', 'seo'].flatMap((cat) => (lhr.categories[cat]?.auditRefs ?? [])
    .map((r) => a[r.id])
    .filter((x) => x && x.score !== null && x.score < 1 && ['binary', 'numeric'].includes(x.scoreDisplayMode))
    .map((x) => ({ category: cat, id: x.id, title: x.title, items: x.details?.items?.length ?? 0 })));
  const lcpBreakdown = (a['lcp-breakdown-insight']?.details?.items?.[0]?.items ?? a['largest-contentful-paint-element']?.details?.items?.[0]?.items ?? [])
    .filter((i) => i.subpart).map((i) => ({ subpart: i.subpart, ms: Math.round(i.duration) }));
  const lcpNode = (a['lcp-breakdown-insight']?.details?.items ?? a['largest-contentful-paint-element']?.details?.items ?? [])
    .find((i) => i.type === 'node');
  return {
    finalUrl: lhr.finalDisplayedUrl || lhr.finalUrl,
    lighthouseVersion: lhr.lighthouseVersion,
    formFactor: lhr.configSettings?.formFactor,
    throttling: lhr.configSettings?.throttling,
    scores,
    metrics,
    requestCount: requests.length,
    totalTransferKiB: requests.reduce((s, r) => s + (r.transferSize ?? 0), 0) / 1024,
    thirdPartyTransferKiB: Object.values(byHost).filter((h) => !h.firstParty).reduce((s, h) => s + h.transferKiB, 0),
    byType,
    byHost,
    failing,
    otherFailing,
    mainThread: (a['mainthread-work-breakdown']?.details?.items ?? []).map((i) => ({ group: i.groupLabel ?? i.group, ms: Math.round(i.duration) })),
    bootup: (a['bootup-time']?.details?.items ?? []).slice(0, 15).map((i) => ({ url: i.url, totalMs: Math.round(i.total), scriptingMs: Math.round(i.scripting ?? 0) })),
    longTasks: (a['long-tasks']?.details?.items ?? []).slice(0, 10).map((t) => ({ url: t.url, startMs: Math.round(t.startTime), durationMs: Math.round(t.duration) })),
    // Lighthouse 13 replaced third-party-summary with third-parties-insight; the item fields are the same.
    thirdParties: ((a['third-parties-insight'] ?? a['third-party-summary'])?.details?.items ?? []).map((i) => ({
      entity: typeof i.entity === 'string' ? i.entity : i.entity?.text,
      transferKiB: (i.transferSize ?? 0) / 1024,
      mainThreadMs: Math.round(i.mainThreadTime ?? 0),
    })),
    lcpElement: lcpNode ? { selector: lcpNode.selector, snippet: lcpNode.snippet } : null,
    lcpBreakdown,
    domSize: a['dom-size']?.numericValue ?? a['dom-size-insight']?.numericValue ?? null,
  };
}

export function aggregate(runs) {
  const metrics = {};
  for (const k of Object.keys(METRICS)) {
    const values = runs.map((r) => r.metrics[k]).filter((v) => v !== null && v !== undefined);
    if (values.length) metrics[k] = { median: median(values), min: Math.min(...values), max: Math.max(...values), values };
  }
  const scores = {};
  for (const k of Object.keys(runs[0].scores)) {
    const values = runs.map((r) => r.scores[k]);
    scores[k] = { median: median(values), min: Math.min(...values), max: Math.max(...values), values };
  }
  const target = metrics.LCP?.median;
  const representative = target === undefined ? runs[0]
    : runs.reduce((best, r) => (Math.abs(r.metrics.LCP - target) < Math.abs(best.metrics.LCP - target) ? r : best), runs[0]);
  return { runs: runs.length, metrics, scores, representative };
}

export function summarizeDir(dir) {
  const out = {};
  for (const form of ['mobile', 'desktop']) {
    const files = fs.readdirSync(dir).filter((f) => f.startsWith(`${form}-`) && f.endsWith('.report.json')).sort();
    if (!files.length) continue;
    out[form] = aggregate(files.map((f) => summarizeRun(JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')))));
  }
  return out;
}

function print(summary) {
  const ms = (k, v) => (k === 'CLS' ? v.toFixed(3) : `${Math.round(v)} ms`);
  for (const [form, s] of Object.entries(summary)) {
    const r = s.representative;
    console.log(`\n## ${form}: ${s.runs} runs, Lighthouse ${r.lighthouseVersion}`);
    for (const [k, v] of Object.entries(s.scores)) console.log(`score ${k}: median ${v.median} [${v.values.join(', ')}]`);
    for (const [k, v] of Object.entries(s.metrics)) console.log(`${k}: median ${ms(k, v.median)}, range ${ms(k, v.min)} - ${ms(k, v.max)}`);
    console.log(`requests ${r.requestCount}, transfer ${Math.round(r.totalTransferKiB)} KiB (third-party ${Math.round(r.thirdPartyTransferKiB)} KiB), DOM ${r.domSize}`);
    console.log('by type: ' + Object.entries(r.byType).map(([t, v]) => `${t} ${v.count}/${Math.round(v.transferKiB)} KiB (raw ${Math.round(v.resourceKiB)})`).join(', '));
    if (r.lcpElement) console.log(`LCP element: ${r.lcpElement.selector}`);
    if (r.lcpBreakdown.length) console.log('LCP subparts (observed): ' + r.lcpBreakdown.map((p) => `${p.subpart} ${p.ms} ms`).join(', '));
    console.log('failing performance audits:');
    for (const f of r.failing) console.log(`  ${f.id} | ${f.displayValue} | ${JSON.stringify(f.metricSavings)}`);
    console.log('main thread: ' + r.mainThread.map((m) => `${m.group} ${m.ms} ms`).join(', '));
    console.log('bootup (top 8):');
    for (const b of r.bootup.slice(0, 8)) console.log(`  ${b.totalMs} ms  ${b.url.slice(0, 110)}`);
    if (r.otherFailing.length) console.log('other categories failing: ' + r.otherFailing.map((o) => `${o.category}/${o.id}`).join(', '));
  }
}

function main() {
  const [dir, outFile] = process.argv.slice(2);
  if (!dir || !outFile) {
    console.error('Usage: node summarize-lighthouse.mjs <lighthouseDir> <outJson>');
    process.exitCode = 2;
    return;
  }
  const summary = summarizeDir(dir);
  if (!Object.keys(summary).length) {
    console.error(`No <form>-<n>.report.json files found in ${dir}`);
    process.exitCode = 1;
    return;
  }
  fs.writeFileSync(outFile, JSON.stringify(summary, null, 2));
  print(summary);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
