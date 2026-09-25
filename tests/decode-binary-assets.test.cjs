const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const decoder = path.resolve(__dirname, '../skills/create-design-system/scripts/decode-binary-assets.cjs');
const asset = Buffer.alloc(128, 65).toString('base64');

function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-toolbox-decoder-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const output = path.join(dir, 'assets');
  return {
    dir,
    output,
    run(data) {
      const input = path.join(dir, 'input.json');
      fs.writeFileSync(input, JSON.stringify(data));
      return spawnSync(process.execPath, [decoder, input, output], { encoding: 'utf8' });
    },
  };
}

test('writes a valid nested asset inside the selected folder', t => {
  const { output, run } = fixture(t);
  const result = run({ 'fonts/example/font.woff2': asset });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.statSync(path.join(output, 'fonts/example/font.woff2')).size, 128);
});

test('rejects traversal before writing any assets', t => {
  const { dir, output, run } = fixture(t);
  const result = run({ 'favicon.ico': asset, '../escaped.bin': asset });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /unsafe asset path/);
  assert.equal(fs.existsSync(path.join(dir, 'escaped.bin')), false);
  assert.equal(fs.existsSync(path.join(output, 'favicon.ico')), false);
});

test('rejects an output subdirectory that is a symlink', t => {
  const { dir, output, run } = fixture(t);
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(output);
  fs.mkdirSync(outside);
  try { fs.symlinkSync(outside, path.join(output, 'fonts'), 'dir'); }
  catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) return t.skip('symlinks unavailable');
    throw error;
  }
  const result = run({ 'fonts/font.woff2': asset });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /unsafe output directory/);
  assert.equal(fs.existsSync(path.join(outside, 'font.woff2')), false);
});

test('rejects an existing output file that is a symlink', t => {
  const { dir, output, run } = fixture(t);
  const outside = path.join(dir, 'outside.bin');
  fs.mkdirSync(output);
  fs.writeFileSync(outside, 'untouched');
  try { fs.symlinkSync(outside, path.join(output, 'favicon.ico')); }
  catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) return t.skip('symlinks unavailable');
    throw error;
  }
  const result = run({ 'favicon.ico': asset });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /unsafe output file/);
  assert.equal(fs.readFileSync(outside, 'utf8'), 'untouched');
});

test('rejects an existing output file that is hard-linked elsewhere', t => {
  const { dir, output, run } = fixture(t);
  const outside = path.join(dir, 'outside.bin');
  fs.mkdirSync(output);
  fs.writeFileSync(outside, 'untouched');
  try { fs.linkSync(outside, path.join(output, 'favicon.ico')); }
  catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) return t.skip('hard links unavailable');
    throw error;
  }
  const result = run({ 'favicon.ico': asset });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /unsafe output file/);
  assert.equal(fs.readFileSync(outside, 'utf8'), 'untouched');
});
