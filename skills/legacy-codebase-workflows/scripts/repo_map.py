#!/usr/bin/env python3
"""Generate an offline, bounded, Aider-derived map of a working copy."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import sys
import tempfile
from collections import Counter, OrderedDict
from pathlib import Path

from repo_render import extract_declarations, render_grouped, render_lines, rendering_metadata
from repo_files import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_FILES, _safe_relative, contains_control_characters, read_safe_text, scan_repository, split_source_lines

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
sys.path.insert(0, str(VENDOR))
from aider_rank import rank_tags  # noqa: E402

VERSION = "1.1.0"
QUERY_DIR = VENDOR / "queries"
QUERY_PATHS = {
    "java": "tree-sitter-language-pack/java-tags.scm",
    "python": "tree-sitter-language-pack/python-tags.scm",
    "javascript": "tree-sitter-language-pack/javascript-tags.scm",
    "typescript": "tree-sitter-languages/typescript-tags.scm",
    "tsx": "tree-sitter-languages/typescript-tags.scm",
    "c": "tree-sitter-language-pack/c-tags.scm",
    "cpp": "tree-sitter-language-pack/cpp-tags.scm",
    "c_sharp": "tree-sitter-language-pack/csharp-tags.scm",
    "go": "tree-sitter-language-pack/go-tags.scm",
    "rust": "tree-sitter-language-pack/rust-tags.scm",
}
PARSER_NAMES = {"c_sharp": "csharp"}
MAX_TAGS_PER_FILE = 20_000
MAX_TOTAL_TAGS = 200_000
MAX_BUDGET = 1_000_000
SOURCE_LINE_CACHE_BYTES = 32 * 1024 * 1024


class LimitExceeded(ValueError):
    """A map-wide safety limit that must stop generation."""


class _SourceLineCache:
    """Per-run LRU bounded by retained Python storage, not file count.

    The loader verifies current source bytes once on each cache miss. Lines
    larger than the budget are returned without caching; rendering never
    retains an unbounded collection of source files.
    """

    def __init__(self, loader, max_bytes=SOURCE_LINE_CACHE_BYTES):
        self.loader = loader
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.entry_bytes = 0

    @property
    def retained_bytes(self):
        return self.entry_bytes + sys.getsizeof(self.entries)

    def __call__(self, path):
        cached = self.entries.get(path)
        if cached is not None:
            self.entries.move_to_end(path)
            return cached[0]
        lines = self.loader(path)
        # Include line/list, path, entry tuple and accounting-integer storage;
        # OrderedDict's hash table and LRU nodes are measured separately.
        cost = (sys.getsizeof(lines) + sum(sys.getsizeof(line) for line in lines)
                + sys.getsizeof(path) + sys.getsizeof((lines, 0)) + sys.getsizeof(0))
        if cost + sys.getsizeof(OrderedDict()) > self.max_bytes:
            return lines
        self.entries[path] = (lines, cost)
        self.entry_bytes += cost
        while self.entries and self.retained_bytes > self.max_bytes:
            _path, (_lines, evicted_cost) = self.entries.popitem(last=False)
            self.entry_bytes -= evicted_cost
        if not self.entries:
            # Release the dictionary's high-water hash-table allocation too.
            self.entries.clear()
        return lines


def _packages():
    return {name: importlib.metadata.version(name) for name in ("tree-sitter", "tree-sitter-language-pack", "tree-sitter-c-sharp", "networkx")}


def _atomic_write(path: Path, content: str):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=".repo-map-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _query(language: str):
    from tree_sitter import Query
    from tree_sitter_language_pack import get_language, get_parser

    path = QUERY_DIR / QUERY_PATHS[language]
    parser_name = PARSER_NAMES.get(language, language)
    language_object = get_language(parser_name)
    return get_parser(parser_name), Query(language_object, path.read_text(encoding="utf-8")), hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_cached(value, digest: str, query_digest: str, parser_version: str, lines: int) -> bool:
    if not isinstance(value, dict) or value.get("version") != VERSION or value.get("sha256") != digest or value.get("query_sha256") != query_digest or value.get("parser_version") != parser_version:
        return False
    tags = value.get("tags")
    if not isinstance(tags, list) or len(tags) > MAX_TAGS_PER_FILE:
        return False
    return all(isinstance(tag, dict) and set(tag) == {"kind", "name", "line"} and tag["kind"] in {"def", "ref"} and isinstance(tag["name"], str) and len(tag["name"]) <= 512 and isinstance(tag["line"], int) and 1 <= tag["line"] <= max(1, lines) for tag in tags)


def _extract(text: str, parser, query, path: str):
    from tree_sitter import QueryCursor

    tree = parser.parse(text.encode("utf-8"))
    captures = QueryCursor(query).captures(tree.root_node)
    result = []
    seen = set()
    for capture, nodes in sorted(captures.items()):
        kind = "def" if capture.startswith("name.definition.") else "ref" if capture.startswith("name.reference.") else None
        if kind is None:
            continue
        for node in nodes:
            name = node.text.decode("utf-8", "replace")
            if not name or len(name) > 512:
                continue
            tag = {"path": path, "line": node.start_point.row + 1, "name": name, "kind": kind}
            key = (tag["line"], name, kind)
            if key not in seen:
                result.append(tag)
                seen.add(key)
                if len(result) > MAX_TAGS_PER_FILE:
                    raise LimitExceeded(f"tag limit exceeded in {path}; map a narrower subtree")
    return sorted(result, key=lambda t: (t["line"], t["kind"], t["name"]))


def _tags(root: Path, output: Path, inventory: dict, *, map_format="lines", all_definitions=False):
    tags_by_file = {}
    parse_failures = []
    cache_dir = output / "cache"
    if cache_dir.is_symlink() or (cache_dir.exists() and not cache_dir.is_dir()):
        raise ValueError("cache path must be an ordinary directory")
    cache_dir.mkdir(exist_ok=True)
    if cache_dir.resolve().is_relative_to(root):
        raise ValueError("cache directory must be outside the source repository")
    parsers = {}
    total = 0
    parsed_files = 0
    packages = _packages()
    base_parser_version = ":".join((packages["tree-sitter"], packages["tree-sitter-language-pack"]))
    for entry in inventory["files"]:
        language = entry["language"]
        if language not in QUERY_PATHS:
            continue
        path = entry["path"]
        parser_version = base_parser_version
        if language == "c_sharp":
            parser_version += ":" + packages["tree-sitter-c-sharp"]
        try:
            text, current_digest = read_safe_text(root, path, max_file_bytes=max(entry["size"], 1))
            if current_digest != entry["sha256"]:
                raise ValueError("source changed during scan")
            if language not in parsers:
                parsers[language] = _query(language)
            parser, query, query_digest = parsers[language]
            cache_key = hashlib.sha256(f"{VERSION}\0{parser_version}\0{language}\0{query_digest}\0{current_digest}".encode()).hexdigest()
            cache_path = cache_dir / f"{cache_key}.json"
            cached = None
            try:
                if not cache_path.is_symlink() and cache_path.stat().st_nlink == 1 and cache_path.stat().st_size <= 16_000_000:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            line_count = len(split_source_lines(text))
            if _valid_cached(cached, current_digest, query_digest, parser_version, line_count):
                tags = [{**tag, "path": path} for tag in cached["tags"]]
            else:
                tags = _extract(text, parser, query, path)
                payload = {"version": VERSION, "sha256": current_digest, "query_sha256": query_digest, "parser_version": parser_version, "tags": [{key: tag[key] for key in ("kind", "name", "line")} for tag in tags]}
                _atomic_write(cache_path, json.dumps(payload, ensure_ascii=False, sort_keys=True))
            if map_format == "grouped" or all_definitions:
                tags = extract_declarations(text, parser, query, path, tags, strict_syntax=all_definitions)
            tags_by_file[path] = tags
            parsed_files += 1
            total += len(tags)
            if total > MAX_TOTAL_TAGS:
                raise LimitExceeded(f"total tag limit exceeded ({MAX_TOTAL_TAGS}); map a subtree")
        except LimitExceeded:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            parse_failures.append({"path": path, "reason": str(exc)})
    return tags_by_file, parsed_files, parse_failures


def _line(tag: dict, line_cache):
    lines = line_cache(tag["path"])
    if tag["line"] > len(lines):
        raise ValueError(f"source line vanished while rendering: {tag['path']}")
    snippet = "".join(" " if character != "\t" and contains_control_characters(character) else character for character in lines[tag["line"] - 1]).strip()
    return f"{tag['path']}:L{tag['line']}: {snippet[:240]}\n"


def generate(root: str | Path, output_dir: str | Path, *, budget: int = 16_384, subtrees=(), focus_files=(), focus_symbols=(), excludes=(), max_files=DEFAULT_MAX_FILES, max_file_bytes=DEFAULT_MAX_FILE_BYTES, inventory_only=False, map_format="grouped", all_definitions=False):
    root = Path(root).resolve(strict=True)
    output = Path(output_dir).resolve()
    if not root.is_dir():
        raise ValueError("repository path is not a directory")
    if output == root or output.is_relative_to(root):
        raise ValueError("output directory must be outside the source repository")
    if not 64 <= budget <= MAX_BUDGET:
        raise ValueError(f"budget must be 64..{MAX_BUDGET} estimated tokens")
    if map_format not in ("grouped", "lines"):
        raise ValueError("format must be grouped or lines")
    if all_definitions and inventory_only:
        raise ValueError("--all-definitions cannot be combined with --inventory-only")
    for path in [*subtrees, *focus_files]:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError(f"focus/subtree path must be relative: {path}")
    subtrees = tuple(_safe_relative(path, cli_input=True).as_posix() for path in subtrees)
    focus_files = tuple(_safe_relative(path, cli_input=True).as_posix() for path in focus_files)
    output.mkdir(parents=True, exist_ok=True)
    initial = {"tool": "legacy-codebase-workflows repo_map", "version": VERSION, "status": "in-progress", "source_root": str(root), "coverage": None, "map_sha256": None}
    _atomic_write(output / "repo-map.md", "# Repository inventory\n\nNo current symbol map. Inspect map.meta.json for generation status.\n")
    _atomic_write(output / "map.meta.json", json.dumps(initial, sort_keys=True, indent=2) + "\n")
    _atomic_write(output / "inventory.json", json.dumps({"root": str(root), "status": "in-progress", "files": []}, sort_keys=True, indent=2) + "\n")
    try:
        inventory = scan_repository(root, subtrees=subtrees, excludes=excludes, max_files=max_files, max_file_bytes=max_file_bytes)
    except (OSError, ValueError) as exc:
        initial.update(status="failed", failure={"stage": "inventory", "message": str(exc)})
        _atomic_write(output / "map.meta.json", json.dumps(initial, sort_keys=True, indent=2) + "\n")
        _atomic_write(output / "inventory.json", json.dumps({"root": str(root), "status": "failed", "files": [], "failure": initial["failure"]}, sort_keys=True, indent=2) + "\n")
        raise
    groups = Counter("/".join(entry["path"].split("/")[:2]) if entry["path"].count("/") >= 2 else (entry["path"].split("/")[0] if "/" in entry["path"] else "<root>") for entry in inventory["files"])
    summary = {"languages": dict(sorted(Counter(entry["language"] or entry["kind"] for entry in inventory["files"]).items())), "modules": [{"path": path, "files": count} for path, count in sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:20]], "modules_omitted": max(0, len(groups) - 20)}
    # Save the current scope before parsing/ranking can exceed their safety limits.
    _atomic_write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    preliminary = {
        "tool": "legacy-codebase-workflows repo_map", "version": VERSION,
        "status": "inventory-only" if inventory_only else "in-progress",
        "source_root": str(root), "revision": inventory["revision"], "dirty": inventory["dirty"], "git_notes": inventory["git_notes"],
        "working_copy_fingerprint": inventory["fingerprint"], "inventory_summary": summary,
        "selection": {"mode": "all-definitions" if all_definitions else "ranked", "subtrees": list(subtrees), "focus_files": list(focus_files), "focus_symbols": list(focus_symbols), "excludes": list(excludes)},
        "coverage": {"candidates_seen": inventory["totals"]["candidates_seen"], "selected_files": len(inventory["files"]), "parsed_files": None, "definitions_found": None},
        "skipped": inventory["skipped"],
        "truncated": any(item["path"] == "*" for item in inventory["skipped"]),
        "estimated_tokens": 0, "map_sha256": None,
        "rendering": rendering_metadata(map_format),
    }
    diagnostic = "# Repository inventory\n\nNo symbol map generated. Inspect inventory.json and choose a subtree.\n"
    _atomic_write(output / "repo-map.md", diagnostic)
    _atomic_write(output / "map.meta.json", json.dumps(preliminary, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    if inventory_only:
        return preliminary
    stage = "parsing"
    try:
        tags_by_file, parsed_count, parse_failures = _tags(root, output, inventory, map_format=map_format, all_definitions=all_definitions)
        preliminary["parse_failures"] = parse_failures
        preliminary["coverage"]["parsed_files"] = parsed_count
        if all_definitions and (parse_failures or any(item["path"] == "*" for item in inventory["skipped"] )):
            diagnostic_reason = f"; first parser failure: {parse_failures[0]['path']}: {parse_failures[0]['reason']}" if parse_failures else ""
            raise ValueError("all-definitions requires an untruncated selected scope without parse failures; inspect skips/parse failures and narrow the scope" + diagnostic_reason)
        stage = "ranking"
        ranked = rank_tags(tags_by_file, focus_files=focus_files, focus_symbols=focus_symbols)
        stage = "rendering"
        by_path = {entry["path"]: entry for entry in inventory["files"]}

        def read_source_lines(path):
            text, digest = read_safe_text(root, path, max_file_bytes=max(by_path[path]["size"], 1))
            if digest != by_path[path]["sha256"]:
                raise ValueError(f"source changed while rendering: {path}")
            return split_source_lines(text)

        source_lines = _SourceLineCache(read_source_lines)
        renderer = render_grouped if map_format == "grouped" else render_lines
        map_text, included, clipping = renderer(ranked, source_lines, budget, all_definitions=all_definitions)
        metadata = {
            "tool": "legacy-codebase-workflows repo_map", "version": VERSION, "status": "complete",
            "source_root": str(root), "revision": inventory["revision"], "dirty": inventory["dirty"], "git_notes": inventory["git_notes"],
            "working_copy_fingerprint": inventory["fingerprint"], "inventory_summary": summary,
            "fingerprint_scope": "selected readable files and skip reasons, from current bytes; ignored files and secret contents are excluded",
            "selection": {"mode": "all-definitions" if all_definitions else "ranked", "subtrees": list(subtrees), "focus_files": list(focus_files), "focus_symbols": list(focus_symbols), "excludes": list(excludes)},
            "limits": {"budget": budget, "max_files": max_files, "max_file_bytes": max_file_bytes, "max_tags_per_file": MAX_TAGS_PER_FILE, "max_total_tags": MAX_TOTAL_TAGS},
            "coverage": {"candidates_seen": inventory["totals"]["candidates_seen"], "selected_files": len(inventory["files"]), "parsed_files": parsed_count, "files_with_definitions": len({tag["path"] for tag in ranked}), "definitions_found": len(ranked), "definitions_in_map": len(included), "definitions_omitted": len(ranked) - len(included)},
            "skipped": inventory["skipped"], "parse_failures": parse_failures,
            "focus_not_found": {
                "files_not_parsed": [path for path in focus_files if path not in tags_by_file],
                "symbols_without_definitions": [name for name in focus_symbols if not any(tag["kind"] == "def" and tag["name"] == name for tags in tags_by_file.values() for tag in tags)],
            },
            "unsupported_languages": sorted({entry["path"] for entry in inventory["files"] if entry["language"] is None and entry["kind"] == "other" and Path(entry["path"]).suffix}),
            "descriptors": sorted(entry["path"] for entry in inventory["files"] if entry["kind"] == "descriptor"),
            "truncated": bool(clipping) or len(included) < len(ranked) or any(item["path"] == "*" for item in inventory["skipped"]),
            "estimated_tokens": math.ceil(len(map_text) / 4), "estimator": "ceil(Unicode characters / 4); a size estimate, not a model tokenizer",
            "map_sha256": hashlib.sha256(map_text.encode("utf-8")).hexdigest(),
            "dependencies": _packages(),
            "rendering": rendering_metadata(map_format, clipping),
        }
        stage = "publication"
        _atomic_write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        _atomic_write(output / "repo-map.md", map_text)
        _atomic_write(output / "map.meta.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return metadata
    except (OSError, ValueError, ImportError, KeyError) as exc:
        preliminary.update(status="failed", failure={"stage": stage, "message": str(exc)})
        if hasattr(exc, "required_estimated_tokens"):
            preliminary["failure"]["required_estimated_tokens"] = exc.required_estimated_tokens
        _atomic_write(output / "map.meta.json", json.dumps(preliminary, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="source directory; never modified")
    parser.add_argument("--output-dir", required=True, help="artifact directory outside source")
    parser.add_argument("--format", choices=("grouped", "lines"), default="grouped", dest="map_format", help="grouped declaration headers (default), or legacy ranked one-line snippets")
    parser.add_argument("--all-definitions", action="store_true", help="require every query definition in the selected scope; fail if budget or parsing prevents it")
    parser.add_argument("--inventory-only", action="store_true", help="write inventory without installing parsers or ranking symbols")
    parser.add_argument("--budget", type=int, default=16_384, help="estimated tokens; ceil(Unicode characters / 4), 64..1000000")
    parser.add_argument("--subtree", action="append", default=[], help="relative module/subtree; repeatable")
    parser.add_argument("--focus-file", action="append", default=[], help="relative file to prioritize; repeatable")
    parser.add_argument("--focus-symbol", action="append", default=[], help="identifier to prioritize; repeatable")
    parser.add_argument("--exclude", action="append", default=[], help="glob path or basename exclusion; repeatable")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES, help="maximum candidate files, 1..100000")
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES, help="maximum bytes per file, 1..20000000")
    args = parser.parse_args(argv)
    try:
        metadata = generate(args.repository, args.output_dir, budget=args.budget, subtrees=args.subtree, focus_files=args.focus_file, focus_symbols=args.focus_symbol, excludes=args.exclude, max_files=args.max_files, max_file_bytes=args.max_file_bytes, inventory_only=args.inventory_only, map_format=args.map_format, all_definitions=args.all_definitions)
    except (OSError, ValueError, ImportError, KeyError) as exc:
        print(f"repo_map: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": metadata["status"], "map": str(Path(args.output_dir).resolve() / "repo-map.md"), "metadata": str(Path(args.output_dir).resolve() / "map.meta.json"), "coverage": metadata["coverage"], "inventory_summary": metadata["inventory_summary"], "estimated_tokens": metadata["estimated_tokens"], "truncated": metadata["truncated"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
