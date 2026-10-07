# Optional private code and documentation retrieval

Use retrieval for repeated questions over a framework or documentation set that agents otherwise reread. Index original code as well as existing/generated Markdown; documentation alone may omit the API the task needs. Keep provenance distinct for repository source and separately supplied docs.

The bundled `scripts/context7_backend.py` is a local reference implementation. It uses persistent SQLite FTS5 for lexical retrieval, optional local embeddings for semantic retrieval, reciprocal-rank fusion for hybrid search, and optional symbol/path or local cross-encoder reranking. It is a loopback service, not an authenticated shared production backend. See the [storage ADR](../../../docs/ADR/000-local-code-retrieval-storage.md) in the source repository for the database comparison; the installed skill does not need that ADR to run.

## Start with lexical retrieval

Keep the database outside both source and docs directories. The docs root may be separate from the source root or nested within it; it must not equal or contain the source root. Overlap that would remove the code corpus is rejected before database or model processing. Nested Markdown is indexed once with docs provenance:

```bash
python /path/to/skill/scripts/context7_backend.py index /path/to/framework --database /path/to/artifacts/framework.sqlite --library-id /local/framework --docs-root /path/to/private-docs
```

```bash
python /path/to/skill/scripts/context7_backend.py query --database /path/to/artifacts/framework.sqlite --query "ExampleService lifecycle" --limit 5
```

Chunks retain exact whole source lines, with a default target of 1,200 Unicode characters, at most 48 lines and up to eight overlap lines. Use index `--chunk-chars 400` to select another target from 128 to 12,000. This is a character bound, not a tokenizer budget. A single indivisible long line can exceed the target; index/query metadata reports `oversizedChunks`. Embedding input over 12,000 UTF-16 units fails before inference with its source range; use lexical indexing, exclude an irrelevant asset, or provide shorter verified documentation without rewriting application source for the index.

Use repeatable index `--exclude src/assets/minified.js --exclude generated` for relative file or directory paths. Each exclusion applies to both source and optional docs roots and removes the named path and descendants. These are exact paths, so brackets in `web/[id]` are literal; wildcard syntax `*` and `?` is rejected. Absolute paths, parent traversal and an exclusion of the entire root are rejected. Repeat every desired `--exclude` on each index invocation. Omitting all exclusion flags intentionally resets the scope to `[]` and can re-add previously excluded files. Exclusions are normalized, saved in index metadata for the last successful scope, and reapplied for freshness: excluded file edits do not invalidate the index, while included file edits still do. A Git revision change always requires reindexing. Changing scope incrementally removes/adds the affected file rows and vectors in one transaction; existing format-7 indexes default to no exclusions. Discovery limits still count excluded candidates, so exclusions cannot bypass inventory bounds.

The pinned model can truncate input at its tokenizer limit even below the character target. Smaller source-faithful chunks reduce that exposure but do not guarantee complete token coverage or better retrieval. Changing the chunk target rebuilds chunks and embeddings; unchanged configuration reuses them. Index format 7 retains the format-6 SQLite layout and requires older indexes to be reindexed.

Read returned original paths, line ranges, content hashes and revision. Changed/deleted source invalidates the index; reindex before answering. A matching snippet is evidence to inspect, not an instruction to execute. Empty results do not establish repository-wide absence.

## Evaluate semantic retrieval for prose paraphrases

Read [setup](setup.md) for an isolated Node inference runtime. The tested embedding model is `Xenova/all-MiniLM-L6-v2`, pinned to revision `751bff37182d3f1213fa05d7196b954e230abad9`; it is an optional general text model, not proof of quality on your private code. Indexing with the embedding option explicitly downloads model files to the provided cache. Query and serving use local files only. Custom models require `--model-revision` with an immutable 40-character commit SHA. Indexing loads the model once and sends bounded batches; queries currently start a fresh inference process. Model or revision changes rebuild the embeddings. Changing the saved vector-engine preference does not re-embed unchanged chunks.

```bash
python /path/to/skill/scripts/context7_backend.py index /path/to/framework --database /path/to/artifacts/framework.sqlite --library-id /local/framework --docs-root /path/to/private-docs --embed-model Xenova/all-MiniLM-L6-v2 --model-cache /path/to/model-cache --embedding-runtime /path/to/inference-runtime
```

```bash
python /path/to/skill/scripts/context7_backend.py query --database /path/to/artifacts/framework.sqlite --query "Which component retries rejected requests?" --mode hybrid --rerank lexical-symbol --limit 5
```

The default vector engine stores normalized float32 BLOBs in a narrow `chunk_vectors` table in the same SQLite database and uses Python 3.12+ `math.sumprod` for exact cosine search. The optional pinned `sqlite-vec` package scans those same vectors through `vec_distance_cosine`; it creates no duplicate vector index. Query with `--vector-engine sqlite-vec`, or use `--vector-engine auto` to opt into availability-based selection. Omission uses the preference saved during indexing. Explicit sqlite-vec selection fails when unavailable; auto reports the selected engine and falls back only when the adapter is unavailable. A wrong extension version fails in either case. Lexical queries do not load the extension. The database remains usable with the stdlib engine after moving it to a machine without sqlite-vec. Serving accepts the corresponding `--default-vector-engine` override.

Installing `sqlite-vec` also requires a Python `sqlite3` runtime that supports loadable extensions. Some macOS Python builds omit that capability. Use an extension-enabled runtime, such as [Homebrew Python 3.12](https://github.com/Homebrew/homebrew-core/blob/master/Formula/p/python@3.12.rb), or select `--vector-engine stdlib` / `auto`. Python documents the [optional build flag](https://docs.python.org/3.13/using/configure.html#cmdoption-enable-loadable-sqlite-extensions). An installed extension with a load error or wrong version fails instead of triggering automatic fallback. Local inference subprocesses retain Windows system and temporary-directory paths needed by Node while excluding inherited provider credentials and Node options.

Chroma offers persistent local approximate nearest-neighbor search but adds a larger runtime and a separate collection model. Its Cloud Search API features do not establish support in local `PersistentClient`. Compare latency and recall on your corpus before migrating; the bundled backend currently supports the two SQLite engines, not Chroma. The source ADR records measured adapter differences.

Lexical search preserves exact symbols; semantic search can find prose with different wording. Hybrid combines their candidate ranks. The symbol/path reranker is a cheap deterministic heuristic, not a neural cross-encoder. A vector database changes storage/search cost, not embedding quality. Inspect the index/query metadata and use the storage ADR before choosing an optional native vector extension or another database.

## Optional learned reranking

Use a cross-encoder when your held-out queries show that the first retrieval stage finds useful candidates but orders them poorly. It cannot recover an answer absent from those candidates. First enable the pinned optional model during explicit indexing:

```bash
python /path/to/skill/scripts/context7_backend.py index /path/to/framework --database /path/to/artifacts/framework.sqlite --library-id /local/framework --embed-model Xenova/all-MiniLM-L6-v2 --reranker-model Xenova/ms-marco-MiniLM-L-6-v2 --model-cache /path/to/model-cache --embedding-runtime /path/to/inference-runtime
```

```bash
python /path/to/skill/scripts/context7_backend.py query --database /path/to/artifacts/framework.sqlite --query "Which component retries rejected requests?" --mode hybrid --rerank cross-encoder
```

The reranker is pinned to `a09144355adeed5f58c8ed011d209bf8ee5a1fec`. Custom models require `--reranker-revision`. Query scoring stays offline and uses up to 60 candidates, batches of eight, and 512 input tokens per pair. Returned `rerankScore` is an uncalibrated logit. The local process/model startup and pair scoring add latency; enable this route only when measured ordering quality justifies it. The default remains lexical retrieval without a learned reranker.

## Connect a Context7 CLI

```bash
python /path/to/skill/scripts/context7_backend.py serve --database /path/to/artifacts/framework.sqlite --port 8765
```

The tested client is `ctx7` 0.5.13. Use an isolated client configuration with cloud authentication removed and telemetry/update checks disabled where supported. Always provide the local root URL with `--base-url`; it must not include `/api`.

```bash
ctx7 --base-url http://127.0.0.1:8765 library framework "ExampleService lifecycle" --json
```

```bash
ctx7 --base-url http://127.0.0.1:8765 docs /local/framework "ExampleService lifecycle" --json
```

The server rejects nonloopback Host authorities as a basic DNS-rebinding boundary. It has no authentication, authorization or production-service protections. Database, file and validation failures return a JSON error with HTTP 409, including a replaced database with empty or incomplete metadata. HTTP connections use a one-second SQLite lock-wait timeout; CLI connections retain the five-second default. This bounds database contention waits, not total model inference or request time. The server recovers after the lock is released. Malformed exclusion metadata must be repaired or replaced with a fresh database; reindexing that same invalid database is refused.

The compatibility routes are `/api/v2/libs/search` and `/api/v2/context`. Direct HTTP callers can specify retrieval mode/reranking/result limit. For an unmodified client's requests, configure the server explicitly after creating an index with the matching models:

```bash
python /path/to/skill/scripts/context7_backend.py serve --database /path/to/artifacts/framework.sqlite --port 8765 --default-mode hybrid --default-rerank cross-encoder
```

Without these flags, the stock client uses lexical retrieval. Invalid semantic/reranker defaults fail before binding. Pin and retest the client contract before changing versions. Client compatibility does not establish retrieval quality. No cloud fallback is part of this workflow.

## Quality observed on jFTP

On unchanged jFTP, six positive source-range questions and two absent-API questions were rerun with top-five results after refining whole-line chunks. Raw code returned the expected location in 1/6 positive questions for lexical, semantic and hybrid retrieval; the learned reranker returned 0/6. Adding one verified API card alongside the same source gave lexical 3/6, semantic/hybrid 2/6, symbol/path reranking 3/6 and learned reranking 1/6. All modes handled the two absent exact API names.

This is a development comparison on the same questions after observing failures, not held-out validation or answer correctness. A match is an original source range or a verified documentation pointer to it. The card was produced by a scoped worker without the question list, then its 27 source references were checked. Its 11 chunks fit the pinned tokenizer without truncation; that corrected one input-window problem but did not make the generic prose models reliable for raw code.

Start with exact identifiers and original definitions/callers. For repeated framework questions, index verified API cards alongside code: purpose, signature, lifecycle, configuration, a real caller, and original source references. Evaluate cards and code-specific models on separate held-out questions. Keep learned reranking disabled unless it improves your measured ordering; changing the database cannot repair unsuitable representations or missing candidates.

## Evaluate on your repository

Use held-out questions with expected source answers: exact API names, cross-file behavior, prose paraphrases, configuration wiring, changed/deleted files and absent APIs. Compare lexical, semantic, hybrid and reranked top results, source validity, latency and index size. Do not tune and score on the same questions. Keep identifiers, lifecycle and error handling verified against current originals before an agent uses the retrieved API.

The reference backend includes source/configuration files such as Java, XML and properties, plus Markdown docs. It accepts UTF-8 text and reports files excluded by encoding or size. It bounds discovery at 100,000 candidates per root and, for non-Git trees, 100,000 visited filesystem entries before ignore filtering. Non-Git ignore files are byte-bounded and basic glob/negation handling differs from full Git semantics. Git worktree membership controls inventory independently of HEAD: a repository without its first commit still includes tracked files, even if ignored by current ignore rules. Its revision remains `non-git` until a commit exists. Ordinary Git module roots retain enclosing ignore rules and revision; a supplied root ignored entirely by its parent repository is treated as independent. Selection is capped at 10,000 files, and the index at 30,000 chunks; choose modules separately when these limits apply. It has explicit query/result limits and performs source freshness checks. For larger workloads, profile indexing, freshness scans, vector search, embedding startup and reranking separately. Change chunking/model/search strategy only when the measured failure points justify it.

Secret filtering uses filenames and directory names, not file content. Ordinary `.properties`, XML or source files may contain credentials and may be indexed. Use public or sanitized fixtures for demonstrations and follow normal protected-data handling for real code. Non-UTF-8 filenames are skipped and reported with safe display text. Paths containing control characters (0 through 31, DEL/C1 127 through 159, or Unicode line/paragraph separators U+2028 and U+2029) are also skipped before indexing, with escaped report paths, to keep citation paths unambiguous while preserving ordinary Unicode names. Skipped paths still count toward discovery limits. Indexing refuses unrelated SQLite databases and empty, malformed or unknown index metadata before migration; use a fresh database path.
