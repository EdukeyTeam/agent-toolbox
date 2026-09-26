const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const YAML = require('yaml');

const skillsDir = path.resolve(__dirname, '../skills');
const skillFolders = fs.readdirSync(skillsDir, { withFileTypes: true })
  .filter(entry => entry.isDirectory())
  .map(entry => entry.name);

function validateMetadata(folder, content) {
  const frontmatter = content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  assert.ok(frontmatter, `${folder} needs YAML frontmatter`);

  const metadata = YAML.parse(frontmatter[1], { uniqueKeys: true });
  assert.ok(metadata && typeof metadata === 'object' && !Array.isArray(metadata),
    `${folder} frontmatter must contain metadata fields`);
  assert.equal(metadata.name, folder, `${folder} name must match its folder`);
  assert.ok(typeof metadata.description === 'string' && metadata.description.trim(),
    `${folder} needs a description`);
}

test('the repository contains skills', () => {
  assert.ok(skillFolders.length > 0);
});

test('accepts a quoted YAML name and folded description', () => {
  assert.doesNotThrow(() => validateMetadata('write-adr', [
    '---',
    'name: "write-adr"',
    'description: >-',
    '  Create a decision record.',
    '---',
  ].join('\n')));
});

test('rejects an empty folded description', () => {
  assert.throws(() => validateMetadata('write-adr', [
    '---',
    'name: write-adr',
    'description: >-',
    '---',
  ].join('\n')), /description/);
});

for (const folder of skillFolders) {
  test(`${folder} has matching name and a description`, () => {
    const skillFile = path.join(skillsDir, folder, 'SKILL.md');
    assert.ok(fs.existsSync(skillFile), `${skillFile} is missing`);

    const content = fs.readFileSync(skillFile, 'utf8');
    validateMetadata(folder, content);
  });
}
