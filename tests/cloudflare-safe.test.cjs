const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const scripts = path.resolve(__dirname, '../skills/cloudflare-safe/scripts');
const load = name => import(pathToFileURL(path.join(scripts, name)).href);

const READ = 'read-token-0123456789abcdefghij';
const WRITE = 'write-token-0123456789abcdefghij';
const ACCOUNT = '0123456789abcdef0123456789abcdef';
const ZONE = 'fedcba9876543210fedcba9876543210';
const API = 'https://api.cloudflare.com/client/v4/';

function workspace(t, { write = false, account = true } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cloudflare-safe-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'credentials');
  fs.writeFileSync(file, [
    '# comment',
    account ? `CF_ACCOUNT_ID='${ACCOUNT}'` : 'CF_ACCOUNT_ID=',
    `CF_TOKEN_READ=${READ}`,
    `CF_TOKEN_WRITE=${write ? WRITE : ''}`,
  ].join('\r\n'));
  return { dir, env: { CLOUDFLARE_TOKENS_FILE: file } };
}

function fakeFetch(respond = () => ({ body: { success: true, errors: [], result: {} } })) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, ...init });
    const { status = 200, body } = respond(url, init);
    const text = typeof body === 'string' ? body : JSON.stringify(body);
    return { status, ok: status >= 200 && status < 300, text: async () => text };
  };
  return { calls, fetchImpl };
}

function sink() {
  const chunks = [];
  return { write: chunk => chunks.push(String(chunk)), text: () => chunks.join('') };
}

function change(overrides = {}) {
  return {
    summary: 'Add a TXT record',
    category: 'dns',
    blast_radius: 'One new record; no traffic affected',
    current_state: null,
    proposed_state: { type: 'TXT', name: 'example.com' },
    diff: 'Adds one TXT record.',
    verification: 'Read the DNS records again.',
    rollback: 'Delete the new record.',
    apply_command: { method: 'POST', url: `${API}zones/${ZONE}/dns_records`, body: { type: 'TXT', name: 'example.com', content: 'hello' } },
    ...overrides,
  };
}

function stage(dir, content) {
  const file = path.join(dir, 'cf-change.json');
  fs.writeFileSync(file, JSON.stringify(content));
  return file;
}

test('credentials are parsed as data, with or without quotes', async () => {
  const { parseTokens, serializeTokens } = await load('lib.mjs');
  const parsed = parseTokens(`export X=1\nCF_ACCOUNT_ID='${ACCOUNT}'\r\nCF_TOKEN_READ="${READ}"\n CF_TOKEN_WRITE = \nOTHER=$(touch nope)\n`);
  assert.deepEqual(parsed, { CF_ACCOUNT_ID: ACCOUNT, CF_TOKEN_READ: READ, CF_TOKEN_WRITE: '' });
  assert.deepEqual(parseTokens(serializeTokens(parsed)), parsed);
});

test('API paths resolve only to the Cloudflare API', async () => {
  const { resolveApiUrl } = await load('lib.mjs');
  assert.equal(resolveApiUrl('/zones?name=example.com').href, `${API}zones?name=example.com`);
  assert.equal(resolveApiUrl(`${API}zones`).href, `${API}zones`);
  assert.equal(resolveApiUrl('accounts/{account_id}/rulesets', ACCOUNT).href, `${API}accounts/${ACCOUNT}/rulesets`);
  assert.throws(() => resolveApiUrl('accounts/{account_id}/rulesets'), /CF_ACCOUNT_ID/);
  for (const hostile of [
    'https://evil.example/client/v4/zones',
    'http://api.cloudflare.com/client/v4/zones',
    'https://api.cloudflare.com.evil.example/client/v4/zones',
    'https://user:pass@api.cloudflare.com/client/v4/zones',
    'https://api.cloudflare.com:8443/client/v4/zones',
    'https://api.cloudflare.com/other',
    '../../other',
  ]) {
    assert.throws(() => resolveApiUrl(hostile), /Refusing/, hostile);
  }
});

test('redaction hides secret-named fields and stored tokens, and keeps ordinary values', async () => {
  const { redact } = await load('lib.mjs');
  const output = redact({
    result: [{ id: 'ssl', value: 'full', client_secret: 'abc', tunnel_token: 'def', note: `leaked ${READ}` }],
  }, [READ, '']);
  assert.deepEqual(output, {
    result: [{ id: 'ssl', value: 'full', client_secret: '[redacted]', tunnel_token: '[redacted]', note: 'leaked [redacted]' }],
  });
});

test('cf-read sends a GET with the read token and prints the response', async t => {
  const { readMain } = await load('cf-read.mjs');
  const { env } = workspace(t, { write: true });
  const { calls, fetchImpl } = fakeFetch(() => ({ body: { success: true, errors: [], result: [{ name: 'example.com' }] } }));
  const stdout = sink();
  assert.equal(await readMain({ argv: ['zones?name=example.com'], env, fetchImpl, stdout }), 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${API}zones?name=example.com`);
  assert.equal(calls[0].method, 'GET');
  assert.equal(calls[0].headers.Authorization, `Bearer ${READ}`);
  assert.equal(calls[0].redirect, 'error');
  assert.match(stdout.text(), /example\.com/);
  assert.doesNotMatch(stdout.text(), new RegExp(READ));
});

test('cf-read verify falls back to the user endpoint for user-owned tokens', async t => {
  const { readMain } = await load('cf-read.mjs');
  const { env } = workspace(t);
  const { calls, fetchImpl } = fakeFetch(url => (url.includes('/accounts/')
    ? { status: 401, body: { success: false, errors: [{ code: 1000 }] } }
    : { body: { success: true, errors: [], result: { status: 'active' } } }));
  assert.equal(await readMain({ argv: ['verify'], env, fetchImpl, stdout: sink() }), 0);
  assert.deepEqual(calls.map(call => call.url), [`${API}accounts/${ACCOUNT}/tokens/verify`, `${API}user/tokens/verify`]);
});

test('cf-read reports API errors and refuses GraphQL mutations', async t => {
  const { readMain } = await load('cf-read.mjs');
  const { env } = workspace(t);
  const failing = fakeFetch(() => ({ status: 403, body: { success: false, errors: [{ code: 10000 }] } }));
  const stdout = sink();
  await assert.rejects(readMain({ argv: ['zones'], env, fetchImpl: failing.fetchImpl, stdout }), { exitCode: 1 });
  assert.match(stdout.text(), /10000/);

  const { calls, fetchImpl } = fakeFetch();
  await assert.rejects(readMain({ argv: ['graphql', 'mutation { x }'], env, fetchImpl, stdout: sink() }), { exitCode: 2 });
  assert.equal(calls.length, 0);
  await readMain({ argv: ['graphql', '{ viewer { zones { zoneTag } } }', '{"a":1}'], env, fetchImpl, stdout: sink() });
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].url, `${API}graphql`);
  assert.deepEqual(JSON.parse(calls[0].body).variables, { a: 1 });
});

test('cf-read explains a missing credentials file', async t => {
  const { readMain } = await load('cf-read.mjs');
  const { dir } = workspace(t);
  const env = { CLOUDFLARE_TOKENS_FILE: path.join(dir, 'absent') };
  await assert.rejects(readMain({ argv: ['zones'], env, stdout: sink() }), { exitCode: 3 });
});

test('cf-apply refuses without --approved and without a write token', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t);
  const file = stage(dir, change());
  const { calls, fetchImpl } = fakeFetch();
  await assert.rejects(applyMain({ argv: [file], env, fetchImpl, stdout: sink() }), { exitCode: 4 });
  await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 6 });
  assert.equal(calls.length, 0);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).applied_at, undefined);
});

test('cf-apply never sends the write token outside the Cloudflare API', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const { calls, fetchImpl } = fakeFetch();
  for (const url of ['https://evil.example/client/v4/zones/x/dns_records', 'http://api.cloudflare.com/client/v4/zones/x/dns_records']) {
    const file = stage(dir, change({ apply_command: { method: 'POST', url, body: {} } }));
    await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 2 });
  }
  assert.equal(calls.length, 0);
});

test('cf-apply rejects incomplete change files and read-only methods', async t => {
  const { applyMain, validateChange } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const { calls, fetchImpl } = fakeFetch();
  const incomplete = change();
  delete incomplete.rollback;
  assert.deepEqual(validateChange(incomplete), ['missing field: rollback']);
  assert.deepEqual(validateChange(change()), []);
  const textBody = change({ apply_command: { method: 'PUT', url: `${API}zones/${ZONE}/rulesets/abc`, body: '{"enabled":false}' } });
  assert.match(validateChange(textBody).join(), /body must be a JSON object/);
  for (const bad of [incomplete, textBody, change({ apply_command: { method: 'GET', url: `${API}zones`, body: null } }), []]) {
    await assert.rejects(applyMain({ argv: [stage(dir, bad), '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 2 });
  }
  assert.equal(calls.length, 0);
});

test('cf-apply refuses the hard-prohibited operations', async () => {
  const { prohibitedReason } = await load('cf-apply.mjs');
  const reason = (method, route, body) => prohibitedReason(method, new URL(API + route), body);
  const zone = `zones/${ZONE}`;
  const many = Array.from({ length: 6 }, (_, index) => ({ type: 'A', name: `host${index}` }));
  const refused = [
    ['POST', `accounts/${ACCOUNT}/tokens`, {}],
    ['PUT', 'user/tokens/abc', {}],
    ['DELETE', zone, null],
    ['PATCH', zone, { paused: true }],
    ['DELETE', `accounts/${ACCOUNT}`, null],
    ['POST', 'zones', { name: 'example.com' }],
    ['POST', `accounts/${ACCOUNT}/members`, {}],
    ['PUT', `accounts/${ACCOUNT}/billing/profile`, {}],
    ['PUT', `accounts/${ACCOUNT}/registrar/domains/example.com`, {}],
    ['POST', `accounts/${ACCOUNT}/access/apps`, {}],
    ['POST', `${zone}/dns_records`, { type: 'ns', name: 'example.com' }],
    ['POST', `${zone}/dns_records/import`, null],
    ['POST', `${zone}/dns_records/batch`, { posts: many }],
    ['POST', `${zone}/dns_records/batch`, { posts: [{ type: 'NS' }] }],
    ['DELETE', `${zone}/rulesets/abc`, null],
    ['PUT', `${zone}/rulesets/phases/http_request_firewall_custom/entrypoint`, { rules: [] }],
    ['PUT', `${zone}/rulesets/abc`, { enabled: false }],
    ['PATCH', `${zone}/rulesets/abc`, { rules: [{ action: 'block', enabled: false }, { action: 'skip', enabled: false }] }],
  ];
  for (const [method, route, body] of refused) assert.ok(reason(method, route, body), `${method} ${route} should be refused`);

  const allowed = [
    ['POST', `${zone}/dns_records`, { type: 'A', name: 'www' }],
    ['POST', `${zone}/dns_records/batch`, { posts: many.slice(0, 3), deletes: [{ id: 'x' }, { id: 'y' }] }],
    ['DELETE', `${zone}/dns_records/abc`, null],
    ['POST', `${zone}/rulesets/abc/rules`, { action: 'block' }],
    ['DELETE', `${zone}/rulesets/abc/rules/def`, null],
    ['PUT', `${zone}/rulesets/phases/http_request_firewall_custom/entrypoint`, { rules: [{ action: 'block' }] }],
    ['PATCH', `${zone}/settings/ssl`, { value: 'strict' }],
    ['PATCH', `${zone}/rulesets/abc/rules/def`, { action: 'block', enabled: false }],
    ['PUT', `${zone}/rulesets/abc`, { rules: [{ action: 'block', enabled: false }, { action: 'skip' }] }],
    ['PUT', `${zone}/rulesets/abc`, { description: 'renamed' }],
  ];
  for (const [method, route, body] of allowed) assert.equal(reason(method, route, body), null, `${method} ${route} should be allowed`);
});

test('cf-apply sends an approved change once and records the outcome', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const file = stage(dir, change());
  const { calls, fetchImpl } = fakeFetch(() => ({ body: { success: true, errors: [], result: { id: 'rec1', api_token: 'server-side' } } }));
  const now = () => new Date('2026-01-15T10:00:00Z');
  assert.equal(await applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink(), now }), 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].headers.Authorization, `Bearer ${WRITE}`);
  assert.deepEqual(JSON.parse(calls[0].body), change().apply_command.body);

  const recorded = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(recorded.applied_at, '2026-01-15T10:00:00.000Z');
  assert.equal(recorded.http_status, 200);
  assert.equal(recorded.api_success, true);
  assert.deepEqual(recorded.result.result, { id: 'rec1', api_token: '[redacted]' });
  assert.equal(recorded.summary, change().summary);
  assert.doesNotMatch(fs.readFileSync(file, 'utf8'), new RegExp(WRITE));

  await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 2 });
  assert.equal(calls.length, 1);
});

test('cf-apply records a rejected change and exits non-zero', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const file = stage(dir, change());
  const { fetchImpl } = fakeFetch(() => ({ status: 400, body: { success: false, errors: [{ code: 81057 }] } }));
  await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 7 });
  const recorded = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(recorded.api_success, false);
  assert.equal(recorded.http_status, 400);
});

test('cf-apply makes a change file non-reusable when no response arrives', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const file = stage(dir, change());
  let attempts = 0;
  const fetchImpl = async () => {
    attempts += 1;
    throw Object.assign(new TypeError('fetch failed'), { cause: { code: 'ECONNRESET' } });
  };
  await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 6 });
  const recorded = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.ok(recorded.applied_at);
  assert.equal(recorded.http_status, null);
  assert.equal(recorded.api_success, null);
  assert.match(recorded.result, /ECONNRESET/);

  await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 2 });
  assert.equal(attempts, 1);
});

test('cf-apply marks the change file as used before the request is sent', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const file = stage(dir, change());
  let duringRequest;
  const fetchImpl = async () => {
    duringRequest = JSON.parse(fs.readFileSync(file, 'utf8'));
    return { status: 200, ok: true, text: async () => JSON.stringify({ success: true, errors: [], result: {} }) };
  };
  await applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() });
  assert.ok(duringRequest.applied_at);
  assert.equal(duringRequest.api_success, null);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).api_success, true);
});

test('cf-apply treats a response that breaks off, or any unexpected error, as an attempt', async t => {
  const { applyMain } = await load('cf-apply.mjs');
  const { dir, env } = workspace(t, { write: true });
  const failures = [
    async () => ({ status: 200, ok: true, text: async () => { throw new TypeError('terminated'); } }),
    async () => { throw new RangeError('unexpected'); },
  ];
  for (const fetchImpl of failures) {
    const file = stage(dir, change());
    await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 6 });
    const recorded = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.ok(recorded.applied_at);
    assert.equal(recorded.api_success, null);
    await assert.rejects(applyMain({ argv: [file, '--approved'], env, fetchImpl, stdout: sink() }), { exitCode: 2 });
  }
});

test('setup input rules', async () => {
  const { checkAccountId, checkToken, mergeAnswer } = await load('setup-tokens.mjs');
  assert.equal(checkAccountId(ACCOUNT), null);
  assert.ok(checkAccountId('ABC'));
  assert.equal(checkToken(READ), null);
  assert.ok(checkToken('short'));
  assert.ok(checkToken(`${READ}' ; rm`));
  assert.equal(mergeAnswer('stored', '  '), 'stored');
  assert.equal(mergeAnswer('stored', ' new '), 'new');
  assert.equal(mergeAnswer('stored', '-', { optional: true }), '');
  assert.equal(mergeAnswer(undefined, ''), '');
});

test('the scripts run as commands, including through a symlink, and setup refuses a non-interactive run', t => {
  const { dir, env } = workspace(t);
  const run = (script, args = []) => spawnSync(process.execPath, [script, ...args], {
    env: { ...process.env, ...env }, encoding: 'utf8', input: '',
  });

  const usage = run(path.join(scripts, 'cf-read.mjs'));
  assert.equal(usage.status, 2);
  assert.match(usage.stderr, /Usage/);

  const unapproved = run(path.join(scripts, 'cf-apply.mjs'), [stage(dir, change())]);
  assert.equal(unapproved.status, 4);

  const setup = run(path.join(scripts, 'setup-tokens.mjs'));
  assert.equal(setup.status, 2);
  assert.match(setup.stderr, /interactive terminal/);
  assert.match(fs.readFileSync(env.CLOUDFLARE_TOKENS_FILE, 'utf8'), new RegExp(READ));

  const link = path.join(dir, 'linked-skill');
  try {
    fs.symlinkSync(path.dirname(scripts), link, 'junction');
  } catch {
    return; // Symlinks can be unavailable on locked-down Windows machines.
  }
  const linked = run(path.join(link, 'scripts', 'cf-read.mjs'));
  assert.equal(linked.status, 2);
  assert.match(linked.stderr, /Usage/);
});
