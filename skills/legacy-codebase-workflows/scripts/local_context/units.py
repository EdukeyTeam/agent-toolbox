"""Shared immutable records and stable errors; standard library only."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import math

INDEX_VERSION = "8"
DEFAULT_CHUNK_CHARS = 1500
EMPTY = "No matching indexed evidence. Empty results are not proof of absence; use direct search."

class RetrievalError(RuntimeError):
    def __init__(self, message: str, code: str = "invalid_argument", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def estimate(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class Root:
    id: str
    path: str
    role: str
    revision: str = "non-git"
    directory_mtime_ns: int = 0
    index_path: str = ""
    index_mtime_ns: int = 0


@dataclass(frozen=True)
class Decoded:
    text: str
    sha256: str
    encoding: str
    assumed: bool = False


@dataclass(frozen=True)
class Definition:
    start: int
    end: int
    name: str
    qualified: str
    signature: str
    scope: tuple[str, ...] = ()
    description: str = ""
    header_start: int | None = None
    header_end: int | None = None


@dataclass(frozen=True)
class UnitDraft:
    start: int
    end: int
    text: str | None
    kind: str = "code-block"
    title: str = ""
    header: str = ""
    description: str = ""
    language: str = "text"
    definitions: tuple[Definition, ...] = ()
    breadcrumb: tuple[str, ...] = ()
    header_spans: tuple[tuple[int, int], ...] = ()
    cell_index: int | None = None
    transformed: bool = False
    redacted: bool = False
    oversized: bool = False
    searchable: bool = True
    parent: int | None = None
    part: int = 1
    parts: int = 1
