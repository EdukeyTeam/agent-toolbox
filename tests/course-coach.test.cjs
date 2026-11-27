const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { execFileSync } = require('node:child_process');

const script = path.resolve(__dirname, '../skills/course-coach/scripts/build-learning-aid.cjs');
const { build, validate, readGuide } = require(script);
const fixtures = path.join(__dirname, 'fixtures', 'course-coach');

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'course-coach-'));
}

function writeJson(dir, value) {
  const file = path.join(dir, 'aid.json');
  fs.writeFileSync(file, JSON.stringify(value));
  return file;
}

function embedded(html) {
  const m = html.match(/<script type="application\/json" id="aid-data">([\s\S]*?)<\/script>/);
  assert.ok(m, 'data block is present');
  return JSON.parse(m[1]);
}

const samples = {
  flashcards: { kind: 'flashcards', title: 'Hooks', cards: [{ front: 'What runs after an edit?', back: 'A `PostToolUse` hook' }] },
  quiz: { kind: 'quiz', title: 'Quiz', questions: [{ question: 'Where do deny rules go?', options: ['AGENTS.md', 'settings.json'], answer: 1 }] },
  cheatsheet: { kind: 'cheatsheet', title: 'Sheet', sections: [{ title: 'Git', items: [{ term: 'status', code: 'git status' }] }] },
};

test('reads course guide frontmatter with quotes, comments and lists', () => {
  const g = readGuide(path.join(fixtures, 'COURSE-GUIDE.md'));
  assert.equal(g.course, 'Example course');
  assert.equal(g.organizer_logo, 'assets/logo.svg');
  assert.deepEqual(g.tools, ['Claude Code', 'Codex CLI']);
});

for (const [kind, data] of Object.entries(samples)) {
  test(`builds a ${kind} aid with the guide's brand`, () => {
    const dir = tmp();
    const out = path.join(dir, 'out', `${kind}.html`);
    build({ data: writeJson(dir, data), out, guide: path.join(fixtures, 'COURSE-GUIDE.md'), root: fixtures });
    const html = fs.readFileSync(out, 'utf8');
    const payload = embedded(html);
    assert.equal(payload.kind, kind);
    assert.equal(payload.lang, 'en', 'language comes from the guide');
    assert.equal(payload.brand.organizer, 'Example Training');
    assert.equal(payload.brand.logoSurface, 'light');
    assert.match(payload.brand.logo, /^data:image\/svg\+xml;base64,/);
    assert.match(html, /<title>.* \| Example course<\/title>/);
    assert.doesNotMatch(html, /\{\{[A-Z]+\}\}/, 'no unresolved placeholders');
  });
}

test('falls back to the Edukey logo and Polish labels without a guide', () => {
  const dir = tmp();
  const out = path.join(dir, 'a.html');
  build({ data: writeJson(dir, samples.quiz), out });
  const payload = embedded(fs.readFileSync(out, 'utf8'));
  assert.equal(payload.lang, 'pl');
  assert.equal(payload.brand.organizer, 'Edukey');
  assert.equal(payload.brand.logoSurface, 'dark');
  assert.ok(payload.brand.logo.startsWith('data:image/svg+xml;base64,'));
});

test('--no-logo omits the logo', () => {
  const dir = tmp();
  const out = path.join(dir, 'a.html');
  build({ data: writeJson(dir, samples.cheatsheet), out, noLogo: true });
  assert.equal(embedded(fs.readFileSync(out, 'utf8')).brand.logo, undefined);
});

test('data cannot break out of the script element or the title', () => {
  const dir = tmp();
  const out = path.join(dir, 'a.html');
  const evil = '</script><script>alert(1)</script><!--';
  build({ data: writeJson(dir, { kind: 'flashcards', title: `<b>${evil}`, cards: [{ front: evil, back: '$& $1 ok' }] }), out, noLogo: true });
  const html = fs.readFileSync(out, 'utf8');
  assert.equal((html.match(/<script/g) || []).length, 2, 'only the template scripts exist');
  assert.doesNotMatch(html, /<!--/);
  const payload = embedded(html);
  assert.equal(payload.cards[0].front, evil);
  assert.equal(payload.cards[0].back, '$& $1 ok', 'replacement patterns are not expanded');
  assert.match(html, /<title>&lt;b&gt;&lt;\/script&gt;/);
});

test('validation reports every problem with its location', () => {
  assert.deepEqual(validate(samples.quiz), []);
  const errors = validate({ kind: 'quiz', title: 'x', lang: 'de', questions: [
    { question: 'q', options: ['a', 'b'], answer: 2 },
    { question: '', options: ['only'], answer: 0 },
  ] });
  assert.ok(errors.includes('lang must be "pl" or "en"'));
  assert.ok(errors.some(e => e.startsWith('questions[0].answer')));
  assert.ok(errors.includes('questions[1].question is required'));
  assert.ok(errors.some(e => e.startsWith('questions[1].options')));
  assert.ok(validate({ kind: 'slides', title: 't' })[0].startsWith('kind must be one of'));
  assert.ok(validate({ kind: 'cheatsheet', title: 't', sections: [{ title: 's', items: [{ term: 't' }] }] })
    .includes('sections[0].items[0] needs text or code'));
});

test('rejects script URLs in sources and hub', () => {
  const bad = { ...samples.flashcards, cards: [{ front: 'f', back: 'b', sourceUrl: 'javascript:alert(1)' }] };
  assert.ok(validate(bad).some(e => e.includes('sourceUrl')));
  assert.deepEqual(validate({ ...samples.flashcards, cards: [{ front: 'f', back: 'b', sourceUrl: 'course-materials/x.md#a' }] }), []);
  const dir = tmp();
  assert.throws(() => build({ data: writeJson(dir, { ...samples.quiz, brand: { hub: 'javascript:alert(1)' } }), out: path.join(dir, 'a.html'), noLogo: true }), /hub/);
});

test('CLI exits non-zero with a readable error for invalid data', () => {
  const dir = tmp();
  const data = writeJson(dir, { kind: 'quiz', title: 'x', questions: [] });
  assert.throws(() => execFileSync(process.execPath, [script, '--data', data, '--out', path.join(dir, 'a.html')], { stdio: 'pipe' }),
    err => err.status === 1 && /questions must be a non-empty array/.test(err.stderr.toString()));
});

test('CLI builds a file and prints its path', () => {
  const dir = tmp();
  const out = path.join(dir, 'f.html');
  const stdout = execFileSync(process.execPath, [script, '--data', writeJson(dir, samples.flashcards), '--out', out, '--logo', path.join(fixtures, 'assets', 'logo.svg'), '--logo-surface', 'light']).toString();
  assert.match(stdout, /Built flashcards \(pl\)/);
  assert.ok(fs.existsSync(out));
});

test('toolbar uses the course SVG icons for theme and print', () => {
  const dir = tmp();
  const out = path.join(dir, 'a.html');
  build({ data: writeJson(dir, samples.quiz), out, noLogo: true });
  const html = fs.readFileSync(out, 'utf8');
  assert.match(html, /<button type="button" class="icon-btn" id="theme"><svg aria-hidden="true" class="icon-sun"[\s\S]*?class="icon-moon"/);
  assert.match(html, /id="print"><svg aria-hidden="true"[^>]*><polyline points="6 9 6 2 18 2 18 9">/);
});
