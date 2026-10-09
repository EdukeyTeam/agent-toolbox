const assert = require('node:assert/strict');
const { execFileSync, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const YAML = require('yaml');
const { classifyPaths, changedPaths, plan, statusFailures, flags } = require('../scripts/ci-changes.cjs');

const cases = [
  ['root documentation', ['README.md', 'docs/ci.md'], []],
  ['skill instructions and references', ['skills/legacy-codebase-workflows/SKILL.md',
    'skills/legacy-codebase-workflows/references/repomix.md'], ['package']],
  ['Rust source', ['src/legacy-repo-map/src/render.rs'], ['native']],
  ['Rust lockfile', ['src/legacy-repo-map/Cargo.lock'], ['native']],
  ['Rust contributor README', ['src/legacy-repo-map/README.md'], []],
  ['Python mapper', ['skills/legacy-codebase-workflows/scripts/repo_map.py'], ['python', 'native', 'package']],
  ['shared discovery helper', ['skills/legacy-codebase-workflows/scripts/repo_files.py'], ['python', 'native', 'semantic', 'package']],
  ['new shared Python helper', ['skills/legacy-codebase-workflows/scripts/new_helper.py'], ['python', 'native', 'semantic', 'package']],
  ['unexpected script input', ['skills/legacy-codebase-workflows/scripts/new_config.json'], flags],
  ['inference helper', ['skills/legacy-codebase-workflows/scripts/legacy_common.py'], ['python', 'native', 'semantic', 'package']],
  ['retrieval backend', ['skills/legacy-codebase-workflows/scripts/context7_backend.py'], ['python', 'native', 'semantic', 'package']],
  ['inference runtime lock', ['skills/legacy-codebase-workflows/scripts/retrieval/pnpm-lock.yaml'], ['python', 'native', 'semantic', 'package']],
  ['vector dependencies', ['skills/legacy-codebase-workflows/scripts/requirements-retrieval.txt'], ['python', 'native', 'semantic', 'package']],
  ['parser dependencies', ['skills/legacy-codebase-workflows/requirements-map.txt'], ['python', 'native', 'package']],
  ['queries and licenses', ['skills/legacy-codebase-workflows/vendor/queries/tree-sitter-language-pack/java-tags.scm'], ['python', 'native', 'package']],
  ['bundled Markdown notice', ['skills/legacy-codebase-workflows/THIRD_PARTY.md'], ['python', 'native', 'package']],
  ['distribution policy', ['skills/legacy-codebase-workflows/tool-distribution.json'], ['python', 'native', 'package']],
  ['standalone builder', ['scripts/build-legacy-tools.py'], ['python', 'native']],
  ['release index helper', ['scripts/create-legacy-release-manifest.py'], ['python', 'native']],
  ['release workflow', ['.github/workflows/release-legacy-tools.yml'], ['workflow', 'node', 'native']],
  ['Node package lock', ['package-lock.json'], ['node']],
  ['other skill code', ['skills/cloudflare-safe/scripts/cf-read.mjs'], ['node', 'package']],
  ['Markdown runtime template', ['skills/write-agents-md/assets/web-AGENTS.md'], ['node', 'package']],
  ['ordinary Node test', ['tests/decode-binary-assets.test.cjs'], ['node']],
  ['mapper regression', ['tests/test_legacy_map.py'], ['python']],
  ['native regression', ['tests/test_legacy_native.py'], ['python', 'native']],
  ['retrieval regression', ['tests/test_legacy_retrieval.py'], ['python', 'semantic']],
  ['plugin manifests', ['plugin.json', '.claude-plugin/plugin.json'], ['node', 'package']],
  ['plugin builder', ['scripts/build-claude-plugin.ps1'], ['package']],
  ['routing change', ['scripts/ci-changes.cjs'], flags],
  ['routing regression', ['tests/ci-changes.test.cjs'], flags],
  ['test workflow', ['.github/workflows/test-skills.yml'], flags],
  ['Git checkout policy', ['.gitattributes'], flags],
  ['unrecognized new runtime', ['src/new-runtime/main.ts'], flags],
  ['unrecognized legacy runtime', ['skills/legacy-codebase-workflows/runtime/config.json'], flags],
  ['mixed changes', ['README.md', 'src/legacy-repo-map/src/main.rs', 'tests/cloudflare-safe.test.cjs'], ['native', 'node']],
  ['empty diff', [], []],
];
for (const [label, paths, expected] of cases) {
  test(`CI routing: ${label}`, () => {
    const actual = classifyPaths(paths);
    assert.deepEqual(Object.keys(actual).filter(flag => actual[flag]).sort(), [...expected].sort());
  });
}

function fixture(t) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-routing-'));
  t.after(() => {
    assert.equal(path.dirname(path.resolve(cwd)), path.resolve(os.tmpdir()));
    fs.rmSync(cwd, { recursive: true, force: true });
  });
  const git = (...args) => execFileSync('git', args, { cwd, encoding: 'utf8' }).trim();
  git('init', '-q', '-b', 'main');
  git('config', 'user.name', 'CI Fixture'); git('config', 'user.email', 'ci@example.invalid');
  const write = (file, content = 'example\n') => {
    fs.mkdirSync(path.dirname(path.join(cwd, file)), { recursive: true });
    fs.writeFileSync(path.join(cwd, file), content);
  };
  const commit = files => { git('add', '--', ...files); git('commit', '-qm', 'fixture'); return git('rev-parse', 'HEAD'); };
  write('README.md'); const base = commit(['README.md']);
  return { cwd, git, write, commit, base };
}

test('PR cumulative diff retains code changes when the newest commit changes only docs', t => {
  const f = fixture(t);
  f.write('src/legacy-repo-map/src/main.rs'); f.commit(['src/legacy-repo-map/src/main.rs']);
  f.write('README.md', 'updated docs\n'); const head = f.commit(['README.md']);
  const result = plan('pull_request', { pull_request: { base: { sha: f.base }, head: { sha: head } } }, f.cwd);
  assert.equal(result.fallback, false); assert.equal(result.selected.native, true);
});

test('PR merge-base comparison excludes unrelated base-branch changes', t => {
  const f = fixture(t);
  f.git('checkout', '-qb', 'feature'); f.write('docs/guide.md'); const head = f.commit(['docs/guide.md']);
  f.git('checkout', '-q', 'main'); f.write('src/legacy-repo-map/src/main.rs'); const base = f.commit(['src/legacy-repo-map/src/main.rs']);
  assert.deepEqual(changedPaths('pull_request', { pull_request: { base: { sha: base }, head: { sha: head } } }, f.cwd), ['docs/guide.md']);
});

test('push diff includes both paths of a rename, plus deletions and space-containing filenames', t => {
  const f = fixture(t); const old = 'src/legacy-repo-map/src/removed.rs';
  f.write(old); const before = f.commit([old]);
  const renamed = 'docs/renamed.md'; f.write(renamed); fs.unlinkSync(path.join(f.cwd, old));
  const odd = 'docs/space in filename.md'; f.write(odd);
  const after = f.commit([old, renamed, odd]);
  const paths = changedPaths('push', { before, after }, f.cwd);
  assert.ok(paths.includes(old)); assert.ok(paths.includes(renamed)); assert.ok(paths.includes(odd));
  assert.equal(classifyPaths(paths).native, true);
});

test('NUL-delimited diff preserves POSIX newline filenames', { skip: process.platform === 'win32' }, t => {
  const f = fixture(t); const odd = 'docs/space and\nnewline.md'; f.write(odd);
  const head = f.commit([odd]);
  assert.deepEqual(changedPaths('push', { before: f.base, after: head }, f.cwd), [odd]);
});

test('diff is not truncated after 300 paths', t => {
  const f = fixture(t); const files = Array.from({ length: 305 }, (_, i) => `docs/page-${i}.md`);
  files.push('src/legacy-repo-map/src/main.rs'); files.forEach(file => f.write(file));
  const head = f.commit(files); const paths = changedPaths('push', { before: f.base, after: head }, f.cwd);
  assert.equal(paths.length, 306); assert.equal(classifyPaths(paths).native, true);
});

test('missing history, initial pushes, malformed SHA and manual runs select full coverage', t => {
  const f = fixture(t);
  for (const [eventName, event] of [
    ['push', { before: '0'.repeat(40), after: f.base }],
    ['push', { before: 'f'.repeat(40), after: f.base }],
    ['pull_request', { pull_request: { base: { sha: 'main;exit 0' }, head: { sha: f.base } } }],
    ['workflow_dispatch', {}], ['merge_group', {}],
  ]) assert.deepEqual(plan(eventName, event, f.cwd).selected, Object.fromEntries(flags.map(flag => [flag, true])));
});

const workflow = YAML.parse(fs.readFileSync(path.join(__dirname, '../.github/workflows/test-skills.yml'), 'utf8'));
const jobFlags = { 'workflow-validation': 'workflow', test: 'python', 'semantic-retrieval': 'semantic',
  'native-artifacts': 'native', 'plugin-package': 'package' };
test('the workflow dispatches exactly the jobs selected for each changed dependency', () => {
  for (const [, paths] of cases) {
    const selected = classifyPaths(paths);
    const needs = { checks: { result: 'success', outputs: Object.fromEntries(flags.map(flag => [flag, String(selected[flag])])) } };
    for (const [job, flag] of Object.entries(jobFlags)) {
      assert.equal(workflow.jobs[job].needs, 'checks');
      assert.equal(vm.runInNewContext(workflow.jobs[job].if, { needs }, { timeout: 100 }), selected[flag], job);
    }
  }
});

function results(selected = {}) {
  const needs = { checks: { result: 'success', outputs: Object.fromEntries(flags.map(flag => [flag, String(Boolean(selected[flag]))])) } };
  for (const [job, flag] of Object.entries(jobFlags)) needs[job] = { result: selected[flag] ? 'success' : 'skipped' };
  return needs;
}
test('stable status accepts intentionally skipped jobs, but rejects failed/cancelled/missing selected jobs', () => {
  assert.deepEqual(statusFailures(results()), []);
  assert.deepEqual(statusFailures(results({ native: true })), []);
  for (const state of ['failure', 'cancelled', 'skipped', undefined]) {
    const needs = results({ native: true }); needs['native-artifacts'].result = state;
    assert.ok(statusFailures(needs).includes('native-artifacts'));
  }
  const needs = results(); needs.checks.result = 'failure'; assert.ok(statusFailures(needs).includes('checks'));
  const missing = results(); delete missing.checks.outputs.node; assert.ok(statusFailures(missing).includes('checks'));
});

test('workflow retains an always-run final status and cancels only superseded PR runs', () => {
  assert.ok(workflow.jobs['ci-status'].needs.includes('checks'));
  for (const job of Object.keys(jobFlags)) assert.ok(workflow.jobs['ci-status'].needs.includes(job));
  assert.equal(workflow.jobs['ci-status'].if, '${{ always() }}');
  assert.equal(workflow.concurrency['cancel-in-progress'], "${{ github.event_name == 'pull_request' }}");
  assert.equal(workflow.on.pull_request, null); // No workflow-level paths filters that strand required checks.
});

test('router CLI safely emits Boolean outputs and fails open on unreadable events', t => {
  const f = fixture(t); const output = path.join(f.cwd, 'outputs');
  const actual = spawnSync(process.execPath, [path.resolve(__dirname, '../scripts/ci-changes.cjs')], {
    cwd: f.cwd, encoding: 'utf8', env: { ...process.env, GITHUB_EVENT_PATH: path.join(f.cwd, 'missing.json'),
      GITHUB_EVENT_NAME: 'pull_request', GITHUB_OUTPUT: output, GITHUB_STEP_SUMMARY: path.join(f.cwd, 'summary') },
  });
  assert.equal(actual.status, 0, actual.stderr);
  assert.equal(fs.readFileSync(output, 'utf8'), flags.map(flag => `${flag}=true\n`).join(''));
  assert.match(actual.stdout, /running all validation/);
});
