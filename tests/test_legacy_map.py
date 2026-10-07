"""Functional checks for the offline legacy repository map and citation verifier."""

import os
import json
from unittest.mock import patch
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from check_citations import check_cards
from repo_files import read_safe_text, scan_repository
from repo_map import generate


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "source with spaces"
        self.repo.mkdir()
        self.out = self.base / "artifacts"

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def map(self, **options):
        return generate(self.repo, self.out, **options)

    def test_java_python_typescript_definitions_focus_and_budget(self):
        self.write("src/École.java", "class École {\n  void calculer() {}\n}\n")
        self.write("src/app.py", "def fetch_data():\n    return 1\n")
        self.write("src/view.ts", "export function renderView() { return 2; }\n")
        self.write("src/more.py", "".join(f"def extra_{n}(): return {n}\n" for n in range(20)))
        meta = self.map(budget=128, focus_symbols=["renderView"])
        content = (self.out / "repo-map.md").read_text()
        self.assertIn("view.ts:L1", content)
        self.assertLessEqual(meta["estimated_tokens"], 128)
        self.assertTrue(meta["truncated"])
        full = self.map(budget=4096, focus_symbols=["renderView"])
        content = (self.out / "repo-map.md").read_text()
        self.assertIn("École.java:L1", content)
        self.assertIn("app.py:L1", content)
        self.assertIn("view.ts:L1", content)
        self.assertGreaterEqual(full["coverage"]["definitions_found"], 3)
        before = [(self.out / n).read_bytes() for n in ("repo-map.md", "inventory.json", "map.meta.json")]
        self.map(budget=4096, focus_symbols=["renderView"])
        self.assertEqual(before, [(self.out / n).read_bytes() for n in ("repo-map.md", "inventory.json", "map.meta.json")])

    def test_changed_same_mtime_deleted_and_poisoned_cache(self):
        path = self.write("a.py", "def alpha():\n    pass\n")
        first = self.map()
        old_mtime = path.stat().st_mtime_ns
        path.write_text("def omega():\n    pass\n", encoding="utf-8")
        os.utime(path, ns=(old_mtime, old_mtime))
        second = self.map()
        self.assertNotEqual(first["working_copy_fingerprint"], second["working_copy_fingerprint"])
        self.assertIn("omega", (self.out / "repo-map.md").read_text())
        self.assertNotIn("alpha", (self.out / "repo-map.md").read_text())
        for cache in (self.out / "cache").glob("*.json"):
            cache.write_text('{"tags": "poison"}', encoding="utf-8")
        self.map()
        self.assertIn("omega", (self.out / "repo-map.md").read_text())
        path.unlink()
        last = self.map()
        self.assertEqual(last["coverage"]["definitions_found"], 0)

    def test_git_ignore_tracked_secret_symlink_and_non_git_ignore(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write(".gitignore", "ignored.py\n")
        self.write("ignored.py", "def ignored(): pass\n")
        self.write("tracked.py", "def kept(): pass\n")
        self.write(".env", "TOKEN=must_not_read\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "-f", ".env"], check=True)
        outside = self.base / "outside.py"
        outside.write_text("def outside(): pass\n")
        (self.repo / "link.py").symlink_to(outside)
        inventory = scan_repository(self.repo)
        paths = {item["path"] for item in inventory["files"]}
        self.assertIn("tracked.py", paths)
        self.assertNotIn("ignored.py", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("link.py", paths)
        self.assertTrue(any(item["path"] == ".env" and "secret" in item["reason"] for item in inventory["skipped"]))
        self.assertTrue(any(item["path"] == "link.py" and "symlink" in item["reason"] for item in inventory["skipped"]))
        subprocess.run(["git", "-C", str(self.repo), "add", "-f", "ignored.py"], check=True)
        self.assertIn("ignored.py", {item["path"] for item in scan_repository(self.repo)["files"]})
        (self.repo / "loop").symlink_to(self.repo, target_is_directory=True)
        (self.repo / ".git").rename(self.base / "hidden-git")
        inventory = scan_repository(self.repo)
        self.assertNotIn("ignored.py", {item["path"] for item in inventory["files"]})
        self.assertFalse(any(item["path"].startswith("loop/") for item in inventory["files"]))

    def test_descriptors_unicode_crlf_unsupported_limits(self):
        self.write("build.xml", "<project/>\n")
        self.write("build.gradle.kts", "plugins {}\n")
        self.write("setup.properties", "key=value\n")
        self.write("x.kt", "class Unsupported {}\n")
        self.write("src/żółć.py", "def ścieżka():\r\n    return 1\r\n")
        meta = self.map()
        self.assertIn("build.xml", meta["descriptors"])
        self.assertIn("build.gradle.kts", meta["descriptors"])
        self.assertIn("setup.properties", meta["descriptors"])
        self.assertIn("żółć.py:L1", (self.out / "repo-map.md").read_text())
        self.assertEqual(meta["coverage"]["parsed_files"], 1)
        self.assertIn("x.kt", meta["unsupported_languages"])
        with self.assertRaisesRegex(ValueError, "outside"):
            generate(self.repo, self.repo / "cache")
        with self.assertRaisesRegex(ValueError, "limits"):
            scan_repository(self.repo, max_files=0)
        capped = scan_repository(self.repo, max_files=1)
        self.assertTrue(any(x["path"] == "*" for x in capped["skipped"]))
        self.write("large.py", "def very_large(): pass\n")
        limited = scan_repository(self.repo, max_file_bytes=5)
        self.assertTrue(any(x["path"] == "large.py" and "max_file_bytes" in x["reason"] for x in limited["skipped"]))

    def test_subtree_finds_module_past_global_cap(self):
        for index in range(5):
            self.write(f"a/{index}.py", "def other(): pass\n")
        self.write("z/main.py", "def desired(): pass\n")
        meta = self.map(subtrees=["z"], max_files=1)
        self.assertEqual(meta["coverage"]["selected_files"], 1)
        self.assertIn("desired", (self.out / "repo-map.md").read_text())

    def test_nested_ignored_directory_is_scanned_as_non_git(self):
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)
        (self.base / ".gitignore").write_text("source with spaces/\n", encoding="utf-8")
        self.write("a.py", "def visible(): pass\n")
        inventory = scan_repository(self.repo)
        self.assertFalse(inventory["git"])
        self.assertIn("a.py", {item["path"] for item in inventory["files"]})

    def test_focus_file_remains_visible_in_small_budget(self):
        self.write("a.py", "".join(f"def other_{n}(): pass\n" for n in range(30)))
        self.write("z.py", "def target(): pass\n")
        self.map(budget=64, focus_files=["z.py"])
        self.assertIn("z.py:L1", (self.out / "repo-map.md").read_text())

    def test_output_symlinks_cannot_redirect_writes_into_source(self):
        self.write("a.py", "def safe(): pass\n")
        target = self.write("important.txt", "DO NOT CHANGE\n")
        self.out.mkdir()
        (self.out / "repo-map.md").symlink_to(target)
        self.map()
        self.assertEqual(target.read_text(), "DO NOT CHANGE\n")
        self.assertFalse((self.out / "repo-map.md").is_symlink())
        (self.out / "cache").rename(self.out / "old-cache")
        (self.out / "cache").symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cache path"):
            self.map()
        self.assertEqual(target.read_text(), "DO NOT CHANGE\n")

    def test_offline_process(self):
        self.write("a.py", "def alpha(): pass\n")
        guard = self.base / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text("import socket\ndef deny(*args, **kwargs): raise RuntimeError('network denied')\nsocket.socket=deny\nsocket.create_connection=deny\n")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(guard), env.get("PYTHONPATH", "")])
        result = subprocess.run([sys.executable, str(SCRIPTS / "repo_map.py"), str(self.repo), "--output-dir", str(self.out)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        query_check = "import sys; sys.path.insert(0, %r); from repo_map import _query, QUERY_PATHS; [_query(name) for name in QUERY_PATHS]" % str(SCRIPTS)
        result = subprocess.run([sys.executable, "-c", query_check], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_clean_filter_is_never_executed(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write("a.py", "def alpha(): pass\n")
        self.write(".gitattributes", "a.py filter=untrusted\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "a.py", ".gitattributes"], check=True)
        marker = self.base / "filter-was-run"
        script = self.base / "filter.py"
        script.write_text("from pathlib import Path; import sys; Path(%r).touch(); print(sys.stdin.read())" % str(marker))
        subprocess.run(["git", "-C", str(self.repo), "config", "filter.untrusted.clean", f'"{sys.executable}" "{script}"'], check=True)
        self.write("a.py", "def changed(): pass\n")
        inventory = scan_repository(self.repo)
        self.assertIsNone(inventory["dirty"])
        self.assertTrue(inventory["git_notes"])
        self.assertFalse(marker.exists())

    def test_failed_scan_invalidates_previous_successful_artifacts(self):
        self.write("a.py", "def alpha(): pass\n")
        self.map()
        with patch("repo_map.scan_repository", side_effect=ValueError("cannot inventory directory")):
            with self.assertRaisesRegex(ValueError, "cannot inventory"):
                self.map()
        meta = json.loads((self.out / "map.meta.json").read_text())
        inventory = json.loads((self.out / "inventory.json").read_text())
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "inventory")
        self.assertEqual(inventory["status"], "failed")
        self.assertIsNone(meta["coverage"])
        self.assertNotIn("alpha", (self.out / "repo-map.md").read_text())

    @unittest.skipUnless(os.name == "posix" and os.geteuid() != 0, "requires non-root POSIX permissions")
    def test_unreadable_subtree_is_reported_as_scan_failure(self):
        hidden = self.repo / "blocked"
        hidden.mkdir()
        self.write("blocked/a.py", "def inaccessible(): pass\n")
        hidden.chmod(0)
        try:
            with self.assertRaisesRegex(ValueError, "cannot inventory directory"):
                self.map()
            self.assertEqual(json.loads((self.out / "map.meta.json").read_text())["status"], "failed")
        finally:
            hidden.chmod(0o700)

    def test_git_trace_cannot_write_inside_source(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write("a.py", "def alpha(): pass\n")
        trace = self.repo / "trace.log"
        with patch.dict(os.environ, {"GIT_TRACE": str(trace), "GIT_TRACE2_EVENT": str(trace)}):
            self.map()
        self.assertFalse(trace.exists())

    def test_form_feed_does_not_shift_original_line_numbers(self):
        self.write("a.py", "# comment\fcontinued\n\ndef real_definition():\n    pass\n")
        self.map()
        self.assertIn("a.py:L3: def real_definition():", (self.out / "repo-map.md").read_text())
        _text, digest = read_safe_text(self.repo, "a.py")
        card = {"path": "a.py", "sha256": digest, "start_line": 3, "end_line": 3, "quote": "def real_definition():"}
        self.assertTrue(check_cards(self.repo, {"citations": [card]})["valid"])
        self.write("b.py", "def crlf():\r\n    pass\r\n")
        _text, digest = read_safe_text(self.repo, "b.py")
        self.assertTrue(check_cards(self.repo, {"citations": [{"path": "b.py", "sha256": digest, "start_line": 1, "end_line": 2, "quote": "def crlf():\n    pass"}]})["valid"])

    def test_inventory_only_without_parser_dependencies(self):
        self.write("src/a.py", "def alpha(): pass\n")
        with patch("repo_map._packages", side_effect=ImportError("not installed")), patch("repo_map._tags", side_effect=AssertionError("must not parse")):
            meta = self.map(inventory_only=True)
        self.assertEqual(meta["status"], "inventory-only")
        self.assertIsNone(meta["coverage"]["definitions_found"])
        self.assertEqual(meta["coverage"]["selected_files"], 1)
        self.assertFalse((self.out / "cache").exists())
        self.assertEqual(meta["inventory_summary"]["languages"]["python"], 1)

    def test_ranking_limit_preserves_fresh_inventory_and_invalidates_old_map(self):
        self.write("src/a.py", "def alpha(): pass\n")
        self.map()
        self.write("src/b.py", "def beta(): pass\n")
        with patch("repo_map.rank_tags", side_effect=ValueError("ranking edge limit exceeded")):
            with self.assertRaisesRegex(ValueError, "ranking edge limit"):
                self.map()
        meta = json.loads((self.out / "map.meta.json").read_text())
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "ranking")
        self.assertIsNone(meta["map_sha256"])
        self.assertIn("src/b.py", {x["path"] for x in json.loads((self.out / "inventory.json").read_text())["files"]})
        self.assertNotIn("alpha", (self.out / "repo-map.md").read_text())

    def test_citations_exact_hash_lines_and_quote(self):
        self.write("src/a.py", "def alpha():\n    return 1\n")
        _text, digest = read_safe_text(self.repo, "src/a.py")
        card = {"path": "src/a.py", "sha256": digest, "start_line": 1, "end_line": 2, "quote": "return 1"}
        self.assertTrue(check_cards(self.repo, {"citations": [card]})["valid"])
        for bad in [{**card, "sha256": "0" * 64}, {**card, "quote": "return 2"}, {**card, "end_line": 99}, {**card, "path": "../outside.py"}]:
            self.assertFalse(check_cards(self.repo, {"citations": [bad]})["valid"])
        self.write("src/a.py", "def alpha():\n    return 2\n")
        self.assertFalse(check_cards(self.repo, {"citations": [card]})["valid"])


if __name__ == "__main__":
    unittest.main()
