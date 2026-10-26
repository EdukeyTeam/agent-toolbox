const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');
const YAML = require('yaml');

const workflow = YAML.parse(fs.readFileSync(path.join(__dirname, '../.github/workflows/release-legacy-tools.yml'), 'utf8'));
const gate = workflow.jobs.publish.if;
const cases = [
  ['main push publishes missing release', 'push', 'refs/heads/main', false, 'true', true],
  ['main push skips existing release', 'push', 'refs/heads/main', false, 'false', false],
  ['tag push cannot publish', 'push', 'refs/tags/legacy-tools-v0.3.0', false, 'true', false],
  ['feature push cannot publish', 'push', 'refs/heads/feature', false, 'true', false],
  ['manual main prepare does not publish', 'workflow_dispatch', 'refs/heads/main', false, 'true', false],
  ['manual main recovery publishes', 'workflow_dispatch', 'refs/heads/main', true, 'true', true],
  ['manual tag publication rejected', 'workflow_dispatch', 'refs/tags/legacy-tools-v0.3.0', true, 'true', false],
  ['manual feature publication rejected', 'workflow_dispatch', 'refs/heads/feature', true, 'true', false],
  ['PR cannot publish', 'pull_request', 'refs/pull/11/merge', true, 'true', false],
];
for (const [label, event_name, ref, publish_release, build, expected] of cases) {
  test(`legacy release: ${label}`, () => {
    const actual = vm.runInNewContext(gate, {
      github: { event_name, ref }, inputs: { publish_release }, needs: { plan: { outputs: { build } } },
    }, { timeout: 100 });
    assert.equal(actual, expected);
  });
}

test('every main push recovers a missing pin; every PR checks pins without publication', () => {
  assert.deepEqual(workflow.on.push, { branches: ['main'] });
  assert.ok(Object.hasOwn(workflow.on, 'pull_request'));
  assert.equal(workflow.on.pull_request, null);
  assert.equal(workflow.on.workflow_dispatch.inputs.publish_release.default, false);
  assert.equal(workflow.on.workflow_dispatch.inputs.release_tag.default, '');
  const steps = workflow.jobs.contract.steps;
  assert.equal(steps[0].with['fetch-depth'], 0);
  assert.ok(steps.some(step => step.run?.includes('check-legacy-release.py') && step.run.includes('--base')));
  assert.ok(steps.some(step => step.run?.includes('test_legacy_release.py')));
  assert.match(workflow.jobs.plan.if, /github.ref == 'refs\/heads\/main'/);
  assert.deepEqual(workflow.jobs.publish.needs, ['plan', 'build']);
  assert.equal(workflow.jobs.build.needs, 'plan');
  assert.equal(workflow.jobs.build.steps[0].with.ref, '${{ needs.plan.outputs.source_commit }}');
});

test('publication is serialized per version, same-run, and least privilege', () => {
  assert.equal(workflow.concurrency['cancel-in-progress'], false);
  assert.match(workflow.concurrency.group, /github.sha/);
  assert.equal(workflow.jobs.publish.concurrency.group, 'legacy-tools-publish-${{ needs.plan.outputs.release_tag }}');
  assert.equal(workflow.jobs.publish.concurrency['cancel-in-progress'], false);
  assert.deepEqual(workflow.permissions, { contents: 'read' });
  for (const [name, job] of Object.entries(workflow.jobs)) {
    assert.deepEqual(job.permissions, { contents: name === 'publish' ? 'write' : 'read' });
    for (const step of job.steps ?? []) {
      if (step.uses?.startsWith('actions/checkout@')) assert.equal(step.with['persist-credentials'], false);
    }
  }
  assert.deepEqual(workflow.jobs.build.strategy.matrix.include.map(item => item.platform).sort(),
    ['linux-x86_64', 'macos-arm64', 'windows-x86_64']);
  const publish = workflow.jobs.publish.steps.at(-1);
  assert.match(publish.run, /legacy-release.py publish/);
  assert.equal(publish.env.GH_TOKEN, '${{ github.token }}');
});

const contractStep = workflow.jobs.contract.steps.find(step => step.run?.includes('check-legacy-release.py'));
function contractCommands({ pr = '', before = '', missing = false, fetchFails = false } = {}) {
  // Execute the actual workflow Python, recording subprocess calls. Real Git
  // version comparisons and same-version merges are tested in the Python suite.
  const harness = `
import json, os, subprocess, sys, types
calls = []
def run(command, **options):
    calls.append(command)
    if command[1:2] == ['fetch'] and os.environ['FETCH_FAILS'] == '1':
        raise subprocess.CalledProcessError(1, command)
    return types.SimpleNamespace(returncode=int(os.environ['MISSING']) if command[1:2] == ['cat-file'] else 0)
def check_output(command, **options):
    calls.append(command)
    return 'fixture-merge-base\\n'
subprocess.run = run
subprocess.check_output = check_output
try:
    exec(sys.argv[1])
except subprocess.CalledProcessError:
    print(json.dumps(calls))
    sys.exit(1)
print(json.dumps(calls))
`;
  const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const result = spawnSync(python, ['-c', harness, contractStep.run], {
    encoding: 'utf8', env: { ...process.env, PR_BASE: pr, PUSH_BEFORE: before, MISSING: missing ? '1' : '0', FETCH_FAILS: fetchFails ? '1' : '0' },
  });
  assert.ifError(result.error);
  assert.equal(result.stderr, '');
  return { status: result.status, calls: JSON.parse(result.stdout) };
}

test('main push version gate compares directly with previous main, including force pushes', () => {
  assert.equal(contractStep.env.PUSH_BEFORE, '${{ github.event.before }}');
  const before = 'a'.repeat(40);
  for (const missing of [false, true]) {
    const { status, calls } = contractCommands({ before, missing });
    assert.equal(status, 0);
    assert.deepEqual(calls[0], ['git', 'cat-file', '-e', `${before}^{commit}`]);
    assert.equal(calls.some(call => call[1] === 'merge-base'), false);
    assert.deepEqual(calls.at(-1).slice(1), ['scripts/check-legacy-release.py', '--base', before]);
    assert.deepEqual(calls.filter(call => call[1] === 'fetch'), missing ? [['git', 'fetch', '--no-tags', 'origin', before]] : []);
  }
});

test('unavailable force-push base fails closed instead of dropping the version comparison', () => {
  const { status, calls } = contractCommands({ before: 'b'.repeat(40), missing: true, fetchFails: true });
  assert.equal(status, 1);
  assert.equal(calls.some(call => call.includes('scripts/check-legacy-release.py')), false);
});

test('new-branch zero SHA and manual dispatch validate pins without a nonexistent base', () => {
  for (const before of ['', '0'.repeat(40)]) {
    const { status, calls } = contractCommands({ before });
    assert.equal(status, 0);
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].slice(1), ['scripts/check-legacy-release.py']);
  }
});

test('PR version gate retains merge-base comparison', () => {
  assert.equal(contractStep.env.PR_BASE, '${{ github.event.pull_request.base.sha }}');
  const { status, calls } = contractCommands({ pr: 'c'.repeat(40) });
  assert.equal(status, 0);
  assert.deepEqual(calls[0], ['git', 'merge-base', 'c'.repeat(40), 'HEAD']);
  assert.deepEqual(calls.at(-1).slice(1), ['scripts/check-legacy-release.py', '--base', 'fixture-merge-base']);
});
