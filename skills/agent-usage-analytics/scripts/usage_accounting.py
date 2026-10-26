"""Per-observation pricing, aggregation and guarded quota comparisons."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import secrets
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage_common import COUNTS, LISTS, copilot_preference, dataset, digest, number, safe_name, timestamp
from usage_attribution import attribution_rank


def merge(*datasets: dict[str, Any]) -> dict[str, Any]:
    """Stable identities reconcile duplicate files; counts are never additive."""
    result = dataset()
    for kind in LISTS:
        records: dict[str, dict[str, Any]] = {}
        for data in datasets:
            for record in data.get(kind, []):
                key = record.get("id") or digest(kind, record)
                if key not in records:
                    records[key] = deepcopy(record)
                    continue
                old = records[key]
                if kind in ("usage", "contexts"):
                    if attribution_rank(record) > attribution_rank(old) or (
                            attribution_rank(record) == 2 and attribution_rank(old) == 2):
                        for field in ("model", "reported_model", "provider", "model_attribution", "speed", "inference_geo", "service_tier"):
                            if field in record:
                                old[field] = record[field]
                if kind == "usage":
                    for field, value in record.items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            prior = number(old.get(field))
                            old[field] = max(prior, value) if prior is not None else value
                        elif old.get(field) is None:
                            old[field] = value
                elif kind == "tools":
                    for field in ("argument_chars", "result_chars"):
                        old[field] = max(old.get(field) or 0, record.get(field) or 0)
                elif kind == "sources":
                    records[key] = deepcopy(record)
                elif kind == "sessions":
                    starts = [v for v in (old.get("start"), record.get("start")) if v]
                    ends = [v for v in (old.get("end"), record.get("end")) if v]
                    old.update(start=min(starts) if starts else None, end=max(ends) if ends else None,
                               compactions=max(old.get("compactions") or 0, record.get("compactions") or 0))
        result[kind] = list(records.values())
    # Alternative accounting sources must reconcile across files AND ledger runs.
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in result["usage"]:
        groups[(row.get("agent"), row.get("session_id"))].append(row)
    reconciled = []
    for (agent, sid), rows in groups.items():
        if agent == "codex":
            native = [r for r in rows if r.get("accounting_mode") == "codex_native_per_response"]
            legacy = [r for r in rows if r.get("accounting_mode") == "codex_legacy_snapshot_delta"]
            if native and legacy:
                first = min(native, key=lambda r: (r.get("native_total_input_tokens") or 0,
                                                   r.get("native_total_output_tokens") or 0,
                                                   r.get("timestamp") or ""))
                budget = {key: first.get("native_total_" + key) - first[key]
                          if first.get("native_total_" + key) is not None and first.get(key) is not None else None
                          for key in ("input_tokens", "output_tokens")}
                excluded = [r for r in legacy if not all(budget[key] is not None and
                            r.get("legacy_total_" + key) is not None and
                            r["legacy_total_" + key] <= budget[key] for key in budget)]
                if excluded:
                    ids = {r["id"] for r in excluded}
                    rows = [r for r in rows if r["id"] not in ids]
                    endpoints = [{key: r.get("legacy_total_" + key) for key in budget} for r in rows
                                 if r.get("accounting_mode") == "codex_legacy_snapshot_delta"] + [{key: 0 for key in budget}]
                    resolved = any(all(budget[key] is not None and endpoint[key] == budget[key] for key in budget) for endpoint in endpoints)
                    code = "native_legacy_overlap_reconciled" if resolved else "native_legacy_overlap_unresolved"
                    result["warnings"].append({"id": digest(code, sid),
                        "code": code, "session_id": sid,
                        "source_id": excluded[0].get("source_id")})
        if agent == "copilot":
            sql = [r for r in rows if r.get("accounting_mode") == "copilot_sql_request"]
            events = [r for r in rows if r.get("accounting_mode") == "copilot_jsonl_request"]
            if sql and events:
                prefer_sql, different = copilot_preference(sql, events)
                excluded = events if prefer_sql else sql
                excluded_ids = {r["id"] for r in excluded}
                rows = [r for r in rows if r["id"] not in excluded_ids]
                code = "sql_jsonl_discrepancy" if different else "copilot_alternative_source_reconciled"
                result["warnings"].append({"id": digest(code, sid), "code": code,
                    "source_id": excluded[0].get("source_id"), "session_id": sid})
        if agent == "agy":
            snapshots = [r for r in rows if r.get("accounting_mode") in ("agy_cumulative_delta", "agy_final_cumulative")]
            if snapshots:
                rows = [r for r in rows if r.get("accounting_mode") != "agy_done_step"]
                timed = [r for r in snapshots if r.get("cumulative_observed_at")]
                untimed = [r for r in snapshots if not r.get("cumulative_observed_at")]
                if untimed:
                    # A timeless aggregate cannot be added to a timed prefix.
                    chosen = deepcopy(untimed[0])
                    for field in COUNTS:
                        values = [r.get("cumulative_" + field, r.get(field)) for r in snapshots]
                        known = [v for v in values if number(v) is not None]
                        chosen[field] = max(known) if known else None
                    chosen["timestamp"] = None
                    snapshot_ids = {r["id"] for r in snapshots}
                    rows = [r for r in rows if r["id"] not in snapshot_ids] + [chosen]
                else:
                    previous = None
                    for row in sorted(timed, key=lambda r: r["cumulative_observed_at"]):
                        totals = {key: row.get("cumulative_" + key) for key in COUNTS}
                        delta = {key: (totals[key] - previous[key] if previous is not None and totals[key] is not None and previous[key] is not None
                                       else totals[key]) for key in COUNTS}
                        if any(v is not None and v < 0 for v in delta.values()):
                            delta = totals.copy()
                        row.update(delta)
                        row["timestamp"] = row["cumulative_observed_at"] if previous is not None else None
                        row["unit"] = "turn" if previous is not None else "session"
                        row["quality"] = "reconstructed"
                        previous = totals
        reconciled.extend(rows)
    result["usage"] = reconciled
    result["warnings"] = list({r["id"]: r for r in result["warnings"]}.values())
    return result


def load_rates(path: Path | None = None) -> dict[str, Any]:
    path = path or Path(__file__).resolve().parent.parent / "assets" / "pricing.json"
    card = json.loads(path.read_text(encoding="utf-8-sig"))
    if card.get("schema_version") != 1 or card.get("currency") != "USD" or not isinstance(card.get("models"), dict):
        raise ValueError("Unsupported pricing schema; expected version 1 and USD models")
    rate_fields = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
    for entry in card["models"].values():
        variants = entry if isinstance(entry, list) else [entry]
        if not variants or not all(isinstance(v, dict) for v in variants):
            raise ValueError("Each model needs a rate object or effective-date variants")
        for variant in variants:
            for field in rate_fields:
                if number(variant.get(field)) is None:
                    raise ValueError("Invalid nonnegative rate in pricing card")
            alternatives = [variant.get("alternate_rates", {})]
            tiers = variant.get("tiers", [])
            if not isinstance(tiers, list):
                raise ValueError("Price tiers must be a list")
            for tier in tiers:
                if not isinstance(tier, dict) or number(tier.get("above_input_tokens")) is None or not isinstance(tier.get("rates"), dict):
                    raise ValueError("Invalid request prompt tier")
                alternatives.append(tier["rates"])
            for override in alternatives:
                if not isinstance(override, dict) or any(key not in rate_fields or number(value) is None for key, value in override.items()):
                    raise ValueError("Invalid alternate token rates")
            for field in ("fast_multiplier", "ultrafast_multiplier"):
                if variant.get(field) is not None and (number(variant[field]) is None or variant[field] <= 0):
                    raise ValueError("Invalid speed multiplier")
            for field in ("effective_from", "effective_until"):
                if variant.get(field):
                    try:
                        parsed = datetime.fromisoformat(variant[field].replace("Z", "+00:00"))
                    except (ValueError, TypeError, AttributeError) as exc:
                        raise ValueError("Invalid effective date in pricing card") from exc
                    variant[field] = timestamp(parsed.replace(tzinfo=timezone.utc).isoformat() if parsed.tzinfo is None else parsed.isoformat())
    aliases = card.get("aliases", {})
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or v not in card["models"] for k, v in aliases.items()):
        raise ValueError("Price aliases must target explicit model entries")
    return card


def price(row: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Ranges cover missing cache allocations/TTL/tier; never price totals."""
    result = {"cost_lower_usd": None, "cost_upper_usd": None, "price_status": "unpriced", "price_notes": []}
    model = card.get("aliases", {}).get(row.get("model"), row.get("model"))
    entry = card["models"].get(model)
    if entry is None:
        result["price_notes"] = ["unknown_model"]
        return result
    variants = entry if isinstance(entry, list) else [entry]
    when = row.get("timestamp")
    variants = [v for v in variants if (not v.get("effective_from") or when and when >= v["effective_from"])
                and (not v.get("effective_until") or when and when < v["effective_until"])]
    if not variants:
        result["price_notes"] = ["no_effective_rate"]
        return result
    inp, out = number(row.get("input_tokens")), number(row.get("output_tokens"))
    read, write = number(row.get("cache_read_tokens")), number(row.get("cache_write_tokens"))
    reasoning = number(row.get("reasoning_tokens"))
    if inp is None or out is None:
        result["price_notes"] = ["missing_usage"]
        return result
    if (read or 0) + (write or 0) > inp or reasoning is not None and reasoning > out:
        result["price_notes"] = ["invalid_token_subsets"]
        return result
    costs: list[Decimal] = []
    notes: set[str] = set()
    if attribution_rank(row) == 0:
        notes.add("reported_model_unverified")
    for base in variants:
        provider = row.get("provider")
        if provider:
            provider = {"z.ai": "zai", "z-ai": "zai"}.get(provider.lower(), provider.lower())
        if provider and provider != base.get("provider"):
            return {**result, "price_notes": ["provider_model_mismatch"]}
        options = [base]
        for tier in base.get("tiers", []):
            if row.get("unit", "request") != "request":
                options.append({**base, **tier["rates"]})
                notes.add("aggregate_prompt_tier_range")
            elif inp > tier["above_input_tokens"]:
                options = [{**base, **tier["rates"]}]
        if base.get("alternate_rates"):
            options.append({**base, **base["alternate_rates"]})
            notes.add("prompt_tier_range")
        for rate in options:
            multiplier = Decimal(1)
            speed = (row.get("speed") or row.get("service_tier") or "standard").lower()
            if speed in ("fast", "priority", "ultrafast"):
                factor = rate.get("ultrafast_multiplier" if speed == "ultrafast" else "fast_multiplier")
                if factor is None:
                    return {**result, "price_notes": ["unknown_speed_rate"]}
                multiplier *= Decimal(str(factor))
            elif speed not in ("standard", "default", "auto", "normal"):
                return {**result, "price_notes": ["unsupported_service_tier"]}
            geo = row.get("inference_geo")
            if geo == "us" and rate.get("provider") == "anthropic":
                multiplier *= Decimal("1.1")
            elif geo not in (None, "global", "us") and rate.get("provider") in ("anthropic", "openai"):
                notes.add("geography_rate_not_established")
                return {**result, "price_notes": sorted(notes)}
            rates = {k: Decimal(str(rate[k])) for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")}
            for key in ("cache_write_5m", "cache_write_1h"):
                if not rates[key]:
                    rates[key] = rates["input"]
            fixed = Decimal(str(read or 0)) * rates["cache_read"] + Decimal(str(out)) * rates["output"]
            w5, w1 = number(row.get("cache_write_5m_tokens")), number(row.get("cache_write_1h_tokens"))
            known5, known1 = w5 or 0, w1 or 0
            if known5 + known1 > (write or 0):
                return {**result, "price_notes": ["invalid_cache_ttl_split"]}
            fixed += Decimal(str(known5)) * rates["cache_write_5m"] + Decimal(str(known1)) * rates["cache_write_1h"]
            remaining_write = (write or 0) - known5 - known1
            write_prices = [rates["cache_write_5m"], rates["cache_write_1h"]]
            # Models without an independent cache-write price charge their ordinary input rate.
            write_prices = [x if x else rates["input"] for x in write_prices]
            if remaining_write:
                notes.add("cache_ttl_range")
            remaining_input = inp - (read or 0) - (write or 0)
            possible = [rates["input"]]
            if read is None:
                possible.append(rates["cache_read"])
                notes.add("cache_read_not_reported")
            if write is None:
                possible.extend(write_prices)
                notes.add("cache_write_not_reported")
            for choose in (min, max):
                weighted = fixed + Decimal(str(remaining_write)) * choose(write_prices)
                weighted += Decimal(str(remaining_input)) * choose(possible)
                costs.append(weighted * multiplier / Decimal(1_000_000))
        if not base.get("effective_from"):
            notes.add("reference_rates_not_historical_invoice")
    lo, hi = float(min(costs)), float(max(costs))
    return {"cost_lower_usd": lo, "cost_upper_usd": hi,
            "price_status": "priced" if lo == hi else "range", "price_notes": sorted(notes)}


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def calls(row):
        value = number(row.get("request_count"))
        return value if value is not None else 1
    result: dict[str, Any] = {key: sum(row.get(key) or 0 for row in rows) for key in COUNTS}
    result.update(requests=sum(calls(row) for row in rows),
                  sessions=len({(r.get("agent"), r.get("session_id")) for r in rows}),
                  total_tokens=result["input_tokens"] + result["output_tokens"],
                  cost_lower_usd=sum(r.get("cost_lower_usd") or 0 for r in rows),
                  cost_upper_usd=sum(r.get("cost_upper_usd") or 0 for r in rows),
                  priced_requests=sum(calls(r) for r in rows if r.get("price_status") != "unpriced"),
                  unpriced_requests=sum(calls(r) for r in rows if r.get("price_status") == "unpriced"),
                  missing_usage_requests=sum(calls(r) for r in rows
                                            if r.get("input_tokens") is None or r.get("output_tokens") is None))
    result["cache_hit_percent"] = 100 * result["cache_read_tokens"] / result["input_tokens"] if result["input_tokens"] else None
    result["unknown_request_count_observations"] = sum(r.get("request_count") is None for r in rows)
    result["count_quality"] = "known lower bound" if result["missing_usage_requests"] or result["unknown_request_count_observations"] else "reported/reconstructed"
    result["missing_fields"] = {key: sum(row.get(key) is None for row in rows) for key in COUNTS}
    return result


def _bound(value: str | None, tz: timezone | ZoneInfo) -> str | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return timestamp(dt.replace(tzinfo=tz).isoformat() if dt.tzinfo is None else dt.isoformat())


def _groups(rows: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return [{"label": label, **stats(items)} for label, items in sorted(grouped.items())]


def quota_analysis(quotas: list[dict[str, Any]], requests: list[dict[str, Any]], complete: bool = False) -> list[dict[str, Any]]:
    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for quota in quotas:
        grouped[(quota.get("agent"), quota.get("account"), quota.get("bucket"), quota.get("resets_at"),
                 quota.get("window_minutes"), quota.get("provider"))].append(quota)
    result = []
    for (agent, account, bucket, reset, duration, provider), rows in grouped.items():
        rows = sorted(rows, key=lambda q: q.get("observed_at") or "")
        item = {"agent": agent, "account": account, "bucket": bucket, "resets_at": reset, "provider": provider,
                "window_minutes": duration, "samples": len(rows), "status": "unavailable",
                "tokens_per_point": None, "cost_per_point": None}
        reason = "Declare complete device/cloud coverage to attempt empirical calibration."
        if complete:
            reason = "Need five compatible observations spanning five percentage points in one reset period."
            valid = [r for r in rows if number(r.get("used_percent")) is not None and r.get("observed_at")]
            if len(valid) >= 5 and reset and valid[-1]["observed_at"] < reset:
                percentages = [r["used_percent"] for r in valid]
                if any(b < a for a, b in zip(percentages, percentages[1:])):
                    reason = "Quota decreased; reset/aging intervals cannot be calibrated."
                elif percentages[-1] - percentages[0] >= 5:
                    relevant = [r for r in requests if r.get("agent") == agent and r.get("account", "local") == account
                                and r.get("timestamp") and valid[0]["observed_at"] < r["timestamp"] <= valid[-1]["observed_at"]]
                    mix = {(r.get("model"), r.get("speed"), r.get("service_tier"), r.get("provider")) for r in relevant}
                    routes = {r.get("provider") for r in relevant if r.get("provider")}
                    if duration:
                        start = datetime.fromisoformat(valid[0]["observed_at"].replace("Z", "+00:00")) - timedelta(minutes=duration)
                        end = datetime.fromisoformat(valid[-1]["observed_at"].replace("Z", "+00:00")) - timedelta(minutes=duration)
                        aging = any(r.get("agent") == agent and r.get("timestamp") and
                                    timestamp(start.isoformat()) < r["timestamp"] <= timestamp(end.isoformat()) for r in requests)
                    else:
                        aging = True
                    # A provider-tagged quota needs every request confirmed on that route: an unmapped request
                    # may have gone through a proxy such as Z.ai and says nothing about this provider's quota.
                    unconfirmed = provider is not None and any(r.get("provider") != provider for r in relevant)
                    if (routes and routes != {provider}) or unconfirmed:
                        reason = "Quota provider is unknown or differs from the confirmed serving route."
                    elif len(mix) != 1 or not relevant or aging or any(r.get("input_tokens") is None or r.get("output_tokens") is None for r in relevant):
                        reason = "Mixed models/speeds, aging usage or incomplete measurements prevent calibration."
                    else:
                        span = percentages[-1] - percentages[0]
                        total = stats(relevant)
                        item.update(status="experimental", tokens_per_point=total["total_tokens"] / span,
                                    cost_per_point=(total["cost_lower_usd"] / span if not total["unpriced_requests"] else None),
                                    observed_percent_span=span)
                        reason = "Empirical interval ratio; provider weighting is unknown and this is not a token allowance."
        result.append({**item, "reason": reason})
    return result


def build_report(data: dict[str, Any], card: dict[str, Any], *, since: str | None = None,
                 until: str | None = None, tz_name: str = "UTC", session_id: str | None = None,
                 compare_since: str | None = None, compare_until: str | None = None,
                 share: bool = False, complete_coverage: bool = False,
                 task_map: dict[str, str] | None = None, now: str | None = None) -> dict[str, Any]:
    try:
        tz = timezone.utc if tz_name == "UTC" else ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Timezone unavailable; use UTC or install a timezone database") from exc
    start, end = _bound(since, tz), _bound(until, tz)
    if start and end and start >= end:
        raise ValueError("The start must be earlier than the exclusive end")
    data = merge(data)
    all_rows = [{**row, **price(row, card)} for row in data["usage"]]
    related_sessions = {(r.get("agent"), r.get("session_id")) for r in data["sessions"]
                        if r.get("parent_session_id") == session_id} if session_id else set()
    def session_scope(row):
        return (not session_id or row.get("session_id") == session_id or row.get("parent_session_id") == session_id
                or (row.get("agent"), row.get("session_id")) in related_sessions)
    def in_scope(row, time_key="timestamp", account_scope=False):
        if not account_scope and not session_scope(row):
            return False
        when = row.get(time_key)
        return not (start and (not when or when < start) or end and (not when or when >= end))
    rows = [r for r in all_rows if in_scope(r)]
    selected_source_ids = {r.get("source_id") for r in all_rows + data["contexts"] + data["tools"] if session_scope(r)}
    selected_source_ids.update(s.get("id") for s in data["sources"] if session_scope(s))
    selected_warnings = [w for w in data["warnings"] if not session_id or
                         w.get("source_id") in selected_source_ids or w.get("session_id") == session_id]
    for row in rows:
        row["task"] = safe_name((task_map or {}).get(row.get("session_id"),
                                (task_map or {}).get(row.get("parent_session_id"), "unclassified")))
    def date_key(row, length):
        when = row.get("timestamp")
        return datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(tz).isoformat()[:length] if when else "undated"
    tools = [r for r in data["tools"] if in_scope(r)]
    ranked: dict[str, list[dict[str, Any]]] = {"tools": [], "skills": []}
    for kind in ("tool", "skill"):
        grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for row in tools:
            if row.get("kind", "tool") == kind:
                grouped[(row.get("agent"), row.get("name", "unknown"))].append(row)
        for (agent, name), items in grouped.items():
            args = sum(i["argument_chars"] for i in items if i.get("argument_chars") is not None) if any(i.get("argument_chars") is not None for i in items) else None
            results = sum(i["result_chars"] for i in items if i.get("result_chars") is not None) if any(i.get("result_chars") is not None for i in items) else None
            ranked["skills" if kind == "skill" else "tools"].append({"agent": agent, "name": name, "calls": len(items),
                "argument_chars": args, "result_chars": results, "estimated_tokens": round(((args or 0) + (results or 0)) / 4) if args is not None or results is not None else None,
                "quality": "estimated visible content; not causal cost"})
    for values in ranked.values():
        values.sort(key=lambda r: r["estimated_tokens"] or 0, reverse=True)
    contexts_by_session = {}
    for context in data["contexts"]:
        if not in_scope(context, "observed_at"):
            continue
        key = (context.get("agent"), context.get("session_id"))
        prior = contexts_by_session.get(key)
        if prior is None or (context.get("observed_at") or "") >= (prior.get("observed_at") or ""):
            contexts_by_session[key] = context
    contexts = list(contexts_by_session.values())
    quotas = [q for q in data["quotas"] if in_scope(q, "observed_at", account_scope=True)]
    summary = stats(rows)
    summary["unverified_model_requests"] = sum(r.get("request_count") if r.get("request_count") is not None else 1
                                               for r in rows if attribution_rank(r) == 0)
    # A selected source that could not be read is a gap; an empty one (no_eligible_sources) is not.
    gap_codes = {"fork_baseline_unknown", "native_legacy_overlap_unresolved", "source_unreadable",
                 "malformed_or_partial_line", "malformed_json", "explicit_export_required",
                 "missing_request_identity", "unsupported_usage_schema",
                 "unsupported_sql_schema", "grok_turn_usage_unavailable", "counter_reset_unknown_baseline",
                 "sql_jsonl_discrepancy", "sql_snapshot_unreadable", "missing_request_id_message_fallback",
                 "grok_aggregate_unavailable_without_turns", "agy_aggregate_time_unavailable"}
    summary["accounting_gap_observations"] = sum(w.get("code") in gap_codes for w in selected_warnings)
    if summary["accounting_gap_observations"]:
        summary["count_quality"] = "known lower bound"
    summary["sessions"] = len({(s.get("agent"), s.get("session_id")) for s in data["sessions"]
                               if (not session_id or s.get("session_id") == session_id or s.get("parent_session_id") == session_id)
                               and (not start or not s.get("end") or s["end"] >= start)
                               and (not end or not s.get("start") or s["start"] < end)} | {(r.get("agent"), r.get("session_id")) for r in rows})
    comparison = None
    if compare_since or compare_until:
        a, b = _bound(compare_since, tz), _bound(compare_until, tz)
        previous = stats([r for r in all_rows if r.get("timestamp") and (not a or r["timestamp"] >= a)
                          and (not b or r["timestamp"] < b) and session_scope(r)])
        comparison = {"previous": previous, "since": a, "until": b,
                      "token_delta_percent": (100 * (summary["total_tokens"] / previous["total_tokens"] - 1)
                                              if previous["total_tokens"] else None),
                      "cost_delta_percent": (100 * (summary["cost_lower_usd"] / previous["cost_lower_usd"] - 1)
                                             if previous["cost_lower_usd"] else None)}
    insights = []
    if summary["unverified_model_requests"]:
        insights.append({"title": "Confirm historical model routes", "evidence": f'{summary["unverified_model_requests"]} requests use reported model labels without confirmed provider attribution.',
                         "action": "If GLM or another proxy served an Opus-labeled session, supply a confirmed attribution map before interpreting its API-equivalent cost."})
    if ranked["tools"]:
        top = ranked["tools"][0]
        insights.append({"title": "Largest observed tool content", "evidence": f'{top["name"]}: {top["result_chars"] if top["result_chars"] is not None else "unknown"} result characters across {top["calls"]} calls.',
                         "action": "Narrow repeated reads or bound result sizes. This measures visible text, not the tool's full causal token cost."})
    if summary["unpriced_requests"]:
        insights.append({"title": "Pricing coverage is incomplete", "evidence": f'{summary["unpriced_requests"]} requests have unknown models or billing dimensions.',
                         "action": "Supply a verified rate card or retain these requests as unpriced; the displayed cost covers only priced work."})
    if any(c.get("compactions", 0) for c in contexts):
        insights.append({"title": "Compaction affects context interpretation", "evidence": f'{sum(c.get("compactions", 0) for c in contexts)} recorded compactions in selected sessions.',
                         "action": "Use the latest measured request and retained-history estimates; lifetime usage is a separate total."})
    if any(c.get("unattributed_tokens") is not None and c["unattributed_tokens"] < 0 for c in contexts):
        insights.append({"title": "Visible estimate exceeds its measured anchor", "evidence": "At least one context estimate has a negative residual.",
                         "action": "Treat composition as uncertain: pruning, serialization and the heuristic can differ. Categories were not rescaled."})
    generated = timestamp(now) or timestamp(datetime.now(timezone.utc).isoformat())
    attribution = _groups(rows, lambda r: " | ".join((str(r.get("agent")), str(r.get("provider") or "unverified provider"),
                          str(r.get("reported_model") or r.get("model") or "unknown"),
                          str(r.get("model") or "unknown"), str(r.get("model_attribution") or "reported"))))
    for group in attribution:
        group["agent"], group["provider"], group["reported_model"], group["model"], group["model_attribution"] = group["label"].split(" | ")
    rolling = {}
    for label, hours in (("five_hour", 5), ("seven_day", 168)):
        bound = timestamp((datetime.fromisoformat(generated.replace("Z", "+00:00")) - timedelta(hours=hours)).isoformat())
        rolling[label] = stats([r for r in all_rows if r.get("timestamp") and bound <= r["timestamp"] <= generated
                                and session_scope(r)])
    session_groups = _groups(rows, lambda r: str(r.get("agent")) + ":" + str(r.get("session_id")))
    for group in session_groups:
        items = [r for r in rows if str(r.get("agent")) + ":" + str(r.get("session_id")) == group["label"]]
        group["agent"] = items[0].get("agent")
        models = {r.get("model") or "unknown" for r in items}
        group["model"] = next(iter(models)) if len(models) == 1 else "mixed models"
    report = {"schema_version": 1, "generated_at": generated, "mode": "session" if session_id else "usage",
              "scope": {"since": start, "until": end, "timezone": tz_name, "session_id": session_id, "share": share},
              "summary": summary, "requests": rows, "daily": _groups(rows, lambda r: date_key(r, 10)),
              "monthly": _groups(rows, lambda r: date_key(r, 7)), "models": _groups(rows, lambda r: r.get("model") or "unknown"),
              "sessions": session_groups,
              "tasks": _groups(rows, lambda r: r["task"]), **ranked, "contexts": contexts, "quotas": quotas,
              "attribution": attribution,
              "quota_estimates": quota_analysis(quotas, all_rows, complete_coverage), "local_rolling_usage": rolling,
              "coverage": [s for s in data["sources"] if not session_id or s.get("id") in selected_source_ids], "warnings": selected_warnings, "insights": insights,
              "comparison": comparison, "undated_requests_excluded": sum(not r.get("timestamp") for r in all_rows if session_scope(r)) if start or end else 0,
              "pricing": {**{key: card.get(key) for key in ("version", "verified_at", "sources", "historical_policy")},
                          "currency": card.get("currency"),
                          "rates": {model: deepcopy(card["models"][model]) for model in
                                    {card.get("aliases", {}).get(r.get("model"), r.get("model")) for r in all_rows}
                                    if model in card["models"]},
                          "aliases": {key: value for key, value in card.get("aliases", {}).items()
                                      if any(r.get("model") == key for r in all_rows)}},
              "methodology": ["Historical totals include measured/reconstructed request counters only; no character estimates.",
                              "Accounting-gap warnings cover selected source history and can extend outside the report period.",
                              "Context categories estimate visible text; hidden schemas, prompts and multimodal content are unknown.",
                              "Local rolling usage is distinct from provider-defined quotas and can omit other devices/cloud work.",
                              "API-equivalent cost uses per-request reference rates, excludes unrecorded tool fees and is not a subscription bill."]}
    report["methodology"].append("Harness labels can hide proxy routes. Reported/unverified models are reference comparisons; use an explicit attribution map for GLM or other routed sessions. Known provider mismatches are unpriced.")
    return pseudonymize(report) if share else report


def pseudonymize(report: dict[str, Any]) -> dict[str, Any]:
    report = deepcopy(report)
    sensitive = {"id", "source_id", "session_id", "parent_session_id", "account", "device", "name", "bucket", "task", "provider"}
    names: dict[str, str] = {}
    salt = secrets.token_hex(24)
    public_categories = {"instructions", "skill_catalog", "loaded_skills", "tool_schemas", "user_messages",
                         "assistant_messages", "tool_results", "tool_arguments", "environment",
                         "compaction_summary", "plugin_instructions"}
    def visit(value, parent=""):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "name" and parent == "categories" and item in public_categories:
                    continue
                if key in sensitive and isinstance(item, str):
                    value[key] = names.setdefault(item, "item-" + digest(salt, item)[:10])
                elif key == "label" and parent in ("sessions", "tasks", "attribution") and isinstance(item, str):
                    value[key] = names.setdefault(item, "item-" + digest(salt, item)[:10])
                else:
                    visit(item, key)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent)
    visit(report)
    # Free-form insight strings are generated from identifiers; remove them for share exports.
    report["insights"] = [{"title": "Share mode", "evidence": "Identifiers were pseudonymized.",
                           "action": "Inspect the local report for named recommendations."}]
    return report
