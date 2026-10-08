# Repository-context intake

Infer available facts first. Ask only unanswered questions that change the next action, at most three together. Skip this intake for a known-file edit. Keep client-sensitive answers in an authorized local location.

## Minimal questions

1. What question or change matters now: lookup, impact/callers, prose discovery, runtime wiring, or edit?
2. Which modules/application and shared core paths are involved? For similar modules, which one is intended?
3. What may be processed or written, and where should results go?
4. For impact navigation only: what javac/classpath or IDE metadata do developers actually use?
5. If considering an index: does this question type recur, and how often do files/branches change?

## Pilot design only

Use these prompts only after baseline search/maps show a repeated gap. Establish the eligible source/file/chunk scope, data boundary, acceptable latency/setup/update costs and users/concurrency. Derive held-out questions from past tickets/commits with independently verified expected ranges; do not require the user to produce an evaluation set before ordinary investigation. Include wrong-module near duplicates, absent APIs, source edits/deletions and wiring. Agree baseline, adoption threshold and stop criteria before tuning. See [scale and intake](../references/scale-and-intake.md).

## One decision record

- Question type, active paths/core dependencies and permitted actions:
- Known facts with evidence; remaining unknowns:
- Selected next action and exact output destination (default docs/repo-maps when repository writes are authorized):
- Examined revision/fingerprint and refresh boundary:
- If a pilot is justified: observed gap, baseline, held-out evidence, cost ceiling, adoption/stop rule:
- Next small iteration and completion evidence:
