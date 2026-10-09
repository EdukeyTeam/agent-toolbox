const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const YAML = require('yaml');

const workflow = YAML.parse(fs.readFileSync(path.join(__dirname, '../.github/workflows/release-legacy-tools.yml'), 'utf8'));
const gate = workflow.jobs.publish.if;
// This gate uses only equality, Boolean operators and startsWith, whose
// behavior agrees for these fixed GitHub event/ref strings and Boolean inputs.
const cases = [
  ['tag push publishes', 'push', 'refs/tags/legacy-tools-v0.3.0', false, true],
  ['branch push does not publish', 'push', 'refs/heads/main', false, false],
  ['manual branch prepare does not publish', 'workflow_dispatch', 'refs/heads/main', false, false],
  ['manual tag prepare does not publish', 'workflow_dispatch', 'refs/tags/legacy-tools-v0.3.0', false, false],
  ['manual branch explicit publication publishes', 'workflow_dispatch', 'refs/heads/main', true, true],
  ['manual tag explicit publication publishes', 'workflow_dispatch', 'refs/tags/legacy-tools-v0.3.0', true, true],
  ['PR event does not publish', 'pull_request', 'refs/pull/11/merge', false, false],
];
for (const [label, event_name, ref, publish_release, expected] of cases) {
  test(`legacy release: ${label}`, () => {
    const actual = vm.runInNewContext(gate, {
      github: { event_name, ref }, inputs: { publish_release },
      startsWith: (value, prefix) => value.startsWith(prefix),
    }, { timeout: 100 });
    assert.equal(actual, expected);
  });
}
