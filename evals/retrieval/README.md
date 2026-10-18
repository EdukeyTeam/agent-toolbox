# Retrieval development evaluation

The corpus manifest pins public snapshots. Question sets are development data, not held-out validation. Each inclusive one-based expected range was checked against the specified snapshot. Do not read a held-out set when developing an engine against these questions. Corpora, caches and indexes belong outside this repository. The course fork URL for jFTP is necessary to reproduce its agent-written documentation; the original upstream alone is not equivalent.

The stdlib harness ships at `skills/legacy-codebase-workflows/scripts/eval_retrieval.py`. Run its `--help` for the complete adapter contract, scoring policies and CLI. It accepts Python 3.12+ and requires no inference dependencies itself. The bundled backend additionally needs SQLite FTS5. Index every corpus with its docs directory and use default chunking for this baseline. Never write an index under the source tree.

```sh
python skills/legacy-codebase-workflows/scripts/context7_backend.py index /external/corpora/httpx --database /external/indexes/httpx.sqlite --library-id /eval/httpx --docs-root /external/corpora/httpx/docs
```

```sh
python skills/legacy-codebase-workflows/scripts/eval_retrieval.py evals/retrieval/questions/httpx.dev.jsonl --engine context7-backend --database /external/indexes/httpx.sqlite --json-output /external/results/httpx.json --markdown-output /external/results/httpx.md
```

Use `--mode semantic` or `--mode hybrid` only after indexing with the optional pinned embedding model and isolated Node runtime described in the skill's retrieval setup. Add `--rerank lexical-symbol` for the deterministic symbol/path reranker. Pass `--corpus-root /external/corpora/django` if indexing subtrees, so source citations still match the corpus-relative labels. Nested docs provenance is rebased automatically; separately supplied external docs use the `@docs/` namespace.

For a different engine, provide `--engine command` and an argv template with `{query}` and `{limit}`. The harness substitutes after splitting the template, never through a shell. Prefer `--command-json` with a JSON array on Windows or when quoting is complex. The command must emit a JSON object with a `results` array; each result has a corpus-relative `path`, inclusive `startLine` and `endLine`, and original `text` beginning on `startLine`. Only the first ten returned results are evaluated. Add a Python adapter implementing `search(query, limit) -> list[Result]` for tighter integration; scoring and reporting stay unchanged.

```sh
python skills/legacy-codebase-workflows/scripts/eval_retrieval.py evals/retrieval/questions/httpx.dev.jsonl --engine command --command 'my-engine query --query {query} --limit {limit}' --json-output /external/results/custom.json --markdown-output /external/results/custom.md
```

Question JSONL requires `id`, `corpus`, `kind`, `question` and `expected`; these sets also supply explanatory `notes`. Kinds are `exact-symbol`, `concept`, `paraphrase`, `config`, `docs-howto`, `cross-file` and `absent`. Expected items contain `path`, `start` and `end`. Absent questions use `expected: []` and `absentIdentifier`; the extra field makes the exact-token test unambiguous for natural-language questions. A single-token absent question can omit the field. Blank or malformed lines, duplicate IDs and invalid ranges are rejected with line numbers.

Hit@1/3/5/10 and MRR@10 use the first same-path inclusive range overlap, after normalizing path separators and dot segments. Path case is preserved. Recall@10 averages the fraction of expected ranges overlapped in each positive question; micro range recall weights all expected ranges equally. An overlap can cover only one line and is not proof of a complete answer. Cross-file questions therefore also need range recall, not just hit rate.

The default budgets are 2,000 and 5,000 estimated tokens using `ceil(chars/4)`. Fill the first ten results in order, keeping a character prefix of the final result. Text alone is charged, without metadata or separators. No chunks are deduplicated. Budget hit and range recall use only source lines that contribute characters to the returned prefix. Character precision is the returned-character fraction inside the union of expected ranges; overlapping labels never double-count characters. Duplicate returned text costs budget again. Zero returned characters have precision zero. Summary budget coverage and precision weight each positive question equally. These are approximate context metrics, not tokenizer measurements.

Absent success means none of the top-five result texts contains the case-sensitive identifier as a full token (Unicode word characters and `$` delimit identifiers). Empty retrieval passes, so this metric is deliberately weak: it measures exact-identifier contamination, not justified abstention. Absent questions are excluded from all positive retrieval averages. Query errors count as misses and failed absence, are saved per question, and make the CLI exit 1 after writing both reports. Input/configuration errors exit 2. Query latency includes subprocess startup and backend freshness scans; p50 and p95 use nearest-rank percentiles across all questions, including absent queries and errors. Runs are sequential, single pass, with no warmup excluded.

Raw baseline reports retain full questions, results, errors, timings and scoring configuration. Index receipts retain the exact command, elapsed wall time, SQLite file bytes, skipped-file details and backend metadata. See `docs/retrieval/baseline.md` for the measured environment, quality findings and limitations.
