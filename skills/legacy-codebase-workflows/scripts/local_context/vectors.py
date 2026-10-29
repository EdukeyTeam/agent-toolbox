"""Bounded exact cosine scans over the authoritative float32 BLOBs.

No optional package is imported until a scan requests it. Scores within the
same six-decimal bucket tie on ascending unit ID, across all engines.
"""
from __future__ import annotations

import heapq
import importlib
import importlib.util
import math
from numbers import Real
import sqlite3
import struct
from itertools import islice


def cached_top_k(query, rows_factory, k, owner, key, *, cache=True):
    """Exact NumPy scan with a bounded, generation-owned prepared snapshot.

    SQLite remains authoritative. No approximate candidate restriction, disk
    sidecar, or stale cross-generation vector survives provider replacement.
    Filters are part of the key; retain at most one 512 MiB snapshot per model.
    """
    np = importlib.import_module("numpy")
    q = normalize(query)
    saved = getattr(owner, "_retrieval_vectors", None) if cache else None
    if saved is None or saved[0] != key:
        blocks, size = [], 0
        iterator = iter(rows_factory())
        while batch := list(islice(iterator, 4096)):
            ids, blobs = zip(*batch)
            if any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
                raise ValueError("Unit ID must be an integer")
            if any(not isinstance(b, (bytes, bytearray, memoryview)) or len(b) != 4 * len(q) for b in blobs):
                raise ValueError("Vector dimension mismatch")
            matrix = np.frombuffer(b"".join(blobs), dtype="<f4").reshape((-1, len(q)))
            if not np.isfinite(matrix).all():
                raise ValueError("Vector must contain finite numbers")
            norms = np.sqrt(np.einsum("ij,ij->i", matrix, matrix, dtype=np.float64))
            if not (norms > 0).all():
                raise ValueError("Vector must have a nonzero norm")
            blocks.append((np.asarray(ids, dtype=np.int64), matrix, norms))
            size += matrix.nbytes + norms.nbytes + len(ids) * 8
            if size > 512 * 1024 * 1024:
                # Larger corpora stay bounded and use the streaming authority.
                return top_k(q, rows_factory(), k, "numpy")
        saved = (key, blocks, len(q))
        if cache:
            owner._retrieval_vectors = saved
    if saved[2] != len(q):
        raise ValueError("Vector dimension mismatch")
    selected = []
    for ids, matrix, norms in saved[1]:
        # Mixed-dtype einsum avoids a float64 matrix copy and BLAS thread
        # startup for every 4096-row block. Norms were validated on publication.
        scores = np.einsum("ij,j->i", matrix, q, dtype=np.float64) / norms
        buckets = np.round(np.clip(scores, -1., 1.), 6)
        count = min(k, len(ids))
        if count:
            threshold = np.partition(buckets, len(ids) - count)[len(ids) - count]
            indices = np.flatnonzero(buckets >= threshold)
            if len(indices) > count:
                indices = indices[np.lexsort((ids[indices], -buckets[indices]))[:count]]
            selected.extend((int(ids[i]), float(scores[i])) for i in indices)
    # Keep the authoritative engines' six-decimal bucket / ascending-ID policy.
    return heapq.nsmallest(k, selected, key=lambda row: (-round(row[1], 6), row[0]))


def _values(vec) -> list[float]:
    result = list(vec)
    try:
        # Native int/float checks stay ahead of the ABC for the scan hot path;
        # Real also accepts NumPy's float32/int64 scalars without importing it.
        valid = result and all(not isinstance(v, bool) and isinstance(v, (int, float, Real)) and math.isfinite(v) for v in result)
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
    numpy = (importlib.import_module("numpy") if engine == "numpy" or
             (engine == "sqlite-vec" and importlib.util.find_spec("numpy") is not None) else None)
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
            if numpy is not None and engine == "numpy":
                # Validate in vectorized bounded batches, avoiding millions of
                # Python float allocations for a large repository.
                matrix = numpy.frombuffer(b"".join(blobs), dtype="<f4").reshape((-1, len(q))).astype(numpy.float64)
                if not numpy.isfinite(matrix).all():
                    raise ValueError("Vector must contain finite numbers")
                # Bounded float64 copies allow the platform's optimized BLAS
                # kernels; mixed-dtype einsum was slower on the CPU trial.
                norms = numpy.linalg.norm(matrix, axis=1)
                if not (norms > 0).all():
                    raise ValueError("Vector must have a nonzero norm")
                scores = (matrix @ numpy.asarray(q)) / norms
                # Only this batch's top-k can enter the global top-k. Retain
                # all boundary ties so an arbitrary partition never drops a
                # smaller unit ID. The final heap uses the same policy as
                # stdlib and sqlite-vec.
                buckets = numpy.round(numpy.clip(scores, -1.0, 1.0), 6)
                count = min(k, len(batch))
                if count:
                    threshold = numpy.partition(buckets, len(batch) - count)[len(batch) - count]
                    indices = numpy.flatnonzero(buckets >= threshold)
                else:
                    indices = []
                scored = ((batch[int(i)][0], float(scores[i])) for i in indices)
            elif connection is not None:
                if numpy is not None:
                    matrix = numpy.frombuffer(b"".join(blobs), dtype="<f4").reshape((-1, len(q)))
                    if not numpy.isfinite(matrix).all():
                        raise ValueError("Vector must contain finite numbers")
                    norms = numpy.sqrt(numpy.einsum("ij,ij->i", matrix, matrix, dtype=numpy.float64))
                    if not (norms > 0).all():
                        raise ValueError("Vector must have a nonzero norm")
                    native = memoryview((matrix / norms[:, None]).astype("<f4").tobytes())
                    width = len(q) * 4
                    native_rows = ((i, native[i * width:(i + 1) * width]) for i in range(len(batch)))
                else:
                    native_rows = ((i, pack(normalize(unpack(blob)))) for i, blob in enumerate(blobs))
                connection.execute("DELETE FROM scan")
                connection.executemany("INSERT INTO scan VALUES (?, ?)", native_rows)
                scores = [score for _, score in connection.execute(
                    "SELECT unit_id, 1.0 - vec_distance_cosine(embedding, ?) FROM scan ORDER BY rowid", (pack(q),))]
                scored = ((row[0], score) for row, score in zip(batch, scores))
            else:
                validated = [normalize(unpack(blob)) for blob in blobs]
                sumprod = getattr(math, "sumprod", None)
                scores = [sumprod(q, v) if sumprod else math.fsum(a * b for a, b in zip(q, v)) for v in validated]
                scored = ((row[0], score) for row, score in zip(batch, scores))
            for unit_id, score in scored:
                if score is None or not math.isfinite(score):
                    raise ValueError("Vector engine returned an invalid cosine")
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
