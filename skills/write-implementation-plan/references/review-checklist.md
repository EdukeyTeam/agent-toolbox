# Mandatory plan consistency review

Review the saved plan before delivering it for human review. The review verdict is separate from human execution approval. A completed review still ends this skill's turn.

## Evidence and sources

Use the actual applicable instructions, PRD, ADRs, selected design references and current source/tooling baseline. Verify exact filenames and section anchors. An agent summary is a navigation aid, not a replacement for the underlying source.

Record the plan revision and source revisions reviewed. For an uncommitted document use its content hash; for committed inputs record the commit and relevant paths. Verify that each input is actually tracked and represented by the cited commit. A parent repository HEAD does not identify ignored or untracked fixtures; record their content hashes instead. Recheck if either changes during review.

## Review dimensions

| Dimension | Questions that must be answered |
|---|---|
| Product coverage | Does every in-scope AC have implementation and verification ownership? Are manual and automated entry paths, failure recovery, persistence and exclusions covered where required? |
| Architecture | Are chosen libraries, versions, boundaries, data models, API behavior and deployment constraints followed? Does the plan accidentally introduce an alternative stack or duplicate business rules? |
| Instructions | Were global/workspace/repo/nested instructions considered for the affected paths? Do TDD, manual QA, evidence, data, commits and delegation rules agree? Are conflicting instructions surfaced with their scope and authority? |
| Dependencies | Does every prerequisite exist? Is the graph acyclic? Do cards, matrix, diagrams and phase gates agree? Can a task reach its claimed result before its successors exist? |
| Contracts | Which task freezes an API/schema/symbol? Does its consumer receive the actual committed interface? Are errors, revisions, retries and unknown values unambiguous where the product needs them? |
| Ownership | Does each file/hotspot have an owner? Are integration surfaces and shared config serialized? Are concurrent verification, servers, fixtures and databases isolated or gated? |
| Task size/context | Is each task bounded enough for its chosen model? Can the brief compiler supply all required details without pasting the whole application? Are decisions assigned to the orchestrator rather than left to workers? |
| Validation feasibility | Do tests assert behavior and meaningful boundaries? Are Red, Green, regressions, build, startup and manual QA distinct? Are tools, scripts and fixtures available by the time each check runs? |
| Design | Do UI steps cite selected tokens/assets and required accessibility behavior? Are unknown or missing assets honestly handled? Are visual claims backed by planned real renders? |
| Authority | Does the plan stay draft and stop for human review? Could a worker, CLI default, broad original request or positive review accidentally start execution? Are commits and external actions separately scoped? |

These questions are checks, not a demand to add features. For example, no authentication requirement should appear merely because a checklist mentions data handling.

## Finding format and resolution

For a substantive issue record:

| Field | Content |
|---|---|
| ID / impact | Blocking conflict, execution blocker, coverage gap, or minor correction. |
| Evidence | Relevant source section/criterion and exact conflicting plan task/statement. |
| Consequence | What would fail, conflict or be left for the worker to guess. |
| Resolution | Concrete plan correction, or the precise source decision required from the human. |
| Recheck | Which dependency, ownership or coverage checks were repeated after correction. |

Correct plan-local mistakes within the authorized documentation scope. Recheck connected tasks, matrix rows and diagrams; a renamed task or split can invalidate many references. Do not change a PRD/ADR/AGENTS requirement just to make the plan appear consistent.

A consequential source contradiction, unsupported architecture choice or missing decision remains blocking until resolved by the appropriate authority. Explain the conflict and ask the focused question. An unknown command can be resolved by an earlier tooling-verification task only if no earlier task already needs it.

## Mechanical and human checks

Where available, check:

- Local links and exact heading anchors resolve; future files are clearly labelled as planned paths.
- Task IDs are unique and every dependency references an existing task.
- The full graph, including phase gates, is acyclic.
- Task cards, matrix, diagram and model/role assignments agree.
- All in-scope AC/TAC IDs from the actual source set have implementation and verification mappings.
- Leases do not authorize conflicting writers or hidden uncommitted dependencies.
- No review or worker path can self-approve or dispatch an implementation step.

A syntactic link checker cannot establish semantic coverage or the intended destination. A link labelled “handoff” must point to the actual output handoff, not an existing input brief with a similar name. Read the mappings: an import-failure criterion must map to the import flow, not an unrelated settings screen. Confirm that stated test outcomes would detect the failure they claim to protect against.

For a larger plan use a fresh permitted reviewer or separate pass. Give the reviewer the saved plan and scoped source documents, not the author's conclusions as its evidence. Record its actual mechanism/model and limits; do not claim a different model family unless one was used.

## Companion review output

Keep it concise and linked to the plan:

1. Reviewed plan path/revision and source/instruction paths/revisions.
2. Checks performed, distinguishing automated checks from manual reading.
3. Coverage/dependency/ownership result and substantive findings/fixes.
4. Unresolved questions, blockers and unavailable verification.
5. Verdict: `review passed — awaiting human review` or `blocked — human decision required`.
6. Explicit statement that implementation has not started and the agent has stopped.

Link supporting evidence instead of copying raw logs or the entire source documents. A verdict applies only to the reviewed plan and inputs; don't claim it covers later edits.
