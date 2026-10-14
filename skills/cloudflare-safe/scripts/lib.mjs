// Shared helpers for the cloudflare-safe scripts. No dependencies; Node.js 18+.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const API_ORIGIN = 'https://api.cloudflare.com';
export const API_PREFIX = '/client/v4/';
export const TOKEN_KEYS = ['CF_ACCOUNT_ID', 'CF_TOKEN_READ', 'CF_TOKEN_WRITE'];

const REDACTED = '[redacted]';
const SENSITIVE_KEY = /secret|password|passwd|private_key|credential|api_key|apikey|^token$|_token$/i;

export class CliError extends Error {
  constructor(message, exitCode = 1) {
    super(message);
    this.exitCode = exitCode;
  }
}

export function tokensFilePath(env = process.env) {
  if (env.CLOUDFLARE_TOKENS_FILE) return path.resolve(env.CLOUDFLARE_TOKENS_FILE);
  if (env.CLOUDFLARE_CONFIG_DIR) return path.resolve(env.CLOUDFLARE_CONFIG_DIR, 'tokens.env');
  return path.join(os.homedir(), '.config', 'cloudflare', 'tokens.env');
}

// The file is parsed as data and never executed, so a damaged or hostile file cannot run code.
export function parseTokens(text) {
  const tokens = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || !TOKEN_KEYS.includes(match[1])) continue;
    let value = match[2];
    const quoted = value.match(/^(['"])(.*)\1$/);
    if (quoted) value = quoted[2];
    tokens[match[1]] = value;
  }
  return tokens;
}

export function serializeTokens(tokens) {
  const lines = [
    '# Cloudflare API credentials for the cloudflare-safe agent skill.',
    '# Keep this file private: do not commit it or store it in a synced folder.',
    '# CF_ACCOUNT_ID  - account ID, fills {account_id} in API paths',
    '# CF_TOKEN_READ  - read-only API token',
    '# CF_TOKEN_WRITE - optional; leave empty to keep agent writes disabled',
  ];
  for (const key of TOKEN_KEYS) lines.push(`${key}=${tokens[key] ?? ''}`);
  return `${lines.join('\n')}\n`;
}

export function loadTokens(env = process.env) {
  const file = tokensFilePath(env);
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    throw new CliError(
      `Missing credentials file: ${file}\nAsk the user to run setup-tokens.mjs from this skill's scripts folder.`, 3);
  }
  return { file, tokens: parseTokens(text.replace(/^\uFEFF/, '')) };
}

// Accepts a path relative to the API root, or a full API URL. Anything that would leave
// https://api.cloudflare.com/client/v4/ is rejected so a token is never sent elsewhere.
export function resolveApiUrl(input, accountId = '') {
  let value = String(input ?? '').trim();
  if (!value) throw new CliError('An API path is required.', 2);
  if (/\{account_id\}/.test(value)) {
    if (!accountId) throw new CliError('CF_ACCOUNT_ID is not set, so {account_id} cannot be filled in.', 5);
    value = value.replaceAll('{account_id}', accountId);
  }
  if (!/^https?:\/\//i.test(value)) {
    value = API_ORIGIN + API_PREFIX + value.replace(/^\/+/, '').replace(/^client\/v4\//, '');
  }
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new CliError(`Not a valid Cloudflare API path or URL: ${input}`, 2);
  }
  if (url.origin !== API_ORIGIN || url.username || url.password || !url.pathname.startsWith(API_PREFIX)) {
    throw new CliError(`Refusing to call anything outside ${API_ORIGIN}${API_PREFIX}`, 2);
  }
  return url;
}

// Blanks values whose field NAME suggests a secret. It cannot see a secret embedded in an
// ordinary string such as a rule expression; SKILL.md tells the agent how to handle that.
export function redact(value, tokenValues = []) {
  const secrets = tokenValues.filter(token => typeof token === 'string' && token.length >= 8);
  const scrub = text => secrets.reduce((result, secret) => result.split(secret).join(REDACTED), text);
  const walk = (node, key) => {
    if (Array.isArray(node)) return node.map(item => walk(item, key));
    if (node && typeof node === 'object') {
      return Object.fromEntries(Object.entries(node).map(([name, child]) => [name, walk(child, name)]));
    }
    if (typeof node === 'string') {
      return key !== undefined && SENSITIVE_KEY.test(key) && node !== '' ? REDACTED : scrub(node);
    }
    return node;
  };
  return typeof value === 'string' ? scrub(value) : walk(value);
}

export async function callApi({ url, method = 'GET', token, body, fetchImpl = globalThis.fetch }) {
  if (typeof fetchImpl !== 'function') throw new CliError('Node.js 18 or newer is required (global fetch is missing).', 5);
  const headers = { Authorization: `Bearer ${token}` };
  const init = { method, headers, redirect: 'error' };
  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json';
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
  }
  // Reading the body is inside the try: a response that breaks off halfway is also "no answer".
  let response;
  let text;
  try {
    response = await fetchImpl(url.toString(), init);
    text = await response.text();
  } catch (error) {
    throw new CliError(`Request to ${url.origin} failed: ${error.cause?.code || error.message}`, 6);
  }
  let json;
  try { json = JSON.parse(text); } catch { json = undefined; }
  return { status: response.status, ok: response.ok, text, json };
}

export function formatBody(result, tokenValues) {
  if (result.json === undefined) return redact(result.text, tokenValues);
  return JSON.stringify(redact(result.json, tokenValues), null, 2);
}

// True when the module is the script being run. Resolves symlinks, because installed
// skills are often symlinked into an agent's skills folder.
export function isMain(moduleUrl, argv1 = process.argv[1]) {
  if (!argv1) return false;
  try {
    return pathToFileURL(fs.realpathSync(argv1)).href === moduleUrl;
  } catch {
    return false;
  }
}

export async function runCli(main) {
  try {
    process.exitCode = await main();
  } catch (error) {
    if (!(error instanceof CliError)) throw error;
    process.stderr.write(`${error.message}\n`);
    process.exitCode = error.exitCode;
  }
}
