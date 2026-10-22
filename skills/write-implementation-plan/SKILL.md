---
name: write-implementation-plan
description: Create and review phased implementation plans from product requirements, architecture decisions and workspace instructions, with task dependencies and agent delegation. Deliver a reviewable repository file and stop for human review before implementation.
---

# Write an implementation plan

Produce an implementation specification, not application code. A plan passing the agent's review is **not** human approval to execute it. End this workflow after delivering the plan and its review; implementation belongs to a subsequent, explicitly authorized execution request.

## 1. Establish the planning boundary

Read applicable global/workspace, repository and nested agent instructions. Locate the actual PRD, ADRs, design references and existing build/test documentation. Resolve a misspelled document reference to an unambiguous existing file; do not create a second source of truth. Report missing or conflicting sources.

State the deliverables and allowed mutations before working. Normally these are the plan and its review. Create or edit role definitions only when the human has requested that work. Do not scaffold the application, install application dependencies, change runtime configuration, launch implementation workers or start services to satisfy a planning request. Version/help inspection and read-only source research are planning work. Follow the workspace's commit/publication rules; planning permission does not authorize deployment, installation of this skill or changes to other sessions.

Where the harness supports it, restrict planning workers to read-only source access and the exact documentation output paths, or have them return Markdown for the orchestrator to save. A written stop rule is not a technical sandbox guarantee; disclose which controls are actually enforced.

Inspect the worktree before writing. Preserve existing changes and active writers. Do not switch another task's branch or create isolation implicitly. Follow the repository's rules for branches/worktrees and concurrent edits. A conversation fork is not proof that another writer stopped; verify ownership rather than controlling other sessions without authorization.

## 2. Ask the intake questions

Before detailed planning, ask concise questions in the user's language. Reuse answers explicitly supplied for this plan; do not repeat them. Do not impose an arbitrary minimum number of questions.

1. **Missing decisions:** identify only gaps that materially affect scope, sequencing, architecture, validation or authority. Cite the source ambiguity and its consequence. If documentation is sufficient, say so instead of inventing questions.
2. **Agent policy:** ask whether to use only named, predefined roles, allow task-specific ad hoc specialists, or combine both. For predefined roles obtain the names and whether missing definitions may be created. Verify the roles are available in the active harness: writing a definition does not prove it has been loaded. Do not silently replace a named role with a generic worker.
3. **External CLIs:** ask whether external CLI workers are permitted, and which ones: Codex, Claude Code, OpenCode, Antigravity, another named tool, or none. Native and external workers can be combined. Approval of one runner does not approve the others.
4. **Routing constraints:** obtain any missing model/provider, cost, data-handling or concurrency limits. Preserve the user's preferred default model; use stronger models only for a reason recorded in the task. If the user delegates model choice, choose explicitly within available, permitted options.

The orchestrator may choose minor implementation details compatible with the existing architecture, such as CLI flag spelling, and record them as proposed defaults for plan review. Do not turn every unspecified detail into a human blocker. Ask when the answer changes observable product behavior, an agreed architecture boundary, cost, permissions or execution feasibility.

Use a short combined intake when possible. An unanswered required question is not approval. Continue independent source inventory while waiting; do not decide dependent work by silence. Use one follow-up for a consequential ambiguity, not a large generic questionnaire.

## 3. Save a visible draft early

Choose the human's requested path or the repository's plan convention; otherwise propose `docs/plans/000-implementation-plan.md`. Inspect an existing destination first. Update it only when it is clearly the plan requested for this task; preserve another plan or active writer and choose a new path, or ask if ownership is unclear. Once the destination and planning boundary are settled, verify or create its permitted parent directory, write an initial draft there and provide its clickable path. Do not keep the only plan in a private harness transcript or temporary fragments until the end.

Start with `approval: draft`, the objective, canonical source links, the confirmed delegation policy, unresolved questions and an outline. Follow local metadata conventions without introducing a mandatory tracker or private service. If planning is interrupted, this visible draft must still explain what is missing. Temporary worker fragments are inputs to this file, not a substitute for it.

## 4. Build the phased task plan

Read [the plan and brief contract](references/plan-and-brief.md). Keep functional and architectural details in their existing documents; link precise sections instead of reproducing schemas, endpoint catalogues or every acceptance-criterion sentence.

Plan small, reviewable changes. Each task names prerequisites, a specialist and model, a bounded file scope, required context, observable outcomes, task-appropriate verification, manual validation for runtime-changing or runtime-verifying work, a commit boundary and the handoff consumed by its successors. Include backend, frontend, unit/component, integration, E2E and manual QA where the agreed product needs them. Preserve PoC exclusions instead of adding production systems.

The dependency/ownership matrix is authoritative: task cards and diagrams must agree with it. Include phase entry/exit gates, joins and realistic parallel opportunities. Shared manifests, lockfiles, routes, migrations, composition roots, integration pages, databases and test servers need explicit owners and serialization. Distinguish parallel preparation from parallel implementation. A task cannot depend on a screen, API, command or fixture that only a later task creates.

The orchestrator owns decisions, brief compilation, quality and coordination. Implementation workers receive exact choices and bounded steps; they must flag contradictions instead of guessing. Preparing the plan may be done by the orchestrator or scoped planning specialists according to the confirmed policy. Do not create an unnecessary team merely to produce a document.

## 5. Specify execution briefs without executing them

For each task, record a context recipe: source sections/criterion IDs, predecessor contracts and files, required fixtures and verification interface. At execution time the orchestrator compiles a self-contained brief in a temporary or ignored task directory. It embeds only the required excerpts, exact current symbols/payloads, decisions, allowed paths and test instructions. A worker should not have to read the whole PRD or make architectural choices.

Do not pre-generate every future brief against nonexistent code. Require committed predecessor outputs and validate paths, interfaces, source revisions and commands immediately before each future dispatch. Regenerate stale briefs. Keep permanent role definitions concise; task-specific procedures belong in briefs.

If CLI delegation is allowed, read only the selected runner sections in [headless CLI examples](references/headless-cli.md). Record runner, model/provider, cwd, input/output paths and permission scope. The examples explain future dispatch; they do not authorize launching an agent now. Follow any installed delegation workflow for execution, monitoring and cleanup, while keeping this skill usable without it.

## 6. Review the plan before handing it over

Perform the mandatory review in [the consistency checklist](references/review-checklist.md). Check the **actual saved plan** against PRD, ADRs, design guidance and all applicable agent instructions, not just against another planning summary. Check task dependencies in both directions and whether each planned task can really be executed with its inputs.

Record findings with source/plan references, impact and a concrete resolution. Correct plan-local defects, then recheck affected dependencies and coverage. Do not rewrite product requirements or architecture to conceal a conflict. Escalate source conflicts or missing human decisions and leave the review blocked where necessary.

Use a separate review pass or permitted reviewer for a complex plan. Disclose what was actually checked; do not describe a same-model check as a different-model-family review. CLI review still requires the chosen runner's authorization. Never let a reviewer launch implementation, change approval metadata, relax acceptance criteria or silently approve its own plan.

Write a concise companion review using the repository convention, otherwise `<plan-stem>.review.md`. It records reviewed source revisions, coverage/dependency/ownership checks, findings and fixes, remaining blockers, limitations and the exact plan revision reviewed. This is engineering evidence, not a second task-state tracker. If an executable validator is unavailable, report a manual check as manual; do not claim automatic verification.

## 7. Deliver and stop

Provide clickable links to the plan and review, a short explanation of the phase/delegation choices, review result and remaining decisions. Clearly state **awaiting human review; implementation has not started**. Show that status in the saved artifact as well.

Then end the turn. Do not launch the first implementation task, install dependencies, create application code or continue automatically because the review passed. A broad build request, an existing accepted PRD/ADR, permission to use workers, budget approval or positive reviewer feedback is not approval of this plan revision.

Only an explicit human request to execute an identified plan revision permits a later execution workflow. Material changes to scope, architecture, dependencies or ownership must be reviewed and reconciled with that authorization. Avoid asking again for unchanged decisions already approved. Do not mark the plan human-approved yourself, and do not let workers do so.
