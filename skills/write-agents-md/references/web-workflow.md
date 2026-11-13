# Web workflow

Use for browser applications. Read [scope and adaptation](scope-and-adaptation.md) when resolving fields or nested scope.

## Copy and adapt

1. Copy `assets/web-AGENTS.md` exactly with the helper in --candidate mode for both new and existing guidance. Adapt and validate the candidate before publishing active AGENTS.md.
2. Fill purpose, agreed chat/documentation languages and existing UI locale policy. Describe the actual project purpose, audience and client when known; do not invent a client or retain names from the example.
3. Include only non-obvious stack constraints and nonstandard layout consequences. Omit standard metadata and conventional source/test/assets maps.
4. Point to an existing documentation entry point; do not always load PRD/ADR/design files or create them just to match the sample.
5. Preserve the original seven TDD steps, all seven Manual QA steps and commit bullets. The template generalizes the fixed dev command and brand details; unit/integration endpoint/database mocks need fresh captured real responses, while E2E/manual QA allow none. It requires no LLM, framework, typography, palette or secret variable.
6. Resolve `{{WEB_QA_METHOD}}`: prefer the Playwright CLI and verify availability. Preserve an established project runner; change the default only to an agreed equivalent, never silently weaken QA. Resolve `{{SCREENSHOTS_PATH}}` to an agreed project-relative evidence folder following the adaptation guide. Missing access/tooling is blocked. Keep the Manual QA procedure and scoped verification as standing gates in AGENTS.md. Scenario steps and executable commands belong in task skills.
7. Apply root/nested admission review and remove unused blocks/placeholders.

## Standing Manual QA procedure

Preserve the template's seven steps in AGENTS.md for every runtime change:

1. Start the real app with its verified command and authorized configuration using isolated synthetic state; confirm startup separately from builds/tests.
2. Exercise complete success, cancellation and error paths; verify actual outputs, state and persistence rather than success messages.
3. Use a real browser with the verified QA method; check responsiveness, focus, keyboard navigation and page transitions.
4. For packaging changes, launch the packaged build outside the IDE and check resources/dependencies.
5. Capture each changed screen/state in the agreed folder and inspect browser/server/runtime logs.
6. Check agreed UI language/localization and approved references or existing visual conventions; do not invent a brand, font or design document.
7. Report steps, environment, screenshots and other evidence; fix failures before committing. State exactly what remains unverified when prerequisites are missing; required QA and the runtime task remain incomplete.

These are shared quality gates, not scenario-specific instructions. Keep actual launch commands, fixture setup, URLs and click sequences in task skills. Documentation-only work follows scoped content/link verification.

## QA contract from the example

A task QA skill should use verified commands, real browser-facing boundaries and only approved design/language expectations. Unit/integration mocks may be suitable; judge whether an LLM mock contributes meaningful coverage. Preserve the explicit endpoint/database mock block and its outdated-documentation rationale: fresh authorized local/test query and complete verbatim capture before each creation/refresh, capture-derived mocks, separate secret-free provenance, existing fixtures never replacing a fresh capture, and blocked creation without access. Follow [endpoint capture policy](endpoint-mocks.md). E2E and Manual QA use the fully working app and zero mocks anywhere: no response interception, provider stubs, fake services or simulated model completions. Missing browser access or a required real-stack dependency leaves required QA and the runtime task incomplete. Do not install, deploy or contact external services merely to author guidance.

This is authoring guidance, not a replacement for an installed browser/testing skill. Do not list nonexistent skill names in generated instructions.

## Review

A documentation, backend, UI or review agent must receive useful shared guidance without inheriting one task's runbook. Nested guidance binds the whole subtree, not a feature, browser test or deployment. Keep quality gates and portability.
