# Mandatory plan consistency review

The main **strong** model reviews the actual saved plan. Models in the execution class must not author, audit, comment on or approve plans. A requested/permitted strong expert may give another opinion; the main agent resolves findings. Mechanical checks and prescribed test outcomes are evidence, not decision authority.

## Sources and revision evidence

Read actual applicable instructions, PRD, ADRs, selected design guidance and relevant existing code/tooling. Verify filenames and section anchors. Agent summaries do not replace sources.

Identify the reviewed plan and inputs by commit/path or content hash. Verify each cited commit actually represents the file: a parent HEAD does not identify ignored/untracked fixtures. Recheck after changes; keep this evidence in the concise companion review rather than repeating it across task rows.

## Checks

| Dimension | Required judgment |
|---|---|
| Model authority | Actual model matches explicitly approved planning routing; main strong agent authored/decomposed/reviewed the plan; small workers are reserved for future bounded execution. No role label or cheap default transfers planning/acceptance authority. |
| Product / architecture | Every in-scope criterion has a true implementation and verification mapping in the matrix; chosen stack, boundaries and PoC exclusions follow source sections. No hidden product/architecture choices are left to workers. |
| Source ownership / size | Product prose, schemas, endpoint catalogues, setup procedures and detailed test cases stay in canonical documents. No copy-and-paste specifications, repetitive cards, complete future briefs or overflow appendices. Typical PoC target: about 2,000 words, with 100-200 lines as a wrapping-dependent heuristic; justify either overage after compression without losing coverage. |
| Instructions / design | Actual global/repo/nested workflow, commits, data, TDD, manual QA, selected assets and accessibility guidance apply at the correct paths. Missing assets and conflicting instructions are explicit. |
| Dependencies / contracts | One matrix has unique IDs, valid prerequisites, no cycles and real joins. Contracts/fixtures/screens/commands exist before consumers. Check both directions, not only phase order. |
| Ownership / concurrency | Shared files, generated outputs, ports, servers and databases have an owner/serialization. A worker cannot rely on another worker's uncommitted state or an unaccepted commit; dependent dispatch needs a strong-orchestrator accepted receipt. |
| Brief feasibility | The strong orchestrator can later compile all task-relevant excerpts, actual predecessor interfaces, choices and exact steps into one bounded brief. Workers need neither the whole plan nor broad PRD/ADR reading. |
| Verification | Meaningful feature Red, characterization, QA and documentation checks are distinguished. Startup/manual QA and automated tests are separate where required; unavailable tools become earlier preflight gates, not false passes. |
| Readability | The matrix alone carries the full task graph. No second giant Mermaid/UML graph; optional phase overview has at most eight nodes and is labelled derived/non-authoritative. |
| Human gate / automation | Plan stays draft and the planning turn ends after review. Missing consequential intake choices block the verdict; future preflights have resolved owners/policy. Later explicit human approval is recorded against a revision, and material changes require re-approval. Positive findings, broad build requests and active goals cannot self-approve a revision or trigger implementation on a resumed turn. |

These checks do not add product requirements. Use source IDs and anchors in mappings, not duplicate requirement paragraphs. Link existence is insufficient: check that labels reach the intended artifact and criteria map to the actual flow.

## Findings and fixes

For each substantive finding record its impact, source/plan references, consequence, concrete fix or human decision, and affected recheck. Correct plan-local mistakes and connected matrix rows. Do not rewrite PRD/ADR/AGENTS to hide a conflict. Consequential source contradictions remain blocked for the appropriate human decision.

Check local links, unique task IDs, prerequisite references, graph acyclicity and per-criterion coverage mechanically where tools exist; report manual checks honestly. Do not require a redundant visual graph to validate dependencies. Runtime or CLI verification not performed must not be claimed.

## Concise companion review

Record only:

1. Exact plan and source/instruction revisions reviewed.
2. Performed checks and substantive findings/fixes, distinguishing scripts from strong-model judgment; one coverage summary: total / mapped / excluded / gaps, with source-linked exclusions.
3. Missing decisions, limitations and unresolved blockers.
4. Verdict: `review passed - awaiting human review` or `blocked - human decision required`.
5. Confirmation that implementation has not started and the turn stops.

Name any actual expert reviewer/model and its limits; do not claim an independent model family without one. Link evidence rather than copying logs or the plan. Review is never human execution approval.
