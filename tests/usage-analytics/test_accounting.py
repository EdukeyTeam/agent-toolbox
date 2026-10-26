from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "agent-usage-analytics" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from usage_common import dataset, context_observation
from usage_accounting import build_report, load_rates, merge, price, quota_analysis
from usage_store import Ledger, normalize_import
from agent_usage import native_snapshot


def request(**updates):
    row = {"id": "r1", "agent": "claude", "session_id": "s1", "model": "claude-sonnet-5-5",
           "timestamp": "2026-10-01T12:00:00.000Z", "input_tokens": 25000,
           "cache_read_tokens": 20000, "cache_write_tokens": 4000, "cache_write_5m_tokens": 4000,
           "cache_write_1h_tokens": 0, "output_tokens": 500, "reasoning_tokens": 200, "request_count": 1,
           "account": "local", "speed": "standard", "inference_geo": "global"}
    return {**row, **updates}


class Pricing(unittest.TestCase):
    def setUp(self):
        self.rates = load_rates()

    def test_disjoint_cache_and_reasoning_buckets(self):
        result = price(request(), self.rates)
        self.assertAlmostEqual(result["cost_lower_usd"], .019)
        self.assertEqual(result["price_status"], "priced")
        self.assertEqual(result, price(request(reasoning_tokens=0), self.rates))

    def test_prompt_tiers_apply_to_each_request_before_aggregation(self):
        high = request(model="claude-haiku-5-5", input_tokens=120000, cache_read_tokens=100000,
                       cache_write_tokens=0, cache_write_5m_tokens=0, output_tokens=1000)
        self.assertAlmostEqual(price(high, self.rates)["cost_lower_usd"], .0175)
        low = {**high, "id": "low", "input_tokens": 100000, "cache_read_tokens": 80000}
        self.assertAlmostEqual(price(low, self.rates)["cost_lower_usd"], .0033)
        d = dataset()
        d["usage"] = [high, low]
        self.assertAlmostEqual(build_report(d, self.rates)["summary"]["cost_lower_usd"], .0208)

    def test_ttl_unknown_is_a_range_and_fast_geo_stack(self):
        result = price(request(model="claude-opus-5-5", input_tokens=1000, cache_read_tokens=0,
                               cache_write_tokens=1000, cache_write_5m_tokens=None,
                               cache_write_1h_tokens=None, output_tokens=0, reasoning_tokens=0), self.rates)
        self.assertAlmostEqual(result["cost_lower_usd"], .005)
        self.assertAlmostEqual(result["cost_upper_usd"], .008)
        stacked = price(request(model="claude-opus-5-5", speed="fast", inference_geo="us"), self.rates)
        self.assertAlmostEqual(stacked["cost_lower_usd"], .0836)

    def test_openai_write_subset_and_unverified_prompt_tier_range(self):
        result = price(request(model="gpt-6.1-sol", input_tokens=10000, cache_read_tokens=8000,
                               cache_write_tokens=1000, cache_write_5m_tokens=1000,
                               output_tokens=100, reasoning_tokens=50), self.rates)
        self.assertAlmostEqual(result["cost_lower_usd"], .0063)
        self.assertAlmostEqual(result["cost_upper_usd"], .0121)
        self.assertIn("prompt_tier_range", result["price_notes"])

    def test_unknown_and_missing_are_not_free(self):
        for row in (request(model="not-a-real-model"), request(input_tokens=None), request(output_tokens=None),
                    request(cache_read_tokens=99999), request(reasoning_tokens=501)):
            self.assertEqual(price(row, self.rates)["price_status"], "unpriced")
            self.assertIsNone(price(row, self.rates)["cost_lower_usd"])

    def test_absent_cache_counter_is_distinct_from_zero(self):
        a = price(request(cache_read_tokens=None), self.rates)
        b = price(request(cache_read_tokens=0), self.rates)
        self.assertLess(a["cost_lower_usd"], b["cost_lower_usd"])
        self.assertIn("cache_read_not_reported", a["price_notes"])

    def test_effective_intervals_and_explicit_alias(self):
        card = deepcopy(self.rates)
        old = {**card["models"]["claude-sonnet-5-5"], "effective_until": "2026-10-01"}
        new = {**old, "effective_from": "2026-10-01", "effective_until": None, "output": 20}
        card["models"]["claude-sonnet-5-5"] = [old, new]
        card["aliases"]["explicit-alias"] = "claude-sonnet-5-5"
        self.assertAlmostEqual(price(request(timestamp="2026-09-30T12:00:00Z"), card)["cost_lower_usd"], .019)
        self.assertAlmostEqual(price(request(model="explicit-alias"), card)["cost_lower_usd"], .024)

    def test_rate_card_rejects_invalid_nested_rates(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "rates.json"
            card = deepcopy(self.rates)
            card["models"]["claude-haiku-5-5"]["tiers"][0]["rates"]["input"] = -1
            p.write_text(json.dumps(card))
            with self.assertRaisesRegex(ValueError, "alternate"):
                load_rates(p)

    def test_aggregate_haiku_usage_cannot_use_one_request_threshold(self):
        row = request(model="claude-haiku-5-5", input_tokens=120000, cache_read_tokens=100000,
                      cache_write_tokens=0, cache_write_5m_tokens=0, output_tokens=1000, unit="session")
        result = price(row, self.rates)
        self.assertLess(result["cost_lower_usd"], result["cost_upper_usd"])
        self.assertIn("aggregate_prompt_tier_range", result["price_notes"])


class Aggregation(unittest.TestCase):
    def test_excluded_unknown_history_marks_totals_as_lower_bounds(self):
        d = dataset()
        d["usage"] = [request()]
        d["warnings"] = [{"id": "w", "code": "fork_baseline_unknown", "source_id": "s"}]
        report = build_report(d, load_rates())
        self.assertEqual(report["summary"]["accounting_gap_observations"], 1)
        self.assertEqual(report["summary"]["count_quality"], "known lower bound")

    def test_skipped_json_source_or_missing_export_marks_totals_as_lower_bounds(self):
        for code in ("malformed_json", "explicit_export_required", "checkpoint_exceeds_requests"):
            d = dataset()
            d["usage"] = [request()]
            d["warnings"] = [{"id": "w", "code": code, "source_id": "s"}]
            self.assertEqual(build_report(d, load_rates())["summary"]["count_quality"], "known lower bound", code)
        d = dataset()
        d["usage"] = [request()]
        d["warnings"] = [{"id": "w", "code": "no_eligible_sources", "source_id": "s"}]
        self.assertEqual(build_report(d, load_rates())["summary"]["accounting_gap_observations"], 0)

    def test_repeated_snapshots_do_not_sum_and_partial_usage_can_improve(self):
        one, two = dataset(), dataset()
        one["usage"] = [request(output_tokens=100)]
        two["usage"] = [request(output_tokens=500)]
        result = merge(one, two, two)
        self.assertEqual(len(result["usage"]), 1)
        self.assertEqual(result["usage"][0]["output_tokens"], 500)

    def test_later_collection_resolves_unknown_model_but_not_a_user_route(self):
        early, late = dataset(), dataset()
        early["usage"] = [request(model="unknown", reported_model="unknown", model_attribution="reported")]
        late["usage"] = [request(model="gpt-5.5", reported_model="gpt-5.5", model_attribution="reported")]
        self.assertEqual(merge(early, late)["usage"][0]["model"], "gpt-5.5")
        routed = dataset()
        routed["usage"] = [request(model="glm-5.3", provider="zai", model_attribution="user_override")]
        self.assertEqual(merge(routed, late)["usage"][0]["model"], "glm-5.3", "a user route is never replaced")

    def test_unreported_counters_stay_unknown_and_cache_hit_needs_coverage(self):
        d = dataset()
        d["usage"] = [request(id="a", cache_read_tokens=None, cache_write_tokens=None, cache_write_5m_tokens=None,
                              cache_write_1h_tokens=None, reasoning_tokens=None)]
        summary = build_report(d, load_rates())["summary"]
        self.assertIsNone(summary["cache_read_tokens"])
        self.assertIsNone(summary["reasoning_tokens"])
        self.assertIsNone(summary["cache_hit_percent"], "no cache counter is not a 0% hit rate")
        self.assertEqual(summary["total_tokens"], 25500)
        d["usage"].append(request(id="b", input_tokens=10000, cache_read_tokens=5000))
        summary = build_report(d, load_rates())["summary"]
        self.assertEqual(summary["cache_read_tokens"], 5000)
        self.assertEqual(summary["missing_fields"]["cache_read_tokens"], 1)
        self.assertEqual(summary["cache_hit_percent"], 50, "only the record reporting both counters")

    def test_later_context_snapshot_adds_capacity(self):
        early, late = dataset(), dataset()
        early["contexts"] = [context_observation("codex", "s1", "2026-10-01T12:00:00.000Z", {}, 40000, None, model="gpt-5.5")]
        late["contexts"] = [context_observation("codex", "s1", "2026-10-01T12:00:00.000Z", {}, 40000, 200000, model="gpt-5.5")]
        self.assertEqual(early["contexts"][0]["id"], late["contexts"][0]["id"])
        ctx = merge(early, late)["contexts"][0]
        self.assertEqual(ctx["window_tokens"], 200000)
        self.assertEqual(ctx["computed_percent"], 20)
        self.assertEqual(merge(late, early)["contexts"][0]["window_tokens"], 200000, "a poorer later copy keeps the measurement")
        richer = dataset()
        richer["contexts"] = [context_observation("codex", "s1", "2026-10-01T12:00:00.000Z", {"user": 4000}, 40000, 200000, model="gpt-5.5")]
        refreshed = merge(late, richer)["contexts"][0]
        self.assertEqual([c["name"] for c in refreshed["categories"]], ["user"], "an equally measured later copy refreshes categories")
        self.assertEqual(refreshed["unattributed_tokens"], 40000 - refreshed["visible_estimated_tokens"])

    def test_half_open_calendar_filter_and_undated_coverage(self):
        d = dataset()
        d["usage"] = [request(id="a", timestamp="2026-09-30T23:59:59.999Z"), request(id="b"),
                      request(id="c", timestamp="2026-11-01T00:00:00.000Z"), request(id="d", timestamp=None)]
        report = build_report(d, load_rates(), since="2026-10-01", until="2026-11-01")
        self.assertEqual(report["summary"]["requests"], 1)
        self.assertEqual(report["monthly"][0]["label"], "2026-10")
        self.assertEqual(report["undated_requests_excluded"], 1)

    def test_local_time_grouping_and_unknown_timezone(self):
        d = dataset()
        d["usage"] = [request(timestamp="2026-10-01T00:15:00.000Z")]
        try:
            report = build_report(d, load_rates(), tz_name="America/New_York")
        except ValueError:
            report = None  # Windows without IANA database still has explicit UTC support.
        if report:
            self.assertEqual(report["daily"][0]["label"], "2026-09-30")
        with self.assertRaisesRegex(ValueError, "Timezone unavailable"):
            build_report(d, load_rates(), tz_name="Invalid/DefinitelyUnavailable")

    def test_unknown_context_does_not_invent_free_space(self):
        c = context_observation("codex", "s", "2026-10-01T00:00:00Z", {"tool_results": 40000}, None, 200000, 1)
        self.assertIsNone(c["computed_percent"])
        self.assertIsNone(c["unattributed_tokens"])
        overrun = context_observation("codex", "s", None, {"tool_results": 40000}, 1000, 200000)
        self.assertLess(overrun["unattributed_tokens"], 0)
        self.assertEqual(overrun["visible_estimated_tokens"], 10000)

    def test_share_pseudonymizes_identifiers_and_named_insights(self):
        d = dataset()
        d["usage"] = [request(session_id="PRIVATE-SESSION")]
        d["tools"] = [{"id": "t", "agent": "claude", "session_id": "PRIVATE-SESSION", "name": "PRIVATE-TOOL", "kind": "tool", "result_chars": 2000}]
        d["contexts"] = [context_observation("claude", "PRIVATE-SESSION", None, {"instructions": 100}, 100, 200000)]
        normal = build_report(d, load_rates())
        shared = build_report(d, load_rates(), share=True)
        self.assertIn("PRIVATE-SESSION", json.dumps(normal))
        self.assertNotIn("PRIVATE-SESSION", json.dumps(shared))
        self.assertNotIn("PRIVATE-TOOL", json.dumps(shared))
        self.assertEqual(shared["contexts"][0]["categories"][0]["name"], "instructions")
        self.assertEqual(normal["summary"], shared["summary"])

    def test_explicit_task_categories_and_missing_usage_coverage(self):
        d = dataset()
        d["usage"] = [request(), request(id="r2", input_tokens=None)]
        report = build_report(d, load_rates(), task_map={"s1": "debugging"})
        self.assertEqual(report["tasks"][0]["label"], "debugging")
        self.assertEqual(report["summary"]["unpriced_requests"], 1)
        self.assertEqual(report["summary"]["missing_usage_requests"], 1)
        self.assertEqual(report["summary"]["count_quality"], "known lower bound")


class ImportsAndHistory(unittest.TestCase):
    def test_import_allowlist_drops_content_and_rejects_invalid_numbers(self):
        d = dataset()
        d["usage"] = [request(raw_prompt="SECRET-CANARY", credentials={"token": "SECRET-CANARY"})]
        clean = normalize_import(d)
        self.assertNotIn("SECRET-CANARY", json.dumps(clean))
        for invalid in (-1, float("nan"), float("inf"), True):
            d["usage"][0]["input_tokens"] = invalid
            with self.assertRaises(ValueError):
                normalize_import(d)

    def test_history_idempotency_concurrency_and_unrelated_db_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.sqlite"
            ledger = Ledger(path)
            d = dataset()
            d["usage"] = [request()]
            ledger.add(d)
            ledger.add(d)
            self.assertEqual(len(ledger.read()["usage"]), 1)
            ledger.close()
            def append(index):
                l = Ledger(path)
                try:
                    value = dataset()
                    value["usage"] = [request(id=f"concurrent-{index}")]
                    l.add(value)
                finally:
                    l.close()
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(append, range(8)))
            ledger = Ledger(path)
            self.assertEqual(len(ledger.read()["usage"]), 9)
            ledger.close()
            unrelated = Path(temp) / "provider.sqlite"
            db = sqlite3.connect(unrelated)
            db.execute("CREATE TABLE provider_data (id INTEGER)")
            db.commit()
            db.close()
            with self.assertRaisesRegex(ValueError, "unrelated"):
                Ledger(unrelated)
            db = sqlite3.connect(unrelated)
            self.assertEqual([r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")], ["provider_data"])
            db.close()

    def test_native_statusline_and_multi_bucket_quota_exports_are_allowlisted(self):
        raw = {"session_id": "s", "user_message": "SECRET-CANARY", "rate_limits": {"five_hour": {"used_percentage": 25, "resets_at": 1792300000}},
               "context_window": {"context_window_size": 200000, "used_percentage": 8,
                                  "current_usage": {"input_tokens": 8500, "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 2000}}}
        data = native_snapshot(raw, "claude", observed_at="2026-10-17T20:00:00Z")
        self.assertEqual(data["contexts"][0]["used_tokens"], 15500)
        self.assertEqual(data["contexts"][0]["provider_percent"], 8)
        self.assertEqual(data["quotas"][0]["window_minutes"], 300)
        self.assertNotIn("SECRET-CANARY", json.dumps(data))
        raw["context_window"]["current_usage"] = None
        self.assertIsNone(native_snapshot(raw, "claude")["contexts"][0]["used_tokens"])
        codex = native_snapshot({"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 4, "windowDurationMins": 10080, "resetsAt": 1792300000}}}}, "codex")
        self.assertEqual(codex["quotas"][0]["window_minutes"], 10080)


class QuotaCalibration(unittest.TestCase):
    def test_requires_coverage_and_rejects_reset_and_mixed_models(self):
        q = [{"agent": "claude", "account": "local", "bucket": "weekly", "window_minutes": 10080,
              "resets_at": "2026-10-08T00:00:00.000Z", "used_percent": 2 * i,
              "observed_at": f"2026-10-01T12:0{i}:00.000Z"} for i in range(5)]
        rows = [{**request(id=str(i), timestamp=f"2026-10-01T12:0{i}:00.000Z"), **price(request(), load_rates())} for i in range(1, 5)]
        self.assertEqual(quota_analysis(q, rows)[0]["status"], "unavailable")
        valid = quota_analysis(q, rows, True)[0]
        self.assertEqual(valid["status"], "experimental")
        self.assertEqual(valid["tokens_per_point"], 12750)
        q[-1]["used_percent"] = 1
        self.assertEqual(quota_analysis(q, rows, True)[0]["status"], "unavailable")
        q[-1]["used_percent"] = 8
        rows[-1]["model"] = "different"
        self.assertEqual(quota_analysis(q, rows, True)[0]["status"], "unavailable")

    def test_provider_tagged_quota_needs_confirmed_routes(self):
        q = [{"agent": "claude", "account": "local", "bucket": "weekly", "window_minutes": 10080, "provider": "anthropic",
              "resets_at": "2026-10-08T00:00:00.000Z", "used_percent": 2 * i,
              "observed_at": f"2026-10-01T12:0{i}:00.000Z"} for i in range(5)]
        rows = [{**request(id=str(i), timestamp=f"2026-10-01T12:0{i}:00.000Z"), **price(request(), load_rates())} for i in range(1, 5)]
        unmapped = quota_analysis(q, rows, True)[0]
        self.assertEqual(unmapped["status"], "unavailable", "unmapped routes may have been served by a proxy")
        self.assertIn("serving route", unmapped["reason"])
        for r in rows:
            r["provider"] = "anthropic"
        self.assertEqual(quota_analysis(q, rows, True)[0]["status"], "experimental")
        rows[0]["provider"] = None
        self.assertEqual(quota_analysis(q, rows, True)[0]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
