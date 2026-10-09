const fs = require('node:fs');
const { execFileSync } = require('node:child_process');

const flags = ['node', 'python', 'semantic', 'native', 'package', 'workflow'];
const legacy = 'skills/legacy-codebase-workflows/';
const full = () => Object.fromEntries(flags.map(flag => [flag, true]));
const mapOnlyScripts = new Set(['repo_map.py', 'repo_render.py', 'export_repo_map.py',
  'setup_native.py', 'check_citations.py', 'legacy_tools.py']);

function classifyPaths(paths) {
  const selected = Object.fromEntries(flags.map(flag => [flag, false]));
  const mark = (...names) => names.forEach(name => { selected[name] = true; });
  for (const file of paths) {
    // Changes to routing or the test DAG must exercise every route.
    if (['.github/workflows/test-skills.yml', 'scripts/ci-changes.cjs',
      'tests/ci-changes.test.cjs', '.gitattributes', '.gitignore'].includes(file)) return full();
    if (file === '.github/workflows/release-legacy-tools.yml') {
      mark('workflow', 'node', 'native');
    } else if (file.startsWith('.github/workflows/')) {
      return full();
    } else if (file.startsWith('src/legacy-repo-map/')) {
      if (file !== 'src/legacy-repo-map/README.md') mark('native');
    } else if (file.startsWith(legacy)) {
      mark('package');
      const relative = file.slice(legacy.length);
      if (relative.startsWith('scripts/')) {
        const pythonScript = /^scripts\/([^/]+\.py)$/.exec(relative);
        if (!pythonScript && relative !== 'scripts/requirements-retrieval.txt' &&
          !relative.startsWith('scripts/retrieval/')) return full();
        mark('python', 'native'); // Python scripts/runtime files are bundled by build-legacy-tools.py.
        if (!pythonScript || !mapOnlyScripts.has(pythonScript[1])) mark('semantic');
      } else if (relative.startsWith('vendor/') || ['requirements-map.txt', 'tool-distribution.json',
        'THIRD_PARTY.md', 'LICENSE.txt', 'NOTICE.txt'].includes(relative)) {
        mark('python', 'native');
      } else if (relative !== 'SKILL.md' && !relative.startsWith('references/') &&
        !relative.startsWith('templates/')) {
        return full(); // New runtime inputs need a dependency rule before they can be skipped.
      }
    } else if (file.startsWith('skills/')) {
      mark('package');
      if (!/^skills\/[^/]+\/(SKILL\.md|references\/.*)$/.test(file)) mark('node');
      // Markdown under assets/ is executable template input, not documentation.
    } else if (file.startsWith('tests/test_legacy_')) {
      mark('python');
      if (file === 'tests/test_legacy_retrieval.py') mark('semantic');
      if (file === 'tests/test_legacy_native.py') mark('native');
    } else if (/^tests\/[^/]+\.test\.(cjs|js)$/.test(file)) {
      mark('node');
    } else if (['scripts/build-legacy-tools.py', 'scripts/create-legacy-release-manifest.py'].includes(file)) {
      mark('python', 'native');
    } else if (file === 'scripts/build-claude-plugin.ps1') {
      mark('package');
    } else if (file.startsWith('.claude-plugin/') || file === 'plugin.json') {
      mark('node', 'package');
    } else if (['package.json', 'package-lock.json'].includes(file)) {
      mark('node');
    } else if (file === 'LICENSE') {
      mark('package', 'native');
    } else if (file.startsWith('docs/') || /^([^/]+\.md|\.github\/[^/]+\.md)$/.test(file)) {
      // Root guidance, repository docs and PR templates do not feed code tests.
    } else {
      return full(); // Unknown inputs fail open to validation, never silently lose coverage.
    }
  }
  return selected;
}

function changedPaths(eventName, event, cwd) {
  let comparison;
  const sha = value => typeof value === 'string' && /^[0-9a-f]{40}$/i.test(value) && !/^0+$/.test(value);
  if (eventName === 'pull_request') {
    const base = event.pull_request?.base?.sha;
    const head = event.pull_request?.head?.sha;
    if (!sha(base) || !sha(head)) throw new Error('Missing PR comparison');
    // Compare the whole PR, not just its last docs commit after an untested code change.
    comparison = `${base}...${head}`;
  } else if (eventName === 'push') {
    if (!sha(event.before) || !sha(event.after)) throw new Error('Missing push comparison');
    comparison = `${event.before}..${event.after}`;
  } else {
    throw new Error('Full validation requested or event is not a diff event');
  }
  // No API pagination/300-file limit. Disabling rename detection includes old AND new paths.
  const output = execFileSync('git', ['diff', '--name-only', '--no-renames', '-z', comparison, '--'],
    { cwd, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  return output.split('\0').filter(Boolean);
}

function plan(eventName, event, cwd) {
  if (eventName === 'workflow_dispatch') return { selected: full(), count: null, fallback: false };
  try {
    const paths = changedPaths(eventName, event, cwd);
    return { selected: classifyPaths(paths), count: paths.length, fallback: false };
  } catch {
    // Missing history, initial/force pushes and malformed events must not yield a green skip.
    return { selected: full(), count: null, fallback: true };
  }
}

const jobs = { 'workflow-validation': 'workflow', test: 'python',
  'semantic-retrieval': 'semantic', 'native-artifacts': 'native', 'plugin-package': 'package' };
function statusFailures(needs) {
  const failures = [];
  if (needs.checks?.result !== 'success' ||
    flags.some(flag => !['true', 'false'].includes(needs.checks?.outputs?.[flag]))) failures.push('checks');
  for (const [job, flag] of Object.entries(jobs)) {
    const chosen = needs.checks?.outputs?.[flag];
    const result = needs[job]?.result;
    if (!['true', 'false'].includes(chosen) ||
      (chosen === 'true' ? result !== 'success' : !['skipped', 'success'].includes(result))) failures.push(job);
  }
  return failures;
}

function main() {
  if (process.argv[2] === '--check-status') {
    const failures = statusFailures(JSON.parse(process.env.NEEDS_JSON));
    if (failures.length) throw new Error(`Required validation did not succeed: ${failures.join(', ')}`);
    console.log('All selected validation jobs succeeded.');
    return;
  }
  let result;
  try {
    const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
    result = plan(process.env.GITHUB_EVENT_NAME, event, process.cwd());
  } catch {
    result = { selected: full(), count: null, fallback: true };
  }
  const lines = Object.entries(result.selected).map(([key, value]) => `${key}=${value}`).join('\n') + '\n';
  fs.appendFileSync(process.env.GITHUB_OUTPUT, lines);
  if (result.fallback) console.log('::warning::Changed paths unavailable or full run requested; running all validation.');
  console.log(JSON.stringify(result)); // Counts/Boolean flags only; no untrusted filenames in workflow commands.
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY,
    `## Selected validation\n\nChanged paths: ${result.count ?? 'unknown/full run'}\n\n` +
    Object.entries(result.selected).map(([key, value]) => `- ${key}: ${value ? 'run' : 'skip'}`).join('\n') + '\n');
}

module.exports = { classifyPaths, changedPaths, plan, statusFailures, flags };
if (require.main === module) main();
