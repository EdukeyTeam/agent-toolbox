const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const read = (file) => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));

test('portable and Claude manifests describe the same plugin', () => {
  const portable = read('plugin.json');
  const claude = read('.claude-plugin/plugin.json');
  const marketplace = read('.claude-plugin/marketplace.json');

  assert.equal(portable.$schema, 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json');
  assert.equal(portable.name, 'agent-toolbox');
  assert.equal(claude.name, portable.name);
  assert.equal(claude.version, portable.version);
  assert.equal(claude.description, portable.description);
  assert.equal(claude.repository, portable.repository);
  assert.equal(marketplace.owner.name, 'Edukey');
  assert.equal(marketplace.plugins.length, 1);
  assert.equal(marketplace.plugins[0].name, portable.name);
  assert.deepEqual(marketplace.plugins[0].source, {
    source: 'github',
    repo: 'EdukeyTeam/agent-toolbox',
  });
});
