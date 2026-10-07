#!/usr/bin/env python3
"""Local, source-grounded Context7-compatible retrieval example.

The SQLite path and optional model cache should be outside the indexed tree.
Only index downloads a model. Query and HTTP serving force local model files.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import queue
from pathlib import Path
import re
import sqlite3
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legacy_common import inference_environment
from repo_files import _candidates, _git, git_context, _safe_relative, _secret, read_safe_text, split_source_lines


EXTENSIONS = {".properties", ".gradle", ".kts", ".ini", ".conf", ".cfg", ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java", ".js", ".json", ".jsx", ".kt", ".md", ".mjs", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".xml", ".yaml", ".yml"}
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "target", ".next", ".venv", "venv", "__pycache__", ".cache"}
MAX_FILE_BYTES = 256_000
MAX_FILES = 10_000
MAX_SOURCE_CANDIDATES = 100_000
MAX_CHUNKS = 30_000
MAX_QUERY = 500
MAX_RESULTS = 10
MAX_REQUEST = 2048
HTTP_SQLITE_TIMEOUT = 1.0
WINDOW = 48
OVERLAP = 8
DEFAULT_CHUNK_CHARS = 1200
MAX_EMBEDDING_UNITS = 12000
MODEL_BATCH = 32
MAX_EMBEDDING_RESPONSE_CHARS = 8 * 1024 * 1024
INDEX_VERSION = "7"
DEFAULT_MODEL = "Xenova/all-MiniLM-L6-v2"
DEFAULT_MODEL_REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"
DEFAULT_RERANKER_REVISION = "a09144355adeed5f58c8ed011d209bf8ee5a1fec"
RERANK_BATCH = 8
MAX_CANDIDATES = 60
SYMBOL_RE = re.compile(r"\b(?:class|interface|enum|record|struct|trait|def|function|fn|const|let|var)\s+([A-Za-z_$][\w$]*)")
METHOD_RE = re.compile(r"\b(?:public|private|protected|static|final|async|export)\b[^;{}\n]*?\b([A-Za-z_$][\w$]*)\s*\([^;{}\n]*\)")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "there", "this", "to", "what", "when", "where", "which", "who", "with"}
MIN_SEMANTIC_SCORE = 0.30
RETRIEVAL = Path(__file__).resolve().parent / "retrieval" / "embed.mjs"
RERANK_HELPER = Path(__file__).resolve().parent / "retrieval" / "rerank.mjs"


class RetrievalError(Exception):
    pass


class VectorAdapterUnavailable(RetrievalError):
    pass


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def revision(root: Path) -> str:
    if not git_context(root):
        return "non-git"
    head = _git(root, "rev-parse", "HEAD")
    return head.stdout.decode("ascii", "replace").strip() if head.returncode == 0 else "non-git"


def allowed(path: Path, root: Path, kind: str) -> bool:
    if not path.is_relative_to(root):
        return False
    rel = _safe_relative(path.relative_to(root).as_posix())
    if _secret(rel):
        return False
    if any(part in SKIP_DIRS or (root.joinpath(*rel.parts[:i + 1])).is_symlink() for i, part in enumerate(rel.parts[:-1])):
        return False
    if path.is_symlink() or not path.is_file():
        return False
    if kind == "docs":
        return path.suffix.lower() == ".md"
    return path.suffix.lower() in EXTENSIONS


def normalize_excludes(excludes) -> tuple[str, ...]:
    if not isinstance(excludes, (tuple, list)):
        raise RetrievalError("Exclusions must be a list of relative paths")
    normalized = []
    for value in excludes:
        if not isinstance(value, str):
            raise RetrievalError("Exclusions must contain relative path strings")
        try:
            value.encode("utf-8")
            path = _safe_relative(value, cli_input=True).as_posix()
            if path == "." or re.match(r"^[A-Za-z]:", path) or any(c in path for c in "*?\x00"):
                raise ValueError("expected a relative file or directory path without glob patterns")
        except (ValueError, UnicodeError) as exc:
            raise RetrievalError(f"Invalid exclusion {value!r}: {exc}") from exc
        normalized.append(path)
    return tuple(sorted(set(normalized)))


def stored_excludes(meta: dict[str, str]) -> tuple[str, ...]:
    try:
        value = json.loads(meta.get("excludes", "[]"))
        return normalize_excludes(value)
    except (TypeError, ValueError, RetrievalError) as exc:
        raise RetrievalError(f"Invalid exclusion metadata; repair metadata or use a fresh database: {exc}") from exc


def safe_skipped_path(relative: str) -> str:
    display = json.dumps(relative.encode("utf-8", "replace").decode("utf-8"), ensure_ascii=False)[1:-1]
    return "".join(f"\\u{ord(character):04x}" if 127 <= ord(character) < 160 or character in "\u2028\u2029" else character for character in display)


def enumerate_files(root: Path, kind: str, excludes: tuple[str, ...] = (), skipped: list[dict[str, str]] | None = None) -> list[Path]:
    paths = []
    seen = 0
    iterator = _candidates(root, git_context(root), ())
    try:
        for relative in iterator:
            seen += 1
            if seen > MAX_SOURCE_CANDIDATES:
                raise RetrievalError(f"Candidate limit {MAX_SOURCE_CANDIDATES} exceeded; index a smaller subtree")
            try:
                relative.encode("utf-8")
            except UnicodeEncodeError:
                if skipped is not None:
                    display = safe_skipped_path(relative)
                    skipped.append({"kind": "docs" if kind == "docs" else "code", "path": display, "reason": "non-UTF-8 filename"})
                continue
            if any(ord(character) < 32 or 127 <= ord(character) < 160 or character in "\u2028\u2029" for character in relative):
                if skipped is not None:
                    display = safe_skipped_path(relative)
                    skipped.append({"kind": "docs" if kind == "docs" else "code", "path": display, "reason": "control character in path"})
                continue
            try:
                rel = _safe_relative(relative)
            except ValueError:
                continue
            if any(rel.as_posix() == item or rel.as_posix().startswith(item + "/") for item in excludes):
                continue
            path = root.joinpath(*rel.parts)
            if allowed(path, root, kind):
                paths.append(path)
                if len(paths) > MAX_FILES:
                    raise RetrievalError(f"File limit {MAX_FILES} exceeded; index a smaller subtree")
    except ValueError as exc:
        raise RetrievalError(f"Cannot inventory source: {exc}") from exc
    finally:
        iterator.close()
    return sorted(paths, key=lambda p: p.as_posix())


def corpus_files(root: Path, docs_root: Path | None, excludes: tuple[str, ...] = (), skipped: list[dict[str, str]] | None = None) -> list[tuple[str, str, Path]]:
    result = [("repo-docs" if p.suffix.lower() == ".md" else "code", p.relative_to(root).as_posix(), p) for p in enumerate_files(root, "code", excludes, skipped)]
    if docs_root:
        result = [entry for entry in result if not entry[2].is_relative_to(docs_root)]
        result += [("docs", p.relative_to(docs_root).as_posix(), p) for p in enumerate_files(docs_root, "docs", excludes, skipped)]
    if len(result) > MAX_FILES:
        raise RetrievalError(f"File limit {MAX_FILES} exceeded; index a smaller subtree")
    return sorted(result, key=lambda row: (row[0], row[1]))


def connect(path: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    if not path.is_file():
        raise RetrievalError(f"Database does not exist: {path}")
    con = sqlite3.connect(path, timeout=timeout, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def load_sqlite_vec(con: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise VectorAdapterUnavailable("sqlite-vec 0.1.9 is required; install the optional pinned package") from exc
    enable = getattr(con, "enable_load_extension", None)
    if not callable(enable) or not callable(getattr(con, "load_extension", None)):
        raise VectorAdapterUnavailable("This Python sqlite3 runtime cannot load extensions; use a Python build with --enable-loadable-sqlite-extensions (for example Homebrew Python on macOS), or select --vector-engine stdlib/auto")
    try:
        enable(True)
    except sqlite3.Error as exc:
        raise VectorAdapterUnavailable(f"This SQLite runtime cannot enable extension loading: {exc}; use an extension-capable Python build or select --vector-engine stdlib/auto") from exc
    try:
        try:
            sqlite_vec.load(con)
        finally:
            enable(False)
        version = con.execute("SELECT vec_version()").fetchone()[0]
    except (AttributeError, OSError, sqlite3.Error) as exc:
        # An installed but broken/incompatible adapter is an error, rather than
        # a missing capability that auto may quietly replace with stdlib.
        raise RetrievalError(f"Installed sqlite-vec adapter failed to load: {exc}") from exc
    if version not in ("v0.1.9", "0.1.9"):
        raise RetrievalError(f"sqlite-vec 0.1.9 required; found {version}")


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def pack_vector(vector: list[float]) -> bytes:
    if not isinstance(vector, (list, tuple)) or not vector or not all(_finite_number(x) for x in vector):
        raise RetrievalError("Embedding contains invalid values")
    try:
        norm = math.sqrt(math.sumprod(vector, vector))
    except (OverflowError, ValueError) as exc:
        raise RetrievalError("Embedding normalization norm is invalid or overflowed") from exc
    if not math.isfinite(norm):
        raise RetrievalError("Embedding normalization norm is not finite")
    if not norm:
        raise RetrievalError("Embedding has zero length")
    return struct.pack(f"<{len(vector)}f", *(x / norm for x in vector))


def unpack_vector(data: bytes) -> tuple[float, ...]:
    if len(data) % 4:
        raise RetrievalError("Stored embedding has invalid float32 length; reindex")
    return struct.unpack(f"<{len(data) // 4}f", data)


def setup(con: sqlite3.Connection) -> None:
    for statement in (
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS files(kind TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL, size INTEGER NOT NULL, PRIMARY KEY(kind,path))",
        "CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, body TEXT NOT NULL, symbols TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS chunk_vectors(chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE, embedding BLOB NOT NULL)",
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(body, symbols, path)",
        "CREATE INDEX IF NOT EXISTS chunks_file ON chunks(kind,path)",
    ):
        con.execute(statement)


def metadata(con: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in con.execute("SELECT key,value FROM meta")}


def _validate_numeric_metadata(meta: dict[str, str]) -> None:
    bounds = {"chunk_chars": (128, 12000), "oversized_chunks": (0, MAX_CHUNKS), "vector_dim": (1, None)}
    for field, (minimum, maximum) in bounds.items():
        if field == "vector_dim" and field not in meta:
            continue
        message = f"Index numeric metadata {field} is invalid; restore a valid index or use a fresh database"
        try:
            value = int(meta[field])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RetrievalError(message) from exc
        if value < minimum or (maximum is not None and value > maximum):
            raise RetrievalError(message)


def indexed_metadata(con: sqlite3.Connection) -> dict[str, str]:
    result = metadata(con)
    if not result:
        raise RetrievalError("Database is not indexed; restore a valid index or use a fresh database")
    if isinstance(result.get("index_version"), str) and result["index_version"] != INDEX_VERSION:
        raise RetrievalError("Index format changed; reindex before querying")
    required = {"root", "docs_root", "library_id", "revision", "index_version", "corpus_id", "chunk_chars", "oversized_chunks", "embed_model", "model_revision", "reranker_model", "reranker_revision", "vector_engine", "model_cache", "embedding_runtime"}
    if not required <= result.keys() or any(not isinstance(value, str) for value in result.values()) or not result["root"] or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", result["library_id"]):
        raise RetrievalError("Index metadata is incomplete or malformed; restore a valid index or use a fresh database")
    _validate_numeric_metadata(result)
    stored_excludes(result)
    return result


def existing_index_metadata(con: sqlite3.Connection) -> dict[str, str]:
    objects = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'")}
    if not objects:
        return {}
    message = "Database is not a recognized retrieval index; use a new database"
    if "meta" not in objects:
        raise RetrievalError(message)
    try:
        rows = con.execute("SELECT key,value FROM meta").fetchall()
    except sqlite3.Error as exc:
        raise RetrievalError(message + " (malformed metadata)") from exc
    if not rows or any(not isinstance(row[0], str) or not isinstance(row[1], str) for row in rows) or len({row[0] for row in rows}) != len(rows):
        raise RetrievalError(message + " (empty or malformed metadata)")
    result = dict(rows)
    if result.get("index_version") not in {str(v) for v in range(1, int(INDEX_VERSION) + 1)} or not result.get("root") or "docs_root" not in result or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", result.get("library_id", "")):
        raise RetrievalError(message + " (unknown or incomplete metadata)")
    if result["index_version"] == INDEX_VERSION:
        _validate_numeric_metadata(result)
    stored_excludes(result)
    return result


def put_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def validate_chunk_chars(chunk_chars: int) -> None:
    if type(chunk_chars) is not int or not 128 <= chunk_chars <= 12000:
        raise RetrievalError("--chunk-chars must be an integer from 128 to 12000")


def chunks_for(text: str, chunk_chars: int = DEFAULT_CHUNK_CHARS):
    """Keep exact whole source lines, with bounded overlap and no coverage gaps."""
    validate_chunk_chars(chunk_chars)
    lines = split_source_lines(text)
    offset = 0
    while offset < len(lines):
        end, size = offset, 0
        while end < len(lines) and end - offset < WINDOW:
            addition = len(lines[end]) + (1 if end > offset else 0)
            if end > offset and size + addition > chunk_chars:
                break
            size += addition
            end += 1
        body = "\n".join(lines[offset:end])
        symbols = " ".join(SYMBOL_RE.findall(body) + METHOD_RE.findall(body))
        yield offset + 1, end, body, symbols
        if end == len(lines):
            break
        following = max(offset + 1, end - OVERLAP)
        # Retain only overlap that leaves room for a new line. An indivisible
        # oversized next line starts its own chunk rather than duplicating an
        # overlap-only chunk. Every yielded chunk therefore extends coverage.
        while following < end and len("\n".join(lines[following:end + 1])) > chunk_chars:
            following += 1
        offset = following


@contextmanager
def _helper_responses(proc: subprocess.Popen[str], limit: int, kind: str):
    responses: queue.Queue[str | None | RetrievalError] = queue.Queue(maxsize=1)
    cancelled = threading.Event()
    def send_response(response: str | None | RetrievalError) -> bool:
        while not cancelled.is_set():
            try:
                responses.put(response, timeout=0.1)
                return True
            except queue.Full:
                pass
        return False

    def read_outputs():
        assert proc.stdout is not None
        try:
            while not cancelled.is_set():
                line = proc.stdout.readline(limit + 1)
                if not line:
                    send_response(None)
                    return
                if len(line) > limit or not line.endswith("\n"):
                    send_response(RetrievalError(f"Invalid {kind} output: response exceeds limit or is unterminated"))
                    return
                if not send_response(line):
                    return
        except (OSError, UnicodeError, ValueError) as exc:
            if not cancelled.is_set():
                send_response(RetrievalError(f"Invalid {kind} output: {exc}"))
    reader = threading.Thread(target=read_outputs, name=f"local-{kind}-reader", daemon=True)
    reader.start()
    try:
        yield responses
    finally:
        cancelled.set()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        reader.join(timeout=1)
        if proc.stdout:
            proc.stdout.close()


def embedding_batches(batches: list[list[str]], model: str, model_revision: str, cache: Path, runtime: Path, *, download: bool):
    if not batches:
        return
    if not RETRIEVAL.is_file():
        raise RetrievalError("Embedding helper is missing")
    if download:
        cache.mkdir(parents=True, exist_ok=True)
    elif not cache.is_dir():
        raise RetrievalError("Local model cache is missing; run explicit model download at index time")
    env = inference_environment(cache, download=download)
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errors:
        try:
            proc = subprocess.Popen(["node", str(RETRIEVAL), model, model_revision, str(cache), str(runtime), "download" if download else "offline"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, env=env, bufsize=1)
        except OSError as exc:
            raise RetrievalError(f"Local embedding helper failed: {exc}") from exc
        with _helper_responses(proc, MAX_EMBEDDING_RESPONSE_CHARS, "embedding") as responses:
            try:
                for texts in batches:
                    if len(texts) > MODEL_BATCH:
                        raise RetrievalError("Embedding batch exceeds limit")
                    assert proc.stdin is not None
                    proc.stdin.write(json.dumps(texts, separators=(",", ":")) + "\n")
                    proc.stdin.flush()
                    try:
                        output = responses.get(timeout=120)
                    except queue.Empty as exc:
                        raise RetrievalError("Local embedding helper timed out") from exc
                    if isinstance(output, RetrievalError):
                        raise output
                    if output is None:
                        errors.seek(0)
                        raise RetrievalError(f"Local embedding helper failed: {errors.read(400)}")
                    try:
                        vectors = json.loads(output)
                        if not isinstance(vectors, list) or len(vectors) != len(texts) or not all(isinstance(row, list) and row for row in vectors):
                            raise ValueError("wrong embedding shape")
                        if not all(_finite_number(value) for row in vectors for value in row):
                            raise ValueError("expected finite nonboolean numbers in embedding rows")
                        yield vectors
                    except (ValueError, TypeError) as exc:
                        raise RetrievalError(f"Invalid embedding output: {exc}") from exc
                proc.stdin.close()
                if proc.wait(timeout=15):
                    errors.seek(0)
                    raise RetrievalError(f"Local embedding helper failed: {errors.read(400)}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RetrievalError(f"Local embedding helper failed: {exc}") from exc


def embeddings(texts: list[str], model: str, cache: Path, runtime: Path, *, download: bool, model_revision: str = DEFAULT_MODEL_REVISION) -> list[list[float]]:
    if not texts:
        return []
    if len(texts) > MODEL_BATCH:
        raise RetrievalError("Embedding batch exceeds limit")
    return list(embedding_batches([texts], model, model_revision, cache, runtime, download=download))[0]


def reranker_scores(question: str, passages: list[str], model: str, model_revision: str, cache: Path, runtime: Path, *, download: bool) -> list[float]:
    if not RERANK_HELPER.is_file():
        raise RetrievalError("Reranker helper is missing")
    if len(passages) > MAX_CANDIDATES or any(len(p) > MAX_FILE_BYTES for p in passages):
        raise RetrievalError("Reranker candidate limit exceeded")
    if download:
        cache.mkdir(parents=True, exist_ok=True)
    elif not cache.is_dir():
        raise RetrievalError("Local reranker cache is missing; index with --reranker-model first")
    env = inference_environment(cache, download=download)
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errors:
        try:
            proc = subprocess.Popen(["node", str(RERANK_HELPER), model, model_revision, str(cache), str(runtime), "download" if download else "offline"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, env=env, bufsize=1)
        except OSError as exc:
            raise RetrievalError(f"Local reranker helper failed: {exc}") from exc
        with _helper_responses(proc, 4096, "reranker") as responses:
            scores: list[float] = []
            try:
                assert proc.stdin is not None
                for start in range(0, len(passages), RERANK_BATCH):
                    batch = passages[start:start + RERANK_BATCH]
                    proc.stdin.write(json.dumps({"query": question, "passages": batch}, separators=(",", ":")) + "\n")
                    proc.stdin.flush()
                    try:
                        output = responses.get(timeout=120)
                    except queue.Empty as exc:
                        raise RetrievalError("Local reranker helper timed out") from exc
                    if isinstance(output, RetrievalError):
                        raise output
                    if output is None:
                        errors.seek(0)
                        raise RetrievalError(f"Local reranker helper failed: {errors.read(400)}")
                    try:
                        values = json.loads(output)
                        if not isinstance(values, list) or len(values) != len(batch) or any(not _finite_number(value) for value in values):
                            raise ValueError("expected one finite scalar per passage")
                    except (ValueError, TypeError) as exc:
                        raise RetrievalError(f"Invalid reranker output: {exc}") from exc
                    scores.extend(float(value) for value in values)
                proc.stdin.close()
                if proc.wait(timeout=15):
                    errors.seek(0)
                    raise RetrievalError(f"Local reranker helper failed: {errors.read(400)}")
                return scores
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RetrievalError(f"Local reranker helper failed: {exc}") from exc


def index(root: Path, database: Path, library_id: str, docs_root: Path | None, embed_model: str | None, model_cache: Path | None, embedding_runtime: Path | None = None, *, model_revision: str | None = None, vector_engine: str = "stdlib", reranker_model: str | None = None, reranker_revision: str | None = None, chunk_chars: int = DEFAULT_CHUNK_CHARS, excludes: tuple[str, ...] | list[str] = ()) -> dict:
    validate_chunk_chars(chunk_chars)
    excludes = normalize_excludes(excludes)
    root = root.resolve(strict=True)
    if not root.is_dir() or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", library_id):
        raise RetrievalError("ROOT must be a directory and library ID must be /owner/name")
    if docs_root:
        docs_root = docs_root.resolve(strict=True)
        if not docs_root.is_dir():
            raise RetrievalError("Docs root must be a directory")
        if root.is_relative_to(docs_root):
            raise RetrievalError("Docs root must not equal or contain the source root; use separate or nested docs")
    database = database.resolve()
    if database.is_relative_to(root) or (docs_root and database.is_relative_to(docs_root)):
        raise RetrievalError("Database must be outside indexed roots")
    if (embed_model or reranker_model) and not model_cache:
        raise RetrievalError("Optional models require --model-cache outside indexed roots")
    if (embed_model or reranker_model) and not embedding_runtime:
        raise RetrievalError("Optional models require --embedding-runtime with isolated node_modules")
    if vector_engine not in ("stdlib", "sqlite-vec") or (vector_engine == "sqlite-vec" and not embed_model):
        raise RetrievalError("--vector-engine sqlite-vec requires an embedding model")
    if embed_model:
        model_revision = model_revision or (DEFAULT_MODEL_REVISION if embed_model == DEFAULT_MODEL else None)
        if not model_revision or not re.fullmatch(r"[a-f0-9]{40}", model_revision):
            raise RetrievalError("Custom embedding models require --model-revision with an immutable 40-character commit SHA")
    elif model_revision:
        raise RetrievalError("--model-revision requires --embed-model")
    if reranker_model:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", reranker_model):
            raise RetrievalError("Reranker model must be a model repository ID such as owner/name")
        reranker_revision = reranker_revision or (DEFAULT_RERANKER_REVISION if reranker_model == DEFAULT_RERANKER else None)
        if not reranker_revision or not re.fullmatch(r"[a-f0-9]{40}", reranker_revision):
            raise RetrievalError("Custom rerankers require --reranker-revision with an immutable 40-character commit SHA")
    elif reranker_revision:
        raise RetrievalError("--reranker-revision requires --reranker-model")
    if model_cache:
        model_cache = model_cache.resolve()
        if model_cache.is_relative_to(root) or (docs_root and model_cache.is_relative_to(docs_root)):
            raise RetrievalError("Model cache must be outside indexed roots")
    if embedding_runtime:
        embedding_runtime = embedding_runtime.resolve(strict=True)
        if not (embedding_runtime / "node_modules" / "@huggingface" / "transformers").is_dir():
            raise RetrievalError("Embedding runtime does not contain @huggingface/transformers")
        if embedding_runtime.is_relative_to(root) or (docs_root and embedding_runtime.is_relative_to(docs_root)):
            raise RetrievalError("Embedding runtime must be outside indexed roots")
    skipped: list[dict[str, str]] = []
    files = corpus_files(root, docs_root, excludes, skipped)
    database.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(database)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        old = existing_index_metadata(con)
        if old and (old.get("root") != str(root) or old.get("docs_root", "") != str(docs_root or "") or old.get("library_id") != library_id):
            raise RetrievalError("Database belongs to another corpus; use a new database")
        if vector_engine == "sqlite-vec" or "chunks_vec" in tables:
            try:
                load_sqlite_vec(con)
            except VectorAdapterUnavailable as exc:
                if "chunks_vec" in tables:
                    raise RetrievalError("Legacy sqlite-vec index needs sqlite-vec 0.1.9 once to reindex; install it or use a fresh database path") from exc
                raise
        con.execute("BEGIN")
        rebuild = old.get("index_version") != INDEX_VERSION or old.get("chunk_chars") != str(chunk_chars) or old.get("embed_model", "") != (embed_model or "") or old.get("model_revision", "") != (model_revision or "")
        if rebuild and tables:
            for table in ("chunks_vec", "chunk_vectors", "chunks_fts", "chunks", "files", "meta"):
                if table in tables:
                    con.execute(f"DROP TABLE {table}")
        setup(con)
        existing = {(r["kind"], r["path"]): r["hash"] for r in con.execute("SELECT * FROM files")}
        current: dict[tuple[str, str], tuple[str, int, str]] = {}
        for kind, rel, path in files:
            try:
                source_root = docs_root if kind == "docs" else root
                content, file_hash = read_safe_text(source_root, rel, max_file_bytes=MAX_FILE_BYTES)
            except ValueError as exc:
                skipped.append({"kind": kind, "path": rel, "reason": str(exc)})
                continue
            current[(kind, rel)] = (file_hash, len(content.encode("utf-8")), content)
        stale = set(existing) - set(current)
        changed = [key for key, row in current.items() if existing.get(key) != row[0]]
        for kind, rel in sorted(stale | set(changed)):
            ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE kind=? AND path=?", (kind, rel))]
            for chunk_id in ids:
                con.execute("DELETE FROM chunks_fts WHERE rowid=?", (chunk_id,))
            con.execute("DELETE FROM chunks WHERE kind=? AND path=?", (kind, rel))
            con.execute("DELETE FROM files WHERE kind=? AND path=?", (kind, rel))
        pending: list[tuple[int, str]] = []
        for kind, rel in changed:
            file_hash, size, content = current[(kind, rel)]
            con.execute("INSERT INTO files VALUES(?,?,?,?)", (kind, rel, file_hash, size))
            for start, end, body, symbols in chunks_for(content, chunk_chars):
                if embed_model and len(body.encode("utf-16-le")) // 2 > MAX_EMBEDDING_UNITS:
                    raise RetrievalError(f"Embedding input exceeds {MAX_EMBEDDING_UNITS} UTF-16 characters at {kind}:{rel}:L{start}-L{end}; use lexical indexing, --exclude this asset, or provide smaller verified documentation chunks")
                cur = con.execute("INSERT INTO chunks(kind,path,start,end,body,symbols) VALUES(?,?,?,?,?,?)", (kind, rel, start, end, body, symbols))
                con.execute("INSERT INTO chunks_fts(rowid,body,symbols,path) VALUES(?,?,?,?)", (cur.lastrowid, body, symbols, rel))
                pending.append((cur.lastrowid, body))
        count = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        oversized = con.execute("SELECT count(*) FROM chunks WHERE length(body)>?", (chunk_chars,)).fetchone()[0]
        if count > MAX_CHUNKS:
            raise RetrievalError(f"Chunk limit {MAX_CHUNKS} exceeded; index a smaller subtree")
        if reranker_model:
            assert model_cache is not None and embedding_runtime is not None and reranker_revision is not None
            reranker_scores("local retrieval warmup", ["local retrieval passage"], reranker_model, reranker_revision, model_cache, embedding_runtime, download=True)
        if embed_model and pending:
            assert model_cache is not None
            batches = [pending[start:start + MODEL_BATCH] for start in range(0, len(pending), MODEL_BATCH)]
            dimension = None
            for batch, vectors in zip(batches, embedding_batches([[body for _, body in batch] for batch in batches], embed_model, model_revision, model_cache, embedding_runtime, download=True), strict=True):
                packed = [pack_vector(vec) for vec in vectors]
                if dimension is None:
                    dimension = len(packed[0]) // 4
                    if not rebuild and old.get("vector_dim") and int(old["vector_dim"]) != dimension:
                        raise RetrievalError("Embedding dimension changed; reindex with a new model revision")
                if any(len(blob) != dimension * 4 for blob in packed):
                    raise RetrievalError("Embedding dimension changed within an indexing run")
                con.executemany("INSERT INTO chunk_vectors(chunk_id,embedding) VALUES(?,?)", [(cid, blob) for (cid, _), blob in zip(batch, packed)])
            put_meta(con, "vector_dim", str(dimension))
        elif embed_model:
            assert model_cache is not None and embedding_runtime is not None
            warmup = embeddings(["local retrieval warmup"], embed_model, model_cache, embedding_runtime, download=True, model_revision=model_revision)
            dimension = len(pack_vector(warmup[0])) // 4
            if count and old.get("vector_dim") != str(dimension):
                raise RetrievalError("Embedding dimension changed or is missing; reindex with a new model revision")
            put_meta(con, "vector_dim", str(dimension))
        if not embed_model:
            con.execute("DELETE FROM meta WHERE key='vector_dim'")
        if embed_model and con.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0] != count:
            raise RetrievalError("Embedding row count mismatch; reindex")
        rev = revision(root)
        signature = digest(json.dumps([rev, sorted((kind, rel, row[0]) for (kind, rel), row in current.items())], separators=(",", ":")).encode())
        for key, value in {"root": str(root), "docs_root": str(docs_root or ""), "library_id": library_id, "embed_model": embed_model or "", "model_revision": model_revision or "", "reranker_model": reranker_model or "", "reranker_revision": reranker_revision or "", "vector_engine": vector_engine, "model_cache": str(model_cache or ""), "embedding_runtime": str(embedding_runtime or ""), "revision": rev, "corpus_id": signature, "index_version": INDEX_VERSION, "chunk_chars": str(chunk_chars), "oversized_chunks": str(oversized), "excludes": json.dumps(excludes)}.items():
            put_meta(con, key, value)
        con.commit()
        return {"libraryId": library_id, "revision": rev, "corpusId": signature, "files": len(current), "chunks": count, "chunkChars": chunk_chars, "oversizedChunks": oversized, "changed": len(changed), "deleted": len(stale), "skippedCount": len(skipped), "skipped": skipped[:20], "embeddingModel": embed_model, "modelRevision": model_revision, "rerankerModel": reranker_model, "rerankerRevision": reranker_revision, "vectorEngine": vector_engine, "excludes": list(excludes)}
    finally:
        con.close()


def assert_fresh(con: sqlite3.Connection, meta: dict[str, str]) -> None:
    root = Path(meta["root"])
    docs = Path(meta["docs_root"]) if meta["docs_root"] else None
    if revision(root) != meta["revision"]:
        raise RetrievalError("Repository revision changed; reindex before querying")
    current = corpus_files(root, docs, stored_excludes(meta))
    indexed = {(r["kind"], r["path"]): r["hash"] for r in con.execute("SELECT kind,path,hash FROM files")}
    eligible: dict[tuple[str, str], str] = {}
    for kind, rel, path in current:
        try:
            _, file_hash = read_safe_text(docs if kind == "docs" else root, rel, max_file_bytes=MAX_FILE_BYTES)
        except ValueError:
            continue
        eligible[(kind, rel)] = file_hash
    if eligible != indexed:
        raise RetrievalError("Indexed files changed, appeared, or disappeared; reindex before querying")


def terms(query: str) -> list[str]:
    return list(dict.fromkeys(t.lower() for t in WORD_RE.findall(query) if t.lower() not in STOPWORDS))[:32]


def lexical_terms(query: str) -> list[str]:
    # Keep ASCII underscore names as quoted phrases. Splitting them into OR
    # components would let an absent identifier acquire a lexical anchor.
    pieces: list[tuple[str, str | None]] = []
    start = 0
    for match in re.finditer(r"(?<!\w)[A-Za-z_][A-Za-z_0-9]*(?!\w)", query):
        if "_" in match[0]:
            pieces.extend(((query[start:match.start()], None), (match[0], match[0].lower())))
            start = match.end()
    pieces.append((query[start:], None))
    # Ask the same default tokenizer used by chunks_fts, instead of approximating
    # its Unicode 6.1 categories and normalization with Python's Unicode rules.
    with sqlite3.connect(":memory:", factory=ClosingConnection) as tokenizer:
        tokenizer.execute("CREATE VIRTUAL TABLE query_text USING fts5(body)")
        tokenizer.execute("CREATE VIRTUAL TABLE query_tokens USING fts5vocab(query_text, 'instance')")
        tokenizer.executemany("INSERT INTO query_text(rowid,body) VALUES(?,?)", ((i, text) for i, (text, _) in enumerate(pieces, 1)))
        words: dict[str, None] = {}
        for doc, token in tokenizer.execute("SELECT doc,term FROM query_tokens ORDER BY doc,offset"):
            word = pieces[doc - 1][1] or token
            if word not in STOPWORDS:
                words.setdefault(word, None)
                if len(words) == 32:
                    break
        return list(words)


def lexical(con: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    words = lexical_terms(query)
    if not words:
        return []
    expression = " OR ".join('"' + word.replace('"', '') + '"' for word in words)
    rows = con.execute("SELECT f.rowid, bm25(chunks_fts,1.0,4.0,2.0) AS rank, c.symbols FROM chunks_fts f JOIN chunks c ON c.id=f.rowid WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (expression, limit)).fetchall()
    scored = []
    wordset = set(terms(query))
    for row in rows:
        symbolset = {word.lower() for word in row["symbols"].split()}
        scored.append((row["rowid"], -row["rank"] + 5 * len(wordset & symbolset)))
    return sorted(scored, key=lambda item: (-item[1], item[0]))


def semantic(con: sqlite3.Connection, query: str, model: str, model_revision: str, cache: Path, runtime: Path, limit: int, vector_engine: str) -> list[tuple[int, float]]:
    vector = unpack_vector(pack_vector(embeddings([query], model, cache, runtime, download=False, model_revision=model_revision)[0]))
    results = []
    if vector_engine == "sqlite-vec":
        rows = con.execute("SELECT chunk_id,vec_distance_cosine(embedding,?) AS distance FROM chunk_vectors ORDER BY distance,chunk_id LIMIT ?", (pack_vector(list(vector)), limit))
        results = [(row["chunk_id"], 1 - row["distance"]) for row in rows]
    else:
        for row in con.execute("SELECT chunk_id,embedding FROM chunk_vectors"):
            vec = unpack_vector(row["embedding"])
            if len(vec) != len(vector):
                raise RetrievalError("Stored embedding dimension mismatch; reindex")
            results.append((row["chunk_id"], math.sumprod(vec, vector)))
    results.sort(key=lambda x: (-x[1], x[0]))
    return [item for item in results if item[1] >= MIN_SEMANTIC_SCORE][:limit]


def query(con: sqlite3.Connection, question: str, mode: str = "lexical", rerank: str | None = None, limit: int = 5, vector_engine: str | None = None) -> dict:
    meta = indexed_metadata(con)
    if not question.strip() or len(question) > MAX_QUERY:
        raise RetrievalError(f"Query must contain 1-{MAX_QUERY} characters")
    if mode not in ("lexical", "semantic", "hybrid") or rerank not in (None, "lexical-symbol", "cross-encoder"):
        raise RetrievalError("Unknown mode or reranker")
    if vector_engine not in (None, "stdlib", "sqlite-vec", "auto"):
        raise RetrievalError("Unknown vector engine")
    if not 1 <= limit <= MAX_RESULTS:
        raise RetrievalError(f"Limit must be 1-{MAX_RESULTS}")
    if rerank == "cross-encoder" and not meta.get("reranker_model"):
        raise RetrievalError("Cross-encoder reranking requires an index created with --reranker-model")
    if rerank == "cross-encoder":
        cache = Path(meta["model_cache"])
        model_files = cache / meta["reranker_model"] / meta["reranker_revision"]
        if not cache.is_dir() or not all((model_files / name).is_file() for name in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx")):
            raise RetrievalError("Local reranker model is unavailable; index with --reranker-model to download it")
    assert_fresh(con, meta)
    candidates = min(MAX_CANDIDATES, max(30, limit * 6))
    lex = lexical(con, question, candidates) if mode != "semantic" else []
    sem = []
    selected_engine = None
    if mode != "lexical":
        if not meta["embed_model"]:
            raise RetrievalError("Semantic search requires an index created with --embed-model")
        requested_engine = vector_engine or meta.get("vector_engine", "stdlib")
        selected_engine = requested_engine
        if requested_engine in ("sqlite-vec", "auto"):
            try:
                load_sqlite_vec(con)
                selected_engine = "sqlite-vec"
            except VectorAdapterUnavailable:
                if requested_engine != "auto":
                    raise
                selected_engine = "stdlib"
        sem = semantic(con, question, meta["embed_model"], meta["model_revision"], Path(meta["model_cache"]), Path(meta["embedding_runtime"]), candidates, selected_engine)
        # Identifier lookups need an exact lexical anchor; embeddings alone can
        # pull unrelated source for a symbol that does not exist.
        identifier = question.strip()
        if re.fullmatch(r"[A-Za-z_$][A-Za-z_$0-9]*", identifier) and ("_" in identifier or any(c.isupper() for c in identifier)):
            anchored = {cid for cid, _ in lexical(con, identifier, candidates)}
            sem = [(cid, score) for cid, score in sem if cid in anchored]
    scores: dict[int, float] = {}
    for ranking in (lex, sem):
        for rank, (cid, _) in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + 1 / (60 + rank)
    if mode == "lexical":
        scores = {cid: score for cid, score in lex}
    elif mode == "semantic":
        scores = {cid: score for cid, score in sem}
    ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))
    if rerank == "lexical-symbol":
        words = set(terms(question))
        scored = []
        for cid in ranked:
            row = con.execute("SELECT symbols,path FROM chunks WHERE id=?", (cid,)).fetchone()
            symbols = {t.lower() for t in WORD_RE.findall(row["symbols"])}
            path_words = {t.lower() for t in WORD_RE.findall(row["path"])}
            scored.append((cid, 5 * len(words & symbols) + len(words & path_words)))
        ranked = [cid for cid, _ in sorted(scored, key=lambda pair: (-pair[1], -scores[pair[0]], pair[0]))]
    rerank_scores_by_id: dict[int, float] = {}
    if rerank == "cross-encoder" and ranked:
        ranked = ranked[:MAX_CANDIDATES]
        rows = con.execute(f"SELECT id,body FROM chunks WHERE id IN ({','.join('?' for _ in ranked)})", ranked).fetchall()
        bodies = {row["id"]: row["body"] for row in rows}
        values = reranker_scores(question, [bodies[cid] for cid in ranked], meta["reranker_model"], meta["reranker_revision"], Path(meta["model_cache"]), Path(meta["embedding_runtime"]), download=False)
        rerank_scores_by_id = dict(zip(ranked, values, strict=True))
        ranked.sort(key=lambda cid: (-rerank_scores_by_id[cid], -scores[cid], cid))
    snippets = []
    for cid in ranked[:limit]:
        row = con.execute("SELECT c.*,f.hash FROM chunks c JOIN files f ON c.kind=f.kind AND c.path=f.path WHERE c.id=?", (cid,)).fetchone()
        source_root = Path(meta["docs_root"] if row["kind"] == "docs" else meta["root"])
        try:
            live, live_hash = read_safe_text(source_root, row["path"], max_file_bytes=MAX_FILE_BYTES)
        except ValueError as exc:
            raise RetrievalError("Source changed during query; reindex") from exc
        if live_hash != row["hash"] or "\n".join(split_source_lines(live)[row["start"] - 1:row["end"]]) != row["body"]:
            raise RetrievalError("Source changed during query; reindex")
        source = {"kind": row["kind"], "path": row["path"], "startLine": row["start"], "endLine": row["end"], "fileSha256": row["hash"], "revision": meta["revision"], "corpusId": meta["corpus_id"]}
        item = {"source": source, "text": row["body"], "score": scores[cid]}
        if rerank == "cross-encoder":
            item["rerankScore"] = rerank_scores_by_id[cid]
        snippets.append(item)
    return {"libraryId": meta["library_id"], "chunkChars": int(meta["chunk_chars"]), "oversizedChunks": int(meta["oversized_chunks"]), "mode": mode, "reranker": rerank, "vectorEngine": selected_engine, "corpusId": meta["corpus_id"], "results": snippets, "message": None if snippets else "No matching indexed evidence"}


def context_payload(result: dict) -> dict:
    code, info = [], []
    for item in result["results"]:
        src = item["source"]
        provenance = f'{src["kind"]}:{src["path"]}:L{src["startLine"]}-L{src["endLine"]} sha256:{src["fileSha256"]} revision:{src["revision"]} corpus:{src["corpusId"]}'
        if src["kind"] != "code":
            info.append({"pageTitle": src["path"], "content": item["text"], "description": provenance})
        else:
            code.append({"codeTitle": provenance, "codeDescription": provenance, "codeLanguage": Path(src["path"]).suffix.lstrip("."), "codeTokens": (len(item["text"]) + 3) // 4, "codeId": provenance, "pageTitle": src["path"], "codeList": [{"language": Path(src["path"]).suffix.lstrip("."), "code": item["text"]}]})
    return {"codeSnippets": code, "infoSnippets": info}


def serve(database: Path, host: str, port: int, default_mode: str = "lexical", default_rerank: str | None = None, default_vector_engine: str | None = None) -> None:
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise RetrievalError("Only loopback binds are supported")
    if default_mode not in ("lexical", "semantic", "hybrid") or default_rerank not in (None, "lexical-symbol", "cross-encoder"):
        raise RetrievalError("Unknown default mode or reranker")
    if default_vector_engine not in (None, "stdlib", "sqlite-vec", "auto"):
        raise RetrievalError("Unknown default vector engine")
    with connect(database, timeout=HTTP_SQLITE_TIMEOUT) as con:
        meta = indexed_metadata(con)
        if default_mode != "lexical" and not meta.get("embed_model"):
            raise RetrievalError("Semantic default requires an index created with --embed-model")
        if default_rerank == "cross-encoder" and not meta.get("reranker_model"):
            raise RetrievalError("Cross-encoder default requires an index created with --reranker-model")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if len(self.path) > MAX_REQUEST:
                self.send_error(413, "Request too large")
                return
            try:
                authority = urlsplit("//" + self.headers.get("Host", ""))
                if authority.hostname not in ("127.0.0.1", "::1", "localhost") or authority.username is not None or authority.password is not None or authority.path or authority.query or authority.fragment:
                    self.respond(403, json.dumps({"error": "Only loopback Host authorities are supported"}).encode(), "application/json")
                    return
                # Validate a supplied port too, without changing client compatibility.
                authority.port
                parsed = urlsplit(self.path)
                args = parse_qs(parsed.query)
                with connect(database, timeout=HTTP_SQLITE_TIMEOUT) as con:
                    meta = indexed_metadata(con)
                    if parsed.path == "/api/v2/libs/search":
                        name = args.get("libraryName", [""])[0].lower()
                        match = name and (name in meta["library_id"].lower())
                        payload = {"results": [{"id": meta["library_id"], "title": meta["library_id"], "description": f'Local indexed source at {meta["revision"]}', "branch": meta["revision"], "totalSnippets": con.execute("SELECT count(*) FROM chunks").fetchone()[0], "trustScore": None}]} if match else {"results": []}
                    elif parsed.path == "/api/v2/context":
                        if args.get("libraryId", [""])[0] != meta["library_id"]:
                            self.send_error(404, "Unknown local library")
                            return
                        try:
                            requested_limit = int(args.get("limit", ["5"])[0])
                        except ValueError as exc:
                            raise RetrievalError("Invalid result limit") from exc
                        result = query(con, args.get("query", [""])[0], args.get("mode", [default_mode])[0], args.get("rerank", [default_rerank])[0], requested_limit, args.get("vectorEngine", [default_vector_engine])[0])
                        payload = context_payload(result)
                        if args.get("type", [""])[0] == "txt":
                            rendered = [s["codeDescription"] + "\n" + s["codeList"][0]["code"] for s in payload["codeSnippets"]]
                            rendered.extend(s["description"] + "\n" + s["content"] for s in payload["infoSnippets"])
                            body = "\n\n".join(rendered)
                            if not body:
                                body = "No matching indexed evidence"
                            self.respond(200, body.encode(), "text/plain; charset=utf-8")
                            return
                    else:
                        self.send_error(404, "Unknown endpoint")
                        return
                self.respond(200, json.dumps(payload).encode(), "application/json")
            except (RetrievalError, sqlite3.Error, OSError, ValueError) as exc:
                self.respond(409, json.dumps({"error": str(exc)}).encode(), "application/json")

        def respond(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    server = Server((host, port), Handler)
    display_host = "[::1]" if host == "::1" else host
    print(f"Local Context7 endpoint: http://{display_host}:{server.server_port} mode={default_mode} rerank={default_rerank}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    idx = commands.add_parser("index")
    idx.add_argument("root", type=Path)
    idx.add_argument("--database", type=Path, required=True)
    idx.add_argument("--library-id", required=True)
    idx.add_argument("--docs-root", type=Path)
    idx.add_argument("--exclude", action="append", default=[], help="Relative file/directory path in source and docs roots; repeatable, no globs")
    idx.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS, help="Whole-line chunk character target, 128..12000; not a token budget")
    idx.add_argument("--embed-model")
    idx.add_argument("--model-revision", help="Immutable 40-character model commit SHA")
    idx.add_argument("--reranker-model", help="Opt-in local cross-encoder; downloads only during indexing")
    idx.add_argument("--reranker-revision", help="Immutable 40-character reranker commit SHA")
    idx.add_argument("--vector-engine", choices=("stdlib", "sqlite-vec"), default="stdlib")
    idx.add_argument("--model-cache", type=Path)
    idx.add_argument("--embedding-runtime", type=Path)
    qry = commands.add_parser("query")
    qry.add_argument("--database", type=Path, required=True)
    qry.add_argument("--query", required=True)
    qry.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    qry.add_argument("--rerank", choices=("lexical-symbol", "cross-encoder"))
    qry.add_argument("--limit", type=int, default=5)
    qry.add_argument("--vector-engine", choices=("stdlib", "sqlite-vec", "auto"))
    srv = commands.add_parser("serve")
    srv.add_argument("--database", type=Path, required=True)
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8765)
    srv.add_argument("--default-mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    srv.add_argument("--default-rerank", choices=("lexical-symbol", "cross-encoder"))
    srv.add_argument("--default-vector-engine", choices=("stdlib", "sqlite-vec", "auto"))
    args = parser.parse_args(argv)
    try:
        if args.command == "index":
            result = index(args.root, args.database, args.library_id, args.docs_root, args.embed_model, args.model_cache, args.embedding_runtime, model_revision=args.model_revision, vector_engine=args.vector_engine, reranker_model=args.reranker_model, reranker_revision=args.reranker_revision, chunk_chars=args.chunk_chars, excludes=args.exclude)
            print(json.dumps(result, indent=2))
        elif args.command == "query":
            with connect(args.database) as con:
                print(json.dumps(query(con, args.query, args.mode, args.rerank, args.limit, args.vector_engine), indent=2))
        else:
            serve(args.database, args.host, args.port, args.default_mode, args.default_rerank, args.default_vector_engine)
        return 0
    except (RetrievalError, OSError, sqlite3.Error) as exc:
        print(f"retrieval error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
