"""Source-faithful decoding and intentionally narrow secret scanning."""
from __future__ import annotations
import codecs
from bisect import bisect_left
import os
from pathlib import Path
import re
import stat
from .discover import safe_path
from .units import Decoded, RetrievalError, digest

PEM = re.compile(r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")
KEY = re.compile(r"(?<![\w])(?:AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|xox[abp]-[A-Za-z0-9-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,})(?![\w])")
MAX_TEXT_BYTES = 20 * 1024 * 1024

DECLARED = re.compile(br"(?:coding\s*[:=]\s*|encoding\s*=\s*['\"]|charset\s*=\s*['\"]?)([-\w.]+)", re.I)


def secret_spans(text: str) -> list[tuple[int, int]]:
    newlines = [m.start() for m in re.finditer("\n", text)]
    return [(bisect_left(newlines, m.start()) + 1, bisect_left(newlines, m.end()) + 1) for pattern in (PEM, KEY) for m in pattern.finditer(text)]


def declared_encoding(raw: bytes, suffix: str) -> str | None:
    if suffix == ".py":
        lines = raw.removeprefix(codecs.BOM_UTF8).split(b"\n", 2)[:2]
        cookie = re.compile(br"^[ \t\f]*\#.*?coding[:=][ \t]*([-\w.]+)")
        for line in lines:
            match = cookie.match(line)
            if match:
                return match[1].decode("ascii")
            # PEP 263 only permits a second-line cookie after a blank/comment.
            if not re.match(br"^[ \t\f]*(?:\#|\r?$)", line):
                break
    elif suffix in {".xml", ".config"}:
        prolog = re.match(br"\s*<\?xml\b[^?]*\?>", raw[:1024], re.I)
        match = DECLARED.search(prolog[0]) if prolog else None
        if match:
            return match[1].decode("ascii")
    elif suffix in {".html", ".htm"}:
        # Inspect actual head metadata, never body text or quoted examples.
        head = re.sub(br"<!--[\s\S]*?-->", b"", raw[:1024])
        for tag in re.finditer(br"<\s*(/?)\s*([\w!]+)\b[^>]*>", head):
            name = tag[2].lower()
            if name in {b"body", b"head"} and (name == b"body" or tag[1]):
                break
            if name not in {b"!doctype", b"html", b"head", b"meta", b"title", b"link", b"base", b"style", b"script"}:
                break
            if name == b"meta" and not tag[1]:
                match = DECLARED.search(tag[0])
                if match:
                    return match[1].decode("ascii")
    return None


def read_source(root: Path, relative: str, encodings=(), max_file_bytes=2_000_000) -> Decoded:
    path = safe_path(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os,"O_NONBLOCK",0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise RetrievalError("Source is no longer a regular file", "source_unreadable",409)
            raw = handle.read(max(max_file_bytes, MAX_TEXT_BYTES) + 1)
    except OSError as exc:
        raise RetrievalError("Cannot read source file", "source_unreadable", 409) from exc
    if len(raw) > max(max_file_bytes, MAX_TEXT_BYTES):
        raise RetrievalError("File exceeds the textual window limit", "file_too_large", 413)
    bom = "utf-16" if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else None
    # ASCII-heavy UTF-16 has NULs predominantly on one byte lane. Test
    # before binary rejection and require a strong, asymmetric signal.
    if not bom and len(raw) >= 8 and len(raw) % 2 == 0:
        sample = raw[:8192]
        even, odd = sample[::2], sample[1::2]
        a, b = even.count(0) / len(even), odd.count(0) / len(odd)
        if b >= .3 and a < .05:
            bom = "utf-16-le"
        elif a >= .3 and b < .05:
            bom = "utf-16-be"
    explicit_utf16 = [encoding for encoding in encodings if encoding.lower().replace("_", "-") in {"utf-16", "utf-16-le", "utf-16-be"}]
    if not bom and b"\0" in raw and not explicit_utf16:
        raise RetrievalError("Binary file", "binary")
    if bom:
        try:
            raw.decode(bom,errors="strict")
        except UnicodeDecodeError as exc:
            raise RetrievalError("Malformed BOM-declared encoding", "encoding") from exc
    declared = declared_encoding(raw, Path(relative).suffix.lower())
    candidates = ([bom] if bom else []) + ([declared] if declared else []) + (explicit_utf16 if b"\0" in raw else []) + ["utf-8"]
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
