# Plan and execution-brief contract

## A compact plan for the orchestrator

The main strong model is the reader and author. It consults canonical sources itself; execution workers receive self-contained briefs later. Keep the plan focused on what it adds: ordering, ownership, dependencies and gates.

Use this minimal structure:

1. Objective, PoC boundary by source reference, baseline and `approval: draft` / awaiting human review, with the top-level do-not-execute directive. Cite excluded criterion IDs where supplied, or their canonical exclusion section; do not invent IDs.
2. Canonical source links and applicable instruction scope; revisions/hashes in a compact source list or companion review, not repeated per task.
3. Confirmed future role/runner/model policy and consequential unresolved decisions.
4. A few phases, each with an observable milestone and entry/exit gate.
5. One task matrix with the fields below; a brief exception note only where needed.
6. Review link and explicit human-review stop.

## The single task matrix

| Field | Keep in the plan |
|---|---|
| ID / outcome | One bounded capability or coherent verification result. |
| Source / coverage | Exact PRD criterion IDs and ADR/design/instruction anchors; no copied requirement prose. |
| Future owner / model | Specialist role and execution model/runner or recorded delegated routing rule; strong orchestrator owns decisions and acceptance. |
| Direct prerequisites | Task IDs and required handoff, including phase joins where relevant. |
| Scope / contention | Planned modules and exclusive shared-file/runtime ownership; expand into actual paths at dispatch. |
| Verification / commit | Short task-specific observable check or source pointer, commit boundary and successor handoff. |

Give every in-scope criterion an implementation and verification owner through these rows. Group IDs only when each has the same true coverage; inspect all source criteria individually during review. Do not add a second full coverage table, dependency list and nine-field task card for every row. Reference the row where the review needs a mapping.

Task size should fit a small model's bounded execution brief. Split a subsystem by observable behavior or contract boundary, not into empty process commits. Freeze transport/schema contracts before consumers. A step must verify with its own changes and accepted committed predecessors, not another worker's dirty files. A predecessor receipt identifies its commit SHA, verification evidence path and strong-orchestrator acceptance note in the existing handoff/tracker convention or a location named in the plan. A commit alone is not acceptance: no dependent dispatch before that accepted receipt exists.

Keep common workflow rules once, by links to applicable instructions. At most use a small, non-authoritative phase picture with eight or fewer nodes; never reproduce the per-task graph. Do not move duplicated specification into a collection of plan appendices to meet the line target.

## Verification by task type

The plan references the project's actual verification policy and records task-specific exceptions or prerequisites. Applicable instructions govern; the following are defaults when that policy is silent:

- Feature/fix: meaningful behavior test first, observed expected Red, minimal implementation, Green, refactor and affected regressions. A bug needs a reproducing regression.
- Behavior-preserving refactor: passing characterization baseline, with mutation proof where required.
- Bootstrap: prove tool/test discovery and a controlled assertion failure/restoration; prove startup once an interface exists. Missing imports or dependencies are not feature Red.
- QA: execute prescribed real flows and report evidence/defects; do not invent a post-implementation Red. Strong orchestrator interprets results and accepts the task.
- Documentation/configuration: relevant diff, links and syntax checks; no fabricated runtime claims.

For runtime changes, validate the interface that exists at that step: storage/CLI before HTTP, real requests after API, and running browser flow for UI. Automated E2E does not replace manual QA when instructions require both. Record exact executable commands in the just-in-time brief after they are established; never add passing placeholder scripts or require a command from a later task.

## QA screenshot storage and retention

Use the repository's existing QA artifact convention; otherwise choose `artifacts/qa/<task-id>/<run-id>/` under the repository root. Record that location once in the plan, assign its setup to the appropriate bootstrap/configuration owner, and include exact paths in future QA briefs. Each capture task must either perform and verify this setup before capture or depend on the task that did; no separate artificial setup-only task is required. Screenshots must remain easy for the human and coordinator to inspect after an agent or test server exits; do not use disposable system temp directories as the only copy.

Before the first capture, the implementation owner adds an anchored ignore entry to the `.gitignore` whose directory anchors the chosen artifact root and verifies a representative screenshot path with `git check-ignore -v`. Confirm captures are not tracked: ignore rules do not untrack an already committed file. Keep captures out of commits and pushes; never force-add them. This planning workflow only specifies that later setup, not permission to mutate the application now.

Use a retention directory independent of any test-runner output directory that gets cleared on reruns; explicitly save or copy captures into it. Do not run `git clean -x` / `git clean -X` or similar cleanup over retained evidence without human authorization. Name evidence by task, run, screen and state so later runs do not overwrite earlier captures. Link the actual local files from the QA report/handoff. Preserve them across test teardown, commits, pushes and agent cleanup until the human explicitly authorizes removal; "temporary artifact" means unversioned, not automatically deleted. Keep any cleanup request separate from ordinary process/server shutdown. Before an isolated worktree, container or sandbox copy disappears, the coordinator preserves its screenshots in the agreed ignored directory of the durable main checkout and updates report links. Verify ignore rules in the destination checkout before transfer, and never overwrite existing captures.

## Dependency and concurrency checks

Check all referenced IDs, acyclicity, joins and both producer/consumer readiness. Give manifests, lockfiles, routes, migrations, composition roots, servers, ports and databases explicit owners and serialization. Disjoint filenames alone do not prove independence.

In a shared checkout, serialize promotion and validation when isolated results cannot be established. Parallel preparation is not parallel implementation. Respect local permission for isolation; do not create worktrees or switch another task's branch implicitly. Failed predecessors block their dependents; the strong orchestrator assigns repair and refreshes downstream briefs. If repair changes the approved plan materially, re-review and human re-approval precede affected dispatch.

## Just-in-time execution brief

At future authorized dispatch the strong orchestrator fills the following template for one task, using its matrix row and current source inputs. This procedural detail belongs in the brief, not the plan. Supply all required excerpts and steps, never the entire application context.

```text
You are an execution delegate, not a planner or approver.
The strong orchestrator owns choices, coordination and acceptance.
Preserve others' edits. Report contradictions/missing inputs; do not guess.

Task ID / role / exact model, provider and runner:
Repository / verified baseline / required accepted predecessor receipts (commit, evidence, orchestrator acceptance):
Goal and task-relevant observable acceptance criteria:
Non-goals, forbidden actions and allowed writable files / exclusive leases:
Required PRD, ADR, design and instruction excerpts:
Current contracts, symbols, payloads, responses and synthetic fixtures:
Ordered implementation/test steps with choices already resolved:
Task-appropriate Red/Green or characterization/QA sequence:
Focused/regression commands and expected assertions/results/test counts:
Separate startup and real manual validation steps where applicable:
Evidence/report paths and required screenshots/API/CLI results:
Repository-local ignored screenshot directory / names / retention and local links:
Committing actor and handoff (follow workspace policy):
Stop/report conditions and owner of the required decision:
Worker findings are factual inputs, not plan review or approval:
```

Verify every path, output parent, active role, contract, tool version and command just before dispatch. Include only necessary inputs. Workers get the brief path and instruction to perform the bounded task; the main orchestrator retains the plan and reads PRD/ADRs. A brief never grants implementation authority before human approval.
