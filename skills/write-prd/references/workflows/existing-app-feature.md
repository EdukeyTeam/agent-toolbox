# Workflow: a feature or module in an existing application

Use when an application already exists and the PRD describes a new feature, or a change to a distinct part of it.

- **Inputs:** the request, plus the application itself: its repository when you can read it, the running application, and existing requirements documents.
- **Explore first (Step 2):** find how the affected part works today: the screens, flows, data and rules the feature touches. Verify the user's assumptions against what is really there and point out any that do not hold.
- **Scope the document to the feature.** Describe the current behavior only as far as the feature depends on it, then the change. A distinct functional area (for example billing or reporting) gets its own document, such as `docs/prd/<feature>.md`, rather than a growing single PRD: save it there instead of the default `docs/PRD.md` in Step 5, and never overwrite an existing main PRD. Link the new document from the main PRD if one exists.
- **Questions:** how the feature fits existing flows and permissions, what happens to existing data, and which existing behavior must not change. Put "must not change" items into the acceptance criteria.
