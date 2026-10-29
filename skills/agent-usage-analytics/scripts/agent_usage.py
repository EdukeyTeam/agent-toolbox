#!/usr/bin/env python3
"""Offline agent usage reports. Run --help for the supported workflows."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

from usage_common import context_observation, dataset, digest, number, safe_name, timestamp
from usage_accounting import build_report, load_rates, merge
from usage_store import Ledger, normalize_import

AGENTS = ("codex", "claude", "copilot", "grok", "agy")


def guarded_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.name.lower() in {"auth.json", "credentials.json", ".credentials.json", "hosts.yml", "secrets.env", "oauth_creds.json"} or path.name.startswith(".env"):
        raise ValueError("Credential/configuration files are not usage sources")
    return path


def discover(home: Path) -> list[dict]:
    roots = {"codex": Path(os.environ.get("CODEX_HOME", home / ".codex")) if home == Path.home() else home / ".codex",
             "claude": home / ".claude", "copilot": home / ".copilot", "grok": home / ".grok"}
    return [{"agent": agent, "path": str(path), "exists": path.is_dir(), "contract": "observed-local"}
            for agent, path in roots.items()]


def native_snapshot(raw: dict, agent: str, account: str = "local", observed_at: str | None = None) -> dict:
    """Allowlist numeric fields from Claude statusline or Codex app-server exports."""
    if not isinstance(raw, dict):
        raise ValueError("Native snapshot must be an object")
    data = dataset()
    when = timestamp(observed_at) or timestamp(datetime.now(timezone.utc).isoformat())
    source_id = digest("native_snapshot", agent, account)
    data["sources"].append({"id": source_id, "agent": agent, "origin": "native_export", "contract": "documented",
                             "files_seen": 1, "files_parsed": 1, "rows_seen": 1, "malformed_rows": 0})
    def quota(bucket, value, minutes=None):
        used = number(value.get("used_percentage", value.get("usedPercent", value.get("used_percent"))))
        if used is None and number(value.get("remaining_fraction")) is not None:
            used = 100 * (1 - value["remaining_fraction"])
        duration = number(value.get("windowDurationMins", value.get("window_minutes", minutes)))
        reset = timestamp(value.get("resets_at", value.get("resetsAt", value.get("reset_time"))))
        if used is not None and used <= 100:
            data["quotas"].append({"id": digest(agent, account, bucket, when, used, reset), "agent": agent,
                "account": safe_name(account), "bucket": safe_name(bucket), "window_minutes": duration,
                "resets_at": reset, "used_percent": used, "observed_at": when, "source_id": source_id,
                "origin": "native_export", "device": "owning-agent"})
    # A syntactically valid export can still hold a non-object quota container; ignore it rather than crash.
    def mapping(value):
        return value if isinstance(value, dict) else {}
    if agent == "codex":
        limits = mapping(raw.get("rateLimitsByLimitId")) or {"codex": raw.get("rateLimits", raw)}
        for label, bucket in limits.items():
            if isinstance(bucket, dict):
                for key in ("primary", "secondary"):
                    if isinstance(bucket.get(key), dict):
                        quota(str(label) + ":" + key, bucket[key])
    else:
        for key, value in (mapping(raw.get("rate_limits")) or mapping(raw.get("quota"))).items():
            if isinstance(value, dict):
                quota(key, value, {"five_hour": 300, "seven_day": 10080}.get(key))
    cw = raw.get("context_window")
    sid = raw.get("session_id")
    if isinstance(cw, dict) and isinstance(sid, str):
        current = cw.get("current_usage")
        used = None
        if isinstance(current, dict):
            values = [number(current.get(key)) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
            if all(v is not None for v in values):
                used = sum(values)
        capacity = number(cw.get("context_window_size"))
        data["contexts"].append(context_observation(agent, safe_name(sid), when, {}, used, capacity,
            source_id=source_id, origin="native_export", provider_percent=number(cw.get("used_percentage")),
            retention_status="native snapshot; category breakdown unavailable"))
    return data


def capture_codex(timeout: float = 15) -> dict:
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("Codex CLI is unavailable; import an owning-agent quota export instead")
    messages: queue.Queue = queue.Queue()
    process = subprocess.Popen([executable, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    def reader():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    def send(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()
    def receive(request_id):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if response is None:
                break
            if response.get("id") == request_id:
                if "error" in response:
                    raise ValueError("Codex usage read was unavailable for this authenticated CLI/version")
                return response.get("result", {})
        raise ValueError("Codex usage read timed out; no model turn was requested")
    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "agent-usage-analytics", "version": "1.0.0"}}})
        receive(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read"})
        return receive(2)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()


def demo_data() -> dict:
    data = dataset()
    base = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    models = [("codex", "gpt-6.1-sol"), ("claude", "claude-opus-5-5"), ("copilot", "claude-sonnet-5-5")]
    for day in range(14):
        for index, (agent, model) in enumerate(models):
            sid = f"sample-{agent}-{day // 4}"
            when = timestamp((base + timedelta(days=day, hours=index)).isoformat())
            inp = 24000 + day * 1800 + index * 9000
            row = {"id": digest(agent, day), "agent": agent, "session_id": sid, "model": model,
                   "timestamp": when, "input_tokens": inp, "cache_read_tokens": inp // 2,
                   "cache_write_tokens": 1000, "cache_write_5m_tokens": 1000, "cache_write_1h_tokens": 0,
                   "output_tokens": 1500 + day * 90, "reasoning_tokens": 300, "request_count": 1,
                   "account": "sample", "device": "synthetic", "origin": "synthetic", "quality": "reported",
                   "source_id": "sample", "speed": "standard", "inference_geo": "global", "unit": "request"}
            data["usage"].append(row)
            data["sessions"].append({"id": digest("session", sid), "agent": agent, "session_id": sid,
                                     "start": when, "end": when, "device": "synthetic", "origin": "synthetic"})
            data["tools"].append({"id": digest("tool", agent, day), "agent": agent, "session_id": sid,
                                  "timestamp": when, "name": "read_file" if day % 3 else "search_docs", "kind": "tool",
                                  "argument_chars": 140, "result_chars": 6000 + day * 1100})
    data["contexts"].append(context_observation("codex", "sample-codex-3", "2026-10-14T11:00:00Z",
        {"instructions": 16000, "skill_catalog": 7800, "loaded_skills": 12000, "tool_results": 68000,
         "user_messages": 10000, "assistant_messages": 28000}, 68000, 200000, 2, model="gpt-6.1-sol"))
    data["sources"].append({"id": "sample", "agent": "multiple", "origin": "synthetic", "device": "synthetic",
                             "contract": "synthetic", "files_seen": 3, "files_parsed": 3, "rows_seen": 42, "malformed_rows": 0})
    data["quotas"].append({"id": "sample-quota", "agent": "codex", "account": "sample", "bucket": "weekly",
        "window_minutes": 10080, "resets_at": "2026-10-20T09:00:00Z", "used_percent": 38,
        "observed_at": "2026-10-14T11:00:00Z", "origin": "synthetic"})
    return merge(data)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("discover", "usage", "collect", "session", "import", "snapshot", "capture-codex", "demo"):
        p = sub.add_parser(command)
        p.add_argument("--home", type=Path, default=Path.home(), help="Explicit user data root; Windows paths work natively or through a WSL mount")
        p.add_argument("--source", action="append", default=[], metavar="AGENT=PATH")
        p.add_argument("--device", default="local")
        p.add_argument("--account", default="local", help="User-chosen alias, not an account ID")
        p.add_argument("--store", type=Path, help="Optional analytics ledger; never a provider database")
        p.add_argument("--out", type=Path, help="Report directory for DOCX, JSON, Markdown and offline HTML; default: user Documents/Agent Analysis/<unique run>")
        p.add_argument("--input", type=Path)
        p.add_argument("--agent", choices=AGENTS, default="claude")
        p.add_argument("--session", dest="session_id")
        p.add_argument("--current", action="store_true")
        p.add_argument("--since", help="Inclusive date/time in --timezone")
        p.add_argument("--until", help="Exclusive date/time in --timezone")
        p.add_argument("--timezone", default="UTC")
        p.add_argument("--compare-since")
        p.add_argument("--compare-until")
        p.add_argument("--rates", type=Path)
        p.add_argument("--task-map", type=Path, help="JSON session ID -> explicit task category")
        p.add_argument("--attribution-map", type=Path, help="JSON agent:session -> confirmed provider/model route")
        p.add_argument("--share", action="store_true", help="Pseudonymize identifiers in reports")
        p.add_argument("--complete-coverage", action="store_true", help="Declare all relevant device/cloud usage captured for experimental quota calibration")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "discover":
            print(json.dumps(discover(args.home), indent=2))
            return 0
        if args.current:
            args.session_id = args.session_id or os.environ.get("CODEX_THREAD_ID")
            if not args.session_id:
                raise ValueError("Current session identity is unavailable; provide --session and a source")
        if args.command == "session" and not args.session_id:
            raise ValueError("Session inspection requires --session ID or --current")
        if args.input and args.source:
            raise ValueError("Choose a normalized --input export or native --source paths, not both")
        if args.command == "demo":
            data = demo_data()
        elif args.command == "import" or (args.input and args.command in ("usage", "session", "collect")):
            if not args.input:
                raise ValueError("Import requires --input normalized.json")
            data = normalize_import(json.loads(guarded_path(str(args.input)).read_text(encoding="utf-8-sig")))
        elif args.command in ("snapshot", "capture-codex"):
            if args.command == "snapshot" and not args.input:
                raise ValueError("Snapshot requires --input owning-agent-export.json")
            raw = capture_codex() if args.command == "capture-codex" else json.loads(guarded_path(str(args.input)).read_text(encoding="utf-8-sig"))
            data = native_snapshot(raw, "codex" if args.command == "capture-codex" else args.agent, args.account)
        else:
            from usage_collectors import collect
            sources = []
            for item in args.source:
                agent, separator, path = item.partition("=")
                if not separator or agent not in AGENTS:
                    raise ValueError("Source must be AGENT=PATH with a supported agent name")
                sources.append((agent, guarded_path(path)))
            if not sources and (not args.store or args.command == "collect"):
                sources = [(r["agent"], Path(r["path"])) for r in discover(args.home) if r["exists"]
                           and (not args.current or r["agent"] == "codex")]
            data = merge(*(collect(agent, path, args.device, args.account, args.session_id) for agent, path in sources))
        # Validate everything before the ledger is written, so a failed invocation never changes history.
        mapping = None
        if args.attribution_map:
            from usage_attribution import apply_attribution
            mapping = json.loads(guarded_path(str(args.attribution_map)).read_text(encoding="utf-8-sig"))
            apply_attribution(dataset(), mapping)
        task_map = json.loads(guarded_path(str(args.task_map)).read_text(encoding="utf-8-sig")) if args.task_map else None
        if task_map is not None and (not isinstance(task_map, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in task_map.items())):
            raise ValueError("Task map must map session IDs to string labels")
        if args.session_id:
            candidate = data
            if args.store and Path(args.store).exists():
                ledger = Ledger(args.store)
                try:
                    candidate = merge(ledger.read(), data)
                finally:
                    ledger.close()
            # A context observation alone is enough for the session-context report.
            if not any(r.get("session_id") == args.session_id
                       for r in (*candidate["sessions"], *candidate["usage"], *candidate.get("contexts", []))):
                raise ValueError("Requested session was not found in the selected sources/history")
        if args.store:
            ledger = Ledger(args.store)
            try:
                ledger.add(data)
                data = ledger.read()
            finally:
                ledger.close()
        if mapping is not None:
            data = apply_attribution(data, mapping)
            if args.store:
                ledger = Ledger(args.store)
                try:
                    ledger.add({"schema_version": 1, "usage": data["usage"], "contexts": data["contexts"]})
                finally:
                    ledger.close()
        report = build_report(data, load_rates(args.rates), since=args.since, until=args.until, tz_name=args.timezone,
                              session_id=args.session_id, compare_since=args.compare_since, compare_until=args.compare_until,
                              share=args.share, complete_coverage=args.complete_coverage, task_map=task_map)
        paths = {}
        if args.out or not args.store:
            from usage_render import write_reports
            from usage_output import new_report_directory
            paths = write_reports(report, args.out.expanduser() if args.out else new_report_directory())
        print(json.dumps({"summary": report["summary"], "artifacts": paths, "warnings": len(report["warnings"]),
                          "scope": report["scope"], "quota_observations": len(report["quotas"])}))
        return 0
    except (ValueError, OSError, json.JSONDecodeError, sqlite3.Error) as exc:
        # Never emit source contents, provider messages or raw JSON decoding excerpts.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else type(exc).__name__
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
