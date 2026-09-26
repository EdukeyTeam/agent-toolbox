# Edukey Agent Toolbox

Practical skills for AI agents, created by [Edukey](https://edukey.ai) and shared with our course participants, clients, and the wider community. The first skills help developers plan software and capture website design systems. We plan to add business skills and plugin bundles for easier installation.

## Available skills

| Skill | What it helps you do |
| --- | --- |
| [write-prd](skills/write-prd/SKILL.md) | Interview stakeholders and write a product requirements document (PRD). |
| [write-adr](skills/write-adr/SKILL.md) | Document architecture decisions (ADRs) for a feature or application. |
| [create-design-system](skills/create-design-system/SKILL.md) | Extract design tokens, a screenshot, and available brand assets from a website. |

## Install a skill

The recommended installer is the [skills CLI](https://skills.sh/). You need Node.js and an AI agent that supports skills. For example, to install the design-system skill for your user account:

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill create-design-system -g
```

Replace `create-design-system` with `write-prd` or `write-adr` to install either of those. The installer asks which agent to target when needed. To keep a skill in one project, run this from that project's root instead:

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill create-design-system --project
```

If you previously installed `write-a-prd` or `create-adr`, remove those old names and install `write-prd` and `write-adr`. A skills update does not rename an installed folder.

Then ask your agent to use the installed skill. For example: “Use create-design-system to document the visual style of this website.” The agent reads the skill's instructions and may need to set up a tool the first time it runs; each skill documents its own requirements.

To see your installed user-level skills or refresh them later:

```bash
npx --yes skills@latest list -g
npx --yes skills@latest update -g
```

## Contribute

Skills live in `skills/<name>/`. Open a pull request for a new skill or a change to an existing one. Include tests for executable behavior and describe a realistic manual trial for instruction-only skills. The [test workflow](.github/workflows/test-skills.yml) checks pull requests; [AGENTS.md](AGENTS.md) has the contribution rules.

Brand assets extracted from other sites may be licensed. Check usage rights before reusing or redistributing them.
