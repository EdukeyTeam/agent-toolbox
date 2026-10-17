# Private retrieval usage

The bundled local retrieval engine (`scripts/context7_backend.py`, backed by the `scripts/local_context/` package) indexes a repository's source and documentation into one SQLite database and answers natural-language and exact-symbol questions with budgeted, source-cited snippets. It runs entirely on the machine, works offline in lexical mode, and complements direct search, repository maps, Repomix packs and code graphs rather than replacing them.

One-time installation, consent gates, air-gapped setup and Windows/WSL notes are in [retrieval setup](retrieval-setup.md). Wiring a project with a launcher, pinned clients and refresh hooks is described in [local Context7 setup](local-context7-setup.md). This reference covers everyday usage.

## Concepts

**Libraries.** A library is a named, indexed corpus (`--library-id /local/name`) built from one code root plus optional docs roots (`--docs-root`, repeatable); a docs-only library omits the code root. One database can hold several libraries, queried independently with no cross-contamination. A query targets exactly one library: `--library-id` is required when the database holds more than one, while `resolve --library-name` searches all libraries. Changing a library's root set requires a new library ID. Keep the database outside every indexed root.

**Units.** Indexing produces typed units: code definitions and blocks, document sections and their fenced code blocks, config groups, notebook cells, and fallback windows for unknown formats. Every returned snippet cites library, root, relative path, inclusive line range, content SHA-256, revision and code/docs provenance; code snippets carry an enclosing signature or scope header, doc snippets a heading breadcrumb.

**Channels.** Lexical queries (the default) combine exact symbol, path, full-text BM25 and a stemmed shadow channel, fused with deterministic reciprocal-rank fusion and small priors (test, vendored, generated and minified paths down-weighted; doc how-to wording boosted). Semantic mode adds a dense vector channel, hybrid uses both; both require explicitly enabled embeddings. `--explain` adds channel ranks to the response; `--ablate <feature>` is for development comparisons.

**Freshness.** Each query checks a cheap per-root trigger (Git HEAD and `.git/index` mtime, or the root directory mtime for non-Git trees) and verifies the files behind its candidates. `--refresh auto` (the default) updates a small changed candidate set's lexical evidence without embedding documents; vectors for changed files remain pending until explicit `refresh`. Candidate refresh preserves the last complete inventory revision and its change triggers, so a changed repository still carries a refresh warning. Larger changes return visibly stale snippets with an instruction to run `refresh`. `--refresh off` never writes; `--refresh strict` fails on any difference. Stale content is never returned as current without a flag.

**Budgets.** `--tokens` bounds the emitted evidence (header, description, body and citation) as `ceil(characters/4)`, supported 256..32,000. The CLI applies a budget only when `--tokens` is given; the served API defaults to 4,000. Items that do not fit become contiguous whole-line excerpts with corrected citations, or are omitted with a count and an expand hint; exact `expand` is all-or-error.

## Everyday commands

```bash
python /path/to/skill/scripts/context7_backend.py index /path/to/repo --database /path/to/indexes/repo.sqlite --library-id /local/repo --docs-root /path/to/repo/docs
```

```bash
python /path/to/skill/scripts/context7_backend.py query --database /path/to/indexes/repo.sqlite --library-id /local/repo --query "Where are retries configured?" --tokens 2000 --format text
```

```bash
python /path/to/skill/scripts/context7_backend.py expand --database /path/to/indexes/repo.sqlite --library-id /local/repo --path src/retry.py --root-id r0 --start-line 10 --end-line 40
```

```bash
python /path/to/skill/scripts/context7_backend.py refresh --database /path/to/indexes/repo.sqlite --library-id /local/repo
```

`query` accepts `--mode lexical|semantic|hybrid` (default lexical), `--rerank lexical-symbol|cross-encoder` (`lexical-symbol` is a compatibility alias of the lexical pipeline; `cross-encoder` returns a clear not-supported error in v1), `--vector-engine`, `--limit` (default 5, range 1..50), `--tokens`, `--refresh auto|off|strict`, `--format json|text|context7-json` (default native JSON), `--kind code|docs`, `--language`, `--explain` and `--ablate`. Query text is 1..8,000 characters; only the first 32 terms are analyzed.

`index` accepts `--library-id` (required), `--docs-root`, `--title`, `--description`, `--chunk-chars` (default 1,500 non-whitespace characters, range 128..12,000), repeatable `--exclude` and `--include` exact relative paths, `--encodings`, `--parser auto|0|1`, `--no-secret-scan`, soft `--max-files`/`--max-units` (default unbounded), `--max-file-bytes` (default 2,000,000), `--discovery-limit` (default 2,000,000), `--jobs`, the embedding flags described in [retrieval setup](retrieval-setup.md) and `--vector-engine`. Omitting every `--exclude` on a new index invocation intentionally resets the exclusion list; `refresh` always reuses the saved scope. Re-running `index` for an existing library is incremental and atomic: a failed run leaves the previous index in place.

`refresh` accepts `--library-id` (optional only for a single-library database), `--all`, `--verify-all` (full hash audit) and `--jobs`. It prints a per-file added/changed/removed report; a commit that changes no file contents updates only revision metadata. `expand` takes `--unit-id`, or `--path` with `--root-id`, `--start-line` and `--end-line` (at most 2,000 lines, always the live verified source). `status` reports per-library counts, roots, revisions, parser tier, embedding coverage and scan policy. `resolve` ranks local libraries by exact ID, then casefolded title/ID token and description matches.

## Languages, formats and symbol honesty

Lexical retrieval works for any text language. Structure comes from the Python AST, Tier-0 declaration recognizers (C/C++, Java, C#, JavaScript/TypeScript, PHP, Go, Rust, Kotlin, Swift, Dart, VB, Pascal/Delphi, SQL, PL/SQL, T-SQL, COBOL, shell, PowerShell, Perl, R and others), and, with the pinned tree-sitter packages installed, Tier-1 grammars (`--parser 1`; `auto` selects Tier 1 only when exactly the pinned versions are importable, and per-grammar failures fall back). Symbol names, signatures and scope chains are best effort outside Python: generic splitting works everywhere, but treat metadata as a navigation aid, not language-server accuracy.

Documentation formats are Markdown, MDX, reStructuredText (including `.txt` files with RST adornments), AsciiDoc, HTML and plain text; fenced code blocks are searchable next to their explanatory prose with a heading breadcrumb. Notebooks (`.ipynb`) index cell sources without executing anything. Config files (JSON, TOML, YAML, XML, properties, Gradle, SQL schema) use generic block/window chunking with key context in the header. HTML is parsed, never fetched or rendered.

## Encodings

Decoding honors declared encodings first (Python coding cookie, XML declaration, HTML meta charset), then BOM-aware UTF-8 and UTF-16, then the `--encodings` list in order, then cp1252, then latin-1 as a marked assumption. UTF-16 without a BOM is detected from its NUL pattern; text with more than 2% control characters counts as binary. Pass `--encodings cp1250` for Central European codebases or `--encodings cp037` for EBCDIC; the index report lists files that fell back to an assumed encoding. `.properties` files try UTF-8 then ISO-8859-1.

## Large files, excludes and includes

Textual files larger than `--max-file-bytes` are window-chunked up to 20 MiB and reported as split; only binaries and files above 20 MiB are skipped, with reasons in the index report. Default-excluded directories (`.git`, `.svn`, `CVS`, `.hg`, `node_modules`, `__pycache__`, `.venv`, `venv`, `target`, `dist`, `build`, `bin`, `obj`, `out`, `.gradle`, `.idea`, `.vs`, `.next`, `.cache`) are pruned during discovery and do not count toward the 2,000,000-entry discovery bound; exceeding that bound aborts with counts instead of silently truncating. `--exclude` takes exact relative file or directory paths (wildcards are rejected); `--include` re-adds Git-ignored or default-excluded paths such as generated API stubs. Secret-named files and directories are always excluded and reported.

## Secret scanning

Default content scanning recognizes PEM private-key blocks and strict provider key formats (AWS `AKIA...`, `ghp_`/`github_pat_`, `xox[abp]-`, realistic-length `sk-` keys); affected units are stored path-only and flagged, so the secret text is not retrievable through queries or expansion. Generic `password=`/`token:` assignments are not redacted. `--no-secret-scan` turns the content scan off as a saved per-library policy and forces reprocessing; filename filtering always stays on. No scanner promises to find every credential.

## Connect a Context7 client

```bash
python /path/to/skill/scripts/context7_backend.py serve --database /path/to/indexes/repo.sqlite --port 8765
```

Routes are `/api/v2/libs/search?libraryName=...`, `/api/v2/context?libraryId=...&query=...&type=txt|json&tokens=...`, `/api/v2/local/expand` and `/api/v2/local/status`. The service binds `127.0.0.1` only, rejects non-loopback Host authorities, has no authentication and is intended for one user on one machine. Stock clients use the server defaults, so configure `--default-mode`, `--default-rerank`, `--default-vector-engine`, `--tokens` and `--refresh` on `serve` for them.

The tested client is the pinned `ctx7` CLI 0.5.13, pointed at the local service with a base URL without `/api`:

```bash
ctx7 --base-url http://127.0.0.1:8765 library repo "retries"
```

```bash
ctx7 --base-url http://127.0.0.1:8765 docs /local/repo "Where are retries configured?" --json
```

The official Context7 MCP server 4.0.3 works unmodified when its API URL override points at `http://127.0.0.1:<port>/api`; the [setup generator](local-context7-setup.md) wires this end to end. Keep an isolated client configuration, do not reuse cloud credentials, and expect no cloud fallback: an unresolvable local library is an error, not a redirect to the hosted service.

## Evaluate on your own repository

Author a JSONL question set: one object per question with the question text and expected corpus-relative path/line ranges; use `expected: []` plus an `absentIdentifier` field for absent APIs. Then run the shipped harness against an existing index:

```bash
python /path/to/skill/scripts/eval_retrieval.py /path/to/questions.jsonl --engine context7-backend --database /path/to/indexes/repo.sqlite --json-output /path/to/result.json --markdown-output /path/to/result.md
```

It reports hit@1/3/5/10, MRR@10, recall, character precision under `--budgets 2000 5000` and latency percentiles. `--mode` and `--rerank` select the engine configuration; `--engine command --command 'engine --query {query} --limit {limit}'` evaluates any external engine that prints the JSON result shape. Keep tuning questions separate from scoring questions. Empty retrieval can pass the weak absent-API check; it does not demonstrate justified abstention or prove the API absent.

## Measured quality

Development numbers are optimistic: the first round reached 76.6% hit@5 on 47 positive development questions against a 46.8% baseline, but only 50.0% on independent held-out questions. The second round reached 76.6% stdlib lexical, 78.7% tree-sitter lexical and 85.1% hybrid hit@5 on that development set; on the independent 68-positive dev2 set it reached 61.8%, 64.7% and 69.1%, respectively. These are tuning measurements over httpx, vite, jFTP and Django, not estimates of unseen-repository accuracy.

The independent held-out run has 68 source-range questions plus 6 absent-API checks. Held-out hit@5 was 48.5% for the old backend, 57.4% for the new stdlib lexical engine, 63.2% with tree-sitter and 70.6% for hybrid with Model2Vec `minishlab/potion-code-16M-v2`. Hybrid improved concept, paraphrase and documentation retrieval, but the measured pre-review version lost 2 of 15 exact-symbol hits that lexical retained. Exact symbol/path evidence now retains lexical priority during hybrid fusion; a fresh held-out run remains separate from development verification. Small per-kind samples make one-question differences noisy. The source repository records the full methodology in `docs/retrieval/heldout-results.md`.

Recommend hybrid when the user accepts the one-time local Model2Vec runtime/model download, or already has a suitable local embedding endpoint; lexical remains the zero-download default. Use a warm `serve --default-mode hybrid --default-vector-engine numpy` process to avoid loading the model for every query. The measured pre-review hybrid CLI p50 was about 1.6-2.5 seconds by corpus; warm-server development p50 was about 0.2-1.0 seconds. These shared-VM measurements do not certify reference-laptop latency or universal quality gains.

## Limitations

Tier-0 symbol names, signatures and scope chains are heuristic outside Python, and Tier-1 metadata is best effort per grammar; neither is language-server accuracy. The learned cross-encoder reranker is not supported in v1. Config files use generic block/window chunking; HTML units contain safely extracted text with the raw file as envelope; notebook units carry transformed cell text with approximate line mapping. Queries verify only their candidate files and cheap root triggers, so files added outside the candidate set need an explicit `refresh`, and Git triggers cannot detect every unstaged nested addition. Empty results are not proof of absence. A 10,000-file incremental refresh and a 200,000-file index have not been certified; large corpora may stop with explicit resource errors, never silent truncation. One code root per library; root changes require a new library ID. The loopback service is unauthenticated and single-user. Freshness is inventory-stat-plus-hit-hash, not a cryptographic proof of the whole tree.
