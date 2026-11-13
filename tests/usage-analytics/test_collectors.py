"""Synthetic, hand-counted adapter regressions. No real agent data is read."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "agent-usage-analytics" / "scripts"))
from usage_collectors import collect

T0 = "2026-10-17T10:00:00Z"
T1 = "2026-10-17T10:01:00Z"
T2 = "2026-10-17T10:02:00Z"
T3 = "2026-10-17T10:03:00Z"
CANARY = "PRIVATE_CANARY_do_not_export_93261"


def cx_counts(inp, out=10, cache=0, write=0, reasoning=0):
    return {"input_tokens": inp, "output_tokens": out, "cached_input_tokens": cache,
            "cache_write_tokens": write, "reasoning_output_tokens": reasoning}


def meta(sid="child", **extra):
    return {"type": "session_meta", "timestamp": T0, "payload": {"id": sid, **extra}}


def turn(tid="t1", model="gpt-5", **extra):
    return {"type": "turn_context", "timestamp": T0,
            "payload": {"turn_id": tid, "model": model, **extra}}


def native(rid="r1", usage=None, at=T1, **extra):
    return {"type": "token_usage_record", "timestamp": at, "payload": {
        "response_id": rid, "thread_id": "child", "turn_id": "t1",
        "usage": usage or cx_counts(100), **extra}}


def snapshot(total, last=None, at=T1, **extra):
    return {"type": "event_msg", "timestamp": at, "payload": {"type": "token_count",
        "info": {"total_token_usage": total, "last_token_usage": last or total,
                 "model_context_window": 1000}, **extra}}


def compact(at=T2, **extra):
    return {"type": "compacted", "timestamp": at, "payload": extra}


def claude(mid="m1", rid="r1", inp=10, out=20, at=T1, **extra):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": 30,
             "cache_creation_input_tokens": 40}
    usage.update(extra.pop("usage", {}))
    return {"type": "assistant", "sessionId": "c1", "timestamp": at, "requestId": rid,
        "message": {"id": mid, "model": "claude-sonnet-4-5", "role": "assistant",
                    "usage": usage, "content": [{"type": "text", "text": CANARY}]}, **extra}


def copilot_event(sid="p1", rid="r1", inp=100, at=T1):
    return [{"type": "session.start", "timestamp": T0, "data": {"sessionId": sid}},
        {"type": "model.model_call_success", "timestamp": at, "data": {
            "modelCall": {"model": "gpt-5", "request_id": rid}, "responseUsage": {
                "prompt_tokens": inp, "completion_tokens": 20, "details": {
                    "cached_tokens": 30, "cache_creation_tokens": 10, "reasoning_tokens": 5}}}}]


class CollectorTests(unittest.TestCase):
    def test_current_codex_native_cache_write_and_thread_total_names(self):
        first = cx_counts(100, 10)
        current = {"input_tokens": 200, "output_tokens": 20, "cached_input_tokens": 100,
                   "cache_write_input_tokens": 50, "reasoning_output_tokens": 5}
        total = {"input_tokens": 300, "output_tokens": 30, "cached_input_tokens": 100,
                 "cache_write_input_tokens": 50, "reasoning_output_tokens": 5}
        path = self.write("native.jsonl", [meta(), turn(), snapshot(first),
            native("r2", current, at=T2, thread_token_usage=total)])
        result = collect("codex", path)
        self.assertEqual(sum(r["input_tokens"] for r in result["usage"]), 300)
        self.assertEqual(result["usage"][0]["cache_write_tokens"], 50)
        self.assertTrue(result["usage"][0]["cache_write_reported"])

    def test_copilot_prompt_and_completion_details_match_observed_schema(self):
        rows = copilot_event()
        rows[1]["data"]["responseUsage"] = {"prompt_tokens": 100, "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 30, "cache_creation_tokens": 10},
            "completion_tokens_details": {"reasoning_tokens": 5}}
        result = collect("copilot", self.write("session-state/p1/events.jsonl", rows))
        row = result["usage"][0]
        self.assertEqual((row["cache_read_tokens"], row["cache_write_tokens"], row["reasoning_tokens"]), (30, 10, 5))

    def test_nested_grok_discovery_and_ended_at(self):
        self.json("sessions/encoded-project/session-1/usage.json", {"sessionId": "session-1", "turns": [
            {"turnNumber": 1, "endedAt": T1, "modelUsage": {"grok-sample": {"inputTokens": 100,
             "outputTokens": 10, "cachedReadTokens": 50, "cacheCreationTokens": 0, "reasoningTokens": 2,
             "totalTokens": 110, "modelCalls": 1}}}]})
        result = collect("grok", self.root)
        self.assertEqual(len(result["usage"]), 1)
        self.assertEqual(result["usage"][0]["timestamp"], "2026-10-17T10:01:00.000Z")

    def test_agy_documented_nested_event_envelope(self):
        rows = [{"event": "step_update", "step_update": {"conversation_id": "agy-1", "state": "DONE",
                  "usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 0}}},
                {"event": "result", "result": {"conversation_id": "agy-1", "num_turns": 1,
                  "usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 0}}},
                {"event": "result", "result": {"conversation_id": "agy-1", "num_turns": 2,
                  "usage": {"input_tokens": 150, "output_tokens": 20, "cache_read_tokens": 0}}}]
        result = collect("agy", self.write("agy.jsonl", rows))
        self.assertEqual(len(result["usage"]), 1)
        self.assertEqual(result["usage"][0]["input_tokens"], 150)
        self.assertEqual(result["usage"][0]["session_id"], "agy-1")

    def test_selected_claude_parent_includes_subagent_files(self):
        self.write("projects/project/c1.jsonl", [claude()])
        self.write("projects/project/c1/subagents/agent-sub.jsonl", [claude(mid="child", rid="child")])
        result = collect("claude", self.root, session="c1")
        self.assertEqual(len(result["usage"]), 2)
        self.assertEqual({r.get("parent_session_id") for r in result["usage"]}, {None, "c1"})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, rows, bom=False, partial=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\r\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\r\n"
        if partial:
            text += '{"private":'
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode())
        return path

    def json(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return path

    def codes(self, data):
        return {row["code"] for row in data["warnings"]}

    def sql(self, name="session-store.db", missing=False, wal=False):
        path = self.root / name
        conn = sqlite3.connect(path)
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA wal_autocheckpoint=0")
        if missing:
            conn.execute("CREATE TABLE assistant_usage_events (id TEXT, session_id TEXT)")
        else:
            conn.execute("CREATE TABLE assistant_usage_events (id TEXT, session_id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER, created_at TEXT)")
        conn.commit()
        return path, conn

    def sql_insert(self, conn, key="s1", sid="p1", inp=100):
        conn.execute("INSERT INTO assistant_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (key, sid, "gpt-5", inp, 20, 30, 10, 5, T1))
        conn.commit()

    def test_codex_native_identity_models_timestamp_and_duplicates(self):
        rows = [meta(), turn(), native(), turn("t2", "gpt-6"),
                native("r2", cx_counts(200, 30, 50, 10, 7), at=T2, turn_id="t2")]
        self.write("sessions/2026/rollout-child.jsonl", rows)
        self.write("archived_sessions/rollout-child-copy.jsonl", rows)
        result = collect("codex", self.root)
        self.assertEqual(len(result["usage"]), 2)
        self.assertEqual(sum(r["input_tokens"] for r in result["usage"]), 300)
        record = result["usage"][1]
        self.assertEqual(record["model"], "gpt-6")
        self.assertFalse(record["model_inferred"])
        self.assertEqual(record["timestamp"], "2026-10-17T10:02:00.000Z")
        self.assertEqual(record["output_tokens"], 30)
        self.assertEqual(record["reasoning_tokens"], 7)
        self.assertEqual(record["cache_write_tokens"], 10)
        self.assertEqual([r["id"] for r in result["usage"]],
                         [r["id"] for r in collect("codex", self.root)["usage"]])

    def test_codex_native_model_forward_join_and_inferred_fallback(self):
        path = self.write("native.jsonl", [meta(), turn(), native(turn_id="later"),
                                          turn("later", "gpt-6"), native("r2", turn_id="missing")])
        data = collect("codex", path)
        self.assertEqual(data["usage"][0]["model"], "gpt-6")
        self.assertFalse(data["usage"][0]["model_inferred"])
        self.assertTrue(data["usage"][1]["model_inferred"])

    def test_codex_legacy_duplicates_and_cumulative_delta(self):
        first = cx_counts(100, 10, 20)
        path = self.write("old.jsonl", [meta(), turn(), snapshot(first), snapshot(first, at=T2),
            snapshot(cx_counts(250, 30, 50), cx_counts(150, 20, 30), at=T3)])
        data = collect("codex", path)
        self.assertEqual([r["input_tokens"] for r in data["usage"]], [100, 150])
        self.assertEqual([r["cache_read_tokens"] for r in data["usage"]], [20, 30])
        self.assertEqual(data["contexts"][0]["used_tokens"], 170)
        self.assertEqual(data["contexts"][0]["provider_percent"], None)

    def test_codex_legacy_rotated_sources_do_not_double_count(self):
        from usage_accounting import merge
        first = self.write("a/run1.jsonl", [meta(), turn(), snapshot(cx_counts(100, 10, 20), at=T1)])
        rotated = self.write("b/run2.jsonl", [meta(), turn(), snapshot(cx_counts(100, 10, 20), at=T2),
            snapshot(cx_counts(150, 15, 30), cx_counts(50, 5, 10), at=T3)])
        later_only = self.write("c/run3.jsonl", [meta(), turn(), snapshot(cx_counts(150, 15, 30), at=T3)])
        for other in (rotated, later_only):
            rows = merge(collect("codex", first), collect("codex", other))["usage"]
            self.assertEqual(sum(r["input_tokens"] for r in rows), 150, other.name)
            self.assertEqual(sum(r["cache_read_tokens"] for r in rows), 30, other.name)
            self.assertEqual(sum(r["output_tokens"] for r in rows), 15, other.name)
        merged = merge(collect("codex", first), collect("codex", rotated))
        self.assertIn("legacy_cross_source_reconciled", self.codes(merged))

    def test_codex_legacy_reconciliation_survives_the_ledger(self):
        from usage_store import Ledger
        first = self.write("a/run1.jsonl", [meta(), turn(), snapshot(cx_counts(100, 10, 20, 4, 2), at=T1)])
        later_only = self.write("c/run3.jsonl", [meta(), turn(), snapshot(cx_counts(150, 15, 30, 6, 3), at=T3)])
        store = self.root / "history.sqlite"
        for path in (first, later_only):
            ledger = Ledger(store)
            try:
                ledger.add(collect("codex", path))
            finally:
                ledger.close()
        ledger = Ledger(store)
        try:
            rows = ledger.read()["usage"]
        finally:
            ledger.close()
        self.assertEqual(sum(r["input_tokens"] for r in rows), 150)
        self.assertEqual(sum(r["cache_read_tokens"] for r in rows), 30, "cache totals must be stored to re-derive deltas")
        self.assertEqual(sum(r["cache_write_tokens"] for r in rows), 6)
        self.assertEqual(sum(r["reasoning_tokens"] for r in rows), 3)

    def test_codex_mixed_reconciled_transition(self):
        path = self.write("mixed.jsonl", [meta(), turn(), snapshot(cx_counts(100, 10)),
            native(usage=cx_counts(200, 20), at=T2, thread_total=cx_counts(300, 30)),
            snapshot(cx_counts(300, 30), cx_counts(200, 20), at=T3)])
        data = collect("codex", path)
        self.assertEqual(sum(r["input_tokens"] for r in data["usage"]), 300)
        self.assertEqual(len(data["usage"]), 2)
        self.assertNotIn("native_legacy_overlap_unresolved", self.codes(data))

    def test_codex_mixed_unknown_transition_excludes_legacy(self):
        path = self.write("mixed.jsonl", [meta(), turn(), snapshot(cx_counts(100)), native()])
        data = collect("codex", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertIn("native_legacy_overlap_unresolved", self.codes(data))

    def test_codex_last_metadata_owns_replayed_file(self):
        path = self.write("replay.jsonl", [meta("parent"), snapshot(cx_counts(100)),
            meta("child", forked_from_id="parent"), turn(), snapshot(cx_counts(100)),
            snapshot(cx_counts(150, 20), cx_counts(50, 10), at=T2)])
        data = collect("codex", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(data["usage"][0]["input_tokens"], 50)
        self.assertEqual(data["usage"][0]["session_id"], "child")
        self.assertEqual(data["sessions"][0]["parent_session_id"], "parent")

    def test_codex_unknown_fork_excludes_unattributable_snapshots(self):
        path = self.write("fork.jsonl", [meta(forked_from_id="parent"), snapshot(cx_counts(500)),
            snapshot(cx_counts(550, 20), cx_counts(50, 10), at=T2)])
        data = collect("codex", path)
        self.assertEqual(data["usage"], [])
        self.assertIn("fork_baseline_unknown", self.codes(data))

    def test_codex_parent_payload_matching_excludes_replay_after_child_metadata(self):
        self.write("sessions/parent.jsonl", [meta("parent"), snapshot(cx_counts(100)), snapshot(cx_counts(500), at=T2)])
        child = self.write("sessions/child.jsonl", [meta(forked_from_id="parent"), snapshot(cx_counts(100)),
            snapshot(cx_counts(500), at=T2), snapshot(cx_counts(550, 20), cx_counts(50, 10), at=T3)])
        data = collect("codex", child)
        self.assertEqual([r["input_tokens"] for r in data["usage"]], [50])
        self.assertIn("inherited_legacy_snapshot_excluded", self.codes(data))

    def test_codex_reset_requires_fresh_equals_total(self):
        path = self.write("resets.jsonl", [meta(), snapshot(cx_counts(100)),
            snapshot(cx_counts(20, 2), at=T2),
            snapshot(cx_counts(10, 1), cx_counts(5, 1), at=T3)])
        data = collect("codex", path)
        self.assertEqual([r["input_tokens"] for r in data["usage"]], [100, 20])
        self.assertIn("counter_reset_reconciled", self.codes(data))
        self.assertIn("counter_reset_unknown_baseline", self.codes(data))

    def test_codex_compaction_replaces_inventory_and_invalidates_anchor(self):
        item = {"type": "response_item", "timestamp": T0, "payload": {
            "type": "message", "role": "user", "content": "x" * 100}}
        path = self.write("compact.jsonl", [meta(), turn(), item, native(), compact()])
        ctx = collect("codex", path)["contexts"][0]
        self.assertIsNone(ctx["used_tokens"])
        self.assertEqual(ctx["categories"], [])
        self.assertEqual(ctx["retention_status"], "unknown-after-compaction")
        replacement = [{"type": "message", "role": "user", "content": "short"}]
        path = self.write("replace.jsonl", [meta(), turn(), item, native(),
            compact(replacement_history=replacement), native("r2", at=T3)])
        ctx = collect("codex", path)["contexts"][0]
        self.assertEqual(ctx["categories"][0]["characters"], 5)
        self.assertEqual(ctx["used_tokens"], 110)
        self.assertEqual(ctx["compactions"], 1)

    def test_codex_base_instructions_not_counted_twice(self):
        path = self.write("base.jsonl", [meta(base_instructions={"text": "same"}), turn(),
            {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                   "content": [{"type": "input_text", "text": "same"}]}}, native()])
        self.assertEqual(collect("codex", path)["contexts"][0]["categories"][0]["characters"], 4)

    def test_codex_quota_survives_identical_snapshots(self):
        limit = {"primary": {"used_percent": 20, "window_minutes": 300, "resets_at": 1792231200}}
        path = self.write("quota.jsonl", [meta(), snapshot(cx_counts(100), rate_limits=limit),
            snapshot(cx_counts(100), at=T2, rate_limits=limit)])
        data = collect("codex", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(len(data["quotas"]), 2)
        self.assertEqual(data["quotas"][0]["window_minutes"], 300)
        self.assertNotEqual(data["quotas"][0]["id"], data["quotas"][1]["id"])

    def test_codex_tool_result_join_and_skill_detection(self):
        items = [{"type": "function_call", "call_id": "a", "name": "read_file",
                  "arguments": {"path": "/generic/skills/example/SKILL.md"}},
                 {"type": "function_call", "call_id": "b", "name": "shell", "arguments": CANARY},
                 {"type": "function_call_output", "call_id": "b", "output": "bb"},
                 {"type": "function_call_output", "call_id": "a", "output": "aaa"},
                 {"type": "function_call", "call_id": "s", "name": "Skill", "arguments": '{"skill":"example"}'}]
        path = self.write("tools.jsonl", [meta(), *({"type": "response_item", "payload": p} for p in items), native()])
        data = collect("codex", path)
        tools = {r["name"]: r for r in data["tools"] if r["kind"] == "tool"}
        self.assertEqual(tools["read_file"]["result_chars"], 3)
        self.assertEqual(tools["shell"]["result_chars"], 2)
        self.assertEqual(len([r for r in data["tools"] if r["kind"] == "skill"]), 2)
        self.assertNotIn(CANARY, json.dumps(data))

    def test_claude_pair_key_maxima_and_global_deduplication(self):
        rows = [claude(out=3), claude(out=20), claude(rid="r2", inp=50, out=5)]
        self.write("projects/p/c1.jsonl", rows)
        self.write("projects/p/copy.jsonl", rows)
        data = collect("claude", self.root)
        self.assertEqual(len(data["usage"]), 2)
        self.assertEqual(sum(r["input_tokens"] for r in data["usage"]), 200)
        self.assertEqual(sum(r["output_tokens"] for r in data["usage"]), 25)
        self.assertIsNone(data["contexts"][0]["window_tokens"])
        self.assertNotIn(CANARY, json.dumps(data))

    def test_claude_cache_ttl_and_server_search_requests(self):
        path = self.write("c.jsonl", [claude(usage={"cache_creation": {
            "ephemeral_5m_input_tokens": 15, "ephemeral_1h_input_tokens": 25},
            "server_tool_use": {"web_search_requests": 2}}), claude(mid="m2", rid="r2")])
        rows = collect("claude", path)["usage"]
        self.assertEqual(rows[0]["cache_write_5m_tokens"], 15)
        self.assertEqual(rows[0]["cache_write_1h_tokens"], 25)
        self.assertEqual(rows[0]["web_search_requests"], 2)
        self.assertIsNone(rows[1]["cache_write_5m_tokens"])

    def test_claude_synthetic_and_subagent_summary_ignored(self):
        synth = claude()
        synth["message"]["model"] = "<synthetic>"
        path = self.write("projects/p/c1/subagents/agent-a.jsonl", [claude(), synth,
            {"type": "subagent_completed", "total_tokens": 99999}])
        data = collect("claude", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(data["usage"][0]["session_id"], "agent-a")
        self.assertEqual(data["sessions"][0]["parent_session_id"], "c1")

    def test_claude_postcompaction_unknown_without_request(self):
        path = self.write("compact.jsonl", [claude(), {"type": "system", "sessionId": "c1",
            "timestamp": T2, "subtype": "compact_boundary"}])
        ctx = collect("claude", path)["contexts"][0]
        self.assertIsNone(ctx["used_tokens"])
        self.assertEqual(ctx["compactions"], 1)

    def test_copilot_modern_events_and_checkpoint_not_additive(self):
        path = self.write("events.jsonl", copilot_event() + [{"type": "session.usage_checkpoint",
            "data": {"input_tokens": 99999}}])
        data = collect("copilot", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(data["usage"][0]["input_tokens"], 100)
        self.assertEqual(data["usage"][0]["cache_read_tokens"], 30)
        self.assertIn("checkpoint_crosscheck_only", self.codes(data))
        self.assertIn("checkpoint_exceeds_requests", self.codes(data), "99999 checkpoint vs 100 collected")

    def test_copilot_matching_checkpoint_is_not_a_gap(self):
        path = self.write("events.jsonl", copilot_event() + [{"type": "session.usage_checkpoint",
            "data": {"prompt_tokens": 100, "completion_tokens": 20}}])
        self.assertNotIn("checkpoint_exceeds_requests", self.codes(collect("copilot", path)))

    def test_copilot_sql_jsonl_no_double_count_and_orphan_coverage(self):
        self.write("session-state/p1/events.jsonl", copilot_event())
        _, conn = self.sql()
        self.sql_insert(conn)
        self.sql_insert(conn, "s2", "sql-only", 200)
        conn.close()
        data = collect("copilot", self.root)
        self.assertEqual(len(data["usage"]), 2)
        self.assertEqual(sum(r["input_tokens"] for r in data["usage"]), 300)
        self.assertIn("sql_jsonl_alternative_excluded", self.codes(data))
        self.assertIn("sql_only_session_coverage", self.codes(data))

    def test_copilot_sql_jsonl_discrepancy_numeric_evidence(self):
        self.write("session-state/p1/events.jsonl", copilot_event(inp=50))
        _, conn = self.sql()
        self.sql_insert(conn)
        conn.close()
        data = collect("copilot", self.root)
        self.assertEqual(data["usage"][0]["input_tokens"], 100)
        self.assertIn("sql_jsonl_discrepancy", self.codes(data))
        evidence = next(r for r in data["warnings"] if r["code"] == "sql_jsonl_discrepancy")
        self.assertEqual(evidence["sql_rows"], 1)
        self.assertEqual(evidence["jsonl_rows"], 1)

    def test_copilot_wal_snapshot_is_current_and_read_only(self):
        path, conn = self.sql(wal=True)
        self.sql_insert(conn, inp=321)
        self.assertTrue(Path(str(path) + "-wal").is_file())
        before = path.read_bytes()
        data = collect("copilot", path)
        self.assertEqual(data["usage"][0]["input_tokens"], 321)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(conn.execute("SELECT count(*) FROM assistant_usage_events").fetchone()[0], 1)
        conn.close()

    def test_copilot_missing_schema_warns(self):
        path, conn = self.sql(missing=True)
        conn.close()
        data = collect("copilot", path)
        self.assertEqual(data["usage"], [])
        self.assertIn("unsupported_sql_schema", self.codes(data))

    def test_copilot_session_filter(self):
        self.write("session-state/p1/events.jsonl", copilot_event())
        _, conn = self.sql()
        self.sql_insert(conn)
        self.sql_insert(conn, "s2", "sql-only", 200)
        conn.close()
        data = collect("copilot", self.root, session="sql-only")
        self.assertEqual([r["session_id"] for r in data["usage"]], ["sql-only"])

    def test_grok_turns_are_inclusive_and_summary_is_not_added(self):
        self.json("sessions/g1/usage.json", {"sessionId": "g1", "updatedAt": T2,
            "inputTokens": 999999, "turns": [{"turnId": "t1", "timestamp": T1,
                "modelUsage": {"grok-4": {"inputTokens": 100, "outputTokens": 20,
                    "cachedReadTokens": 30, "cacheCreationTokens": 10,
                    "reasoningTokens": 5, "totalTokens": 120, "modelCalls": 2}}}]})
        self.json("sessions/g1/signals.json", {"sessionId": "g1", "updatedAt": T2,
            "contextTokensUsed": 75, "contextWindowTokens": 1000, "compactionCount": 2,
            "prompt": CANARY})
        data = collect("grok", self.root)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(data["usage"][0]["input_tokens"], 100)
        self.assertEqual(data["usage"][0]["request_count"], 2)
        self.assertEqual(data["usage"][0]["unit"], "turn")
        self.assertEqual(data["contexts"][0]["used_tokens"], 75)
        self.assertEqual(data["contexts"][0]["window_tokens"], 1000)
        self.assertNotIn(CANARY, json.dumps(data))

    def test_grok_no_turns_does_not_claim_summary(self):
        path = self.json("usage.json", {"sessionId": "g1", "inputTokens": 99999})
        data = collect("grok", path)
        self.assertEqual(data["usage"], [])
        self.assertIn("grok_aggregate_unavailable_without_turns", self.codes(data))

    def test_agy_prefers_final_cumulative_without_time(self):
        rows = [{"type": "step_update", "conversation_id": "a1", "state": "DONE",
                 "usage": {"input_tokens": 50, "output_tokens": 5}},
                {"type": "result", "conversation_id": "a1", "usage": {"input_tokens": 50, "output_tokens": 5}},
                {"type": "result", "conversation_id": "a1", "usage": {"input_tokens": 150, "output_tokens": 15}}]
        path = self.write("export.jsonl", rows)
        data = collect("agy", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(data["usage"][0]["input_tokens"], 150)
        self.assertEqual(data["usage"][0]["unit"], "session")
        self.assertIsNone(data["usage"][0]["timestamp"])

    def test_agy_timed_cumulative_deltas_and_reset(self):
        path = self.write("export.jsonl", [{"type": "result", "conversation_id": "a1",
            "timestamp": at, "usage": {"input_tokens": inp, "output_tokens": out}}
            for at, inp, out in [(T1, 50, 5), (T2, 150, 15), (T3, 20, 2)]])
        data = collect("agy", path)
        self.assertEqual([r["input_tokens"] for r in data["usage"]], [50, 100, 20])
        self.assertIn("agy_cumulative_reset", self.codes(data))

    def test_agy_cache_ambiguity_and_explicit_semantics(self):
        path = self.json("export.json", {"conversation_id": "a1", "usage": {
            "input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 500,
            "thinking_tokens": 7, "total_tokens": 120}})
        data = collect("agy", path)
        self.assertIsNone(data["usage"][0]["input_tokens"])
        self.assertEqual(data["usage"][0]["output_tokens"], 20)
        self.assertEqual(data["usage"][0]["reasoning_tokens"], 7)
        self.assertIn("agy_cache_semantics_ambiguous", self.codes(data))
        path = self.json("explicit.json", {"conversation_id": "a1", "usage": {
            "input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 500,
            "input_includes_cache": False}})
        self.assertEqual(collect("agy", path)["usage"][0]["input_tokens"], 600)

    def test_agy_done_steps_only_and_directory_rejected(self):
        path = self.write("steps.jsonl", [{"type": "step_update", "state": state,
            "conversation_id": "a1", "step_id": str(i),
            "usage": {"input_tokens": 10, "output_tokens": 2}}
            for i, state in enumerate(["RUNNING", "DONE", "DONE"])])
        self.assertEqual(sum(r["input_tokens"] for r in collect("agy", path)["usage"]), 20)
        self.assertIn("explicit_export_required", self.codes(collect("agy", self.root)))

    def test_bom_crlf_unicode_partial_and_no_raw_content(self):
        path = self.write("sesje/zażółć.jsonl", [meta(base_instructions={"text": CANARY}),
            turn(), {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": CANARY},
                            {"type": "input_image", "image_url": CANARY * 100}]}}, native()],
            bom=True, partial=True)
        data = collect("codex", path)
        self.assertEqual(len(data["usage"]), 1)
        self.assertEqual(data["sources"][0]["malformed_rows"], 1)
        self.assertIn("malformed_or_partial_line", self.codes(data))
        self.assertNotIn(CANARY, json.dumps(data))
        self.assertNotIn(str(self.root), json.dumps(data))
        self.assertEqual(sum(c["characters"] for c in data["contexts"][0]["categories"]), len(CANARY) * 2)

    def test_bounded_discovery_and_unsupported_agent(self):
        self.write("unrelated/private.jsonl", [meta(), native()])
        self.assertEqual(collect("codex", self.root)["usage"], [])
        with self.assertRaises(ValueError):
            collect("unknown", self.root)

    def test_codex_postcompact_quota_snapshot_cannot_restore_old_context(self):
        for with_native in (False, True):
            with self.subTest(native=with_native):
                rows = [meta(), turn(), snapshot(cx_counts(100))]
                if with_native:
                    rows.append(native(at=T1))
                rows += [compact(), snapshot(cx_counts(100), at=T3)]
                path = self.write("postcompact.jsonl", rows)
                self.assertIsNone(collect("codex", path)["contexts"][0]["used_tokens"])

    def test_codex_replayed_snapshot_is_not_a_new_context_request(self):
        path = self.write("fork.jsonl", [meta("parent"), snapshot(cx_counts(100)),
            meta("child", forked_from_id="parent"), snapshot(cx_counts(100), at=T2)])
        data = collect("codex", path)
        self.assertEqual(data["usage"], [])
        self.assertIsNone(data["contexts"][0]["used_tokens"])

    def test_codex_native_capacity_snapshot_preserves_request_time(self):
        path = self.write("capacity.jsonl", [meta(), turn(), native(),
            snapshot(cx_counts(100), at=T2)])
        ctx = collect("codex", path)["contexts"][0]
        self.assertEqual(ctx["observed_at"], "2026-10-17T10:01:00.000Z")
        self.assertEqual(ctx["window_tokens"], 1000)

    def test_codex_unknown_inventory_stays_unknown_after_new_request(self):
        path = self.write("unknown.jsonl", [meta(), turn(), native(), compact(), native("r2", at=T3)])
        ctx = collect("codex", path)["contexts"][0]
        self.assertEqual(ctx["used_tokens"], 110)
        self.assertEqual(ctx["retention_status"], "unknown-after-compaction")

    def test_codex_tool_result_join_across_rotated_files(self):
        self.write("sessions/a.jsonl", [meta(), {"type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "call", "output": "1234567"}}])
        self.write("sessions/b.jsonl", [meta(), {"type": "response_item", "payload": {
            "type": "function_call", "call_id": "call", "name": "read_file", "arguments": "{}"}}])
        tools = collect("codex", self.root)["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "read_file")
        self.assertEqual(tools[0]["result_chars"], 7)
        self.assertEqual(tools[0]["argument_chars"], 2)

    def test_codex_base_instructions_embedded_in_developer_message(self):
        path = self.write("base-long.jsonl", [meta(base_instructions="instructions"), turn(),
            {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                   "content": "prefix instructions suffix"}}, native()])
        ctx = collect("codex", path)["contexts"][0]
        self.assertEqual(sum(c["characters"] for c in ctx["categories"]), len("prefix instructions suffix"))

    def test_claude_missing_counters_stay_unknown(self):
        row = claude()
        del row["message"]["usage"]["cache_creation_input_tokens"]
        path = self.write("missing.jsonl", [row])
        record = collect("claude", path)["usage"][0]
        self.assertIsNone(record["cache_write_tokens"])
        self.assertIsNone(record["input_tokens"])

    def test_claude_explicit_capacity_not_model_guess(self):
        path = self.write("explicit-window.jsonl", [claude(context_window={"context_window_size": 200000})])
        self.assertEqual(collect("claude", path)["contexts"][0]["window_tokens"], 200000)

    def test_claude_capacity_resets_when_the_model_changes(self):
        switched = claude("m2", "r2", at=T2)
        switched["message"]["model"] = "claude-opus-4-1"
        same = claude("m2", "r2", at=T2)
        first = claude(context_window={"context_window_size": 1000000})
        changed = collect("claude", self.write("switch.jsonl", [first, switched]))["contexts"][0]
        self.assertIsNone(changed["window_tokens"], "no stale capacity from the previous model")
        kept = collect("claude", self.write("same.jsonl", [first, same]))["contexts"][0]
        self.assertEqual(kept["window_tokens"], 1000000)

    def test_copilot_old_assistant_usage(self):
        path = self.write("older.jsonl", [{"type": "assistant.usage", "timestamp": T1, "data": {
            "requestId": "r", "model": "gpt-5", "input_tokens": 50, "output_tokens": 5}}])
        record = collect("copilot", path)["usage"][0]
        self.assertEqual(record["input_tokens"], 50)
        self.assertIsNone(record["cache_read_tokens"])

    def test_invalid_numeric_and_unsafe_names_are_not_exported(self):
        row = native(usage={"input_tokens": -1, "output_tokens": True,
                            "cached_input_tokens": "123"})
        path = self.write("invalid.jsonl", [meta(), turn(model="https://invalid.example/" + CANARY), row])
        data = collect("codex", path)
        self.assertEqual(data["usage"][0]["model"], "unknown")
        for k in ("input_tokens", "output_tokens", "cache_read_tokens"):
            self.assertIsNone(data["usage"][0][k])
        self.assertNotIn(CANARY, json.dumps(data))

    def test_codex_native_item_wrapper_and_turn_pricing_dimensions(self):
        record = native()
        record["type"] = "response_item"
        record["payload"]["type"] = "token_usage_record"
        path = self.write("wrapped.jsonl", [meta(), turn(speed="fast", service_tier="priority",
            inference_geo="eu"), record])
        row = collect("codex", path)["usage"][0]
        self.assertEqual((row["speed"], row["service_tier"], row["inference_geo"]),
                         ("fast", "priority", "eu"))

    def test_claude_partial_streaming_does_not_shrink_context(self):
        path = self.write("partial-stream.jsonl", [claude(inp=50), claude(inp=10)])
        data = collect("claude", path)
        self.assertEqual(data["usage"][0]["input_tokens"], 120)
        self.assertEqual(data["contexts"][0]["used_tokens"], 120)

    def test_grok_newer_usage_does_not_hide_native_context_signal(self):
        self.json("sessions/g1/usage.json", {"sessionId": "g1", "updatedAt": T3, "turns": []})
        self.json("sessions/g1/signals.json", {"sessionId": "g1", "updatedAt": T1,
            "contextTokensUsed": 75, "contextWindowTokens": 1000})
        data = collect("grok", self.root)
        self.assertEqual(data["contexts"][0]["used_tokens"], 75)
        self.assertEqual(data["contexts"][0]["observed_at"], "2026-10-17T10:01:00.000Z")

    def test_reasoning_is_only_exported_as_valid_output_subset(self):
        path = self.write("reasoning.jsonl", [meta(), turn(), native(usage=cx_counts(100, 5, reasoning=7))])
        row = collect("codex", path)["usage"][0]
        self.assertIsNone(row["reasoning_tokens"])
        self.assertEqual(row["output_tokens"], 5)

    def test_codex_session_filter_uses_metadata_for_renamed_file(self):
        self.write("sessions/renamed.jsonl", [meta(), turn(), native()])
        self.assertEqual(len(collect("codex", self.root, session="child")["usage"]), 1)
        self.assertEqual(collect("codex", self.root, session="other")["usage"], [])


if __name__ == "__main__":
    unittest.main()
