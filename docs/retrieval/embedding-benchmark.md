# CPU embedding benchmark and provider implementation

**Final handoff with explicitly partial Jina measurements, as directed by the orchestrator.**

Date: 2026-10-17. Development proxy only; no held-out questions were opened. Raw measurements and per-question first-hit ranks are in [`evals/retrieval/results/embeddings/`](../../evals/retrieval/results/embeddings/).

## Recommendation

Use **Model2Vec 0.10.0 with `minishlab/potion-code-16M-v2`**, revision `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b`, as the optional local-Python default. Keep provider `none` as the system default. Potion has 256 dimensions and an MIT license; its current model card supersedes the older potion-code-16M. This recommendation applies to CPU code/docs retrieval in a warm process and the development proxy below, not a claim about unseen questions or full engine acceptance. [Model card](https://huggingface.co/minishlab/potion-code-16M-v2), [Model2Vec](https://github.com/minishlab/model2vec).

## Measurement completeness

Potion and BGE completed all three corpora and 39 questions each. Jina completed HTTPX only (532 windows, 13 questions). At 22:47 UTC, the orchestrator terminated its Vite run with SIGTERM (exit 143) for time and CPU contention and explicitly requested finalization with the Potion recommendation. The last logged Vite progress was 2,400 of 4,499 windows after 3,110.28 seconds (51.84 minutes); no Vite quality metrics were produced, and JFTP was not started. This was an operator stop, not a successful full run or a demonstrated model crash. The full three-corpus Jina comparison remains incomplete. The stop note, progress and exit receipts are preserved in jina-partial.json and jina.log. No held-out questions were used.

## Method and boundaries

The benchmark ran on this VM with seven visible AMD EPYC 7763 logical CPUs, no GPU, Python 3.12, 16-text embedding batches for Potion/BGE and single-window batches for Jina (measured faster in a separate small trial), and the adapter's 8,000-character input cap. Model2Vec uses static mean embeddings without its runtime's default 512-token cut; FastEmbed uses CPUExecutionProvider and its model tokenizer limit. ONNX telemetry is explicitly disabled before session construction. Four ONNX session threads were selected by a separate small tuning trial; seven were slower on that trial. Other agents were active on the shared development VM, so these are observed service-machine timings, not isolated hardware capacity.

For each corpus, enumerate code and Markdown/MDX files, skip `.git`, `node_modules`, symlinks, files larger than 1,000,000 bytes, NUL-containing files and non-UTF-8 text. Eligible suffixes are listed exactly in `benchmark-source.py`. Split into 60-line windows, advance 45 lines, stop after the first window reaching EOF, and prefix each window with its relative path. Completed model/corpus pairs use the same windows; Jina Vite is explicitly partial and is excluded from quality tables. An answer is correct only when its path matches an expected path and its inclusive line range overlaps an expected range. All 13 non-absent development questions per corpus are retained; absent questions are excluded rather than treating nearest-neighbor output as an absence detector. All expected ranges are reachable. The recorded encoding audit found no otherwise eligible files excluded for non-UTF-8 encoding.

Dense ranks use cosine of normalized embeddings with stable window-ID ties. The BM25-free result is the dense-only row: no lexical scores, symbols, path bonus or learned reranker. The separate lexical baseline is a simple stdlib BM25 (k1=1.2, b=0.75), with whole identifiers and camel/snake components, path-prefixed text, and no stopword removal. Hybrid sums `1/(60+rank)` over the full dense ranking and positive-score lexical ranking, with equal weights. MRR uses the entire ranking; hit@k uses k=1,5,10. This proxy has no syntax-aware chunks, exact-symbol channel, freshness or answer assembly; it is not the production engine and cannot establish its PRD quality gates.

## Quality

All rates below are percentages except MRR. Each corpus has 13 questions, so one question changes a rate by 7.69 percentage points. Treat small differences as exploratory.

| Model | Corpus | Ranking | Hit@1 | Hit@5 | Hit@10 | MRR |
|---|---|---|---:|---:|---:|---:|
| lexical baseline | httpx | bm25 | 38.46 | 61.54 | 76.92 | 0.4773 |
| potion | httpx | dense | 23.08 | 46.15 | 76.92 | 0.3649 |
| potion | httpx | hybrid_rrf60 | 23.08 | 76.92 | 76.92 | 0.4396 |
| lexical baseline | vite | bm25 | 30.77 | 76.92 | 84.62 | 0.4971 |
| potion | vite | dense | 53.85 | 84.62 | 84.62 | 0.6507 |
| potion | vite | hybrid_rrf60 | 61.54 | 84.62 | 92.31 | 0.7104 |
| lexical baseline | jftp | bm25 | 23.08 | 38.46 | 46.15 | 0.3037 |
| potion | jftp | dense | 23.08 | 53.85 | 76.92 | 0.3996 |
| potion | jftp | hybrid_rrf60 | 38.46 | 61.54 | 76.92 | 0.4871 |
| bge | httpx | dense | 30.77 | 61.54 | 69.23 | 0.4883 |
| bge | httpx | hybrid_rrf60 | 38.46 | 69.23 | 84.62 | 0.5193 |
| bge | vite | dense | 23.08 | 38.46 | 46.15 | 0.2908 |
| bge | vite | hybrid_rrf60 | 30.77 | 76.92 | 100.00 | 0.5142 |
| bge | jftp | dense | 38.46 | 61.54 | 61.54 | 0.4754 |
| bge | jftp | hybrid_rrf60 | 38.46 | 76.92 | 84.62 | 0.5331 |
| jina | httpx | dense | 30.77 | 61.54 | 69.23 | 0.4462 |
| jina | httpx | hybrid_rrf60 | 38.46 | 69.23 | 84.62 | 0.5377 |

### Aggregate comparison

| Model | Hybrid hit@1 | Hybrid hit@10 | Hybrid MRR | Index windows/s |
|---|---:|---:|---:|---:|
| potion | 41.03% | 82.05% | 0.5457 | 204.16 |
| bge | 35.90% | 89.74% | 0.5222 | 3.13 |

The aggregate comparison includes only the two models with all three corpora complete. The HTTPX-only Jina results appear in the per-corpus table and are not averaged against 39-question results. Potion has higher aggregate hybrid MRR (0.5457 versus BGE 0.5222) and hit@1 (41.03% versus 35.90%), while BGE has higher hit@10 (89.74% versus 82.05%). Potion indexes about 65 times faster in these runs, which favors it as the practical CPU default. Jina could differ on the uncompleted corpora; no overall Jina quality conclusion is claimed.


Across the 39 development questions, Potion plus BM25 improves hit@10 from 69.23% (27/39) to 82.05% (32/39), hit@5 from 58.97% to 74.36%, and MRR from 0.4260 to 0.5457. Potion dense-only reaches hit@10 79.49% and MRR 0.4717. Its aggregate indexing throughput is 204.16 windows/s, giving an 8.16-minute linear estimate for 100k windows. The default runtime is 93.52 MB across 23 packages, with a 33.52 MB model download. These numbers favor retaining lexical retrieval and adding the static model when semantics are enabled; they do not justify semantic-only as a universal default.


## CPU time and resource footprint

Download and installed package sizes use decimal MB. RAM uses MiB. Runtime package bytes are the summed installed distribution file sizes including shared-library files, excluding Python itself, model files, pip caches and generated bytecode; they do not equal physical filesystem blocks when uv hardlinks files. The extra `sqlite-vec==0.1.9` used for vector tests is excluded from the default runtime figures. Raw JSON records every installed package/version/size, including that testing extra.

| Model | Runtime | Model MB | Runtime packages / MB | Initial provider load s | Peak process RAM MiB |
|---|---|---:|---:|---:|---:|
| potion | model2vec | 33.52 | 23 / 93.52 | 4.812 | 195.3 |
| bge | fastembed | 67.41 | 28 / 179.53 | 1.649 | 877.5 |
| jina | fastembed | 165.44 | 28 / 179.53 | 2.173 | 872.7 |

Peak RAM is the high-water RSS of the entire benchmark process, including tokenizer, windows, vectors and BM25 bookkeeping. It is not a model-only allocation. The reported Jina high-water RSS covers HTTPX only; peak RSS during the interrupted Vite pass was not captured. Initial load is a fresh process with uncontrolled OS file caches, and includes lazy runtime imports and manifest hashing; CLI one-shot queries can pay this startup cost. Warm service reuse avoids it.

| Model | Corpus | Files / windows | Windows/s | Truncated windows | Query embed median / p95 ms | In-memory dense sort median ms |
|---|---|---:|---:|---:|---:|---:|
| potion | httpx | 88 / 532 | 190.80 | 0 | 0.649 / 5.140 | 0.113 |
| potion | vite | 2054 / 4499 | 241.02 | 21 | 0.781 / 10.604 | 35.505 |
| potion | jftp | 459 / 3358 | 171.01 | 22 | 0.857 / 5.552 | 16.584 |
| bge | httpx | 88 / 532 | 3.38 | 364 | 22.966 / 34.357 | 0.243 |
| bge | vite | 2054 / 4499 | 3.01 | 1946 | 57.856 / 125.884 | 15.367 |
| bge | jftp | 459 / 3358 | 3.26 | 2837 | 32.061 / 64.676 | 9.152 |
| jina | httpx | 88 / 532 | 0.94 | 0 | 48.495 / 96.068 | 0.301 |

These query samples are one warm embedding per question (13 per corpus), not load-test p95s. The in-memory sort is only the benchmark proxy; SQLite BLOB scan costs are measured separately. Truncation counts include input character caps and observable tokenizer overflow, counted at most once per input. Inputs begin with the path, so truncation preserves it.

| Model | Measurement scope | Windows/s | Linear estimate for 100,000 windows | Float32 vectors for 100,000 units |
|---|---|---:|---:|---:|
| potion | three corpora | 204.16 | 8.16 minutes | 102.4 MB |
| bge | three corpora | 3.13 | 532.69 minutes | 153.6 MB |
| jina | HTTPX only, partial comparison | 0.94 | 1773.25 minutes | 307.2 MB |

The Jina projection uses only HTTPX and is not a measured three-corpus estimate. The 100k figures are linear extrapolations from measured window embedding time, not a 100k end-to-end index run; parsing, transactions and storage overhead are additional. Different chunk lengths change throughput. In particular, Transformer model token truncation can affect both speed and quality.

## Identities, files and licenses

The exact downloaded file sizes and SHA-256 hashes are in `model-manifests.json`; runtime identities additionally hash the files actually required for inference. Model2Vec files are `model.safetensors`, `tokenizer.json` and `config.json`. FastEmbed BGE uses the supported quantized ONNX conversion `Qdrant/bge-small-en-v1.5-onnx-Q` at `aa8f8b060edb00e03bfdd08813a2949946c8ba55`, file `model_optimized.onnx`, rather than the original PyTorch weights. Jina uses its official `onnx/model_quantized.onnx` (int8) at `516f4baf13dec4ddddda8631e019b5737c8bc250`, copied into the FastEmbed manifest slot `onnx/model.onnx` in a dedicated manual model directory. The upstream weight filename and SHA-256 are recorded; this is explicitly a quantized variant, not the default FastEmbed FP32 download. The original FP32 snapshot was downloaded for inspection and is also recorded, but is not included as a measured quality candidate. All saved retrieval vectors remain normalized float32, independent of model weight precision.

Potion and BGE are MIT; Jina code v2 is Apache-2.0. No non-commercial model is selected. Model2Vec is MIT, FastEmbed and ONNX Runtime have permissive licenses; preserve wheel license metadata and model-card/license files in offline bundles. No repository Python code from a model is downloaded or executed. [BGE conversion](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q), [Jina model card](https://huggingface.co/jinaai/jina-embeddings-v2-base-code).

The benchmark uses the current code-specific Potion v2 rather than the superseded v1, as permitted by the brief. Nomic and Snowflake were optional candidates and were not added to this already costly CPU comparison. The local model choice does not authorize a fleet rollout or a model download by a query.

## Provider and vector contracts

`embed.py` imports only stdlib until a provider is created. `none` returns `None`. `openai-compatible` POSTs bounded batches to the configured base plus `/embeddings` (use an explicit `/v1` base for Ollama/llama.cpp). Proxies and all redirects are disabled; localhost must resolve only to loopback on every request. Non-loopback requires `allow_remote=True`, which is exposed in the identity for index-metadata auditing. Both document and query embeddings use that same explicitly approved endpoint. Provider errors discard server bodies and transport details so echoed keys or source do not leak. Credentials are looked up only by their environment-variable name. The application still owns saved-grant validation and index metadata persistence; a provider flag cannot grant itself consent.

`local-python` chooses Model2Vec for `minishlab/*`, FastEmbed otherwise. Explicit `model2vec:org/model` or `fastembed:org/model` prefixes override routing. For cache lookup/download the revision is the SHA of the actual weight repository (for BGE, the Qdrant conversion), with files at `<cache_dir>/<repo-with-slashes-replaced-by-double-hyphens>/<revision>/`. `model_dir` directly supplies a complete local directory and requires no download grant; file hashes become part of its identity. A missing cache raises ConsentRequired; downloads require both `allow_download=True` and a 40-character immutable SHA. Only the approved manifest files are fetched. FastEmbed always receives `local_files_only=True` and `specific_model_path`, even after explicit setup download. Model2Vec receives only an existing absolute directory. Reuse the same config with `allow_download=False` for query operations.

`transformers-js` reuses the existing locked Node helper in a persistent subprocess with bounded newline responses, Unicode-safe UTF-16 helper limits, bounded writes, timeouts, serial access, sanitized environment and kill/wait cleanup. Its tested protocol uses a synthetic helper; this run did not install the Node model. Real local Python tests use the downloaded Potion and BGE models with Python socket connection attempts blocked and Hub offline mode. For HTTP/Node identities, dimension starts as `None` until the first validated response; callers must embed before comparing a complete identity or persist the discovered dimension after indexing. Local-Python dimension is available immediately.

The HTTP and Node providers add the documented `search_document: ` and `search_query: ` prefixes for named Nomic embed-text models; other custom endpoints must expose their own task contract, recorded through the caller's versioned model identity. FastEmbed delegates to model-specific `passage_embed` and `query_embed`. All providers cap inputs, count truncations and validate finite nonzero vectors with stable dimensions. Counts are cumulative per provider, not per library; callers needing per-operation counts take before/after deltas. The required count-only interface cannot identify individual tokenizer-truncated rows within a batch. Callers persisting per-unit flags must obtain their own token accounting or embed single items; a cumulative count is not a per-unit audit trail.

`vectors.py` packs little-endian float32, normalizes robustly and scans at most 4,096 BLOBs at once. Explicit engines are stdlib, NumPy and sqlite-vec 0.1.9. Auto prefers a compatible sqlite-vec if installed, then NumPy, then stdlib; installed-but-broken accelerators fail explicitly. NumPy performs bounded vectorized validation rather than allocating millions of Python floats. Scores in the same rounded six-decimal bucket tie on ascending unit ID. This is a concrete deterministic interpretation of the ADR's 1e-6 tie tolerance, which is not a transitive comparison by itself. No ANN or additional persistent vector table is introduced.

### Exact scan measurement

Synthetic scan of 100,000 256-dimensional normalized float32 BLOB rows, top 10, 4,096-row batches, three runs per engine. The input is a generator reusing 128 seed vectors, with distinct unit IDs, to isolate scanner overhead from database I/O. This does not establish a SQLite database p95 or high-entropy cache behavior. All three engines return the same IDs.

| Engine | Median ms | Samples ms |
|---|---:|---|
| stdlib | 37257.04 | 31616.12, 37257.04, 43149.21 |
| numpy | 713.49 | 981.64, 713.49, 455.29 |
| sqlite-vec | 2400.08 | 2400.08, 1771.81, 2452.56 |

The 200 ms review threshold from ADR 002 is not demonstrated by these shared-VM scan measurements. No production database p95 was measured; a dedicated end-to-end database run is required before claiming that gate. NumPy was fastest; the default runtime omits sqlite-vec so auto selects NumPy. If sqlite-vec is installed for other reasons, explicitly select numpy for this workload. The sqlite-vec adapter uses NumPy for bounded validation/normalization when available and retains a stdlib validation fallback otherwise. Its native cosine still scores the validated BLOBs. Three interleaved NumPy implementation trials are recorded in vector-numpy-tuning.json; BLAS plus boundary-safe candidate selection had the best median in that trial, with substantial scheduling variance. Original slow-path measurements remain in vector-scan-before-optimization.json.

## Air-gapped installation

Prepare wheels on a connected machine matching the target OS, architecture and Python version; this run tested CPython 3.12/Linux only. Do not copy Linux native wheels onto Windows/macOS. The exact selected Model2Vec runtime is pinned in [`requirements-embed.txt`](../../skills/legacy-codebase-workflows/scripts/requirements-embed.txt). It deliberately omits FastEmbed and torch/sentence-transformers. The measured FastEmbed environment has its separate full package list in `runtime-fastembed.json`; use a separate environment because its Hugging Face Hub major version differs from the locked default.

On the connected machine, download the selected runtime wheels and install them in a temporary preparation environment:

```bash
python3.12 -m pip download --only-binary=:all: --dest wheels -r requirements-embed.txt
```

```bash
python3.12 -m pip install -r requirements-embed.txt
```

Download only the selected pinned model files, plus its model card for provenance/license retention:

```bash
python3.12 -c "from huggingface_hub import snapshot_download; snapshot_download('minishlab/potion-code-16M-v2', revision='e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b', local_dir='models/potion-code-16M-v2', allow_patterns=['config.json','model.safetensors','tokenizer.json','README.md'], token=False)"
```

Copy the engine package, pinned requirements, wheels, model directory and SHA-256 manifest onto the offline machine. Verify copied model hashes against `model-manifests.json` and preserve the installed packages' license metadata. Install using only the copied wheel directory:

```bash
python3.12 -m pip install --no-index --find-links wheels -r requirements-embed.txt
```

Configure `EmbedConfig(provider="local-python", model="minishlab/potion-code-16M-v2", revision="e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b", model_dir="/absolute/path/to/models/potion-code-16M-v2", allow_download=False)`. Use a native absolute path on Windows. Keep the manifest/identity with the index; copied models need no daemon, Hub account, torch, sentence-transformers or query-time connection. First online setup may instead use `cache_dir` plus `allow_download=True`; subsequent queries must turn that flag off.

## Existing Ollama or llama.cpp service

Recommend **Nomic embed-text v1.5** as an optional existing-service route, not as a measured winner here: Ollama model `nomic-embed-text:v1.5`, base `http://127.0.0.1:11434/v1`; or the official Nomic v1.5 GGUF served by llama.cpp with embedding mode and mean pooling, base `http://127.0.0.1:8080/v1`. Its upstream license is Apache-2.0 and its embedding dimension is 768. Pin the served file digest/version in `revision`; tags alone are mutable. The adapter supplies Nomic's asymmetric retrieval prefixes. Do not mix these vectors with Potion or with differently configured Nomic pooling/dimensions. [Nomic model and prefix contract](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5), [Ollama tag](https://ollama.com/library/nomic-embed-text:v1.5), [Ollama compatibility](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx), [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Only the fake HTTP server contract was exercised here; no actual Ollama/llama.cpp service was launched or probed. Validate the particular server's model alias and maximum input size before indexing. A remote server additionally requires explicit consent and the same approved endpoint for documents and queries. This follows the brief's orchestrator ruling; the ADR's older remote-query prohibition remains an upstream document conflict for the orchestrator to reconcile.

## Validation and handoff

The focused unittest suite covers consent before DNS, HTTP batching/reordering, redirects/proxies, malformed vectors, body size limits, secret-safe errors, dimension changes, Nomic task prefixes, cache/download guards, pinned manifests, telemetry suppression, real offline local models, persistent Node protocol, blocked stdin writes, timeouts/reaping, float32 bytes and deterministic exact engines against a brute-force float64 oracle across multiple scan batches. Real model tests are skipped unless their explicit test model directory variables are set; optional NumPy/sqlite-vec tests skip when those packages are absent.

```bash
python3 -m unittest discover -s tests -p test_legacy_embed.py -v
```

The stdlib environment runs 31 tests with four optional skips. Each isolated candidate environment runs NumPy/sqlite-vec oracle checks plus its own real offline model check, with only the other model runtime skipped. No changes were made outside the delegate's owned implementation/tests/report/results and evaluation scratch directory. No commits, pushes, Beads writes, package marker or installed skill edits were made. Integration, PR review and commits belong to the orchestrator.

Durable scratch: `/home/lucas/DEV/Projects/agent-toolbox-eval/embed-bench/`. It holds the two isolated runtimes, model files, benchmark/download scripts and streamed logs. The raw results include copied source scripts and file hashes for reproduction; paths in those scripts describe this run, not required engine paths. Workspace lifecycle and evidence paths are in `session.json`. The interrupted seven-thread trial is preserved as `bge-interrupted.log` and excluded from final performance tables.
