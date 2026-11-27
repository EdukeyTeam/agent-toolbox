# Choosing agent features

Use this when the learner asks "should this be an AGENTS.md rule, a skill, a hook...?". If the course has its own checklist or decision table (often in the course guide or `course-materials/references/`), quote and link that first; this file is the fallback and a summary.

## Two questions

1. **How long will it stay true?** One session, one task, one feature, the whole repository, the whole organization.
2. **Who needs it, and how often?** Every session in the repository, one module, some tasks, only this person.

Quick test: *"Will this be true in a month and needed in most sessions?"*

- Yes: `AGENTS.md` (or `CLAUDE.md` importing it) or settings.
- True in a month but needed rarely: a skill, a nested `AGENTS.md`, PRD/ADR or other docs.
- Not true in a month: the plan, the task, the PR description.

## Decision table

| Need | Put it in | Why |
|---|---|---|
| Build, test and lint commands, code conventions, definition of done | root `AGENTS.md`, short | needed in every session |
| Conventions of one module or folder | nested `AGENTS.md` in that folder | loads only when the agent works there |
| Something that must never happen (secrets, prod, destructive commands) | permissions in settings and hooks | enforced by the harness, not a request to the model |
| Formatting, linting, fast tests after edits; blocking sensitive files | hooks | deterministic, every time |
| A repeatable multi-step procedure, domain knowledge needed sometimes | skill (`SKILL.md` + scripts) | loaded only when relevant |
| Work that reads a lot but returns a short answer; parallel independent work; a restricted role | subagent | separate context and permissions |
| Personal preferences (language, tone, editor) | user-level memory or `~/.claude/CLAUDE.md` / user `AGENTS.md` | applies to you, not the team |
| Access to an external system | CLI first (`gh`, `glab`, `az`, `psql`); MCP when no good CLI exists or it needs structured tools | CLIs cost less context and the agent knows them |
| Library documentation | Context7 (MCP or `ctx7` CLI), then official docs | current versions, fewer tokens than web search |
| What to build and why | PRD | product decisions |
| How and why it is built this way | ADR | architecture decisions |
| Steps of the current task | plan (plan mode, a plan file, issues) | temporary |

## Common mistakes to point out

- A long root `AGENTS.md` (over about 150 lines) full of procedures: move procedures to skills and module rules to nested files.
- Secrets or tokens in instruction files or prompts.
- Broad allow rules that run arbitrary code (`npx`, `node`, `python`, `uv` with a wildcard); prefer narrow ones such as `Bash(npx vitest:*)`.
- Relying on a Markdown request for something that must be enforced: use permissions or a hook.
- Many MCP servers always on: each one costs context in every session.
- Installing a third-party skill without reading it: a skill can run scripts.
- Explaining the same thing to the agent for the third time instead of writing a skill.
