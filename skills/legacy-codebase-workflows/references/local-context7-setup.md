# Project-local Context7 setup

Use this short route for a requested local runtime/MCP integration. Reuse the
generator and assets; do not recreate launchers, hook handlers, client locks or
Windows fixes. Read [retrieval setup](retrieval-setup.md) for one-time engine
installation and consent gates, and [private retrieval](private-retrieval.md)
for usage, models and unusual corpus layouts.

## Ask first

At the start ask: "May I add a short AGENTS.md routing note and automatic
index-refresh hooks for this repository?" Show both additions and let the user
accept both, either or neither. Wait before changing instructions or hooks.
A local-search request, general repo write permission, course demonstration or
another repository's approval is not consent. Reuse an explicit answer already
given for this proposal in this repository; do not repeat a settled question.

Inspect the actual source root, client and existing project config. Reuse a
compatible existing local runtime after verification; do not overwrite one
just to generate it again. Configure
only requested clients. Start lexically; no model/vector package is required.
Choose /local/name from the actual checkout. Do not start or repair the app.

## Reuse the generator

Preview without writes:

    python /path/to/skill/scripts/setup_context7.py /path/to/repo --library-id /local/name --agent codex --dry-run

After the user approves both additions, acknowledge the answers:

    python /path/to/skill/scripts/setup_context7.py /path/to/repo --library-id /local/name --agent codex --clients --with-hooks --consent-hooks --with-agents-md --consent-agents-md

Use --agent claude, or repeat --agent for both requested clients. Omit declined
additions and their consent flags. Never manufacture consent. Without --clients,
preparation is offline. --clients uses pinned pnpm 11.1.1 with noninteractive
Corepack download handling and installs locked ctx7 0.5.13 and
@upstash/context7-mcp 4.0.3 externally using pnpm with lifecycle scripts disabled.
Global authentication and public MCP registrations remain unchanged.

The helper detects nested docs/; --docs-root selects another nested relative
directory. Repeat --exclude for extra exact relative paths. Generated tools,
agent config, installed skills and default RepoMap/RepoMix outputs are excluded.
For external docs or semantic models use the advanced backend directly.

From the project root:

    python tools/local_context7.py index

Exercise library/docs with a focused identifier and actual MCP initialize/list/
call. Compare a returned range/hash with source; inspect definitions/callers
before edits. Empty results are not absence proof. Avoid printing entire
sources, lockfiles or inventories during setup.

## Routing and refresh

Server context7-local exposes resolve-library-id and query-docs for /local/name.
Hosted Context7 remains for public external libraries. WezTerm is a terminal;
its agent chooses the tool. The official stdio client uses CONTEXT7_API_URL
pointing to a session-owned loopback server plus /api, with no cloud fallback.
Shared Git inventory detaches stdin from MCP, so no project monkeypatch is needed.

Hooks run refresh synchronously after write/edit/shell tools and at turn end.
Shell coverage catches scripted edits/deletions and commits without executing
input commands. Other checkouts are ignored. A fresh index is silent and incurs
no database writes. Refresh scans scope, HEAD and hashes; indexing replaces
only changed/new file chunks and removes deleted files. No single-file flag or
watcher exists. A commit without source edits updates provenance only.

Without active hooks, agents run python tools/local_context7.py refresh after
code/docs changes or commits and on HTTP 409; do not ask the human to memorize it.
Codex requires review in /hooks; Claude follows workspace/MCP trust. Restart/
reload before expecting new tools. Do not bypass trust or equate direct handler
checks with native interactive hook dispatch. Report verification layers honestly.

## Locations and delivery

Report briefly: server/library ID, generated files, actual runtime/database path,
coverage/skips, source/query evidence, hook consent/activation, commit/push state
and unexecuted checks. The helper emits paths and the next command.

Launcher/config, backend hashes, client lock, hooks and approved instructions
are reviewable repo files. Backend/helpers/notices are copied from this skill to
%LOCALAPPDATA%/local-context7/<path-hash>/ on Windows or
~/.cache/local-context7/<path-hash>/ elsewhere. SQLite, node_modules and isolated
empty credentials stay outside source/docs and Git. A clone needs the matching
skill and explicit setup. A local commit is not publication or fleet installation.

Refuse differing existing files/local-server entries before writes, preserving
unrelated config. Stale results are refreshed locally. Missing clients/backend
data need explicit setup; hash failures need a reviewed update. Keep skipped
non-UTF-8 locale files unchanged. For known Windows sandbox launch failures use
the environment's existing policy; do not repeat probes or disable the sandbox.

Contracts: [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude hooks](https://code.claude.com/docs/en/hooks),
[Context7 API override](https://github.com/upstash/context7/blob/master/packages/mcp/src/lib/constants.ts).
