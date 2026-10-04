#!/usr/bin/env node
// cf-apply.mjs - send ONE staged, human-approved change to the Cloudflare API.
//
//   node cf-apply.mjs <change-file.json> --approved
//
// Disarmed by default: it refuses unless the user stored a write token (CF_TOKEN_WRITE).
// --approved is passed by the agent only after the human typed "approved" in the chat;
// the script cannot check the chat, so the missing write token is the real safeguard.
//
// The script validates the change file, refuses the hard-prohibited operations, sends the
// request and records the outcome in the change file. It does not verify the effect and it
// does not roll back: both stay with the agent and the human, as described in SKILL.md.
// Exit codes: 0 applied, 2 usage or invalid change file, 3 credentials file missing,
// 4 not approved, 6 write token missing or no response received, 7 API rejected the change,
// 8 prohibited operation, or a DNS record whose type could not be checked.
import fs from 'node:fs';
import { API_PREFIX, CliError, callApi, isMain, loadTokens, redact, resolveApiUrl, runCli } from './lib.mjs';

const USAGE = 'Usage: node cf-apply.mjs <change-file.json> --approved';
const WRITE_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE'];
const REQUIRED = ['summary', 'category', 'blast_radius', 'current_state', 'proposed_state', 'diff', 'verification', 'rollback', 'apply_command'];
const TEXT_FIELDS = ['summary', 'category', 'blast_radius', 'diff', 'verification', 'rollback'];
const MAX_DNS_RECORDS = 5;
const ID = '[0-9a-f]{32}';

export function validateChange(change) {
  const problems = [];
  if (!change || typeof change !== 'object' || Array.isArray(change)) return ['the change file must contain a JSON object'];
  for (const field of REQUIRED) {
    // current_state and proposed_state may be null (creating or deleting something).
    const empty = TEXT_FIELDS.includes(field) && (typeof change[field] !== 'string' || !change[field].trim());
    if (!(field in change) || empty) problems.push(`missing field: ${field}`);
  }
  const command = change.apply_command;
  if ('apply_command' in change && (!command || typeof command !== 'object' || Array.isArray(command))) {
    problems.push('apply_command must be an object with method, url and body');
  } else if (command) {
    if (!WRITE_METHODS.includes(command.method)) problems.push(`apply_command.method must be one of ${WRITE_METHODS.join(', ')}`);
    if (typeof command.url !== 'string' || !command.url) problems.push('apply_command.url is required');
    // A body given as text would be sent as-is and skip the checks on its content.
    const body = command.body;
    if (body !== undefined && body !== null && typeof body !== 'object') {
      problems.push('apply_command.body must be a JSON object, an array or null, not text');
    }
  }
  if ('applied_at' in change) problems.push('this change file was already applied; stage a new file');
  return problems;
}

function hasKey(value, name) {
  if (!value || typeof value !== 'object') return false;
  return Object.entries(value).some(([key, child]) => key === name || hasKey(child, name));
}

// Operations no approval can unlock. Returns the reason, or null when the change is allowed.
// This list covers what can be recognised from the request. It cannot cover the whole API,
// so the permissions of the write token remain the real limit on what a change can do.
export function prohibitedReason(method, url, body) {
  const route = url.pathname.slice(API_PREFIX.length).replace(/\/+$/, '');
  const segments = route.split('/');
  if (segments.includes('tokens')) return 'API tokens are created and changed only by a human in the dashboard';
  if (new RegExp(`^(zones|accounts)/${ID}$`).test(route)) return 'changing or deleting a whole zone or account is not allowed';
  if (method === 'POST' && route === 'zones') return 'adding a zone is not allowed';
  for (const area of ['members', 'roles', 'billing', 'subscriptions', 'subscription', 'registrar', 'access']) {
    if (segments.includes(area)) return `changes under "${area}" are not allowed`;
  }
  if (segments.includes('custom_ns')) return 'custom nameservers are not changed through this script';
  if (segments.includes('dns_settings') && hasKey(body, 'nameservers')) return 'nameserver settings are not changed through this script';
  if (route.endsWith('certificate_packs/order')) return 'ordering a paid certificate is a purchase and is not allowed';
  if (segments.includes('dns_records')) {
    if (segments.includes('import') || segments.includes('scan')) return 'bulk DNS import and DNS scans are not allowed';
    if (body && String(body.type).toUpperCase() === 'NS') return 'NS records are not changed through this script';
    if (segments.includes('batch')) {
      const lists = ['deletes', 'patches', 'puts', 'posts'].map(key => (Array.isArray(body?.[key]) ? body[key] : []));
      if (lists.flat().some(record => String(record?.type).toUpperCase() === 'NS')) return 'NS records are not changed through this script';
      const count = lists.reduce((sum, list) => sum + list.length, 0);
      if (count > MAX_DNS_RECORDS) return `a change may touch at most ${MAX_DNS_RECORDS} DNS records (this one touches ${count})`;
    }
  }
  if (segments.includes('rulesets')) {
    if (method === 'DELETE' && !segments.includes('rules')) return 'deleting a whole ruleset is not allowed';
    if (!segments.includes('rules')) {
      // Ruleset-level writes replace the whole rule list, so they can switch everything off at once.
      if (body?.enabled === false) return 'disabling a whole ruleset is not allowed';
      if (Array.isArray(body?.rules) && body.rules.every(rule => rule?.enabled === false)) {
        return 'a ruleset update that leaves no enabled rule is not allowed';
      }
    }
  }
  return null;
}

// DNS records the request changes or deletes by ID. Their type is not in the request, so it
// has to be looked up before the NS rule can be applied to them.
export function existingDnsRecords(method, url, body) {
  const route = url.pathname.slice(API_PREFIX.length).replace(/\/+$/, '');
  const single = route.match(new RegExp(`^(zones/${ID}/dns_records)/([^/]+)$`));
  if (!single) return [];
  if (single[2] !== 'batch') return method === 'POST' ? [] : [`${single[1]}/${single[2]}`];
  return ['deletes', 'patches', 'puts']
    .flatMap(key => (Array.isArray(body?.[key]) ? body[key] : []))
    .map(record => `${single[1]}/${encodeURIComponent(String(record?.id ?? ''))}`);
}

async function refuseNsRecords({ method, url, body, token, fetchImpl }) {
  for (const route of existingDnsRecords(method, url, body)) {
    const lookup = await callApi({ url: resolveApiUrl(route), token, fetchImpl });
    const type = lookup.ok ? lookup.json?.result?.type : undefined;
    if (typeof type !== 'string') {
      throw new CliError(`Refusing: could not read the DNS record ${route} to check its type (HTTP ${lookup.status}). Nothing was changed.`, 8);
    }
    if (type.toUpperCase() === 'NS') {
      throw new CliError('Refusing: NS records are not changed through this script. Ask the human to do this in the Cloudflare dashboard.', 8);
    }
  }
}

export async function applyMain(options = {}) {
  const file = (options.argv ?? process.argv.slice(2)).find(arg => !arg.startsWith('--'));
  if (!file) throw new CliError(USAGE, 2);
  // One run per change file: a second run started at the same moment must not send it too.
  const lock = `${file}.lock`;
  try {
    fs.closeSync(fs.openSync(lock, 'wx'));
  } catch (error) {
    if (error.code !== 'EEXIST') throw new CliError(`Cannot read the change file ${file}: ${error.message}`, 2);
    throw new CliError(`${lock} exists: another run is applying this change, or one was interrupted. Read the current state in Cloudflare; delete the lock file only when no run is active.`, 2);
  }
  try {
    return await applyLocked(file, options);
  } finally {
    fs.rmSync(lock, { force: true });
  }
}

async function applyLocked(file, {
  argv = process.argv.slice(2),
  env = process.env,
  fetchImpl = globalThis.fetch,
  stdout = process.stdout,
  now = () => new Date(),
}) {
  if (!argv.includes('--approved')) {
    throw new CliError('Refusing to apply. Pass --approved only after the human typed "approved" in the chat.', 4);
  }

  let change;
  try {
    change = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  } catch (error) {
    throw new CliError(`Cannot read the change file ${file}: ${error.message}`, 2);
  }
  const problems = validateChange(change);
  if (problems.length) throw new CliError(`Invalid change file:\n- ${problems.join('\n- ')}`, 2);

  const { method, body = null } = change.apply_command;
  const url = resolveApiUrl(change.apply_command.url);
  const reason = prohibitedReason(method, url, body);
  if (reason) throw new CliError(`Refusing: ${reason}. Ask the human to do this in the Cloudflare dashboard.`, 8);

  const { file: tokensFile, tokens } = loadTokens(env);
  if (!tokens.CF_TOKEN_WRITE) {
    throw new CliError(
      `No write token in ${tokensFile}, so writes are disabled (the default). Hand the change to the human for the dashboard.`, 6);
  }

  await refuseNsRecords({ method, url, body, token: tokens.CF_TOKEN_WRITE, fetchImpl });

  stdout.write(`Cloudflare change: ${change.summary}\n  category: ${change.category}\n  blast radius: ${change.blast_radius}\n  ${method} ${url}\n`);
  const secrets = [tokens.CF_TOKEN_READ, tokens.CF_TOKEN_WRITE];
  const record = outcome => {
    const stamped = { ...change, applied_at: now().toISOString(), ...outcome };
    const temporary = `${file}.tmp`;
    fs.writeFileSync(temporary, `${JSON.stringify(stamped, null, 2)}\n`);
    fs.renameSync(temporary, file);
    return stamped;
  };

  // Mark the file as used before sending. If the process is killed mid-request, the file is
  // already refused on reuse, so a retry cannot create the same record or rule twice.
  record({ http_status: null, api_success: null, result: 'Request sent; no outcome was recorded.' });

  let result;
  try {
    result = await callApi({ url, method, token: tokens.CF_TOKEN_WRITE, body, fetchImpl });
  } catch (error) {
    // Whatever went wrong, the request may have reached Cloudflare.
    record({ http_status: null, api_success: null, result: redact(String(error.message), secrets) });
    throw new CliError(`${error.message}\nNo complete response was received, so the change may or may not have been applied. Recorded in ${file}. Read the current state before staging a new change.`, 6);
  }
  const success = result.ok && result.json?.success === true;
  const stamped = record({
    http_status: result.status,
    api_success: success,
    result: result.json === undefined ? redact(result.text, secrets) : redact(result.json, secrets),
  });

  stdout.write(`  HTTP ${result.status}\n${JSON.stringify(stamped.result, null, 2)}\n`);
  if (!success) {
    throw new CliError(`The API did not confirm the change. Outcome recorded in ${file}. Check the current state before retrying, and use the "rollback" field if something changed.`, 7);
  }
  stdout.write(`Applied. Outcome recorded in ${file}. Now run the check described in its "verification" field.\n`);
  return 0;
}

if (isMain(import.meta.url)) await runCli(applyMain);
