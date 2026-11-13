"""Optional embeddings with explicit download and remote-endpoint consent.

Importing this module uses only the standard library. Local model paths never
fall through to hub loading. Set allow_download only during explicit setup or
indexing; the application must persist endpoint consent with index metadata.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass, replace
from http.client import HTTPException
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_MODEL = "minishlab/potion-code-16M-v2"
DEFAULT_REVISION = "e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b"
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_TIMEOUT = 30
_MAX_RESPONSE = 8 * 1024 * 1024
_MAX_REQUEST = 1024 * 1024


@dataclass(frozen=True)
class EmbedConfig:
    provider: str = "none"
    model: str | None = None
    revision: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    model_dir: str | None = None
    cache_dir: str | None = None
    allow_remote: bool = False
    allow_download: bool = False
    batch_size: int = 32
    max_input_chars: int = 8000
    runtime_dir: str | None = None


class EmbeddingError(RuntimeError):
    pass


class ConsentRequired(EmbeddingError):
    pass


class EmbeddingProvider(Protocol):
    identity: dict
    truncated: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
    def close(self) -> None: ...


def _url_parts(url: str):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment or "\\" in url
                or any(ord(c) < 33 or ord(c) == 127 for c in url)):
            raise ValueError()
        _ = parts.port
        return parts
    except (TypeError, ValueError):
        raise EmbeddingError("Embedding URL must be HTTP(S), without credentials, query or fragment") from None


def is_loopback_url(url: str) -> bool:
    try:
        host = _url_parts(url).hostname.lower()
        # Only the explicitly approved spellings count as local. No DNS alias.
        return host in ("localhost", "127.0.0.1", "::1")
    except EmbeddingError:
        return False


def config_from_env(base: EmbedConfig | None = None) -> EmbedConfig:
    config = base or EmbedConfig()
    fields = {"provider": "LEGACY_EMBED_PROVIDER", "base_url": "LEGACY_EMBED_BASE_URL",
              "model": "LEGACY_EMBED_MODEL", "api_key_env": "LEGACY_EMBED_API_KEY_ENV",
              "model_dir": "LEGACY_EMBED_MODEL_DIR"}
    # Ambient environment never grants remote or download permission.
    return replace(config, **{key: os.environ[name] for key, name in fields.items() if name in os.environ})


def _normalized(row) -> list[float]:
    if hasattr(row, "tolist"):
        row = row.tolist()
    try:
        valid = (isinstance(row, list) and bool(row)
                 and all(not isinstance(v, bool) and isinstance(v, (float, int)) and math.isfinite(v) for v in row))
    except OverflowError:
        valid = False
    if not valid:
        raise EmbeddingError("Embedding response must contain finite nonboolean vectors")
    norm = math.hypot(*row)
    if not norm or not math.isfinite(norm):
        raise EmbeddingError("Embedding response contains a zero or invalid vector")
    return [float(v) / norm for v in row]


def _task_text(texts: list[str], model: str, query: bool) -> list[str]:
    # Nomic's published retrieval contract is asymmetric, including when it is
    # served through Ollama or llama.cpp's otherwise task-agnostic HTTP API.
    if "nomic-embed-text" in model.lower():
        prefix = "search_query: " if query else "search_document: "
        return [t if t.startswith(prefix) else prefix + t for t in texts]
    return texts


class _Provider:
    def __init__(self, config: EmbedConfig):
        self.config = config
        self.identity = {"provider": config.provider, "model": config.model,
                         "revision": config.revision, "dimension": None, "normalized": True}
        self.truncated = 0
        self.closed = False
        self._lock = threading.RLock()

    def _prepare(self, texts: list[str]) -> list[str]:
        if self.closed:
            raise EmbeddingError("Embedding provider is closed")
        if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
            raise EmbeddingError("Embedding inputs must be a list of strings")
        self.truncated += sum(len(t) > self.config.max_input_chars for t in texts)
        return [t[:self.config.max_input_chars] for t in texts]

    def _finish(self, rows, expected: int) -> list[list[float]]:
        rows = list(rows)
        if len(rows) != expected:
            raise EmbeddingError("Embedding response has the wrong number of vectors")
        result = [_normalized(row) for row in rows]
        for row in result:
            dimension = self.identity["dimension"]
            if dimension is not None and dimension != len(row):
                raise EmbeddingError("Embedding dimension changed")
            self.identity["dimension"] = len(row)
        return result

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def close(self) -> None:
        with self._lock:
            self.closed = True


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _HTTPProvider(_Provider):
    def __init__(self, config: EmbedConfig):
        super().__init__(config)
        if not config.base_url or not config.model:
            raise EmbeddingError("openai-compatible requires base_url and model")
        parts = _url_parts(config.base_url)
        self._local = is_loopback_url(config.base_url)
        if not self._local and not config.allow_remote:
            raise ConsentRequired("Remote embedding endpoint requires allow_remote=True; code leaves this machine")
        path = parts.path.rstrip("/")
        if not path.endswith("/embeddings"):
            path += "/embeddings"
        self._url = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.identity.update({"base_url": urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', '')),
                              "allow_remote": config.allow_remote,
                              "task_settings": "nomic search_document/search_query prefixes" if "nomic-embed-text" in config.model.lower()
                              else "endpoint-defined; caller must version model and task settings",
                              "max_input_chars": config.max_input_chars, "tokenCountKnown": False})
        if config.api_key_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config.api_key_env):
            raise EmbeddingError("api_key_env must name an environment variable")

    def _check_endpoint(self):
        if self._local:
            parts = _url_parts(self._url)
            if parts.hostname.lower() == "localhost":
                try:
                    addresses = socket.getaddrinfo("localhost", parts.port or (443 if parts.scheme == "https" else 80),
                                                   type=socket.SOCK_STREAM)
                    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_loopback for a in addresses):
                        raise EmbeddingError("localhost must resolve only to loopback addresses")
                except OSError:
                    raise EmbeddingError("Cannot resolve local embedding endpoint") from None

    def _request(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.config.model, "input": texts}, ensure_ascii=True).encode("utf-8")
        if len(body) > _MAX_REQUEST:
            if len(texts) == 1:
                raise EmbeddingError("Embedding input exceeds one MiB request limit")
            midpoint = len(texts) // 2
            return self._request(texts[:midpoint]) + self._request(texts[midpoint:])
        self._check_endpoint()
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            key = os.environ.get(self.config.api_key_env)
            if not key or "\r" in key or "\n" in key:
                raise EmbeddingError("Embedding API key environment variable is missing or invalid")
            headers["Authorization"] = "Bearer " + key
        try:
            with self._opener.open(Request(self._url, data=body, headers=headers, method="POST"), timeout=_TIMEOUT) as response:
                payload = response.read(_MAX_RESPONSE + 1)
                if len(payload) > _MAX_RESPONSE:
                    raise EmbeddingError("Embedding response exceeds eight MiB limit")
        except HTTPError as exc:
            code = exc.code
            exc.close()
            # Discard bodies/reason/URL entirely: servers can echo credentials or source.
            raise EmbeddingError(f"Embedding endpoint returned HTTP {code}; response body redacted") from None
        except (URLError, OSError, ValueError, HTTPException):
            raise EmbeddingError("Embedding endpoint request failed; transport details redacted") from None
        try:
            data = json.loads(payload)["data"]
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError()
            by_index = {}
            for item in data:
                index = item["index"]
                if type(index) is not int or not 0 <= index < len(texts) or index in by_index:
                    raise ValueError()
                by_index[index] = item["embedding"]
            return self._finish([by_index[i] for i in range(len(texts))], len(texts))
        except (KeyError, ValueError, TypeError, UnicodeError, RecursionError):
            raise EmbeddingError("Invalid embedding response structure; body redacted") from None

    def _embed(self, texts: list[str], query: bool) -> list[list[float]]:
        with self._lock:
            if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
                raise EmbeddingError("Embedding inputs must be a list of strings")
            texts = self._prepare(_task_text(texts, self.config.model, query))
            output = []
            for start in range(0, len(texts), self.config.batch_size):
                output.extend(self._request(texts[start:start + self.config.batch_size]))
            return output

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, False)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], True)[0]


def _manifest(path: Path, names: list[str]) -> dict[str, str]:
    hashes = {}
    for name in sorted(set(names)):
        file = path / name
        if not file.is_file():
            raise EmbeddingError("Local model files are incomplete; prepare the model during explicit setup")
        with file.open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashes


class _LocalProvider(_Provider):
    def __init__(self, config: EmbedConfig):
        if config.model is None:
            config = replace(config, model=DEFAULT_MODEL, revision=config.revision or DEFAULT_REVISION)
        super().__init__(config)
        name = config.model
        if name.startswith("model2vec:"):
            runtime, name = "model2vec", name.removeprefix("model2vec:")
        elif name.startswith("fastembed:"):
            runtime, name = "fastembed", name.removeprefix("fastembed:")
        else:
            runtime = "model2vec" if name.startswith("minishlab/") else "fastembed"
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) or any(p in (".", "..") for p in name.split("/")):
            raise EmbeddingError("Local model must be a hub ID, optionally prefixed model2vec: or fastembed:")
        try:
            if runtime == "model2vec":
                from model2vec import StaticModel
                repo = name
                files = ["config.json", "model.safetensors", "tokenizer.json"]
            else:
                import onnxruntime
                onnxruntime.disable_telemetry_events()
                from fastembed import TextEmbedding
                descriptions = TextEmbedding.list_supported_models()
                description = next((d for d in descriptions if d["model"].lower() == name.lower()), None)
                if not description or not description["sources"].get("hf"):
                    raise EmbeddingError("Model has no supported FastEmbed Hugging Face manifest")
                repo = description["sources"]["hf"]
                files = [description["model_file"], "config.json", "tokenizer.json", "tokenizer_config.json",
                         "special_tokens_map.json", *description.get("additional_files", [])]
        except ImportError:
            raise EmbeddingError(f"Optional {runtime} runtime is missing; install requirements during setup") from None
        if config.model_dir:
            path = Path(config.model_dir).expanduser().resolve()
            if not path.is_dir():
                raise EmbeddingError("model_dir must be an existing directory")
            hashes = _manifest(path, files)
        else:
            if not config.cache_dir:
                raise EmbeddingError("local-python requires model_dir or an explicit cache_dir")
            if not config.revision or not _SHA.fullmatch(config.revision):
                if config.allow_download:
                    raise ConsentRequired("Downloading a model requires an immutable 40-character revision")
                raise EmbeddingError("Cache lookup requires the model's immutable revision or model_dir")
            path = Path(config.cache_dir).expanduser().resolve() / repo.replace("/", "--") / config.revision
            try:
                hashes = _manifest(path, files)
            except EmbeddingError:
                if not config.allow_download:
                    raise ConsentRequired("Model files are absent; explicit allow_download=True is required during setup") from None
                try:
                    from huggingface_hub import snapshot_download
                    snapshot_download(repo, revision=config.revision, local_dir=str(path),
                                      allow_patterns=files, token=False)
                    hashes = _manifest(path, files)
                except Exception:
                    raise EmbeddingError("Pinned model download failed; details redacted") from None
        try:
            if runtime == "model2vec":
                # No hub ID reaches Model2Vec. Disable its default 512-token
                # truncation: static averaging is bounded by max_input_chars.
                self._model = StaticModel.from_pretrained(str(path), normalize=True, max_length=None, force_download=False)
                dimension = self._model.embedding.shape[1]
                token_limit = None
            else:
                self._model = TextEmbedding(model_name=name, specific_model_path=str(path),
                                            cache_dir=str(path), local_files_only=True,
                                            threads=min(4, os.cpu_count() or 1), providers=["CPUExecutionProvider"])
                dimension = self._model.embedding_size
                tokenizer = getattr(self._model.model, "tokenizer", None)
                token_limit = tokenizer.truncation.get("max_length") if tokenizer and tokenizer.truncation else None
        except Exception:
            raise EmbeddingError(f"Cannot load local {runtime} model; check pinned runtime and complete model files") from None
        self._runtime = runtime
        self.identity.update({"model": name, "dimension": int(dimension), "runtime": runtime,
                              "model_repo": repo, "manifest_sha256": hashes, "token_limit": token_limit,
                              "task_settings": "symmetric static mean" if runtime == "model2vec" else "fastembed passage_embed/query_embed",
                              "max_input_chars": config.max_input_chars, "tokenCountKnown": False,
                              "token_truncation_observable": runtime == "fastembed"})

    def _run(self, texts: list[str], query: bool) -> list[list[float]]:
        with self._lock:
            original = texts
            texts = self._prepare(texts)
            output = []
            try:
                for start in range(0, len(texts), self.config.batch_size):
                    batch = texts[start:start + self.config.batch_size]
                    if self._runtime == "model2vec":
                        rows = self._model.encode(batch, use_multiprocessing=False)
                    else:
                        tokenizer = getattr(self._model.model, "tokenizer", None)
                        if tokenizer:
                            self.truncated += sum(bool(e.overflowing) and len(original[start + i]) <= self.config.max_input_chars
                                                  for i, e in enumerate(tokenizer.encode_batch(batch)))
                        method = self._model.query_embed if query else self._model.passage_embed
                        rows = method(batch, batch_size=self.config.batch_size)
                    output.extend(self._finish(rows, len(batch)))
                return output
            except EmbeddingError:
                raise
            except Exception:
                raise EmbeddingError("Local embedding inference failed; input and runtime details redacted") from None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._run(texts, False)

    def embed_query(self, text: str) -> list[float]:
        return self._run([text], True)[0]

    def close(self) -> None:
        with self._lock:
            self._model = None
            self.closed = True


class _JSProvider(_Provider):
    def __init__(self, config: EmbedConfig):
        super().__init__(config)
        if not config.model or not config.revision or not _SHA.fullmatch(config.revision):
            raise EmbeddingError("transformers-js requires model and immutable 40-character revision")
        if not config.cache_dir or not config.runtime_dir:
            raise EmbeddingError("transformers-js requires cache_dir and runtime_dir")
        cache = Path(config.cache_dir).expanduser().resolve()
        runtime = Path(config.runtime_dir).expanduser().resolve()
        helper = Path(__file__).resolve().parents[1] / "retrieval" / "embed.mjs"
        if not helper.is_file() or not (runtime / "node_modules/@huggingface/transformers/src/transformers.js").is_file():
            raise EmbeddingError("Transformers.js helper/runtime is missing; install during explicit setup")
        if config.allow_download:
            cache.mkdir(parents=True, exist_ok=True)
        elif not cache.is_dir():
            raise ConsentRequired("Transformers.js cache is missing; explicit model download is required")
        node = shutil.which("node")
        if not node:
            raise EmbeddingError("Node.js is required by transformers-js")
        # Do not inherit credentials, proxies, NODE_OPTIONS or loader hooks.
        env = {k: os.environ[k] for k in ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "TMPDIR") if k in os.environ}
        env.update({"HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HF_HUB_OFFLINE": "0" if config.allow_download else "1"})
        try:
            self._process = subprocess.Popen([node, str(helper), config.model, config.revision, str(cache), str(runtime),
                                              "download" if config.allow_download else "offline"],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                             env=env, text=True, encoding="utf-8", bufsize=1)
        except OSError:
            raise EmbeddingError("Cannot start Transformers.js helper") from None
        self._responses: queue.Queue = queue.Queue(maxsize=1)
        self._cancelled = threading.Event()
        self._reader = threading.Thread(target=self._read, name="embedding-js-reader", daemon=True)
        self._reader.start()
        self.identity.update({"task_settings": "mean pooling; q8 CPU; symmetric", "max_input_chars": min(config.max_input_chars, 12000),
                              "tokenCountKnown": False})

    def _write(self, batch: list[str]) -> None:
        # A cold model (or a broken helper) might not read stdin. Bound writes
        # too: a JSON batch can exceed the OS pipe buffer before inference starts.
        written: queue.Queue = queue.Queue(maxsize=1)
        def send():
            try:
                self._process.stdin.write(json.dumps(batch) + "\n")
                self._process.stdin.flush()
                written.put(None)
            except (OSError, ValueError):
                written.put(EmbeddingError("Cannot write embedding helper input"))
        writer = threading.Thread(target=send, name="embedding-js-writer", daemon=True)
        writer.start()
        try:
            result = written.get(timeout=_TIMEOUT)
            if isinstance(result, EmbeddingError):
                raise result
        except queue.Empty:
            # Kill before joining; otherwise a writer blocked on a full pipe
            # would prevent deterministic cleanup.
            self.close()
            raise EmbeddingError("Transformers.js input write timed out") from None
        finally:
            writer.join(timeout=1)

    def _read(self):
        try:
            while not self._cancelled.is_set():
                line = self._process.stdout.readline(_MAX_RESPONSE + 1)
                if not line or len(line) > _MAX_RESPONSE or not line.endswith("\n"):
                    result = EmbeddingError("Transformers.js helper exited or exceeded response limit")
                else:
                    result = line
                while not self._cancelled.is_set():
                    try:
                        self._responses.put(result, timeout=0.1)
                        break
                    except queue.Full:
                        pass
                if isinstance(result, EmbeddingError):
                    return
        except (OSError, ValueError, UnicodeError):
            if not self._cancelled.is_set():
                try:
                    self._responses.put_nowait(EmbeddingError("Invalid Transformers.js helper output"))
                except queue.Full:
                    pass

    def _embed(self, texts: list[str], query: bool) -> list[list[float]]:
        with self._lock:
            if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
                raise EmbeddingError("Embedding inputs must be a list of strings")
            original = _task_text(texts, self.config.model, query)
            texts = self._prepare(original)
            # The Node helper counts UTF-16 code units, while Python counts
            # Unicode code points. Preserve whole astral characters at its cap.
            for i, text in enumerate(texts):
                if len(text) <= 6000:
                    continue
                utf16 = text.encode("utf-16-le", "surrogatepass")
                if len(utf16) > 24000:
                    utf16 = utf16[:24000]
                    if 0xD800 <= int.from_bytes(utf16[-2:], "little") <= 0xDBFF:
                        utf16 = utf16[:-2]
                    texts[i] = utf16.decode("utf-16-le", "surrogatepass")
                    self.truncated += len(original[i]) <= self.config.max_input_chars
            output = []
            try:
                for start in range(0, len(texts), min(32, self.config.batch_size)):
                    batch = texts[start:start + min(32, self.config.batch_size)]
                    self._write(batch)
                    response = self._responses.get(timeout=_TIMEOUT)
                    if isinstance(response, EmbeddingError):
                        raise response
                    output.extend(self._finish(json.loads(response), len(batch)))
                return output
            except (OSError, ValueError, queue.Empty, EmbeddingError, RecursionError):
                self.close()
                raise EmbeddingError("Transformers.js embedding failed or timed out; helper output redacted") from None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, False)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], True)[0]

    def close(self) -> None:
        with self._lock:
            self.closed = True
            self._cancelled.set()
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait(timeout=5)
            for stream in (self._process.stdin, self._process.stdout):
                if stream:
                    stream.close()
            self._reader.join(timeout=1)


def create_provider(config: EmbedConfig) -> EmbeddingProvider | None:
    if config.provider == "none":
        return None
    if type(config.allow_remote) is not bool or type(config.allow_download) is not bool:
        raise EmbeddingError("allow_remote and allow_download must be explicit booleans")
    if (type(config.batch_size) is not int or not 1 <= config.batch_size <= 1024
            or type(config.max_input_chars) is not int or not 1 <= config.max_input_chars <= 1_000_000):
        raise EmbeddingError("batch_size must be 1..1024 and max_input_chars 1..1000000")
    if config.provider == "openai-compatible":
        return _HTTPProvider(config)
    if config.provider == "local-python":
        return _LocalProvider(config)
    if config.provider == "transformers-js":
        # Existing helper's public protocol has a stricter character limit.
        return _JSProvider(replace(config, max_input_chars=min(config.max_input_chars, 12000)))
    raise EmbeddingError("Unknown embedding provider")
