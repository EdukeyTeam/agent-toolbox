#!/usr/bin/env python3
"""Engine-independent source-range retrieval evaluation (Python 3.12+, stdlib).

Adapters implement search(query: str, limit: int) -> list[Result]. Paths in Result
are corpus-relative; ranges are inclusive, one-based; text starts at startLine.
Add an adapter without changing score_question or summarize. The command adapter
splits its template with shlex BEFORE replacing {query}/{limit}; it never uses a
shell. Quote paths/arguments with spaces, including Windows paths, in the template.
Use --command-json for an unambiguous JSON argv array on any platform. Commands
must return {"results": [{"path": ..., "startLine": ..., "endLine": ..., "text": ...}]}.

Budget policy: concatenate text in rank order, truncating the final result to the
remaining characters (4 * budget). No headers/separators are charged. Tokens are
ceil(total chars / 4). Character precision counts returned characters whose
original line lies in the union of expected intervals, including newline chars.
Duplicates are charged and counted each time; no deduplication/packing/reordering.
A hit requires any inclusive overlap, NOT full answer coverage. Recall@10 is
macro-averaged over positive questions; micro range recall is also reported.
Budget precision and coverage means also weight each positive question equally.

Absent questions require expected=[] and absentIdentifier (or a single-token
question). Success means no top-five text has that exact, case-sensitive token,
using Unicode word characters plus '$' as token boundaries. Empty retrieval can
pass this weak check; it does not demonstrate justified abstention or API absence.
Query errors count as misses, never successful absence. Latency includes process
startup and backend freshness validation; percentiles use nearest-rank selection.

Example:
  python eval_retrieval.py questions.jsonl --engine context7-backend \
    --database /external/index.sqlite --json-output result.json --markdown-output result.md
  python eval_retrieval.py questions.jsonl --engine command \
    --command 'my-engine --query {query} --limit {limit}' \
    --json-output result.json --markdown-output result.md
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import posixpath
import re
import shlex
import sqlite3
import subprocess
import sys
import time
from typing import Protocol

KINDS = frozenset({"exact-symbol", "concept", "paraphrase", "config", "docs-howto", "cross-file", "absent"})


def normalize_path(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/"))


def positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True)
class Result:
    path: str
    startLine: int
    endLine: int
    text: str


class Adapter(Protocol):
    def search(self, query: str, limit: int) -> list[Result]: ...


def load_questions(path: Path) -> list[dict]:
    questions: list[dict] = []
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("question must be an object")
                for key in ("id", "corpus", "question"):
                    if not isinstance(item.get(key), str) or not item[key].strip():
                        raise ValueError(f"{key} must be a nonempty string")
                if item["id"] in ids:
                    raise ValueError(f"duplicate id {item['id']}")
                if item.get("kind") not in KINDS:
                    raise ValueError("invalid question kind")
                expected = item.get("expected")
                if not isinstance(expected, list):
                    raise ValueError("expected must be a list")
                if (item["kind"] == "absent") != (not expected):
                    raise ValueError("only absent questions may have expected=[]")
                for target in expected:
                    if not isinstance(target, dict) or not isinstance(target.get("path"), str) or not target["path"]:
                        raise ValueError("expected range needs a path")
                    if not positive_integer(target.get("start")) or not positive_integer(target.get("end")) or target["end"] < target["start"]:
                        raise ValueError("expected ranges must be positive, inclusive and ordered")
                    target["path"] = normalize_path(target["path"])
                if not expected:
                    identifier = item.get("absentIdentifier", item["question"].strip())
                    if not isinstance(identifier, str) or not re.fullmatch(r"[\w$]+", identifier):
                        raise ValueError("absent question needs a single-token absentIdentifier")
                    item["absentIdentifier"] = identifier
                ids.add(item["id"])
                questions.append(item)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}: line {number}: {exc}") from exc
    if not questions:
        raise ValueError(f"{path}: no questions")
    return questions


def parse_results(payload: object) -> list[Result]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("engine output must be an object with a results array")
    results = []
    for index, row in enumerate(payload["results"], 1):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not row["path"]:
            raise ValueError(f"result {index}: missing path")
        if not positive_integer(row.get("startLine")) or not positive_integer(row.get("endLine")) or row["endLine"] < row["startLine"]:
            raise ValueError(f"result {index}: invalid line range")
        if not isinstance(row.get("text"), str):
            raise ValueError(f"result {index}: missing text")
        lines = row["text"].count("\n") + bool(row["text"] and not row["text"].endswith("\n"))
        if lines > row["endLine"] - row["startLine"] + 1:
            raise ValueError(f"result {index}: text exceeds cited line range")
        results.append(Result(normalize_path(row["path"]), row["startLine"], row["endLine"], row["text"]))
    return results


def run_json(argv: list[str], timeout: float) -> object:
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    if proc.returncode:
        raise ValueError(f"engine exited {proc.returncode}: {proc.stderr.strip()[:2000]}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise ValueError("engine stdout is not valid JSON") from exc


class CommandAdapter:
    def __init__(self, argv: list[str], timeout: float = 120):
        if not argv or any(not isinstance(arg, str) for arg in argv):
            raise ValueError("command must be a nonempty array of strings")
        if not any("{query}" in arg for arg in argv) or not any("{limit}" in arg for arg in argv):
            raise ValueError("command must include {query} and {limit}")
        self.argv, self.timeout = argv, timeout

    def search(self, query: str, limit: int) -> list[Result]:
        argv = [arg.replace("{limit}", str(limit)).replace("{query}", query) for arg in self.argv]
        return parse_results(run_json(argv, self.timeout))[:limit]


class Context7BackendAdapter:
    def __init__(self, database: Path, backend: Path, mode: str = "lexical", rerank: str | None = None,
                 corpus_root: Path | None = None, timeout: float = 120):
        self.argv = [sys.executable, str(backend.resolve()), "query", "--database", str(database.resolve()), "--mode", mode]
        if rerank:
            self.argv += ["--rerank", rerank]
        self.timeout = timeout
        # Read provenance roots once. Backend query still performs all freshness checks.
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as con:
            meta = dict(con.execute("SELECT key,value FROM meta"))
        root = Path(meta["root"])
        corpus_root = (corpus_root or root).resolve()
        self.prefixes = {"code": root.relative_to(corpus_root).as_posix(),
                         "repo-docs": root.relative_to(corpus_root).as_posix()}
        if meta.get("docs_root"):
            # For external docs, use their own namespace rather than guessing a repository path.
            docs = Path(meta["docs_root"])
            self.prefixes["docs"] = docs.relative_to(corpus_root).as_posix() if docs.is_relative_to(corpus_root) else "@docs"

    def search(self, query: str, limit: int) -> list[Result]:
        payload = run_json(self.argv + ["--query=" + query, "--limit", str(limit)], self.timeout)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ValueError("backend output must contain results array")
        rows = []
        for row in payload["results"]:
            source = row["source"]
            prefix = self.prefixes[source["kind"]]
            rows.append({"path": posixpath.join(prefix, source["path"]), "startLine": source["startLine"],
                         "endLine": source["endLine"], "text": row["text"]})
        return parse_results({"results": rows})[:limit]


def overlaps(result: Result, target: dict) -> bool:
    return (normalize_path(result.path) == normalize_path(target["path"])
            and result.startLine <= target["end"] and result.endLine >= target["start"])


def budget_context(results: list[Result], expected: list[dict], budget: int) -> dict:
    remaining = budget * 4
    returned = relevant = count = 0
    covered: set[int] = set()
    for result in results:
        text = result.text[:remaining]
        if not text:
            continue
        count += 1
        returned += len(text)
        remaining -= len(text)
        # Keep newlines attached to their original source line, including CRLF.
        parts = text.split("\n")
        for offset, part in enumerate(parts):
            size = len(part) + (offset < len(parts) - 1)
            if not size:
                continue
            line = result.startLine + offset
            targets = {i for i, target in enumerate(expected)
                       if normalize_path(result.path) == normalize_path(target["path"]) and target["start"] <= line <= target["end"]}
            if targets:
                relevant += size
                covered.update(targets)
        if not remaining:
            break
    return {"hit": bool(covered), "range_recall": len(covered) / len(expected) if expected else None,
            "character_precision": relevant / returned if returned else 0.0,
            "returned_chars": returned, "relevant_chars": relevant, "estimated_tokens": math.ceil(returned / 4),
            "results_used": count}


def score_question(question: dict, results: list[Result], budgets: list[int], error: str | None = None) -> dict:
    if not question["expected"]:
        identifier = question["absentIdentifier"]
        pattern = re.compile(r"(?<![\w$])" + re.escape(identifier) + r"(?![\w$])")
        ranks = [i for i, result in enumerate(results[:5], 1) if pattern.search(result.text)]
        return {"absent_success": not error and not ranks, "identifier_match_ranks": ranks}
    expected = question["expected"]
    ranks = [i for i, result in enumerate(results[:10], 1) if any(overlaps(result, target) for target in expected)]
    matched = sum(any(overlaps(result, target) for result in results[:10]) for target in expected)
    return {**{f"hit@{k}": bool(ranks and ranks[0] <= k) for k in (1, 3, 5, 10)},
            "MRR@10": 1 / ranks[0] if ranks else 0.0, "recall@10": matched / len(expected),
            "matched_ranges@10": matched, "expected_ranges": len(expected),
            "budgets": {str(budget): budget_context(results[:10], expected, budget) for budget in budgets}}


def percentile(values: list[float], probability: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * probability) - 1)] if values else None


def summarize(records: list[dict], budgets: list[int]) -> dict:
    positive = [row for row in records if row["question"]["expected"]]
    absent = [row for row in records if not row["question"]["expected"]]
    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None
    scores = [row["metrics"] for row in positive]
    total_ranges = sum(score["expected_ranges"] for score in scores)
    return {"questions": len(records), "positive_questions": len(positive), "absent_questions": len(absent),
            "errors": sum(bool(row.get("error")) for row in records),
            **{key: mean([score[key] for score in scores]) for key in ("hit@1", "hit@3", "hit@5", "hit@10", "MRR@10", "recall@10")},
            "micro_range_recall@10": sum(score["matched_ranges@10"] for score in scores) / total_ranges if total_ranges else None,
            "absent_success": mean([row["metrics"]["absent_success"] for row in absent]),
            "budgets": {str(budget): {"hit": mean([score["budgets"][str(budget)]["hit"] for score in scores]),
                                      "range_recall": mean([score["budgets"][str(budget)]["range_recall"] for score in scores]),
                                      "character_precision": mean([score["budgets"][str(budget)]["character_precision"] for score in scores])}
                        for budget in budgets},
            "latency_seconds": {"p50": percentile([row["latency_seconds"] for row in records], .5),
                                "p95": percentile([row["latency_seconds"] for row in records], .95)}}


def evaluate(questions: list[dict], adapter: Adapter, budgets: list[int]) -> dict:
    records = []
    for question in questions:
        start = time.perf_counter()
        error = None
        try:
            results = adapter.search(question["question"], 10)
        except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
            results, error = [], str(exc)
        latency = time.perf_counter() - start
        records.append({"question": question, "results": [asdict(result) for result in results], "error": error,
                        "latency_seconds": latency, "metrics": score_question(question, results, budgets, error)})
        print(f"{question['id']}: {latency:.3f}s" + (f" ERROR {error}" if error else ""), file=sys.stderr, flush=True)
    return {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
            "budget_policy": "ranked character prefix; ceil(chars/4); text only; no deduplication",
            "overall": summarize(records, budgets),
            "by_kind": {kind: summarize([row for row in records if row["question"]["kind"] == kind], budgets)
                        for kind in sorted({question["kind"] for question in questions})},
            "by_corpus": {corpus: summarize([row for row in records if row["question"]["corpus"] == corpus], budgets)
                          for corpus in sorted({question["corpus"] for question in questions})},
            "questions": records}


def markdown_summary(report: dict) -> str:
    def fmt(value: float | None) -> str:
        return "-" if value is None else f"{value:.3f}"
    lines = ["# Retrieval evaluation", "", "Scores are fractions. Positive questions exclude absent APIs. Errors count as misses. Latency includes backend startup and freshness checks.", "",
             "| Group | Positive | Absent | Errors | H@1 | H@3 | H@5 | H@10 | MRR@10 | Recall@10 | Absent success | p50 s | p95 s |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    groups = [("overall", report["overall"])] + [(f"kind:{key}", value) for key, value in report["by_kind"].items()] + [(f"corpus:{key}", value) for key, value in report["by_corpus"].items()]
    for name, score in groups:
        cells = [name, str(score["positive_questions"]), str(score["absent_questions"]), str(score["errors"])]
        cells += [fmt(score[key]) for key in ("hit@1", "hit@3", "hit@5", "hit@10", "MRR@10", "recall@10", "absent_success")]
        cells += [fmt(score["latency_seconds"][key]) for key in ("p50", "p95")]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "Budget uses a ranked character prefix, including a partial last result, with 4 chars/token. Character precision counts characters on expected source lines; overlap is not full answer correctness.", "",
              "| Group | Budget | Any expected hit | Range recall | Character precision |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, score in groups:
        for budget, value in score["budgets"].items():
            lines.append(f"| {name} | {budget} | {fmt(value['hit'])} | {fmt(value['range_recall'])} | {fmt(value['character_precision'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("questions", type=Path)
    parser.add_argument("--engine", required=True, choices=("context7-backend", "command"))
    parser.add_argument("--database", type=Path)
    parser.add_argument("--backend", type=Path, default=Path(__file__).with_name("context7_backend.py"))
    parser.add_argument("--corpus-root", type=Path, help="Original corpus root when indexing a subtree; normalizes citations")
    parser.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    parser.add_argument("--rerank", choices=("lexical-symbol", "cross-encoder"))
    command = parser.add_mutually_exclusive_group()
    command.add_argument("--command", help="shlex-split argv template; never interpreted by a shell")
    command.add_argument("--command-json", help="JSON argv array template (recommended on Windows)")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--budgets", type=int, nargs="+", default=[2000, 5000])
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if any(budget <= 0 for budget in args.budgets) or not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("budgets and timeout must be positive and finite")
        questions = load_questions(args.questions)
        adapter: Adapter
        if args.engine == "command":
            if not args.command and not args.command_json:
                raise ValueError("command engine requires --command or --command-json")
            command_argv = json.loads(args.command_json) if args.command_json else shlex.split(args.command)
            if not isinstance(command_argv, list):
                raise ValueError("--command-json must be a JSON argv array")
            adapter = CommandAdapter(command_argv, args.timeout)
        else:
            if args.database is None:
                raise ValueError("context7-backend requires --database")
            if len({question['corpus'] for question in questions}) != 1:
                raise ValueError("one backend database can evaluate only one corpus at a time")
            adapter = Context7BackendAdapter(args.database, args.backend, args.mode, args.rerank, args.corpus_root, args.timeout)
        report = evaluate(questions, adapter, list(dict.fromkeys(args.budgets)))
        report["configuration"] = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
        for path in (args.json_output, args.markdown_output):
            path.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        args.markdown_output.write_text(markdown_summary(report), encoding="utf-8")
        return 1 if report["overall"]["errors"] else 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
