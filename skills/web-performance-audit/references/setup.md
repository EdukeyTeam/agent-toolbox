# One-time setup: Chrome DevTools CLI, MCP and skills

Upstream project: https://github.com/ChromeDevTools/chrome-devtools-mcp. Check its `docs/cli.md` and `docs/client-configurations.md` for changes before following these steps.

## 1. CLI (`chrome-devtools`)

The npm package `chrome-devtools-mcp` ships two binaries: `chrome-devtools-mcp` (the MCP server) and `chrome-devtools` (the CLI). Install it globally with the project's or user's package manager:

```bash
pnpm add -g chrome-devtools-mcp@latest
```

```bash
npm install -g chrome-devtools-mcp@latest
```

On pnpm, a global install fails with "The configured global bin directory ... is not in PATH" until `pnpm setup` has been run once. `pnpm setup` adds `PNPM_HOME` to the user's PATH permanently. Tell the user before running it. Already-open shells and apps (including the agent's own host app) only see the new PATH after a restart; until then, prefix commands with the bin directory or call the binary by its full path.

Check the install:

```bash
chrome-devtools status
```

The CLI talks to a background daemon over a socket (a named pipe on Windows). The first tool call starts the daemon and a browser. Later calls reuse them, so pages, cookies and state persist. By default the browser is **headless and isolated** (a temporary profile). Useful commands:

```bash
chrome-devtools start --help
chrome-devtools stop
chrome-devtools <tool> --help
```

Required parameters are positional and optional ones are flags. For example: `chrome-devtools click 2 "1_4"`, or `chrome-devtools evaluate_script "() => document.title" --pageId 2`. For long scripts, write the function to a file and pass `"$(cat file.js)"`. Inline quoting of regexes and nested quotes breaks easily.

## 2. Attach to the user's real Chrome (logged-in or consented state)

Chrome 144+ can expose its running instance without restarting:

1. The user opens `chrome://inspect/#remote-debugging` and enables remote debugging.
2. Start the daemon attached to that browser:

```bash
chrome-devtools stop
chrome-devtools start --autoConnect
```

3. Chrome may show an "Allow remote debugging?" prompt. The user must click Allow. If a command hangs with "Timeout waiting for daemon response" right after `--autoConnect`, the prompt is usually waiting. Ask the user to check Chrome, and do not retry in a loop.

When attached, `list_pages` shows all of the user's tabs. Open your own tab for measurements, never navigate the user's tabs, and close your tabs when done. Extension tools are disabled in this mode.

## 3. MCP server (optional, for interactive use)

Generic MCP client entry:

```json
{
  "mcpServers": {
    "chrome-devtools": { "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"] }
  }
}
```

On Windows desktop clients, use `"command": "npx.cmd"`.

- Claude Code (user scope): `claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest`
- Claude Code plugin (MCP + skills in one step): `/plugin marketplace add ChromeDevTools/chrome-devtools-mcp`, then `/plugin install chrome-devtools-mcp@chrome-devtools-plugins`. Remove any existing `chrome-devtools` MCP entry first, or the client runs two servers that fight over the same browser profile.
- Codex, Copilot, Cursor, Gemini and others: see upstream `docs/client-configurations.md`.

Useful server flags:

- `--autoConnect`: attach to the user's Chrome
- `--isolated`: temporary profile
- `--headless`
- `--no-usage-statistics`
- `--no-performance-crux`: stops sending trace URLs to the CrUX API, but also removes field data from trace summaries

Allow the tools in project permissions if the client supports it, for example `"Bash(chrome-devtools:*)"` and `"mcp__chrome-devtools"` in Claude Code.

## 4. Upstream skills

Install the official skills from their source; do not copy them. They are:

- `chrome-devtools`
- `chrome-devtools-cli`
- `debug-optimize-lcp`
- `memory-leak-debugging`
- `a11y-debugging`
- `cookie-debugging`
- `troubleshooting`

```bash
npx --yes skills@latest add ChromeDevTools/chrome-devtools-mcp -g -a universal -a claude-code -s "*" -y
```

Pass both `-a universal` and `-a claude-code`. With `-a claude-code` alone, the CLI copies the skills into `~/.claude/skills` instead of linking them from the shared `~/.agents/skills` directory, so other agents keep stale copies.

Other skills that informed this workflow, which you can read or install from their sources: `addyosmani/web-quality-skills` (`performance`, `core-web-vitals`, and its `references/MEASUREMENT.md`) and `cloudflare/skills` (`web-perf`).

## 5. Lighthouse CLI

No install needed. [scripts/run-lighthouse.mjs](../scripts/run-lighthouse.mjs) runs `npx --yes lighthouse@<version>` in a clean headless Chrome. Pass `--lighthouse <version>` to pin a version for before/after comparisons.
