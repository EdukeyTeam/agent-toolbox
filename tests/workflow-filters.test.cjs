const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const YAML = require('yaml');

const root = path.resolve(__dirname, '..');
const files = {
  node: 'test-skills.yml', python: 'test-python.yml', semantic: 'test-semantic.yml',
  native: 'test-native.yml', package: 'test-plugin.yml', workflow: 'validate-workflows.yml',
};
const workflows = Object.fromEntries(Object.entries(files).map(([key, file]) => {
  const source = path.join(root, '.github/workflows', file);
  return [key, fs.existsSync(source) ? YAML.parse(fs.readFileSync(source, 'utf8')) : null];
}));

// Exercise the simple *, ** and ordered ! patterns used by these YAML files.
// GitHub evaluates them before creating a run; this helper is test-only.
function matches(file, patterns) {
  let included = false;
  for (const pattern of patterns) {
    const negative = pattern.startsWith('!');
    if (path.posix.matchesGlob(file, negative ? pattern.slice(1) : pattern)) included = !negative;
  }
  return included;
}
function selected(paths, event) {
  return Object.entries(workflows).filter(([, workflow]) => {
    if (!workflow) return false;
    const trigger = workflow.on[event];
    return !trigger?.paths || paths.some(file => matches(file, trigger.paths));
  }).map(([key]) => key).sort();
}
const legacy = 'skills/legacy-codebase-workflows/';
const cases = [
  ['repository docs', ['README.md', 'AGENTS.md', 'docs/ci.md', '.github/PULL_REQUEST_TEMPLATE.md'], []],
  ['Rust contributor docs', ['src/legacy-repo-map/README.md'], []],
  ['skill metadata', [legacy + 'SKILL.md'], ['node', 'package']],
  ['skill references', [legacy + 'references/repomix.md', 'skills/write-agents-md/references/web-workflow.md'], ['package']],
  ['legacy intake template', [legacy + 'templates/repository-intake.md'], ['package']],
  ['runtime Markdown template', ['skills/write-agents-md/assets/web-AGENTS.md'], ['node', 'package']],
  ['Node skill code', ['skills/cloudflare-safe/scripts/lib.mjs'], ['node', 'package']],
  ['Rust code and lock', ['src/legacy-repo-map/src/main.rs', 'src/legacy-repo-map/Cargo.lock'], ['native']],
  ['mapper Python', [legacy + 'scripts/repo_map.py'], ['native', 'package', 'python']],
  ['new shared Python helper', [legacy + 'scripts/new_helper.py'], ['native', 'package', 'python', 'semantic']],
  ['shared inference helper', [legacy + 'scripts/legacy_common.py'], ['native', 'package', 'python', 'semantic']],
  ['retrieval discovery', [legacy + 'scripts/repo_files.py'], ['native', 'package', 'python', 'semantic']],
  ['inference lock', [legacy + 'scripts/retrieval/pnpm-lock.yaml'], ['native', 'package', 'python', 'semantic']],
  ['vector requirements', [legacy + 'scripts/requirements-retrieval.txt'], ['native', 'package', 'python', 'semantic']],
  ['parser requirements', [legacy + 'requirements-map.txt'], ['native', 'package', 'python']],
  ['bundled notice', [legacy + 'THIRD_PARTY.md'], ['native', 'package', 'python']],
  ['vendor query', [legacy + 'vendor/queries/tree-sitter-language-pack/java-tags.scm'], ['native', 'package', 'python']],
  ['standalone builder', ['scripts/build-legacy-tools.py'], ['native', 'python']],
  ['native tests', ['tests/test_legacy_native.py'], ['native', 'python']],
  ['retrieval tests', ['tests/test_legacy_retrieval.py'], ['python', 'semantic']],
  ['Node regression', ['tests/cloudflare-safe.test.cjs'], ['node']],
  ['Node package lock', ['package-lock.json'], ['node']],
  ['plugin metadata', ['plugin.json', '.claude-plugin/plugin.json'], ['node', 'package']],
  ['plugin builder', ['scripts/build-claude-plugin.ps1'], ['package']],
  ['native workflow', ['.github/workflows/test-native.yml'], ['native', 'node', 'workflow']],
  ['release workflow', ['.github/workflows/release-legacy-tools.yml'], ['native', 'node', 'workflow']],
  ['release index helper', ['scripts/create-legacy-release-manifest.py'], ['native', 'python']],
  ['distribution policy', [legacy + 'tool-distribution.json'], ['native', 'package', 'python']],
  ['embedded license', ['src/legacy-repo-map/licenses/manifest.json'], ['native']],
  ['root Git ignore rules', ['.gitignore'], []],
  ['vendor checkout attributes', ['.gitattributes'], ['native', 'python']],
  ['ignore rules with documentation', ['.gitignore', 'README.md'], []],
  ['ignore rules with Rust code', ['.gitignore', 'src/legacy-repo-map/src/main.rs'], ['native']],
  ['irrelevant root assets', ['assets/logo.png'], []],
  ['mixed docs and Rust', ['docs/ci.md', 'src/legacy-repo-map/src/main.rs'], ['native']],
];
for (const [label, paths, expected] of cases) {
  test(`built-in CI filters: ${label}`, () => {
    for (const event of ['pull_request', 'push']) assert.deepEqual(selected(paths, event), [...expected].sort(), event);
  });
}

test('all validation workflows have consistent built-in filters, manual runs and isolated concurrency', () => {
  for (const [key, workflow] of Object.entries(workflows)) {
    assert.ok(workflow, key);
    assert.ok(workflow.on.pull_request.paths.length, key);
    assert.deepEqual(workflow.on.push.paths, workflow.on.pull_request.paths, key);
    assert.ok(matches('.github/workflows/' + files[key], workflow.on.pull_request.paths), key);
    assert.deepEqual(workflow.on.push.branches, ['main']);
    assert.ok(Object.hasOwn(workflow.on, 'workflow_dispatch'));
    assert.equal(workflow.concurrency['cancel-in-progress'], "${{ github.event_name == 'pull_request' }}");
    assert.match(workflow.concurrency.group, /github.workflow/);
    for (const job of Object.values(workflow.jobs)) {
      assert.equal(job.needs, undefined); // No runtime routing or cross-workflow dependencies.
    }
  }
  assert.equal(fs.existsSync(path.join(root, 'scripts/ci-changes.cjs')), false);
});
