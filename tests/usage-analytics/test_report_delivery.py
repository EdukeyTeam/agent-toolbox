import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/agent-usage-analytics/scripts"
sys.path.insert(0, str(SCRIPTS))
from agent_usage import main, demo_data
from usage_accounting import build_report, load_rates
from usage_render import write_reports


class ReportDelivery(unittest.TestCase):
    def test_default_reports_land_in_documents_without_overwriting_prior_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            documents = Path(temp) / "redirected Documents"
            with patch("usage_output.documents_directory", return_value=documents):
                results = []
                for _ in range(2):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        self.assertEqual(main(["demo"]), 0)
                    results.append(json.loads(stdout.getvalue())["artifacts"])
            first = Path(results[0]["docx"])
            second = Path(results[1]["docx"])
            self.assertEqual(first.parent.parent, documents.resolve() / "Agent Analysis")
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())

    def test_explicit_destination_wins_over_documents(self):
        with tempfile.TemporaryDirectory() as temp:
            requested = Path(temp) / "user selected"
            with patch("usage_output.documents_directory", side_effect=AssertionError("default must not be consulted")):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["demo", "--out", str(requested)]), 0)
            self.assertEqual(Path(json.loads(stdout.getvalue())["artifacts"]["docx"]), requested.resolve() / "report.docx")

    def test_relative_destination_returns_absolute_existing_artifact_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "agent_usage.py"), "demo", "--out", "reports with spaces"],
                cwd=temp, capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            artifacts = json.loads(result.stdout)["artifacts"]
            self.assertEqual(set(artifacts), {"docx", "json", "markdown", "html"})
            for value in artifacts.values():
                path = Path(value)
                self.assertTrue(path.is_absolute(), value)
                self.assertEqual(path.parent, Path(temp).resolve() / "reports with spaces")
                self.assertTrue(path.is_file(), value)

    def test_docx_contains_report_metrics_unicode_and_inert_labels(self):
        report = build_report(demo_data(), load_rates())
        label = r"Zażółć <script> & | backslash\ label"
        report["tools"][0]["name"] = label
        with tempfile.TemporaryDirectory() as temp:
            paths = write_reports(report, Path(temp))
            self.assertIn("docx", paths)
            with ZipFile(paths["docx"]) as archive:
                for name in archive.namelist():
                    if name.endswith((".xml", ".rels")):
                        ET.fromstring(archive.read(name))
                document = ET.fromstring(archive.read("word/document.xml"))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                text = " ".join(document.itertext())
                self.assertIn("Agent usage report", text)
                self.assertIn("42", text)
                self.assertIn("1,964,970", text)
                self.assertIn(label, text)
                self.assertNotIn("**Confirm historical model routes**", text)
                self.assertTrue(document.findall(".//w:tbl", ns))
                self.assertTrue(document.findall(".//w:tblHeader", ns))
                for name in archive.namelist():
                    if name.endswith(".rels"):
                        self.assertNotIn(b'TargetMode="External"', archive.read(name))

    @unittest.skipIf(os.name == "nt", "XDG applies on Linux")
    def test_linux_uses_configured_documents_directory(self):
        from usage_output import documents_directory
        import subprocess
        with patch("usage_output.sys.platform", "linux"), patch("usage_output.shutil.which", return_value="/usr/bin/xdg-user-dir"), patch(
            "usage_output.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "/home/example/Dokumenty\n", "")
        ):
            self.assertEqual(documents_directory(), Path("/home/example/Dokumenty"))

    @unittest.skipUnless(os.name == "nt", "Windows known-folder integration")
    def test_windows_documents_known_folder_resolves_without_creating_it(self):
        from usage_output import documents_directory
        self.assertTrue(documents_directory().is_absolute())


if __name__ == "__main__":
    unittest.main()
