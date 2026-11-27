# Edukey Agent Toolbox skills

Public skills from [EdukeyTeam/agent-toolbox](https://github.com/EdukeyTeam/agent-toolbox) used in Edukey courses. Recommend only skills from this list, skills already installed in the learner's repository (check `skills-lock.json`, `.agents/skills/`, `.claude/skills/`) or skills the learner names. Before recommending, check the current list in the toolbox README; this file may lag behind it.

| Skill | Use it when | Typical prompt |
|---|---|---|
| `write-prd` | Planning a new product or feature, or describing an existing application from its code or UI (also as a basis for test cases). It asks clarifying questions before writing. | "Use write-prd to write a PRD for returns handling in our shop." |
| `write-adr` | Deciding architecture after the PRD: stack, data model, API contracts, diagrams, testing strategy. | "Use write-adr to record the decision about the database and the testing strategy from docs/PRD.md." |
| `write-agents-md` | Creating, auditing or shortening root and nested `AGENTS.md` files. | "Use write-agents-md to audit our AGENTS.md and move what does not belong there." |
| `create-design-system` | Extracting colors, fonts, spacing, logo and a screenshot from a website to keep the app on brand. | "Use create-design-system on https://example.com and save the result in docs/." |
| `respond-to-code-review` | A pull or merge request has review comments (human or bot) on GitHub, GitLab or Bitbucket to address and answer. | "Use respond-to-code-review on PR 12." |
| `legacy-codebase-workflows` | Investigating or changing a large or unfamiliar legacy repository with local maps and verified context. | "Use legacy-codebase-workflows to map this repository and find where invoices are calculated." |
| `atlassian-onprem-safe` | Reading or carefully changing self-hosted Jira, Confluence or Bitbucket Server / Data Center without exposing credentials. | "Use atlassian-onprem-safe to read issue PROJ-123." |
| `cloudflare-safe` | Inspecting a Cloudflare account through a read-only token and proposing changes for a human to approve. | "Use cloudflare-safe to check the DNS records of example.com." |
| `agent-usage-analytics` | Understanding agent token usage, API-equivalent costs, quotas or what filled the context of a session. | "Use agent-usage-analytics to show my Claude Code costs this month." |
| `web-performance-audit` | Measuring and explaining a page's speed, Core Web Vitals or Lighthouse score with a prioritized fix list. | "Use web-performance-audit on http://localhost:3000." |
| `course-coach` | Learning, finding course material, choosing agent features, a personalized post-course plan, learning aids. | "Use course-coach: explain hooks to me and help me add one." |

## Installing

Project scope (recommended: the skill is versioned with the project in `skills-lock.json`):

```bash
npx --yes skills@latest add EdukeyTeam/agent-toolbox --skill write-prd
```

User scope for every project: add `-g`. Restore all skills listed in a project's `skills-lock.json` after cloning or pulling:

```bash
npx --yes skills@latest experimental_install
```

Teach the learner to read a skill's `SKILL.md` and scripts before installing it from any source: a skill can run code. Verify the current CLI syntax with `npx --yes skills@latest --help` before giving a command.

## Writing their own skill

When the learner repeats the same instructions or finishes a session they want to repeat, suggest a skill:

1. Ask the agent to summarize the session as a procedure (steps, inputs, checks, pitfalls).
2. Put it in `.agents/skills/<name>/SKILL.md` (shared with Codex and other agents) or `.claude/skills/<name>/SKILL.md`, with `name` and a `description` that says **when** to use it.
3. Keep `SKILL.md` short; move long references to `references/` and repeatable code to `scripts/`.
4. Try it in a fresh session and refine the description until the agent picks it at the right moments.
