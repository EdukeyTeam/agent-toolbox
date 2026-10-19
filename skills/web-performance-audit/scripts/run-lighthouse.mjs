#!/usr/bin/env node
// Runs Lighthouse N times per form factor, sequentially, in a clean headless Chrome.
// Usage: node run-lighthouse.mjs --url <url> --out <dir> [--runs 3] [--forms mobile,desktop] [--lighthouse latest]
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function parseArgs(argv) {
  const opts = { runs: 3, forms: ['mobile', 'desktop'], lighthouse: 'latest' };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === '--url') opts.url = value;
    else if (key === '--out') opts.out = value;
    else if (key === '--runs') opts.runs = Number(value);
    else if (key === '--forms') opts.forms = value.split(',').map((f) => f.trim()).filter(Boolean);
    else if (key === '--lighthouse') opts.lighthouse = value;
    else throw new Error(`Unknown argument: ${key}`);
    i += 1;
  }
  if (!opts.url || !/^https?:\/\//.test(opts.url)) throw new Error('--url must be an http(s) URL');
  if (!opts.out) throw new Error('--out is required');
  if (!Number.isInteger(opts.runs) || opts.runs < 1) throw new Error('--runs must be a positive integer');
  const unknown = opts.forms.filter((f) => !['mobile', 'desktop'].includes(f));
  if (unknown.length) throw new Error(`Unknown form factor(s): ${unknown.join(', ')}`);
  return opts;
}

export function lighthouseArgs(opts, form, run) {
  const args = [
    '--yes', `lighthouse@${opts.lighthouse}`, opts.url,
    '--quiet', '--chrome-flags=--headless=new',
    '--output=json', '--output=html',
    `--output-path=${path.join(opts.out, `${form}-${run}`)}`,
    '--only-categories=performance,accessibility,best-practices,seo',
  ];
  if (form === 'desktop') args.push('--preset=desktop');
  return args;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  fs.mkdirSync(opts.out, { recursive: true });
  const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const version = spawnSync(npx, ['--yes', `lighthouse@${opts.lighthouse}`, '--version'], { encoding: 'utf8', shell: process.platform === 'win32' });
  fs.writeFileSync(path.join(opts.out, 'lighthouse-version.txt'), (version.stdout || '').trim() + '\n');
  console.log(`Lighthouse ${(version.stdout || '?').trim()} -> ${opts.out}`);
  let failures = 0;
  for (const form of opts.forms) {
    for (let run = 1; run <= opts.runs; run += 1) {
      const started = Date.now();
      const res = spawnSync(npx, lighthouseArgs(opts, form, run), { encoding: 'utf8', shell: process.platform === 'win32' });
      fs.writeFileSync(path.join(opts.out, `${form}-${run}.log`), `${res.stdout || ''}\n${res.stderr || ''}`);
      const ok = res.status === 0 && fs.existsSync(path.join(opts.out, `${form}-${run}.report.json`));
      if (!ok) failures += 1;
      console.log(`${form}-${run} ${ok ? 'ok' : 'FAILED (see log)'} ${Math.round((Date.now() - started) / 1000)}s`);
    }
  }
  process.exitCode = failures ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
