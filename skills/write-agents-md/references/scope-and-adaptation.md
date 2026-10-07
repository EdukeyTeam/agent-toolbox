# Scope and adaptation

## Resolve placeholders without inventing requirements

| Placeholder | Adaptation |
|---|---|
| `{{PROJECT_CONTEXT}}` | One or two sentences of verified project type, purpose, audience, scope and client when one is known. Do not invent a client or copy example names. |
| `{{CHAT_LANGUAGE}}`, `{{DOCUMENTATION_LANGUAGE}}` | Agreed human communication/documentation languages, not programming languages. Preserve existing policy; ask if a new policy matters and is unknown. |
| `{{UI_LANGUAGE_POLICY}}` | Existing localization constraint, when known and relevant repository-wide. Otherwise remove. |
| `{{NON_OBVIOUS_LANGUAGE_OR_FRAMEWORK_CONSTRAINT}}` | A hidden constraint of the actual programming language, framework or internal library. Include the applicable technology only if it changes decisions; remove obvious stack metadata. Never list versions or name a language just to fill the slot. |
| `{{DOCUMENTATION_LABEL}}`, `{{DOCUMENTATION_PATH}}` | One existing documentation entry point with a relative link. Otherwise remove; do not fabricate a PRD, ADR or design guide. |
| `{{NONSTANDARD_LAYOUT_RULES}}` | Nonstandard roots and enduring consequences. Remove the entire Repository Layout section if there are none. |
| `{{DESKTOP_QA_METHOD}}` | Available computer-use tooling or Computer Commander/Command Commander MCP equivalent for real native windows. Do not assert an unavailable tool is installed. |

No `{{...}}` may remain in a finished AGENTS.md. Read metadata to avoid fabricated commands but keep tool-specific commands out of always-loaded output. Do not change communication language, UI locale, brand, architecture or scope to match a sample.

## Root versus nested

- **Root:** every agent in the repository must need the rule. A shared serialization compatibility boundary can qualify; one certificate-dialog repair does not.
- **Nested:** every agent doing anything in the subtree must need the rule. Synthetic test assets can qualify across a test subtree; instructions for only an FTPS test belong in a skill or a narrower genuinely distinct scope.
- Do not create files merely to describe obvious contents. If no distinct rule survives the admission test, omit that file and explain why.
- Adapt nested output from an exact copy of the selected web/desktop template, not a third template. Prune inherited Project/Layout/Workflow blocks; keep the scope purpose and unique folder-wide invariants.
- Reconcile existing human instructions. Relocate specific requirements rather than silently losing them. Use an appropriate existing skill for procedures; otherwise identify the separate skill needed.

Before keeping a sentence, finish: **Every agent in this scope must know this because…** An answer beginning “only when doing this particular task” means move it out. Standing verification/commit gates remain because every agent respects the same definition of a reviewable change; documentation agents do not thereby need to start the application.

## Preserve mandatory policies

At root retain the TDD sequence, missing-test-infrastructure requirement, real Manual QA, zero-mock E2E/Manual QA (including LLM connections) and freshly captured endpoint mocks for unit/integration, honest scoped verification, focused commits, no unrequested push and documentation maintenance. Keep TDD steps and core commit bullets word-for-word unless the user expressly changes them. Adapt domain wording/placeholders only after copying.

Nested files inherit these policies: remove repetition instead of weakening them. Explicit user instructions take precedence over defaults.

## Relocation

| Candidate | Destination |
|---|---|
| Exact versions, resolved dependency tree, architecture narrative | Manifests and maintained documentation |
| Session tools, host paths, sandbox failures | Environment-owned guidance outside the project |
| Feature migrations, fixtures, incident recovery, task-specific document triggers | Relevant skill |
| Branch/task status and pending execution | Tracker |
| Standard conventions or obvious layout | Omit |

A stable documentation reference can help; do not replace removed detail with a long link list.

## Existing guidance

Copy to a candidate first. Adapt, compare with prior human decisions, and reconcile in a reviewed edit. Preserve unrelated tool-specific guidance and user edits. A minimal CLAUDE import is appropriate only when requested/already used; do not discard CLAUDE-specific content.

Report template, scope, relocations, unresolved decisions and checks. Remove your candidate after reconciliation; never delete another person's draft.
