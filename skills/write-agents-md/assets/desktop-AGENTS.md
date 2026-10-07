# Repository Guidelines

## Project

{{PROJECT_CONTEXT}}

All user-facing text in **{{CHAT_LANGUAGE}}** on chat. Repository documentation always in **{{DOCUMENTATION_LANGUAGE}}**. {{UI_LANGUAGE_POLICY}}

{{NON_OBVIOUS_LANGUAGE_OR_FRAMEWORK_CONSTRAINT}}

Documentation entry point: [{{DOCUMENTATION_LABEL}}]({{DOCUMENTATION_PATH}}).

## Repository Layout

{{NONSTANDARD_LAYOUT_RULES}}

## Agent Workflow

Agreed requirements and existing PRD/ADR/design decisions govern changes; define expected behavior before code.

### TDD Rules

For every feature and bug fix:
1. Start from the specification, not the existing implementation.
2. Write or extend tests **before** production code.
3. Run the new tests and confirm they fail for the expected reason.
4. Implement the minimum code needed to make them pass.
5. Run the full verification suite for the changed scope.
6. Refactor only while tests stay green.
7. **Manually validate the running application** (see Manual QA below). Automated tests — especially E2E — can produce false passes; a task is not done until the real app has been exercised by hand.

If the area has no suitable test infrastructure yet, add it as part of the task — do not silently skip tests.

### Manual QA

Use **{{DESKTOP_QA_METHOD}}** on real windows: affected flows, changed-screen screenshots and application errors. Report evidence; headless tests do not prove GUI behavior. Missing access is blocked.

### Test Strategy

| Type | Mocks |
|---|---|
| Unit | Dependencies may be isolated |
| Integration | Mocks allowed when useful; endpoint fixtures require a fresh real response |
| E2E and Manual QA | **Zero mocks; fully working real stack, including real LLM calls** |

Endpoint mocks must use a complete response saved verbatim from a fresh real query; never invent objects from documentation. Missing access or budget blocks a required real check.

### Verification

Verify the changed scope before committing: startup, tests and Manual QA for runtime changes; content/links for documentation. Tests passing ≠ app working.

### Commit Rules

- Commit only after verification passes and the changed scope is in a working state.
- Keep commits focused: one logical change per commit.
- Format: `Area: short summary`.
- Do **not** push to remote unless the user explicitly asks.
- Stage explicit paths and preserve unrelated work.

### Completion Criteria

Complete only with agreed behavior, honest verification, required QA evidence and a reviewable result. Investigate failures/new warnings; report blockers.

Update affected repository instructions and documentation in the same logical change whenever enduring project facts or policies change.
