# Workflow: documenting an existing application as it is

Use before modernizing, migrating or taking over an application with little or no documentation: the goal is to describe what it does today, not to design something new.

- **Inputs:** the source code, the running application, or both. This works for web, desktop and mobile applications; without the running application, behavior comes from the code alone and is less certain.
- **Explore (Step 2):** map the main screens or entry points, the flows, the business rules and the data the application keeps. For a large or unfamiliar codebase, use a repository map or a dedicated legacy-code workflow first, then read only the parts that matter.
- **Separate evidence from assumptions.** For every requirement, note where it comes from: a code path, an observed screen, a document. Mark behavior you inferred but did not confirm as an open question, and ask the user or a domain expert rather than guessing.
- **Describe, do not improve.** Record current behavior, including odd behavior that users may rely on. Improvement ideas go to Further Notes, not into the requirements.
- **Questions:** which parts are actually used, which are dead, and which behavior is known to be wrong today.
