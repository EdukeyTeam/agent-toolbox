#!/usr/bin/env python3
"""Outline, page and account for the members of large Java source files.

outline   one line per type and member of a file, with line ranges and sizes
slice     the exact lines of one member or line range, with source identity
baseline  record tracked files and the surrounding scope before a refactor
compare   account for every recorded member after the refactor

The scanner is lexical. It compares token sequences, so whitespace and comment
changes are ignored and every code or literal change is detected. It does not
resolve types and cannot show that moved code behaves the same.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from pathlib import Path

from repo_files import _candidates, _safe_relative, _secret, git_context, read_safe_text, split_source_lines

SCHEMA = "member-ledger/1"
MAX_FILE_BYTES = 20_000_000
DEFAULT_MAX_FILES = 2_000
HARD_MAX_FILES = 20_000
DEFAULT_SLICE_LINES = 400
DISPOSITIONS = ("deleted", "merged", "replaced", "intentional-change")
MODIFIERS = frozenset("public protected private abstract static final synchronized native transient volatile strictfp default sealed".split())
TYPE_WORDS = frozenset(("class", "interface", "enum", "record"))
CLOSERS = {"(": ")", "[": "]", "{": "}"}

# `>` is never merged into `>>` or `>=`: nested generics then compare equal
# however they are spaced. Every other operator uses the longest match, which
# keeps `a++ + b` and `a + ++b` distinct.
_TOKEN = re.compile(r"""
    (?P<space>\s+|﻿)
  | (?P<comment>//[^\r\n]*|/\*.*?\*/)
  | (?P<text>\"\"\"(?:[^"\\]|\\.|"(?!""))*\"\"\")
  | (?P<string>"(?:[^"\\\r\n]|\\.)*")
  | (?P<char>'(?:[^'\\\r\n]|\\.)+')
  | (?P<word>(?:[^\W\d]|\$)[\w$]*)
  | (?P<number>\d[\w.]*)
  | (?P<op>\.\.\.|<<=|->|::|\+\+|--|&&|\|\||==|!=|<=|<<|[-+*/&|^%]=)
  | (?P<bad>/\*|"|')
  | (?P<punct>.)
""", re.S | re.X)


class ScanError(ValueError):
    """The file cannot be split into members reliably."""


def _digest(tokens) -> str:
    return hashlib.sha256("\0".join(tokens).encode("utf-8")).hexdigest()


class _Scanner:
    def __init__(self, text: str):
        if "\r" in text and "\n" not in text:
            raise ScanError("bare CR line endings are not supported")
        self.line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
        self.texts: list[str] = []
        self.offsets: list[int] = []
        self.words: list[bool] = []
        self.lead: dict[int, int] = {}  # token index -> offset of the comment block before it
        pending = None
        for match in _TOKEN.finditer(text):
            group = match.lastgroup
            if group == "space":
                continue
            if group == "comment":
                # A comment ending the previous declaration's last line is not documentation for the next one.
                trailing = self.texts and self._line_at(match.start()) == self._end_line(len(self.texts) - 1)
                if pending is None and not trailing:
                    pending = match.start()
                continue
            if group == "bad":
                kind = "block comment" if match.group() == "/*" else "string or character literal"
                raise ScanError(f"unterminated {kind} at line {self._line_at(match.start())}")
            if pending is not None:
                self.lead[len(self.texts)] = pending
                pending = None
            self.texts.append(match.group())
            self.offsets.append(match.start())
            self.words.append(group == "word")
        self.match = self._pair_brackets()
        self.members: list[dict] = []
        self.types: list[dict] = []
        self._ids: dict[str, int] = {}

    def _line_at(self, offset: int) -> int:
        return bisect.bisect_right(self.line_starts, offset)

    def _line(self, index: int) -> int:
        return self._line_at(self.offsets[index])

    def _end_line(self, index: int) -> int:
        return self._line_at(self.offsets[index] + len(self.texts[index]) - 1)

    def _pair_brackets(self) -> dict[int, int]:
        pairs, stack = {}, []
        for index, token in enumerate(self.texts):
            if token in CLOSERS:
                stack.append(index)
            elif token in (")", "]", "}"):
                if not stack or CLOSERS[self.texts[stack[-1]]] != token:
                    raise ScanError(f"unbalanced {token!r} at line {self._line(index)}")
                pairs[stack.pop()] = index
        if stack:
            raise ScanError(f"unclosed {self.texts[stack[-1]]!r} opened at line {self._line(stack[-1])}")
        return pairs

    def _skip_annotation(self, index: int, end: int) -> int:
        """Index after an annotation starting at `@`, or `index` when it is not one."""
        t = self.texts
        if t[index] != "@" or index + 1 >= end or not self.words[index + 1] or t[index + 1] == "interface":
            return index
        index += 2
        while index + 1 < end and t[index] == "." and self.words[index + 1]:
            index += 2
        if index < end and t[index] == "(":
            index = self.match[index] + 1
        return index

    def _type_keyword(self, index: int, end: int) -> bool:
        t = self.texts
        if index + 1 >= end or not self.words[index + 1] or (index and t[index - 1] == "."):
            return False
        after = t[index + 2] if index + 2 < end else ""
        if t[index] == "enum":  # an ordinary identifier before Java 5
            return after in ("{", "implements")
        if t[index] == "record":  # an ordinary identifier before Java 16
            return after in ("(", "<")
        return True

    def _is_constructor(self, start: int, name: int, simple: str) -> bool:
        """A constructor has no return type: only annotations, modifiers and type parameters precede its name."""
        t, index = self.texts, start
        if t[name] != simple:
            return False
        while index < name:
            skipped = self._skip_annotation(index, name)
            if skipped != index:
                index = skipped
            elif t[index] in MODIFIERS:
                index += 1
            elif t[index] == "<":
                depth = 0
                while index < name:
                    depth += (t[index] == "<") - (t[index] == ">")
                    index += 1
                    if depth == 0:
                        break
            else:
                return False
        return True

    def _parameters(self, opening: int) -> str:
        t, closing = self.texts, self.match[opening]
        parts, current, angle, index = [], [], 0, opening + 1
        while index < closing:
            skipped = self._skip_annotation(index, closing)
            if skipped != index:
                index = skipped
                continue
            token = t[index]
            if token in CLOSERS:
                current.extend(range(index, self.match[index] + 1))
                index = self.match[index] + 1
                continue
            angle += (token == "<") - (token == ">")
            if token == "," and angle == 0:
                parts.append(current)
                current = []
            elif token != "final":
                current.append(index)
            index += 1
        if current:
            parts.append(current)
        types = []
        for part in parts:
            names = [position for position, token_index in enumerate(part) if self.words[token_index]]
            if len(names) > 1:  # drop the parameter name; `String a[]` keeps its brackets
                del part[names[-1]]
            types.append("".join(t[token_index] for token_index in part))
        return ",".join(types)

    def _add(self, kind: str, name: str, ident: str, owner: str, start: int, end: int, header_end: int, body: int | None = None) -> None:
        key = f"{owner}#{ident}"
        seen = self._ids[key] = self._ids.get(key, 0) + 1
        modifiers, index = [], start
        while index < header_end:
            skipped = self._skip_annotation(index, header_end)
            if skipped != index:
                index = skipped
            elif self.texts[index] in MODIFIERS:
                modifiers.append(self.texts[index])
                index += 1
            else:
                break
        member = {
            "id": key if seen == 1 else f"{key}~{seen}", "kind": kind, "name": name, "owner": owner, "modifiers": modifiers,
            "header": _pretty(self.texts[start:header_end]),
            "start_line": self._line(start), "end_line": self._end_line(end),
            "tokens": end - start + 1, "token_sha256": _digest(self.texts[start:end + 1]),
            "body_sha256": _digest(self.texts[body:end + 1]) if body is not None else None,
        }
        member["lines"] = member["end_line"] - member["start_line"] + 1
        if start in self.lead:
            member["doc_start_line"] = self._line_at(self.lead[start])
        self.members.append(member)

    def scan(self) -> None:
        index, end = 0, len(self.texts)
        while index < end:
            index = index + 1 if self.texts[index] == ";" else self._declaration(index, end, "")
        counts: dict[str, int] = {}
        for member in self.members:
            if member["kind"] != "type":
                counts[member["owner"]] = counts.get(member["owner"], 0) + 1
        for entry in self.types:
            entry["members"] = counts.get(entry["name"], 0)

    def _body(self, index: int, end: int, owner: str, is_enum: bool) -> None:
        if is_enum:
            index = self._enum_constants(index, end, owner)
        while index < end:
            index = index + 1 if self.texts[index] == ";" else self._declaration(index, end, owner)

    def _enum_constants(self, index: int, end: int, owner: str) -> int:
        t, start = self.texts, index
        while index <= end:
            token = t[index] if index < end else ";"
            if token in CLOSERS:
                index = self.match[index] + 1
                continue
            if token in (",", ";"):
                if index > start:
                    name = start
                    while self._skip_annotation(name, index) != name:
                        name = self._skip_annotation(name, index)
                    self._add("enum-constant", t[name], f"constant:{t[name]}", owner, start, index - 1, name + 1)
                start = index + 1
                if token == ";":
                    return min(index + 1, end)
            index += 1
        return end

    def _declaration(self, start: int, end: int, owner: str) -> int:
        """Record one declaration starting at `start`; return the index after it."""
        t, index = self.texts, start
        simple = owner.rsplit(".", 1)[-1]
        declarator_closed = False
        paren = keyword = field_name = assigned = None  # `assigned` is the index of a field's first `=`
        angle = 0
        while index < end:
            skipped = self._skip_annotation(index, end)
            if skipped != index:
                index = skipped
                continue
            token = t[index]
            if token == "(":
                if paren is None and assigned is None and keyword is None:
                    paren = index
                index = self.match[index] + 1
                continue
            if token == "[":
                index = self.match[index] + 1
                continue
            if token == "{":
                closing = self.match[index]
                if keyword is not None:
                    name = t[keyword + 1]
                    qualified = f"{owner}.{name}" if owner else name
                    kind = "annotation" if t[keyword] == "interface" and keyword > start and t[keyword - 1] == "@" else t[keyword]
                    self.types.append({"name": qualified, "kind": kind, "start_line": self._line(start), "end_line": self._end_line(closing)})
                    self._add("type", name, "<type>", qualified, start, index - 1, index)
                    self._body(index + 1, closing, qualified, t[keyword] == "enum")
                    return closing + 1
                if assigned is not None:  # array initializer, anonymous class or lambda block of a field
                    index = closing + 1
                    continue
                if not owner:  # module declaration or other top-level block
                    return closing + 1
                if paren is not None:
                    name = t[paren - 1]
                    kind = "constructor" if self._is_constructor(start, paren - 1, simple) else "method"
                    self._add(kind, name, f"{name}({self._parameters(paren)})", owner, start, closing, index, index)
                elif simple in t[start:index]:  # compact record constructor
                    self._add("constructor", simple, simple, owner, start, closing, index, index)
                elif "static" in t[start:index]:
                    self._add("static-init", "<static-init>", "<static-init>", owner, start, closing, index, index)
                else:
                    self._add("instance-init", "<init>", "<init>", owner, start, closing, index, index)
                return closing + 1
            if token == ";":
                if not owner:  # package and import statements
                    return index + 1
                if paren is not None:
                    name = t[paren - 1]
                    self._add("method", name, f"{name}({self._parameters(paren)})", owner, start, index, index)
                else:
                    name = field_name or "<unnamed>"
                    self._add("field", name, f"field:{name}", owner, start, index, index if assigned is None else assigned)
                return index + 1
            if paren is None and assigned is None:
                if token == "=":
                    assigned = index
                elif keyword is None and token in TYPE_WORDS and self._type_keyword(index, end):
                    keyword = index
                elif not declarator_closed:
                    angle += (token == "<") - (token == ">")
                    if token == "," and angle == 0:
                        declarator_closed = True
                    elif self.words[index]:
                        field_name = token
            index += 1
        raise ScanError(f"declaration starting at line {self._line(start)} has no end")


def _pretty(tokens) -> str:
    out, previous = [], ""
    for token in tokens:
        attached = previous in (")", "]", ">") or (previous[-1:].isalnum() and previous not in MODIFIERS) if token in ("(", "<") else token in (",", ")", "[", "]", ".", ">", ";", "...")
        if out and (attached or previous in ("(", "[", ".", "<", "@")):
            out[-1] += token
        else:
            out.append(token)
        previous = token
    return " ".join(out)


def scan_java(text: str) -> dict:
    """Types and members of one Java compilation unit, in source order."""
    scanner = _Scanner(text)
    scanner.scan()
    return {"types": scanner.types, "members": scanner.members}


def read_source(root: Path, path: str, encoding: str) -> tuple[str, str]:
    if not path.lower().endswith(".java"):
        raise ValueError(f"only Java source is supported: {path}")
    try:
        return read_safe_text(root, path, max_file_bytes=MAX_FILE_BYTES, encoding=encoding)
    except ValueError as exc:
        if str(exc) == "non-UTF-8 file":
            raise ValueError(f"{path} is not valid UTF-8; confirm its encoding from the build configuration and pass --encoding (for example cp1250)") from exc
        raise


def outline_file(root: str | Path, path: str, encoding: str = "utf-8") -> dict:
    root = Path(root).resolve(strict=True)
    path = _safe_relative(path, cli_input=True).as_posix()
    text, digest = read_source(root, path, encoding)
    try:
        scanned = scan_java(text)
    except ScanError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return {"schema": SCHEMA, "path": path, "sha256": digest, "encoding": encoding, "lines": len(split_source_lines(text)), **scanned}


def _range(member: dict) -> str:
    return f"L{member['start_line']}" if member["lines"] == 1 else f"L{member['start_line']}-L{member['end_line']}"


def render_outline(outline: dict, top: int = 5) -> str:
    members = [member for member in outline["members"] if member["kind"] != "type"]
    kinds: dict[str, int] = {}
    for member in members:
        kinds[member["kind"]] = kinds.get(member["kind"], 0) + 1
    lines = [
        f"{outline['path']} {outline['lines']} lines sha256={outline['sha256']} encoding={outline['encoding']}",
        f"{len(outline['types'])} types, {len(members)} members: " + (", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items())) or "none"),
    ]
    largest = sorted(members, key=lambda member: (-member["lines"], member["start_line"]))[:top]
    if largest:
        lines.append("largest: " + "; ".join(f"{member['id']} {member['lines']} lines" for member in largest))
    by_owner: dict[str, list[dict]] = {}
    for member in members:
        by_owner.setdefault(member["owner"], []).append(member)
    for entry in outline["types"]:
        lines.append(f"{entry['kind']} {entry['name']} L{entry['start_line']}-L{entry['end_line']} ({entry['members']} members)")
        for member in by_owner.get(entry["name"], []):
            modifiers = f" [{' '.join(member['modifiers'])}]" if member["modifiers"] else ""
            lines.append(f"{_range(member)} {member['lines']} {member['kind']} {member['id'].split('#', 1)[1]}{modifiers}")
    return "\n".join(lines) + "\n"


def find_member(outline: dict, selector: str) -> dict:
    members = outline["members"]
    for candidates in ([m for m in members if m["id"] == selector], [m for m in members if m["id"].split("#", 1)[1] == selector], [m for m in members if m["name"] == selector and m["kind"] != "type"]):
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            raise ValueError(f"{selector!r} matches several members: " + ", ".join(m["id"] for m in candidates))
    raise ValueError(f"no member matches {selector!r}; run outline to list member ids")


def slice_file(root: str | Path, path: str, *, member: str | None = None, lines: tuple[int, int] | None = None, encoding: str = "utf-8", with_doc: bool = False, max_lines: int = DEFAULT_SLICE_LINES) -> str:
    root = Path(root).resolve(strict=True)
    path = _safe_relative(path, cli_input=True).as_posix()
    text, digest = read_source(root, path, encoding)
    source = split_source_lines(text)
    label = ""
    if member is not None:
        found = find_member(outline_file(root, path, encoding), member)
        start, end = found.get("doc_start_line", found["start_line"]) if with_doc else found["start_line"], found["end_line"]
        label = f" member={found['id']}"
    else:
        start, end = lines
    if not 1 <= start <= end <= len(source):
        raise ValueError(f"line range L{start}-L{end} is outside {path} ({len(source)} lines)")
    shown = end if max_lines <= 0 else min(end, start + max_lines - 1)
    out = [f"{path} L{start}-L{shown} of {len(source)} sha256={digest} encoding={encoding}{label}"]
    out.extend(f"{number}: {source[number - 1]}" for number in range(start, shown + 1))
    if shown < end:
        out.append(f"[truncated: {end - shown} more lines; continue with --lines {shown + 1}-{end}]")
    return "\n".join(out) + "\n"


def _scope_files(root: Path, scope: list[str], max_files: int) -> list[str]:
    if not scope:
        return []
    if not 1 <= max_files <= HARD_MAX_FILES:
        raise ValueError(f"--max-files must be 1..{HARD_MAX_FILES}")
    subtrees = tuple(s for s in (_safe_relative(item, cli_input=True).as_posix() if item != "." else "." for item in scope) if s != ".")
    found = []
    iterator = _candidates(root, git_context(root), subtrees)
    try:
        for relative in iterator:
            rel = _safe_relative(relative)
            if rel.suffix.lower() != ".java" or _secret(rel):
                continue
            if subtrees and not any(relative == s or relative.startswith(s + "/") for s in subtrees):
                continue
            found.append(relative)
            if len(found) > max_files:
                raise ValueError(f"scope holds more than {max_files} Java files; narrow --scope or raise --max-files (at most {HARD_MAX_FILES})")
    finally:
        iterator.close()
    return sorted(found)


def _identity(root: Path, path: str) -> str | None:
    """Byte hash of a file that could not be scanned, or None when it cannot be read."""
    try:
        return read_safe_text(root, path, max_file_bytes=MAX_FILE_BYTES, encoding="latin-1")[1]
    except ValueError:
        return None


def _scan_many(root: Path, paths, encoding: str) -> tuple[dict[str, dict], list[dict]]:
    scanned, unscanned = {}, []
    for path in paths:
        try:
            scanned[path] = outline_file(root, path, encoding)
        except ValueError as exc:
            unscanned.append({"path": path, "reason": str(exc).removeprefix(f"{path}: ")})
    return scanned, unscanned


def build_baseline(root: str | Path, tracked: list[str], scope: list[str] = (), encoding: str = "utf-8", max_files: int = DEFAULT_MAX_FILES) -> dict:
    root = Path(root).resolve(strict=True)
    tracked = sorted({_safe_relative(path, cli_input=True).as_posix() for path in tracked})
    if not tracked:
        raise ValueError("at least one --track file is required")
    files = {path: outline_file(root, path, encoding) for path in tracked}  # a tracked file must scan
    scope = sorted(set(scope))
    others, unscanned = _scan_many(root, [path for path in _scope_files(root, scope, max_files) if path not in files], encoding)
    for item in unscanned:  # identity lets compare ignore a file that stays unscannable and unchanged
        item["sha256"] = _identity(root, item["path"])
    return {
        "schema": SCHEMA, "encoding": encoding, "tracked": tracked, "scope": scope, "max_files": max_files, "files": files,
        "preexisting": {path: {member["id"]: member["token_sha256"] for member in outline["members"]} for path, outline in others.items()},
        "unscanned": unscanned,
    }


def compare(root: str | Path, baseline: dict, decisions: dict | None = None, strict: bool = False) -> dict:
    root = Path(root).resolve(strict=True)
    if not isinstance(baseline, dict) or baseline.get("schema") != SCHEMA:
        raise ValueError(f"baseline is not a {SCHEMA} file")
    encoding, tracked = baseline["encoding"], baseline["tracked"]
    existing_tracked = [path for path in tracked if (root / path).is_file()]
    paths = sorted(set(existing_tracked) | set(_scope_files(root, baseline["scope"], baseline.get("max_files", DEFAULT_MAX_FILES))))
    current, unscanned = _scan_many(root, paths, encoding)
    known_unscanned = {item["path"]: item.get("sha256") for item in baseline.get("unscanned", [])}
    blocking = [item for item in unscanned if item["path"] not in known_unscanned or known_unscanned[item["path"]] != _identity(root, item["path"])]

    before = {path: {member["id"]: member["token_sha256"] for member in outline["members"]} for path, outline in baseline["files"].items()}
    before.update(baseline.get("preexisting", {}))

    def existed(path: str, member: dict) -> bool:
        return before.get(path, {}).get(member["id"]) == member["token_sha256"]

    by_token: dict[str, list] = {}
    by_body: dict[tuple, list] = {}
    types_by_name: dict[str, list] = {}
    for path, outline in current.items():
        for member in outline["members"]:
            if existed(path, member):
                continue  # code that was already there cannot be the destination of a move
            by_token.setdefault(member["token_sha256"], []).append((path, member))
            if member["body_sha256"]:
                by_body.setdefault((member["name"], member["body_sha256"]), []).append((path, member))
            if member["kind"] == "type":
                types_by_name.setdefault(member["name"], []).append((path, member))

    decided = {}
    for entry in (decisions or {}).get("decisions", []):
        if not isinstance(entry, dict) or entry.get("disposition") not in DISPOSITIONS or not str(entry.get("reason", "")).strip() or not isinstance(entry.get("member"), str):
            raise ValueError(f"each decision needs member, a reason and a disposition from {', '.join(DISPOSITIONS)}")
        decided[entry["member"]] = entry

    records, used, claimed = [], set(), set()
    for path in tracked:
        now = {member["id"]: member for member in current.get(path, {}).get("members", [])}
        for member in baseline["files"][path]["members"]:
            key = f"{path}::{member['id']}"
            here = now.get(member["id"])
            record = {"member": key, "kind": member["kind"], "was": {"start_line": member["start_line"], "end_line": member["end_line"], "lines": member["lines"], "modifiers": member["modifiers"]}}
            targets = []
            if here is not None and here["token_sha256"] == member["token_sha256"]:
                status = "unchanged"
            elif targets := by_token.get(member["token_sha256"], []):
                status = "moved"
            elif targets := (types_by_name.get(member["name"], []) if member["kind"] == "type" else by_body.get((member["name"], member["body_sha256"]), [])):
                status = "signature-changed"
            elif here is not None:
                status, targets = "modified", [(path, here)]
            else:
                status = "missing"
            if here is not None:
                claimed.add((path, here["id"]))
            if status != "unchanged":
                record["now"] = [{"member": f"{target_path}::{target['id']}", "start_line": target["start_line"], "end_line": target["end_line"], "lines": target["lines"], "modifiers": target["modifiers"]} for target_path, target in targets]
                used.update((target_path, target["id"]) for target_path, target in targets)
                if status in ("moved", "signature-changed") and here is not None and (path, here["id"]) not in {(p, t["id"]) for p, t in targets}:
                    record["origin"] = "still present with different content"
            record["status"] = status
            needs_decision = status == "missing" or (strict and status in ("modified", "signature-changed"))
            if key in decided:
                record["decision"] = {name: decided[key][name] for name in ("disposition", "reason", "into") if name in decided[key]}
            record["accounted"] = not needs_decision or key in decided
            records.append(record)

    new_files = {path for path in current if path not in before}
    report_in = set(tracked) | new_files | {path for path, _ in used}
    added = sorted(f"{path}::{member['id']}" for path in sorted(report_in & set(current)) for member in current[path]["members"]
                   if not existed(path, member) and (path, member["id"]) not in used and (path, member["id"]) not in claimed)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    known = {record["member"] for record in records}
    unaccounted = [record["member"] for record in records if not record["accounted"]]
    return {
        "schema": SCHEMA, "passed": not unaccounted and not blocking, "strict": strict, "tracked": tracked, "scope": baseline["scope"],
        "files_scanned": len(current), "unscanned": blocking, "counts": counts, "unaccounted": unaccounted,
        "added": added, "unused_decisions": sorted(set(decided) - known), "members": records,
    }


def render_comparison(result: dict) -> str:
    counts = result["counts"]
    total = sum(counts.values())
    lines = [f"{total} tracked members: " + ", ".join(f"{counts.get(status, 0)} {status}" for status in ("unchanged", "moved", "signature-changed", "modified", "missing")) + f"; {len(result['added'])} added"]
    scope = ", ".join(result["scope"]) or "tracked files only"
    lines.append(f"searched {result['files_scanned']} files: {', '.join(result['tracked'])}; scope: {scope}")
    lines.extend(f"UNSCANNED {item['path']}: {item['reason']}" for item in result["unscanned"])
    destinations: dict[str, int] = {}
    for record in result["members"]:
        status = record["status"]
        if status == "unchanged":
            continue
        targets = record.get("now", [])
        if status == "moved" and "origin" not in record:
            destination = targets[0]["member"].split("::", 1)[0]
            destinations[destination] = destinations.get(destination, 0) + 1
            continue
        was = record["was"]
        line = f"{status.upper()} {record['member']} was L{was['start_line']}-L{was['end_line']}"
        if status == "modified":
            line += f", now L{targets[0]['start_line']}-L{targets[0]['end_line']}"
        elif targets:
            line += " -> " + ", ".join(f"{target['member']} L{target['start_line']}-L{target['end_line']}" for target in targets)
        if status == "signature-changed" and targets and targets[0]["modifiers"] != was["modifiers"]:
            line += f" modifiers [{' '.join(was['modifiers'])}] -> [{' '.join(targets[0]['modifiers'])}]"
        if "origin" in record:
            line += f" (origin {record['origin']})"
        if "decision" in record:
            line += f" decision: {record['decision']['disposition']}"
        elif not record["accounted"]:
            line += " NEEDS DECISION"
        lines.append(line)
    lines.extend(f"moved verbatim: {count} -> {path}" for path, count in sorted(destinations.items()))
    lines.extend(f"ADDED {member}" for member in result["added"])
    lines.extend(f"UNUSED DECISION {member}" for member in result["unused_decisions"])
    verdict = "PASS" if result["passed"] else f"FAIL: unaccounted members {len(result['unaccounted'])}, unscanned files {len(result['unscanned'])}"
    lines.append(f"{verdict}. Token identity is not behavioral equivalence; 'missing' means not found in the searched files.")
    return "\n".join(lines) + "\n"


def _write_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def _line_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"L?(\d+)(?:-L?(\d+))?", value)
    if not match:
        raise argparse.ArgumentTypeError("use START-END, for example 120-180")
    return int(match.group(1)), int(match.group(2) or match.group(1))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("repository")
    encoded = argparse.ArgumentParser(add_help=False)
    encoded.add_argument("--encoding", default="utf-8", help="source encoding, for example cp1250 or iso-8859-2 (default: utf-8; never guessed)")

    sub = commands.add_parser("outline", parents=[shared, encoded], help="list the types and members of one file")
    sub.add_argument("path")
    sub.add_argument("--json", help="also write the complete outline to this file")
    sub = commands.add_parser("slice", parents=[shared, encoded], help="print the lines of one member or range")
    sub.add_argument("path")
    choice = sub.add_mutually_exclusive_group(required=True)
    choice.add_argument("--member", help="member id, its part after '#', or a unique member name")
    choice.add_argument("--lines", type=_line_range, metavar="START-END")
    sub.add_argument("--with-doc", action="store_true", help="include the comment block directly before the member")
    sub.add_argument("--max-lines", type=int, default=DEFAULT_SLICE_LINES, help=f"page size; 0 prints everything (default: {DEFAULT_SLICE_LINES})")
    sub = commands.add_parser("baseline", parents=[shared, encoded], help="record members before a refactor")
    sub.add_argument("--track", action="append", default=[], required=True, metavar="FILE", help="file whose members must all be accounted for; repeatable")
    sub.add_argument("--scope", action="append", default=[], metavar="DIR", help="directory where members may be moved; repeatable")
    sub.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    sub.add_argument("--output", required=True, help="baseline JSON file to write")
    sub = commands.add_parser("compare", parents=[shared], help="account for every baseline member")
    sub.add_argument("baseline")
    sub.add_argument("--decisions", help="JSON file: {\"decisions\": [{member, disposition, reason}]}")
    sub.add_argument("--strict", action="store_true", help="modified and signature-changed members also need a decision")
    sub.add_argument("--json", help="also write the complete ledger to this file")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        if args.command == "outline":
            outline = outline_file(args.repository, args.path, args.encoding)
            if args.json:
                _write_json(args.json, outline)
            sys.stdout.write(render_outline(outline))
        elif args.command == "slice":
            sys.stdout.write(slice_file(args.repository, args.path, member=args.member, lines=args.lines, encoding=args.encoding, with_doc=args.with_doc, max_lines=args.max_lines))
        elif args.command == "baseline":
            baseline = build_baseline(args.repository, args.track, args.scope, args.encoding, args.max_files)
            _write_json(args.output, baseline)
            members = sum(len(outline["members"]) for outline in baseline["files"].values())
            sys.stdout.write(f"recorded {members} members of {len(baseline['tracked'])} tracked files; {len(baseline['preexisting'])} other files in scope; {len(baseline['unscanned'])} unscanned\n")
            sys.stdout.writelines(f"UNSCANNED {item['path']}: {item['reason']}\n" for item in baseline["unscanned"])
        else:
            decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8")) if args.decisions else None
            result = compare(args.repository, json.loads(Path(args.baseline).read_text(encoding="utf-8")), decisions, args.strict)
            if args.json:
                _write_json(args.json, result)
            sys.stdout.write(render_comparison(result))
            return 0 if result["passed"] else 1
    except (OSError, ValueError, KeyError, LookupError) as exc:
        sys.stderr.write(f"member_ledger: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
