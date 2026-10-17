"""Source-faithful decoding and intentionally narrow secret scanning."""
from __future__ import annotations
import codecs
import os
from pathlib import Path
import re
import stat
from .discover import safe_path
from .units import Decoded, RetrievalError, digest

PEM = re.compile(r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")
KEY = re.compile(r"(?<![\w])(?:AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|xox[abp]-[A-Za-z0-9-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,})(?![\w])")
DECLARED = re.compile(br"(?:coding\s*[:=]\s*|encoding\s*=\s*['\"]|charset\s*=\s*['\"]?)([-\w.]+)", re.I)


def secret_spans(text: str) -> list[tuple[int, int]]:
    return [(text.count("\n", 0, m.start()) + 1, text.count("\n", 0, m.end()) + 1) for pattern in (PEM, KEY) for m in pattern.finditer(text)]


def read_source(root: Path, relative: str, encodings=(), max_file_bytes=2_000_000) -> Decoded:
    path = safe_path(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os,"O_NONBLOCK",0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise RetrievalError("Source is no longer a regular file", "source_unreadable",409)
            raw = handle.read(max_file_bytes + 1)
    except OSError as exc:
        raise RetrievalError("Cannot read source file", "source_unreadable", 409) from exc
    if len(raw) > max_file_bytes:
        raise RetrievalError("File exceeds max_file_bytes", "file_too_large", 413)
    bom = "utf-16" if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else None
    if not bom and b"\0" in raw:
        raise RetrievalError("Binary file", "binary")
    if bom:
        try:
            raw.decode(bom,errors="strict")
        except UnicodeDecodeError as exc:
            raise RetrievalError("Malformed BOM-declared encoding", "encoding") from exc
    declared = DECLARED.search(raw[:1024]) if Path(relative).suffix.lower() in {".py", ".xml", ".html", ".htm", ".config"} else None
    candidates = ([bom] if bom else []) + ([declared[1].decode("ascii")] if declared else []) + ["utf-8"]
    candidates += ["iso-8859-1"] if relative.lower().endswith(".properties") else [*encodings, "cp1252", "latin-1"]
    text = None
    for encoding in dict.fromkeys(candidates):
        try:
            text = raw.decode(encoding, errors="strict")
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise RetrievalError("No configured encoding can decode source", "encoding")
    if len(re.findall(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]", text)) > len(text) * .02:
        raise RetrievalError("Binary file (control characters)", "binary")
    return Decoded(text.replace("\r\n", "\n").replace("\r", "\n"), digest(raw), encoding, encoding in {"latin-1", "iso-8859-1"} and not declared and not bom)
