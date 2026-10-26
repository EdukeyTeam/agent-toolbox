"""Read-only, content-free adapters for explicitly selected agent data sources.

Only observed schemas are accepted. Logs are data: no logged command is executed.
Missing counters and uncertain attribution remain unavailable rather than zero.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

from usage_common import (classify_text, context_observation, copilot_preference, dataset, digest, jsonl,
                          number, safe_name, source_info, text_chars, timestamp, warn)

# Any is confined to untyped JSON / normalized interchange boundaries.
JSON = dict[str, Any]
TOKEN_FIELDS = ("input_tokens", "cache_read_tokens", "cache_write_tokens",
                "output_tokens", "reasoning_tokens")


def obj(value: object) -> JSON:
    return value if isinstance(value, dict) else {}


def pick(value: JSON, *keys: str) -> object:
    for key in keys:
        if key in value:
            return value[key]
    return None


def count(value: JSON, *keys: str) -> int | float | None:
    return number(pick(value, *keys))


def plus(*values: int | float | None) -> int | float | None:
    return sum(values) if all(v is not None for v in values) else None


def identifier(value: object, fallback: str) -> str:
    return safe_name(value, fallback)


def stamp(row: JSON) -> str | None:
    return timestamp(pick(row, "timestamp", "created_at", "updatedAt", "endedAt", "time"))


def usage_row(agent: str, sid: str, key: object, raw: JSON, source: JSON,
              device: str, account: str, at: str | None, model: object = None,
              mode: str = "reported", **extra: Any) -> JSON:
    fields = {k: number(raw.get(k)) for k in TOKEN_FIELDS}
    if fields["reasoning_tokens"] is not None and (fields["output_tokens"] is None or
            fields["reasoning_tokens"] > fields["output_tokens"]):
        fields["reasoning_tokens"] = None
    return {"id": digest("usage", agent, sid, key), "agent": agent,
            "session_id": sid, "model": safe_name(model), "reported_model": safe_name(model),
            "provider": None, "model_attribution": "reported", "timestamp": at,
            "source_id": source["id"], "origin": source.get("origin", "local"), "device": safe_name(device),
            "account": safe_name(account), **fields,
            "cache_write_5m_tokens": number(raw.get("cache_write_5m_tokens")),
            "cache_write_1h_tokens": number(raw.get("cache_write_1h_tokens")),
            "request_count": 1, "unit": "request", "quality": "reported" if any(
                fields[k] is not None for k in ("input_tokens", "output_tokens")) else "unavailable",
            "speed": None, "inference_geo": None, "service_tier": None,
            "cache_write_reported": raw.get("cache_write_tokens") is not None,
            "model_inferred": False, "accounting_mode": mode, **extra}


def coalesce(rows: list[JSON]) -> list[JSON]:
    """Repeated streaming/rotated sources carry maxima, never additional usage."""
    unique: dict[str, JSON] = {}
    for row in rows:
        prior = unique.get(row["id"])
        if prior is None:
            unique[row["id"]] = row
            continue
        for field in (*TOKEN_FIELDS, "cache_write_5m_tokens", "cache_write_1h_tokens",
                      "web_search_requests", "request_count", "argument_chars", "result_chars"):
            value = number(row.get(field))
            if value is not None:
                prior[field] = max(value, number(prior.get(field)) or 0)
        if prior.get("model") == "unknown" and row.get("model") != "unknown":
            prior["model"] = row["model"]
            prior["model_inferred"] = row.get("model_inferred", False)
        if prior.get("name") == "unknown" and row.get("name") != "unknown":
            for field in ("name", "detection", "timestamp"):
                prior[field] = row.get(field)
    return list(unique.values())


class Inventory:
    """Only lengths/categories survive each row; replacement histories replace all."""
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, int]] = {}
        self.known = True
        self.base_hash: str | None = None
        self.base_text: str | None = None
        self.developer_hashes: set[str] = set()

    def reset(self, known: bool = True) -> None:
        self.entries.clear()
        self.developer_hashes.clear()
        self.base_hash = None
        self.base_text = None
        self.known = known

    def add(self, key: str, value: object, role: str = "user", category: str | None = None) -> None:
        if category:
            self.entries[key] = {category: text_chars(value)}
            return
        strings: list[str] = []
        def visit(part: object) -> None:
            if isinstance(part, str):
                strings.append(part)
            elif isinstance(part, list):
                for sub in part:
                    visit(sub)
            elif isinstance(part, dict) and part.get("type") not in (
                    "image", "input_image", "image_url", "audio", "input_audio"):
                for field in ("text", "content", "summary"):
                    if field in part:
                        visit(part[field])
        visit(value)
        if role == "developer" and self.base_text and self.base_text in "".join(strings):
            self.entries.pop("base", None)
        totals: dict[str, int] = defaultdict(int)
        for text in strings:
            hashed = digest(text)
            if role == "base":
                self.base_hash = hashed
                self.base_text = text
                if hashed in self.developer_hashes:
                    continue
            elif role == "developer":
                self.developer_hashes.add(hashed)
                if hashed == self.base_hash:
                    self.entries.pop("base", None)
            for name, n in classify_text(text, "system" if role == "base" else role).items():
                totals[name] += n
        self.entries[key] = dict(totals)

    def chars(self) -> dict[str, int]:
        totals: dict[str, int] = defaultdict(int)
        for entry in self.entries.values():
            for name, n in entry.items():
                totals[name] += n
        return dict(totals)


class Observations:
    def __init__(self, data: JSON, source: JSON, agent: str, sid: str, device: str) -> None:
        self.data, self.source, self.agent, self.sid = data, source, agent, sid
        self.device = safe_name(device)
        self.inv = Inventory()
        self.compactions = 0
        self.context: JSON | None = None
        self.start: str | None = None
        self.end: str | None = None
        self.parent: str | None = None
        self.calls: dict[str, JSON] = {}
        self.pending_results: dict[str, int] = {}

    def tick(self, at: str | None) -> None:
        if at:
            self.start = min(self.start, at) if self.start else at
            self.end = max(self.end, at) if self.end else at

    def tool(self, call_id: object, name: object, args: object, at: str | None,
             inferred: bool = False, kind: str = "tool") -> None:
        key = str(call_id)
        row = {"id": digest("tool", self.agent, self.sid, key, kind), "agent": self.agent,
               "session_id": self.sid, "timestamp": at, "source_id": self.source["id"],
               "device": self.device, "origin": self.source.get("origin", "local"), "name": safe_name(name),
               "kind": kind, "argument_chars": len(args) if isinstance(args, str) else len(
                   json.dumps(args, ensure_ascii=False)) if args is not None else None,
               "result_chars": self.pending_results.pop(key, None),
               "detection": "inferred_file_read" if inferred else "explicit"}
        self.calls[key + (":skill" if kind == "skill" else "")] = row
        # Observe a recorded SKILL.md read without interpreting shell syntax or running it.
        if kind == "tool":
            text = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            if re.search(r"(?i)(?:read|view|cat|exec|command|shell)", str(name)):
                for match in re.finditer(r"(?:skills[/\\]+|[./\\]+)([\w.-]+)[/\\]+SKILL\.md\b", text):
                    self.tool(key + ":" + match.group(1), match.group(1), None, at, True, "skill")

    def result(self, key: object, value: object) -> None:
        if key is None:
            warn(self.data, "missing_tool_call_identity", self.source["id"])
            return
        size = text_chars(value)
        row = self.calls.get(str(key))
        if row:
            row["result_chars"] = size
            loads = [value for call, value in self.calls.items()
                     if call.startswith(str(key) + ":") and value.get("kind") == "skill"]
            if len(loads) == 1:
                loads[0]["result_chars"] = size
                loads[0]["quality"] = "estimated_load_output_proxy"
        else:
            self.pending_results[str(key)] = size

    def compact(self, at: str | None, replacement: object = None) -> None:
        self.compactions += 1
        self.inv.reset(isinstance(replacement, list))
        if isinstance(replacement, list):
            for i, item in enumerate(replacement):
                self.item(obj(item), at, f"replacement:{self.compactions}:{i}", observe_tools=False)
        self.context = None

    def item(self, item: JSON, at: str | None, key: str, observe_tools: bool = True) -> None:
        kind = item.get("type")
        if kind in ("function_call", "custom_tool_call", "tool_use"):
            args = pick(item, "arguments", "input")
            self.inv.add(key, args if isinstance(args, str) else json.dumps(args), category="tool_arguments")
            if observe_tools:
                self.tool(pick(item, "call_id", "id") or key, item.get("name"), args, at)
                if str(item.get("name", "")).lower() in ("skill", "load_skill", "invoke_skill"):
                    parsed = obj(args)
                    if isinstance(args, str):
                        try:
                            parsed = obj(json.loads(args))
                        except ValueError:
                            parsed = {"skill": args}
                    self.tool(str(pick(item, "call_id", "id") or key) + ":invocation",
                              pick(parsed, "skill", "name"), None, at, kind="skill")
        elif kind in ("function_call_output", "custom_tool_call_output", "tool_result"):
            output = pick(item, "output", "content")
            self.inv.add(key, output, category="tool_results")
            if observe_tools:
                self.result(pick(item, "call_id", "tool_use_id"), output)
        else:
            self.inv.add(key, pick(item, "content", "text", "summary"), str(item.get("role", "user")))

    def anchor(self, at: str | None, used: int | float | None, window: object,
               model: str = "unknown", **extra: Any) -> None:
        self.context = context_observation(self.agent, self.sid, at, self.inv.chars(), used,
            number(window), self.compactions, model, source_id=self.source["id"],
            device=self.device, origin=self.source.get("origin", "local"), retention_status=(
                "recorded-visible-history" if self.inv.known else "unknown-after-compaction"), **extra)

    def finish(self, emit_context: bool = True) -> None:
        if self.context is None:
            self.anchor(self.end, None, None)
        if emit_context:
            self.context["parent_session_id"] = self.parent
            self.data["contexts"].append(self.context)
        # A rotation may separate a result from its call. Content-free stubs
        # join by the same stable invocation ID during collection coalescence.
        for key, size in list(self.pending_results.items()):
            self.tool(key, None, None, None)
            self.calls[key]["detection"] = "unmatched_result"
        self.data["tools"].extend(self.calls.values())
        self.data["sessions"].append({"id": digest("session", self.agent, self.sid),
            "agent": self.agent, "session_id": self.sid, "parent_session_id": self.parent,
            "device": self.device, "origin": self.source.get("origin", "local"), "start": self.start,
            "end": self.end, "compactions": self.compactions})


def quota(data: JSON, source: JSON, agent: str, sid: str, raw: object,
          at: str | None, device: str, account: str) -> None:
    limits = obj(raw)
    # Provider percentages are observations even on unchanged token snapshots.
    for bucket in ("primary", "secondary"):
        entry = obj(limits.get(bucket))
        if number(entry.get("used_percent")) is None:
            continue
        label = safe_name(limits.get("limit_id"), "codex" if agent == "codex" else "default") + ":" + bucket
        data["quotas"].append({"id": digest("quota", agent, account, label, at,
                                             entry.get("resets_at"), entry.get("used_percent")),
            "agent": agent, "account": safe_name(account), "bucket": label,
            "window_minutes": count(entry, "window_minutes", "window_duration_mins"),
            "resets_at": timestamp(entry.get("resets_at")), "used_percent": count(entry, "used_percent"),
            "observed_at": at, "source_id": source["id"], "device": safe_name(device), "origin": "local"})


def codex_counts(raw: JSON) -> JSON:
    return {"input_tokens": count(raw, "input_tokens"),
            "cache_read_tokens": count(raw, "cached_input_tokens", "cache_read_tokens", "cache_read_input_tokens"),
            "cache_write_tokens": count(raw, "cache_write_input_tokens", "cache_write_tokens", "cache_creation_input_tokens", "cache_creation_tokens"),
            "output_tokens": count(raw, "output_tokens"),
            "reasoning_tokens": count(raw, "reasoning_output_tokens", "reasoning_tokens")}


def counters_equal(a: JSON, b: JSON) -> bool:
    return all(a.get(k) == b.get(k) for k in TOKEN_FIELDS)


def delta_counts(total: JSON, previous: JSON) -> JSON:
    return {k: total[k] - previous[k] if total.get(k) is not None and previous.get(k) is not None
            else None for k in TOKEN_FIELDS}


def _codex(path: Path, data: JSON, source: JSON, device: str, account: str,
           selected: str | None) -> None:
    # First pass retains metadata/numbers only, so replay ownership and forward model
    # joins are known without retaining an entire transcript in memory.
    meta: JSON = {}
    boundary = 0
    models: dict[str, str] = {}
    dimensions: dict[str, JSON] = {}
    first_native: tuple[int, JSON] | None = None
    for line, row in jsonl(path, data, source):
        p = obj(row.get("payload"))
        if row.get("type") == "session_meta":
            meta, boundary = p, line
            first_native = None
            models.clear()
            dimensions.clear()
        elif row.get("type") == "turn_context" and p.get("turn_id"):
            models[str(p["turn_id"])] = safe_name(p.get("model"))
            dimensions[str(p["turn_id"])] = {k: safe_name(p[k]) if p.get(k) else None
                for k in ("speed", "service_tier", "inference_geo")}
        elif row.get("type") == "token_usage_record" or p.get("type") == "token_usage_record":
            if first_native is None:
                first_native = line, p
    sid = identifier(pick(meta, "id", "session_id", "thread_id"), path.stem)
    parent = pick(meta, "forked_from_id", "parent_thread_id", "parent_session_id")
    fork = obj(obj(meta.get("source")).get("subagent"))
    parent = parent or pick(fork, "parent_thread_id", "parent_session_id")
    parent = parent or pick(obj(fork.get("thread_spawn")), "parent_thread_id", "parent_session_id")
    if selected and sid != selected and parent != selected:
        return
    source["session_id"] = sid
    # Re-reading a stream is intentional, but parsing coverage counts source rows once.
    source["rows_seen"] = source["malformed_rows"] = 0
    data["warnings"] = [w for w in data["warnings"] if w["source_id"] != source["id"]]
    obs = Observations(data, source, "codex", sid, device)
    obs.parent = identifier(parent, "unknown") if parent else None
    parent_snapshots: set[str] = set()
    if obs.parent and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", obs.parent):
        # Legacy forks can replay snapshots AFTER their own metadata. Compare
        # leading payloads with the parent when that rollout is available.
        tree = next((p for p in path.parents if p.name in ("sessions", "archived_sessions")), path.parent)
        trees = [tree]
        if tree.name in ("sessions", "archived_sessions"):
            trees = [p for p in (tree.parent / "sessions", tree.parent / "archived_sessions") if p.is_dir()]
        candidates = (candidate for root in trees for candidate in root.glob("**/*" + obs.parent + "*.jsonl"))
        for candidate in candidates:
            if candidate == path or candidate.is_symlink():
                continue
            parent_source = source_info(candidate, "codex", device)
            scratch = dataset()
            for _, parent_row in jsonl(candidate, scratch, parent_source):
                payload = obj(parent_row.get("payload"))
                if parent_row.get("type") == "event_msg" and payload.get("type") == "token_count":
                    counters = obj(obj(payload.get("info")).get("total_token_usage"))
                    if counters:
                        parent_snapshots.add(digest(codex_counts(counters)))
    replay_pending = bool(meta.get("forked_from_id") or boundary > 1 or
                          (obs.parent and not fork.get("thread_spawn")))
    inherited = False
    last_total: JSON | None = None
    context_total: JSON | None = None
    preceding_model = "unknown"
    window: int | float | None = None
    current_turn: str | None = None
    legacy: list[JSON] = []
    native_counts: dict[str, JSON] = {}
    for line, row in jsonl(path, data, source):
        p = obj(row.get("payload"))
        kind = row.get("type")
        at = stamp(row)
        if line < boundary:
            if kind == "event_msg" and p.get("type") == "token_count":
                candidate = obj(obj(p.get("info")).get("total_token_usage"))
                if candidate:
                    last_total = codex_counts(candidate)
                    context_total = last_total
                    inherited = True
                    replay_pending = False
            continue
        obs.tick(at)
        if kind == "session_meta":
            obs.inv.add("base", pick(p, "base_instructions", "instructions"), "base")
        elif kind == "turn_context":
            if preceding_model != "unknown" and safe_name(p.get("model")) != preceding_model:
                window = None
            preceding_model = safe_name(p.get("model"))
            current_turn = str(p["turn_id"]) if p.get("turn_id") else None
            # Context capacity is usually emitted by token_count, sometimes by turn context.
            if number(p.get("model_context_window")) is not None:
                window = number(p["model_context_window"])
        elif kind == "compacted" or p.get("type") in ("context_compacted", "compaction"):
            obs.compact(at, p.get("replacement_history"))
        elif kind == "response_item" and p.get("type") != "token_usage_record":
            obs.item(p, at, f"item:{line}")
        elif kind == "token_usage_record" or p.get("type") == "token_usage_record":
            raw = codex_counts(obj(p.get("usage")))
            response = pick(p, "response_id", "responseId")
            thread = identifier(pick(p, "thread_id", "threadId"), sid)
            if thread != sid:
                warn(data, "inherited_native_record_excluded", source["id"], line)
                continue
            if not response:
                warn(data, "missing_request_identity", source["id"], line)
                continue
            turn = str(p.get("turn_id")) if p.get("turn_id") else current_turn
            model = models.get(turn or "", preceding_model)
            inferred = not (p.get("turn_id") and str(p["turn_id"]) in models)
            dims = dimensions.get(turn or "", {})
            record = usage_row("codex", sid, (thread, response), raw, source, device, account,
                at, model, "codex_native_per_response", parent_session_id=obs.parent,
                native_total_input_tokens=count(obj(pick(p, "thread_token_usage", "thread_total", "thread_total_usage", "thread_total_token_usage", "total_token_usage")), "input_tokens"),
                native_total_output_tokens=count(obj(pick(p, "thread_token_usage", "thread_total", "thread_total_usage", "thread_total_token_usage", "total_token_usage")), "output_tokens"),
                model_inferred=inferred, **{k: safe_name(p[k]) if p.get(k) else dims.get(k)
                    for k in ("speed", "service_tier", "inference_geo")})
            provider = pick(p, "model_provider", "provider") or pick(meta, "model_provider", "provider")
            if provider:
                record.update(provider=safe_name(provider), model_attribution="recorded")
            data["usage"].append(record)
            previous = native_counts.setdefault(str(response), raw.copy())
            for k in TOKEN_FIELDS:
                if raw[k] is not None:
                    previous[k] = max(raw[k], previous.get(k) or 0)
            obs.anchor(at, plus(previous["input_tokens"], previous["output_tokens"]), window, model,
                       capacity_basis="preceding_observation" if window is not None else "unavailable")
        elif kind == "event_msg" and p.get("type") == "token_count":
            quota(data, source, "codex", sid, p.get("rate_limits"), at, device, account)
            info = obj(p.get("info"))
            fresh = codex_counts(obj(info.get("last_token_usage")))
            total_raw = obj(info.get("total_token_usage"))
            if number(info.get("model_context_window")) is not None:
                window = number(info["model_context_window"])
            total = codex_counts(total_raw) if total_raw else None
            if total is not None and replay_pending and not (first_native and line > first_native[0]):
                if parent_snapshots and digest(total) in parent_snapshots:
                    last_total = total
                    warn(data, "inherited_legacy_snapshot_excluded", source["id"], line)
                    continue
                if not parent_snapshots or last_total is None:
                    # Without an established parent baseline, every leading
                    # legacy value could be replay. Do not charge it as own work.
                    warn(data, "fork_baseline_unknown", source["id"], line)
                    continue
                replay_pending = False
            changed_snapshot = total is not None and (
                context_total is None or not counters_equal(context_total, total))
            if first_native and line > first_native[0]:
                # The native response already anchors context. Token snapshots
                # can refine capacity, but repeated/quota-only events cannot
                # resurrect an anchor invalidated by a later compaction.
                if obs.context is not None and window is not None:
                    obs.context["window_tokens"] = window
                    obs.context["computed_percent"] = (100 * obs.context["used_tokens"] / window
                        if window and obs.context["used_tokens"] is not None else None)
                    obs.context["capacity_basis"] = "event_observation"
            elif fresh["input_tokens"] is not None and changed_snapshot:
                obs.anchor(at, plus(fresh["input_tokens"], fresh["output_tokens"]), window,
                           preceding_model, capacity_basis="event_observation" if
                           number(info.get("model_context_window")) is not None else "preceding_observation")
            context_total = total or context_total
            if total is None or (first_native and line > first_native[0]):
                continue
            if last_total is not None and counters_equal(total, last_total):
                continue
            if last_total is None:
                if replay_pending and not inherited:
                    warn(data, "fork_baseline_unknown", source["id"], line)
                    last_total = total
                    continue
                delta = total.copy()
            else:
                delta = delta_counts(total, last_total)
                if any(v is not None and v < 0 for v in delta.values()):
                    if counters_equal(total, fresh):
                        delta = fresh.copy()
                        warn(data, "counter_reset_reconciled", source["id"], line)
                    else:
                        warn(data, "counter_reset_unknown_baseline", source["id"], line)
                        last_total = total
                        continue
            last_total = total
            legacy.append(usage_row("codex", sid, ("legacy", total, at), delta, source,
                device, account, at, preceding_model, "codex_legacy_snapshot_delta",
                legacy_total_input_tokens=total["input_tokens"], legacy_total_output_tokens=total["output_tokens"],
                quality="reconstructed", model_inferred=True, parent_session_id=obs.parent))
    if legacy and first_native:
        p = first_native[1]
        thread_total = codex_counts(obj(pick(p, "thread_token_usage", "thread_total", "thread_total_usage",
                                               "thread_total_token_usage", "total_token_usage")))
        response = codex_counts(obj(p.get("usage")))
        budget = delta_counts(thread_total, response)
        # A legacy snapshot can precede its matching native event in the log.
        # Keep only endpoints proven to precede the first native response.
        proven = [r for r in legacy if all(budget.get(k) is not None and
            r.get("legacy_total_" + k) is not None and r["legacy_total_" + k] <= budget[k]
            for k in ("input_tokens", "output_tokens"))]
        if len(proven) != len(legacy):
            endpoints = [{k: r.get("legacy_total_" + k) for k in ("input_tokens", "output_tokens")} for r in proven]
            endpoints.append({"input_tokens": 0, "output_tokens": 0})
            resolved = any(all(budget.get(k) is not None and e[k] == budget[k] for k in e) for e in endpoints)
            warn(data, "native_legacy_overlap_reconciled" if resolved else "native_legacy_overlap_unresolved", source["id"])
        legacy = proven
    data["usage"].extend(legacy)
    obs.finish()


def claude_counts(raw: JSON) -> JSON:
    read = count(raw, "cache_read_input_tokens")
    write = count(raw, "cache_creation_input_tokens")
    ttl = obj(raw.get("cache_creation"))
    if write is None and ttl:
        write = plus(count(ttl, "ephemeral_5m_input_tokens"), count(ttl, "ephemeral_1h_input_tokens"))
    return {"input_tokens": plus(count(raw, "input_tokens"), read, write),
            "cache_read_tokens": read, "cache_write_tokens": write,
            "cache_write_5m_tokens": count(ttl, "ephemeral_5m_input_tokens"),
            "cache_write_1h_tokens": count(ttl, "ephemeral_1h_input_tokens"),
            "output_tokens": count(raw, "output_tokens"),
            "reasoning_tokens": count(raw, "reasoning_tokens", "thinking_tokens")}


def _claude(path: Path, data: JSON, source: JSON, device: str, account: str,
            selected: str | None) -> None:
    obs: Observations | None = None
    parent = path.parent.parent.name if path.parent.name == "subagents" else None
    window: int | float | None = None
    # The model a capacity was observed with; None until the next assistant request binds it.
    window_model: str | None = None
    request_counts: dict[str, JSON] = {}
    for line, row in jsonl(path, data, source):
        message = obj(row.get("message"))
        sid = identifier(row.get("sessionId"), path.stem)
        # Subagents often retain the parent's sessionId in every record.
        if parent:
            sid = path.stem
        if selected and sid != selected and parent != selected:
            continue
        if obs is None:
            obs = Observations(data, source, "claude", sid, device)
            obs.parent = identifier(parent or row.get("parentSessionId"), "unknown") if (
                parent or row.get("parentSessionId")) else None
            source["session_id"] = sid
        at = stamp(row)
        obs.tick(at)
        if row.get("type") == "subagent_completed" or row.get("subtype") == "subagent_completed":
            continue
        if row.get("subtype") == "compact_boundary" or row.get("type") == "compact_boundary":
            obs.compact(at, [])
            continue
        if number(row.get("model_context_window")) is not None:
            window, window_model = number(row["model_context_window"]), None
        metadata_window = obj(row.get("context_window"))
        if number(metadata_window.get("context_window_size")) is not None:
            window, window_model = number(metadata_window["context_window_size"]), None
        mid = message.get("id")
        # Claude stores distinct streamed content blocks under the same message
        # ID. UUID identifies the block observation, while repeated UUIDs replace
        # earlier snapshots of that same block.
        block_id = row.get("uuid") or mid or line
        blocks = message.get("content", [])
        if isinstance(blocks, str):
            obs.inv.add(str(block_id), blocks, str(message.get("role", row.get("type", "user"))))
        elif isinstance(blocks, list):
            for i, block in enumerate(blocks):
                b = obj(block)
                if b.get("type") == "text":
                    obs.inv.add(f"{block_id}:{i}", b.get("text"),
                                str(message.get("role", row.get("type", "user"))))
                elif b.get("type") in ("tool_use", "tool_result"):
                    obs.item(b, at, f"{block_id}:{i}")
        raw = obj(message.get("usage"))
        if row.get("type") != "assistant" or not raw or message.get("model") in ("<synthetic>", "synthetic"):
            continue
        request = pick(row, "requestId", "request_id")
        if not mid:
            warn(data, "missing_request_identity", source["id"], line)
            continue
        if not request:
            warn(data, "missing_request_id_message_fallback", source["id"], line)
        counts = claude_counts(raw)
        record = usage_row("claude", sid, (mid, request), counts, source, device, account,
            at, message.get("model"), "claude_request", parent_session_id=obs.parent,
            speed=safe_name(raw.get("speed")) if raw.get("speed") else None,
            inference_geo=safe_name(raw.get("inference_geo")) if raw.get("inference_geo") else None,
            service_tier=safe_name(raw.get("service_tier")) if raw.get("service_tier") else None)
        provider = pick(message, "provider", "model_provider") or pick(row, "provider", "model_provider")
        if provider:
            record.update(provider=safe_name(provider), model_attribution="recorded")
        # Claude's request identity is global, not scoped to the file or session copy.
        record["id"] = digest("usage", "claude", mid, request)
        searches = count(obj(raw.get("server_tool_use")), "web_search_requests")
        if searches is not None:
            record["web_search_requests"] = searches
        data["usage"].append(record)
        previous = request_counts.setdefault(record["id"], counts.copy())
        for k in TOKEN_FIELDS:
            if counts[k] is not None:
                previous[k] = max(counts[k], previous.get(k) or 0)
        # A capacity belongs to its model: drop it when the session switches models, as the Codex collector does.
        if window_model is not None and record["model"] != window_model:
            window = None
        window_model = record["model"]
        obs.anchor(at, previous["input_tokens"], window, record["model"])
    if obs:
        obs.finish()


def _copilot_events(path: Path, data: JSON, source: JSON, device: str,
                    account: str, selected: str | None) -> set[str]:
    obs: Observations | None = None
    sid = path.parent.name if path.name == "events.jsonl" else path.stem
    sessions: set[str] = set()
    checkpoint: JSON | None = None
    collected = {"input_tokens": 0, "output_tokens": 0}
    for line, row in jsonl(path, data, source):
        kind = row.get("type")
        p = obj(row.get("data"))
        if kind == "session.start":
            sid = identifier(pick(p, "sessionId", "session_id"), sid)
        if selected and selected != sid:
            continue
        if obs is None:
            obs = Observations(data, source, "copilot", sid, device)
            source["session_id"] = sid
        at = stamp(row)
        obs.tick(at)
        if kind == "session.usage_checkpoint":
            checkpoint = p
            continue
        if kind in ("session.compaction_complete", "session.compaction", "compact_boundary"):
            obs.compact(at)
            continue
        if kind in ("tool.execution_start", "tool.start"):
            obs.tool(pick(p, "toolCallId", "tool_call_id", "id") or line,
                     pick(p, "toolName", "name"), pick(p, "arguments", "input"), at)
        elif kind in ("tool.execution_complete", "tool.end"):
            obs.result(pick(p, "toolCallId", "tool_call_id", "id"),
                       pick(p, "result", "output", "content"))
        elif kind in ("user.message", "assistant.message"):
            obs.inv.add(str(row.get("id") or line), p.get("content"), kind.split(".")[0])
        if kind == "model.model_call_success":
            raw = obj(p.get("responseUsage"))
            call = obj(p.get("modelCall"))
            request = pick(call, "request_id", "requestId", "id") or pick(p, "request_id", "requestId")
            model = pick(call, "model", "modelId") or p.get("model")
        elif kind == "assistant.usage":
            raw = obj(p.get("usage")) or p
            call = p
            request = pick(p, "request_id", "requestId", "messageId")
            model = p.get("model")
        else:
            continue
        if not raw:
            warn(data, "unsupported_usage_schema", source["id"], line)
            continue
        details = obj(raw.get("details"))
        input_details = obj(raw.get("prompt_tokens_details"))
        output_details = obj(raw.get("completion_tokens_details"))
        counts = {"input_tokens": count(raw, "prompt_tokens", "input_tokens"),
            "output_tokens": count(raw, "completion_tokens", "output_tokens"),
            "cache_read_tokens": count(details, "cached_tokens", "cache_read_tokens") if details else
                count(input_details, "cached_tokens"),
            "cache_write_tokens": count(details, "cache_creation_tokens", "cache_write_tokens") if details else
                count(input_details, "cache_creation_tokens", "cache_write_tokens"),
            "reasoning_tokens": count(details, "reasoning_tokens") if details else
                count(output_details, "reasoning_tokens")}
        if not request:
            warn(data, "missing_request_identity", source["id"], line)
            continue
        record = usage_row("copilot", sid, request, counts, source, device, account, at,
                           model, "copilot_jsonl_request")
        data["usage"].append(record)
        for k in ("input_tokens", "output_tokens"):
            collected[k] += counts[k] or 0
        if counts["input_tokens"] is not None or counts["output_tokens"] is not None:
            sessions.add(sid)
        obs.anchor(at, counts["input_tokens"], pick(p, "model_context_window", "contextWindow"), record["model"])
    if checkpoint:
        # Checkpoints have no request identity and are never additive.
        warn(data, "checkpoint_crosscheck_only", source["id"])
        # The cumulative checkpoint exceeding the collected requests means the file lost requests
        # (truncated or rotated): the detailed total is a lower bound.
        raw = obj(checkpoint.get("usage")) or checkpoint
        reported = {"input_tokens": count(raw, "prompt_tokens", "input_tokens"),
                    "output_tokens": count(raw, "completion_tokens", "output_tokens")}
        if any(v is not None and v > collected[k] for k, v in reported.items()):
            warn(data, "checkpoint_exceeds_requests", source["id"])
    if obs:
        obs.finish()
    return sessions


SQL_COLUMNS = ("id", "session_id", "model", "input_tokens", "output_tokens",
               "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "created_at")
SQL_SELECT = "SELECT id, session_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, created_at FROM assistant_usage_events"


def _copilot_sql(path: Path, data: JSON, source: JSON, device: str, account: str,
                 selected: str | None, event_sessions: set[str]) -> None:
    memory = sqlite3.connect(":memory:")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)
        connection.execute("PRAGMA busy_timeout=200")
        deadline = time.monotonic() + 2.0
        def progress(status: int, remaining: int, total: int) -> None:
            if time.monotonic() > deadline:
                raise TimeoutError("snapshot deadline")
        connection.backup(memory, pages=128, progress=progress, sleep=0.01)
        schema = {r[1]: r[2].upper() for r in memory.execute("PRAGMA table_info(assistant_usage_events)")}
        numeric = SQL_COLUMNS[3:8]
        numeric_types = ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")
        if not all(k in schema for k in SQL_COLUMNS) or any(
                not any(t in schema[k] for t in numeric_types) for k in numeric):
            warn(data, "unsupported_sql_schema", source["id"])
            return
        totals: dict[str, JSON] = {}
        alternatives: dict[str, list[JSON]] = defaultdict(list)
        observations: dict[str, Observations] = {}
        for values in memory.execute(SQL_SELECT):
            source["rows_seen"] += 1
            raw = dict(zip(SQL_COLUMNS, values))
            sid = identifier(raw["session_id"], "unknown")
            if selected and selected != sid:
                continue
            created = raw["created_at"]
            at = timestamp(created)
            if at is None and isinstance(created, str) and re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?", created):
                at = timestamp(created.replace(" ", "T") + "Z")
            if sid in event_sessions:
                aggregate = totals.setdefault(sid, {k: 0 for k in TOKEN_FIELDS})
                for k in TOKEN_FIELDS:
                    aggregate[k] = plus(aggregate[k], number(raw[k]))
                alternatives[sid].append(usage_row("copilot", sid, ("sql", raw["id"]), raw, source,
                    device, account, at, raw["model"], "copilot_sql_request"))
                continue
            if sid not in observations:
                observations[sid] = Observations(data, source, "copilot", sid, device)
                warn(data, "sql_only_session_coverage", source["id"])
            # This store writes UTC wall-clock SQL timestamps without an offset.
            # Interpret that documented SQL representation here only; generic
            # imports still reject timezone-naive observations.
            observations[sid].tick(at)
            data["usage"].append(usage_row("copilot", sid, ("sql", raw["id"]), raw, source,
                device, account, at, raw["model"], "copilot_sql_request"))
        for sid, total in totals.items():
            event_rows = coalesce([r.copy() for r in data["usage"] if r["agent"] == "copilot"
                                  and r["session_id"] == sid and r["accounting_mode"] == "copilot_jsonl_request"])
            different = any(total[k] != plus(*(r[k] for r in event_rows)) for k in TOKEN_FIELDS)
            prefer_sql, measures_differ = copilot_preference(alternatives[sid], event_rows)
            different = different or measures_differ
            if prefer_sql:
                excluded_ids = {r["id"] for r in event_rows}
                data["usage"] = [r for r in data["usage"] if r["id"] not in excluded_ids]
                data["usage"].extend(alternatives[sid])
            code = "sql_jsonl_discrepancy" if different else "sql_jsonl_alternative_excluded"
            warn(data, code, source["id"])
            # Only numeric mismatch evidence is retained, never the SQL row itself.
            evidence = data["warnings"][-1]
            evidence["session_id"] = sid
            evidence["sql_rows"] = memory.execute(
                "SELECT count(*) FROM assistant_usage_events WHERE session_id = ?", (sid,)).fetchone()[0]
            evidence["jsonl_rows"] = len(event_rows)
            evidence["sql_totals"] = total
            evidence["jsonl_totals"] = {k: plus(*(r[k] for r in event_rows)) for k in TOKEN_FIELDS}
        for obs in observations.values():
            obs.finish()
        source["files_parsed"] = 1
    except (sqlite3.Error, OSError, TimeoutError):
        warn(data, "sql_snapshot_unreadable", source["id"])
    finally:
        if connection:
            connection.close()
        memory.close()


def _json_file(path: Path, data: JSON, source: JSON) -> JSON:
    try:
        with path.open(encoding="utf-8-sig") as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        source["files_parsed"] = 1
        source["rows_seen"] = 1
        return raw
    except (OSError, UnicodeError):
        warn(data, "source_unreadable", source["id"])
    except (ValueError, RecursionError):
        source["malformed_rows"] += 1
        warn(data, "malformed_json", source["id"])
    return {}


def _grok(path: Path, data: JSON, source: JSON, device: str, account: str,
          selected: str | None) -> None:
    raw = _json_file(path, data, source)
    if not raw:
        return
    sid = identifier(raw.get("sessionId"), path.parent.name)
    if selected and sid != selected:
        return
    source["session_id"] = sid
    obs = Observations(data, source, "grok", sid, device)
    obs.tick(stamp(raw))
    if path.name == "signals.json":
        # Strict numeric-only metadata. No prompt/history/config inspection.
        obs.compactions = int(count(raw, "compactionCount") or 0)
        obs.anchor(stamp(raw), count(raw, "contextTokensUsed"), count(raw, "contextWindowTokens"),
                   safe_name(raw.get("model")), basis="reported_context_tokens")
    else:
        turns = raw.get("turns")
        if not isinstance(turns, list) or not turns:
            warn(data, "grok_aggregate_unavailable_without_turns", source["id"])
        for index, turn in enumerate(turns if isinstance(turns, list) else []):
            turn = obj(turn)
            model_usage = turn.get("modelUsage")
            if isinstance(model_usage, dict):
                models = [(model, obj(counters)) for model, counters in model_usage.items()]
            elif isinstance(model_usage, list):
                models = [(pick(obj(v), "model", "modelId"), obj(v)) for v in model_usage]
            else:
                warn(data, "grok_turn_usage_unavailable", source["id"], index + 1)
                continue
            for model, counters in models:
                counts = {"input_tokens": count(counters, "inputTokens"),
                    "output_tokens": count(counters, "outputTokens"),
                    "cache_read_tokens": count(counters, "cachedReadTokens"),
                    "cache_write_tokens": count(counters, "cacheCreationTokens"),
                    "reasoning_tokens": count(counters, "reasoningTokens")}
                total = count(counters, "totalTokens")
                if total is not None and plus(counts["input_tokens"], counts["output_tokens"]) != total:
                    counts["input_tokens"] = None
                    warn(data, "grok_input_semantics_ambiguous", source["id"], index + 1)
                at = stamp(turn)
                obs.tick(at)
                data["usage"].append(usage_row("grok", sid,
                    (pick(turn, "turnId", "id") or index, safe_name(model)), counts, source,
                    device, account, at, model, "grok_turn_model_usage", unit="turn",
                    request_count=count(counters, "modelCalls")))
    obs.finish(emit_context=path.name == "signals.json")


def agy_counts(raw: JSON, data: JSON, source: JSON) -> JSON:
    inp = count(raw, "input_tokens", "inputTokens")
    out = count(raw, "output_tokens", "outputTokens")
    read = count(raw, "cache_read_tokens", "cache_read_input_tokens", "cached_input_tokens")
    write = count(raw, "cache_creation_tokens", "cache_creation_input_tokens", "cache_write_tokens")
    reasoning = count(raw, "thinking_tokens", "reasoning_tokens")
    total = count(raw, "total_tokens", "totalTokens")
    semantics = pick(raw, "input_includes_cache", "inputIncludesCache")
    if semantics is True:
        if inp is not None and (read or 0) + (write or 0) > inp:
            inp = None
            warn(data, "agy_cache_semantics_ambiguous", source["id"])
    elif semantics is False:
        inp = plus(inp, read or 0, write or 0)
    elif (read or 0) or (write or 0):
        # total=input+output does not establish whether the cache is included;
        # both interpretations occur in documented/observed export variants.
        inp = None
        warn(data, "agy_cache_semantics_ambiguous", source["id"])
    elif total is not None and inp is not None and out is not None and total != inp + out:
        inp = None
        warn(data, "agy_input_semantics_ambiguous", source["id"])
    if reasoning is not None and (out is None or reasoning > out):
        reasoning = None
        warn(data, "agy_reasoning_subset_unknown", source["id"])
    return {"input_tokens": inp, "output_tokens": out, "cache_read_tokens": read,
            "cache_write_tokens": write, "reasoning_tokens": reasoning}


def _agy(path: Path, data: JSON, source: JSON, device: str, account: str,
         selected: str | None) -> None:
    rows = [(1, _json_file(path, data, source))] if path.suffix.lower() == ".json" else jsonl(path, data, source)
    results: dict[str, list[tuple[JSON, JSON]]] = defaultdict(list)
    steps: dict[str, list[tuple[JSON, JSON, object]]] = defaultdict(list)
    observations: dict[str, Observations] = {}
    for line, row in rows:
        if not row:
            continue
        event = pick(row, "event", "type")
        payload = obj(row.get(event)) if isinstance(event, str) else {}
        payload = payload or obj(pick(row, "data", "step")) or row
        sid = identifier(pick(payload, "conversation_id", "conversationId", "session_id") or
                         pick(row, "conversation_id", "conversationId", "session_id"), path.stem)
        if selected and sid != selected:
            continue
        obs = observations.setdefault(sid, Observations(data, source, "agy", sid, device))
        obs.tick(stamp(row))
        raw = obj(payload.get("usage"))
        if not raw:
            continue
        row = {**payload, "type": event or row.get("type"), "timestamp": stamp(row) or stamp(payload)}
        counts = agy_counts(raw, data, source)
        if row.get("type") == "result" or (path.suffix.lower() == ".json" and row.get("type") is None):
            results[sid].append((row, counts))
        elif row.get("type") == "step_update" and pick(payload, "state", "status") == "DONE":
            steps[sid].append((row, counts, pick(payload, "step_id", "step_index", "id") or line))
    for sid, obs in observations.items():
        cumulative = results.get(sid, [])
        if cumulative:
            # Keep final cumulative result when time attribution is unavailable.
            # With trustworthy event times, difference cumulative observations.
            timed = all(stamp(row) for row, _ in cumulative)
            timed = timed and all(stamp(cumulative[i][0]) > stamp(cumulative[i-1][0])
                                  for i in range(1, len(cumulative)))
            if not timed:
                row, counters = cumulative[-1]
                data["usage"].append(usage_row("agy", sid, "cumulative_session", counters,
                    source, device, account, None, row.get("model"), "agy_final_cumulative",
                    unit="session", request_count=None))
                warn(data, "agy_aggregate_time_unavailable", source["id"])
            else:
                previous: JSON | None = None
                for index, (row, counters) in enumerate(cumulative):
                    delta = delta_counts(counters, previous) if previous is not None else counters.copy()
                    if any(v is not None and v < 0 for v in delta.values()):
                        # A result is explicitly cumulative since a session reset.
                        delta = counters.copy()
                        warn(data, "agy_cumulative_reset", source["id"])
                    data["usage"].append(usage_row("agy", sid,
                        ("cumulative", stamp(row)), delta, source, device, account,
                        stamp(row), row.get("model"), "agy_cumulative_delta", unit="turn",
                        request_count=None, cumulative_observed_at=stamp(row),
                        **{"cumulative_" + key: counters[key] for key in TOKEN_FIELDS}))
                    previous = counters
        else:
            for row, counters, key in steps.get(sid, []):
                data["usage"].append(usage_row("agy", sid, ("step", key), counters, source,
                    device, account, stamp(row), row.get("model"), "agy_done_step"))
        obs.finish()


def _discover(agent: str, path: Path, selected: str | None) -> list[Path]:
    if path.is_file():
        eligible = path.suffix.lower() in ((".json", ".jsonl") if agent == "agy" else
            (".jsonl",) if agent in ("codex", "claude") else
            (".jsonl", ".db", ".sqlite", ".sqlite3") if agent == "copilot" else (".json",))
        if agent == "grok":
            eligible = path.name in ("usage.json", "signals.json")
        return [path] if eligible and not path.is_symlink() else []
    if not path.is_dir() or agent == "agy":
        return []
    # Bound discovery to known source subdirectories. Never rglob a user's home.
    roots: list[Path] = []
    patterns: tuple[str, ...]
    if agent == "codex":
        roots = [p for p in (path / "sessions", path / "archived_sessions") if p.is_dir()]
        if path.name in ("sessions", "archived_sessions"):
            roots = [path]
        patterns = ("**/*.jsonl",)
    elif agent == "claude":
        roots = [path / "projects"] if (path / "projects").is_dir() else []
        if path.name == "projects":
            roots = [path]
        elif path.parent.name == "projects":
            roots = [path]
        patterns = ("**/*.jsonl",)
    elif agent == "copilot":
        roots = [path / "session-state"] if (path / "session-state").is_dir() else []
        if path.name == "session-state":
            roots = [path]
        elif (path / "events.jsonl").is_file():
            roots = [path]
        patterns = ("*/events.jsonl", "events.jsonl")
    else:
        roots = [path / "sessions"] if (path / "sessions").is_dir() else []
        if path.name == "sessions":
            roots = [path]
        elif (path / "usage.json").is_file() or (path / "signals.json").is_file():
            roots = [path]
        patterns = ("**/usage.json", "**/signals.json")
    found: set[Path] = set()
    for root in roots:
        for pattern in patterns:
            for candidate in root.glob(pattern):
                if candidate.is_file() and not candidate.is_symlink():
                    # Filename filters are safe only when the format includes
                    # the session ID there. Claude streaming copies may differ.
                    if (selected and agent == "codex" and
                            re.fullmatch(r"[a-fA-F0-9-]{36}", selected) and
                            candidate.name.startswith("rollout-") and selected not in candidate.stem):
                        # Children have their own UUID filenames. Inspect only
                        # metadata rather than parsing unrelated full rollouts.
                        related = False
                        try:
                            with candidate.open(encoding="utf-8-sig") as stream:
                                first = obj(json.loads(stream.readline()))
                            p = obj(first.get("payload")) if first.get("type") == "session_meta" else {}
                            sub = obj(obj(p.get("source")).get("subagent"))
                            parent = pick(p, "forked_from_id", "parent_thread_id", "parent_session_id")
                            parent = parent or pick(sub, "parent_thread_id", "parent_session_id")
                            parent = parent or pick(obj(sub.get("thread_spawn")), "parent_thread_id", "parent_session_id")
                            related = parent == selected or p.get("id") == selected
                        except (OSError, ValueError, UnicodeError):
                            pass
                        if not related:
                            continue
                    found.add(candidate)
    if agent == "copilot":
        for name in ("session-store.db", "session-state.db", "sessions.db"):
            if (path / name).is_file():
                found.add(path / name)
    return sorted(found, key=str)


def collect(agent: str, path: Path, device: str = "local", account: str = "local",
            session: str | None = None) -> JSON:
    """Collect numeric observations from an eligible file or native data root."""
    if agent not in ("codex", "claude", "copilot", "grok", "agy"):
        raise ValueError("Unsupported agent")
    path = Path(path)
    data = dataset()
    files = _discover(agent, path, session)
    if not files:
        source = source_info(path, agent, device)
        source["files_seen"] = 0
        data["sources"].append(source)
        warn(data, "explicit_export_required" if agent == "agy" and path.is_dir() else
             "no_eligible_sources", source["id"])
        return data
    sql: list[tuple[Path, JSON]] = []
    event_sessions: set[str] = set()
    for file in files:
        source = source_info(file, agent, device, origin="imported" if agent == "agy" else "local")
        data["sources"].append(source)
        if agent == "codex":
            _codex(file, data, source, device, account, session)
        elif agent == "claude":
            _claude(file, data, source, device, account, session)
        elif agent == "copilot":
            if file.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
                sql.append((file, source))
            else:
                event_sessions.update(_copilot_events(file, data, source, device, account, session))
        elif agent == "grok":
            _grok(file, data, source, device, account, session)
        else:
            _agy(file, data, source, device, account, session)
    for file, source in sql:
        _copilot_sql(file, data, source, device, account, session, event_sessions)
    for key in ("usage", "tools", "quotas"):
        data[key] = coalesce(data[key])
    # Native context/signals outrank unavailable companions; equal-time duplicates
    # retain the greatest measured occupancy rather than losing partial streaming.
    contexts: dict[str, JSON] = {}
    for row in data["contexts"]:
        key = row["session_id"]
        old = contexts.get(key)
        if old is None or (row.get("observed_at") or "", row.get("used_tokens") is not None,
                           row.get("used_tokens") or 0) > (old.get("observed_at") or "",
                           old.get("used_tokens") is not None, old.get("used_tokens") or 0):
            contexts[key] = row
    data["contexts"] = list(contexts.values())
    sessions: dict[str, JSON] = {}
    for row in data["sessions"]:
        old = sessions.get(row["id"])
        if old is None:
            sessions[row["id"]] = row
        else:
            starts = [x for x in (old["start"], row["start"]) if x]
            ends = [x for x in (old["end"], row["end"]) if x]
            old.update(start=min(starts) if starts else None, end=max(ends) if ends else None,
                       compactions=max(old["compactions"], row["compactions"]))
    data["sessions"] = list(sessions.values())
    data["warnings"] = list({w["id"]: w for w in data["warnings"]}.values())
    return data
