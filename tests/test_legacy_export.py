"""Behavior checks for publishing an existing map with readable statistics."""

import errno
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from export_repo_map import export_map


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "source with spaces"
        self.repo.mkdir()
        self.artifacts = self.base / "artifacts"
        self.artifacts.mkdir()
        self.raw = "# Repository map\n\nsrc/École.py:L1: def 👋():\n"
        self.metadata = {
            "status": "complete", "source_root": str(self.repo), "revision": "abc123",
            "dirty": True, "working_copy_fingerprint": "fixture-fingerprint",
            "coverage": {"candidates_seen": 5, "selected_files": 3, "parsed_files": 2,
                         "definitions_found": 7, "definitions_in_map": 1},
            "limits": {"budget": 64}, "truncated": True,
            "skipped": [{"path": "*", "reason": "scan limit"}],
            "parse_failures": [{"path": "bad.py", "reason": "fixture failure"}],
            "map_sha256": hashlib.sha256(self.raw.encode()).hexdigest(),
            "estimated_tokens": math.ceil(len(self.raw) / 4),
        }
        self.inventory = {"root": str(self.repo), "revision": "abc123", "fingerprint": "fixture-fingerprint",
                          "files": [{"path": "a.py"}, {"path": "b.py"}, {"path": "bad.py"}]}
        self.write_artifacts()

    def write_artifacts(self):
        (self.artifacts / "repo-map.md").write_bytes(self.raw.encode())
        (self.artifacts / "map.meta.json").write_text(json.dumps(self.metadata), encoding="utf-8")
        (self.artifacts / "inventory.json").write_text(json.dumps(self.inventory), encoding="utf-8")

    def export(self, **options):
        return export_map(self.repo, self.artifacts, implementation="python", **options)

    def test_default_destination_preserves_source_and_raw_hash(self):
        before = {p.name: p.read_bytes() for p in self.artifacts.iterdir()}
        paths = self.export(elapsed_seconds=1.25)
        self.assertEqual(paths["report"], self.repo / "docs/repo-maps/repo-map.python.md")
        self.assertEqual(paths["raw"].read_bytes(), self.raw.encode())
        self.assertEqual(paths["inventory"].read_bytes(), before["inventory.json"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.artifacts.iterdir()})
        metadata = json.loads(paths["metadata"].read_text())
        self.assertEqual(metadata["map_sha256"], self.metadata["map_sha256"])
        self.assertEqual(metadata["revision"], "abc123")
        self.assertEqual(metadata["export"]["generation_elapsed_seconds"], 1.25)
        self.assertEqual(metadata["export"]["raw_estimated_tokens"], math.ceil(len(self.raw) / 4))
        report = paths["report"].read_text(encoding="utf-8")
        self.assertEqual(metadata["export"]["report_estimated_tokens"], math.ceil(len(report) / 4))
        self.assertEqual(metadata["export"]["report_sha256"], hashlib.sha256(report.encode()).hexdigest())
        self.assertIn("scan or map is truncated", report)
        self.assertIn("Files selected / parsed: 3 / 2", report)
        self.assertIn("Definitions found / selected: 7 / 1", report)
        self.assertIn("abc123", report)
        self.assertIn("1.25 seconds", report)
        self.assertTrue(report.endswith(self.raw))

    def test_default_keeps_evidence_out_of_agent_report_directory(self):
        paths = self.export()
        self.assertEqual(paths["raw"].parent, paths["report"].parent / "artifacts/repo-map.python")
        self.assertEqual(sorted(p.name for p in paths["report"].parent.iterdir()),
                         ["artifacts", "repo-map.python.md"])
        self.assertIn("artifacts/repo-map.python/repo-map.python.meta.json",
                      paths["report"].read_text(encoding="utf-8"))

    def test_custom_evidence_directory_and_header_selection(self):
        self.metadata["rendering"] = {"format": "grouped", "clipped_declarations": []}
        self.metadata["selection"] = {"mode": "budget"}
        self.write_artifacts()
        evidence = self.base / "archived evidence"
        paths = self.export(evidence_dir=evidence)
        self.assertEqual(paths["metadata"].parent, evidence)
        report = paths["report"].read_text(encoding="utf-8")
        self.assertIn("budget / grouped", report)
        self.assertIn("Captured definitions omitted: 6", report)
        self.assertIn("Declaration snippets clipped: 0", report)
        self.assertEqual(json.loads(paths["metadata"].read_text(encoding="utf-8"))["export"]["evidence_dir"], str(evidence))

    def test_invalid_rendering_and_selection_fail_before_any_publication(self):
        cases = [
            {"selection": None}, {"selection": []},
            {"selection": {"mode": "all-definitions"}},
            {"rendering": None}, {"rendering": []},
            {"rendering": {"format": "grouped", "clipped_declarations": "bad"}},
            {"rendering": {"format": "grouped", "clipped_declarations": [None]}},
            {"coverage": {**self.metadata["coverage"], "definitions_omitted": 999}},
        ]
        original = dict(self.metadata)
        for changes in cases:
            with self.subTest(changes=changes):
                self.metadata = {**original, **changes}
                self.write_artifacts()
                with self.assertRaises(ValueError):
                    self.export()
                self.assertFalse((self.repo / "docs").exists())

    def test_evidence_cannot_replace_generation_artifacts(self):
        before = {p.name: p.read_bytes() for p in self.artifacts.iterdir()}
        with self.assertRaisesRegex(ValueError, "artifact"):
            self.export(evidence_dir=self.artifacts)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.artifacts.iterdir()})
        self.assertFalse((self.repo / "docs").exists())

    def test_custom_filename_and_unmeasured_time(self):
        output = self.base / "custom/my named map.md"
        paths = self.export(output_file=output)
        self.assertEqual(paths["report"], output)
        self.assertEqual(paths["raw"].name, "my named map.raw.md")
        self.assertEqual(paths["metadata"].name, "my named map.meta.json")
        self.assertEqual(paths["inventory"].name, "my named map.inventory.json")
        self.assertIn("not supplied", output.read_text())
        self.assertNotIn("generation_elapsed_seconds", json.loads(paths["metadata"].read_text())["export"])

    def test_missing_failed_and_inventory_only_artifacts_do_not_publish(self):
        for status in ("failed", "in-progress", "inventory-only"):
            with self.subTest(status=status):
                self.metadata["status"] = status
                self.write_artifacts()
                with self.assertRaisesRegex(ValueError, "complete"):
                    self.export()
                self.assertFalse((self.repo / "docs").exists())
        self.metadata["status"] = "complete"
        self.write_artifacts()
        (self.artifacts / "inventory.json").unlink()
        with self.assertRaises((ValueError, OSError)):
            self.export()
        self.assertFalse((self.repo / "docs").exists())

    def test_invalid_timing_and_implementation_do_not_publish(self):
        for elapsed in (-1, float("inf"), float("nan"), "1", True):
            with self.subTest(elapsed=elapsed):
                with self.assertRaisesRegex(ValueError, "elapsed"):
                    self.export(elapsed_seconds=elapsed)
        with self.assertRaisesRegex(ValueError, "implementation"):
            export_map(self.repo, self.artifacts, implementation="unknown")
        self.assertFalse((self.repo / "docs").exists())

    def test_collision_refusal_and_force_preserve_existing_without_force(self):
        destination = self.repo / "docs/repo-maps"
        destination.mkdir(parents=True)
        evidence = destination / "artifacts/repo-map.python"
        evidence.mkdir(parents=True)
        collision = evidence / "repo-map.python.inventory.json"
        collision.write_text("keep this")
        with self.assertRaisesRegex(ValueError, "exists"):
            self.export()
        self.assertEqual(collision.read_text(), "keep this")
        self.assertEqual([p.name for p in evidence.iterdir()], [collision.name])
        paths = self.export(force=True)
        self.assertEqual(paths["inventory"].read_bytes(), (self.artifacts / "inventory.json").read_bytes())

    def test_corrupt_hash_or_wrong_repository_is_rejected_before_writes(self):
        self.metadata["map_sha256"] = "0" * 64
        self.write_artifacts()
        with self.assertRaisesRegex(ValueError, "hash"):
            self.export()
        self.metadata["map_sha256"] = hashlib.sha256(self.raw.encode()).hexdigest()
        self.metadata["source_root"] = str(self.base)
        self.write_artifacts()
        with self.assertRaisesRegex(ValueError, "repository"):
            self.export()
        self.assertFalse((self.repo / "docs").exists())

    def test_refuses_artifacts_inside_repository_and_outputs_inside_artifacts(self):
        for artifact_dir in (self.repo, self.repo / "cache"):
            with self.subTest(artifact_dir=artifact_dir):
                artifact_dir.mkdir(exist_ok=True)
                with self.assertRaisesRegex(ValueError, "outside"):
                    export_map(self.repo, artifact_dir, implementation="rust")
        with self.assertRaisesRegex(ValueError, "artifact"):
            self.export(output_file=self.artifacts / "copy.md")
        self.assertFalse((self.artifacts / "copy.md").exists())

    def test_incomplete_metadata_and_mismatched_inventory_are_rejected(self):
        self.metadata["coverage"].pop("parsed_files")
        self.write_artifacts()
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.export()
        self.metadata["coverage"]["parsed_files"] = 2
        self.inventory["revision"] = "different"
        self.write_artifacts()
        with self.assertRaisesRegex(ValueError, "revision"):
            self.export()
        self.assertFalse((self.repo / "docs").exists())

    def test_missing_or_empty_fingerprints_reject_before_creating_outputs(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.metadata["working_copy_fingerprint"] = value
                self.inventory["fingerprint"] = value
                self.write_artifacts()
                with self.assertRaisesRegex(ValueError, "fingerprint"):
                    self.export()
                self.assertFalse((self.repo / "docs").exists())
        self.metadata.pop("working_copy_fingerprint")
        self.inventory.pop("fingerprint")
        self.write_artifacts()
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.export()
        self.assertFalse((self.repo / "docs").exists())

    def test_unsupported_hard_links_fall_back_to_exclusive_creation(self):
        with patch("export_repo_map.os.link", side_effect=OSError(errno.ENOTSUP, "links unsupported")):
            paths = self.export()
        self.assertEqual(paths["raw"].read_bytes(), self.raw.encode())
        self.assertTrue(paths["report"].read_text(encoding="utf-8").endswith(self.raw))
        self.assertEqual(list(paths["report"].parent.glob(".repo-map-export-*")), [])

    def test_fallback_refuses_concurrently_created_destination(self):
        def unsupported_link(_source, destination):
            destination.write_bytes(b"concurrent writer owns this")
            raise OSError(errno.ENOTSUP, "links unsupported")

        with patch("export_repo_map.os.link", side_effect=unsupported_link):
            with self.assertRaisesRegex(ValueError, "exists"):
                self.export()
        destination = self.repo / "docs/repo-maps"
        self.assertEqual((destination / "artifacts/repo-map.python/repo-map.python.raw.md").read_bytes(), b"concurrent writer owns this")
        self.assertFalse((destination / "repo-map.python.md").exists())
        self.assertEqual(list(destination.glob(".repo-map-export-*")), [])

    def test_fallback_write_failure_removes_only_its_partial_output(self):
        def fail_copy(_source, destination):
            destination.write(b"partial")
            raise OSError(errno.EIO, "injected copy failure")

        with patch("export_repo_map.os.link", side_effect=OSError(errno.ENOTSUP, "links unsupported")), \
             patch("export_repo_map.shutil.copyfileobj", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "injected copy"):
                self.export()
        destination = self.repo / "docs/repo-maps"
        self.assertEqual(list(destination.rglob("*.md")), [])
        self.assertEqual(list(destination.rglob(".repo-map-export-*")), [])

    def test_fallback_failure_keeps_another_writers_replacement(self):
        real_open = Path.open

        class ReplaceOnClose:
            def __init__(self, path, handle):
                self.path, self.handle = path, handle

            def __enter__(self):
                return self.handle.__enter__()

            def __exit__(self, kind, value, traceback):
                result = self.handle.__exit__(kind, value, traceback)
                if kind is not None:
                    self.path.rename(self.path.with_name("interrupted-output"))
                    self.path.write_bytes(b"concurrent replacement")
                return result

        def replacement_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            if args and args[0] == "xb":
                return ReplaceOnClose(path, handle)
            return handle

        def fail_copy(_source, destination):
            destination.write(b"partial")
            raise OSError(errno.EIO, "injected copy failure")

        with patch("export_repo_map.os.link", side_effect=OSError(errno.ENOTSUP, "links unsupported")), \
             patch.object(Path, "open", autospec=True, side_effect=replacement_open), \
             patch("export_repo_map.shutil.copyfileobj", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "injected copy"):
                self.export()
        destination = self.repo / "docs/repo-maps"
        self.assertEqual((destination / "artifacts/repo-map.python/repo-map.python.raw.md").read_bytes(), b"concurrent replacement")
        self.assertFalse((destination / "repo-map.python.md").exists())

    def test_force_staging_failure_preserves_prior_report(self):
        paths = self.export()
        before = {name: path.read_bytes() for name, path in paths.items()}
        real_temporary = tempfile.NamedTemporaryFile
        creations = 0

        def fail_staging(*args, **kwargs):
            nonlocal creations
            creations += 1
            if creations == 2:
                raise OSError(errno.EIO, "injected staging failure")
            return real_temporary(*args, **kwargs)

        with patch("export_repo_map.tempfile.NamedTemporaryFile", side_effect=fail_staging):
            with self.assertRaisesRegex(OSError, "injected staging"):
                self.export(force=True)
        self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, before)
        self.assertEqual(list(paths["report"].parent.glob(".repo-map-export-*")), [])

    def test_failed_force_replacement_invalidates_old_report(self):
        paths = self.export()
        paths["report"].write_text("OLD REPORT MUST NOT SURVIVE")
        old_inventory = paths["inventory"].read_bytes()
        real_replace = __import__("os").replace
        replacements = 0

        def interrupt_replace(source, destination):
            nonlocal replacements
            replacements += 1
            if replacements == 2:
                raise OSError(errno.EIO, "injected inventory publication failure")
            return real_replace(source, destination)

        with patch("export_repo_map.os.replace", side_effect=interrupt_replace):
            with self.assertRaisesRegex(OSError, "injected inventory"):
                self.export(force=True)
        self.assertEqual(replacements, 2)
        self.assertFalse(paths["report"].exists())
        self.assertEqual(paths["inventory"].read_bytes(), old_inventory)
        self.assertEqual(list(paths["raw"].parent.glob(".repo-map-export-*")), [])

    def test_cli_accepts_named_report_and_rejects_invalid_elapsed(self):
        output = self.base / "CLI report.md"
        result = subprocess.run([sys.executable, str(SCRIPTS / "export_repo_map.py"), str(self.repo),
                                 "--artifact-dir", str(self.artifacts), "--implementation", "bundle",
                                 "--output-file", str(output), "--evidence-dir", str(self.base / "saved evidence"), "--elapsed-seconds", "0.5"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["report"], str(output))
        result = subprocess.run([sys.executable, str(SCRIPTS / "export_repo_map.py"), str(self.repo),
                                 "--artifact-dir", str(self.artifacts), "--implementation", "bundle",
                                 "--elapsed-seconds", "nan"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("elapsed", result.stderr)



    def test_compact_selection_controls_and_actual_coverage_preserve_literals(self):
        self.raw = '# Repository map\n\n## a.py\n\nL1: def f(value="keep  two `ticks`"):\n\n'
        self.metadata["map_sha256"] = hashlib.sha256(self.raw.encode()).hexdigest()
        self.metadata["rendering"] = {"format": "compact", "clipped_declarations": []}
        self.metadata["selection"] = {"mode": "ranked", "requested_coverage_percent": 20, "requested_max_definitions": None, "effective_max_definitions": 2, "coverage_percent": 100 / 7, "selection_limit_reached": False}
        self.write_artifacts()
        paths = self.export()
        report = paths["report"].read_text(encoding="utf-8")
        self.assertIn("ranked / compact", report)
        self.assertIn("Requested coverage: 20%", report)
        self.assertIn("Effective maximum definitions: 2", report)
        self.assertIn("Actual captured-definition coverage: 14.2857%", report)
        self.assertIn('"keep  two `ticks`"', report)
        self.assertNotIn("status `complete`",report)
        sidecar = json.loads(paths["metadata"].read_text())
        self.assertEqual(sidecar["export"]["report_estimated_tokens"],math.ceil(len(report)/4))
        self.assertEqual(paths["raw"].read_text(),self.raw)

    def test_inconsistent_selection_caps_fail_before_publication(self):
        base = {"mode": "ranked", "requested_coverage_percent": 20, "requested_max_definitions": None, "effective_max_definitions": 2, "coverage_percent": 100 / 7, "selection_limit_reached": False}
        for change in ({"coverage_percent": 99}, {"coverage_percent":10**1000}, {"requested_coverage_percent":10**1000}, {"effective_max_definitions": 0}, {"requested_max_definitions": 1}, {"selection_limit_reached": True}, {"requested_coverage_percent": float("nan")}):
            with self.subTest(change=change):
                self.metadata["selection"] = {**base,**change}
                self.write_artifacts()
                with self.assertRaises(ValueError):
                    self.export()
                self.assertFalse((self.repo/"docs").exists())


if __name__ == "__main__":
    unittest.main()
