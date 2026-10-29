"""Legacy bounded helper protocol and direct tokenizer compatibility tests."""
from __future__ import annotations
from .units import RetrievalError
from .store import ClosingConnection

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

from legacy_common import inference_environment

from repo_files import _candidates, _git, git_context, _safe_relative, _secret, read_safe_text, split_source_lines



MAX_FILE_BYTES = 256_000








WINDOW = 48

OVERLAP = 8

DEFAULT_CHUNK_CHARS = 1200

MAX_EMBEDDING_UNITS = 12000

MODEL_BATCH = 32

MAX_EMBEDDING_RESPONSE_CHARS = 8 * 1024 * 1024


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


RETRIEVAL = Path(__file__).resolve().parent.parent / "retrieval" / "embed.mjs"

RERANK_HELPER = Path(__file__).resolve().parent.parent / "retrieval" / "rerank.mjs"

class VectorAdapterUnavailable(RetrievalError):
    pass

def load_sqlite_vec(con: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except (ImportError, OSError) as exc:
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
