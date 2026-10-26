---
name: write-implementation-plan
description: Use when asked to write or revise an implementation plan from PRD, ADRs and workspace instructions. The main strong model authors and reviews a concise plan, ending at a human-review stop before implementation.
---

# Write an implementation plan

The plan is a coordination document for the **main orchestrator**, not a specification for implementation workers. The orchestrator reads the plan and canonical sources, makes decisions and later compiles complete worker briefs. A passed consistency review is not human approval to execute.

## 1. Keep planning with the strong model

The main agent creates the whole plan and performs its consistency review. Do not delegate task decomposition, plan fragments, architectural choices, plan audits, review comments or acceptance judgments to small models. Small execution models may write code or run prescribed tests from complete briefs after human approval. A specialist role name does not change a model's capability or authority.

The planning class consists of models explicitly designated for planning by the human or applicable workspace/harness routing (for example Sol or Opus). The execution class contains bounded workers (for example Luna or Haiku). Verify the actual model identifier against that approved routing; do not self-classify an unlisted model as strong. If planning authority is unspecified, ask the human to confirm this model for planning or hand off to a designated one before drafting or judging. Do not downgrade decisions to save cost. Routine planning needs no subagents. A separately requested expert opinion may use an explicitly permitted strong reviewer; the main agent remains accountable. Do not launch plan-writing workers or behavioral trials by default.

Read applicable global/workspace, repository and nested instructions, then the actual PRD, ADRs, selected design guidance and current build/test documentation. Resolve unambiguous filename mistakes; report missing or conflicting sources. Use [skill-appropriate review checks](references/review-checklist.md) for evidence, not an agent summary as a replacement source.

State allowed writes: normally the plan and its review. Role definitions require a human request. Do not scaffold applications, install application dependencies, start services or dispatch implementation workers during planning. Version/help inspection and read-only source research are allowed. Respect commit/publication rules and preserve other writers' files and branches; other sessions, including the parent of a forked session, may still be writing.

Inspect visible persistent goals, loops, schedules, hooks and auto-continue too. An active implementation goal can trigger another turn after a final response. Do not create a broad execution goal for planning or treat automatic continuation as approval. Preserve the review gate on resumed turns; report conflicting automation without silently changing or pausing another goal.

Where supported, constrain source access to read-only and writes to the exact document paths, or save a permitted reviewer's returned Markdown yourself. Written instructions are not a technical sandbox guarantee; disclose actual controls.

## 2. Ask focused intake questions

Reuse explicit answers already supplied. Ask in the user's language, without an arbitrary question minimum:

- What consequential information is missing from the sources for scope, architecture, sequencing, verification or authority? Cite the gap and its consequence. If none is missing, say so.
- For **later execution**, use only named predefined roles, ad hoc specialists, or a hybrid? Obtain names and permission to create missing definitions; verify role availability in the active harness before dispatch.
- Which external CLI workers are permitted for later execution: Codex, Claude Code, OpenCode, Antigravity, another named runner, or none? Permission for one does not approve another or authorize planning delegation.
- What execution-model, provider, cost, data or concurrency constraints are missing? A cheap default applies only to bounded execution; planning and acceptance stay with the strong orchestrator.

Choose minor technical defaults compatible with existing decisions and record them for review; do not escalate CLI flag spelling as a product decision. Required unanswered questions remain unresolved, never approved by silence. Continue independent source inventory while waiting. An unanswered choice affecting decomposition, source decisions, ownership, model authority or permissions blocks the review; never pass rows with unspecified owners/models or fill them from a cheap default. An explicit human delegation of an execution choice (role, runner, model, cost or concurrency) to the strong orchestrator within stated bounds counts as resolved; record those bounds and the routing rule instead of an unspecified model. A bounded tool/version check may instead be an explicit future preflight only when the policy and responsible owner are already resolved.

## 3. Save a concise draft early

Use the requested path or repository convention; otherwise use `docs/plans/000-implementation-plan.md`. Inspect an existing destination: update only the requested plan, preserve another plan or active writer, and choose another path or ask if ownership is unclear. Create the permitted parent directory and save an early draft with `approval: draft`, source links, unresolved decisions and phase outline. Put a directive for any reader at the top: **Do not execute: draft awaiting human review; execution requires explicit human instruction naming this reviewed revision.** Provide its clickable link before detailed work. Temporary fragments are not the deliverable.

Read [the plan and brief contract](references/plan-and-brief.md). For a typical PoC aim for **at most about 2,000 words** including the matrix; **100-200 lines** is a secondary readability heuristic, dependent on wrapping. Above 250 lines or the word target, compress repetition before handoff. Justify a necessary overage in the review for either metric; never drop criterion IDs, prerequisites, ownership or verification to meet a size target, or hide overflow in companion plan files.

PRD owns product behavior; ADRs own architectural decisions; design guidance owns visual rules; applicable agent instructions own workflow. The plan owns sequencing and coordination. Link exact sections/criterion IDs instead of copying requirements, schemas, endpoint lists, DTOs, test catalogues or setup instructions. Put unresolved source changes back with their authoritative document and owner.

## 4. Plan small tasks in one matrix

Name phases with entry/exit gates, then keep **one authoritative task/dependency matrix**. Each row identifies task/outcome, source references, future specialist/model, direct prerequisites, bounded ownership/shared hotspots, and the task-specific verification/commit handoff. Define common TDD, manual QA and commit rules once by reference. Add a short task note only for an exception the matrix and sources cannot express; do not repeat every row as a long task card.

Name one repository-local, Git-ignored QA evidence directory and its setup owner in the plan; put exact per-task screenshot paths and retention rules in briefs. Follow [QA screenshot storage](references/plan-and-brief.md#qa-screenshot-storage-and-retention); planning itself does not create application artifacts.

Check dependencies in both directions, cycles, joins and shared files/ports/databases. A task cannot require a later screen, contract, fixture or command. Serialize conflicting work and distinguish parallel preparation from parallel code changes. Keep PoC exclusions and avoid artificial process tasks.

Do not generate a second full dependency graph or giant Mermaid/UML diagram. The matrix is readable by the orchestrator and carries the complete dependencies. If a visual helps a human, use only a phase overview of at most eight nodes; label it non-authoritative and derive it from the matrix. No per-task edge duplication.

## 5. Plan brief compilation, not all future briefs

Record only the context recipe needed at execution: exact source sections, predecessor outputs and verification interface. Do not put full worker prompts or all future implementation steps into the plan.

After the human authorizes execution, the strong orchestrator reads the relevant PRD/ADR/design/instruction sections and committed predecessor code, resolves decisions, and writes a self-contained Markdown brief for one task. Give the worker its brief path and instruction to execute it; the brief contains required source excerpts, exact contracts, files, ordered steps, fixtures, expected behavior and checks. The worker should not read the whole plan or documentation set or rediscover architecture. It must report contradictions rather than guess; the orchestrator resolves them.

Compile and verify each brief just before dispatch. Do not freeze nonexistent symbols or commands in advance. See [the execution brief template](references/plan-and-brief.md#just-in-time-execution-brief). Keep role definitions short; execution-model roles must not grant planning, review or acceptance authority.

Execution-worker invocation is decided at dispatch under human-approved permissions and limited to the brief's allowed files; the review-only CLI examples do not configure implementation workers. Follow local runner, monitoring and cleanup requirements.

## 6. Review the saved plan and stop

The main strong model performs [the mandatory consistency review](references/review-checklist.md) against actual PRD, ADRs, design and applicable instructions. Fix plan-local defects and recheck affected dependencies/coverage. Do not rewrite requirements to hide conflicts. Leave consequential source decisions blocked for the human.

Save a concise companion review, normally `<plan-stem>.review.md`, identifying the exact plan/source revisions, checks, findings/fixes, limits and remaining decisions. This is review evidence, not another task tracker. Use a separate strong expert only when requested/permitted, never a small-model audit; consult only that runner in [read-only review CLI examples](references/headless-cli.md). Mechanical link/graph checks are helpers, not judgment or approval.

Deliver plan/review links, verdict and unresolved decisions. State **awaiting human review; implementation has not started**, in the saved plan and final response. Identify any observed active automation that could resume this planning task. Then **end the turn**, even if review passed. Do not dispatch the first task, create application code or continue automatically.

Only a later explicit human instruction to execute the identified reviewed plan permits execution. Accepted PRD/ADRs, worker/budget permission, an active broad goal or a positive reviewer verdict do not replace that gate. In that later workflow, record the human decision (who, when, revision/hash) under workspace policy and update the draft directive/status accordingly; recording explicit human approval is not granting it yourself.

Material changes include adding/removing a task or changing scope, dependencies, ownership, a source decision, a matrix verification/commit boundary, a phase gate, or the approved model/runner/cost/data boundary. Return the affected plan to draft, review it and obtain human re-approval before affected dispatch. Brief details within approved contracts and administrative approval records are not material changes; record them in existing handoff evidence and reuse unchanged human decisions.
