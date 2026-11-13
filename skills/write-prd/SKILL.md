---
name: write-prd
description: Use when the user wants to write a PRD, create a product requirements document, plan a new feature or product, or describe what an existing application does from its code or from its interface (black-box, e.g. as a basis for test cases).
---

This skill creates a Product Requirements Document (PRD). The PRD covers functional requirements, user flows, UX/UI, personas, and business constraints. Technical architecture, implementation decisions, and testing strategy are NOT part of PRD — they belong in a separate ADR document created in a later step.

Skip steps that are clearly not applicable, but do not skip the required question step. Do not repeat information the user has already provided.

---

## Process

### Step 1 — Gather initial description
If not already provided, ask the user for a detailed description of the product or feature: what problem it solves, who it's for, and any ideas they already have about how it should work.

### Step 2 — Choose the workflow and explore
Decide which case this is, read its reference, and explore what it says to explore before asking questions. Ask the user only if the case is unclear.

| Case | Read |
|---|---|
| A new product from an idea, brief or draft | [greenfield](references/workflows/greenfield.md) |
| A new feature or a change to one part of an existing application | [feature in an existing application](references/workflows/existing-app-feature.md) |
| Describing what an existing application does today, from its code and/or the running web, desktop or mobile app | [existing application as it is](references/workflows/existing-app-as-is.md) |
| Describing an application only from its interface, without the source code (usually testers) | [black-box](references/workflows/black-box.md) |

The rest of the process and the template are the same in every case. Verify the user's assumptions against what you find; do not skip exploration when there is something to explore.

In the as-is and black-box cases the document describes behavior that exists, so read the process and template that way: ask the Step 3 questions about how the application behaves today instead of what should be built, state in the Executive Summary that the document describes an existing application, use Out of Scope for the parts of the application the document does not cover, and describe the screens in the UI section as they are. Proposed changes go to Further Notes.

### Step 3 — Ask clarifying questions (REQUIRED — minimum 5)
Ask the user at least five focused clarifying questions before writing the PRD. Do not start writing until you have answers. If the brief already covers a listed topic, ask a deeper question about another decision instead of repeating it.

Cover at minimum:
- Who are the users? Any specific personas or edge cases?
- What happens after the main happy-path action? (e.g., after form submit, after AI decision)
- What are the explicit out-of-scope items for this PoC/MVP?
- What should happen in error and unclear/ambiguous cases?
- Are there any external constraints — legal, API limits, third-party rules, file formats — that need to be validated before writing?
- What does the UI/UX need to look like at a wireframe level?
- If AI/agents are involved: what should the agent do when it cannot make a clear decision? What is it NOT allowed to do?

Resolve decisions that affect the main flows before writing. Record any remaining assumptions or open questions in the PRD rather than inventing answers.

### Step 4 — Research external facts (if needed)
If the product involves external APIs, file format constraints, legal requirements, or third-party service limits, research them before writing. Do not put unverified numbers or constraints into the PRD.

### Step 5 — Write the PRD
Use the template below. Save the result as `docs/PRD.md`, unless the user specifies another path or the chosen workflow names one (a distinct feature in an existing application gets its own document).

### Step 6 — Stop, then ask about the ADR
Stop once the PRD is saved. Do not begin implementation, and do not write the ADR in the same run.

Ask the user whether they want to continue now with the `write-adr` skill to generate the ADR from this PRD. In the black-box case there is usually nothing to build, so offer instead to derive test cases from the acceptance criteria in a separate document. **The user decides** — do not start it unprompted, and do not assume the answer is yes.

---

## Rules

- **Language**: Always write the PRD in English, regardless of the language of the brief or conversation.
- **No marketing language**: No fluff, no "users will be delighted", no vague superlatives. Every sentence must be useful to a developer or agent implementing the product.
- **No technical implementation details**: Do not specify frameworks, libraries, file paths, SDK choices, database schemas, or code patterns. Those belong in the ADR (Architecture Decision Records). Mention functional behavior only.
- **No testing strategy**: Test cases and testing decisions belong in the ADR, not the PRD.
- **Measurable acceptance criteria**: Every AC must be verifiable. "Works correctly" is not an AC. "For a file larger than 10 MB, the product does not save the file and displays 'File exceeds the 10 MB limit'" is.
- **Out of Scope is mandatory**: Explicitly listing what is NOT in scope is as important as listing what is. It prevents scope creep during implementation.
- **Purpose**: The PRD will be used by a developer agent to create an ADR, and then to implement the application. Write for that audience.

---

## PRD Template

````markdown
# PRD — [Product / Feature Name]

---

## 1. Executive Summary

2-3 sentences. What is being built, for whom, and what problem it solves. This is a PoC/MVP/feature — state it.

---

## 2. Problem Statement

What problem exists today. Why it matters. What the user currently has to do instead. No solution here — only the problem.

---

## 3. Users / Personas

2-3 concrete personas. For each: who they are, what they want to do, what they expect from the outcome.

---

## 4. Main Flows

One subsection per scenario (happy path + key alternative paths). Step-by-step numbered list. Include what the system does at each step, not just what the user does.

---

## 5. User Stories

Format: "As [who], I want [what], so that [why]."

Minimum 4 user stories. Cover:
- Happy path (main scenario)
- Error cases (invalid input, service unavailable, ambiguous result)
- Session/state scenarios (if applicable)

---

## 6. Acceptance Criteria

Group by area (Form, AI Decision, Chat, Session, General, etc.).
Each criterion is prefixed AC-XX and is a single, testable, measurable statement.
Do not use subjective language.

---

## 7. Out of Scope

Explicit list of what is NOT being built. Use bold headers for each item.
Include: auth, integrations, admin UI, notifications, multilingual support, mobile apps, etc. — whatever does not apply.

---

## 8. Constraints

### Business
Policy, legal, or operational constraints the product must respect.

### Functional
Concrete limits: file size, accepted formats, number of items, supported browsers/devices, language, etc.

### External document / data references (if applicable)
If the product uses external files (policy docs, knowledge base, etc.), list them in a table: document name | file path | when it is used.

---

## 9. UI Description (wireframe level)

One subsection per screen. Describe:
- What the user sees (layout structure, key elements)
- What each interactive element does
- Error states and empty states
- Loading states
- Navigation between screens

No visual design details (colors, fonts, spacing). Functional and UX detail only.

---

## 10. User Flow Diagram

Mermaid flowchart covering all main flows from Section 4, including branching and error paths.

```mermaid
flowchart TD
    ...
```

---

## 11. Agent / System Behavior Specification (if applicable)

Include this section if the product involves an AI agent, LLM, or automated decision system.

- Role and purpose of the agent
- What the agent is allowed to do and what it is NOT allowed to do
- Decision categories and how each should be communicated
- Mandatory disclaimers or legal notices the agent must always include
- How the agent should handle off-topic questions or out-of-scope requests
- Language and tone requirements

---

## 12. Further Notes (optional)

Any open questions, assumptions made, or decisions deferred to a later stage.
````
