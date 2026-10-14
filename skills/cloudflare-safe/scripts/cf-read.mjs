#!/usr/bin/env node
// cf-read.mjs - read from the Cloudflare API with the stored read-only token.
//
//   node cf-read.mjs <api-path>                    GET https://api.cloudflare.com/client/v4/<api-path>
//   node cf-read.mjs 'zones?name=example.com'
//   node cf-read.mjs 'accounts/{account_id}/rulesets'   {account_id} is filled from the credentials file
//   node cf-read.mjs verify                        check that the token is active
//   node cf-read.mjs graphql <query> [variables-json]   GraphQL Analytics query (read-only)
//
// The token is sent only to api.cloudflare.com and is never printed.
// Exit codes: 0 success, 1 API error, 2 usage, 3 credentials file missing, 4 token missing.
import { CliError, callApi, formatBody, isMain, loadTokens, resolveApiUrl, runCli } from './lib.mjs';

const USAGE = `Usage: node cf-read.mjs <api-path>
       node cf-read.mjs verify
       node cf-read.mjs graphql <query> [variables-json]`;

async function verify({ token, accountId, fetchImpl }) {
  // Account-owned tokens verify under the account; user-owned tokens under /user.
  const paths = accountId ? [`accounts/${accountId}/tokens/verify`, 'user/tokens/verify'] : ['user/tokens/verify'];
  let result;
  for (const candidate of paths) {
    result = await callApi({ url: resolveApiUrl(candidate), token, fetchImpl });
    if (result.ok && result.json?.success) break;
  }
  return result;
}

export async function readMain({
  argv = process.argv.slice(2),
  env = process.env,
  fetchImpl = globalThis.fetch,
  stdout = process.stdout,
} = {}) {
  const [target, ...rest] = argv;
  if (!target || target === '-h' || target === '--help') throw new CliError(USAGE, 2);

  const { file, tokens } = loadTokens(env);
  const token = tokens.CF_TOKEN_READ;
  const accountId = tokens.CF_ACCOUNT_ID || '';
  if (!token) throw new CliError(`CF_TOKEN_READ is empty in ${file}. Ask the user to run setup-tokens.mjs.`, 4);

  let result;
  if (target === 'verify') {
    result = await verify({ token, accountId, fetchImpl });
  } else if (target === 'graphql') {
    const [query, variablesJson] = rest;
    if (!query) throw new CliError(USAGE, 2);
    if (/^\s*mutation\b/i.test(query)) throw new CliError('cf-read only runs GraphQL queries, not mutations.', 2);
    let variables = {};
    if (variablesJson) {
      try { variables = JSON.parse(variablesJson); } catch { throw new CliError('variables-json is not valid JSON.', 2); }
    }
    result = await callApi({
      url: resolveApiUrl('graphql'), method: 'POST', token, body: { query, variables }, fetchImpl,
    });
  } else {
    if (rest.length) throw new CliError(`Unexpected arguments. Quote the path if it contains spaces or "&".\n${USAGE}`, 2);
    result = await callApi({ url: resolveApiUrl(target, accountId), token, fetchImpl });
  }

  stdout.write(`${formatBody(result, [tokens.CF_TOKEN_READ, tokens.CF_TOKEN_WRITE])}\n`);
  const failed = !result.ok || result.json?.success === false || (Array.isArray(result.json?.errors) && result.json.errors.length > 0);
  if (failed) throw new CliError(`Cloudflare API returned HTTP ${result.status}.`, 1);
  return 0;
}

if (isMain(import.meta.url)) await runCli(readMain);
