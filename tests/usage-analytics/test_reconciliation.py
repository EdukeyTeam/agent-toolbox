"""Independent-review regressions for growing histories and alternative sources."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agent-usage-analytics/scripts"))
from usage_accounting import build_report, load_rates, merge, pseudonymize
from usage_common import dataset
from usage_store import Ledger
import test_collectors as fixtures
from test_collectors import T0, T1, T2, T3, claude, copilot_event, cx_counts, meta, native, snapshot, turn
from usage_collectors import collect


class Reconciliation(unittest.TestCase):
    setUp = fixtures.CollectorTests.setUp
    tearDown = fixtures.CollectorTests.tearDown
    write = fixtures.CollectorTests.write
    json = fixtures.CollectorTests.json
    sql = fixtures.CollectorTests.sql
    sql_insert = fixtures.CollectorTests.sql_insert

    def ledger_sequence(self, *values):
        ledger = Ledger(self.root / "history.sqlite")
        try:
            for value in values:
                ledger.add(value)
            return ledger.read()
        finally:
            ledger.close()

    def test_copilot_separate_sources_and_rotated_ledger_do_not_double_count(self):
        events = self.write("session-state/p1/events.jsonl", copilot_event())
        sql, connection = self.sql()
        self.sql_insert(connection)
        self.sql_insert(connection, "second", "sql-only", 200)
        connection.close()
        a, b = collect("copilot", events), collect("copilot", sql)
        for value in (merge(a, b), merge(b, a), self.ledger_sequence(a, b, a, b)):
            self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 300)
            self.assertEqual(len(value["usage"]), 2)

    def test_copilot_partial_events_do_not_hide_growing_sql_history(self):
        event_path = self.write("session-state/p1/events.jsonl", copilot_event())
        sql, connection = self.sql()
        self.sql_insert(connection)
        self.sql_insert(connection, "new-request", "p1", 200)
        connection.close()
        a, b = collect("copilot", event_path), collect("copilot", sql)
        for value in (merge(a, b), merge(b, a), self.ledger_sequence(a, b), collect("copilot", self.root)):
            report = build_report(value, load_rates())
            self.assertEqual(report["summary"]["input_tokens"], 300)
            self.assertEqual(report["summary"]["requests"], 2)
            self.assertGreater(report["summary"]["accounting_gap_observations"], 0)
            self.assertEqual(report["summary"]["count_quality"], "known lower bound")

    def test_empty_or_unusable_event_accounting_falls_back_to_sql(self):
        events = copilot_event()
        events[1]["data"]["responseUsage"] = {"new_field": 999}
        event_path = self.write("session-state/p1/events.jsonl", events)
        sql, connection = self.sql()
        self.sql_insert(connection)
        connection.execute("UPDATE assistant_usage_events SET created_at='2026-10-17 10:01:00'")
        connection.commit()
        connection.close()
        for value in (merge(collect("copilot", event_path), collect("copilot", sql)), collect("copilot", self.root)):
            report = build_report(value, load_rates(), since="2026-10-17", until="2026-10-18")
            self.assertEqual(report["summary"]["input_tokens"], 100)
            self.assertEqual(report["summary"]["requests"], 1)

    def test_agy_cross_file_and_ledger_cumulative_deltas(self):
        def export(name, at, inp):
            return collect("agy", self.json(name, {"event": "result", "timestamp": at,
                "result": {"conversation_id": "a1", "usage": {"input_tokens": inp, "output_tokens": inp / 10}}}))
        a, b = export("a.json", T1, 100), export("b.json", T2, 150)
        for value in (merge(a, b), merge(b, a), self.ledger_sequence(a, b, a)):
            self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 150)
            ordered = sorted(value["usage"], key=lambda r: r["cumulative_observed_at"])
            self.assertEqual([r["input_tokens"] for r in ordered], [100, 50])
            self.assertIsNone(ordered[0]["timestamp"])
            self.assertEqual(merge(value), value)
        report = build_report(merge(a, b), load_rates(), since="2026-10-17", until="2026-10-18")
        self.assertEqual(report["summary"]["input_tokens"], 50)
        self.assertEqual(report["undated_requests_excluded"], 1)

    def test_claude_streamed_blocks_and_repeated_snapshots(self):
        text = claude(uuid="text-uuid")
        text["message"]["content"] = [{"type": "text", "text": "a" * 1000}]
        tool = claude(uuid="tool-uuid")
        tool["message"]["content"] = [{"type": "tool_use", "id": "call", "name": "Read", "input": {"file_path": "file.py"}}]
        value = collect("claude", self.write("c.jsonl", [text, tool, text]))
        self.assertEqual(len(value["usage"]), 1)
        categories = {c["name"]: c["characters"] for c in value["contexts"][0]["categories"]}
        self.assertEqual(categories["assistant_messages"], 1000)
        self.assertGreater(categories["tool_arguments"], 0)

    def test_selected_codex_parent_matches_full_ledger_including_child_context(self):
        parent, child = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
        for sid, extra in ((parent, {}), (child, {"source": {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}})):
            row = native(rid=sid)
            row["payload"]["thread_id"] = sid
            self.write(f".codex/sessions/rollout-{sid}.jsonl", [meta(sid, **extra), turn(), row])
        direct = collect("codex", self.root / ".codex", session=parent)
        stored = self.ledger_sequence(collect("codex", self.root / ".codex"))
        reports = [build_report(v, load_rates(), session_id=parent, compare_since="2026-10-17", compare_until="2026-10-18", now=T2,
                                task_map={parent: "client-work"}) for v in (direct, stored)]
        for report in reports:
            self.assertEqual(report["summary"]["input_tokens"], 200)
            self.assertEqual(len(report["contexts"]), 2)
            self.assertEqual(report["local_rolling_usage"]["five_hour"]["input_tokens"], 200)
            self.assertEqual(report["comparison"]["previous"]["input_tokens"], 200)
            self.assertEqual([r["label"] for r in report["tasks"]], ["client-work"])

    def test_fresh_legacy_spawn_starts_at_zero(self):
        path = self.write("spawn.jsonl", [meta(source={"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}),
            turn(), snapshot(cx_counts(100)), snapshot(cx_counts(150, 15), at=T2)])
        value = collect("codex", path)
        self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 150)
        self.assertNotIn("fork_baseline_unknown", {r["code"] for r in value["warnings"]})

    def test_uuid_discovery_recognizes_replayed_parent_metadata(self):
        parent, child = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
        self.write(f".codex/sessions/rollout-{parent}.jsonl", [meta(parent), turn(), snapshot(cx_counts(100))])
        self.write(f".codex/sessions/rollout-{child}.jsonl", [meta(parent), snapshot(cx_counts(100)),
            meta(child, forked_from_id=parent), turn(), snapshot(cx_counts(150, 15), at=T2)])
        for value in (collect("codex", self.root / ".codex", session=parent),
                      self.ledger_sequence(collect("codex", self.root / ".codex"))):
            report = build_report(value, load_rates(), session_id=parent)
            self.assertEqual(report["summary"]["input_tokens"], 150)
            self.assertEqual(len(report["contexts"]), 2)

    def test_codex_legacy_parent_in_archive_tree(self):
        self.write(".codex/archived_sessions/parent.jsonl", [meta("parent"), snapshot(cx_counts(100))])
        child = self.write(".codex/sessions/child.jsonl", [meta("child", forked_from_id="parent"),
            snapshot(cx_counts(100)), snapshot(cx_counts(150, 15), at=T2)])
        value = collect("codex", child)
        self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 50)

    def test_codex_snapshot_before_native_and_prior_live_ledger_reconcile(self):
        path = self.write("child.jsonl", [meta(), turn(), snapshot(cx_counts(100)), snapshot(cx_counts(300, 30), at=T2)])
        prefix = collect("codex", path)
        self.write("child.jsonl", [meta(), turn(), snapshot(cx_counts(100)), snapshot(cx_counts(300, 30), at=T2),
            native("r2", cx_counts(200, 20), at=T2, thread_token_usage=cx_counts(300, 30))])
        full = collect("codex", path)
        for value in (merge(prefix, full), self.ledger_sequence(prefix, full)):
            self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 300)
            self.assertEqual(sum(r["output_tokens"] for r in value["usage"]), 30)
            self.assertEqual(build_report(value, load_rates())["summary"]["accounting_gap_observations"], 0)

    def test_undated_later_native_cannot_expand_legacy_budget(self):
        path = self.write("child.jsonl", [meta(), turn(), snapshot(cx_counts(100)), snapshot(cx_counts(300, 30), at=T2)])
        old = collect("codex", path)
        self.write("child.jsonl", [meta(), turn(), snapshot(cx_counts(100)),
            native("r1", cx_counts(200, 20), at=T2, thread_token_usage=cx_counts(300, 30)),
            native("r2", cx_counts(200, 20), at=None, thread_token_usage=cx_counts(500, 50))])
        value = self.ledger_sequence(old, collect("codex", path))
        self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 500)

    def test_resolved_source_warnings_expire_after_recollection(self):
        child = self.write(".codex/sessions/child.jsonl", [meta("child", forked_from_id="parent"),
            snapshot(cx_counts(100)), snapshot(cx_counts(150, 15), at=T2)])
        old = collect("codex", child)
        self.assertIn("fork_baseline_unknown", {r["code"] for r in old["warnings"]})
        self.write(".codex/archived_sessions/parent.jsonl", [meta("parent"), snapshot(cx_counts(100))])
        value = self.ledger_sequence(old, collect("codex", child))
        self.assertNotIn("fork_baseline_unknown", {r["code"] for r in value["warnings"]})
        self.assertEqual(sum(r["input_tokens"] for r in value["usage"]), 50)

    def test_comparison_only_models_keep_their_rate_entries(self):
        from test_accounting import request
        value = dataset()
        value["usage"] = [request(id="old", model="claude-sonnet-5-5"),
                          request(id="new", model="claude-opus-5-5", timestamp=T1)]
        report = build_report(value, load_rates(), since="2026-10-17", until="2026-10-18",
                              compare_since="2026-10-01", compare_until="2026-10-02", now=T2)
        self.assertEqual(set(report["pricing"]["rates"]), {"claude-sonnet-5-5", "claude-opus-5-5"})

    def test_growing_session_metadata_and_warning_scope(self):
        a, b = dataset(), dataset()
        a["sessions"] = [{"id": "s", "agent": "codex", "session_id": "good", "start": T0, "end": T1, "compactions": 0}]
        b["sessions"] = [{**a["sessions"][0], "start": T1, "end": T3, "compactions": 2}]
        value = self.ledger_sequence(a, b)
        self.assertEqual((value["sessions"][0]["start"], value["sessions"][0]["end"], value["sessions"][0]["compactions"]),
                         ("2026-10-17T10:00:00.000Z", "2026-10-17T10:03:00.000Z", 2))
        value["warnings"] = [{"id": "w", "code": "malformed_or_partial_line", "source_id": "bad"}]
        value["sources"] = [{"id": "bad", "session_id": "other"}]
        self.assertEqual(build_report(value, load_rates(), session_id="good")["summary"]["accounting_gap_observations"], 0)

    def test_share_identifiers_are_randomized_per_report(self):
        value = {"session_id": "client-name", "source_id": "low-entropy", "categories": [{"name": "instructions"}]}
        first, second = pseudonymize(value), pseudonymize(value)
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["categories"][0]["name"], "instructions")
        self.assertNotIn("client-name", json.dumps(first))


if __name__ == "__main__":
    unittest.main()
