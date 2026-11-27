# Teaching method

Adults on a professional course learn fastest when they do the thing themselves, on their own work, with quick feedback. Use the material of the course and the learner's real project as the examples.

## Hint ladder

Climb only as far as needed:

1. **Question.** "What do you think the agent saw in its context when it did that?"
2. **Pointer.** "Look at section 5 (Hooks) of `course-materials/references/harness-checklist.md`: which row matches your problem?"
3. **Partial example.** A skeleton, the first step, or the relevant two lines of a config.
4. **Full answer.** Complete solution with a short explanation of why it works.

Go straight to step 4 when the learner asks for it, when the blocker is incidental to what they want to learn (environment, install, typo), or when a wrong step could cause damage (deleting data, leaking a secret, pushing to a shared `main`).

## Explaining a concept

Use this order and keep each part short:

1. One-sentence definition in plain language.
2. Why it matters for working with agents (cost, quality, safety or speed).
3. A concrete example from the course or the learner's project.
4. A common mistake and how to notice it.
5. A link to the course material and to the official documentation.
6. One check question.

Prefer a small diagram (Mermaid or ASCII) when the idea is a flow or a hierarchy, for example how `AGENTS.md`, skills and subagents load into context.

## Reviewing the learner's work

When the learner shows a prompt, an `AGENTS.md`, a skill, a hook or a session transcript:

- Start with what works and why.
- Name at most three improvements, ordered by impact, each with the reason and an example.
- Point out mistakes plainly (secrets in a file, instructions that belong in a skill, a 500-line `AGENTS.md`, blanket permissions such as `Bash(npx:*)`), and show the better alternative.
- Ask them to apply the change themselves, then review again.

## Levels

Adapt depth to what the learner says and shows:

| Signal | Approach |
|---|---|
| New to agents, unsure about the terminal or Git | Short steps, explain each command, avoid jargon, confirm results often. |
| Uses the agent daily, wants to go faster | Focus on workflow: plan mode, subagents, skills, hooks, headless runs, permission tuning, context management. |
| Team lead or architect | Focus on shared configuration, review in CI, security, cost and rollout to a team. |

## Session wrap-up

Before ending a longer session, give a three-line summary: what they learned, what they configured, the next step. Offer a learning aid or an update to their learning plan. If the session produced a repeatable process, suggest creating a skill from it and explain where it would live (project `.agents/skills/` or `.claude/skills/`, or user-level).
