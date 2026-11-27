#!/usr/bin/env node
// Build a self-contained, branded learning aid (flashcards, quiz or cheat sheet)
// from a JSON data file and the course-coach HTML template. No dependencies.
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const SKILL_DIR = path.resolve(__dirname, '..');
const TEMPLATE = path.join(SKILL_DIR, 'templates', 'learning-aid.html');
const DEFAULT_LOGO = path.join(SKILL_DIR, 'assets', 'edukey-logo-white.svg');
const KINDS = ['flashcards', 'quiz', 'cheatsheet'];
const MAX_LOGO_BYTES = 512 * 1024;
const MIME = { '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };

const USAGE = `Usage: node build-learning-aid.cjs --data <aid.json> --out <aid.html>
         [--guide <COURSE-GUIDE.md>] [--root <repository root>]
         [--logo <file>] [--logo-surface light|dark] [--no-logo]

--guide reads organizer, organizer_logo, logo_surface, trainer, course, hub and
language from the guide's frontmatter. organizer_logo is resolved against --root
(default: the current directory). Values in the data file's "brand" object and
explicit flags override the guide. Without a logo the Edukey logo is used.`;

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') args.help = true;
    else if (a === '--no-logo') args.noLogo = true;
    else if (['--data', '--out', '--guide', '--root', '--logo', '--logo-surface'].includes(a)) {
      if (i + 1 >= argv.length) throw new Error(`${a} needs a value`);
      args[a.slice(2).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = argv[++i];
    } else throw new Error(`Unknown argument: ${a}`);
  }
  return args;
}

// Minimal frontmatter reader: `key: value` and `key: [a, b]`; strips trailing comments.
function readGuide(file) {
  const text = fs.readFileSync(file, 'utf8');
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) throw new Error(`${file} has no YAML frontmatter`);
  const out = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!kv) continue;
    let value = kv[2].replace(/\s+#.*$/, '').trim();
    if (/^\[.*\]$/.test(value)) value = value.slice(1, -1).split(',').map(s => unquote(s.trim())).filter(Boolean);
    else value = unquote(value);
    out[kv[1]] = value;
  }
  return out;
}

function unquote(s) {
  return s.replace(/^(["'])(.*)\1$/, '$2');
}

function isText(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function validate(data) {
  const errors = [];
  if (!data || typeof data !== 'object' || Array.isArray(data)) return ['data must be a JSON object'];
  if (!KINDS.includes(data.kind)) errors.push(`kind must be one of: ${KINDS.join(', ')}`);
  if (!isText(data.title)) errors.push('title is required');
  if (data.lang !== undefined && !['pl', 'en'].includes(data.lang)) errors.push('lang must be "pl" or "en"');
  if (data.kind === 'flashcards') {
    if (!Array.isArray(data.cards) || data.cards.length === 0) errors.push('cards must be a non-empty array');
    else data.cards.forEach((c, i) => {
      if (!isText(c && c.front)) errors.push(`cards[${i}].front is required`);
      if (!isText(c && c.back)) errors.push(`cards[${i}].back is required`);
    });
  }
  if (data.kind === 'quiz') {
    if (!Array.isArray(data.questions) || data.questions.length === 0) errors.push('questions must be a non-empty array');
    else data.questions.forEach((q, i) => {
      if (!isText(q && q.question)) errors.push(`questions[${i}].question is required`);
      const opts = q && q.options;
      if (!Array.isArray(opts) || opts.length < 2 || !opts.every(isText)) errors.push(`questions[${i}].options needs at least two non-empty strings`);
      else if (!Number.isInteger(q.answer) || q.answer < 0 || q.answer >= opts.length) errors.push(`questions[${i}].answer must be the index of the correct option (0-${opts.length - 1})`);
    });
  }
  if (data.kind === 'cheatsheet') {
    if (!Array.isArray(data.sections) || data.sections.length === 0) errors.push('sections must be a non-empty array');
    else data.sections.forEach((s, i) => {
      if (!isText(s && s.title)) errors.push(`sections[${i}].title is required`);
      if (!Array.isArray(s && s.items) || s.items.length === 0) errors.push(`sections[${i}].items must be a non-empty array`);
      else s.items.forEach((it, k) => {
        if (!isText(it && it.term)) errors.push(`sections[${i}].items[${k}].term is required`);
        if (!isText(it && it.text) && !isText(it && it.code)) errors.push(`sections[${i}].items[${k}] needs text or code`);
      });
    });
  }
  const linked = [].concat(data.cards || [], data.questions || [], data.sections || []);
  linked.forEach((item, i) => {
    const url = item && item.sourceUrl;
    if (url !== undefined && !(typeof url === 'string' && (/^https?:\/\//i.test(url) || !/^[a-z][a-z0-9+.-]*:/i.test(url)))) {
      errors.push(`sourceUrl of item ${i} must be an http(s) URL or a relative path`);
    }
  });
  return errors;
}

function logoDataUri(file) {
  const ext = path.extname(file).toLowerCase();
  if (!MIME[ext]) throw new Error(`Unsupported logo type ${ext}; use ${Object.keys(MIME).join(', ')}`);
  const buf = fs.readFileSync(file);
  if (buf.length > MAX_LOGO_BYTES) throw new Error(`Logo ${file} is larger than ${MAX_LOGO_BYTES} bytes`);
  return `data:${MIME[ext]};base64,${buf.toString('base64')}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// JSON inside <script type="application/json">: escape characters that could close
// the element or start an HTML comment; JSON.parse restores them.
function scriptSafeJson(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}

function build(options) {
  const data = JSON.parse(fs.readFileSync(options.data, 'utf8'));
  const errors = validate(data);
  if (errors.length) throw new Error(`Invalid learning aid data:\n- ${errors.join('\n- ')}`);

  const root = path.resolve(options.root || process.cwd());
  const guide = options.guide ? readGuide(options.guide) : {};
  const brand = Object.assign({
    organizer: guide.organizer,
    trainer: guide.trainer,
    course: guide.course,
    hub: guide.hub,
    logoSurface: guide.logo_surface,
  }, data.brand || {});
  if (options.logoSurface) brand.logoSurface = options.logoSurface;
  if (brand.logoSurface && !['light', 'dark'].includes(brand.logoSurface)) throw new Error('logo surface must be "light" or "dark"');
  if (brand.hub && !/^https?:\/\//.test(brand.hub)) throw new Error('hub must be an http(s) URL');

  let logoFile = null;
  if (!options.noLogo) {
    if (options.logo) logoFile = path.resolve(options.logo);
    else if (guide.organizer_logo) logoFile = path.resolve(root, guide.organizer_logo);
    else { logoFile = DEFAULT_LOGO; brand.logoSurface = 'dark'; if (!brand.organizer) brand.organizer = 'Edukey'; }
  }
  delete brand.logo;
  if (logoFile) brand.logo = logoDataUri(logoFile);
  for (const k of Object.keys(brand)) if (brand[k] === undefined || brand[k] === '') delete brand[k];

  const lang = data.lang || (guide.language === 'en' ? 'en' : 'pl');
  const payload = Object.assign({}, data, { lang, brand });
  const html = fs.readFileSync(TEMPLATE, 'utf8')
    .replace('{{LANG}}', () => lang)
    .replace('{{TITLE}}', () => escapeHtml(data.title + (brand.course ? ` | ${brand.course}` : '')))
    .replace('{{DATA}}', () => scriptSafeJson(payload));
  fs.mkdirSync(path.dirname(path.resolve(options.out)), { recursive: true });
  fs.writeFileSync(options.out, html);
  return { out: path.resolve(options.out), kind: data.kind, lang, logo: logoFile };
}

module.exports = { build, validate, readGuide, scriptSafeJson };

if (require.main === module) {
  try {
    const args = parseArgs(process.argv.slice(2));
    if (args.help) { console.log(USAGE); process.exit(0); }
    if (!args.data || !args.out) { console.error(USAGE); process.exit(2); }
    const r = build(args);
    console.log(`Built ${r.kind} (${r.lang}) -> ${r.out}${r.logo ? `\nLogo: ${r.logo}` : ''}`);
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }
}
