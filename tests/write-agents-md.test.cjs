const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const skillRoot = path.resolve(__dirname, '../skills/write-agents-md');
const script = path.join(skillRoot, 'scripts/copy_template.py');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'agents-copy-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const project = path.join(directory, 'project with spaces — ć');
  fs.mkdirSync(project);
  return { directory, project };
}

function run(project, workflow = 'web', extra = []) {
  return spawnSync(python, [script, '--workflow', workflow, '--project-root', project, ...extra],
    { encoding: 'utf8', timeout: 10000 });
}

for (const workflow of ['web', 'desktop']) {
  test(`${workflow} copies canonical bytes and emits a verifiable receipt`, t => {
    const { project } = fixture(t);
    const source = fs.readFileSync(path.join(skillRoot, 'assets', `${workflow}-AGENTS.md`));
    const result = run(project, workflow);
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    const receipt = JSON.parse(result.stdout);
    assert.deepEqual(fs.readFileSync(path.join(project, 'AGENTS.md.candidate')), source);
    assert.equal(fs.existsSync(path.join(project, 'AGENTS.md')), false);
    assert.equal(receipt.sha256, crypto.createHash('sha256').update(source).digest('hex'));
    assert.equal(fs.realpathSync.native(receipt.destination), fs.realpathSync.native(path.join(project, 'AGENTS.md.candidate')));
    assert.deepEqual(fs.readFileSync(path.join(skillRoot, 'assets', `${workflow}-AGENTS.md`)), source);
  });
}

test('nested scope copies the original template without writing root guidance', t => {
  const { project } = fixture(t);
  fs.mkdirSync(path.join(project, 'tests'));
  const result = run(project, 'desktop', ['--scope', 'tests']);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(fs.readFileSync(path.join(project, 'tests', 'AGENTS.md.candidate')),
    fs.readFileSync(path.join(skillRoot, 'assets', 'desktop-AGENTS.md')));
  assert.equal(fs.existsSync(path.join(project, 'AGENTS.md')), false);
});

test('existing AGENTS.md is preserved while a candidate is staged by default', t => {
  const { project } = fixture(t);
  fs.writeFileSync(path.join(project, 'AGENTS.md'), 'Human instructions\n');
  const result = run(project);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(fs.readFileSync(path.join(project, 'AGENTS.md.candidate')),
    fs.readFileSync(path.join(skillRoot, 'assets/web-AGENTS.md')));
  assert.equal(fs.readFileSync(path.join(project, 'AGENTS.md'), 'utf8'), 'Human instructions\n');
});

test('candidate mode preserves original and refuses candidate overwrite', t => {
  const { project } = fixture(t);
  fs.writeFileSync(path.join(project, 'AGENTS.md'), 'Human instructions\n');
  assert.equal(run(project, 'web', ['--candidate']).status, 0);
  const candidate = path.join(project, 'AGENTS.md.candidate');
  const bytes = fs.readFileSync(candidate);
  assert.deepEqual(bytes, fs.readFileSync(path.join(skillRoot, 'assets', 'web-AGENTS.md')));
  const second = run(project, 'desktop', ['--candidate']);
  assert.notEqual(second.status, 0);
  assert.match(second.stderr, /exists|overwrite/i);
  assert.deepEqual(fs.readFileSync(candidate), bytes);
  assert.equal(fs.readFileSync(path.join(project, 'AGENTS.md'), 'utf8'), 'Human instructions\n');
});

test('rejects traversal and absolute scopes without out-of-project writes', t => {
  const { directory, project } = fixture(t);
  const outside = path.join(directory, 'outside');
  fs.mkdirSync(outside);
  for (const scope of ['../outside', outside]) {
    const result = run(project, 'web', ['--scope', scope]);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /scope|outside|relative/i);
    assert.deepEqual(fs.readdirSync(outside), []);
  }
});

test('missing scope and invalid workflow create no folders/files', t => {
  const { project } = fixture(t);
  const missing = run(project, 'web', ['--scope', 'missing']);
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /directory|exist/i);
  const invalid = run(project, 'mobile');
  assert.notEqual(invalid.status, 0);
  assert.match(invalid.stderr, /invalid choice/i);
  assert.deepEqual(fs.readdirSync(project), []);
});

test('rejects a directory symlink escaping the project', t => {
  const { directory, project } = fixture(t);
  const outside = path.join(directory, 'outside');
  fs.mkdirSync(outside);
  try {
    fs.symlinkSync(outside, path.join(project, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) {
      t.skip('This runner cannot create the symlink fixture');
      return;
    }
    throw error;
  }
  const result = run(project, 'desktop', ['--scope', 'linked']);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /outside|scope/i);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('does not follow dangling destination symlinks', t => {
  const { directory, project } = fixture(t);
  const target = path.join(directory, 'uncreated.md');
  const destination = path.join(project, 'AGENTS.md.candidate');
  try {
    fs.symlinkSync(target, destination, 'file');
  } catch (error) {
    if (['EPERM', 'EACCES', 'ENOTSUP'].includes(error.code)) {
      t.skip('This runner cannot create the symlink fixture');
      return;
    }
    throw error;
  }
  const result = run(project);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /exists|overwrite/i);
  assert.equal(fs.existsSync(target), false);
  assert.equal(fs.lstatSync(destination).isSymbolicLink(), true);
});

test('receipt works with a non-UTF8 output encoding and Unicode paths', t => {
  const { project } = fixture(t);
  const result = spawnSync(python, [script, '--workflow', 'web', '--project-root', project],
    { encoding: 'utf8', timeout: 10000, env: { ...process.env, PYTHONIOENCODING: 'cp1252' } });
  assert.equal(result.status, 0, result.stderr);
  const receipt = JSON.parse(result.stdout);
  assert.equal(fs.realpathSync.native(receipt.destination), fs.realpathSync.native(path.join(project, 'AGENTS.md.candidate')));
  assert.deepEqual(fs.readFileSync(receipt.destination),
    fs.readFileSync(path.join(skillRoot, 'assets/web-AGENTS.md')));
});
for (const failure of ['write', 'verification']) {
  test(`a ${failure} failure removes only its new destination and permits retry`, t => {
    const { project } = fixture(t);
    const probe = [
      'import pathlib, runpy, sys',
      'from unittest.mock import patch',
      'namespace = runpy.run_path(sys.argv[1])',
      'project = pathlib.Path(sys.argv[2]).resolve()',
      'destination = project / "AGENTS.md.candidate"',
      'original_open = pathlib.Path.open',
      'original_read = pathlib.Path.read_bytes',
      'class BrokenOutput:',
      '    def __init__(self, output): self.output = output',
      '    def __enter__(self): return self',
      '    def __exit__(self, *args): self.output.close()',
      '    def write(self, payload):',
      '        self.output.write(payload[:10])',
      '        self.output.flush()',
      '        raise OSError("simulated disk full")',
      'def faulty_open(target, mode="r", *args, **kwargs):',
      '    output = original_open(target, mode, *args, **kwargs)',
      '    return BrokenOutput(output) if target == destination and mode == "xb" else output',
      'def faulty_read(target):',
      '    return b"invalid verification" if target == destination else original_read(target)',
      'operation = "open" if sys.argv[3] == "write" else "read_bytes"',
      'replacement = faulty_open if operation == "open" else faulty_read',
      'with patch.object(pathlib.Path, operation, replacement):',
      '    try: namespace["copy_template"]("web", str(project))',
      '    except OSError: pass',
      '    else: raise AssertionError("Injected failure was not reported")',
      'assert not destination.exists(), "Failed copy left active partial guidance"',
      'receipt = namespace["copy_template"]("web", str(project))',
      'assert destination.read_bytes() == pathlib.Path(receipt["source"]).read_bytes()',
    ].join('\n');
    const result = spawnSync(python, ['-c', probe, script, project, failure],
      { encoding: 'utf8', timeout: 10000 });
    assert.equal(result.status, 0, result.stderr);
  });
}

for (const scope of ['.', 'checks']) {
  test(`default invocation stages ${scope} guidance without activating placeholders`, t => {
    const { project } = fixture(t);
    const directory = scope === '.' ? project : path.join(project, scope);
    if (scope !== '.') fs.mkdirSync(directory);
    const result = run(project, 'web', ['--scope', scope]);
    assert.equal(result.status, 0, result.stderr);
    const candidate = path.join(directory, 'AGENTS.md.candidate');
    assert.equal(fs.existsSync(candidate), true, 'The default must create an inactive candidate');
    assert.equal(fs.existsSync(path.join(directory, 'AGENTS.md')), false);
    assert.deepEqual(fs.readFileSync(candidate), fs.readFileSync(path.join(skillRoot, 'assets/web-AGENTS.md')));
    assert.equal(fs.realpathSync.native(JSON.parse(result.stdout).destination), fs.realpathSync.native(candidate));
  });
}
