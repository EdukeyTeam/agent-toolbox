#!/usr/bin/env python3
"""Compatibility entry point for the format-8 local retrieval engine."""
from __future__ import annotations
import builtins
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_context.units import RetrievalError, INDEX_VERSION, DEFAULT_CHUNK_CHARS, digest
from local_context.store import connect, indexed_metadata, metadata, ClosingConnection
from local_context.discover import normalize_excludes, revision
from local_context.freshness import index, refresh, assert_fresh
from local_context.engine import query, resolve, status, expand
from local_context.assemble import context_payload
from local_context.cli import main
HTTP_SQLITE_TIMEOUT = 1.0
MAX_REQUEST = 2048


def __getattr__(name):
    if name == "ThreadingHTTPServer":
        from http.server import ThreadingHTTPServer
        return ThreadingHTTPServer
    if name in {"embedding_batches", "embeddings", "reranker_scores", "chunks_for",
                "validate_chunk_chars", "lexical_terms", "terms", "load_sqlite_vec",
                "VectorAdapterUnavailable", "DEFAULT_MODEL", "DEFAULT_MODEL_REVISION",
                "DEFAULT_RERANKER", "DEFAULT_RERANKER_REVISION"}:
        from local_context import protocol
        return getattr(protocol,name)
    raise AttributeError(name)


def serve(database, host="127.0.0.1", port=8765, default_mode="lexical", default_rerank=None, default_vector_engine=None, **kwargs):
    from local_context.http_api import serve as run
    # The generated launcher patches these two exports to own server lifecycle
    # and keep MCP stdout clean. Preserve both contracts.
    return run(database,host,port,default_mode,default_rerank,default_vector_engine,
               server_factory=globals().get("ThreadingHTTPServer") or __getattr__("ThreadingHTTPServer"),diagnostic=globals().get("print",builtins.print),**kwargs)


def pack_vector(vector):
    from local_context.vectors import pack, normalize
    try:
        return pack(normalize(vector))
    except ValueError as exc:
        raise RetrievalError(str(exc)) from exc


def unpack_vector(blob):
    from local_context.vectors import unpack
    return tuple(unpack(blob))


if __name__ == "__main__":
    raise SystemExit(main())
