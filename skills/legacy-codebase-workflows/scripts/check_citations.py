#!/usr/bin/env python3
"""Check JSON evidence cards against exact current source bytes and line ranges."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from repo_files import read_safe_text, split_source_lines


def check_cards(root: str | Path, evidence: dict) -> dict:
    root = Path(root).resolve(strict=True)
    cards = evidence.get("citations") if isinstance(evidence, dict) else None
    if not isinstance(cards, list) or not cards:
        raise ValueError("evidence must contain a nonempty citations array")
    results = []
    for index, card in enumerate(cards):
        errors = []
        if not isinstance(card, dict):
            results.append({"index": index, "valid": False, "errors": ["citation is not an object"]})
            continue
        path = card.get("path")
        digest = card.get("sha256")
        start = card.get("start_line")
        end = card.get("end_line")
        quote = card.get("quote")
        if not isinstance(path, str) or not path:
            errors.append("path must be a nonempty relative string")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append("sha256 must be a lowercase 64-character hex digest")
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 1 or end < start:
            errors.append("invalid line range")
        if not isinstance(quote, str) or not quote.strip():
            errors.append("quote must be nonempty")
        if not errors:
            try:
                text, actual_digest = read_safe_text(root, path, max_file_bytes=20_000_000)
                lines = split_source_lines(text)
                if actual_digest != digest:
                    errors.append("stale source sha256")
                if end > len(lines):
                    errors.append("line range outside source")
                elif quote.replace("\r\n", "\n") not in "\n".join(lines[start - 1:end]):
                    errors.append("quote does not occur in cited lines")
            except ValueError as exc:
                errors.append(str(exc))
        results.append({"index": index, "path": path, "valid": not errors, "errors": errors})
    return {"valid": all(item["valid"] for item in results), "checked": len(results), "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("evidence_json", help="JSON file containing {\"citations\": [{path, sha256, start_line, end_line, quote}]} ")
    args = parser.parse_args(argv)
    try:
        evidence = json.loads(Path(args.evidence_json).read_text(encoding="utf-8"))
        result = check_cards(args.repository, evidence)
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
