# Workflow: describing an application from the outside (black-box)

Use when there is no access to the source code and the application can only be observed through its interface: a web page, a mobile app or a desktop program. Testers are the usual users of this workflow; it also fits analysts, support teams and anyone evaluating a third-party system.

- **Inputs:** the running application, its public documentation, release notes, and existing test cases or bug reports. Never ask for the source code; the point is to work without it.
- **Explore through the interface (Step 2):** walk the main screens and flows the way a user would, using browser or device automation tools when the agent has them (for example a browser MCP server for web, a UI hierarchy dump for Android). Record what you see: screens, fields, buttons, messages, validation errors, and what changes after each action. Do not submit real data or change production state; use a demo or test environment.
- **Only observable behavior.** Every user story and acceptance criterion describes something a person can see or do in the interface. "The system stores the invoice" is not observable; "after saving, the invoice appears in the list with status Draft" is.
- **Mark the source of each requirement:** observed, documented (with a link) or assumed. Assumptions go to the open questions for the product owner or the development team.
- **Questions:** which flows matter most to the business, which environments and test data are available, and which behavior is already known to be broken.
- **Acceptance criteria are the test basis.** Write them precise enough that each one becomes one or more test cases with concrete inputs and expected results. Test cases themselves stay out of the PRD; after it is saved, offer to derive them from the acceptance criteria in a separate document instead of offering an ADR.
