# Desktop workflow

Use for native desktop applications, independent of implementation language/framework. Read [scope and adaptation](scope-and-adaptation.md) when resolving fields or nested scope.

## Copy and adapt

1. Copy `assets/desktop-AGENTS.md` exactly with the helper in --candidate mode for both new and existing guidance. Adapt and validate the candidate before publishing active AGENTS.md.
2. Fill purpose, agreed chat/documentation languages and localization policy. Describe the actual purpose, audience and client when known. Do not assume a language, framework, application, OS or home path.
3. Include only folder/repository-wide internal constraints, nonstandard resources and state/compatibility invariants. Keep versions, package tours, protocol migrations and bootstrap detail in documentation/skills.
4. Use one existing documentation entry point. Remove optional stack/layout blocks that merely restate obvious metadata.
5. Preserve shared TDD/commit gates and all seven Manual QA steps. Fill `{{DESKTOP_QA_METHOD}}` with available native computer-use tooling or established human verification. Playwright can cover an embedded web surface, not prove native-window behavior. Resolve `{{SCREENSHOTS_PATH}}` to an agreed project-relative evidence folder following the adaptation guide.
6. Keep the Manual QA procedure and scoped verification as standing gates in AGENTS.md. Launch commands, fixture setup, platform integrations and particular action sequences belong in task skills.
7. Apply root/nested admission review and remove unused blocks/placeholders.

## QA contract from the desktop adaptation

The template's seven steps define required QA for every runtime change: verify startup separately from builds/tests with isolated synthetic state; exercise success, cancellation and errors; verify actual outputs and persistence; interact with real windows and check responsiveness/focus/navigation; launch packaged builds outside the IDE for packaging changes; capture changed screens/states and inspect logs; check agreed UI language and visual conventions; report steps, environment, evidence and exactly what remains unverified. Preserve this procedure at root, rather than relocating it into a separate skill. Documentation-only tasks use scoped content/link checks.

Keep the shared gate: automated/headless tests alone do not prove GUI behavior. E2E and Manual QA require the fully working application with zero mocks, including real backing services and real LLM connections. Preserve the endpoint/database mock block for unit/integration: a fresh authorized local/test query and verbatim full capture before each creation/refresh, capture-derived mocks, separate secret-free provenance, no reuse of historical fixtures instead of a fresh capture, and blocked creation without access. Keep its outdated-documentation rationale; follow [endpoint capture policy](endpoint-mocks.md). Missing desktop access/tooling leaves required QA and the runtime task incomplete; obtain appropriate human verification before claiming completion. Do not invent installed tools, install software, launch the app or inspect real user state merely to write guidance.

## Review

Guidance must serve documentation, build, implementation and review agents. Nested content must be enduring folder-wide rules, not one platform's setup or one connection test. Do not promote a language, OS, install or old defect from the example into a new requirement.
