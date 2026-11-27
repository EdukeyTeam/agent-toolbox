# Post-course plan and guided setup

Goal: turn a generic post-course checklist into a short plan that fits one person, then help them put it into practice on their own machine and projects, one step at a time.

## Steps

1. **Read what the course offers.** Find the course's own post-course checklist and decision table through the course guide (often `course-materials/references/*checklist*.md` or a checklist page on the hub). Use its items and wording as the source; [choosing agent features](choosing-features.md) is only the fallback.
2. **Interview.** Use [learner interview](learner-profile.md). Inspect their actual project read-only when they work in it: build files, `AGENTS.md`, agent settings, installed skills, hooks, CI files.
3. **Draft the plan** from [the template](../templates/learning-plan.md): keep 3-5 items for "this week", the rest in "later". Every item has a reason tied to their answers, a done condition and a link to the course material. Drop items that do not fit their stack or company policy instead of keeping them "just in case".
4. **Review together.** Show the plan, ask what to remove or change, then save it where they choose.
5. **Guided setup.** Work through the "this week" items one at a time, in the learner's real project. For each item:
   - explain what it does and the risk it addresses;
   - show the official documentation or course example;
   - let the learner make the change (or approve your edit), run it, and see the effect;
   - tick the item in the plan with the date.
6. **Close.** Summarize what is configured, what is next, and offer a learning aid or a reminder (for example a scheduled task, if their agent supports it and they want one).

## Typical setup items

Pick only what fits. Verify every command and setting against current documentation before showing it.

| Item | Done when |
|---|---|
| Short root `AGENTS.md` (with `CLAUDE.md` importing `@AGENTS.md` for Claude Code) holding real build, test and lint commands and the definition of done | a fresh session runs the tests without asking how |
| Nested `AGENTS.md` for a module with its own conventions | the agent follows the module rule when working there |
| Permission rules: narrow allow rules for safe commands, deny rules for secrets and production | fewer prompts, and a test shows a denied command is blocked |
| Hook: format or lint after edits, block writes to secret files | the hook fires in a test edit |
| Statusline with model, context use and cost | visible in the next session |
| Context7 (MCP or `ctx7` CLI) and an `AGENTS.md` rule to check docs there first | the agent cites current docs for a library question |
| CLI access to the repository host (`gh`, `glab`, `az`) with a least-privilege token | the agent can list issues or open a PR |
| Install 1-3 toolbox skills that match their work | the skill shows in the agent and was used once |
| Write their first own skill from a repeated task | it triggers on a matching request in a fresh session |
| Plan mode or a plan file before larger changes | one feature delivered from a plan |
| Subagent for research or review | one task delegated, with a short report back |
| Agent review in CI (with the team's approval) | a PR receives an automated review |
| Weekly learning habit: one channel or newsletter from the course index | added to their calendar |

## Safety notes

- Never ask the learner to paste tokens or passwords. Show where to store them (environment variables, the OS credential store, CI secrets).
- Company and shared configuration (managed settings, CI secrets, organization-wide MCP) goes through their team or administrator.
- Back up a config file before editing it, and show the learner how to undo the change.
