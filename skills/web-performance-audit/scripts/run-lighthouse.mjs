#!/usr/bin/env node
// Runs Lighthouse N times per form factor, sequentially, in a clean headless Chrome.
// Usage: node run-lighthouse.mjs --url <url> --out <dir> [--runs 3] [--forms mobile,desktop] [--lighthouse latest] [--clean]
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// chrome-launcher's DEFAULT_FLAGS (v1.2.2) plus its Linux sandbox flag, so a self-launched Chrome measures
// like one Lighthouse launches itself.
export const CHROME_FLAGS = [
  '--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,CalculateNativeWinOcclusion,InterestFeedContentSuggestions,CertificateTransparencyComponentUpdater,AutofillServerCommunication,PrivacySandboxSettings4,RenderDocument',
  '--disable-extensions', '--disable-component-extensions-with-background-pages', '--disable-background-networking',
  '--disable-component-update', '--disable-client-side-phishing-detection', '--disable-sync', '--metrics-recording-only',
  '--disable-default-apps', '--mute-audio', '--no-default-browser-check', '--no-first-run',
  '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling',
  '--disable-ipc-flooding-protection', '--password-store=basic', '--use-mock-keychain',
  '--force-fieldtrials=*BackgroundTracing/default/', '--disable-hang-monitor', '--disable-prompt-on-repost',
  '--disable-domain-reliability', '--propagate-iph-for-testing', '--disable-setuid-sandbox',
];

export function parseArgs(argv) {
  const opts = { runs: 3, forms: ['mobile', 'desktop'], lighthouse: 'latest', clean: false };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === '--clean') { opts.clean = true; continue; }
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

// The summarizer aggregates every <form>-<n>.report.json in the folder, so earlier runs would skew the medians.
export const RUN_ARTIFACT = /^(mobile|desktop)-\d+(\.report\.json|\.report\.html|\.log)$/;
export function priorRunFiles(dir) {
  return fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => RUN_ARTIFACT.test(f)) : [];
}

// npx is a .cmd shim on Windows, which Node only runs through cmd.exe, and cmd.exe splits a URL at & or
// runs what follows it. Run npm's npx-cli.js with node.exe instead, so no shell parses the arguments.
export function npxCommand(platform = process.platform, execPath = process.execPath, exists = fs.existsSync) {
  if (platform !== 'win32') return { cmd: 'npx', pre: [] };
  const cli = path.win32.join(path.win32.dirname(execPath), 'node_modules', 'npm', 'bin', 'npx-cli.js');
  if (!exists(cli)) throw new Error(`npx-cli.js not found next to ${execPath}; install Node.js with its bundled npm.`);
  return { cmd: execPath, pre: [cli] };
}

// With a port, Lighthouse attaches to an already running Chrome instead of launching one.
export function lighthouseArgs(opts, form, run, port) {
  const args = [
    '--yes', `lighthouse@${opts.lighthouse}`, opts.url,
    '--quiet', port ? `--port=${port}` : '--chrome-flags=--headless=new',
    '--output=json', '--output=html',
    `--output-path=${path.join(opts.out, `${form}-${run}`)}`,
    '--only-categories=performance,accessibility,best-practices,seo',
  ];
  if (form === 'desktop') args.push('--preset=desktop');
  return args;
}

// chrome-launcher assumes Chrome on WSL is the Windows build: it derives a Windows temp dir from /mnt/c PATH
// entries (failing with "mkdtemp 'undefined:/Users/undefined/...'" when there are none) and rewrites
// --user-data-dir to a Windows path, which a Linux Chrome creates as junk folders in the working directory.
// Open upstream: GoogleChrome/chrome-launcher#250, #324, #334. Docker on a WSL kernel is plain Linux.
export function isWsl(release = os.release(), inDocker = fs.existsSync('/.dockerenv')) {
  return /microsoft/i.test(release) && !inDocker;
}

// Windows Chrome under /mnt is skipped on purpose, also when CHROME_PATH (often inherited from Windows) names it:
// it cannot use a Linux profile path or POSIX process-group cleanup.
const isWindowsBuild = (p) => p.startsWith('/mnt/') || /\.exe$/i.test(p);
export function findLinuxChrome(env = process.env, exists = fs.existsSync) {
  if (env.CHROME_PATH && !isWindowsBuild(env.CHROME_PATH) && exists(env.CHROME_PATH)) return env.CHROME_PATH;
  const dirs = (env.PATH ?? '').split(':').filter((d) => d && !d.startsWith('/mnt/'));
  for (const name of ['google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser']) {
    const hit = dirs.map((d) => path.posix.join(d, name)).find((p) => exists(p));
    if (hit) return hit;
  }
  return null;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function groupAlive(pid) {
  try { process.kill(-pid, 0); return true; } catch { return false; }
}

// Starts headless Chrome on a fresh Linux profile and returns its DevTools port, as chrome-launcher would.
// Chrome runs in its own process group: its helper processes keep writing the cache after the browser
// process exits, so the whole group is stopped before the profile is removed.
async function launchChrome(chromePath) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'lighthouse-chrome-'));
  const child = spawn(chromePath, [...CHROME_FLAGS, '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore', detached: true });
  const close = async () => {
    for (const signal of ['SIGTERM', 'SIGKILL']) {
      if (groupAlive(child.pid)) process.kill(-child.pid, signal);
      for (let waited = 0; waited < 5000 && groupAlive(child.pid); waited += 100) await sleep(100);
    }
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5 });
  };
  const portFile = path.join(profile, 'DevToolsActivePort');
  for (let waited = 0; waited < 30000 && child.exitCode === null; waited += 100) {
    const port = fs.existsSync(portFile) ? Number(fs.readFileSync(portFile, 'utf8').split('\n')[0]) : 0;
    if (port) return { port, close };
    await sleep(100);
  }
  await close();
  throw new Error(`Chrome did not expose a DevTools port: ${chromePath}`);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const prior = priorRunFiles(opts.out);
  if (prior.length && !opts.clean) throw new Error(`${opts.out} already holds ${prior.length} files from an earlier run. Use a new --out, or pass --clean to delete them.`);
  for (const f of prior) fs.rmSync(path.join(opts.out, f));
  fs.mkdirSync(opts.out, { recursive: true });
  const npx = npxCommand();
  const wsl = isWsl();
  const chromePath = wsl ? findLinuxChrome() : null;
  if (wsl && !chromePath) throw new Error('WSL: no Linux Chrome found. Install Google Chrome inside WSL or set CHROME_PATH to a Linux build.');
  const version = spawnSync(npx.cmd, [...npx.pre, '--yes', `lighthouse@${opts.lighthouse}`, '--version'], { encoding: 'utf8' });
  fs.writeFileSync(path.join(opts.out, 'lighthouse-version.txt'), (version.stdout || '').trim() + '\n');
  console.log(`Lighthouse ${(version.stdout || '?').trim()} -> ${opts.out}${chromePath ? ` (WSL: own Chrome ${chromePath})` : ''}`);
  let failures = 0;
  for (const form of opts.forms) {
    for (let run = 1; run <= opts.runs; run += 1) {
      const started = Date.now();
      const chrome = chromePath ? await launchChrome(chromePath) : null;
      let res;
      try {
        res = spawnSync(npx.cmd, [...npx.pre, ...lighthouseArgs(opts, form, run, chrome?.port)], { encoding: 'utf8' });
      } finally {
        await chrome?.close();
      }
      fs.writeFileSync(path.join(opts.out, `${form}-${run}.log`), `${res.stdout || ''}\n${res.stderr || ''}`);
      const ok = res.status === 0 && fs.existsSync(path.join(opts.out, `${form}-${run}.report.json`));
      if (!ok) failures += 1;
      console.log(`${form}-${run} ${ok ? 'ok' : 'FAILED (see log)'} ${Math.round((Date.now() - started) / 1000)}s`);
    }
  }
  process.exitCode = failures ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => { console.error(err.message); process.exitCode = 1; });
}
