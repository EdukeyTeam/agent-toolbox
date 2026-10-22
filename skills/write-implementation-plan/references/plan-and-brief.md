# Plan and execution-brief contract

Use this when drafting task structure. Adapt size to the project: a small PoC should not acquire production infrastructure or dozens of artificial steps. Keep source documents authoritative.

## Visible plan structure

Include the following information, grouped as appropriate:

| Part | Required content |
|---|---|
| Boundary | Objective, current baseline, included scope and exclusions; `approval: draft`; awaiting human review. |
| Sources | Canonical PRD/ADR/design/instruction paths and precise relevant section links; commit IDs or hashes for dirty/unversioned inputs. |
| Decisions | Confirmed named/ad hoc agent policy, permitted native/CLI runners, selected default model and exceptions, costs/data limits and who may commit. |
| Phases | Observable milestone, entry prerequisites, exit checks and join gates. |
| Task matrix | ID, owner role, model/runner, direct prerequisite IDs, owned paths, shared-file leases, preparation/implementation parallelism, expected commit. |
| Task cards | The bounded contract below, linked to source criteria and predecessor outputs. |
| Coverage | Every in-scope criterion mapped to implementation task(s), meaningful test/manual scenario and QA owner; IDs with short labels, not copied requirement paragraphs. |
| Completion | Build/tests/startup/manual QA evidence required for a working product, reproducible run instructions, cleanup and handoff. |
| Review | Link to the consistency review, unresolved decisions and the human-review stop. |

If the workspace already has a tracker, keep live ownership, receipts and progress there; the plan describes the work and its dependencies. Do not create a parallel backlog merely because this skill is used.

## Bounded task card

For each task provide:

1. **ID and outcome:** one demonstrable capability or coherent verification deliverable.
2. **Authority:** exact PRD criteria and ADR/design/instruction sections. Identify a discrepancy instead of adding a new requirement.
3. **Owner and routing:** named/ad hoc role, native/CLI mechanism, exact chosen model or the explicit preflight that resolves it, and rationale for an exception to the default.
4. **Dependencies:** direct predecessor IDs and their concrete outputs/contracts; distinguish contract readiness from phase gates.
5. **Ownership:** planned module/file scope, forbidden paths and shared hotspots. At dispatch, expand proposed patterns into actual allowed files. Name one owner for each migration and integration surface.
6. **Context recipe:** only the source sections, current symbols/DTOs, examples and fixtures the future brief must contain.
7. **Work sequence:** use the task-type rules below. For a feature/fix: inspect the baseline, write/run a behavior test, observe meaningful Red, implement the minimum, Green, refactor, run regressions, validate the actual flow and return evidence. For QA, refactors and documentation, specify their appropriate sequence without inventing feature Red steps. Include task-specific edge cases.
8. **Verification:** concrete input and expected output, failure/boundary cases, affected test layers, executable commands where known, manual API/browser/CLI steps, and required evidence.
9. **Commit and handoff:** one logical green commit after required checks; exact committing actor according to the workspace policy; contracts/results unblocking successors.

Do not disguise a whole subsystem as one small task. Split by observable behavior or contract boundary, then update dependencies and coverage together. Avoid splitting a tiny coherent change into empty process commits.

## Bootstrap and TDD

Installation, test discovery and a donor scaffold do not prove domain behavior. A bootstrap step demonstrates runnable tools, at least one discovered test, a controlled assertion failure and restoration, and actual startup when a runnable interface exists. Compilation errors, missing imports or a broken fixture are not a meaningful feature Red.

Separate these kinds of work:

- **Feature/fix:** test first, observe the intended behavioral failure, implement, rerun. A discovered bug needs a failing regression before the repair.
- **Behavior-preserving refactor:** establish a characterization baseline before changing production behavior; use controlled mutation where required by workspace instructions.
- **QA of delivered behavior:** verify outcomes; do not fabricate a post-implementation Red. Return defects to the implementation owner with a reproducer.
- **Documentation/configuration:** inspect relevant diffs, links and syntax; do not invent application runtime evidence.

For each runtime-changing step, plan validation through the interface actually available at that point. Before HTTP exists, validate a real CLI/storage lifecycle; after the API exists, start it and issue real requests; for UI work, operate the running browser flow. Automated E2E does not replace manual QA where instructions require both.

Name script activation steps. A future test/build command is a planned contract until the harness exists; later dispatch briefs must contain its verified invocation. Do not add passing placeholder scripts or make a task run commands introduced later.

## Dependency and concurrency rules

- List direct prerequisites, not only phase numbers. Every referenced ID must exist; check for cycles, missing joins and backward dependencies.
- Freeze common transport/schema contracts before consumers. Include a coordinated change path if a contract must change later.
- Give shared config, dependency installation, lockfiles, routes, composition roots and migration registration explicit exclusive leases.
- Disjoint filenames alone do not establish independence: tests, generated outputs, watched sources, ports and databases can conflict.
- A commit must be verifiable with its committed predecessors and own changes. Do not let another worker's dirty files supply a hidden dependency.
- In one shared checkout, serialize source promotion and verification when independent validation cannot be established. Other agents may prepare scoped research, briefs and test designs in parallel; label that accurately.
- Use isolated coding environments only when permitted by the workspace and human. Do not silently create worktrees, switch shared branches or discard changes to make scheduling convenient.
- A failed predecessor blocks affected dependents. Assign repair to its owner, add a regression first, rerun affected checks and refresh downstream briefs.

## Just-in-time execution brief

The plan contains a recipe, not a large copy of all future prompts. At future dispatch the orchestrator fills every field below; unresolved choices are a dispatch blocker.

```text
You are a delegate. Follow this bounded brief and applicable workspace rules.
The orchestrator owns decisions, coordination and task acceptance.
Do not change plan approval or exceed your file/permission scope.

Task ID / role / exact model and provider / runner:
Mode: implement | verify | prepare-only
Repository root / baseline commit / required predecessor receipts:
Goal and observable acceptance criteria:
Non-goals and forbidden actions:
Exact readable inputs and writable files / exclusive leases:
Task-relevant PRD, ADR, design and instruction excerpts:
Current contracts, symbols, sample payloads and error responses:
Ordered feature-specific work steps:
Red input, assertion and expected behavioral failure:
Green result and boundary/error cases:
Verified focused and regression commands / expected exit and test counts:
Separate startup and real manual validation steps:
Evidence paths and required screenshots/API/CLI results:
Committing actor and expected handoff (follow workspace policy):
Report path and required report contents:
Stop/report conditions for contradictions or unavailable prerequisites:
```

Tell workers they share the codebase and must preserve others' edits. Preserve stricter local delegation rules, including a required brief preamble, if present. A prepared brief grants no authority to start implementation before the human-review gate.

Verify paths, source revisions, predecessor contracts, permissions, tool versions and test commands immediately before dispatch. Create permitted output parent directories before assigning a writer; confirm the named role is active in the selected harness. Include the necessary documentation excerpts/API usage rather than asking a small model to rediscover architecture. Avoid filling the context with entire documents, unrelated schemas or stale transcripts.
