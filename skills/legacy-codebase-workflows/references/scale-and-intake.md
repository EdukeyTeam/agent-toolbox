# Scale context to the task

Choose from the question, relevant source scope and measured costs. Git history, binaries, generated output and vendored dependencies differ from current maintained source. Repository bytes alone are not a routing rule. Keep the simple workflow for simple tasks in any repository. The bundled tools have not been validated on a hundreds-of-megabytes production corpus.

## Choose a starting point

| Task scope | Start with | Escalate only for an observed gap |
| --- | --- | --- |
| Known path or symbol, in any repository | Direct search, original definition and callers | Scoped map when ownership is unclear |
| Unfamiliar small repository or subsystem | Native overview and relevant originals | Complete captured-definition index or focused full-source pack |
| Several modules or applications | Lazy catalog, one task map over active subtrees and required core paths | Separate searchable module indexes, verified API cards |
| Repeated difficult questions in a large/huge repository | The same scoped navigation; record which question types fail | Evaluate retrieval for prose discovery, compiler references for impact, or verified wiring notes for runtime questions |

Classify the question: exact lookup, who-uses/change impact, prose discovery, runtime/configuration wiring, or edit. That selects the next tool. Large size alone does not require retrieval or a graph database. Partition analysis along real source/build/ownership boundaries; physically refactoring the application's modules is a separately authorized task.

## Minimal intake

Infer facts from the request, repository instructions and descriptors first. Use the [intake template](../templates/repository-intake.md) only for missing decisions; ask at most three relevant questions together. A known-file edit needs no questionnaire, saved map or instruction-file update.

Establish the active application/modules, relevant shared core, question and permitted processing/writes. For compiler navigation, obtain real source roots, dependencies and javac/classpath or IDE evidence. Mapping and lexical search do not require a working application build. Keep unknown framework APIs and relationships explicitly unresolved.

## Lazy catalog and task maps

Start catalog rows with module path, application and build-descriptor facts. Add purpose, entry points, required core paths and evidence only for modules the task touches. Do not characterize every module before starting. A root inventory discovers candidates, not dependency edges. Its stdout shows at most 20 module groups: inspect inventory.json rather than treating that summary as exhaustive. If inventory reports max_files truncation, use build descriptors and per-application/subtree inventories; never infer absence from the partial result.

The mapper's repeatable --subtree filter applies before its max_files candidate count. Generate one task map over active modules and the required core slice, rather than loading a default-size map for every module:

```bash
/verified/legacy-repo-map /repo --subtree core/relevant --subtree modules/active-a --subtree modules/active-b --focus-symbol ExampleService --output-dir /external/task-map --budget 16384
```

Choose actual paths from evidence; the example does not assert that every repository has these directories. Keep generation caches/staging external. Export into docs/repo-maps when repository writes are within the task, or use the user's external destination for read-only work. Add an AGENTS.md pointer when those instruction edits are authorized. See [repository maps](repo-map.md) for named export commands and limits.

Optionally save one --all-definitions index per reusable module with a sufficient explicit budget. Search these indexes for a symbol-to-original-path/line lookup; do not load every full index into context. All-definitions means all captured eligible tags, with query/admission limits still visible. Reserve context for the task, conversation, tools and original bodies before increasing the default 16,384 estimated-token map budget.

Store scope, examined revision and working-copy fingerprint with each artifact. Changed relevant paths/declarations require a refresh; a fingerprint/revision mismatch means a snapshot needs revalidation, not that a manually maintained catalog can propagate dependency invalidation. Similar modules may have identical symbol names but different persistence, registration or behavior: select the intended module before ranking and inspect the real variations. Verified core API cards can record purpose, exact signature, lifecycle, configuration, a caller and current original-source citations; use check_citations.py for mechanical citation validation.

## Maps, packs and retrieval serve different questions

Maps expose declarations and ownership. Scoped full-source [Repomix packs](repomix.md) collect definitions, callers and wiring for an investigation/edit. Compressed packs can remove behavior and even multiline parameters; fetch full source for claims or changes. [Local retrieval](private-retrieval.md) can be evaluated for repeated source/documentation questions. Every result is a pointer to current originals, not proof of the answer.

Before a pilot, compare direct search/read, search over saved complete indexes, and a task map plus scoped full-source pack. For a prose-discovery failure, compare lexical-only SQLite FTS5 before adding models. Exact identifier tokenization does not automatically split camelCase; include both identifier and prose queries in evaluation. API cards/model changes need independent evidence, not just a better storage engine.

The bundled Context7-compatible backend indexes one root per database, with optional docs root and exact-path exclusions. It has no multi-subtree include list, corpus router, module payload filters or cross-corpus fusion. A runnable first pilot indexes one representative module/root; inspect core/consumer sources directly or evaluate separate core/consumer databases explicitly. Combining those roots into one routed corpus needs additional implementation. Do not silently stage copied client source or remove limits to make a pilot fit.

Limits are 256,000 bytes per eligible file, 10,000 selected files, 30,000 chunks and 100,000 discovery candidates per root; excluded candidates still count. Each query enumerates/hashes the included corpus and checks revision. Source edits/deletions or branch/commit changes require reindexing. Semantic queries also start a fresh inference process. This favors investigation/read-mostly scopes over an unmodified edit-loop index. Exact vector scans and source freshness costs must be measured separately.

Use a held-out set derived from real tickets/changes with independently verified expected source ranges. A broad adoption pilot should aim for at least 40 questions; a smaller trial establishes workflow compatibility, not reliable quality. Include exact lookups, prose, cross-module/wiring questions, look-alike modules as hard negatives, absent APIs, edits and deletions. Keep tuning examples separate. Score module-correct range recall@5/@10, evidence sufficiency and time-to-evidence against the cheap baselines; report sample count, p50/p95, indexing/update time, RAM/disk and stale-source behavior.

Agree an adoption threshold and cost ceiling before tuning. Retain a new tool only when held-out evidence improves the failing question type without losing source validity and acceptable update/operational cost. Stop or return to maps/search when there is no improvement, candidates miss the answer, stale results are admitted, or scope/setup costs exceed the task's value.

## Escalate the measured bottleneck

First inspect representation quality, missing candidates, scope and near-duplicate pollution; next freshness and inference startup; only then vector storage/search. Existing jFTP quality observations are development comparisons, not held-out validation. See the source [storage ADR](../../../docs/ADR/000-local-code-retrieval-storage.md) for measured database tradeoffs. Its storage review triggers include an index above 100,000 chunks or measured vector-step p95 above 200 ms; these do not authorize silently raising the backend's current caps.

| Observed gap | Evaluate | Boundary |
| --- | --- | --- |
| Exact symbol found, ownership unknown | Catalog plus complete-index lookup | No database needed |
| Repeated prose questions fail despite useful candidates | Verified API cards, suitable model/reranker, existing SQLite | Changing storage does not repair representation |
| Exact Java references/change impact | JDT LS or SCIP-Java for core plus one module | First obtain classpath/javac inputs and resolve one real slice; occurrences are not automatically call edges |
| Selective shared indexes/concurrent users or measured ANN need | Self-hosted Qdrant pilot | Requires ingestion, module/application filters, update consistency, access policy, backups and recall evaluation |
| Data/control-flow questions | Scoped Joern evaluation | Requires usable frontend evidence and unresolved-edge reporting |
| Reflection/string/custom lifecycle wiring | Verified registration/configuration notes | No tool here automatically resolves it |

Primary-source capabilities checked 2026-10-08: Qdrant's [Query API](https://qdrant.tech/documentation/search/hybrid-queries/) provides dense/sparse prefetch and fusion; [payload indexes](https://qdrant.tech/documentation/manage-data/indexing/) support filtering. Chroma's [advanced Search API](https://docs.trychroma.com/cloud/search-api/overview) is Cloud-only at this check; local contains/regex filters are not a ranked lexical leg. Chroma OSS dense ANN is an optional future comparison, not a default migration; the ADR rejects its cost at current limits. sqlite-vec's [scalar-distance KNN](https://alexgarcia.xyz/sqlite-vec/features/knn.html) is exact scanning. Keep chunks/questions/models fixed when comparing storage; raw float32 vector bytes are chunks × dimensions × 4, before text, metadata and index overhead.

[JDT LS](https://github.com/eclipse-jdtls/eclipse.jdt.ls) needs Java 21 to run at this check and supports Java 17 project analysis. [SCIP-Java's manual javac-plugin route](https://github.com/scip-code/scip-java/blob/main/docs/manual-configuration.md) can work with a custom build when real compiler arguments are available; Maven/Gradle integration is not assumed. [Joern](https://docs.joern.io/frontends/java/) is another evaluated frontend, not an already integrated feature. A program reference/call graph and an ANN HNSW graph describe different relationships. Choose any separate graph store only after useful edges and queries exist.

Finish with the answered question or verified change, refreshed relevant artifacts when authorized, evidence and unknowns. Expand tooling for a demonstrated gap, while keeping simple tasks simple.
