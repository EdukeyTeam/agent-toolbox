# Web workflow

Use for browser applications. Read [scope and adaptation](scope-and-adaptation.md) when resolving fields or nested scope.

## Copy and adapt

1. Copy `assets/web-AGENTS.md` exactly with the helper; use candidate mode for existing guidance.
2. Fill purpose, agreed chat/documentation languages and existing UI locale policy. Describe the actual project purpose, audience and client when known; do not invent a client or retain names from the example.
3. Include only non-obvious stack constraints and nonstandard layout consequences. Omit standard metadata and conventional source/test/assets maps.
4. Point to an existing documentation entry point; do not always load PRD/ADR/design files or create them just to match the sample.
5. Preserve the original seven TDD steps and commit bullets. The template generalizes the fixed dev command and brand details; integration mocks need captured real responses, while E2E/manual QA allow none. It requires no LLM, framework, typography, palette or secret variable.
6. Keep Manual QA/scoped verification as standing gates. Scenario steps and executable commands belong in task skills.
7. Apply root/nested admission review and remove unused blocks/placeholders.

## Operational QA detail stays in task skills

Preserve these requirements from the user's example when defining a task QA procedure:
1. Start the app with its verified command and open it in a real browser.
2. Capture every changed screen.
3. Exercise the actual end-to-end flow with zero mocks, including actual LLM calls.
4. Check navigation, displayed data, errors and the agreed UI language.
5. Compare with the application's own approved brand/design reference when one exists; do not invent a brand, font or design document.
6. Report steps and screenshots, fix regressions, then commit after relevant verification.

These steps guide authoring a separate QA skill; only their standing quality gate belongs in AGENTS.md.

## QA contract from the example

The source example required startup, Playwright CLI, screenshots of affected screens, real end-to-end flows, errors/text checks, approved visual comparison, and evidence before completion/commit. Preserve this intent without putting a browser runbook into AGENTS.md.

A task QA skill should use verified commands, real browser-facing boundaries and only approved design/language expectations. Unit/integration mocks may be suitable; judge whether an LLM mock contributes meaningful coverage. Follow [endpoint capture policy](endpoint-mocks.md) before creating any endpoint fixture. E2E and Manual QA use the fully working app and zero mocks anywhere: no response interception, provider stubs, fake services or simulated model completions. Missing browser access or a required real-stack dependency is blocked, not passing. Do not install, deploy or contact external services merely to author guidance.

This is authoring guidance, not a replacement for an installed browser/testing skill. Do not list nonexistent skill names in generated instructions.

## Review

A documentation, backend, UI or review agent must receive useful shared guidance without inheriting one task's runbook. Nested guidance binds the whole subtree, not a feature, browser test or deployment. Keep quality gates and portability.
