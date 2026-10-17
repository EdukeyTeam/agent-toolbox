"""Bounded exact cosine scans over the authoritative float32 BLOBs.

No optional package is imported until a scan requests it. Scores within the
same six-decimal bucket tie on ascending unit ID, across all engines.
"""
from __future__ import annotations

import heapq
import importlib
import importlib.util
import math
import sqlite3
import struct
from itertools import islice


def _values(vec) -> list[float]:
    result = list(vec)
    try:
        valid = result and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in result)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Vector must contain finite nonboolean numbers")
    return [float(v) for v in result]


def normalize(vec) -> list[float]:
    values = _values(vec)
    # hypot avoids overflow/underflow for otherwise valid vectors.
    norm = math.hypot(*values)
    if not norm or not math.isfinite(norm):
        raise ValueError("Vector must have a finite nonzero norm")
    return [v / norm for v in values]


def pack(vec: list[float]) -> bytes:
    values = _values(vec)
    try:
        return struct.pack(f"<{len(values)}f", *values)
    except (OverflowError, struct.error) as exc:
        raise ValueError("Vector cannot be represented as float32") from exc


def unpack(blob: bytes) -> list[float]:
    if not isinstance(blob, (bytes, bytearray, memoryview)) or not blob or len(blob) % 4:
        raise ValueError("Expected a nonempty little-endian float32 BLOB")
    return _values(struct.unpack(f"<{len(blob) // 4}f", blob))


def _sqlite_vec():
    module = importlib.import_module("sqlite_vec")
    if getattr(module, "__version__", None) != "0.1.9":
        raise ValueError("sqlite-vec requires version 0.1.9")
    return module


def available_engines() -> list[str]:
    engines = ["stdlib"]
    if importlib.util.find_spec("numpy") is not None:
        engines.append("numpy")
    if importlib.util.find_spec("sqlite_vec") is not None:
        _sqlite_vec()  # An installed incompatible extension is an error.
        engines.append("sqlite-vec")
    return engines


def top_k(query: list[float], rows, k: int, engine: str = "auto") -> list[tuple[int, float]]:
    if engine not in ("auto", "numpy", "stdlib", "sqlite-vec"):
        raise ValueError("Unknown vector engine")
    if isinstance(k, bool) or not isinstance(k, int) or k < 0:
        raise ValueError("k must be a nonnegative integer")
    q = normalize(query)
    if engine == "auto":
        engines = available_engines()
        engine = "sqlite-vec" if "sqlite-vec" in engines else engines[-1]
    numpy = importlib.import_module("numpy") if engine == "numpy" else None
    connection = None
    if engine == "sqlite-vec":
        extension = _sqlite_vec()
        connection = sqlite3.connect(":memory:")
        try:
            connection.enable_load_extension(True)
            extension.load(connection)
            connection.enable_load_extension(False)
            connection.execute("CREATE TEMP TABLE scan (unit_id INTEGER, embedding BLOB)")
        except Exception:
            connection.close()
            raise
    heap: list[tuple[float, int, float, int]] = []
    iterator = iter(rows)
    try:
        while batch := list(islice(iterator, 4096)):
            blobs = []
            for unit_id, blob in batch:
                if isinstance(unit_id, bool) or not isinstance(unit_id, int):
                    raise ValueError("Unit ID must be an integer")
                if not isinstance(blob, (bytes, bytearray, memoryview)) or len(blob) != 4 * len(q):
                    raise ValueError("Vector dimension mismatch")
                blobs.append(blob)
            if numpy is not None:
                # Validate in vectorized bounded batches, avoiding millions of
                # Python float allocations for a large repository.
                matrix = numpy.frombuffer(b"".join(blobs), dtype="<f4").reshape((-1, len(q))).astype(numpy.float64)
                if not numpy.isfinite(matrix).all():
                    raise ValueError("Vector must contain finite numbers")
                norms = numpy.linalg.norm(matrix, axis=1)
                if not (norms > 0).all():
                    raise ValueError("Vector must have a nonzero norm")
                scores = ((matrix @ numpy.asarray(q)) / norms).tolist()
            elif connection is not None:
                validated = [normalize(unpack(blob)) for blob in blobs]
                connection.execute("DELETE FROM scan")
                connection.executemany("INSERT INTO scan VALUES (?, ?)",
                                       [(i, pack(v)) for i, v in enumerate(validated)])
                scores = [score for _, score in connection.execute(
                    "SELECT unit_id, 1.0 - vec_distance_cosine(embedding, ?) FROM scan ORDER BY rowid", (pack(q),))]
            else:
                validated = [normalize(unpack(blob)) for blob in blobs]
                sumprod = getattr(math, "sumprod", None)
                scores = [sumprod(q, v) if sumprod else math.fsum(a * b for a, b in zip(q, v)) for v in validated]
            for (unit_id, _), score in zip(batch, scores):
                score = max(-1.0, min(1.0, float(score)))
                item = (round(score, 6), -unit_id, score, unit_id)
                if k and len(heap) < k:
                    heapq.heappush(heap, item)
                elif k and item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, item)
        return [(item[3], item[2]) for item in sorted(heap, key=lambda v: (-v[0], -v[1]))]
    finally:
        if connection is not None:
            connection.close()
