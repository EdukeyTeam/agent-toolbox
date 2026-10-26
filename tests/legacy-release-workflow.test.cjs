const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
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
