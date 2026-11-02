import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "agent-usage-analytics" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from agent_usage import demo_data
from usage_accounting import build_report, load_rates
from usage_render import write_reports, render_markdown, render_html


class CLIAndArtifacts(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "agent_usage.py"), *map(str, args)],
                              capture_output=True, encoding="utf-8", timeout=30)

    def test_report_artifacts_agree_and_embed_data_safely(self):
        report = build_report(demo_data(), load_rates(), now="2026-10-17T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp:
            paths = write_reports(report, Path(temp))
            stored = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            html = Path(paths["html"]).read_text(encoding="utf-8")
            match = re.search(r'<script[^>]+id="report-data"[^>]*>(.*?)</script>', html, re.S)
            self.assertIsNotNone(match)
            self.assertEqual(json.loads(match[1]), stored)
            self.assertEqual(stored["summary"]["requests"], 42)
            md = Path(paths["markdown"]).read_text(encoding="utf-8")
            self.assertIn(f'{stored["summary"]["input_tokens"]:,}', md)
            self.assertNotRegex(html, r'<(?:script|link|img)[^>]+(?:src|href)=["\']https?://')

    def test_html_script_breakout_and_markdown_table_injection_are_inert(self):
        report = build_report(demo_data(), load_rates())
        label = '</script><img src=x onerror="window.CANARY=1">\u2028'
        report["tools"][0]["name"] = label
        html = render_html(report)
        self.assertNotIn(label, html)
        self.assertIn("\\u003c/script\\u003e", html)
        markdown = render_markdown(report)
        self.assertNotRegex(markdown, r'(?<!\\)<img')
        self.assertIn(r'\<img', markdown)

    def test_demo_then_repeat_import_are_idempotent_and_scope_is_filtered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "demo"
            result = self.run_cli("demo", "--out", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            # The imported input is a normalized dataset, distinct from the report JSON.
            normalized = root / "input.json"
            normalized.write_text(json.dumps(demo_data()))
            ledger = root / "history.sqlite"
            for _ in range(2):
                result = self.run_cli("import", "--input", normalized, "--store", ledger)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["summary"]["requests"], 42)
            result = self.run_cli("usage", "--store", ledger, "--since", "2026-10-01", "--until", "2026-10-02", "--out", root / "day")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["summary"]["requests"], 3)

    def test_bad_import_does_not_echo_private_content_and_ambiguous_session_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            broken = root / "bad.json"
            broken.write_text('{"prompt":"SECRET-CANARY", garbage')
            result = self.run_cli("import", "--input", broken, "--out", root / "reports")
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("SECRET-CANARY", result.stderr + result.stdout)
            self.assertNotIn("Traceback", result.stderr)
            result = self.run_cli("session", "--out", root / "reports")
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires --session", result.stderr)

    def test_context_only_session_is_inspectable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = demo_data()
            data.update(usage=[], sessions=[], tools=[])
            snapshot = root / "context-only.json"
            snapshot.write_text(json.dumps(data))
            result = self.run_cli("session", "--input", snapshot, "--session", "sample-codex-3", "--out", root / "ctx")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_cli("session", "--input", snapshot, "--session", "missing", "--out", root / "none")
            self.assertEqual(result.returncode, 2)
            self.assertIn("not found", result.stderr)

    def test_failed_validation_never_writes_the_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            normalized = root / "input.json"
            normalized.write_text(json.dumps(demo_data()))
            ledger = root / "history.sqlite"
            result = self.run_cli("session", "--input", normalized, "--session", "missing", "--store", ledger, "--out", root / "x")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(ledger.exists(), "a mistyped session must not create or change history")
            bad_map = root / "tasks.json"
            bad_map.write_text(json.dumps({"s": 1}))
            result = self.run_cli("import", "--input", normalized, "--store", ledger, "--task-map", bad_map)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(ledger.exists())
            self.assertEqual(self.run_cli("import", "--input", normalized, "--store", ledger).returncode, 0)
            result = self.run_cli("session", "--store", ledger, "--session", "sample-codex-3", "--out", root / "y")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_inputs_and_credential_filename_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_cli("usage", "--home", root, "--out", root / "empty")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["summary"]["requests"], 0)
            self.assertIn("No", (root / "empty/report.md").read_text())
            result = self.run_cli("import", "--input", root / "auth.json", "--out", root / "bad")
            self.assertEqual(result.returncode, 2)
            self.assertIn("Credential", result.stderr)

    def test_utf8_bom_task_map_and_embedded_rates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = demo_data()
            normalized = root / "input.json"
            normalized.write_text(json.dumps(value), encoding="utf-8")
            category = "Szkolenia ąęłńóśźż"
            tasks = root / "tasks.json"
            tasks.write_text(json.dumps({r["session_id"]: category for r in value["usage"]}, ensure_ascii=False), encoding="utf-8-sig")
            result = self.run_cli("import", "--input", normalized, "--task-map", tasks, "--out", root / "out")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "out/report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["tasks"][0]["label"], category)
            self.assertTrue(report["pricing"]["rates"])
            self.assertEqual(report["pricing"]["currency"], "USD")


if __name__ == "__main__":
    unittest.main()
