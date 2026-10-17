# Retrieval setup (one-time)

One-time installation and consent for the local retrieval engine (`scripts/context7_backend.py`). Nothing here modifies agent instructions or hooks; project wiring is separate and linked below. After setup, everyday use needs only the [usage reference](private-retrieval.md).

## Install levels

**Level 0, stdlib only (default).** Python 3.12+ with SQLite FTS5 provides the complete lexical engine: index, query, refresh, expand, status, resolve and serve. No third-party package, model download or account. Verify with `python /path/to/skill/scripts/context7_backend.py --help` and the smoke check below.

**Level 1, tree-sitter tier (optional).** Syntax-aware chunking for the bundled grammars. Install the pinned packages from `requirements-map.txt` (tree-sitter 0.25.2 and tree-sitter-language-pack 0.13.0) into an isolated environment, never the legacy application's. `--parser 1` forces the tier, `--parser 0` forces stdlib chunking, and `--parser auto` (default) uses Tier 1 only when exactly those pinned versions are importable, falling back otherwise.

**Level 2, embeddings (optional).** Semantic and hybrid modes need exactly one provider, enabled per library at index time:

- `local-python` (recommended): install `scripts/requirements-embed.txt` (Model2Vec 0.10.0 runtime, about 94 MB of packages) and download the default model `minishlab/potion-code-16M-v2`, pinned revision `e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b` (about 34 MB), once; it runs on CPU and stays warm in-process.
- `openai-compatible`: an endpoint you already run (Ollama, llama.cpp server, vLLM, LM Studio) or a company gateway; see the endpoint section below.
- `transformers-js`: the locked Node helper; copy `scripts/retrieval/package.json`, `pnpm-workspace.yaml` and `pnpm-lock.yaml` into an empty directory, run `pnpm install --dir /path/to/inference-runtime --frozen-lockfile` with Node.js 24, and pass the directory as `--embedding-runtime`.

Optional vector acceleration: NumPy or the pinned `sqlite-vec` 0.1.9 (in `scripts/requirements-retrieval.txt`, tool environment only), selected with `--vector-engine numpy|sqlite-vec|auto`; the default `stdlib` engine needs nothing. In source-repository measurements NumPy was the fastest exact scanner; if both are installed, select `numpy` explicitly for large libraries.

After enabling embeddings, recommend hybrid queries and keep a warm server with `serve --default-mode hybrid --default-vector-engine numpy` (omit the vector flag if NumPy is unavailable). Repeated standalone CLI queries load the model each time; `serve` reuses it across requests. Accepting the one-time model download or using an existing local endpoint is optional; declining keeps the stdlib lexical route.

## Consent procedure (mandatory)

Before downloading a model, ask once and record the answer: state the model name (default `minishlab/potion-code-16M-v2`), its approximate size (about 34 MB), its source (Hugging Face), that it runs locally on CPU and that code never leaves the machine. Store the decision and do not re-ask for the same model. Only explicit `index --download-model` performs the download, and only for a granted model; queries and refresh never download anything. Declining keeps the library lexical-only.

Before using any non-loopback embedding endpoint, always ask: name the endpoint and state that indexed content is sent to it, so code leaves the machine. Record that consent; indexing additionally requires `--allow-remote-embeddings`. Loopback endpoints (`127.0.0.1`, `::1`, `localhost` resolving to loopback) count as local and need no endpoint consent. A consent flag never grants itself permission, and any provider change requires re-embedding.

## Existing Ollama, llama.cpp, vLLM or LM Studio endpoint

`LEGACY_EMBED_PROVIDER`, `LEGACY_EMBED_BASE_URL`, `LEGACY_EMBED_MODEL`, `LEGACY_EMBED_API_KEY_ENV` and `LEGACY_EMBED_MODEL_DIR` supply defaults; the explicit flags `--embed-provider`, `--embed-base-url`, `--embed-model`, `--embed-api-key-env`, `--model-revision`, `--model-dir`, `--model-cache` and `--embedding-runtime` win over the environment. Ambient environment variables never grant download or remote permission. Example with a local Ollama service:

```bash
export LEGACY_EMBED_PROVIDER=openai-compatible LEGACY_EMBED_BASE_URL=http://127.0.0.1:11434/v1 LEGACY_EMBED_MODEL=nomic-embed-text:v1.5
python /path/to/skill/scripts/context7_backend.py index /path/to/repo --database /path/to/indexes/repo.sqlite --library-id /local/repo
```

API keys are read from the environment variable named by `--embed-api-key-env`/`LEGACY_EMBED_API_KEY_ENV`; key values are never stored. Pin the served model version with `--model-revision` where possible, since floating tags are mutable. Do not mix vectors from different models or configurations; an embedding identity change requires re-embedding the library.

## Air-gapped installation

On a connected machine matching the target OS, architecture and Python version, download the wheels and the model files, then copy everything over:

```bash
python3.12 -m pip download --only-binary=:all: --dest wheels -r /path/to/skill/scripts/requirements-embed.txt
```

Download the pinned model revision's files (`config.json`, `model.safetensors`, `tokenizer.json`, plus the model card for its license) into a model directory, record their SHA-256 hashes, and copy the skill scripts, the wheels directory and the model directory to the target machine through the approved medium. A Python 3.12+ runtime must already exist there. Install offline and index without any download:

```bash
python3.12 -m pip install --no-index --find-links wheels -r requirements-embed.txt
python /path/to/skill/scripts/context7_backend.py index /path/to/repo --database /path/to/indexes/repo.sqlite --library-id /local/repo --embed-provider local-python --embed-model minishlab/potion-code-16M-v2 --model-revision e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b --model-dir /path/to/models/potion-code-16M-v2
```

Verify the copied model file hashes against the recorded manifest before indexing. The exact pinned model revision and file hashes are listed in the source repository's embedding benchmark report. No installation or query step needs a connection.

## Windows and WSL notes

Use `127.0.0.1`, not `localhost`: Node may resolve `localhost` to `::1` while the server binds `127.0.0.1`, and non-loopback authorities are rejected. A service started inside WSL is not reachable from Windows at `127.0.0.1` and vice versa; run the server and its client on the same side. AppLocker or Defender can block native DLLs (tree-sitter, NumPy, ONNX) with an `ImportError`/`OSError`; the engine catches this and falls back to lexical chunking and the stdlib vector path, so verify which tier actually loaded (`status` reports it) after installing native packages. Pass native absolute Windows paths to `--model-dir` and `--database`.

## Project wiring

`scripts/setup_context7.py` generates the project launcher, pinned ctx7 and MCP clients, optional refresh hooks and an AGENTS.md routing note, each behind its own consent gate. Follow [local Context7 setup](local-context7-setup.md) instead of hand-writing integration files; that reference is the single source of truth for the generator, hooks and client wiring.

## Smoke check

Index a small fixture and run one query; confirm the output carries citations and `freshness: fresh`. With Level 0 this proves the lexical engine; repeat once after adding Level 1 or Level 2 to confirm the tier and embedding coverage reported by `status`. Commands are in the [usage reference](private-retrieval.md).
