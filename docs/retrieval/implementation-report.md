# Local retrieval engine implementation report

Format 8 is implemented as a stdlib-first Python package behind the existing Context7 entry point. The complete Tier-0 development run reaches 76.6% hit@5 against 46.8% baseline. All quality figures below use the 47 positive development questions; eight additional absent-name questions are included in the runs. No held-out question or label was opened or used.

These are development measurements on the shared W365 VM, not reference-laptop, held-out, or release acceptance claims. No installed skill, PRD, ADR, commit, push, or production service was changed by this delegate.

## Implementation

The package is `skills/legacy-codebase-workflows/scripts/local_context/`. `units.py` supplies frozen source/unit records and stable errors; `discover.py` and `decode.py` supply bounded inventory, root ownership, exclusions, strict decoding and narrow secret scanning; `chunk.py` supplies Python AST, conservative declaration scanners, optional pinned tree-sitter, document sections, HTML and notebooks; `store.py` supplies format-8 SQLite/WAL, ownership constraints, per-library FTS5, symbols and vector rows; `symbols.py`, `search.py` and `assemble.py` supply tokenization, shadow stemming, retrieval, verification, citations and evidence budgets; `freshness.py` and `engine.py` supply incremental publication, candidate catch-up, expansion, resolution and status; `cli.py` and `http_api.py` supply the adapters. `protocol.py` retains the bounded legacy Node helper protocol and its focused regressions.

`context7_backend.py` is a thin shim. The old positional arguments and the required exports remain available. The server factory and diagnostic sink actually use the shim exports, preserving the generated launcher's lifecycle and stdout patches. `setup_context7.py` hashes and copies the complete package and required Node helper/lock resources. The Claude hook uses the setup interpreter so it cannot silently switch parser tiers. The existing native/ZIP payload discovery already includes the package; no builder fork was needed.

`embed.py`, `vectors.py`, their requirements, benchmarks and provider tests belong to the other delegate. This engine integrates their published provider/vector interface lazily. Lexical import, index, query, refresh and HTTP do not require those optional capabilities. Model downloads require explicit index enablement; queries and refresh pass download disabled. Consented endpoint configuration and identity are saved per library. Models are loaded only when changed content needs embedding, not for an unchanged or metadata-only refresh.

## Development quality

The full row below is the fresh-index Tier-0 development run using the shipped evaluator's unchanged source-range scoring. It includes Python CLI startup and candidate source verification. Indexing/benchmark lanes overlapped during this run; the separate sequential CLI table follows.

| Corpus | Baseline hit@5 | New hit@5 | Baseline MRR@10 | New MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| httpx | 69.2% | 76.9% | 0.654 | 0.769 |
| vite | 53.8% | 92.3% | 0.419 | 0.592 |
| jftp | 7.7% | 53.8% | 0.077 | 0.460 |
| django | 62.5% | 87.5% | 0.317 | 0.812 |
| Overall | 46.8% | 76.6% | 0.372 | 0.642 |

Every corpus exceeds its baseline hit@5 and MRR@10; jFTP exceeds the 40% floor. Absent-name contamination checks remain 100% successful. They are not an absence/completeness proof. Raw records are in `evals/retrieval/results/local-core/release-t0/` and `release-t1/`; the final sequential comparison is in `verified-cli/`.

## Sequential CLI and parser tiers

Each CLI latency includes a new Python process, query analysis/ranking, root triggers, and candidate source hashes. Runs use `--limit 10`, lexical mode, default 1,500 non-whitespace character chunks and no explicit output budget. Parsing is an index-time choice. Tier 1 is optional and falls back per grammar; its generic symbol metadata is best effort.

| Mode | Corpus | Hit@5 | MRR@10 | Query p50 s | Query p95 s |
| --- | --- | ---: | ---: | ---: | ---: |
| t0 | httpx | 76.9% | 0.769 | 0.409 | 0.723 |
| t0 | vite | 92.3% | 0.592 | 0.694 | 0.837 |
| t0 | jftp | 53.8% | 0.460 | 0.919 | 1.567 |
| t0 | django | 87.5% | 0.812 | 0.689 | 0.990 |
| t1 | httpx | 76.9% | 0.769 | 0.392 | 0.761 |
| t1 | vite | 92.3% | 0.727 | 0.778 | 1.005 |
| t1 | jftp | 53.8% | 0.511 | 0.883 | 1.394 |
| t1 | django | 87.5% | 0.812 | 0.744 | 1.431 |

## Index coverage and scale observations

The fresh default-size index receipts below use the final format-8 parser/discovery behavior. Indexing ran concurrently on this shared VM; do not treat timings as isolated throughput. Every discovered eligible file is indexed/redacted or has an explicit skip/binary/unreadable record. There is no old 10k-file, 30k-chunk or 100k-discovery ceiling. The default discovery safety bound is 2,000,000 and exceeding it aborts atomically.

| Mode | Corpus | Indexed files | Skipped | Searchable units | Seconds | SQLite MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| t0 | httpx | 113 | 10 | 1985 | 3.344 | 8.68 |
| t0 | vite | 2739 | 86 | 12922 | 29.785 | 59.64 |
| t0 | jftp | 808 | 115 | 13583 | 33.435 | 89.72 |
| t0 | django | 5701 | 1378 | 67929 | 154.687 | 319.32 |
| t1 | httpx | 113 | 10 | 1997 | 6.018 | 8.86 |
| t1 | vite | 2739 | 86 | 10968 | 45.021 | 54.44 |
| t1 | jftp | 808 | 115 | 13694 | 45.009 | 87.20 |
| t1 | django | 5701 | 1378 | 66786 | 204.143 | 316.67 |

Django includes all 678 reStructuredText files under its documentation root, including the 677 `.txt` files omitted by the old backend. Its default index completes well below ten minutes on this VM. Unknown extensions and legacy source families are admitted through the text fallback; the decoding chain covers declared encodings, BOM-aware UTF-8/UTF-16, configured encodings, cp1252 and marked latin-1 assumptions. `.properties` tries UTF-8 then ISO-8859-1.

The additional synthetic run indexed 1000 files in 2.183 s, refreshed exactly 100 changed files of 1,000 in 1.509 s, and returned zero hash-mismatched bodies across 100 follow-up queries. A metadata-only commit refreshed in 0.621 s with zero content reprocessing. WAL reader/writer, rollback, preserved-mtime, deletion, unsafe replacement and candidate-only query behavior have dedicated regressions. A full 10k-file/1% refresh and 200k-file index were not run; these are outstanding scale certifications, not claimed passes.

## Evidence budgets

A8 is implemented literally: `ceil((header + description + source body + compact citation characters)/4)`. JSON keys/envelope are outside this budget. CLI queries are unbudgeted unless `--tokens` is supplied; HTTP defaults to 4,000. Over-budget query units become contiguous whole-line excerpts with corrected citations, or are omitted explicitly. Exact expansion is all-or-error.

| Measurement | 2k hit | 2k source-character precision |
| --- | ---: | ---: |
| Baseline evaluator text-prefix budget | 46.8% | 5.1% |
| New ranking, same posthoc text-prefix policy | 76.6% | 7.2% |
| New native `--tokens 2000` response | 74.5% | 10.8% |

The native response reaches 2.10x baseline precision and checks its charged budget for every question. This is not an identical budgeting policy: the baseline/posthoc evaluator clips source bodies alone, whereas the engine spends some of its 2k allowance on provenance, headers and descriptions. Under a strict interpretation requiring the unchanged posthoc policy, the 2x precision gate is not met. Do not combine these policies into a single unconditional acceptance claim. `budget-native.json` records the distinction, every budget receipt and source-only precision scores.

## Ranking iterations and ablations

The measured failure behind the symbol fix was a tiny class declaration outranking its constructor or method. Exact class queries now anchor descendant units, while qualified identifiers keep specific definitions first. Coverage uses decoded header text, not escaped JSON. The shadow stemmer normalizes ordinary inflections without a corpus-specific synonym dictionary. History/release reports, test fixtures, generated/minified paths and doc-intent boosts are separately ablatable.

The additional structural channel follows only explicit backticked symbol references in the top three relevant documentation units, resolves names against this library's real symbol table, then ranks at most three implementing units per bounded reference. It runs only when the first three lexical results contain no code, the query has no exact symbol anchor, and no doc-intent boost applies. It never invents APIs or fetches a URL. Ungated references damaged jFTP; the gate preserves existing leading code evidence. This is a deliberate, measured extension to the ADR's listed channels.

| Iteration | Overall hit@5 | MRR@10 | Note |
| --- | ---: | ---: | --- |
| Quadratic coverage | 70.2% | 0.584 | Development trial |
| Linear coverage | 72.3% | 0.587 | Development trial |
| No coverage | 74.5% | 0.555 | Development trial |
| Linear + stronger stem channel | 74.5% | 0.590 | Development trial |
| Ungated explicit doc references | 70.2% | 0.560 | Rejected: jFTP floor regressed |
| Final gated references + linear coverage | 76.6% | 0.642 | Selected |

Additional lighter coverage weights are retained in `ranking-trials-v2.json`. A 750-character exploratory index lost the jFTP floor, so the 1,500-character default is retained; its unnecessary Django continuation was stopped after preserving the evidence. Early `initial`, `structure` and `tier1` reports were development diagnostics while code evolved; `verified-cli` is the final CLI comparison.

| Feature removed | Overall hit@5 | MRR@10 |
| --- | ---: | ---: |
| symbols | 72.3% | 0.581 |
| paths | 76.6% | 0.630 |
| shadow | 72.3% | 0.599 |
| coverage | 76.6% | 0.577 |
| history | 76.6% | 0.629 |
| tests | 70.2% | 0.625 |
| generated | 76.6% | 0.630 |
| docs | 76.6% | 0.626 |
| references | 72.3% | 0.587 |

These whole-feature ablations were run before the final config-flow refinement. They include each earlier named prior and the selected coverage factor. The final 0.8 config-flow weight is independently compared by the per-corpus `before-config-prior/` and final CLI records; it down-weights passive config/resource labels only for where/trace behavior queries and moved the Tier-1 post-login implementation from rank six to rank one. The nonzero weights are not claimed universal optima. No held-out tuning was done.

## Compatibility, tests and intentional test changes

Real unmodified ctx7 0.5.13 and Context7 MCP 4.0.3 pass the generated-project integration suite. MCP identification is the inspected `X-Context7-Source: mcp-server` header; missing `type` defaults to text only for that client and to legacy JSON otherwise. Info snippets retain `pageTitle`/`description` and add the corrected `pageId`, `breadcrumb` and actual content token count. Host/Origin/port rejection, duplicate parameters, request bounds, UUID replacement, expansion, native/text/JSON stale markers and legacy startup stdout have contract tests.

The full Python suite passed 341 tests with system Python and with the isolated pinned parser venv; the focused core/HTTP suite has 47 tests, passing with one explicit real-model opt-in skip. Optional parser-dependent map/render tests now skip cleanly in the stdlib lane and execute in the parser lane; the equivalent C# dispatcher test also gates its optional capability. The native dispatcher's Unicode regression now accepts the newly searchable Latin-1 documentation fixture in addition to the original source file. These narrow edits outside the brief's named retrieval test files were required to make its repository-wide stdlib check meaningful.

`test_legacy_retrieval.py` retains the bounded helper/Unicode tokenizer/whole-line protocol regressions. Format-7 storage, in-place migration, global caps, mandatory UTF-8 skips, extra symbol-only reranking, mandatory stale HTTP 409 and learned cross-encoder assumptions were replaced by format-8 integration coverage in `test_legacy_local_context_core.py` and `test_legacy_local_context_http.py`. Provider/vector oracles and malformed-provider cases are in the other delegate's `test_legacy_embed.py`. New tests cover same-line metadata deduplication, oversized parent/child identity, inherited-header secret redaction, mixed libraries, safe expansion, operator-as-data queries, no query inventory, rollback/WAL snapshots and fake-provider integration.

A real cached Transformers.js index and semantic/hybrid round-trip passed. This establishes wiring, not semantic quality superiority. The engine does not recommend an embedding provider on the basis of this round-trip; the other delegate owns the model benchmark. The semantic CI workflow now triggers on the new tests and runs the new engine suite as well as the retained helper suite. The broad Python workflow already covered the package and tests.

Node `npm ci` succeeded. Early Node runs passed the original 108 tests; a temporary failure came from a parallel usage-analytics addition. That work completed independently, and the final full Node run passed all 111 tests. Those unrelated files were not changed by this delegate.

## Remaining limits and ADR interpretations

There is no held-out or reference-laptop signoff. Full 200k-file and 10k-file incremental certification remain unmeasured. The primary dev hit/MRR floors are met, while the precision gate depends on the budget-policy interpretation explained above. Full-corpus semantic/paraphrase superiority has not been established by this engine run. Only Linux/WSL was executed locally; Windows/macOS validation remains with CI. The legacy `lexical-symbol` flag is a compatibility alias for the lexical pipeline rather than a second ranking pass. Changing the root set of an existing library requires a new library ID. The generated wrapper refresh now preserves saved provider/scanner/parser settings.

Tier-0 names and scope chains are heuristic outside Python; Tier-1 symbol metadata is best effort. Configs intentionally use generic block/windows. HTML uses safe extracted text with a raw-file envelope; notebooks use transformed cell text and a raw-file envelope when exact cell source offsets are unavailable. Oversized documentation sections use source-faithful whole-line parts with nearby explanatory context rather than a complete separate fenced-code AST; fitting prose/code sections stay together. These are bounded v1 alternatives, not claims of complete language/document understanding.

Queries verify only their bounded candidate files and cheap root triggers. Newly added noncandidate files require explicit refresh; Git HEAD/index triggers cannot detect every unstaged nested addition. Empty results remain explicitly not proof of absence. Exact expansion always requires the live indexed hash and cannot read arbitrary files. Parent metadata for multiple declarations sharing one physical line is deduplicated before persistence; public UIDs include searchable/parent identity and title to disambiguate metadata from a body with the same envelope.

The service is unauthenticated and intended for one user on one machine, on 127.0.0.1 only by default. No source text is executed. The scanner is deliberately narrow: strict provider keys and PEM private blocks, not generic password assignments. It does not promise detection of all credentials.

## Reproduce

Use the pinned commits in `evals/retrieval/corpora.json`, with all indexes and caches outside source trees. On this machine corpora are `/home/lucas/DEV/Projects/agent-toolbox-eval/corpora/`, indexes are `/home/lucas/DEV/Projects/agent-toolbox-eval/indexes/`, and the parser venv is `/home/lucas/DEV/Projects/agent-toolbox-eval/venv-core/`. `python3 -m venv` lacked ensurepip; the installed uv created the venv and installed the unchanged requirements-map pins instead.

```bash
python3 skills/legacy-codebase-workflows/scripts/context7_backend.py index "$CORPUS" --docs-root "$CORPUS/docs" --database "$DATABASE" --library-id /local/example --parser 0
```

```bash
python3 skills/legacy-codebase-workflows/scripts/eval_retrieval.py evals/retrieval/questions/httpx.dev.jsonl --engine context7-backend --database "$DATABASE" --json-output "$OUTPUT/httpx.json" --markdown-output "$OUTPUT/httpx.md"
```

Use `--parser 1` under the pinned parser venv for Tier 1. For a per-feature ablation, add `--ablate symbols`, `paths`, `shadow`, `coverage`, `history`, `tests`, `generated`, `docs`, `references` or `config-behavior` to query invocations. Query with `--tokens 2000` for the charged-budget run.

```bash
LEGACY_NATIVE_BUILD=0 python3 -m unittest discover -s tests -p "test_legacy_*.py"
```

```bash
LEGACY_NATIVE_BUILD=0 /home/lucas/DEV/Projects/agent-toolbox-eval/venv-core/bin/python -m unittest discover -s tests -p "test_legacy_*.py"
```

```bash
LEGACY_CONTEXT7_CLIENTS=1 python3 -m unittest discover -s tests -p test_legacy_context7_project.py
```

```bash
npm ci
```

```bash
npm test
```

Exact run drivers and durable logs are under `/home/lucas/DEV/Projects/agent-toolbox-eval/logs/`: `i1-run.py`, `i1-final-ablations.py`, `i1-verified-cli.py`, `i1-budget-eval.py`, `i1-final-extra.py`, `i1-release-t0.log`, `i1-release-t1.log`, `i1-final-ablations.log`, `i1-release-cli.log`, `i1-release-budget.log`, `i1-extra.log`, `i1-client-checks.log`, `i1-semantic-check.log`, `i1-sealed-checks.log` and `i1-final-python.log`. Earlier failed/import/setup/minified-index logs are retained beside them.

The owned Herdr workspaces were `wMZ` (corpus runs/ablations), `wM0` (parser setup, budget/scale checks and sequential CLI) and `wN2` (tests and the rejected smaller-chunk trial). Each is closed after its processes exit and evidence is recorded; final cleanup is recorded in the handoff. No worktree was created.

Cleanup verified: owned workspaces wMZ, wM0 and wN2 were closed after foreground/process and background-child checks. `/home/lucas/DEV/Projects/agent-toolbox-eval/logs/i1-cleanup.jsonl` records zero remaining child jobs for each. Final workspace listing contains none of those IDs. Existing worktrees and other workspaces were preserved.

The final source also validates cached bodies against live cited lines, rejects nonregular/FIFO replacements without blocking, validates persisted library metadata, and avoids fetching the full per-file index report during queries. These corrections preserve candidate-only query cost and do not change the indexed source content or selected ranking parameters.

## Quality round 2

This round uses the original 47 positive development questions and the independent 68-positive dev2 set, with 15 additional absent-name checks across the two sets. No held-out question or label was opened. These are development results, not held-out acceptance. Before means commit `1a41859` run against the preserved Tier-0 indexes; after means the final source and freshly reprocessed format-8 indexes. Every reported quality/latency row uses the unchanged evaluator source-range scoring and a new CLI process per question. Full records and streamed logs remain under `/home/lucas/DEV/Projects/agent-toolbox-eval/round2/` and `/home/lucas/DEV/Projects/agent-toolbox-eval/logs/`; compact final evidence is in `evals/retrieval/results/local-core/round2/`.

### Lexical before and after

dev: 47 positive questions.

| Kind | N | Before hit@5 | After hit@5 | Before MRR@10 | After MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| concept | 8 | 87.5% | 87.5% | 0.515 | 0.604 |
| config | 10 | 80.0% | 80.0% | 0.633 | 0.700 |
| cross-file | 4 | 100.0% | 100.0% | 1.000 | 0.875 |
| docs-howto | 9 | 77.8% | 77.8% | 0.720 | 0.738 |
| exact-symbol | 8 | 100.0% | 100.0% | 0.938 | 0.938 |
| paraphrase | 8 | 25.0% | 25.0% | 0.156 | 0.177 |
| Overall | 47 | 76.6% | 76.6% | 0.631 | 0.657 |

| Corpus | N | Before hit@5 | After hit@5 | Before MRR@10 | After MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| httpx | 13 | 76.9% | 76.9% | 0.769 | 0.769 |
| vite | 13 | 92.3% | 92.3% | 0.554 | 0.673 |
| jftp | 13 | 53.8% | 53.8% | 0.460 | 0.421 |
| django | 8 | 87.5% | 87.5% | 0.812 | 0.833 |
| Overall | 47 | 76.6% | 76.6% | 0.631 | 0.657 |

dev2: 68 positive questions.

| Kind | N | Before hit@5 | After hit@5 | Before MRR@10 | After MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| concept | 18 | 61.1% | 61.1% | 0.363 | 0.407 |
| config | 7 | 57.1% | 57.1% | 0.375 | 0.429 |
| cross-file | 16 | 50.0% | 56.2% | 0.309 | 0.368 |
| docs-howto | 4 | 100.0% | 100.0% | 0.833 | 0.833 |
| exact-symbol | 7 | 100.0% | 100.0% | 1.000 | 1.000 |
| paraphrase | 16 | 37.5% | 43.8% | 0.300 | 0.309 |
| Overall | 68 | 58.8% | 61.8% | 0.430 | 0.463 |

| Corpus | N | Before hit@5 | After hit@5 | Before MRR@10 | After MRR@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| httpx | 18 | 66.7% | 72.2% | 0.426 | 0.450 |
| vite | 18 | 55.6% | 50.0% | 0.439 | 0.466 |
| jftp | 18 | 66.7% | 72.2% | 0.479 | 0.486 |
| django | 14 | 42.9% | 50.0% | 0.360 | 0.448 |
| Overall | 68 | 58.8% | 61.8% | 0.430 | 0.463 |

The aggregate lexical gain includes tradeoffs: Vite dev2 hit@5 falls from 55.6% to 50.0%, and jFTP dev MRR falls from 0.460 to 0.421. These regressions remain visible in the corpus tables and need the orchestrator's independent held-out check.

### Parser and hybrid comparison

Hybrid uses Tier-0 chunks, the cached Potion model pinned at `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b`, and the NumPy exact scanner. Tier 1 is lexical with the pinned parser venv. Embeddings remain explicitly enabled; lexical queries do not import or load a model. Hybrid trades extra latency and corpus-specific regressions for aggregate gains; the jFTP dev2 row is a material regression and prevents a universal quality claim.

dev.

| Kind | Tier-0 hit@5 | Tier-1 hit@5 | Hybrid hit@5 | Tier-0 MRR | Hybrid MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| concept | 87.5% | 87.5% | 87.5% | 0.604 | 0.656 |
| config | 80.0% | 70.0% | 90.0% | 0.700 | 0.733 |
| cross-file | 100.0% | 100.0% | 100.0% | 0.875 | 0.875 |
| docs-howto | 77.8% | 77.8% | 77.8% | 0.738 | 0.796 |
| exact-symbol | 100.0% | 100.0% | 100.0% | 0.938 | 0.875 |
| paraphrase | 25.0% | 50.0% | 62.5% | 0.177 | 0.325 |
| Overall | 76.6% | 78.7% | 85.1% | 0.657 | 0.699 |

| Corpus | Tier-0 hit@5 | Tier-1 hit@5 | Hybrid hit@5 | Tier-0 MRR | Hybrid MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| httpx | 76.9% | 76.9% | 92.3% | 0.769 | 0.810 |
| vite | 92.3% | 92.3% | 92.3% | 0.673 | 0.808 |
| jftp | 53.8% | 61.5% | 61.5% | 0.421 | 0.394 |
| django | 87.5% | 87.5% | 100.0% | 0.833 | 0.838 |

dev2.

| Kind | Tier-0 hit@5 | Tier-1 hit@5 | Hybrid hit@5 | Tier-0 MRR | Hybrid MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| concept | 61.1% | 66.7% | 66.7% | 0.407 | 0.454 |
| config | 57.1% | 57.1% | 71.4% | 0.429 | 0.565 |
| cross-file | 56.2% | 56.2% | 68.8% | 0.368 | 0.454 |
| docs-howto | 100.0% | 100.0% | 100.0% | 0.833 | 0.750 |
| exact-symbol | 100.0% | 100.0% | 85.7% | 1.000 | 0.857 |
| paraphrase | 43.8% | 50.0% | 56.2% | 0.309 | 0.380 |
| Overall | 61.8% | 64.7% | 69.1% | 0.463 | 0.507 |

| Corpus | Tier-0 hit@5 | Tier-1 hit@5 | Hybrid hit@5 | Tier-0 MRR | Hybrid MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| httpx | 72.2% | 72.2% | 72.2% | 0.450 | 0.466 |
| vite | 50.0% | 61.1% | 72.2% | 0.466 | 0.544 |
| jftp | 72.2% | 72.2% | 61.1% | 0.486 | 0.436 |
| django | 50.0% | 50.0% | 71.4% | 0.448 | 0.605 |

### Changes and selection

The candidate window now applies the existing per-file cap and envelope deduplication before bounded source verification. The former raw 30-unit prefix could be filled by one large class, after which packing kept only three units and never reached the other component. The old backend overfetched more candidates without that packing cap. New regression cases cover class siblings and duplicate envelopes; the change preserves ranking order while making the candidate bound apply to usable evidence.

Symbol anchoring now requires a real definition before expanding descendant titles. A documentation heading is not a definition. Unmarked all-capital prose acronyms no longer become case-folded lowercase function anchors; explicit code notation retains case-folded lookup, and title-case UI labels can still connect to actual lowercase methods. The symbol channel weight is reduced from 2.5 to 1.0, which improves aggregate dev2 hit@5 and MRR while keeping original dev hit@5. Body-heavy BM25 and lighter coverage were rejected because they did not improve both sets consistently. No corpus-specific terms, synonyms, paths or question IDs enter ranking.

Dense fusion happens after the complete lexical/reference pipeline. Dense-only code candidates cannot suppress lexical documentation-to-definition references. Lexical coverage no longer penalizes dense scores, including in semantic-only mode. A dense RRF weight of 2 balances the overlapping lexical channels better than 1 and improved both development sets in the controlled trial. Focused tests exercise semantic coverage independence, preservation of lexical reference bridges, and import/preamble windows that should not count as definition evidence.

History, tests, generated-path, config-flow and gated reference behavior remain independently ablatable. The A16-stage ablations in `ablations.json` cover both sets: removing history, test priors, references or coverage hurts dev2; config-flow removal leaves hit@5 tied but reduces MRR on both sets. Removing the 1.25 documentation-intent multiplier ties hit@5 on both final lexical sets but trades lower dev MRR for higher dev2 MRR; it was rejected because the secondary results do not tie. The existing conservative gate is retained, with real definitions replacing code provenance as its blocking signal. The report preserves each trial stage so earlier ablations are not presented as measurements of the final combined ranking.

The server cache keys the actual embedding config/identity, excluding publication timestamps and truncation counters, and closes the superseded provider when that library identity changes. HTTP regressions verify one model load across repeated requests and metadata republication, plus closure on shutdown. Real cached-model CLI index/query trials pass for both `--model-dir` and the new `--cache-dir` alias. The evaluator only gains an adapter option for `--vector-engine`; scoring and aggregation are unchanged. No changes were needed in the separately owned `embed.py`, `vectors.py` or embedding requirements.

A16(a)-(f) are implemented: underscore-preserving FTS with transactional upgrade of existing per-library tables; source-faithful line windows above the configured file threshold up to the default 20 MiB text ceiling, reported in `splitFiles`; generic recognition restricted to tree-sitter ERROR spans while valid syntax nodes survive; SQL-family Tier-0 procedure recognition including `.pck`; 8,000-character queries and 16 KiB request targets with a clear server-limit 413; default-excluded Git entries pruned before counting the discovery bound; BOM-less UTF-16 lane detection before binary rejection; and a Unicode-unescaped `.properties` search shadow that leaves cited source bytes/lines intact. Tests also cover both UTF-16 byte orders, upper-size boundaries, escaped backslashes and surrogate pairs, Git/walk exclusion parity, 32 analyzed terms and retained raw source envelopes. Secondary identifier pieces are derived only from retained primary terms, preventing the shadow channel from resurrecting terms past the 32-term bound. Assumed Latin-1 files are recorded separately from explicitly declared encodings.

Full reprocessing exposed an unindexed parent foreign-key lookup. An auxiliary `units(parent_unit_id)` index removes the whole-table scan during delete cascades and is added safely to existing format-8 stores without changing the logical schema fingerprint or reprocessing unchanged source. The focused regression checks the query plan and an unchanged refresh. The slow pre-fix reprocessing attempts were interrupted with rollback, preserved as `i3-index-*-before-parent-index.log`, then completed with the auxiliary index. No speedup ratio is claimed from the overlapping jobs.

### Latency and index receipts

CLI p50 values below pool dev and dev2 for each corpus and include startup, candidate hashes and normal freshness checks. Hybrid CLI includes a new model load per process; the HTTP column uses the persistent server after its first request.

| Corpus | Tier-0 lexical p50 s | Tier-1 lexical p50 s | Hybrid CLI p50 s | Warm hybrid HTTP p50 s |
| --- | ---: | ---: | ---: | ---: |
| httpx | 0.341 | 0.268 | 1.189 | 0.230 |
| vite | 0.380 | 0.386 | 1.462 | 0.448 |
| jftp | 0.567 | 0.565 | 1.599 | 0.473 |
| django | 0.672 | 0.666 | 2.060 | 0.968 |

Each real HTTP server handled 20 requests with exactly one provider load and closed after the benchmark. `warm-serve.json` records cold, warm p50/p95 and all samples. Both lexical parser tiers remain below the one-second p50 requirement for every corpus; hybrid latency is reported separately.

The initial clean embedded-index receipts below come from the first complete A16 pass, before the auxiliary parent lookup index was added. They ran concurrently with other validation on the shared W365 VM and are not isolated throughput measurements. The final allocated and active database sizes are also shown: allocation includes reusable pages from subsequent reprocessing, while active size excludes the freelist. The model cache and venv are outside the database size. Both the initial and final operational receipts are preserved in `indexes.json`.

| Corpus | Embedded units | Initial clean seconds | Initial SQLite MiB | Final allocated MiB | Final active MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| httpx | 1985 | 10.7 | 10.7 | 12.0 | 11.7 |
| vite | 12922 | 68.3 | 74.1 | 80.7 | 78.9 |
| jftp | 13583 | 91.3 | 107.5 | 117.2 | 115.8 |
| django | 67929 | 306.3 | 408.0 | 463.2 | 462.4 |

### Verification and handoff

System Python and `/home/lucas/DEV/Projects/agent-toolbox-eval/venv-core/` each passed the complete `python3 -m unittest discover -s tests -p "test_legacy_*.py"` discovery: 365 tests, with 133 and 13 optional skips respectively. `npm ci` and `npm test` passed all 111 Node tests. The fake timeout line and Python 3.14 unclosed-connection ResourceWarnings in the logs are test diagnostics, not failed checks. Only Linux/WSL was executed. All final evaluator runs have zero errors; absent-name checks are reported separately and do not prove API absence.

Question-set hashes, source hashes, raw per-question metrics and top-ten source ranges are in the compact result directory. The final analyzer-bound correction was checked for token-stream equivalence on every benchmark query before retaining the CLI measurements; the longest query has 14 distinct non-stopword primary terms, so the 32-term boundary is not reached. Full bodies are retained only in the durable evaluation scratch directory. Reproduce the final CLI comparisons with `/home/lucas/DEV/Projects/agent-toolbox-eval/round2/final_eval.py`; its flags select system Python for Tier 0, the parser venv for Tier 1, and the Model2Vec venv for hybrid. The exact index, ablation, CLI smoke, warm-server and test drivers and streaming logs are beside it under `round2/` and `logs/`. The final model route is `index --embed-provider local-python --embed-model minishlab/potion-code-16M-v2 --model-revision e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b --cache-dir <model-cache>` followed by `query --mode hybrid --vector-engine numpy`; `--model-dir` also works without a download grant.

Independent held-out rerun remains with the orchestrator. The report does not extrapolate development hit rates to that set. Commits, pushes, Beads tracking, PRD/ADR updates and installed-skill rollout remain with the orchestrator under the delegate brief. Unrelated analytics, README and embedding-owner changes were preserved.

Owned Herdr workspaces `wNK` (index, CLI and real-server runs), `wNM` (parser and test runs), and `wNN` (ranking trials) are closed. Final foreground checks and explicit descendant audits for the remaining task shells found no background children. `cleanup.json` records the final workspace-list check, with no owned workspace remaining. No worktree was created; existing worktrees and other owners' workspaces were preserved.


## Review fixes

The final fix round verified all 15 GLM findings and all 21 Argon findings. The per-finding verdict/reason/test table is `/home/lucas/DEV/Projects/agent-toolbox/.agent-briefs/reports/i4-fix-round.md`: 32 findings fixed, the documented lexical-symbol compatibility alias confirmed as intentional, and three deferred entries covering overlapping readability work plus the shared `repo_files.py` Git-helper cleanup outside the permitted files. No PRD, ADR, README, unrelated analytics source, installed skill, branch, Git index or project commit was changed by this delegate.

Candidate refresh preserves complete-inventory revisions/triggers and the last full report. It refreshes lexical units offline, deletes obsolete vectors and marks changed files pending; explicit refresh completes those vectors. Embedding coverage is measured per selected library/filter, and incomplete semantic queries fail with `embedding_incomplete` HTTP 409. Exact header source spans cover multiline signatures, leading comments and docstrings before truncated metadata can leak a key prefix. Range expansion also honors overlapping derived-secret redactions, including joined notebook strings. Braceless declarations have bounded spans, fitting outer definitions retain nested symbols/docstrings, and config windows carry nearby key context with a separator and source span. Parser fingerprint revision 2 makes explicit refresh rebuild earlier chunk metadata.

Other verified corrections include old-Git inventory compatibility/deduplication, UTF-8 CLI output under redirected legacy code pages, encoding declarations restricted to prologs, explicit short/non-Latin UTF-16, Markdown fence boundaries, symlinked ancestor canonicalization, empty first-index retries, literal scope paths, bounded path probes and symbol descendant lookup, unreadable-directory accounting, legacy ignore-file comments, scoped include pruning, selected-library evaluator roots, recursive runtime manifests, UTF-8 setup templates and harmless hook invocation outside a project. Re-indexing preserves embedding configuration unless explicitly disabled, and a changed explicit endpoint does not inherit another endpoint's ambient credential binding.

Hybrid keeps exact lexical evidence ahead of dense-only neighbors and rescues leading exact hits from displacement by dense scores on overlapping lexical candidates. It preserves fused order when the default evidence window already contains those hits and applies the existing overlap/per-file rules. Sentence-initial prose verbs no longer create false lowercase symbol anchors; interior UI labels and explicit code references retain their supported behavior. No corpus names, expected ranges or held-out labels enter ranking.

Final development quality is pooled using the unchanged evaluator. Before is the previous final hybrid run; after is the final warm-process run of the existing round-2 driver over the requested pinned `i3-*` indexes.

| Set | N | Lexical hit@5 | Hybrid before hit@5 | Hybrid after hit@5 | Hybrid before MRR | Hybrid after MRR | Exact lexical / hybrid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| dev | 47 | 76.6% | 85.1% | 85.1% | 0.699 | 0.699 | 8/8 / 8/8 |
| dev2 | 68 | 61.8% | 69.1% | 70.6% | 0.507 | 0.512 | 7/7 / 7/7 |

There are zero query errors and no lost previously successful hybrid questions; dev2 gains one cross-file hit. All 15 absent-name checks pass, without claiming proof of absence. The final comparison uses warm processes to check ranking after the last capitalization correction; it does not replace the earlier standalone-CLI latency measurements. Full intermediate CLI receipts are in `/home/lucas/DEV/Projects/agent-toolbox-eval/round2/i4-argon-final/`; final source fingerprints, lexical/hybrid receipts, pooled/per-kind/per-corpus metrics, streaming logs and comparison scripts are in `/home/lucas/DEV/Projects/agent-toolbox-eval/i4/`. Question hashes match the baseline; no held-out question or label was opened. The public reference now reports both development and the orchestrator's held-out headline numbers, marks development optimism, and recommends hybrid with the pinned local Model2Vec model or a suitable existing local endpoint. Setup includes the immutable revision and the warm-serve latency recommendation.

Final checks pass 405 tests in system Python 3.14.4, 405 in `venv-core` Python 3.14.4, and 405 in Model2Vec Python 3.12.15, with 139/57/136 expected optional/native skips. The real cached Potion test passes offline. `npm ci` and all 111 Node tests pass, including workflow filters. The broad Python workflow already covers all legacy tests; the semantic workflow now explicitly includes local-context, embedding and evaluator tests and their filters. `git diff --check` passes. No build was launched and no Windows/macOS execution is claimed.

All four owned Herdr workspaces (`wNZ`, `wP1`, `wP2`, `wN0`) are closed after foreground/descendant audits; cleanup evidence remains in the scratch directory. No worktree was created. The orchestrator retains commits, publishing, tracking and fresh held-out evaluation.

## Large-repository fixes

The large-repository pass fixes discovery, modern declaration extraction, query costs and duplicated FTS bodies. Final source uses chunker revision 6. All six requested full-repository indexes and all twelve development indexes were rebuilt. No hidden question set or held-out labels were opened. Commits, publishing, task tracking and installed-skill rollout remain with the orchestrator.

### Discovery and symbols

Git-visible files under `build`, `bin`, `out`, `dist`, `target` and `obj` are retained; VCS, dependency/cache, explicit-scope and secret filters remain active. Non-Git output-name pruning requires a directory consisting entirely of known generated-output suffixes. `discovery.prunedDirectories` records root ID, path, file count and reason. Git counts cover entries Git actually enumerated. Explicit includes supplement Git inventory instead of replacing it, preserving tracked files covered by ignore rules.

Every final Next.js lane contains all 289 tracked files under `packages/next/src/build/`, including its 278 `.ts` files; the brief's 289 count includes other file types. Payload audits locate `executeAccess` at `packages/payload/src/auth/executeAccess.ts:14` and `combineQueries` at `packages/payload/src/database/combineQueries.ts:8` in both parser tiers.

Tier 0 and Tier 1 recognize direct variable-bound arrow/function expressions, async and typed arrows, multiline parameter lists, named default exports, class arrow fields, exported-object methods and TypeScript type/interface declarations. Go function-valued variables, Kotlin anonymous-function values and Rust const/static declarations, including mutable statics, are covered. Tier 0 balances parameter lists so a parenthesized call followed by an unrelated callback cannot become a function definition; quoted literals remain neutral tokens during scanning. JS/TS call statements such as `await executeAccess(...)` no longer pass the C/Java typed-return declaration scanner. Tier 0 remains conservative source scanning; Tier 1 uses the pinned syntax runtime with its existing fallback behavior.

### Query costs and storage

FTS retrieves a bounded ranked prefix and retains the original path/line/UID tie order, falling back to the full tie breaker when a score tie crosses the cutoff. Path and symbol-descendant lookups use the file-span index. Coverage scoring checks query words instead of allocating every body token, and Unicode folding checks character categories per distinct character. The candidate depth is 300; both the controlled depth trial and the final fresh-index comparisons are retained. Unnamed location/flow queries demote isolated source-comment fragments so new declaration boundaries do not promote detached JSDoc ahead of implementing code; named-symbol and usage queries retain normal evidence.

Warm NumPy queries reuse an exact float32 vector snapshot with validated float64 norms, keyed by database UUID, library generation and filters. One snapshot is capped at 512 MiB per provider, with a streaming fallback above that bound. Automatic engine selection uses this path when NumPy is selected. Coverage counts share the same generation/filter invalidation. Candidate hashes and Git/root freshness checks still run; semantic incomplete-coverage errors still precede model loading. Tests exercise refresh, filter changes, malformed vectors and six-decimal/ascending-ID tie equivalence.

External-content FTS shares the authoritative unit body through a SQLite view; a separate table holds search shadows and is read directly during candidate scoring. Migration is transactional, old format-8 indexes remain readable by the current code, and the new storage fingerprint rejects older writers. On an identical-content Next.js hybrid copy, FTS field checksums before/after are identical and `integrity-check` passes. Storage falls from 1246.1 MiB to 1079.6 MiB, saving 166.5 MiB (13.4%). This control isolates storage savings from the declaration and coverage changes in the complete rebuilds.

### Sequential query measurements

| Corpus | Mode | CLI before s | CLI after s | Warm HTTP before s | Warm HTTP after s |
| --- | --- | ---: | ---: | ---: | ---: |
| payload | lexical | 0.527 | 0.421 | 0.329 | 0.211 |
| payload | hybrid | 2.536 | 2.395 | 1.429 | 0.352 |
| nextjs | lexical | 1.077 | 0.721 | 0.745 | 0.600 |
| nextjs | hybrid | 4.907 | 3.330 | 4.007 | 0.497 |

Each CLI p50 has eight new-process samples: four generic natural-language/identifier queries repeated twice. Lexical CLI uses system Python; hybrid CLI and the real HTTP servers use the Model2Vec venv. Warm HTTP p50 excludes the first request and pools the remaining eleven requests. Timing runs follow completion of this task's indexing/check jobs on the shared W365 VM; OS caches are not flushed. cProfile runs separately from timed requests, covering one-shot CLI and warm handler work. Raw samples, query strings, profiles and interpreter paths are in `before-clean-timings.json`, `after-clean-timings.json` and the adjacent `*-clean-*.prof` files. These are constructed-query development measurements, not hidden-set or reference-laptop latency claims.

### Full-repository index receipts

| Corpus | Lane | Indexed files | Searchable units | Index s | Peak RSS MiB | Before MiB | After MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| payload | t0 | 9616 | 70705 | 142.2 | 102.1 | 337.9 | 308.1 |
| payload | t1 | 9616 | 68245 | 260.8 | 610.4 | 277.2 | 322.3 |
| payload | hybrid | 9616 | 70705 | 246.2 | 197.3 | 433.7 | 400.4 |
| nextjs | t0 | 32556 | 178672 | 385.2 | 180.9 | 980.9 | 784.1 |
| nextjs | t1 | 32556 | 177121 | 598.9 | 394.2 | 928.0 | 914.1 |
| nextjs | hybrid | 32556 | 178672 | 415.3 | 286.8 | 1246.1 | 1017.9 |

All databases are `/home/lucas/DEV/Projects/agent-toolbox-eval/indexes/big2-<corpus>-<lane>.sqlite`. Tier 0 uses system Python, Tier 1 the pinned parser venv, and hybrid uses Tier 0 plus offline `minishlab/potion-code-16M-v2` revision `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b` from the existing cache. GNU time receipts record whole-command wall time and peak RSS. Indexing jobs overlapped on the shared VM; the table is an operational receipt, not an isolated indexing-speed comparison. `indexes.json` also retains active-page sizes, vector counts, status counts, build-directory coverage and symbol audits. Some Tier-1 sizes grow because previously missing declarations now create real units; the identical-content control above separates that effect from FTS body savings.

### Fresh development quality

| Set | Lane | N | Before hit@5 | After hit@5 | Before MRR@10 | After MRR@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| dev | t0 | 47 | 76.6% | 76.6% | 0.664 | 0.671 |
| dev | t1 | 47 | 78.7% | 78.7% | 0.707 | 0.726 |
| dev | hybrid | 47 | 85.1% | 85.1% | 0.695 | 0.701 |
| dev2 | t0 | 68 | 70.6% | 70.6% | 0.513 | 0.522 |
| dev2 | t1 | 68 | 72.1% | 72.1% | 0.528 | 0.528 |
| dev2 | hybrid | 68 | 77.9% | 77.9% | 0.549 | 0.552 |

Before is a complete re-index using the source snapshot saved before this task. The existing archived `i3-*` indexes were unsuitable as the sole baseline: with identical file hashes, Django's `ref/models/querysets.txt` had 119 archived units but 95 units in both fresh snapshots; `django/db/models/query.py` had 251 archived units but 228 in both fresh snapshots. `baseline-audit.json` records the evidence. This prevents attributing earlier chunker changes to these fixes.

The same dev/dev2 question files and unchanged evaluator score both snapshots. Final warm queries use the official adapter's root mapping and verify CLI/warm evidence parity per corpus and lane. Question SHA-256 values are recorded and checked. All previously successful lexical and hybrid questions are retained; hit@5 and MRR@10 do not decrease in any pooled lane/set, and all previously successful exact-symbol questions remain successful. All 15 absent-name cases pass per lane, with zero query errors; this check does not establish API absence. Raw per-corpus and per-question results are in `quality-summary.json` and the `fresh-before-*`/lane JSON files.

### Verification and handoff

| Runtime | Tests passed/skipped | Optional skips | Seconds |
| --- | ---: | ---: | ---: |
| System Python | 431 | 135 | 38.361 |
| Parser venv | 431 | 15 | 116.935 |
| Model2Vec venv | 431 | 131 | 28.931 |

`npm ci` and all 111 Node tests pass with system Node 24.21.0. Loading nvm returned status 3, so the checks explicitly use the installed system runtime. `git diff --check` passes. Only Linux/WSL was executed. The required system/parser suites and the additional real cached-model suite are complete; optional/native skips are reported above. The engine and source snapshots, exact drivers, index receipts, CLI evidence, FTS integrity checks and streaming logs remain under `/home/lucas/DEV/Projects/agent-toolbox-eval/i7/` and `/home/lucas/DEV/Projects/agent-toolbox-eval/logs/i7-*.log`.

Repository changes stay within the permitted local-context modules, legacy tests, retrieval-reference corrections and these requested reports. Scratch drivers and receipts remain in the evaluation workspace. The existing README and analytics work were preserved. The project branch and Git index were not changed; no commit, push, worktree, installed-skill update or production-service change was made. Owned Herdr task workspaces were audited for foreground processes and background/session children, with final cleanup evidence in `cleanup-*.json` and `cleanup.json`; no owned task workspace remains open.


## Rank stability

The final ranking preserves hit@1/5/10 on both development sets in every lane, and improves Tier 1 dev2 MRR@10 from 0.528268 to 0.528472. No positive question loses MRR, no previously successful hit@5 question is lost, and every corpus/lane/set also holds hit@5 and MRR. Across 390 lane/query pairs, duplicate-file slots in the top five fall from 513 to 503, import-only slots from 17 to 0, and header-only slots from 1 to 0. These are development results, without a claim about unseen questions.

The retained rule runs after fusion: a second unit yields to an unseen file only within a 0.5% score margin, a third within 1%, and only when the unseen file has at least equal query-term coverage. Exact symbol/path rows are exempt. The existing exact-window rescue, hybrid lexical fence, 80% overlap removal and three-results-per-file cap remain active. Overlap removal precedes diversity counts, and assembly checks only the at-most-three selected siblings of that file. Raw scores, source ranges, unit IDs, source verification and budget packing retain their existing contracts.

Pure import/header fragments receive a 0.5 score multiplier unless they carry exact symbol/path evidence. The conservative detector handles Python imports/module strings/comments, JS/TS static imports, require declarations and re-export barrels, plus common package/import/using/use/include forms and source-comment headers. It retains executable, incomplete and unsupported fragments rather than guessing. New development ablations are --ablate preambles and --ablate diversity. Chunking, parser fingerprints, storage and embeddings are unchanged, so all existing big2 indexes remain valid; no big3 or Payload/Next.js rebuild is required.

| Set | Lane | Positive N | hit@1 before/after | hit@5 before/after | hit@10 before/after | MRR@10 before/after | Import-only top-5 before/after | Header-only top-5 before/after | Duplicate slots before/after |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dev | t0 | 47 | 61.7% / 61.7% | 76.6% / 76.6% | 78.7% / 78.7% | 0.670745 / 0.670745 | 2 / 0 | 0 / 0 | 78 / 76 |
| dev | t1 | 47 | 68.1% / 68.1% | 78.7% / 78.7% | 80.9% / 80.9% | 0.726064 / 0.726064 | 4 / 0 | 0 / 0 | 78 / 76 |
| dev | hybrid | 47 | 61.7% / 61.7% | 85.1% / 85.1% | 89.4% / 89.4% | 0.700709 / 0.700709 | 1 / 0 | 0 / 0 | 76 / 74 |
| dev2 | t0 | 68 | 39.7% / 39.7% | 70.6% / 70.6% | 77.9% / 77.9% | 0.521936 / 0.521936 | 4 / 0 | 0 / 0 | 88 / 86 |
| dev2 | t1 | 68 | 39.7% / 39.7% | 72.1% / 72.1% | 77.9% / 77.9% | 0.528268 / 0.528472 | 5 / 0 | 0 / 0 | 92 / 90 |
| dev2 | hybrid | 68 | 38.2% / 38.2% | 77.9% / 77.9% | 83.8% / 83.8% | 0.551937 / 0.551937 | 1 / 0 | 1 / 0 | 101 / 101 |

Positive denominators are 47 for dev and 68 for dev2. Import/header and duplicate-slot counts include the 15 absent-name questions per lane, giving 390 total lane/query pairs and 345 positive pairs. All absent-name checks pass, with zero query errors. Baseline and final use the same twelve big2-<corpus>-<lane>.sqlite indexes for httpx/vite/jftp/django, the unchanged score_question/summarize evaluator, limit 10 and official adapter root mapping. Every standalone CLI lane/corpus matches warm-engine unit order, text, ranges and scores in twelve additional parity checks. Question SHA-256 values match before and after.

The vector cache is an in-memory snapshot of the original float32 BLOB bytes with float64 norms, not an int8 or disk sidecar. Across all 130 development queries, cached and exact NumPy scans have identical top-300 IDs/order and six-decimal scores; the largest raw floating-point difference is 7.77e-16. A separate hybrid rerun with the exact BLOB scanner produces identical result-unit order and metrics for all 130 queries on the final source. The cache is retained without a storage or normalization change.

Wider diversity rules were rejected. Unconditional 10%/25% penalties lower hit@5 or MRR in at least one lane/set. A coverage-guarded 1% rule passes the pooled gate but moves one Tier 1 dev2 answer from rank 8 to 9; the retained 0.5% rule avoids that loss and still reduces duplicate slots. Trial receipts, including rejected profiles, are retained rather than presenting the final margin as independently validated.

| Runtime | Tests run | Optional skips | Test seconds |
| --- | ---: | ---: | ---: |
| System Python | 444 | 136 | 27.175 |
| Parser venv | 444 | 16 | 85.441 |
| Model2Vec venv | 444 | 131 | 27.092 |

All three full Python discoveries pass, each running 444 tests with the skips above and including 13 new regressions; NumPy-specific coverage executes in the Model2Vec venv. npm ci and all 111 Node tests pass, and git diff --check passes. The fixture timeout diagnostic in the Python log is expected test output. Only Linux/WSL was executed. Regression cases cover source-language preambles and executable lookalikes, URL/comment handling, near ties and strong-score exceptions, query-coverage protection, exact symbol/path protection, overlapping units, root identity, hybrid lexical fencing, budgets and float32 score/order parity across multiple batches.

Durable drivers, raw per-corpus/per-question before/after results, source/question hashes, vector controls, CLI receipts, tests and cleanup evidence are under /home/lucas/DEV/Projects/agent-toolbox-eval/i8/. Key receipts are quality-summary.json, vector-audit.json, exact-parity.json, cli-parity.json, provenance.json, checks.json, eval-final.log and checks.log. The original implementation snapshot is before-source/local_context/, and the superseded 1% final receipts are under one-percent/. The delegate report is /home/lucas/DEV/Projects/agent-toolbox/.agent-briefs/reports/i8-rank-stability.md.

Only local_context/search.py, local_context/assemble.py, local_context/cli.py, tests/test_legacy_rank_stability.py and the two requested reports were changed by this delegate. Existing README and analytics changes were preserved. No hidden/held-out question directory was opened, no commit/push/branch/index/worktree change was made, and no installed skill was updated. The orchestrator retains tracking, documentation approval, review and publishing. Owned Herdr workspaces wQ3 and wQ4 were closed after foreground, descendant and session-process audits; cleanup.json records the final workspace inventory with no owned workspace left open.
