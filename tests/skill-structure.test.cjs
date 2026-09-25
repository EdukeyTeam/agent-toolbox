const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const skillsDir = path.resolve(__dirname, '../skills');
const skillFolders = fs.readdirSync(skillsDir, { withFileTypes: true })
  .filter(entry => entry.isDirectory())
  .map(entry => entry.name);

test('the repository contains skills', () => {
  assert.ok(skillFolders.length > 0);
});

for (const folder of skillFolders) {
  test(`${folder} has matching name and a description`, () => {
    const skillFile = path.join(skillsDir, folder, 'SKILL.md');
    assert.ok(fs.existsSync(skillFile), `${skillFile} is missing`);

    const content = fs.readFileSync(skillFile, 'utf8');
    const frontmatter = content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
    assert.ok(frontmatter, `${skillFile} needs YAML frontmatter`);

    const name = frontmatter[1].match(/^name:\s*(.+)$/m)?.[1]?.trim();
    const description = frontmatter[1].match(/^description:\s*(.+)$/m)?.[1]?.trim();
    assert.equal(name, folder, `${skillFile} name must match its folder`);
    assert.ok(description, `${skillFile} needs a description`);
  });
}
