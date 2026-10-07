"""Observable checks for bounded, AST-based grouped repository maps."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from repo_map import generate


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "source"
        self.repo.mkdir()
        self.out = self.base / "maps"
        environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def map(self, **options):
        metadata = generate(self.repo, self.out, **options)
        return metadata, (self.out / "repo-map.md").read_text(encoding="utf-8")

    def test_default_grouped_java_multiline_parameters_annotations_and_class_context(self):
        source = """@Deprecated
public class First {
  @Deprecated
  public java.util.List<String> render(
      final String label,
      int count
  ) throws java.io.IOException {
    return null;
  }
}
class Second {
  public String render(
      int count
  ) {
    return "BODY_MUST_NOT_LEAK";
  }
}
"""
        path = self.write("src/Examples.java", source)
        metadata, text = self.map(all_definitions=True)
        self.assertEqual(metadata["rendering"]["format"], "grouped")
        self.assertEqual(metadata["selection"]["mode"], "all-definitions")
        self.assertEqual(metadata["coverage"]["definitions_omitted"], 0)
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 4)
        self.assertIn("## src/Examples.java\n\n```text\n", text)
        self.assertIn("L1: @Deprecated\nL2: public class First {", text)
        self.assertIn("L3:   @Deprecated\nL4:   public java.util.List<String> render(", text)
        self.assertIn("L5:       final String label,\nL6:       int count\nL7:   ) throws java.io.IOException {", text)
        self.assertIn("L11: class Second {", text)
        self.assertIn("L12:   public String render(", text)
        self.assertNotIn("return null", text)
        self.assertNotIn("BODY_MUST_NOT_LEAK", text)
        self.assertIn("  ...\n", text)
        inventory = json.loads((self.out / "inventory.json").read_text())
        self.assertEqual(inventory["files"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(metadata["map_sha256"], hashlib.sha256(text.encode()).hexdigest())

    def test_python_decorators_async_types_and_repeated_methods(self):
        self.write("src/app.py", """@decorate(
    enabled=True,
)
class First(
    BaseType,
):
    @check
    async def render(
        self,
        value: dict[str, int],
    ) -> tuple[str, int]:
        return BODY_MUST_NOT_LEAK

class Second:
    def render(
        self,
        value: str,
    ) -> str:
        return BODY_MUST_NOT_LEAK
""")
        metadata, text = self.map(all_definitions=True)
        self.assertIn("L1: @decorate(\nL2:     enabled=True,\nL3: )\nL4: class First(", text)
        self.assertIn("L7:     @check\nL8:     async def render(", text)
        self.assertIn("L10:         value: dict[str, int],\nL11:     ) -> tuple[str, int]:", text)
        self.assertIn("L14: class Second:", text)
        self.assertIn("L15:     def render(", text)
        self.assertNotIn("BODY_MUST_NOT_LEAK", text)
        self.assertEqual(metadata["coverage"]["definitions_found"], 4)
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 4)
        self.assertEqual(text.count("L4:"), 1)
        self.assertEqual(text.count("L14:"), 1)

    def test_one_line_parent_is_cut_at_selected_body_opener(self):
        self.write("One.java", "class One { void work(String value) { System.out.println(\"BODY\"); } }\n")
        metadata, text = self.map(all_definitions=True)
        self.assertIn("L1: class One { void work(String value) {\n", text)
        self.assertNotIn("System.out", text)
        self.assertEqual(text.count("L1:"), 1)
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 2)

    def test_budget_counts_group_headers_fences_and_complete_signatures(self):
        self.write("x.py", "".join(f"def function_{number:02}(\n    argument: str,\n) -> str:\n    return argument\n" for number in range(20)))
        metadata, text = self.map(budget=64)
        self.assertLessEqual(len(text), 64 * 4)
        self.assertLessEqual(metadata["estimated_tokens"], 64)
        self.assertTrue(metadata["truncated"])
        self.assertGreater(metadata["coverage"]["definitions_omitted"], 0)
        self.assertEqual(metadata["coverage"]["definitions_found"], metadata["coverage"]["definitions_in_map"] + metadata["coverage"]["definitions_omitted"])
        self.assertTrue(text.endswith("```\n\n"))
        # Every admitted function has its complete closing parameter/type line.
        self.assertEqual(text.count("def function_"), text.count(") -> str:"))

    def test_all_definitions_exact_budget_boundary_and_failure_diagnostic(self):
        self.write("functions.py", "".join(f"def function_{number:02}(\n    argument: str,\n) -> str:\n    return argument\n" for number in range(20)))
        full, full_text = self.map(all_definitions=True, budget=4096)
        required = full["estimated_tokens"]
        self.assertGreater(required, 64)
        exact, exact_text = self.map(all_definitions=True, budget=required)
        self.assertEqual(exact_text, full_text)
        self.assertEqual(exact["coverage"]["definitions_omitted"], 0)
        with self.assertRaisesRegex(ValueError, "required.*budget|requires.*budget"):
            self.map(all_definitions=True, budget=required - 1)
        failed = json.loads((self.out / "map.meta.json").read_text())
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure"]["stage"], "rendering")
        self.assertEqual(failed["failure"]["required_estimated_tokens"], required)
        self.assertNotIn("def function_", (self.out / "repo-map.md").read_text())

    def test_long_declaration_clipping_is_explicit_and_name_remains_visible(self):
        decorators = "".join(f"@decorator_{number}\n" for number in range(90))
        self.write("long.py", decorators + "def selected(value: str) -> str:\n    return value\n")
        metadata, text = self.map(all_definitions=True, budget=4096)
        self.assertIn("def selected(value: str) -> str:", text)
        self.assertIn("declaration clipped", text)
        self.assertTrue(metadata["truncated"])
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 1)
        self.assertEqual(metadata["coverage"]["definitions_omitted"], 0)
        self.assertEqual(metadata["rendering"]["declaration_line_limit"], 80)
        self.assertEqual(metadata["rendering"]["declaration_character_limit"], 8000)
        self.assertEqual(metadata["rendering"]["clipped_declarations"], [{"path": "long.py", "line": 91, "start_line": 1, "end_line": 91, "reason": "line limit"}])
        self.assertLessEqual(sum(line.startswith("L") for line in text.splitlines()), 80)

    def test_character_clipping_preserves_definition_identity_and_reports_limit(self):
        self.write("long.py", '@decorate("' + "x" * 9000 + '")\ndef selected(value: str) -> str:\n    return value\n')
        metadata, text = self.map(all_definitions=True, budget=4096)
        self.assertIn("L2: def selected(value: str) -> str:", text)
        self.assertIn("character limit", text)
        self.assertEqual(metadata["rendering"]["clipped_declarations"], [{"path": "long.py", "line": 2, "start_line": 1, "end_line": 2, "reason": "character limit"}])
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 1)

    def test_identifier_beyond_character_safety_limit_cannot_be_counted_as_rendered(self):
        self.write("long.py", "class " + "X" * 8000 + "Name:\n    pass\n")
        # Query names longer than 512 are deliberately excluded upstream.
        # A short function identifier after excessive source indentation is not.
        self.write("indented.py", "class Outer:\n" + " " * 8000 + "def selected(self):\n" + " " * 8004 + "pass\n")
        with self.assertRaisesRegex(ValueError, "identifier.*limit|name.*limit"):
            self.map(all_definitions=True, budget=16384)
        failed = json.loads((self.out / "map.meta.json").read_text())
        self.assertEqual(failed["status"], "failed")

    def test_grouped_is_deterministic_with_warm_legacy_tag_cache(self):
        self.write("x.py", "class Example:\n    def one(self, argument: str) -> str:\n        return argument\n")
        self.map(map_format="lines")
        before_cache = {path.name: path.read_bytes() for path in (self.out / "cache").glob("*.json")}
        first, first_text = self.map(all_definitions=True)
        second, second_text = self.map(all_definitions=True)
        self.assertEqual(first, second)
        self.assertEqual(first_text, second_text)
        self.assertEqual(before_cache, {path.name: path.read_bytes() for path in (self.out / "cache").glob("*.json")})

    def test_source_change_after_ranking_is_detected_before_rendering(self):
        import repo_map
        path = self.write("x.py", "def before(value: str) -> str:\n    return value\n")
        original = repo_map.rank_tags

        def change_source(*args, **kwargs):
            result = original(*args, **kwargs)
            path.write_bytes(b"def after(value: str) -> str:\n    return value\n")
            return result

        with patch("repo_map.rank_tags", side_effect=change_source):
            with self.assertRaisesRegex(ValueError, "source changed"):
                self.map()
        metadata = json.loads((self.out / "map.meta.json").read_text())
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["failure"]["stage"], "rendering")

    def test_all_definitions_rejects_incomplete_scan_or_parse(self):
        self.write("a.py", "def alpha():\n    pass\n")
        self.write("b.py", "def beta():\n    pass\n")
        with self.assertRaisesRegex(ValueError, "all.*definitions|all-definitions"):
            self.map(all_definitions=True, max_files=1)
        self.write("broken.py", "def broken(:\n    pass\n")
        with self.assertRaisesRegex(ValueError, "all.*definitions|all-definitions"):
            self.map(all_definitions=True)

    def test_supported_language_headers_keep_types_context_and_exclude_bodies(self):
        fixtures = {
            "sample.ts": ("export function render(\n    value: string,\n): Promise<string> {\n    throw new Error('BODY_MUST_NOT_LEAK');\n}\n", "L3: ): Promise<string> {"),
            "sample.js": ("export const render = (\n    value,\n) => {\n    return 'BODY_MUST_NOT_LEAK';\n};\n", "L1: export const render = ("),
            "sample.c": ("static int render(\n    int value\n) {\n    return BODY_MUST_NOT_LEAK;\n}\n", "L1: static int render("),
            "sample.cpp": ("class Example {\npublic:\n    int render(\n        int value\n    ) const {\n        return BODY_MUST_NOT_LEAK;\n    }\n};\n", "L5:     ) const {"),
            "sample.go": ("package example\ntype Example struct {\n    Hidden string\n}\nfunc render(\n    value string,\n) string {\n    return \"BODY_MUST_NOT_LEAK\"\n}\n", "L2: type Example struct {"),
            "sample.cs": ("class Example {\n    public string Render(\n        string value\n    ) {\n        return \"BODY_MUST_NOT_LEAK\";\n    }\n}\n", "L2:     public string Render("),
            "sample.rs": ("struct Example;\nimpl Example {\n    #[inline]\n    fn render<T>(\n        value: T,\n    ) -> T\n    where T: Clone {\n        println!(\"BODY_MUST_NOT_LEAK\");\n        value\n    }\n}\n", "L7:     where T: Clone {"),
        }
        for path, (source, expected) in fixtures.items():
            self.write(path, source)
        metadata, text = self.map(all_definitions=True, budget=16384)
        for path, (_source, expected) in fixtures.items():
            with self.subTest(path=path):
                self.assertIn("## " + path + "\n", text)
                self.assertIn(expected, text)
        self.assertNotIn("BODY_MUST_NOT_LEAK", text)
        self.assertNotIn("Hidden string", text)
        self.assertIn("L2: impl Example {", text)
        self.assertIn("L3:     #[inline]", text)
        self.assertEqual(metadata["coverage"]["definitions_omitted"], 0)

    def test_default_budget_is_large_enough_for_repository_overview(self):
        self.write("x.py", "def example(value: str) -> str:\n    return value\n")
        metadata, _ = self.map()
        self.assertEqual(metadata["limits"]["budget"], 16384)

    def test_cli_format_lines_retains_legacy_output_and_all_mode(self):
        self.write("x.py", "def alpha(): return 1\ndef beta(): return 2\n")
        metadata, text = self.map(map_format="lines", all_definitions=True)
        self.assertEqual(text, "# Repository map\n\nx.py:L1: def alpha(): return 1\nx.py:L2: def beta(): return 2\n")
        self.assertEqual(metadata["rendering"]["format"], "lines")
        result = subprocess.run([sys.executable, str(SCRIPTS / "repo_map.py"), str(self.repo), "--output-dir", str(self.out),
                                 "--format", "lines", "--all-definitions"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "repo-map.md").read_text(), text)


    def test_inline_sibling_bodies_are_omitted_in_grouped_output(self):
        self.write("Inline.java", "class C { void alpha() { secret(); } void beta() { other(); } }\n")
        metadata, text = self.map(all_definitions=True)
        self.assertIn("void alpha() {", text)
        self.assertIn("void beta() {", text)
        self.assertIn(" … ", text)
        self.assertNotIn("secret()", text)
        self.assertNotIn("other()", text)
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 3)

    def test_multiple_arrow_declarators_each_have_a_visible_declaration(self):
        self.write("arrows.js", "const alpha = () => secret(), beta = () => other();\n")
        # Warm legacy caches must not hide current AST identity checks.
        self.map(map_format="lines")
        metadata, text = self.map(all_definitions=True)
        self.assertIn("const alpha = () =>", text)
        self.assertIn("beta = () =>", text)
        self.assertNotIn("secret()", text)
        self.assertNotIn("other()", text)
        self.assertEqual(metadata["coverage"]["definitions_found"], 2)
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 2)

    def test_all_definitions_rejects_safety_filtered_names_even_from_warm_cache(self):
        self.write("Name.java", "class " + "X" * 513 + " {}\n")
        # The legacy line format intentionally retains the existing filtered cache.
        self.map(map_format="lines")
        for map_format in ("grouped", "lines"):
            with self.subTest(map_format=map_format):
                with self.assertRaises(ValueError):
                    self.map(map_format=map_format, all_definitions=True)
                metadata = json.loads((self.out / "map.meta.json").read_text())
                self.assertEqual(metadata["status"], "failed")
                self.assertTrue(any("name" in failure["reason"] and "512" in failure["reason"] for failure in metadata["parse_failures"]))

    def test_all_definitions_rejects_same_line_same_name_distinct_capture_positions(self):
        self.write("Both.java", "class A { void same() { one(); } } class B { void same() { two(); } }\n")
        self.map(map_format="lines")
        for map_format in ("grouped", "lines"):
            with self.subTest(map_format=map_format):
                with self.assertRaises(ValueError):
                    self.map(map_format=map_format, all_definitions=True)
                metadata = json.loads((self.out / "map.meta.json").read_text())
                self.assertEqual(metadata["status"], "failed")
                self.assertTrue(any("ambiguous" in failure["reason"] and "same" in failure["reason"] for failure in metadata["parse_failures"]))


    def test_all_legacy_lines_rejects_identifiers_hidden_by_240_character_clipping(self):
        name = "X" * 250
        self.write("Wide.java", f"class {name} {{}}\n")
        with self.assertRaisesRegex(ValueError, "240.*grouped|grouped.*240"):
            self.map(map_format="lines", all_definitions=True)
        failed = json.loads((self.out / "map.meta.json").read_text())
        self.assertEqual(failed["status"], "failed")
        grouped, text = self.map(all_definitions=True)
        self.assertEqual(grouped["coverage"]["definitions_in_map"], 1)
        self.assertIn(name, text)


    def test_small_files_beyond_32_entries_are_read_once_during_rendering(self):
        import repo_map
        from collections import Counter
        for number in range(40):
            self.write(f"src/Service{number:02}.java", f"class Service{number:02} {{\n    void sharedMethod() {{}}\n}}\n")
        expected, expected_text = self.map()
        render_reads = Counter()
        original_read = repo_map.read_safe_text
        original_render = repo_map.render_grouped
        rendering = False

        def counted_read(root, path, **options):
            if rendering:
                render_reads[path] += 1
            return original_read(root, path, **options)

        def measured_render(*args, **options):
            nonlocal rendering
            rendering = True
            return original_render(*args, **options)

        with patch("repo_map.read_safe_text", side_effect=counted_read), patch("repo_map.render_grouped", side_effect=measured_render):
            actual, text = self.map()
        self.assertEqual(text, expected_text)
        self.assertEqual(actual["coverage"], expected["coverage"])
        self.assertEqual(actual["coverage"]["definitions_in_map"], 80)
        self.assertEqual(len(render_reads), 40)
        self.assertEqual(set(render_reads.values()), {1}, render_reads)


    def test_source_line_cache_evicts_by_unicode_storage_and_does_not_retain_oversized_files(self):
        import repo_map
        from collections import Counter
        reads = Counter()
        values = {"a": ["🍀" * 5000], "b": ["🎉" * 5000], "huge": ["🍀" * 10000]}

        def load(path):
            reads[path] += 1
            return values[path]

        cache = repo_map._SourceLineCache(load, max_bytes=25_000)
        for path in ("a", "a", "b", "a", "huge", "huge", "a"):
            self.assertEqual(cache(path), values[path])
            self.assertLessEqual(cache.retained_bytes, 25_000)
        # Wide Unicode strings consume more memory than len(text) bytes.
        # One fits the cache; two evict, and the oversized value stays uncached.
        self.assertEqual(reads, {"a": 2, "b": 1, "huge": 2})


if __name__ == "__main__":
    unittest.main()
