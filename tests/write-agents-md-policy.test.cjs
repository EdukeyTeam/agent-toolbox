const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const assets = path.resolve(__dirname, '../skills/write-agents-md/assets');

function section(text, heading) {
  const start = text.indexOf(`### ${heading}`);
  assert.notEqual(start, -1, `missing section: ${heading}`);
  const next = text.indexOf('\n### ', start + 4);
  return text.slice(start, next === -1 ? undefined : next);
}

for (const workflow of ['web', 'desktop']) {
  const template = fs.readFileSync(path.join(assets, `${workflow}-AGENTS.md`), 'utf8');

  test(`${workflow} template keeps the seven-step Manual QA procedure`, () => {
    const qa = section(template, 'Manual QA');
    for (let step = 1; step <= 7; step += 1) {
      assert.match(qa, new RegExp(`^${step}\\. \\S`, 'm'), `Manual QA step ${step} missing`);
    }
    assert.match(qa, /startup separately from/i);
    assert.match(qa, /cancellation and relevant error paths/i);
    assert.match(qa, /persisted results/i);
    assert.match(qa, /packaged build/i);
    assert.match(qa, /\{\{SCREENSHOTS_PATH\}\}/);
    assert.match(qa, /logs/i);
    assert.match(qa, /remains unverified/i);
  });

  test(`${workflow} template keeps the endpoint-first mock contract`, () => {
    const mocks = section(template, 'Test Strategy');
    assert.match(mocks, /#### Endpoint and database mocks/);
    assert.match(mocks, /fresh real query/i);
    assert.match(mocks, /complete response verbatim/i);
    assert.match(mocks, /never documentation or invented objects/i);
    assert.match(mocks, /provenance separately without secrets/i);
    assert.match(mocks, /Existing fixtures do not replace a fresh capture/i);
    assert.match(mocks, /Documentation can be outdated/i);
    assert.match(mocks, /Zero mocks/);
  });
}
