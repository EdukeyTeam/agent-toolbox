# Edukey Agent Toolbox

Practical skills for AI agents, created by [Edukey](https://edukey.ai) and shared with our course participants, clients, and the wider community. The first skills help developers plan software, capture website design systems, respond to code review, and work safely with Cloudflare. We plan to add business skills and plugin bundles for easier installation.

## Available skills

| Skill | What it helps you do |
| --- | --- |
| [write-agents-md](skills/write-agents-md/SKILL.md) | Create minimal, durable root and nested AGENTS.md guidance from web or desktop templates, copied before adaptation. |
| [write-prd](skills/write-prd/SKILL.md) | Interview stakeholders and write a product requirements document (PRD). |
| [write-adr](skills/write-adr/SKILL.md) | Write Architecture Decision Records (ADRs) covering system design, data models, API contracts, diagrams, and testing strategy. |
| [create-design-system](skills/create-design-system/SKILL.md) | Extract design tokens, a screenshot, and available brand assets from a website. |
| [respond-to-code-review](skills/respond-to-code-review/SKILL.md) | Address and answer review comments on GitHub, GitLab, or Bitbucket pull and merge requests. |
| [legacy-codebase-workflows](skills/legacy-codebase-workflows/SKILL.md) | Investigate and change unfamiliar legacy repositories with local maps, verified source context, optional workers and private retrieval. |
| [cloudflare-safe](skills/cloudflare-safe/SKILL.md) | Let an agent inspect a Cloudflare account through a read-only token it never sees, and propose changes for you to approve. |
| [agent-usage-analytics](skills/agent-usage-analytics/SKILL.md) | Analyze agent tokens, API-equivalent costs, quotas and individual-session context; generate JSON, Markdown and offline HTML reports. |
| [web-performance-audit](skills/web-performance-audit/SKILL.md) | Measure a live page with Chrome DevTools CLI/MCP and Lighthouse (field vs lab vitals, LCP subparts, third parties, INP, memory) and save a Markdown and an interactive HTML report with prioritized fixes in `docs/`. |

## Install a skill

The recommended installer is the [skills CLI](https://skills.sh/). You need Node.js and an AI agent that supports skills. For example, to install the design-system skill for your user account:

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill create-design-system -g
```

Replace `create-design-system` with `write-agents-md`, `write-prd`, `write-adr`, `respond-to-code-review`, `legacy-codebase-workflows`, `cloudflare-safe`, `agent-usage-analytics`, or `web-performance-audit` to install another skill. The installer asks which agent to target when needed. To keep a skill in one project, run this from that project's root instead:

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill create-design-system --project
```

Then ask your agent to use the installed skill. For example: “Use create-design-system to document the visual style of this website.” The agent reads the skill's instructions and may need to set up a tool the first time it runs; each skill documents its own requirements.

To see your installed user-level skills or refresh them later:

```bash
npx --yes skills@latest list -g
npx --yes skills@latest update -g
```

## Install the whole toolbox

To add every skill in one run with the [skills CLI](https://skills.sh/), use `--skill '*'`. The installer lets you choose which agent to target. `--all` also targets every supported agent, so it is not needed here.

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill '*' -g
```

### Codex CLI and Codex app

Codex CLI 0.162.1 supports this repository as a marketplace containing one plugin with every skill. Register the marketplace, then install the toolbox:

```bash
codex plugin marketplace add EdukeyTeam/agent-toolbox
```

```bash
codex plugin add agent-toolbox@edukey-agent-toolbox
```

Start a new Codex session after installation. Use `codex plugin list --marketplace edukey-agent-toolbox` to check the installation, or `/plugins` in an interactive CLI session. In [Codex in the ChatGPT desktop app](https://learn.chatgpt.com/docs/plugins), restart the app, open the **Plugins** tab, select the **Edukey Agent Toolbox** marketplace, then open **agent-toolbox** and install it. Register the marketplace with the CLI on the same backend the app uses; the [local marketplace guide](https://developers.openai.com/plugins/build/plugins#build-your-own-curated-plugin-list) describes app discovery.

To update, refresh the Git marketplace and install the plugin again, then start a new session:

```bash
codex plugin marketplace upgrade edukey-agent-toolbox
```

```bash
codex plugin add agent-toolbox@edukey-agent-toolbox
```

To remove the plugin and its marketplace registration:

```bash
codex plugin remove agent-toolbox@edukey-agent-toolbox
```

```bash
codex plugin marketplace remove edukey-agent-toolbox
```

The configuration equivalent is a `[marketplaces.edukey-agent-toolbox]` table in `config.toml` with `source_type = "git"` and `source = "https://github.com/EdukeyTeam/agent-toolbox.git"`; an optional `ref` pins a branch, tag or commit. This registers the source; installing the plugin is a separate step. Trusted projects can set `[plugins."agent-toolbox@edukey-agent-toolbox"]` with `enabled = true` or `false` in `.codex/config.toml`. See the [configuration reference](https://developers.openai.com/codex/config-reference). The toolbox reuses the root `plugin.json` and `skills/`; no separate Codex skill copies are needed.

### Claude Code and Claude Desktop / Cowork

This repository is also a Claude plugin marketplace. Register the marketplace, then install its plugin from a terminal:

```bash
claude plugin marketplace add EdukeyTeam/agent-toolbox
claude plugin install agent-toolbox@edukey-agent-toolbox
```

In Claude Desktop or Cowork, open **Customize → Plugins**, add this GitHub repository as a marketplace, then install **Agent Toolbox**. A maintainer can also build a ZIP for manual upload with PowerShell 7:

```powershell
pwsh -NoProfile -File ./scripts/build-claude-plugin.ps1
```

The ZIP builder includes every folder under `skills/` that has a `SKILL.md`. It creates a file in `~/Downloads/Claude Plugins/` by default; it does not install the plugin or change your agent settings.

### GitHub Copilot CLI

Copilot CLI can install the same repository as a plugin using its root plugin manifest:

```bash
copilot plugin install EdukeyTeam/agent-toolbox
```

The skills CLI remains an option for Codex and other supported agents when you want to install skills directly. The root `plugin.json` provides a portable plugin manifest shared by Codex and Copilot; publishing in a public plugin directory is separate from registering this repository as a marketplace.

## Contribute

Skills live in `skills/<name>/`. Open a pull request for a new skill or a change to an existing one. Include tests for executable behavior and describe a realistic manual trial for instruction-only skills. The [validation workflows](docs/ci.md) use built-in path filters to run only for their inputs; [AGENTS.md](AGENTS.md) has the contribution rules.

Brand assets extracted from other sites may be licensed. Check usage rights before reusing or redistributing them.
