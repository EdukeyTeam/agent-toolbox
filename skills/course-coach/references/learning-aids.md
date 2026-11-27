# Learning aids

Short, branded study materials built from what the learner just covered or from the course materials. Offer them; do not produce them unasked in the middle of a task.

## Choose the format

| Learner need | Kind | Size |
|---|---|---|
| Remember terms, commands, shortcuts, "which file for what" | `flashcards` | 8-20 cards |
| Check understanding after a topic or before using it at work | `quiz` | 5-12 questions |
| One page to keep open or print: commands, decision table, workflow | `cheatsheet` (also serves as a simple infographic) | 3-6 sections |

For a diagram-style infographic (a flow, a hierarchy), add a Mermaid diagram to a Markdown note or a cheat sheet item with `code`, or ask whether the learner wants a richer HTML page.

## Content rules

- Base every item on the course material or official documentation and add `source` (short title) and `sourceUrl` (a relative path inside the repository or an https link). Verify commands and settings before writing them; never invent flags.
- Tie items to the learner's stack and goals from their plan when you know them.
- Quiz: one clearly correct option, plausible distractors from real mistakes, an `explanation` that teaches why. Avoid "all of the above" and trick questions.
- Flashcards: one idea per card; the front is a question or a situation ("A rule must never be broken by the agent. Where does it go?"), the back is the answer with one reason.
- Use `inline code` with backticks and fenced code blocks with triple backticks inside text; no HTML (it is shown as text).
- Write in the learner's language; set `lang` to `pl` or `en` for the interface labels.

## Data format

```json
{
  "kind": "quiz",
  "lang": "pl",
  "title": "Hooki i uprawnienia w Claude Code",
  "subtitle": "Sprawdź się po module o konfiguracji agenta",
  "questions": [
    {
      "question": "Zasady, której agent nie może złamać, gdzie ją umieścić?",
      "options": ["W AGENTS.md", "W regułach deny w settings.json lub w hooku", "W prompcie"],
      "answer": 1,
      "explanation": "Instrukcje w Markdown to prośba; uprawnienia i hooki egzekwuje harness.",
      "source": "Harness checklist, sekcja 2",
      "sourceUrl": "course-materials/references/harness-checklist.md"
    }
  ]
}
```

- `flashcards`: `cards: [{ front, back, tag?, source?, sourceUrl? }]`
- `quiz`: `questions: [{ question, options: [..], answer: <index from 0>, explanation?, source?, sourceUrl? }]`
- `cheatsheet`: `sections: [{ title, items: [{ term, text?, code? }], source?, sourceUrl? }]`
- Optional `brand` overrides the course guide: `{ organizer, trainer, course, hub, logoSurface }`.

## Build

Write the JSON to a temporary file, then run from the repository root (Node.js 18+, no dependencies):

```bash
node <skill-dir>/scripts/build-learning-aid.cjs --data aid.json --out learning-aids/hooks-quiz.html --guide course-materials/COURSE-GUIDE.md
```

`<skill-dir>` is the folder of this skill, for example `.agents/skills/course-coach` or `.claude/skills/course-coach`. The script validates the data, embeds the organizer logo from the guide (or the Edukey logo when there is no guide or logo), and writes one self-contained HTML file with light and dark themes and a print layout. Use `--logo <file> --logo-surface light|dark` for another brand, or `--no-logo`. Fix every validation error it reports rather than editing the HTML by hand.

Open the file in a browser (or give the learner its path), check that it renders, then delete the temporary JSON. Commit learning aids only to the learner's own branch or fork.
