const { spawnSync } = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

test('offline dashboard inline JavaScript compiles, including Unicode escaping', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../skills/agent-usage-analytics/assets/dashboard.html'), 'utf8');
  const scripts = [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new vm.Script(scripts[0][1]));
});

test('agent usage analytics: Python accounting, adapters and CLI contracts', () => {
  const python = process.platform === 'win32' ? 'python' : 'python3';
  const result = spawnSync(python, ['-m', 'unittest', 'discover', '-s', 'tests/usage-analytics', '-p', 'test_*.py'], {
    cwd: path.resolve(__dirname, '..'), encoding: 'utf8', timeout: 120000,
  });
  assert.equal(result.error, undefined, `Python 3.11+ is required: ${result.error?.message}`);
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
