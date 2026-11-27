# Learner interview

Use for a personalized plan. Ask in two or three short rounds, with selectable answers when the harness has a question tool. Skip what the learner already told you or what you can see in their repository (stack, package manager, existing `AGENTS.md`, `.claude/settings.json`, installed skills).

## Round 1: context

1. Role: developer (backend, frontend, full stack, mobile), data or ETL, tester, DevOps, architect or team lead, other.
2. Main languages, frameworks and databases at work.
3. Repository host and CI: GitHub, GitLab, Bitbucket, Azure DevOps; self-hosted or cloud.
4. Operating system and terminal: Windows (PowerShell, WSL), macOS, Linux.
5. Agents available at work and their plans: Claude Code, Codex, Copilot, other; company policy restrictions.

## Round 2: practice

6. How often do you use an agent today: not yet, occasionally, daily?
7. Greenfield, legacy, or both? Size and age of the main codebase.
8. What takes most of your time that an agent could help with (tests, reviews, migrations, documentation, SQL, debugging)?
9. What went wrong or felt risky when using agents so far?

## Round 3: goals and time

10. One concrete goal for the next 30 days.
11. Time per week for learning and setup.
12. Preferred learning style: reading, short exercises, videos, building on real work.

## From answers to a plan

- Choose 3-5 setup items that pay off immediately for this person (for example: a short `AGENTS.md` with real commands, narrow permission rules, a format/lint hook, Context7, a statusline showing context use).
- Choose one weekly practice habit tied to their real work (one task per day planned in plan mode, one review per week done with an agent).
- Choose resources: two or three course files and one or two people or channels from the course index matching their stack.
- Put risky or company-level changes (CI tokens, shared settings, MCP with production access) behind "agree with your team or administrator first".
