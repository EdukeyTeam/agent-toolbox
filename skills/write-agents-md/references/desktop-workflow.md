# Desktop workflow

Use for native desktop applications, independent of implementation language/framework. Read [scope and adaptation](scope-and-adaptation.md) when resolving fields or nested scope.

## Copy and adapt

1. Copy `assets/desktop-AGENTS.md` exactly with the helper; use candidate mode for existing guidance.
2. Fill purpose, agreed chat/documentation languages and localization policy. Describe the actual purpose, audience and client when known. Do not assume a language, framework, application, OS or home path.
3. Include only folder/repository-wide internal constraints, nonstandard resources and state/compatibility invariants. Keep versions, package tours, protocol migrations and bootstrap detail in documentation/skills.
4. Use one existing documentation entry point. Remove optional stack/layout blocks that merely restate obvious metadata.
5. Preserve shared TDD/commit gates. Fill `{{DESKTOP_QA_METHOD}}` with available computer-use tooling or Computer Commander/Command Commander MCP equivalent for native windows. Playwright can cover an embedded web surface, not prove native-window behavior.
6. Keep real-window QA/scoped verification as universal gates. Launch commands, fixture setup, platform integrations and particular action sequences belong in task skills.
7. Apply root/nested admission review and remove unused blocks/placeholders.

## QA contract from the desktop adaptation

The adaptation required startup with isolated state, real-window interaction, changed-screen capture, completion/cancellation/failure checks, application-log inspection and evidence. Native state/transfer changes need observable-result verification; package changes need launch from the package outside the IDE. These are task QA examples, not unconditional instructions for every root agent.

Keep the shared gate: automated/headless tests alone do not prove GUI behavior. E2E and Manual QA require the fully working application with zero mocks, including real backing services and real LLM connections. Integration may use meaningful mocks, including LLM fixtures, only after a fresh real query and verbatim full capture; follow [endpoint capture policy](endpoint-mocks.md). Missing desktop access/tooling is blocked; obtain appropriate human verification before claiming affected runtime work complete. Do not invent installed tools, install software, launch the app or inspect real user state merely to write guidance.

## Review

Guidance must serve documentation, build, implementation and review agents. Nested content must be enduring folder-wide rules, not one platform's setup or one connection test. Do not promote a language, OS, install or old defect from the example into a new requirement.
