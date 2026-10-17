from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agent-usage-analytics/scripts"))
from usage_common import dataset, context_observation
from usage_attribution import apply_attribution
from usage_accounting import build_report, load_rates, price
from usage_store import Ledger
from usage_render import render_markdown, render_html
from test_accounting import request
import test_cli as cli_fixtures


class Attribution(unittest.TestCase):
    def data(self):
        value = dataset()
        value["usage"] = [request(agent="claude", session_id="routed", model="claude-opus-5-5",
            input_tokens=1000, cache_read_tokens=500, cache_write_tokens=0, cache_write_5m_tokens=0,
            cache_write_1h_tokens=0, output_tokens=100, reasoning_tokens=0)]
        value["contexts"] = [context_observation("claude", "routed", "2026-10-01T12:00:00Z", {}, 1000, 200000,
                                                model="claude-opus-5-5")]
        return value

    def test_glm_route_preserves_opus_label_and_uses_zai_reference_rates(self):
        value = apply_attribution(self.data(), {"claude:routed": {"provider": "zai", "model": "glm-5.3"}})
        row = value["usage"][0]
        self.assertEqual((row["reported_model"], row["model"], row["provider"]), ("claude-opus-5-5", "glm-5.3", "zai"))
        self.assertAlmostEqual(price(row, load_rates())["cost_lower_usd"], .00127)
        self.assertAlmostEqual(price({**row, "model": "GLM-5.3"}, load_rates())["cost_lower_usd"], .00127)
        self.assertEqual(value["contexts"][0]["model"], "glm-5.3")
        report = build_report(value, load_rates())
        self.assertEqual(report["models"][0]["label"], "glm-5.3")
        self.assertEqual(report["attribution"][0]["reported_model"], "claude-opus-5-5")
        self.assertIn("Provider and model attribution", render_markdown(report))
        self.assertIn("glm-5.3", render_html(report))

    def test_provider_only_and_mismatched_provider_do_not_charge_opus(self):
        value = apply_attribution(self.data(), {"claude:*": {"provider": "zai"}})
        self.assertEqual(value["usage"][0]["model"], "unknown")
        self.assertEqual(price(value["usage"][0], load_rates())["price_status"], "unpriced")
        row = {**self.data()["usage"][0], "provider": "zai"}
        self.assertEqual(price(row, load_rates())["price_notes"], ["provider_model_mismatch"])

    def test_explicit_routes_survive_recollection_and_can_be_corrected(self):
        original = self.data()
        mapped = apply_attribution(original, {"claude:routed": {"provider": "zai", "model": "glm-5.3"}})
        with tempfile.TemporaryDirectory() as temp:
            ledger = Ledger(Path(temp) / "history.sqlite")
            try:
                for value in (original, mapped, original):ledger.add(value)
                stored = ledger.read()
                self.assertEqual(stored["usage"][0]["model"], "glm-5.3")
                self.assertEqual(stored["contexts"][0]["model"], "glm-5.3")
                self.assertEqual(stored["contexts"][0]["estimation_method"], original["contexts"][0]["estimation_method"])
                corrected = apply_attribution(stored, {"claude:routed": {"provider": "zai", "model": "glm-5.3-flash"}})
                ledger.add(corrected)
                self.assertEqual(ledger.read()["usage"][0]["model"], "glm-5.3-flash")
            finally:ledger.close()

    def test_specific_mapping_wins_and_unsafe_route_values_are_rejected(self):
        value = apply_attribution(self.data(), {"claude:*": {"provider": "zai"},
            "claude:routed": {"provider": "anthropic", "model": "claude-opus-5-5"}})
        self.assertEqual(value["usage"][0]["provider"], "anthropic")
        for invalid in ([1], {"claude:routed": {"provider": "https://private.example"}},
                        {"claude:routed": {"provider": "zai", "credentials": "PRIVATE-CANARY"}}):
            with self.assertRaises(ValueError):apply_attribution(self.data(), invalid)

    def test_cli_attribution_and_existing_ledger_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, mapping, ledger = root / "numeric.json", root / "routes.json", root / "history.sqlite"
            source.write_text(json.dumps(self.data()), encoding="utf-8")
            mapping.write_text(json.dumps({"claude:routed": {"provider": "zai", "model": "glm-5.3"}}), encoding="utf-8-sig")
            for args in (("import", "--input", source, "--store", ledger),
                         ("usage", "--store", ledger, "--attribution-map", mapping, "--out", root / "out"),
                         ("import", "--input", source, "--store", ledger, "--out", root / "out")):
                result = cli_fixtures.CLIAndArtifacts.run_cli(self, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "out/report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["requests"][0]["reported_model"], "claude-opus-5-5")
            self.assertAlmostEqual(report["summary"]["cost_lower_usd"], .00127)

    def test_explicit_session_input_never_falls_back_to_native_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "numeric.json"
            source.write_text(json.dumps(self.data()), encoding="utf-8")
            for command in ("session", "usage", "collect"):
                result = cli_fixtures.CLIAndArtifacts.run_cli(self, command, "--input", source,
                    "--session", "routed", "--home", root / "no-native-sessions", "--out", root / "out")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["summary"]["total_tokens"], 1100)
            result = cli_fixtures.CLIAndArtifacts.run_cli(self, "session", "--input", source,
                "--source", "claude=" + str(root), "--session", "routed", "--out", root / "out")
            self.assertEqual(result.returncode, 2)
            self.assertIn("not both", result.stderr)


if __name__ == "__main__":unittest.main()
