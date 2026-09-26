# Edukey Agent Toolbox

Practical skills for AI agents, created by [Edukey](https://edukey.ai) and shared with our course participants, clients, and the wider community. The first skills help developers plan software and capture website design systems. We plan to add business skills and plugin bundles for easier installation.

## Available skills

| Skill | What it helps you do |
| --- | --- |
| [write-prd](skills/write-prd/SKILL.md) | Interview stakeholders and write a product requirements document (PRD). |
| [write-adr](skills/write-adr/SKILL.md) | Write Architecture Decision Records (ADRs) covering system design, data models, API contracts, diagrams, and testing strategy. |
| [create-design-system](skills/create-design-system/SKILL.md) | Extract design tokens, a screenshot, and available brand assets from a website. |
| [respond-to-code-review](skills/respond-to-code-review/SKILL.md) | Address and answer review comments on GitHub, GitLab, or Bitbucket pull and merge requests. |

## Install a skill

The recommended installer is the [skills CLI](https://skills.sh/). You need Node.js and an AI agent that supports skills. For example, to install the design-system skill for your user account:

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill create-design-system -g
```

Replace `create-design-system` with `write-prd`, `write-adr`, or `respond-to-code-review` to install another skill. The installer asks which agent to target when needed. To keep a skill in one project, run this from that project's root instead:

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

For Codex and other agents, the skills CLI command above installs the skills directly. The root `plugin.json` also provides a portable plugin manifest; availability in a particular plugin catalog depends on that catalog's publishing process.

## Contribute

Skills live in `skills/<name>/`. Open a pull request for a new skill or a change to an existing one. Include tests for executable behavior and describe a realistic manual trial for instruction-only skills. The [test workflow](.github/workflows/test-skills.yml) checks pull requests; [AGENTS.md](AGENTS.md) has the contribution rules.

Brand assets extracted from other sites may be licensed. Check usage rights before reusing or redistributing them.
