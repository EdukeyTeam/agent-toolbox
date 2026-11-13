# Local code and docs retrieval landscape (October 2026)

Research snapshot for an offline, local retrieval engine (a "local Context7") that indexes any repository plus Markdown/RST/AsciiDoc/HTML docs, answers natural-language and exact-symbol questions with source-cited snippets, runs on CPU-only laptops across Linux/macOS/Windows, and treats embeddings as optional.

Each section answers one brief question with a direct answer, the evidence, and source URLs. Official documentation and papers are labeled as such. Community blogs and vendor marketing are labeled as such. Claims that could not be verified from a primary page are marked UNCONFIRMED.

## 1. Code-aware chunking

### Direct answer

The current best production pattern is size-budgeted, structure-aware chunking on a tree-sitter AST (cAST-style recursive split-then-merge), with a sliding-window fallback when parsing fails, plus cheap metadata prefixes (path, enclosing class/function signature, language). Do not use one-function-per-chunk as the retrieval unit. LLM-generated "contextual retrieval" prefixes help mixed-document RAG a lot, but they are an indexing-time cost and are not required to beat fixed-size line chunks on code.

### Evidence

cAST (Zhang et al., EMNLP 2025 Findings; arXiv v2 2 Oct 2025) parses with tree-sitter, recursively splits AST nodes that exceed a size budget measured in non-whitespace characters, then greedily merges sibling nodes so chunks stay dense. Concatenating chunks reproduces the original file. Against fixed-size line chunks, the paper reports Recall@5 gains of 1.8 to 4.3 points on RepoEval and Precision gains of 1.2 to 3.3 points; on SWE-bench Lite, Precision +0.5 to +1.4 and Recall +0.7 to +1.1; Pass@1 +2.67 points in the abstract, and up to 2.7 points in the body. StarCoder2-7B sees an average 5.5-point gain on RepoEval. With CodeSage-small-v2 retrieval, StarCoder2-7B Pass@1 is 73.2 (cAST) vs 67.6 (fixed-size). Split-only (no sibling merge) collapses nDCG from 71.1 to 53.5 with BGE-base. Best max_chunk_size in their ablation is 2000 to 2500 non-whitespace characters. The authors explicitly did not prepend enclosing-scope headers; that is listed as a limitation. Official paper and code: https://arxiv.org/abs/2506.15655 and https://github.com/yilinjz/astchunk

A 2026 controlled study (Wu, Gong, Jahangirova, Zhang; arXiv:2605.04763, 6 May 2026) isolates chunking across 864 RAG code-completion settings (Function, Declaration, Sliding Window, cAST x 4 retrievers x 5 generators x 9 parameter configs on RepoEval and CrossCodeEval). Chunking has a statistically significant effect, but function-boundary chunking underperforms every other strategy by 3.57 to 5.64 percentage points Exact Match on RepoEval (Cliff's delta = -1.0) and is never Pareto-optimal. Sliding Window and cAST perform comparably and dominate the cost-quality front. Cross-file context length is the dominant knob: 2048 to 8192 tokens yields up to 4.2 points EM; chunk size is weaker and non-monotonic, peaking around 2000 non-whitespace characters. Retriever swap moves EM by at most 1.11 points on RepoEval, less than the chunking gap. The same ranking holds on Java CrossCodeEval, with cAST slightly ahead of Sliding Window there. Official paper: https://arxiv.org/abs/2605.04763

Anthropic Contextual Retrieval (official engineering post, 19 Sep 2024) prepends a 50-100 token model-written situating prefix to each chunk before both embedding and BM25. On mixed knowledge bases (including codebases, fiction, papers) with Gemini embeddings and top-20 retrieval, contextual embeddings cut top-20 failure from 5.7% to 3.7% (35%); adding contextual BM25 reaches 2.9% (49%); adding a Cohere reranker reaches 1.9% (67%). They found k=20 better than k=5 or 10 among the options they tried. This is document-context restoration, not AST cutting, and it needs an LLM at index time (~$1.02 per million document tokens with Claude prompt caching in their 2024 recipe). Official: https://www.anthropic.com/news/contextual-retrieval

Enclosing-scope headers (file path, class name, function signature prepended to the chunk text) are the cheap analog of contextual retrieval and are widely recommended in production writeups. cAST itself does not do this. Continue's official custom-code-RAG guide ranks strategies as: (1) truncate whole files when the embedder is long-context (voyage-code-3 at 16k tokens), (2) fixed-length line chunks, (3) recursive AST as "most exact, but most complex". Official Continue: https://docs.continue.dev/guides/custom-code-rag

Vendor/community numbers that should not be treated as independent replications: Supermemory `code-chunk` reports Recall@5 70.1% vs 42.4% fixed-size on their own benchmark (community blog, 29 Dec 2025, https://supermemory.ai/blog/building-code-chunk-ast-aware-code-chunking). A Substack post claims ~40% fewer irrelevant hits on a 300k-LOC Python monorepo (community, 9 Jan 2026). UNCONFIRMED outside those posts.

### Practical rule for this engine

Use cAST-style split-then-merge with a ~2000 non-whitespace-character budget, attach path + signature + start/end line as both metadata and an embedded prefix, fall back to overlapping sliding windows on parse failure, and do not make "one function = one chunk" the default.

## 2. Documentation chunking

### Direct answer

Split on the author's heading hierarchy first, never split inside fenced code blocks, keep the heading breadcrumb in the chunk text (not only in metadata), and keep a code fence with the explanatory paragraph that immediately precedes it. Recurse into paragraphs/sentences only when a section exceeds the size cap. The same breadcrumb trick is the docs analog of contextual retrieval and is free.

### Evidence

Heading-aware splitting is the default in every serious Markdown RAG stack. LangChain `MarkdownHeaderTextSplitter` is the well-known implementation; its default `strip_headers=True` removes headings from chunk text and stores them only in metadata, which starves BM25 of section titles. Community guidance (DEV, June 2026) is to set `strip_headers=False` and also prepend a formatted breadcrumb such as "Page title > H1 > H2" before embedding. Community: https://dev.to/kartikeyraj/free-contextual-chunk-headers-heading-aware-chunking-for-hybrid-retrieval-560

VoltAgent's Markdown chunker (official docs) parses headings, lists, blockquotes, paragraphs, and code fences separately, attaches `headingPath`, and routes fenced code through a code chunker so a language-tagged fence can be split at function/class boundaries. Official: https://voltagent.dev/docs/rag/chunkers/markdown/

Rust `breadchunks` (lib.rs) is a clean statement of the three-phase recipe: split at ATX headers while protecting fenced code, merge same-breadcrumb chunks below a min length, then absorb small children into parents under a max length; each chunk carries `H1 > H2 > H3`. Community crate docs: https://lib.rs/crates/breadchunks

`markdown-chunk` (lib.rs, May 2026) states the hard rule: never split inside ``` fenced code; oversize sections are returned whole rather than cut mid-fence. Community: https://lib.rs/crates/markdown-chunk

Anthropic's contextual prefixes (50-100 tokens) apply equally to docs: a chunk that says "Yes, within 30 days" is useless without "Returns and Refunds > Sale items". Official Anthropic post above.

HTML should be converted to Markdown (or walked as a heading/DOM tree) before the same heading-aware splitter. RST and AsciiDoc have equivalent section markers (`====`, `----`, `= Title`); treat those as headings. A dedicated published eval of RST/AsciiDoc vs Markdown heading splitters was not found; treat cross-format quality deltas as UNCONFIRMED.

Pairing: keep a fenced example with the immediately preceding prose (or the section heading plus that prose) in one chunk when they fit the budget; if they do not, duplicate the breadcrumb and a one-line caption onto the code-only chunk so BM25 still sees the API name. This is practitioner consensus, not a numbered paper result.

MDKeyChunker (arXiv:2603.23533, community paper) adds one LLM call per chunk for title/summary/keywords. That is optional enrichment, not a replacement for heading-aware splits.

## 3. Small embedding models for CPU code and docs retrieval

### Direct answer

For a laptop skill that must stay optional and offline, the practical CPU-code shortlist is CodeRankEmbed (137M, MIT, 768-d, 8k) or Qwen3-Embedding-0.6B (596M, Apache 2.0, 1024-d Matryoshka, 32k) as a single code+docs model. jina-code-embeddings-0.5B/1.5B are stronger on MTEB Code but CC-BY-NC-4.0, so they are a poor default for a redistributable commercial skill. nomic-embed-code (7B) is too large for CPU-only laptops. voyage-code-3/4 remain the API quality ceiling.

### Comparison table

Scores are from the cited official model cards or papers. Cells marked UNCONFIRMED were not on the primary card. CPU throughput is almost always hardware-specific; treat those cells as order-of-magnitude only.

| Model | Params / weight | Dims | Max tokens | License | Code scores (as published) | Matryoshka | ONNX / GGUF | CPU notes |
|---|---|---|---|---|---|---|---|---|
| jina-embeddings-v2-base-code | 161M | 768 | 8192 | Apache 2.0 | CoIR NDCG@10 58.4 as "Jina-Code-v2" on CodeRankEmbed card; 30 languages | No | Transformers.js / ONNX community quants exist | BERT+ALiBi; mean pool. Official: https://huggingface.co/jinaai/jina-embeddings-v2-base-code |
| jina-code-embeddings-0.5b | 494M | 896 (to 64) | 32768 | CC-BY-NC-4.0 | Overall 78.41%, MTEB Code 78.72% (Jina report) | Yes 64/128/256/512/896 | Official GGUF; community ONNX | Last-token pool, task prefixes. Official: https://jina.ai/news/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/ and https://huggingface.co/jinaai/jina-code-embeddings-0.5b |
| jina-code-embeddings-1.5b | 1.54B | 1536 (to 128) | 32768 | CC-BY-NC-4.0 | Overall 79.04%, MTEB Code 78.94% | Yes | Official GGUF | Same family. Heavy for CPU laptops. |
| nomic-embed-code | 7B (Qwen2.5-Coder-7B) | 3584 last-token hidden (GGUF `embedding_length`; card does not state a projected dim) | 32768 | Apache 2.0 | CodeSearchNet: Python 81.7, Java 80.5, Ruby 81.8, PHP 72.3, JS 77.1, Go 93.8 (beats voyage-code-3 on 4/6 langs on that table) | UNCONFIRMED | Official GGUF (Q4_K_M ~4.4 GB, F16 13.2 GB) | Too big for default CPU. Official: https://huggingface.co/nomic-ai/nomic-embed-code |
| CodeRankEmbed | 137M | 768 | 8192 | MIT | CSN MRR 77.9; CoIR NDCG@10 60.1 (official card, vs Jina-Code-v2 58.4 / Voyage-Code-002 56.3) | No | Community GGUF (F16 ~274 MB, Q8 ~146 MB); ONNX requested, not official | Best small permissive code encoder. Query prefix required. Official: https://huggingface.co/nomic-ai/CodeRankEmbed |
| Qwen3-Embedding-0.6B | 0.6B (596M) | 1024 (32 to 1024) | 32768 | Apache 2.0 | MTEB Code 75.41 (Qwen paper); Jina re-eval overall 73.49 / MTEB Code 74.69 | Yes | GGUF widely available; ONNX community | Instruction-aware; last-token pool. Strong default if one model must cover code and docs. Official: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B and https://arxiv.org/abs/2506.05176 |
| EmbeddingGemma-300m | ~308M | 768 (to 128) | 2048 | Gemma Terms of Use (not Apache) | MTEB Code 68.76 at 768-d; 68.48/66.74/62.96 at 512/256/128 (official card / paper) | Yes | Official-community ONNX (`onnx-community/embeddinggemma-300m-ONNX`); int8 ~68.70 MTEB Code | Built for on-device. Code-retrieval task prefix documented. Official: https://huggingface.co/blog/embeddinggemma and https://arxiv.org/abs/2509.20354 |
| granite-embedding-english-r2 | 149M | 768 | 8192 | Apache 2.0 | CoIR 55.3 (card table 1) / 54.8 (card table 2); BEIR 53.1; MTEB-v2 62.8 | No on this English-r2 card (MRL is on 311m multilingual-r2) | Quantizations listed on the Hub | ModernBERT; enterprise-friendly training data (no MS MARCO). Official: https://huggingface.co/ibm-granite/granite-embedding-english-r2 |
| granite-embedding-small-english-r2 | 47M | 384 | 8192 | Apache 2.0 | CoIR 53.8 / 53.4 | No | Hub quants | Fastest Granite English. Same card. |
| granite-embedding-311m-multilingual-r2 | 311M | 768 (MRL) | 32768 | Apache 2.0 | Paper claims SOTA-ish multilingual retrieval; MTEB Code column in arXiv HTML is mixed with other models | Yes | UNCONFIRMED ONNX | Official IBM docs: https://www.ibm.com/granite/docs/models/embedding |
| bge-small-en-v1.5 | 33M | 384 | 512 | MIT | General English retrieval; not code-specialized. FastEmbed default. | No | Official ONNX via FastEmbed | Tiny lexical-semantic baseline. Official: https://huggingface.co/BAAI/bge-small-en-v1.5 (card not re-fetched this session; size/dims/license are the long-standing published spec). |
| bge-m3 | 568M | 1024 + sparse + multi-vector | 8192 | MIT | Strong multilingual hybrid; CoIR not its headline. Qwen paper lists BGE-reranker-v2-m3 MTEB Code 41.38 as a reranker, not this embedder. | Partial (can truncate) | ONNX / FastEmbed | Dense+sparse in one model. Official: https://huggingface.co/BAAI/bge-m3 |
| all-MiniLM-L6-v2 | 22.7M | 384 | 256 | Apache 2.0 | Weak on code; still the FastEmbed/prototyping default | No | ONNX everywhere | Fastest transformer-class baseline. Official: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |
| snowflake-arctic-embed-m-long | 137M | 768 | 8192 | Apache 2.0 | CSN MRR 53.4; CoIR 43.0 on CodeRankEmbed card (this is the CodeRankEmbed initialization, not a code model) | UNCONFIRMED for this variant | Sentence-transformers | Use only as a general embedder. CodeRankEmbed card: https://huggingface.co/nomic-ai/CodeRankEmbed |
| snowflake-arctic-embed-l-v2.0 | ~568M | 1024 | 8192 | Apache 2.0 | Granite card: CoIR 52.2 for arctic-embed-m-v2.0 (305M, 768-d). L-v2.0 code score UNCONFIRMED here. | UNCONFIRMED | GGUF / Ollama `snowflake-arctic-embed2` | Official family: https://huggingface.co/Snowflake |
| voyage-code-3 (API) | undisclosed | 1024 default (256/512/2048) | 32000 | proprietary API | Jina report: overall 79.23%, MTEB Code 79.84%; vendor: +13.80% vs OpenAI v3-large on 32 datasets | Yes | API only | Quality ceiling for cloud. Official: https://docs.voyageai.com/docs/embeddings and https://blog.voyageai.com/2024/12/04/voyage-code-3/ |
| voyage-code-4 (API) | undisclosed | 2048/1024/512/256 | UNCONFIRMED (family is 32k) | proprietary API | Vendor: +19.21% vs Cohere Embed v4 and +16.01% vs Gemini Embedding 2 on the voyage-code-3 suite; agent-oriented eval | Yes | API only | Newer ceiling, Aug 2026. Official blog: https://blog.voyageai.com/2026/08/13/voyage-code-4/ |
| potion-code-16M-v2 | ~16M static | 256 | effectively unlimited (static) | MIT | Distilled from CodeRankEmbed on CoRNStack; hybrid+BM25 RRF mentioned on card. Absolute CoIR UNCONFIRMED in this session. | No | model2vec / ONNX | Lookup-table speed. Official: https://huggingface.co/minishlab/potion-code-16M-v2 |

Notes on score comparability: CoIR, MTEB Code, and CodeSearchNet tables in 2024-2026 cards are not on a single frozen eval harness. Jina's 25-task average, Qwen's MTEB Code 75.41, and CodeRankEmbed's CoIR 60.1 cannot be subtracted as if they were the same metric. Use them as within-card rankings.

License trap: jina-code-embeddings-0.5b/1.5b and jina-reranker-v3 are CC-BY-NC-4.0. jina-embeddings-v2-base-code is Apache 2.0. EmbeddingGemma-300m is Gemma ToU; EmbeddingGemma 2 (Oct 2026) is Apache 2.0 per Google's blog but is multimodal and newer than this CPU shortlist's 300m card.

## 4. Local runtimes

### Direct answer

For a Python-first skill used by non-expert clients, FastEmbed (ONNX Runtime, no PyTorch) is the most robust default for BERT-class models (bge-small, MiniLM, and any model Qdrant already ships). Use sentence-transformers when the chosen model is Qwen3-Embedding, EmbeddingGemma, CodeRankEmbed (`trust_remote_code`), or Granite. Offer an OpenAI-compatible embeddings HTTP endpoint as an escape hatch. Do not require Ollama or llama.cpp for the default path.

### Comparison table

| Runtime | Install size / deps | Windows/macOS/Linux | Speed on CPU | Offline cache | Fit for this skill |
|---|---|---|---|---|---|
| fastembed (Qdrant) | Small; ONNX Runtime, no PyTorch. `pip install fastembed`. Default model bge-small-en-v1.5. | Officially supported; ONNX Runtime is the portability layer | Designed for CPU; data-parallel batch encode. Absolute tok/s UNCONFIRMED here | Downloads ONNX weights once to a cache dir | Best default for BERT-sized models and serverless/offline. Official: https://github.com/qdrant/fastembed and https://pypi.org/project/fastembed/ |
| sentence-transformers | Heavy if it pulls torch+cuda; CPU torch wheels exist. Needed for Qwen3-Embedding (>= transformers 4.51) and EmbeddingGemma | Excellent | Slower than ONNX for the same MiniLM; fine for 0.6B on a laptop if batched | Hugging Face hub cache (`HF_HOME`) | Required adapter for SOTA small decoder embedders. Official: https://sbert.net |
| ONNX Runtime directly | `onnxruntime` CPU wheel is small | First-class on all three OSes | Fastest portable transformer runtime | Local `.onnx` files | Use via FastEmbed unless we need a model FastEmbed does not list |
| transformers.js | npm; WASM/ONNX in Node or browser | Yes | Fine for interactive, not for 100k-file indexing in Python | Hub cache | Not the Python-first path |
| llama.cpp / llama-server embeddings | Single binary + GGUF. `--embeddings --pooling last` (or `mean`; must match the card) | Excellent, including Windows | Good for GGUF-only models (jina-code GGUF, Qwen3 GGUF). Pooling mistakes silently destroy quality | Local GGUF | Optional backend, not default. Users already running llama-server can point us at `/v1/embeddings` |
| Ollama embeddings API | Separate daemon; model pulls are quantized GGUF | Excellent UX, extra moving part | Fine; one more process to install and keep alive | `ollama pull` cache | Optional OpenAI-compatible endpoint. Weak if we need a model Ollama does not ship, or EmbeddingGemma 2 on Linux CPU (community report that Ollama 0.40 needs MLX/CUDA for that model: https://www.ssdnodes.com/learn/run-embeddinggemma-2-on-a-vps ) |
| model2vec / potion | `pip install model2vec`; ~16-32M static tables | Pure Python/numpy, very portable | Orders of magnitude faster than transformers (vendor: up to 500x; treat as vendor claim) | Hub | Excellent optional first-stage or lexical-adjacent dense index. potion-code-16M-v2 is the code-specific weights |

Robustness ranking for non-expert clients: (1) FastEmbed in-process, (2) sentence-transformers in-process for models FastEmbed lacks, (3) user-supplied OpenAI-compatible base URL (Ollama, llama-server, TEI, cloud), (4) model2vec as a speed option.

PyTorch-on-Windows has historically been the failure mode for "just pip install". FastEmbed avoids that. CodeRankEmbed currently wants `trust_remote_code` in sentence-transformers; that is a support cost.

## 5. Vector storage and search on a laptop

### Direct answer

For up to a few million chunks on a laptop, prefer an embedded library: sqlite-vec (or SQLite FTS5 + brute-force/quantized vectors) while the corpus is small or embeddings are off; LanceDB when you need ANN, metadata, and disk-backed memory maps at 1M-10M vectors. Do not default to Chroma (RAM) or a server database. Keep a lexical index regardless.

### Comparison table

| Store | Algorithm | Laptop 1M-scale (published) | Memory | Windows | Notes |
|---|---|---|---|---|---|
| sqlite-vec (asg017) | Brute-force KNN on float32/int8/bit; ANN still "roadmap" as of the v0.1 post | Author: brute-force is "fast enough" for thousands to low hundreds of thousands; Kanopy Labs (community, Sep 2026): ~45 ms p50 @ 1M, ~400 ms @ 10M; ~200 MB RSS @ 1M | Low; SQLite cache | Yes (Python `pip install sqlite-vec`) | Pure C, no deps, one file. Pre-v1. Official: https://github.com/asg017/sqlite-vec and https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/ |
| SQLite Vec1 (sqlite.org) | IVFADC + OPQ ANN | Official page exists as of Oct 2026; independent laptop numbers UNCONFIRMED | Designed smaller than HNSW | Buildable (`nmake` mentioned) | Different from sqlite-vec. Official: https://sqlite.org/vec1 |
| LanceDB | IVF_PQ / IVF_RQ / IVF_HNSW_SQ; disk-backed Lance files | Community (Sep 2026): 1.18M glove-100, index <30 s on 4 CPU cores, p95 ~6 ms, recall@10 0.91, disk 488 MiB. Kanopy: ~4 ms p50 @ 1M, ~8 ms @ 10M, ~400 MB / ~2.2 GB RSS | Memory-maps; working set << raw vectors | Official `win_amd64` wheel (lancedb 0.40.0, 83.4 MB, 7 Oct 2026) | Best ANN default in Python. Official: https://docs.lancedb.com/indexing/vector-index and https://pypi.org/project/lancedb/ |
| usearch | HNSW, SIMD, int8/binary | Used inside DuckDB VSS; vendor claims very fast HNSW. Independent million-scale laptop numbers UNCONFIRMED in this session | Compact | Yes | Good if we want a tiny C++/Python ANN without a DB. https://github.com/unum-cloud/usearch |
| hnswlib | Classic HNSW | Standard library; RAM grows with graph (often 1.5-2x vectors). Exact laptop RSS UNCONFIRMED | In-RAM graph | Yes | Simple, well-known, not disk-native |
| FAISS | IVF, HNSW, PQ, on CPU | Mature; heavier build. Meta has shifted emphasis to GPU in 2026 commentary (community). Windows via conda/pip, historically painful | Tunable | Yes with caveats | Overkill unless we already depend on it |
| Chroma | In-memory HNSW (embedded mode) | Kanopy Labs: ~2 ms p50 @ 1M but ~6.5 GB RSS; ~58 GB @ 10M | High | Yes | Fast queries, bad laptop citizen at millions of chunks. Community: https://kanopylabs.com/blog/lancedb-vs-chroma-vs-sqlite-vec |
| DuckDB VSS | HNSW via usearch; experimental persistence | Official docs still call `vss` experimental; persistence needs `hnsw_enable_experimental_persistence`. Windows wheels exist (`duckdb-extension-vss` 1.5.5 win_amd64, Aug 2026) | In-process | Yes | Excellent if we already want SQL analytics. Official: https://duckdb.org/docs/stable/core_extensions/vss |
| numpy brute force (+ int8/binary) | Exact scan | Fine to tens of thousands of 768-d vectors; at 1M x 1024-d float32 = 4.1 GB just for vectors (community arithmetic, https://www.maximem.ai/blog/local-embedding-models) | Full matrix in RAM | Yes | Acceptable for lexical-only or tiny indexes; pair with int8/binary for a first-stage |

Kanopy Labs (community, 3 Sep 2026) side-by-side on insert/query/RAM is the most complete laptop-shaped comparison found; treat numbers as one lab's run, not a standard: https://kanopylabs.com/blog/lancedb-vs-chroma-vs-sqlite-vec

A Go benchmark (community, Apr 2026) at 100k x 1024-d: sqlite-vec brute force p50 1.7 s (slow in that harness), LanceDB-go p50 6 ms, chromem-go 38 ms at 1.3 GB RAM. Cross-language timings are not directly comparable to Python.

## 6. Hybrid retrieval and reranking

### Direct answer

Always run lexical (BM25/FTS5) alongside dense when dense is on. Fuse with reciprocal rank fusion (RRF, k=60) as the default; weighted score fusion needs per-corpus tuning. Rerank the fused top 50-150 down to 10-20 with a small cross-encoder when the user can spend CPU. For code, split identifiers on camelCase/snake_case, index path components, and boost exact symbol matches.

### Evidence

Anthropic (official): embeddings+BM25 already beat embeddings; contextual BM25 stacked further; reranking stacked again (5.7% -> 4.8% hybrid baseline vs 2.9% contextual hybrid vs 1.9% with rerank, top-20 failure). Official: https://www.anthropic.com/news/contextual-retrieval

RRF: `score(d) = sum_i 1/(k + rank_i(d))` with k=60 is the standard from Cormack et al. and the recipe repeated in 2026 RAG guides. Weighted fusion (alpha * cosine + (1-alpha) * BM25) works when both scores are calibrated; RRF does not need calibration. Prefer RRF as the default.

Code lexical tricks that are standard in code search (Lucene `word_delimiter`, Elasticsearch, CodeSearchNet-era tokenizers): split `getUserId` -> `get user id`, `snake_case` -> `snake case`, keep the original token, add filename and directory tokens, optionally boost hits where the query token equals a defined symbol. No new 2026 paper was found that re-measures camelCase splitting in isolation; treat the magnitude of the gain as UNCONFIRMED and the practice as established.

### CPU rerankers

| Model | Size | License | Published retrieval/rerank scores | CPU practicality |
|---|---|---|---|---|
| bge-reranker-v2-m3 | 568M | Apache 2.0 (Hub GGUF cards also say Apache; original FlagEmbedding list) | BEIR ~56.51 nDCG@10; MIRACL 69.32; CoIR 36.28 (jina-reranker-v3 card table) | Default multilingual cross-encoder. 8k context. Community: ~200-600 ms for a small candidate list on CPU. Official: https://huggingface.co/BAAI/bge-reranker-v2-m3 |
| jina-reranker-v2-base-multilingual | ~278-300M | Apache 2.0 | BEIR 57.06; CoIR 56.14 (same table) | Faster than bge-m3; weaker on CoIR than later Jina/Qwen |
| jina-reranker-v3 | 0.6B listwise | CC-BY-NC-4.0 | BEIR 61.94; CoIR 70.64 | Strong on code (CoIR) but non-commercial weights |
| mxbai-rerank-base-v2 | 0.5B | Apache 2.0 | BEIR 55.57 (Mixedbread blog) / 58.40 (Jina table); CoIR 65.71 | Faster than bge-m3 on Mixedbread's A100 table; CPU numbers UNCONFIRMED. Official: https://www.mixedbread.com/blog/mxbai-rerank-v2 |
| mxbai-rerank-large-v2 | 1.5B | Apache 2.0 | BEIR 57.49 / 61.44; CoIR 70.87 | Heavy for CPU |
| ms-marco MiniLM-L6 | ~22M | Apache 2.0 | Old but very fast; English MS MARCO | FastEmbed ships `Xenova/ms-marco-MiniLM-L-6-v2` ONNX. Best latency fallback. Official FastEmbed README: https://github.com/qdrant/fastembed |
| Qwen3-Reranker-0.6B | 0.6B | Apache 2.0 | MTEB-R 65.80; MTEB Code 73.42; FollowIR 5.41 (Qwen paper Table) | Best permissive small reranker on Qwen's code column, ahead of bge-reranker-v2-m3's 41.38 MTEB Code. Official: https://arxiv.org/html/2506.05176v2 |

bge-reranker-v2-m3's CoIR 36.28 vs Qwen3-Reranker-0.6B 73.42 (and 65.18 on the Jina table) is a large spread; if we rerank code, prefer Qwen3-Reranker-0.6B or skip rerank on CPU rather than using bge-m3 as a code reranker.

Pipeline: BM25 top 50 + dense top 50 -> RRF top 100 -> optional cross-encoder top 10-20.

## 7. Existing local code+docs retrieval tools

### Direct answer

No open tool is both fully local, code+docs, token-budgeted, and well-evaluated. Steal AST chunking + hybrid search from Claude Context, symbol tools from Serena, heading-aware docs indexing from docs-mcp-server, repo-map outlines from Aider, and the "grep still wins exact lookup" lesson from Claude Code / Cursor.

### Evidence by tool

Claude Context (Zilliz, MIT). MCP semantic+hybrid (BM25 + dense) code search with AST chunking, Merkle-tree incremental indexing, Milvus/Zilliz + OpenAI/Voyage/Ollama/Gemini. Vendor eval: ~40% token reduction at equivalent retrieval quality. Not offline-first: default path wants Zilliz Cloud and an embedding API. Official: https://github.com/zilliztech/claude-context

Serena (Oraios, MIT). LSP-backed symbol find/refs/rename/overview, not a vector index. Agent-written qualitative evals on the README; no public retrieval IR table. Complements embeddings: use it for "every caller of X". Official: https://github.com/oraios/serena

docs-mcp-server (arabold / grounded.tools, MIT). Local Context7-style docs index: scrape official sites, GitHub, npm, PyPI, local files; versioned libraries; search + fetch-url. Embeddings optional (OpenAI, Ollama). This is the closest open docs analog. No published IR eval found. Official: https://github.com/arabold/docs-mcp-server

Sourcegraph / Cody. Enterprise code search + graph; cloud or self-host. Public agent-harness evals comparable to this brief were not found. Treat quality claims as vendor. https://sourcegraph.com

Continue. Open-source IDE agent. Indexes with tree-sitter snippets, SQLite FTS5, and LanceDB embeddings; recursive AST chunker in `core/indexing/chunk/code.ts`. Official indexing README: https://github.com/continuedev/continue/blob/main/core/indexing/README.md and custom RAG guide: https://docs.continue.dev/guides/custom-code-rag

Cursor codebase indexing. Official docs: chunk into functions/classes/logical blocks, embed, sync to Cursor servers, incremental updates every 5 minutes. Official research post (6 Nov 2025): semantic search + grep vs grep-only gives +12.5% question accuracy on Cursor Context Bench (range 6.5-23.5% by model); A/B: +0.3% code retention overall, +2.6% on repos with 1000+ files; +2.2% dissatisfied follow-ups when semantic search is removed. They train a custom embedder on agent traces. Official: https://cursor.com/docs/context/codebase-indexing and https://cursor.com/blog/semsearch

Augment Context Engine. Vendor: live semantic index, "400K+ files", IDE/CLI/MCP. Independent published eval UNCONFIRMED. Community landscape: https://codevetter.com/docs/knowledge/codebase-context-tools-landscape/

Greptile. Graph of functions/classes/files for PR review and Q&A. Cloud-first. Independent retrieval numbers UNCONFIRMED.

Aider repo map. Tree-sitter definitions + PageRank on the file-dependency graph, packed into a token budget (default ~1k, expandable). SWE-bench Lite 26.3% resolve and 70.3% correct file identification are often cited as then-SOTA for the system as a whole, not an isolated map ablation. Official: https://aider.chat/docs/repomap.html and https://aider.chat/2023/10/22/repomap.html

Repomix. Packs a repo into one XML/Markdown blob for a model; MCP `pack_codebase`. Context dumping, not retrieval. Official: https://repomix.com/guide/mcp-server

Code-graph tools (code-graph-rag, GitNexus, CodeGraphContext, codebase-index). Useful for "what calls this" and impact. Sverklo's own 60-task bench (community, 28 Apr 2026): tuned grep F1 0.67 vs sverklo 0.58, but 62x fewer tokens than naive grep (255 vs 15,814) and 1 tool call vs 7-12. Community: https://sverklo.com/blog/i-benchmarked-code-retrieval-for-ai-agents/

## 8. How agents consume retrieval vs agentic grep

### Direct answer

Return a small number of cited snippets (about 10-20) with file path, line range, and the enclosing signature or heading; keep a "read more of this file" / `read_file(start, end)` follow-up; always expose grep/path/symbol search beside semantic search. Semantic search helps large repos and natural-language questions; grep wins exact identifiers. Hybrid is what Cursor measured as best.

### Evidence

Cursor (official, above): semantic search + grep beats grep-only by 12.5% accuracy on their question bench; retention gains concentrate on 1000+ file repos. They state the combination of grep and semantic search leads to the best outcomes.

Claude Code agentic search. Anthropic has not published a paper titled "we abandoned RAG". Community writeups (citing Boris Cherny) say an early Voyage embedding index was replaced by Glob+Grep+Read because grep returns exact lines the agent can use immediately, while RAG returned "related" snippets that needed a second filter. Treat the internal A/B as UNCONFIRMED without an official Anthropic URL. The observable product still greps by default. LSP-backed navigation (Serena, Claude Code LSP) is a third path: ~50 ms definition lookup vs multi-second grep+read (community).

Snippet shape. cAST and Continue both store start/end lines. Anthropic found k=20 better than 5 or 10 for generation on their corpora. The 2026 chunking study found the generator's cross-file token budget (4096-8192) moved EM more than chunker choice among the non-function strategies. Aider shows that signatures/outlines alone often suffice, with on-demand file reads for the rest.

Token economy. Zilliz Claude Context: ~40% fewer tokens at matched quality (vendor). grepai vs grep on Excalidraw (community, Sep 2026): -27.5% billed cost, -97% input tokens, -55% tool calls. Sverklo: 62x fewer tokens than naive grep, 2.9x vs smart grep, with lower F1 than smart grep. The consistent lesson: ranked ranges beat dumping files; exact tools beat semantic when the query is a symbol.

Published "agent with retrieval vs agentic grep" academic study beyond Cursor's post and the community MCP benches was not found. Do not claim a universal winner.

Recommended result record: `{path, start_line, end_line, language, symbol_or_heading, signature, snippet, score, source=bm25|dense|hybrid}`. Cap default k at 10 for the model, keep 20-50 in the engine for a "more results" follow-up. Never omit line ranges.

## Recommendations for our engine

Ranked, concrete, matching the product constraints (offline, CPU laptop, Python 3.12+, embeddings optional, 100k+ files, Linux/macOS/Windows).

1. Chunker (default, always on). Tree-sitter cAST-style recursive split-then-merge with a 2000 non-whitespace-character budget and sibling merge. Attach `path`, enclosing class/function signature, start/end line, and language as metadata and as a short text prefix on the stored/embedded string. Fallback: overlapping sliding window (about 15 lines overlap) when parse fails. Do not use one-function-per-chunk. Implementation reference: https://github.com/yilinjz/astchunk

2. Docs chunker (default, always on). Heading-aware split (Markdown ATX; RST/AsciiDoc section underlines; HTML headings after convert-or-DOM). Never split fenced code. Prepend breadcrumb `doc_title > H1 > H2` into the chunk text. Keep a code fence with its preceding explanation when they fit; otherwise duplicate the breadcrumb onto the code chunk.

3. Lexical index (default, always on, no downloads). SQLite FTS5 with a tokenizer that emits original tokens plus camelCase/snake_case pieces plus path segments. BM25 is the only retriever when embeddings are off. This is the Claude Code-compatible path.

4. Vector store. Primary: SQLite for FTS and, while embeddings are small, sqlite-vec brute-force (int8 or bit if we quantize). Graduate a repo to LanceDB IVF_PQ/IVF_RQ when chunk count or latency demands ANN. Do not ship Chroma or FAISS as the default. Windows wheels exist for both sqlite-vec and LanceDB.

5. Embedding model (optional). Off by default. When enabled locally, prefer CodeRankEmbed (MIT, 137M, 768-d, 8k, CoIR 60.1) for code-heavy corpora, or Qwen3-Embedding-0.6B (Apache 2.0, 1024-d Matryoshka, 32k, MTEB Code 75.41) if one model must cover code and docs. Truncate Qwen3 to 256-512-d for storage. Skip jina-code-embeddings as the default because of CC-BY-NC-4.0. Skip nomic-embed-code (7B) on CPU. Expose an OpenAI-compatible embeddings URL for voyage-code-3/4 or a hosted Qwen.

6. Embedding runtime. FastEmbed/ONNX for MiniLM/bge-class models; sentence-transformers for CodeRankEmbed, Qwen3-Embedding, Granite, EmbeddingGemma. Optional model2vec `potion-code-16M-v2` as a no-transformer dense first stage. Optional Ollama/llama-server as a user-supplied endpoint, not a required daemon.

7. Fusion and rerank. Hybrid = FTS5 BM25 + dense, fused with RRF k=60. Optional CPU rerank: Qwen3-Reranker-0.6B (Apache 2.0, strong MTEB Code) or FastEmbed MiniLM cross-encoder for latency. Do not use bge-reranker-v2-m3 as the code reranker (CoIR 36.28 on the Jina comparison table). Rerank is optional and off by default on small machines.

8. Agent API. Tools: `search` (hybrid), `grep` / exact symbol, `read` with line range, `outline` (file or repo-map style signatures). Default 10 snippets, each with path and line range, each small enough that 10 fit a few thousand tokens. Offer `k=20` and "expand this hit to the rest of the file". Include a cheap repo map (Aider-style, token-budgeted) as orientation, not as a substitute for search.

9. Make optional, in this order. (a) Embeddings. (b) Cross-encoder rerank. (c) LLM contextual prefixes (Anthropic-style) at index time. (d) Call-graph / LSP (Serena-like) for references. (e) Cloud embedders (voyage-code-4).

10. Do not. Function-only chunks. Header-stripped Markdown. Chroma as the laptop store. A required GPU. A required network call. CC-BY-NC weights in the default wheel. Claiming vector search replaces grep.
