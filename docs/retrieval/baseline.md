# Retrieval baseline: development questions

Measured 2026-10-17 against the four pinned snapshots in `evals/retrieval/corpora.json`. These are development-set source-range retrieval scores, not answer correctness or held-out validation. Each positive question has one or more independently checked defining source/doc ranges. The held-out directory was not accessed.

Lexical retrieval reached an expected range in the top ten for 24/47 positive questions overall: HTTPX 9/13, Vite 9/13, jFTP 1/13 and Django 5/8. HTTPX semantic and hybrid each reached 11/13. The extra lexical-symbol reranker hurt HTTPX and Vite but helped jFTP and Django. The optional semantic setup outcomes below must be read alongside these quality numbers.

## Setup and reproducibility

The harness is `skills/legacy-codebase-workflows/scripts/eval_retrieval.py`; usage and scoring details are in `evals/retrieval/README.md`. It is Python 3.12+ stdlib only. This run used Python 3.14.4, SQLite 3.46.1, Ubuntu 26.04 on WSL2, an AMD EPYC 7763 guest with seven visible logical CPUs and about 19 GiB RAM. The backend source was unchanged. `environment.json` records its checkout revision and file hashes.

The corpus root is `/home/lucas/DEV/Projects/agent-toolbox-eval/corpora/`; indexes are under `/home/lucas/DEV/Projects/agent-toolbox-eval/indexes/`. All four Git HEADs matched the requested commits and the corpora had clean working trees before evaluation. Source text and documentation were not rewritten or excluded to improve scores. The ground-truth provenance receipt records hashes for all 55 labeled ranges. All eight absent identifiers were checked with exact-token Git searches and were absent from the tracked corpus files.

Default backend scope includes source, tests, changelogs, supported configuration files, nested Markdown and generated Markdown maps. Every index used its `docs/` root, no exclusions, 1,200-character whole-line chunks, at most 48 lines and eight overlap lines. This is the existing backend configuration, including its built-in symbol bonus even in lexical mode; the separate lexical-symbol reranker adds another deterministic symbol/path ranking stage. Query limit was ten.

Optional inference used Node 24.21.0, pnpm 12.4.1 and the frozen runtime manifests copied into `/home/lucas/DEV/Projects/agent-toolbox-eval/cache/inference-runtime/`. The model was `Xenova/all-MiniLM-L6-v2` at `751bff37182d3f1213fa05d7196b954e230abad9`, Transformers.js 3.8.1, quantized q8 CPU inference, and the stdlib exact cosine vector engine. The model cache is `/home/lucas/DEV/Projects/agent-toolbox-eval/cache/models/`. Query inference was offline. No reranker model or native vector extension was installed.

The first setup wrapper exited 3 during nvm initialization, before pnpm ran. Allowing that initialization status while checking the actual Node executable fixed the wrapper; the pinned frozen install then succeeded. No installed skill or global Node environment was changed.

Each published query timing is one sequential CLI call, including Python/Node startup, backend freshness scans and parsing, with no warmup removed. Embedding indexing and some validation ran concurrently on this shared host. Latencies are observations under contention, not isolated throughput measurements or reliable speed rankings. Index receipts include wall time from a fresh process and SQLite bytes.

## Index coverage and limits

| Corpus | Tracked paths | Indexed files | Chunks | Skipped files | Oversized chunks | Lexical index seconds | Lexical MiB | Embedded index seconds | Embedded MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| httpx | 125 | 97 | 1177 | 0 | 0 | 0.759 | 3.47 | 209.884 | 5.78 |
| vite | 2868 | 2430 | 7284 | 2 | 11 | 6.138 | 17.84 | - | - |
| jftp | 923 | 601 | 6332 | 41 | 11 | 2.771 | 23.00 | - | - |
| django | 7084 | 3484 | 23597 | 3 | 9 | 11.937 | 68.64 | - | - |

All four full lexical corpora indexed successfully. No 10,000-file, 30,000-chunk or 100,000-candidate discovery limit was hit. Django had 7,084 tracked paths, 3,484 indexed files and 23,597 chunks; the brief predicted that it might exceed a cap, but it did not. No Django subset was necessary or substituted. Unsupported files do not count as backend `skipped` files.

Django has 677 `.txt` reStructuredText documents and one `.rst` document under `docs/`; none is admitted by the Markdown-only docs path or the source extension allowlist. The docs index therefore contains zero docs-root chunks. The transaction-howto question deliberately retains its original unindexed documentation range rather than replacing the label with code the engine can see. This coverage gap also explains why a full lexical index stays under the chunk cap.

HTTPX skipped no files. Vite skipped its oversized lockfile and package changelog. jFTP skipped 41 non-UTF-8 localized resource files. Django skipped two oversized test modules and one non-UTF-8 CSS fixture. `inventory.json` contains the complete skipped-path list and reasons; the backend index response itself returns only the first twenty details. An oversized chunk exceeds the 1,200-character target because a whole source line is indivisible; it is not necessarily over the separate embedding input limit.

### Optional embedding setup outcomes

Each corpus was given a bounded 900-second embedding-index setup attempt, following the brief's approximately 15-minute setup escape. This is an evaluation wrapper budget, not a backend file/chunk cap. Unfinished indexes are not queried and receive no retrieval score. A timeout does not show that indexing could never finish with more time. Lexical-symbol uses the same lexical index; semantic and hybrid require the completed embedded index.

| Corpus | Attempt seconds | Status | Evidence |
| --- | ---: | --- | --- |
| httpx | 209.884 | completed | Completed |
| vite | 900.000 | unavailable | Evaluation setup wall-time budget of 900 seconds exceeded; subprocess.TimeoutExpired. No completed embedded index or semantic score. |
| jftp | 2.408 | unavailable | retrieval error: Embedding input exceeds 12000 UTF-16 characters at docs:repo-maps/artifacts/2026-10-08/windows-final/final-report.md:L25-L25; use lexical indexing, --exclude this asset, or provide smaller verified documentation chunks |
| django | - | pending | No completed receipt yet |

Vite exceeded the wrapper limit. The initial run driver failed to catch `subprocess.TimeoutExpired`; its traceback and exit 1 are preserved in `embed-e1.log`, and the receipt explicitly records the configured 900-second limit rather than a successful duration. The driver then recorded failures without aborting the remaining setup attempts. This orchestration failure is separate from the evaluated backend and did not change its source or the lexical indexes.

## Retrieval results

Scores below use 13 positive and two absent questions for each of HTTPX, Vite and jFTP, and eight positive and two absent questions for Django. Hit@k requires any same-path inclusive line overlap. Recall@10 is the mean fraction of all expected ranges found per positive question. The JSON and per-run Markdown also contain hit@3, micro range recall, all budget character precision values and every question result. Budget columns show any-expected-range hit rates at 2,000 and 5,000 estimated tokens.

| Corpus | Mode | H@1 | H@5 | H@10 | MRR@10 | Range recall@10 | Budget 2k hit | Budget 5k hit | Precision 2k | p50 s | p95 s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| httpx | lexical | 61.5% | 69.2% | 69.2% | 0.654 | 69.2% | 69.2% | 69.2% | 10.4% | 1.444 | 3.426 |
| httpx | lexical-symbol | 38.5% | 46.2% | 46.2% | 0.410 | 46.2% | 46.2% | 46.2% | 6.7% | 1.451 | 3.021 |
| httpx | semantic | 38.5% | 76.9% | 84.6% | 0.564 | 84.6% | 84.6% | 84.6% | 9.7% | 3.096 | 6.309 |
| httpx | hybrid | 61.5% | 69.2% | 84.6% | 0.678 | 84.6% | 84.6% | 84.6% | 10.5% | 3.813 | 5.406 |
| vite | lexical | 30.8% | 53.8% | 69.2% | 0.419 | 65.4% | 53.8% | 69.2% | 5.1% | 8.029 | 10.857 |
| vite | lexical-symbol | 23.1% | 38.5% | 46.2% | 0.297 | 46.2% | 38.5% | 46.2% | 3.3% | 7.063 | 8.506 |
| vite | semantic | unavailable | - | - | - | - | - | - | - | - | - |
| vite | hybrid | unavailable | - | - | - | - | - | - | - | - | - |
| jftp | lexical | 7.7% | 7.7% | 7.7% | 0.077 | 3.8% | 7.7% | 7.7% | 0.2% | 3.837 | 5.019 |
| jftp | lexical-symbol | 7.7% | 15.4% | 23.1% | 0.105 | 19.2% | 23.1% | 23.1% | 2.9% | 2.978 | 4.307 |
| jftp | semantic | unavailable | - | - | - | - | - | - | - | - | - |
| jftp | hybrid | unavailable | - | - | - | - | - | - | - | - | - |
| django | lexical | 12.5% | 62.5% | 62.5% | 0.317 | 56.2% | 62.5% | 62.5% | 4.8% | 13.017 | 16.702 |
| django | lexical-symbol | 25.0% | 75.0% | 75.0% | 0.448 | 68.8% | 75.0% | 75.0% | 5.4% | 11.162 | 12.975 |
| django | semantic | unavailable | - | - | - | - | - | - | - | - | - |
| django | hybrid | unavailable | - | - | - | - | - | - | - | - | - |

### Overall on all four corpora

This pools the same 47 positive questions for both lexical variants; the eight absent questions remain separate. Semantic results are not pooled across unequal corpus coverage. `lexical-overall.json` and `lexical-symbol-overall.json` retain the combined per-question and per-kind detail.

| Mode | H@1 | H@3 | H@5 | H@10 | MRR@10 | Macro range recall | Micro range recall | Budget 2k hit | Budget 2k precision | Budget 5k hit | Budget 5k precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical | 29.8% | 42.6% | 46.8% | 51.1% | 0.372 | 47.9% | 45.5% | 46.8% | 5.1% | 51.1% | 4.0% |
| lexical-symbol | 23.4% | 34.0% | 40.4% | 44.7% | 0.301 | 42.6% | 40.0% | 42.6% | 4.5% | 44.7% | 3.8% |

### Per-kind breakdown

Each cell is hit@1 / hit@5 / hit@10, followed by MRR@10 in parentheses. Counts exclude the absent questions. Full per-kind budget metrics and latencies are in each raw run.

| Corpus | Kind | Count | Lexical | Lexical-symbol | Semantic | Hybrid |
| --- | --- | ---: | --- | --- | --- | --- |
| httpx | concept | 2 | 50.0% / 50.0% / 50.0% (0.500) | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 50.0% / 100.0% (0.250) | 50.0% / 50.0% / 50.0% (0.500) |
| httpx | config | 3 | 33.3% / 66.7% / 66.7% (0.500) | 33.3% / 33.3% / 33.3% (0.333) | 0.0% / 33.3% / 33.3% (0.167) | 33.3% / 66.7% / 66.7% (0.500) |
| httpx | cross-file | 1 | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) |
| httpx | docs-howto | 3 | 100.0% / 100.0% / 100.0% (1.000) | 33.3% / 66.7% / 66.7% (0.444) | 33.3% / 100.0% / 100.0% (0.611) | 100.0% / 100.0% / 100.0% (1.000) |
| httpx | exact-symbol | 2 | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) |
| httpx | paraphrase | 2 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | 50.0% / 100.0% / 100.0% (0.750) | 0.0% / 0.0% / 100.0% (0.155) |
| vite | concept | 3 | 0.0% / 66.7% / 66.7% (0.250) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| vite | config | 2 | 0.0% / 50.0% / 50.0% (0.250) | 0.0% / 50.0% / 100.0% (0.306) | - | - |
| vite | cross-file | 1 | 0.0% / 0.0% / 100.0% (0.100) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| vite | docs-howto | 3 | 33.3% / 33.3% / 66.7% (0.367) | 0.0% / 33.3% / 33.3% (0.083) | - | - |
| vite | exact-symbol | 2 | 100.0% / 100.0% / 100.0% (1.000) | 100.0% / 100.0% / 100.0% (1.000) | - | - |
| vite | paraphrase | 2 | 50.0% / 50.0% / 50.0% (0.500) | 50.0% / 50.0% / 50.0% (0.500) | - | - |
| jftp | concept | 2 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| jftp | config | 3 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| jftp | cross-file | 1 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| jftp | docs-howto | 2 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 50.0% / 100.0% (0.181) | - | - |
| jftp | exact-symbol | 2 | 50.0% / 50.0% / 50.0% (0.500) | 50.0% / 50.0% / 50.0% (0.500) | - | - |
| jftp | paraphrase | 3 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| django | concept | 1 | 0.0% / 100.0% / 100.0% (0.200) | 0.0% / 100.0% / 100.0% (0.250) | - | - |
| django | config | 2 | 0.0% / 100.0% / 100.0% (0.417) | 0.0% / 100.0% / 100.0% (0.417) | - | - |
| django | cross-file | 1 | 0.0% / 100.0% / 100.0% (0.500) | 0.0% / 100.0% / 100.0% (0.500) | - | - |
| django | docs-howto | 1 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | - | - |
| django | exact-symbol | 2 | 50.0% / 50.0% / 50.0% (0.500) | 100.0% / 100.0% / 100.0% (1.000) | - | - |
| django | paraphrase | 1 | 0.0% / 0.0% / 0.0% (0.000) | 0.0% / 0.0% / 0.0% (0.000) | - | - |

### Absent questions

| Corpus | Lexical | Lexical-symbol | Semantic | Hybrid |
| --- | ---: | ---: | ---: | ---: |
| httpx | 100.0% | 100.0% | 100.0% | 100.0% |
| vite | 100.0% | 100.0% | - | - |
| jftp | 100.0% | 100.0% | - | - |
| django | 100.0% | 100.0% | - | - |

The absent test checks only whether a top-five result text contains the invented identifier as a case-sensitive exact token. Since each invented token was verified absent from all tracked corpus text, a source-faithful retriever will pass regardless of whether it returns useful snippets, unrelated snippets or no snippets. This is effectively a contamination/contract check, not an answerability evaluation. It does not establish justified abstention, a correct natural-language answer or a reliable repository-wide absence judgment. These rows are kept separate from positive hit and recall metrics.

## Instructive failures

### httpx-003 (lexical)

Where is the redirect limit enforced for a synchronous request?

Expected: `httpx/_client.py:L964-L974`. Top three: `CHANGELOG.md:L613-L633`; `CHANGELOG.md:L842-L865`; `CHANGELOG.md:L690-L703`. No expected range was found in the top ten. Indexed overlapping chunks: 1; their initial BM25 ranks: [54]; ranks after the existing lexical symbol bonus within the 60 candidates: [54]. Natural-language redirect intent loses to changelog vocabulary; the enforcement guard does not carry the same prose. This points to concept-to-symbol linking and retrieval candidate/ranking quality, not evidence of a missing API.

### httpx-007 (lexical-symbol)

How does Timeout combine a default duration with separate connect, read, write and pool durations?

Expected: `httpx/_config.py:L111-L130`. Top three: `httpx/_config.py:L58-L94`; `tests/test_multipart.py:L393-L430`; `httpx/_transports/default.py:L393-L406`. No expected range was found in the top ten. Indexed overlapping chunks: 3; their initial BM25 ranks: [2, 4, 5]; ranks after the existing lexical symbol bonus within the 60 candidates: [2, 4, 5]. The first result names Timeout but ends before the actual default-filling logic. Fixed line/character chunks detach the class name and usage documentation from its implementation; a symbol-only bonus can prefer the earlier fragment.

### vite-004 (lexical)

Why can changing a prebundled dependency cause the browser to lose its current page state?

Expected: `packages/vite/src/node/optimizer/optimizer.ts:L378-L389`; `packages/vite/src/node/optimizer/optimizer.ts:L529-L538`. Top three: `packages/create-vite/template-svelte/README.md:L28-L43`; `packages/create-vite/template-svelte/README.md:L22-L35`; `packages/vite/src/node/optimizer/optimizer.ts:L585-L610`. No expected range was found in the top ten. Indexed overlapping chunks: 4; their initial BM25 ranks: [13, 16, 1412, 1499]; ranks after the existing lexical symbol bonus within the 60 candidates: [15, 18]. The query wording about browser state overlaps generic template documentation, while dependency hash and interop logic is spread across optimizer chunks. Function-aware chunks and code/doc linkage are plausible improvements.

### jftp-012 (lexical)

Where are post-login commands executed before switching to the initial remote directory?

Expected: `src/main/java/com/myjavaworld/jftp/FTPSession.java:L649-L672`. Top three: `docs/application-workflows.md:L15-L15`; `docs/ui-and-browser-details.md:L32-L36`; `src/main/resources/com/myjavaworld/jftp/ConnectionDlg.properties:L1-L31`. No expected range was found in the top ten. Indexed overlapping chunks: 2; their initial BM25 ranks: [76, 331]; ranks after the existing lexical symbol bonus within the 60 candidates: []. The requested lifecycle spans login, post-login commands and initial-directory handling in a large session class. Competing generated documentation and short fragments can hide the defining sequence; inspect the shown evidence before assigning causality.

### django-006 (lexical)

How do I make every HTTP request commit on success and roll back if the view raises an exception?

Expected: `docs/topics/db/transactions.txt:L29-L44`. Top three: `tests/view_tests/views.py:L1-L43`; `django/db/transaction.py:L41-L86`; `django/db/transaction.py:L291-L314`. No expected range was found in the top ten. Indexed overlapping chunks: 0; their initial BM25 ranks: []; ranks after the existing lexical symbol bonus within the 60 candidates: []. The labeled reStructuredText document is not indexed at all. Ranking or a different vector database cannot recover this range; extension/format coverage must be fixed first.

## Observed defects and operational limitations

The backend did not crash during any completed query run. Its main coverage defect in this evaluation is that specifying Django's docs root produces no reStructuredText chunks, without counting unsupported documentation formats in `skippedCount`. The inventory receipt makes that missing coverage explicit.

jFTP's unchanged docs contain a 43,837-character single-line generated report at `docs/repo-maps/artifacts/2026-10-08/windows-final/final-report.md:L25`. The whole-line chunker preserves it, then the embedding input guard rejects it before inference. That prevents semantic/hybrid setup for the full corpus; it was not silently excluded or rewritten. The lexical index still succeeds and reports oversized chunks.

The index response truncates skipped-path detail to twenty entries even when the count is larger; the full jFTP list was recovered through a separate read-only inventory pass. The lexical candidate limit is sixty, so reranking cannot recover jFTP post-login implementation chunks initially ranked 76 and 331. Conversely, the HTTPX Timeout implementation already appears at lexical candidate ranks 2, 4 and 5 but is pushed out of the final top ten by the extra symbol/path reranker. These are distinct coverage and ordering problems.

No backend files were patched. The local setup/benchmark wrapper fixes and timeout receipts are documented separately above.

## Metric design and interpretation

I would not use any-overlap hit rate alone as the release gate for the replacement engine. A chunk touching one expected line can count as a hit while omitting the answer, and a useful unlisted doc or test can be scored as a miss. Cross-file questions require all-range recall and manual evidence review. The question sets are intentionally small (47 positive questions total), with some per-kind groups containing only one or two items; small differences are not statistical proof.

The character budget fills results in rank order and clips the final result to the remaining `4 * budget` characters. It charges text only, without citation metadata or formatting; precision measures characters lying on expected source lines, unioned across overlapping labels. Duplicated returned chunks cost budget again. This is an explicit reproducible estimate, not a tokenizer measurement or agent answer score. At the default 1,200-character target, ten ordinary chunks fit well within 5,000 estimated tokens, so the 5k hit rate often equals hit@10. A larger candidate pool and actual snippet formatting would make that budget more discriminating.

## Concrete hypotheses for the replacement

1. Index supported code and actual documentation formats, including Django reStructuredText, before changing ranking. Report omitted extensions separately from files attempted but skipped. Keep source and doc provenance without losing their corpus-relative identity.

2. Use function/class-aware boundaries with enclosing symbol names, signatures and imports retained across fragments. Pair concise verified how-to/API cards with the original implementation and real callers, so natural-language intent can lead to source without treating every changelog or generated map as equally authoritative.

3. Retrieve diversified candidates across code, docs and tests, retain exact symbol matches, and deduplicate near-identical overlapping chunks before spending answer budget. Measure source diversity and all-range recall for cross-file questions.

4. Evaluate code-aware embeddings and hybrid fusion on held-out data. The pinned generic prose embedding is useful on some paraphrases but cannot by itself supply missing docs, restore truncated context or resolve every symbol. Do not infer that changing vector storage will improve representation quality.

5. Replace or calibrate the extra symbol/path reranker only with measured evidence. Benchmark persistent warm inference and incremental freshness validation separately from quality, then compare latency on an otherwise idle host. Add an abstention/answerability evaluation beyond the deliberately weak absent-identifier contamination check.

## Validation and artifacts

The focused evaluator suite passed 24 offline tests, including an actual-backend regression for queries beginning with a dash. The existing retrieval suite passed 83 tests with 12 expected optional skips. `npm ci` ran in the external cache runtime, followed by the repository Node suite: 108 passed, zero failed. The existing Python CI glob already discovers `tests/test_legacy_eval_retrieval.py`, so no workflow edits were needed. All eight absent identifiers and 55 labeled source/doc ranges were validated against the pinned checkouts.

Raw runs and summaries: `evals/retrieval/results/baseline/`. Question sources: `evals/retrieval/questions/`. Harness: `skills/legacy-codebase-workflows/scripts/eval_retrieval.py`. Unit tests: `tests/test_legacy_eval_retrieval.py`. The complete inventory, ground-truth hashes and backend/environment hashes are saved beside the query reports.

Durable job logs and launch scripts are under `/home/lucas/DEV/Projects/agent-toolbox-eval/logs/`: `setup-e1.log`, `index-e1.log`, `embed-e1.log`, `embed-e1-followup.log`, `query-e1.log`, `checks-e1.log`, `final-checks-e1.log` and `evaluator-final-e1.log`. Tracking, commits, pushes and review belong to the orchestrator as directed by the brief.
