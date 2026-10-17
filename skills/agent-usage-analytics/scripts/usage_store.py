"""Validated numeric imports and an optional, content-free SQLite ledger."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any

from usage_common import LISTS, dataset, digest, number, safe_name, timestamp
from usage_accounting import merge

FIELDS = {
    "usage": "id agent session_id parent_session_id model timestamp source_id origin device account input_tokens cache_read_tokens cache_write_tokens cache_write_5m_tokens cache_write_1h_tokens output_tokens reasoning_tokens request_count unit quality speed inference_geo service_tier cache_write_reported model_inferred accounting_mode web_search_requests task cumulative_observed_at cumulative_input_tokens cumulative_output_tokens cumulative_cache_read_tokens cumulative_cache_write_tokens cumulative_reasoning_tokens",
    "contexts": "id agent session_id parent_session_id observed_at used_tokens window_tokens basis provider_percent computed_percent baseline_reserved_tokens compactions model quality visible_estimated_tokens unattributed_tokens estimation_method retention_status capacity_basis source_id origin device post_compaction_pending_turn",
    "tools": "id agent session_id parent_session_id timestamp source_id origin device name kind argument_chars result_chars quality detection",
    "quotas": "id agent account bucket window_minutes resets_at used_percent observed_at source_id device origin model speed",
    "sessions": "id agent session_id parent_session_id device origin start end compactions source_id",
    "sources": "id agent session_id device origin contract files_seen files_parsed rows_seen malformed_rows schema_fingerprint",
    "warnings": "id code source_id session_id line",
}
NUMERIC = set("input_tokens cache_read_tokens cache_write_tokens cache_write_5m_tokens cache_write_1h_tokens output_tokens reasoning_tokens request_count web_search_requests used_tokens window_tokens provider_percent computed_percent baseline_reserved_tokens compactions visible_estimated_tokens window_minutes used_percent argument_chars result_chars files_seen files_parsed rows_seen malformed_rows line".split())
NUMERIC.update("cumulative_" + key for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"))
RECONCILIATION_FIELDS = "native_total_input_tokens native_total_output_tokens legacy_total_input_tokens legacy_total_output_tokens"
FIELDS["usage"] += " " + RECONCILIATION_FIELDS
FIELDS["usage"] += " provider reported_model model_attribution"
FIELDS["contexts"] += " provider reported_model model_attribution"
NUMERIC.update(RECONCILIATION_FIELDS.split())
TIMES = {"timestamp", "observed_at", "resets_at", "start", "end", "cumulative_observed_at"}
BOOLEANS = {"cache_write_reported", "model_inferred", "post_compaction_pending_turn"}


def normalize_import(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Import requires a normalized schema_version 1 dataset")
    result = dataset()
    for kind in LISTS:
        rows = value.get(kind, [])
        if not isinstance(rows, list):
            raise ValueError("Dataset observation groups must be lists")
        for record in rows:
            if not isinstance(record, dict):
                raise ValueError("Each observation must be an object")
            row = {}
            for key in FIELDS[kind].split():
                if key not in record:
                    continue
                item = record[key]
                if key in TIMES:
                    row[key] = timestamp(item)
                    if item is not None and row[key] is None:
                        raise ValueError("Invalid or timezone-naive observation timestamp")
                elif key in NUMERIC:
                    row[key] = number(item)
                    if item is not None and row[key] is None:
                        raise ValueError("Token counts and percentages must be finite and nonnegative")
                elif key == "unattributed_tokens":
                    if item is not None and (not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item)):
                        raise ValueError("Invalid context residual")
                    row[key] = item
                elif key in BOOLEANS:
                    if not isinstance(item, bool):
                        raise ValueError("Invalid observation boolean")
                    row[key] = item
                elif key == "estimation_method" and isinstance(item, str) and re.fullmatch(
                        r"visible characters / (?:4\.0|3\.1); range characters / 6 to / 2", item):
                    row[key] = item
                elif item is None:
                    row[key] = None
                else:
                    row[key] = safe_name(item)
            if kind == "usage":
                if not row.get("agent") or not row.get("session_id"):
                    raise ValueError("Usage needs agent and session identity")
                for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"):
                    row.setdefault(key, None)
                if row.get("request_count") is not None and row["request_count"] < 0:
                    raise ValueError("request_count must be nonnegative")
                row.setdefault("request_count", 1)
            if kind == "contexts":
                categories = record.get("categories", [])
                if not isinstance(categories, list):
                    raise ValueError("Context categories must be a list")
                row["categories"] = []
                for category in categories:
                    if not isinstance(category, dict):
                        raise ValueError("Context category must be an object")
                    row["categories"].append({"name": safe_name(category.get("name")), "quality": category.get("quality") if category.get("quality") in ("reported", "reconstructed", "estimated", "unavailable") else "estimated",
                        **{k: number(category.get(k)) for k in ("characters", "estimated_tokens", "lower_tokens", "upper_tokens")}})
            if kind == "quotas" and (row.get("used_percent") is not None and row["used_percent"] > 100):
                raise ValueError("Quota percentage must be between zero and 100")
            if kind == "warnings" and not re.fullmatch(r"[a-z0-9_]{1,100}", str(row.get("code", ""))):
                row["code"] = "import_warning"
            row.setdefault("id", digest(kind, row))
            row.setdefault("origin", "imported") if kind not in ("warnings",) else None
            result[kind].append(row)
    return merge(result)


class Ledger:
    """Never initialize/migrate an unrelated database passed accidentally."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10)
        tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and tables != {"usage_analytics_meta", "usage_analytics_records"}:
            self.connection.close()
            raise ValueError("Refusing unrelated database; choose a new analytics ledger path")
        self.connection.execute("PRAGMA busy_timeout=10000")
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS usage_analytics_meta (version INTEGER NOT NULL)")
            if not self.connection.execute("SELECT version FROM usage_analytics_meta").fetchone():
                self.connection.execute("INSERT INTO usage_analytics_meta VALUES (1)")
            version = self.connection.execute("SELECT version FROM usage_analytics_meta").fetchone()[0]
            if version != 1:
                self.connection.close()
                raise ValueError("Unsupported analytics ledger version")
            self.connection.execute("CREATE TABLE IF NOT EXISTS usage_analytics_records (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(kind,id))")

    def add(self, value: dict[str, Any]) -> None:
        value = normalize_import(value)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            refreshed = {r["id"] for r in value["sources"] if r.get("files_parsed") == 1}
            if refreshed:
                for key, raw in self.connection.execute("SELECT id,data FROM usage_analytics_records WHERE kind='warnings'").fetchall():
                    if json.loads(raw).get("source_id") in refreshed:
                        self.connection.execute("DELETE FROM usage_analytics_records WHERE kind='warnings' AND id=?", (key,))
            for kind in LISTS:
                for row in value[kind]:
                    previous = self.connection.execute("SELECT data FROM usage_analytics_records WHERE kind=? AND id=?", (kind, row["id"])).fetchone()
                    if previous:
                        older = dataset()
                        newer = dataset()
                        older[kind] = [json.loads(previous[0])]
                        newer[kind] = [row]
                        row = merge(older, newer)[kind][0]
                    self.connection.execute("INSERT INTO usage_analytics_records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
                                            (kind, row["id"], json.dumps(row, allow_nan=False)))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def read(self) -> dict[str, Any]:
        result = dataset()
        for kind, raw in self.connection.execute("SELECT kind,data FROM usage_analytics_records ORDER BY kind,id"):
            if kind in result:
                result[kind].append(json.loads(raw))
        return normalize_import(result)

    def close(self) -> None:
        self.connection.close()
