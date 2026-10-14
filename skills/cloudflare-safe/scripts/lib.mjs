// Shared helpers for the cloudflare-safe scripts. No dependencies; Node.js 18+.
import { createHash } from 'node:crypto';
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

// Optional list of extra values the scripts must never print: one value per line, '#' for
// comments, in redact.txt next to the credentials file (or CLOUDFLARE_REDACT_FILE). Values
// shorter than 8 characters are ignored, because masking them would garble ordinary output.
export function redactFilePath(env = process.env) {
  if (env.CLOUDFLARE_REDACT_FILE) return path.resolve(env.CLOUDFLARE_REDACT_FILE);
  return path.join(path.dirname(tokensFilePath(env)), 'redact.txt');
}

export function loadRedactValues(env = process.env) {
  const file = redactFilePath(env);
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    // The user asked for these values to be hidden; printing without them would leak them.
    throw new CliError(`Cannot read the redaction list ${file} (${error.code}), so nothing was printed.`, 3);
  }
  return text.replace(/^\uFEFF/, '').split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line.length >= 8 && !line.startsWith('#'));
}

// Every value the output must never contain: the stored tokens plus the optional list.
export function secretValues(tokens, env = process.env) {
  return [tokens.CF_TOKEN_READ, tokens.CF_TOKEN_WRITE, ...loadRedactValues(env)];
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

// Rule expressions often hold a secret as the value a cookie or request header is compared
// with (a bypass cookie, a shared header key). Those literals are replaced with a short
// fingerprint, so an agent can still tell whether two rules use the same value without seeing
// it. Other text in an expression (paths, hosts, user agents) is left alone.
const NAME = String.raw`(?:"(?:[^"\\]|\\.)*"|r#*"[^"]*"#*)`;
const SECRET_FIELD = String.raw`(?:http\.cookie|http\.request\.(?:cookies|headers)\[\s*${NAME}\s*\](?:\[(?:\d+|\*)\])?)`;
const BEFORE_COMPARED_VALUE = new RegExp(String.raw`(${SECRET_FIELD})(?:\s+(?:contains|eq|ne|matches|wildcard|strict\s+wildcard)\s+|\s*(?:==|!=|~)\s*)$`);
const BEFORE_SET = new RegExp(String.raw`(${SECRET_FIELD})\s+in\s*$`);
const EXPRESSION_KEY = /expression$/i;

export const fingerprint = text => `[redacted:${createHash('sha256').update(text).digest('hex').slice(0, 4)}]`;

// Finds every string literal the way the rules language reads them: "..." with backslash
// escapes, and raw strings r"...", r#"..."#, r##"..."## and so on, closed only by a quote
// followed by the same number of #. Also records, for each literal, the inline set { ... }
// it sits in, so braces inside a literal never end a set.
function scanLiterals(expression) {
  const literals = [];
  let setStart = -1;
  for (let i = 0; i < expression.length; i += 1) {
    const char = expression[i];
    let open = null;
    if (char === '"') {
      open = '"';
    } else if (char === 'r' && !/[\w.]/.test(expression[i - 1] ?? '')) {
      open = /^r#*"/.exec(expression.slice(i, i + 260))?.[0] ?? null;
    }
    if (open) {
      const contentStart = i + open.length;
      let end;
      let close;
      if (open === '"') {
        let j = contentStart;
        while (j < expression.length && expression[j] !== '"') j += expression[j] === '\\' ? 2 : 1;
        end = j;
        close = '"';
      } else {
        close = `"${'#'.repeat(open.length - 2)}`;
        end = expression.indexOf(close, contentStart);
        if (end === -1) end = expression.length;
      }
      literals.push({ start: i, contentStart, contentEnd: end, end: end + close.length, open, close, setStart });
      i = end + close.length - 1;
    } else if (char === '{') {
      setStart = i;
    } else if (char === '}') {
      setStart = -1;
    }
  }
  return literals;
}

function maskContent(field, content) {
  if (content === '') return content;
  if (field === 'http.cookie' && content.includes('=')) {
    // "name=value; other=value": keep the cookie names, hide the values.
    return content.replace(/=([^;]+)/g, (_, cookieValue) => `=${fingerprint(cookieValue.trim())}`);
  }
  return fingerprint(content);
}

export function maskExpression(expression) {
  let output = '';
  let copied = 0;
  for (const literal of scanLiterals(expression)) {
    const before = expression.slice(0, literal.start);
    const compared = BEFORE_COMPARED_VALUE.exec(before);
    const inSet = literal.setStart >= 0 ? BEFORE_SET.exec(expression.slice(0, literal.setStart)) : null;
    const field = (compared ?? inSet)?.[1];
    if (!field) continue;
    const content = expression.slice(literal.contentStart, literal.contentEnd);
    const fieldName = field.startsWith('http.cookie') ? 'http.cookie' : field;
    output += expression.slice(copied, literal.contentStart) + maskContent(fieldName, content);
    copied = literal.contentEnd;
  }
  return output + expression.slice(copied);
}

// Blanks values whose field NAME suggests a secret, masks cookie and header values inside rule
// expressions, and replaces every known secret value (stored tokens and the optional redaction
// list) wherever it appears. Anything else it cannot recognise; SKILL.md covers that case.
export function redact(value, secretList = []) {
  // Longest first, so a value that contains another one is hidden as a whole.
  const secrets = [...new Set(secretList.filter(secret => typeof secret === 'string' && secret.length >= 8))]
    .sort((a, b) => b.length - a.length);
  const scrub = text => secrets.reduce((result, secret) => result.split(secret).join(fingerprint(secret)), text);
  const walk = (node, key) => {
    if (Array.isArray(node)) return node.map(item => walk(item, key));
    if (node && typeof node === 'object') {
      return Object.fromEntries(Object.entries(node).map(([name, child]) => [name, walk(child, name)]));
    }
    if (typeof node === 'string') {
      if (key !== undefined && SENSITIVE_KEY.test(key) && node !== '') return REDACTED;
      return scrub(key !== undefined && EXPRESSION_KEY.test(key) ? maskExpression(node) : node);
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

export function formatBody(result, secretList) {
  if (result.json === undefined) return redact(result.text, secretList);
  return JSON.stringify(redact(result.json, secretList), null, 2);
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
