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

test('Codex marketplace reuses the portable plugin and all its skills', () => {
  const portable = read('plugin.json');
  const marketplace = read('.agents/plugins/marketplace.json');
  const claudeMarketplace = read('.claude-plugin/marketplace.json');

  assert.equal(marketplace.name, claudeMarketplace.name);
  assert.equal(marketplace.plugins.length, 1);
  const plugin = marketplace.plugins[0];
  for (const field of ['name', 'version', 'description', 'repository']) {
    assert.equal(plugin[field], portable[field], `Codex ${field} must match plugin.json`);
  }
  assert.deepEqual(plugin.author, portable.author);
  assert.deepEqual(plugin.source, { source: 'local', path: './' });
  assert.deepEqual(plugin.policy, { installation: 'AVAILABLE', authentication: 'ON_INSTALL' });
  assert.equal(plugin.category, 'Productivity');

  const pluginRoot = path.resolve(root, plugin.source.path);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(pluginRoot, 'plugin.json'), 'utf8')), portable);
  const skillNames = fs.readdirSync(path.join(pluginRoot, 'skills'), { withFileTypes: true })
    .filter((entry) => entry.isDirectory()).map((entry) => entry.name);
  assert.ok(skillNames.length > 0);
  for (const name of skillNames) {
    assert.ok(fs.existsSync(path.join(pluginRoot, 'skills', name, 'SKILL.md')), `${name} must be discoverable`);
  }
  assert.equal(fs.existsSync(path.join(pluginRoot, '.codex-plugin', 'plugin.json')), false,
    'Codex must use the portable manifest without a second manifest overlay');
});
