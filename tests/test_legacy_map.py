"""Functional checks for the offline legacy repository map and citation verifier."""

import os
import errno
import hashlib
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
from repo_files import contains_control_characters, read_safe_text, safe_path_display, scan_repository
from repo_map import generate


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        git_environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        git_environment.start()
        self.addCleanup(git_environment.stop)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "source with spaces"
        self.repo.mkdir()
        self.out = self.base / "artifacts"

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def map(self, **options):
        return generate(self.repo, self.out, **options)

    def test_java_python_typescript_definitions_focus_and_budget(self):
        self.write("src/École.java", "class École {\n  void calculer() {}\n}\n")
        self.write("src/app.py", "def fetch_data():\n    return 1\n")
        self.write("src/view.ts", "export function renderView() { return 2; }\n")
        self.write("src/more.py", "".join(f"def extra_{n}(): return {n}\n" for n in range(20)))
        meta = self.map(budget=128, focus_symbols=["renderView"])
        content = (self.out / "repo-map.md").read_text(encoding="utf-8")
        self.assertIn("view.ts:L1", content)
        self.assertLessEqual(meta["estimated_tokens"], 128)
        self.assertTrue(meta["truncated"])
        full = self.map(budget=4096, focus_symbols=["renderView"])
        content = (self.out / "repo-map.md").read_text(encoding="utf-8")
        self.assertIn("École.java:L1", content)
        self.assertIn("app.py:L1", content)
        self.assertIn("view.ts:L1", content)
        self.assertGreaterEqual(full["coverage"]["definitions_found"], 3)
        before = [(self.out / n).read_bytes() for n in ("repo-map.md", "inventory.json", "map.meta.json")]
        self.map(budget=4096, focus_symbols=["renderView"])
        self.assertEqual(before, [(self.out / n).read_bytes() for n in ("repo-map.md", "inventory.json", "map.meta.json")])

    def test_focus_paths_normalize_before_ranking_and_report_missing_targets(self):
        self.write("src/a.java", "class Preferred { void selected() {} }\n")
        self.write("src/b.java", "class Ordinary { void other() {} }\n")
        baseline = self.map(focus_files=["src/a.java"])
        content = (self.out / "repo-map.md").read_bytes()
        for path in ("./src/a.java", "src\\a.java"):
            with self.subTest(path=path):
                meta = self.map(focus_files=[path])
                self.assertEqual(meta["selection"]["focus_files"], ["src/a.java"])
                self.assertEqual(meta["focus_not_found"]["files_not_parsed"], [])
                self.assertEqual(content, (self.out / "repo-map.md").read_bytes())
        missing = self.map(focus_files=["./src/missing.java"], focus_symbols=["ImaginaryMethod"])
        self.assertEqual(missing["focus_not_found"], {"files_not_parsed": ["src/missing.java"], "symbols_without_definitions": ["ImaginaryMethod"]})
        self.assertEqual(baseline["focus_not_found"]["files_not_parsed"], [])
        for unsafe in ("../outside.java", "..\\outside.java"):
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                self.map(focus_files=[unsafe])

    def test_non_git_ignore_directory_anchors_scope_and_negation(self):
        self.write(".gitignore", "target/\n/dist\n*.tmp\n")
        self.write("moduleA/.gitignore", "cache/\n/local/\n!keep.tmp\n*.drop\n!keep.drop\nblocked/\n!blocked/rescue.java\n")
        excluded = ["moduleA/target/classes/Foo.java", "dist/Root.java", "moduleA/cache/Cached.java", "moduleA/deep/cache/Cached.java", "moduleA/local/Local.java", "moduleB/file.tmp", "moduleA/file.drop", "moduleA/blocked/rescue.java"]
        kept = ["moduleA/deep/dist/Kept.java", "moduleB/dist/Kept.java", "moduleA/deep/local/Kept.java", "moduleB/cache/Kept.java", "moduleA/keep.tmp", "moduleA/keep.drop", "moduleB/target"]
        for name in excluded + kept:
            self.write(name, "class Example {}\n")
        visited = []
        original = os.scandir
        def observe(directory):
            visited.append(Path(directory).relative_to(self.repo).as_posix())
            return original(directory)
        with patch("repo_files.os.scandir", side_effect=observe):
            inventory = scan_repository(self.repo)
        paths = {entry["path"] for entry in inventory["files"]}
        self.assertTrue(set(kept).issubset(paths))
        self.assertFalse(set(excluded) & paths)
        for directory in ("moduleA/target", "moduleA/cache", "moduleA/deep/cache", "moduleA/blocked", "dist"):
            self.assertNotIn(directory, visited)
        self.assertIn("moduleA/deep/local", visited)
        # The same basic policies agree with Git's actual ignore engine.
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.assertEqual(paths, {entry["path"] for entry in scan_repository(self.repo)["files"]})

    def test_anchored_and_slashed_ignore_wildcards_do_not_cross_directories(self):
        self.write(".gitignore", "/*.java\ndocs/*.txt\nlogs/*.log\n")
        self.write("module/.gitignore", "/*.java\n")
        excluded = ["Scratch.java", "docs/Direct.txt", "logs/Direct.log", "module/Scratch.java"]
        kept = ["src/main/App.java", "src/main/Util.java", "docs/deep/Nested.txt", "logs/deep/Nested.log", "module/src/App.java", "other/docs/Elsewhere.txt"]
        for name in excluded + kept:
            self.write(name, "class Example {}\n")
        fallback = {entry["path"] for entry in scan_repository(self.repo)["files"]}
        self.assertTrue(set(kept).issubset(fallback))
        self.assertFalse(set(excluded) & fallback)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.assertEqual(fallback, {entry["path"] for entry in scan_repository(self.repo)["files"]})

    def test_directory_whitelist_negation_does_not_restore_nonmatching_files(self):
        self.write(".gitignore", "*\n!*/\n!*.java\n")
        kept = ["Root.java", "src/App.java", "src/deep/Util.java", "out/Generated.java"]
        excluded = ["out/cache.json", "src/generated-report.xml", "src/deep/cache.txt", "Root.txt"]
        for name in kept + excluded:
            self.write(name, "class Example {}\n")
        fallback = {entry["path"] for entry in scan_repository(self.repo)["files"]}
        self.assertEqual(fallback, set(kept))
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.assertEqual(fallback, {entry["path"] for entry in scan_repository(self.repo)["files"]})

    def test_ancestor_directory_negation_does_not_restore_excluded_xml(self):
        original = self.repo
        for negation in ("!reports", "!reports/"):
            with self.subTest(negation=negation):
                self.repo = original / ("directory-rule" if negation.endswith("/") else "basename-rule")
                self.repo.mkdir()
                self.write(".gitignore", "*.xml\n" + negation + "\n")
                self.write("reports/summary.xml", "<report/>\n")
                self.write("reports/deep/summary.xml", "<report/>\n")
                self.write("reports/keep.txt", "kept\n")
                fallback = {entry["path"] for entry in scan_repository(self.repo)["files"]}
                self.assertEqual(fallback, {".gitignore", "reports/keep.txt"})
                subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
                self.assertEqual(fallback, {entry["path"] for entry in scan_repository(self.repo)["files"]})
        self.repo = original

    @unittest.skipUnless(os.name == "posix", "requires POSIX byte filenames")
    def test_non_utf8_paths_are_counted_skipped_and_safe_in_git_and_non_git_maps(self):
        raw_path = os.fsencode(self.repo) + b"/Bad-\xff.java"
        try:
            with open(raw_path, "wb") as handle:
                handle.write(b"class MustNotParse {}\n")
        except OSError as error:
            if error.errno == errno.EILSEQ:
                self.skipTest("filesystem does not support invalid UTF-8 filenames (EILSEQ)")
            raise
        self.write("Good.java", "class Good {}\n")
        for git in (False, True):
            if git:
                subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
                subprocess.run([b"git", b"-C", os.fsencode(self.repo), b"add", b"--", b"Bad-\xff.java", b"Good.java"], check=True)
            for excludes in ((), ("Bad-*",)):
                with self.subTest(git=git, excludes=excludes):
                    meta = self.map(excludes=excludes)
                    self.assertEqual(meta["status"], "complete")
                    self.assertEqual(meta["coverage"]["candidates_seen"], 2)
                    self.assertEqual(meta["skipped"], [{"path": "Bad-\ufffd.java", "reason": "non-UTF-8 path"}])
                    self.assertEqual(len(meta["working_copy_fingerprint"]), 64)
                    self.assertIn("Good.java", (self.out / "repo-map.md").read_text(encoding="utf-8"))
                    for name in ("repo-map.md", "inventory.json", "map.meta.json"):
                        (self.out / name).read_bytes().decode("utf-8")
            capped = self.map(max_files=1)
            self.assertEqual(capped["coverage"]["candidates_seen"], 2)
            self.assertEqual(capped["coverage"]["selected_files"], 0)
            self.assertEqual(capped["skipped"][0]["reason"], "non-UTF-8 path")
            self.assertTrue(capped["truncated"])
            with open(raw_path, "rb") as handle:
                self.assertEqual(handle.read(), b"class MustNotParse {}\n")

    def test_git_conflict_entries_deduplicate_without_recent_git_option(self):
        self.write("a.py", "def alpha(): pass\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        blob = subprocess.check_output(["git", "-C", str(self.repo), "hash-object", "-w", "a.py"], text=True).strip()
        stages = "".join(f"100644 {blob} {stage}\ta.py\n" for stage in (1, 2, 3))
        subprocess.run(["git", "-C", str(self.repo), "update-index", "--index-info"], input=stages.encode("utf-8"), check=True)
        raw = subprocess.check_output(["git", "-C", str(self.repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        self.assertEqual(raw.count(b"a.py\0"), 3)
        real_popen = subprocess.Popen
        with patch("repo_files.subprocess.Popen", wraps=real_popen) as launched:
            inventory = scan_repository(self.repo, max_files=1)
        ls_calls = [call.args[0] for call in launched.call_args_list if "ls-files" in call.args[0]]
        self.assertEqual(len(ls_calls), 1)
        self.assertNotIn("--deduplicate", ls_calls[0])
        self.assertEqual([entry["path"] for entry in inventory["files"]], ["a.py"])
        self.assertEqual(inventory["totals"]["candidates_seen"], 1)
        self.assertEqual(inventory["skipped"], [])

    def test_vendor_manifest_lists_existing_resources_with_exact_hashes(self):
        vendor = SCRIPTS.parent / "vendor"
        manifest = json.loads((vendor / "manifest.json").read_text(encoding="utf-8"))
        paths = [entry["vendored_path"] for entry in manifest["entries"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertNotIn("manifest.json", paths)
        self.assertFalse(any("__pycache__" in Path(path).parts or path.endswith(".pyc") for path in paths))
        for entry in manifest["entries"]:
            with self.subTest(path=entry["vendored_path"]):
                path = vendor / entry["vendored_path"]
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["vendored_sha256"])
        actual = {path.relative_to(vendor).as_posix() for path in vendor.rglob("*") if path.is_file() and path.name != "manifest.json" and "__pycache__" not in path.parts and path.suffix != ".pyc"}
        self.assertEqual(set(paths), actual)

    def test_csharp_cache_invalidates_when_separate_grammar_version_changes(self):
        import repo_map
        self.write("src/Example.cs", "class Example { public void Run() {} }\n")
        first = self.map()
        self.assertEqual(first["coverage"]["parsed_files"], 1)
        self.assertEqual(first["dependencies"]["tree-sitter-c-sharp"], "0.23.5")
        with patch("repo_map._extract", wraps=repo_map._extract) as extract:
            self.map()
            extract.assert_not_called()
        cached = list((self.out / "cache").glob("*.json"))
        self.assertEqual(len(cached), 1)
        payload = json.loads(cached[0].read_text(encoding="utf-8"))
        self.assertTrue(payload["parser_version"].endswith(":0.23.5"))
        for tag in payload["tags"]:
            if tag["kind"] == "def":
                tag["name"] = "StaleGrammarOnly"
        cached[0].write_text(json.dumps(payload), encoding="utf-8")
        actual_version = repo_map.importlib.metadata.version
        def upgraded_version(name):
            return "0.23.6" if name == "tree-sitter-c-sharp" else actual_version(name)
        with patch("repo_map.importlib.metadata.version", side_effect=upgraded_version), patch("repo_map._extract", wraps=repo_map._extract) as extract:
            current = self.map(focus_symbols=["StaleGrammarOnly"])
        extract.assert_called_once()
        self.assertEqual(current["dependencies"]["tree-sitter-c-sharp"], "0.23.6")
        self.assertEqual(current["focus_not_found"]["symbols_without_definitions"], ["StaleGrammarOnly"])
        self.assertIn("Example.cs:L1", (self.out / "repo-map.md").read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.out / "cache").glob("*.json"))), 2)

    def test_rank_edge_caps_cover_referenced_and_unreferenced_definitions(self):
        from aider_rank import rank_tags
        def tag(name, kind, line):
            return {"path": "a.py", "line": line, "name": name, "kind": kind}
        for references in ([tag("A", "ref", 3)], [], [tag("Unknown", "ref", 3)]):
            with self.subTest(references=references):
                tags = {"a.py": [tag("A", "def", 1), tag("Z", "def", 2), *references]}
                self.assertEqual(len(rank_tags(tags, max_edges=2)), 2)
                for limit in (0, 1):
                    with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "ranking edge limit exceeded"):
                        rank_tags(tags, max_edges=limit)

    def test_control_path_display_escapes_controls_and_line_separators_reversibly(self):
        for value in (*range(32), *range(127, 160), 0x2028, 0x2029):
            name = "folder/żółć" + chr(value) + '"\\name.java'
            with self.subTest(control=value):
                self.assertTrue(contains_control_characters(name))
                display = safe_path_display(name)
                self.assertFalse(contains_control_characters(display))
                self.assertEqual(json.loads('"' + display + '"'), name)
        self.assertFalse(contains_control_characters("folder/żółć.java"))

    @unittest.skipUnless(os.name == "posix", "requires POSIX control-character filenames")
    def test_control_filenames_are_counted_without_reading_or_injecting_map_records(self):
        names = ["A-żółć\nline.java", "B-tab\tname.java", "C-del\x7fname.java", "D-esc\x1bname.java", "E-c1\x80name.java", "F-nel\x85name.java", "G-line\u2028name.java", "H-paragraph\u2029name.java"]
        for name in names:
            self.write(name, "class InjectedDefinition {}\n")
        good = self.write("Z-good.java", "class GoodDefinition {}\n")
        originals = {name: (self.repo / name).read_bytes() for name in names + [good.name]}
        for git in (False, "untracked", "tracked"):
            if git:
                subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
                if git == "tracked":
                    subprocess.run(["git", "-C", str(self.repo), "add", "--", *names, good.name], check=True)
            for excludes in ((), ("A-*",)):
                with self.subTest(git=git, excludes=excludes), patch("repo_files.read_safe_text", wraps=read_safe_text) as reader:
                    meta = self.map(excludes=excludes, budget=128)
                    self.assertEqual(meta["status"], "complete")
                    self.assertEqual(meta["coverage"]["candidates_seen"], len(names) + 1)
                    self.assertEqual(meta["coverage"]["selected_files"], 1)
                    self.assertLessEqual(meta["estimated_tokens"], 128)
                    skipped = {item["path"]: item["reason"] for item in meta["skipped"]}
                    self.assertEqual(skipped, {safe_path_display(name): "control character in path" for name in names})
                    self.assertEqual([call.args[1] for call in reader.call_args_list], [good.name])
                    content = (self.out / "repo-map.md").read_text(encoding="utf-8")
                    self.assertIn("Z-good.java:L1: class GoodDefinition", content)
                    self.assertNotIn("InjectedDefinition", content)
                    inventory = json.loads((self.out / "inventory.json").read_text(encoding="utf-8"))
                    self.assertEqual([entry["path"] for entry in inventory["files"]], [good.name])
                    for item in inventory["skipped"]:
                        self.assertFalse(contains_control_characters(item["path"]))
                        self.assertIn(json.loads('"' + item["path"] + '"'), names)
            capped = self.map(max_files=1)
            self.assertEqual(capped["coverage"]["candidates_seen"], 2)
            self.assertEqual(capped["coverage"]["selected_files"], 0)
            self.assertEqual(capped["skipped"][0]["reason"], "control character in path")
            self.assertTrue(capped["truncated"])
            for name, data in originals.items():
                self.assertEqual((self.repo / name).read_bytes(), data)
        caches = [json.loads(path.read_text(encoding="utf-8")) for path in (self.out / "cache").glob("*.json")]
        self.assertEqual(len(caches), 1)
        self.assertFalse(any(tag["name"] == "InjectedDefinition" for cache in caches for tag in cache["tags"]))

    @unittest.skipUnless(os.name == "posix", "requires literal POSIX backslash filenames")
    def test_literal_backslash_paths_preserve_inventory_hashes_and_citations(self):
        literal = self.write("a\\b.py", "def literal_backslash(): pass\n")
        nested = self.write("a/b.py", "def nested_identity(): pass\n")
        traversal_looking = self.write("..\\literal.py", "def legitimate_literal(): pass\n")
        original = {path.relative_to(self.repo).as_posix(): path.read_bytes() for path in (literal, nested, traversal_looking)}
        for git in (False, "untracked", "tracked"):
            if git:
                subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
                if git == "tracked":
                    subprocess.run(["git", "-C", str(self.repo), "add", "--", *original], check=True)
            with self.subTest(git=git):
                meta = self.map()
                inventory = json.loads((self.out / "inventory.json").read_text(encoding="utf-8"))
                entries = {item["path"]: item for item in inventory["files"]}
                self.assertEqual(set(entries), set(original))
                for name, data in original.items():
                    text, digest = read_safe_text(self.repo, name)
                    self.assertEqual(text.encode(), data)
                    self.assertEqual(entries[name]["sha256"], hashlib.sha256(data).hexdigest())
                    card = {"path": name, "sha256": digest, "start_line": 1, "end_line": 1, "quote": text.strip()}
                    self.assertTrue(check_cards(self.repo, {"citations": [card]})["valid"])
                wrong = {"path": "a\\b.py", "sha256": entries["a/b.py"]["sha256"], "start_line": 1, "end_line": 1, "quote": "nested_identity"}
                self.assertFalse(check_cards(self.repo, {"citations": [wrong]})["valid"])
                content = (self.out / "repo-map.md").read_text(encoding="utf-8")
                self.assertIn("a\\b.py:L1: def literal_backslash", content)
                self.assertIn("a/b.py:L1: def nested_identity", content)
                self.assertIn("..\\literal.py:L1: def legitimate_literal", content)
                scoped = self.map(subtrees=["a"], focus_files=["a\\b.py"])
                self.assertEqual(scoped["selection"]["focus_files"], ["a/b.py"])
                self.assertEqual(scoped["coverage"]["selected_files"], 1)
                filtered = scan_repository(self.repo, excludes=["a\\b.py"])
                self.assertNotIn("a\\b.py", {item["path"] for item in filtered["files"]})
                self.assertIn("a/b.py", {item["path"] for item in filtered["files"]})
                for name, data in original.items():
                    self.assertEqual((self.repo / name).read_bytes(), data)
        with self.assertRaises(ValueError):
            read_safe_text(self.repo, "a/../b.py")

    def test_snippets_sanitize_controls_preserving_tabs_unicode_and_original_source(self):
        import repo_map
        for value in (*range(32), *range(127, 160), 0x2028, 0x2029):
            character = chr(value)
            original_line = character + "żółć" + character + "x\tz" + character
            expected = "żółć" + ("\t" if value == 9 else " ") + "x\tz"
            with self.subTest(control=value):
                self.assertEqual(repo_map._line({"path": "source.java", "line": 1}, lambda _: [original_line]), "source.java:L1: " + expected + "\n")
        controls = "".join(chr(value) for value in (*range(1, 32), *range(127, 160), 0x2028, 0x2029) if value != 10)
        original_line = "class Hostile {\tvoid run() {} } // żółć" + controls + " marker"
        path = self.write("Hostile.java", original_line + "\r\n\nclass After {}\n")
        original_bytes = path.read_bytes()
        meta = self.map(budget=128)
        self.assertEqual(meta["coverage"]["parsed_files"], 1)
        self.assertLessEqual(meta["estimated_tokens"], 128)
        text = (self.out / "repo-map.md").read_text(encoding="utf-8")
        self.assertIn("Hostile.java:L1: class Hostile {\tvoid run() {} } // żółć", text)
        self.assertIn("Hostile.java:L3: class After {}", text)
        self.assertFalse(any(contains_control_characters(c) for c in text if c not in "\t\n"))
        inventory = json.loads((self.out / "inventory.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(original_bytes).hexdigest()
        self.assertEqual(inventory["files"][0]["sha256"], digest)
        self.assertTrue(check_cards(self.repo, {"citations": [{"path": "Hostile.java", "sha256": digest, "start_line": 1, "end_line": 1, "quote": original_line}]})["valid"])
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_changed_same_mtime_deleted_and_poisoned_cache(self):
        path = self.write("a.py", "def alpha():\n    pass\n")
        first = self.map()
        old_mtime = path.stat().st_mtime_ns
        path.write_text("def omega():\n    pass\n", encoding="utf-8", newline="\n")
        os.utime(path, ns=(old_mtime, old_mtime))
        second = self.map()
        self.assertNotEqual(first["working_copy_fingerprint"], second["working_copy_fingerprint"])
        self.assertIn("omega", (self.out / "repo-map.md").read_text(encoding="utf-8"))
        self.assertNotIn("alpha", (self.out / "repo-map.md").read_text(encoding="utf-8"))
        for cache in (self.out / "cache").glob("*.json"):
            cache.write_text('{"tags": "poison"}', encoding="utf-8", newline="\n")
        self.map()
        self.assertIn("omega", (self.out / "repo-map.md").read_text(encoding="utf-8"))
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
        outside.write_text("def outside(): pass\n", encoding="utf-8", newline="\n")
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
        self.assertIn("żółć.py:L1", (self.out / "repo-map.md").read_text(encoding="utf-8"))
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
        self.assertIn("desired", (self.out / "repo-map.md").read_text(encoding="utf-8"))

    def test_subtree_dot_and_relative_prefix_preserve_selected_scope(self):
        self.write("module/a.py", "def selected(): pass\n")
        self.write("outside.py", "def outside(): pass\n")
        for git in (False, True):
            if git:
                subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
            self.assertEqual(scan_repository(self.repo, subtrees=["."])["files"], scan_repository(self.repo)["files"])
            selected = scan_repository(self.repo, subtrees=["./module/"])
            self.assertEqual([entry["path"] for entry in selected["files"]], ["module/a.py"])

    def test_non_git_walk_keeps_sorted_files_before_sorted_child_directories(self):
        self.write("z.py", "def root_file(): pass\n")
        self.write("m.py", "def earlier_root_file(): pass\n")
        self.write("a/z.py", "def first_child(): pass\n")
        self.write("a/a/deep.py", "def deeper_child(): pass\n")
        self.write("b/a.py", "def second_child(): pass\n")
        expected = ["m.py", "z.py", "a/z.py", "a/a/deep.py", "b/a.py"]
        self.assertEqual([entry["path"] for entry in scan_repository(self.repo)["files"]], expected)
        capped = scan_repository(self.repo, max_files=1)
        self.assertEqual([entry["path"] for entry in capped["files"]], ["m.py"])
        self.assertEqual(capped["totals"]["candidates_seen"], 2)

    def test_nested_ignored_directory_is_scanned_as_non_git(self):
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)
        (self.base / ".gitignore").write_text("source with spaces/\n", encoding="utf-8", newline="\n")
        self.write("a.py", "def visible(): pass\n")
        inventory = scan_repository(self.repo)
        self.assertFalse(inventory["git"])
        self.assertIn("a.py", {item["path"] for item in inventory["files"]})

    def test_git_module_root_preserves_parent_ignore_revision_and_scoped_dirty(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write(".gitignore", "module/ignored.py\n")
        self.write("module/ok.py", "def visible(): pass\n")
        self.write("module/ignored.py", "def excluded(): pass\n")
        self.write("outside.py", "def outside(): pass\n")
        subprocess.run(["git", "-C", str(self.repo), "add", ".gitignore", "module/ok.py", "outside.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"], check=True)
        expected_revision = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.write("outside.py", "def changed_outside(): pass\n")
        inventory = scan_repository(self.repo / "module")
        self.assertTrue(inventory["git"])
        self.assertEqual(inventory["revision"], expected_revision)
        self.assertFalse(inventory["dirty"])
        self.assertEqual([item["path"] for item in inventory["files"]], ["ok.py"])
        self.write("module/ok.py", "def changed_inside(): pass\n")
        self.assertTrue(scan_repository(self.repo / "module")["dirty"])

    def test_non_git_walk_prunes_ignored_secret_and_nonselected_directories(self):
        self.write(".gitignore", "ignored/\n")
        self.write("ignored/deep/a.py", "def ignored(): pass\n")
        self.write("secrets/deep/a.py", "def sensitive(): pass\n")
        self.write("outside/deep/a.py", "def outside(): pass\n")
        self.write("module/a.py", "def selected(): pass\n")
        original = os.scandir
        visited = []
        def observe(directory):
            visited.append(Path(directory))
            return original(directory)
        with patch("repo_files.os.scandir", side_effect=observe):
            inventory = scan_repository(self.repo, subtrees=["module"])
        self.assertEqual([item["path"] for item in inventory["files"]], ["module/a.py"])
        self.assertEqual(visited, [self.repo, self.repo / "module"])

    def test_non_git_discovery_and_ignore_bytes_fail_with_unknown_coverage(self):
        for i in range(10):
            self.write(f"files/{i}.py", "def example(): pass\n")
        with patch("repo_files.MAX_DISCOVERY_ENTRIES", 5):
            with self.assertRaisesRegex(ValueError, "discovery entry limit"):
                self.map(inventory_only=True)
        meta = json.loads((self.out / "map.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertIsNone(meta["coverage"])
        self.assertEqual(meta["failure"]["stage"], "inventory")
        self.write(".gitignore", "x" * 257_000)
        with self.assertRaisesRegex(ValueError, "exceeds max_file_bytes"):
            scan_repository(self.repo)

    def test_source_change_during_rendering_records_failed_stage(self):
        self.write("a.py", "def initial(): pass\n")
        import repo_map
        original = repo_map.rank_tags
        def change_source(tags, **options):
            ranked = original(tags, **options)
            self.write("a.py", "def changed_source(): pass\n")
            return ranked
        with patch("repo_map.rank_tags", side_effect=change_source):
            with self.assertRaises(ValueError):
                self.map()
        meta = json.loads((self.out / "map.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "rendering")
        self.assertEqual(meta["coverage"]["selected_files"], 1)
        self.assertNotIn("# Repository map", (self.out / "repo-map.md").read_text(encoding="utf-8"))

    def test_publication_failure_records_failed_stage(self):
        self.write("a.py", "def initial(): pass\n")
        import repo_map
        original = repo_map._atomic_write
        def fail_map(path, content):
            if path.name == "repo-map.md" and content.startswith("# Repository map"):
                raise OSError("synthetic publication failure")
            original(path, content)
        with patch("repo_map._atomic_write", side_effect=fail_map):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.map()
        meta = json.loads((self.out / "map.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "publication")

    def test_focus_file_remains_visible_in_small_budget(self):
        self.write("a.py", "".join(f"def other_{n}(): pass\n" for n in range(30)))
        self.write("z.py", "def target(): pass\n")
        self.map(budget=64, focus_files=["z.py"])
        self.assertIn("z.py:L1", (self.out / "repo-map.md").read_text(encoding="utf-8"))

    def test_output_symlinks_cannot_redirect_writes_into_source(self):
        self.write("a.py", "def safe(): pass\n")
        target = self.write("important.txt", "DO NOT CHANGE\n")
        self.out.mkdir()
        (self.out / "repo-map.md").symlink_to(target)
        self.map()
        self.assertEqual(target.read_text(encoding="utf-8"), "DO NOT CHANGE\n")
        self.assertFalse((self.out / "repo-map.md").is_symlink())
        (self.out / "cache").rename(self.out / "old-cache")
        (self.out / "cache").symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cache path"):
            self.map()
        self.assertEqual(target.read_text(encoding="utf-8"), "DO NOT CHANGE\n")

    def test_offline_process(self):
        self.write("a.py", "def alpha(): pass\n")
        guard = self.base / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text("import socket\ndef deny(*args, **kwargs): raise RuntimeError('network denied')\nsocket.socket=deny\nsocket.create_connection=deny\n", encoding="utf-8", newline="\n")
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
        script.write_text("from pathlib import Path; import sys; Path(%r).touch(); print(sys.stdin.read())" % str(marker), encoding="utf-8", newline="\n")
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
        meta = json.loads((self.out / "map.meta.json").read_text(encoding="utf-8"))
        inventory = json.loads((self.out / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "inventory")
        self.assertEqual(inventory["status"], "failed")
        self.assertIsNone(meta["coverage"])
        self.assertNotIn("alpha", (self.out / "repo-map.md").read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "posix" and os.geteuid() != 0, "requires non-root POSIX permissions")
    def test_unreadable_subtree_is_reported_as_scan_failure(self):
        hidden = self.repo / "blocked"
        hidden.mkdir()
        self.write("blocked/a.py", "def inaccessible(): pass\n")
        hidden.chmod(0)
        try:
            with self.assertRaisesRegex(ValueError, "cannot inventory directory"):
                self.map()
            self.assertEqual(json.loads((self.out / "map.meta.json").read_text(encoding="utf-8"))["status"], "failed")
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
        self.assertIn("a.py:L3: def real_definition():", (self.out / "repo-map.md").read_text(encoding="utf-8"))
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
        meta = json.loads((self.out / "map.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "ranking")
        self.assertIsNone(meta["map_sha256"])
        self.assertIn("src/b.py", {x["path"] for x in json.loads((self.out / "inventory.json").read_text(encoding="utf-8"))["files"]})
        self.assertNotIn("alpha", (self.out / "repo-map.md").read_text(encoding="utf-8"))

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
