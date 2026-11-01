const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const YAML = require('yaml');

test('semantic matrix stops when any native suite fails', t => {
  const workflow = YAML.parse(fs.readFileSync('.github/workflows/test-semantic.yml', 'utf8'));
  const step = workflow.jobs['semantic-retrieval'].steps.find(step => step.name === 'Test actual local embeddings and hybrid retrieval');
  assert.equal(step.shell, 'bash');
  assert.match(step.run, /^\s*set -e\s*$/m);
  assert.equal(step.run.match(/python -m unittest discover/g).length, 4);
  const probe = spawnSync('bash', ['--version'], { encoding: 'utf8' });
  if (probe.error) return t.skip('bash unavailable; workflow structure verified');
  for (let failure = 0; failure < 4; failure++) {
    let suite = 0;
    const script = step.run.replace(/^\s*python -m unittest discover[^\n]*/gm, () => suite++ === failure ? 'false' : 'true') + '\nprintf unreachable';
    const result = spawnSync('bash', ['-c', script], { encoding: 'utf8' });
    assert.notEqual(result.status, 0, `suite ${failure + 1} must fail CI`);
    assert.doesNotMatch(result.stdout, /unreachable/);
  }
});
