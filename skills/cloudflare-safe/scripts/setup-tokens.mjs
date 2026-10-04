#!/usr/bin/env node
// setup-tokens.mjs - store the Cloudflare credentials for the cloudflare-safe skill.
//
//   node setup-tokens.mjs
//
// A HUMAN runs this once per machine, in their own terminal. It refuses to run without an
// interactive terminal, so an agent cannot feed it a token and no token passes through a chat.
// Works the same on Linux, macOS and Windows. The file is written to
// ~/.config/cloudflare/tokens.env (set CLOUDFLARE_TOKENS_FILE to use another path).
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { Writable } from 'node:stream';
import { CliError, isMain, parseTokens, runCli, serializeTokens, tokensFilePath } from './lib.mjs';
import { readMain } from './cf-read.mjs';

const CLEAR = '-';

export function checkAccountId(value) {
  return /^[0-9a-f]{32}$/.test(value) ? null : 'An account ID is 32 lowercase hexadecimal characters.';
}

export function checkToken(value) {
  if (/[\s'"#=\\]/.test(value)) return 'A token cannot contain spaces, quotes, "#", "=" or "\\". Paste only the token.';
  return value.length < 20 ? 'That is too short to be a Cloudflare API token.' : null;
}

// Blank keeps the stored value; "-" clears an optional one.
export function mergeAnswer(current, answer, { optional = false } = {}) {
  const value = answer.trim();
  if (value === '') return current ?? '';
  if (optional && value === CLEAR) return '';
  return value;
}

function ask(question, { hidden = false } = {}) {
  return new Promise(resolve => {
    let muted = false;
    const output = new Writable({
      write(chunk, encoding, callback) {
        if (!muted) process.stdout.write(chunk, encoding);
        callback();
      },
    });
    const rl = readline.createInterface({ input: process.stdin, output, terminal: true });
    rl.question(question, answer => {
      rl.close();
      if (hidden) process.stdout.write('\n');
      resolve(answer);
    });
    muted = hidden;
  });
}

async function askChecked(question, current, check, options = {}) {
  for (;;) {
    const value = mergeAnswer(current, await ask(question, options), options);
    if (value === '' && options.optional) return value;
    const problem = value === '' ? 'A value is required.' : check(value);
    if (!problem) return value;
    process.stdout.write(`  ${problem}\n`);
  }
}

// Writes the credentials through a new file that is private before any token is in it, then
// swaps it into place. An existing file's looser permissions are therefore never reused, and
// the parent folder is left as it is (it may be a shared folder the user chose).
export function writePrivateFile(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.new`;
  fs.rmSync(temporary, { force: true });
  try {
    fs.closeSync(fs.openSync(temporary, 'wx', 0o600));
    if (process.platform === 'win32') {
      // Drop inherited permissions, grant the user, and remove the broad groups by their
      // well-known IDs (Everyone, Authenticated Users, Users). Windows keeps SYSTEM and
      // Administrators on the file, as it does for other private files such as SSH keys.
      const { USERDOMAIN, USERNAME } = process.env;
      const user = USERDOMAIN && USERNAME ? `${USERDOMAIN}\\${USERNAME}` : os.userInfo().username;
      execFileSync('icacls', [temporary, '/inheritance:r', '/grant:r', `${user}:F`, '/remove:g', '*S-1-1-0', '*S-1-5-11', '*S-1-5-32-545'], { stdio: 'ignore' });
    } else {
      fs.chmodSync(temporary, 0o600);
    }
    fs.writeFileSync(temporary, content);
    fs.renameSync(temporary, file);
  } catch (error) {
    fs.rmSync(temporary, { force: true });
    throw new CliError(`Could not create a private credentials file at ${file}: ${error.message}\nNothing was stored.`, 1);
  }
}

export async function setupMain({ env = process.env } = {}) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new CliError('setup-tokens must be run by a person in an interactive terminal. Agents: ask the user to run it.', 2);
  }
  const file = tokensFilePath(env);
  const current = fs.existsSync(file) ? parseTokens(fs.readFileSync(file, 'utf8')) : {};
  const kept = value => (value ? ' [Enter keeps the stored one]' : '');

  process.stdout.write(`Cloudflare credentials will be stored in:\n  ${file}\n
Account ID: the 32-character ID in the dashboard address, dash.cloudflare.com/<account-id>/...
Read token: Manage Account > Account API Tokens > Create Token > "Read all resources" template.
Write token: leave it blank. Without it the agent can only read; you make changes in the dashboard.\n\n`);

  const tokens = {
    CF_ACCOUNT_ID: await askChecked(`Account ID${kept(current.CF_ACCOUNT_ID)}: `, current.CF_ACCOUNT_ID, checkAccountId),
    CF_TOKEN_READ: await askChecked(`Read-only token (input hidden)${kept(current.CF_TOKEN_READ)}: `, current.CF_TOKEN_READ, checkToken, { hidden: true }),
    CF_TOKEN_WRITE: await askChecked(
      `Write token (input hidden, optional; blank = ${current.CF_TOKEN_WRITE ? `keep the stored one, "${CLEAR}" = remove it` : 'writes stay disabled'}): `,
      current.CF_TOKEN_WRITE, checkToken, { hidden: true, optional: true }),
  };

  writePrivateFile(file, serializeTokens(tokens));

  process.stdout.write(`\nStored in ${file}\n  account ID: ${tokens.CF_ACCOUNT_ID}\n  read token: set\n`);
  process.stdout.write(tokens.CF_TOKEN_WRITE
    ? '  write token: set - the agent can now apply changes you approve in chat\n'
    : '  write token: not set - the agent is read-only (recommended)\n');

  process.stdout.write('\nChecking the read token...\n');
  try {
    await readMain({ argv: ['verify'], env });
    process.stdout.write('The read token works.\n');
  } catch (error) {
    if (!(error instanceof CliError)) throw error;
    throw new CliError(`${error.message}\nThe credentials were saved, but the check failed. Fix the token or account ID and run this again.`, 1);
  }
  return 0;
}

if (isMain(import.meta.url)) await runCli(setupMain);
