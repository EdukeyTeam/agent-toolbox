# Course map

A course repository often holds far more material than a participant can browse: slides, prompt libraries, research notes, checklists, chat archives, examples and configuration samples. Your job in Navigate mode is to answer "where is X?" with the exact file and heading, and to say in one sentence why it is the right one.

## 1. Read the course guide

Look in this order and stop at the first hit:

1. `course-materials/COURSE-GUIDE.md`
2. `COURSE-GUIDE.md` in the repository root
3. A file the learner names

The guide is written by the trainer. Its YAML frontmatter describes the course and the brand for learning aids; its body is a map of the materials. Format:

```yaml
---
course: AI for developers - from idea to MVP   # course title
organizer: Example Training Ltd                 # who runs the course (brand on learning aids)
organizer_logo: assets/brand/organizer.svg      # path relative to the repository root
logo_surface: light                             # light | dark: the background the logo is drawn for
trainer: Jane Doe                               # trainer credit on learning aids
hub: https://example.com/course/                # public materials hub, if any
language: pl                                    # language of the course materials
tools: [Claude Code, Codex CLI, GitHub Copilot] # agents taught in the course
---
```

Use [the guide template](../templates/course-guide.md) when a trainer asks you to create one.

## 2. Discover when there is no guide

Build a quick map yourself, read-only, and keep it in the conversation (do not write it into the repository unless asked):

1. `README.md`: course description, updates after each day, links to the hub, slides and checklists.
2. `AGENTS.md` / `CLAUDE.md`: how the repository is organized and what the agent must not do.
3. List `course-materials/` (or `docs/`, `materials/`) two levels deep. Typical folders: prompts or prompt examples, research, references and checklists, exercises, quizzes, agent configs, hooks examples, CI/CD examples, chat summaries.
4. Search by keyword with `grep -ril "<term>"` before opening large files; open only the section you need.
5. Look for an index file (a name containing `INDEX`) and read its headings first.

## 3. Answer well

- Give one best location first, then at most two alternatives.
- Link to the heading anchor when the file is long.
- Prefer summaries of the day over raw chat history; prefer verified research notes over chat messages.
- Prefer the newest material: day summaries and update notes at the top of the README override older notes on the same topic.
- If the material is outdated or wrong in the light of current documentation, say so and show the current source.
- If nothing fits, say so and propose where to look next (official docs, Context7, the trainer's hub).

## Material types and what to use them for

| Need | Look for |
|---|---|
| What happened on a given day, links shown live | day summaries and chat histories |
| "Where do I put this rule / procedure / secret?" | a harness or configuration checklist with a decision table |
| A prompt to copy | prompt examples or the prompt library on the hub |
| Ready configuration (permissions, hooks, statusline, aliases) | agent configs and hooks examples |
| CI/CD and code review with agents | CI/CD or headless examples |
| Background, evidence, numbers | research notes and the course index |
| People and channels to follow | the course index, section about people and accounts |
| Exercises and test data | exercises and exercise data folders |
