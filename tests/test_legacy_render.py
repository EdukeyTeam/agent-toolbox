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
        options.setdefault("map_format", "grouped")
        metadata = generate(self.repo, self.out, **options)
        return metadata, (self.out / "repo-map.md").read_text(encoding="utf-8")

    def test_grouped_java_multiline_parameters_annotations_and_class_context(self):
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
        for map_format in ("compact", "grouped", "lines"):
            with self.subTest(map_format=map_format):
                with self.assertRaises(ValueError):
                    self.map(map_format=map_format, all_definitions=True)
                metadata = json.loads((self.out / "map.meta.json").read_text())
                self.assertEqual(metadata["status"], "failed")
                self.assertTrue(any("name" in failure["reason"] and "512" in failure["reason"] for failure in metadata["parse_failures"]))

    def test_all_definitions_rejects_same_line_same_name_distinct_capture_positions(self):
        self.write("Both.java", "class A { void same() { one(); } } class B { void same() { two(); } }\n")
        self.map(map_format="lines")
        for map_format in ("compact", "grouped", "lines"):
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


    def test_complete_grouped_counts_large_rejection_without_rendering_oversized_files(self):
        import math
        import repo_render
        ranked = []
        sources = {}
        for file_number in range(3):
            path = f"src/Śervice{file_number}.py"
            lines = ["class Shared:"]
            for number in range(120):
                line = len(lines) + 1
                declaration = f"    def function_{number:03}(" + " " * 3000 + "value):"
                lines.extend([declaration, "        return value"])
                ranked.append({"path": path, "name": f"function_{number:03}", "line": line, "kind": "def",
                               "declaration_spans": [
                                   {"line": line, "start_line": line, "end_line": line, "start_column": 4, "end_column": len(declaration)},
                                   {"line": 1, "start_line": 1, "end_line": 1, "start_column": 0, "end_column": len(lines[0])},
                               ]})
            sources[path] = lines
        full, included, _ = repo_render.render_grouped(ranked, sources.__getitem__, 1_000_000, all_definitions=True)
        self.assertEqual(len(included), 360)
        required = math.ceil(len(full) / 4)
        self.assertEqual(full.count("class Shared:"), 3)
        rendered_sizes = []
        original_render = repo_render._file_text

        def measured_file(*args):
            text = original_render(*args)
            rendered_sizes.append(len(text))
            return text

        with patch("repo_render._file_text", side_effect=measured_file):
            with self.assertRaises(repo_render.BudgetExceeded) as failure:
                repo_render.render_grouped(ranked, sources.__getitem__, 64, all_definitions=True)
        self.assertEqual(failure.exception.required_estimated_tokens, required)
        self.assertLessEqual(max(rendered_sizes, default=0), 64 * 4,
                             "rejected complete output was rendered despite the configured bound")
        exact, exact_included, _ = repo_render.render_grouped(ranked, sources.__getitem__, required, all_definitions=True)
        self.assertEqual(exact, full)
        self.assertEqual(exact_included, included)

    def test_complete_legacy_lines_keeps_exact_budget_diagnostic_after_overflow(self):
        self.write("functions.py", "".join(f"def function_{number:03}(" + " " * 300 + "value): return value\n" for number in range(80)))
        full, full_text = self.map(all_definitions=True, map_format="lines", budget=16384)
        required = full["estimated_tokens"]
        with self.assertRaisesRegex(ValueError, "requires.*budget"):
            self.map(all_definitions=True, map_format="lines", budget=64)
        failed = json.loads((self.out / "map.meta.json").read_text())
        self.assertEqual(failed["failure"]["required_estimated_tokens"], required)
        exact, exact_text = self.map(all_definitions=True, map_format="lines", budget=required)
        self.assertEqual(exact_text, full_text)
        self.assertEqual(exact["coverage"]["definitions_omitted"], 0)

    def test_all_definitions_inventory_only_is_rejected_before_artifacts(self):
        self.write("sample.py", "def selected():\n    pass\n")
        with self.assertRaisesRegex(ValueError, "all-definitions.*inventory-only|inventory-only.*all-definitions"):
            self.map(all_definitions=True, inventory_only=True)
        self.assertFalse(self.out.exists())
        result = subprocess.run([sys.executable, str(SCRIPTS / "repo_map.py"), str(self.repo),
                                 "--output-dir", str(self.out), "--all-definitions", "--inventory-only"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.out.exists())



    def test_bounded_fragments_do_not_keep_minified_bodies_across_files(self):
        import repo_render
        fragments = []
        for number in range(20):
            header = f"class Tiny{number} {{"
            physical = header + 'void method() { String hidden = "' + "BODY_MUST_NOT_RETAIN" * 7000 + '"; }}'
            fragment = repo_render.LineFragments.excerpt(physical, 0, len(header)).bounded(repo_render.DECLARATION_CHARACTER_LIMIT)
            fragments.append(fragment)

        def reachable_strings(value, seen):
            if id(value) in seen:
                return 0
            seen.add(id(value))
            if isinstance(value, str):
                return len(value)
            if isinstance(value, dict):
                return sum(reachable_strings(part, seen) for pair in value.items() for part in pair)
            if isinstance(value, (tuple, list)):
                return sum(reachable_strings(part, seen) for part in value)
            if hasattr(value, "__dict__"):
                return reachable_strings(vars(value), seen)
            return 0

        retained = reachable_strings(fragments, set())
        self.assertLessEqual(retained, 20 * repo_render.DECLARATION_CHARACTER_LIMIT,
                             "tiny declarations kept large original physical lines alive")
        self.assertTrue(all(fragment.text().startswith("class Tiny") for fragment in fragments))


    def test_ranked_minified_files_keep_compact_fragments_after_source_cache_eviction(self):
        import repo_map
        import tracemalloc
        for number in range(20):
            self.write(f"Tiny{number}.java", f'class Tiny{number} {{ void first() {{ String body = "' + "BODY_MUST_NOT_LEAK" * 8000
                       + '"; } void second(\n  String value,\n  int count\n) {} }\n')
        original_cache = repo_map._SourceLineCache
        original_renderer = repo_map.render_grouped
        peak = 0

        def tiny_cache(loader):
            return original_cache(loader, max_bytes=512)

        def measured_renderer(*args, **options):
            nonlocal peak
            tracemalloc.start()
            try:
                return original_renderer(*args, **options)
            finally:
                peak = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()

        with patch("repo_map._SourceLineCache", side_effect=tiny_cache), patch("repo_map.render_grouped", side_effect=measured_renderer):
            metadata, text = self.map(budget=16384)
        self.assertEqual(metadata["coverage"]["definitions_in_map"], 60)
        self.assertNotIn("BODY_MUST_NOT_LEAK", text)
        self.assertIn("L2:   String value,\nL3:   int count\nL4: ) {", text)
        self.assertLess(peak, 2_000_000, "selected fragments kept evicted physical source bodies alive")



class CompactTests(unittest.TestCase):
    setUp = RenderTests.setUp
    write = RenderTests.write

    def map(self, **options):
        metadata = generate(self.repo, self.out, **options)
        return metadata, (self.out / "repo-map.md").read_text(encoding="utf-8")

    def test_default_compact_keeps_complete_headers_owners_and_inline_literals(self):
        self.write("api.py", 'class API:\n    @decorator("keep  two `ticks`")\n    def choose(\n        self,\n        value: str = "keep  two `ticks`",\n    ) -> str:\n        return HIDDEN_BODY\n\n    def other(self):\n        pass\n')
        meta, text = self.map(all_definitions=True)
        self.assertEqual(meta["rendering"]["format"], "compact")
        self.assertIn("## api.py\n\nL1: class API:", text)
        self.assertIn('L2: @decorator("keep  two `ticks`")', text)
        self.assertIn('L5: value: str = "keep  two `ticks`",\nL6: ) -> str:', text)
        self.assertIn("L9: def other(self):", text)
        self.assertNotIn("```", text)
        self.assertNotIn("  ...\n", text)
        self.assertNotIn("HIDDEN_BODY", text)
        self.assertEqual(meta["coverage"]["definitions_in_map"], 3)

    def test_compact_normalizes_whitespace_only_inline_gaps_but_keeps_elision(self):
        self.write("inline.java", 'class A { void first() { secret(); }' + ' ' * 50000 + 'void second(@Named("keep  two") String s) { hidden(); } }\n')
        meta, text = self.map(budget=256)
        self.assertIn("void first() { … void second", text)
        self.assertNotIn("secret()", text)
        self.assertNotIn("hidden()", text)
        self.assertLessEqual(len(text), 256 * 4)
        self.assertIn('"keep  two"', text)
        self.write("gap.java", 'class B {' + ' ' * 50000 + 'void method() {} }\n')
        meta, text = self.map(budget=256)
        self.assertIn("class B { void method() {", text)
        self.assertLessEqual(len(text), 256 * 4)

    def test_compact_multiline_literal_is_explicitly_a_whitespace_stripped_sketch(self):
        self.write("literal.py", 'def choose(value="""\n    keep\n    spaces\n"""):\n    pass\n')
        meta, compact = self.map(all_definitions=True)
        self.assertIn("L2: keep\nL3: spaces", compact)
        self.assertIn("including multiline literal lines", meta["rendering"]["whitespace"])
        grouped, pretty = self.map(all_definitions=True, map_format="grouped")
        self.assertIn("L2:     keep\nL3:     spaces", pretty)
        self.assertEqual(grouped["rendering"]["whitespace"], "source indentation preserved")

    def test_compact_is_measured_before_budget_fit_and_exact_all_boundary(self):
        self.write("x.py", "".join(f"def function_{i:02}(\n    arg: str,\n) -> str:\n    return arg\n" for i in range(20)))
        full, full_text = self.map(all_definitions=True)
        required = full["estimated_tokens"]
        exact, exact_text = self.map(all_definitions=True, budget=required)
        self.assertEqual(exact_text, full_text)
        with self.assertRaisesRegex(ValueError, "requires.*budget"):
            self.map(all_definitions=True, budget=required - 1)
        grouped, _ = self.map(map_format="grouped", budget=64)
        compact, text = self.map(budget=64)
        self.assertGreater(compact["coverage"]["definitions_in_map"], grouped["coverage"]["definitions_in_map"])
        self.assertLessEqual(len(text), 256)

    def test_coverage_rounds_up_and_max_definitions_stops_accepted_tags(self):
        self.write("functions.py", "".join(f"def f{i}():\n    pass\n" for i in range(7)))
        for options, expected in [({"coverage": 30}, 3), ({"coverage": 5e-324}, 1), ({"max_definitions": 2}, 2), ({"coverage": 100}, 7), ({"max_definitions": 99}, 7), ({}, 7)]:
            with self.subTest(options=options):
                meta, text = self.map(**options)
                self.assertEqual(meta["coverage"]["definitions_in_map"], expected)
                selection = meta["selection"]
                self.assertEqual(selection["effective_max_definitions"], expected)
                self.assertAlmostEqual(selection["coverage_percent"], expected / 7 * 100)
                self.assertEqual(selection["selection_limit_reached"], expected < 7)
                self.assertEqual(selection["requested_coverage_percent"], options.get("coverage"))
                self.assertEqual(selection["requested_max_definitions"], options.get("max_definitions"))
                self.assertEqual(text.count("def f"), expected)

    def test_cap_skips_oversized_candidate_and_counts_only_accepted_tags(self):
        import repo_render
        lines = ['def huge(' + 'x' * 900 + '):', 'def tiny():']
        ranked = [{"path": "x.py", "name": name, "line": n, "kind": "def", "declaration_spans": [{"line": n, "start_line": n, "end_line": n, "start_column": 0, "end_column": len(lines[n-1])}]} for n,name in ((1,"huge"),(2,"tiny"))]
        text, included, _ = repo_render.render_compact(ranked, lambda path: lines, 64, max_definitions=1)
        self.assertEqual([tag["name"] for tag in included], ["tiny"])
        self.assertNotIn("huge", text)
        self.assertIn("tiny", text)

    def test_empty_scope_has_zero_coverage_and_no_limit_reached(self):
        meta, _ = self.map(coverage=25)
        self.assertEqual(meta["selection"]["effective_max_definitions"], 0)
        self.assertEqual(meta["selection"]["coverage_percent"], 0)
        self.assertFalse(meta["selection"]["selection_limit_reached"])

    def test_invalid_controls_and_strict_all_conflicts_leave_no_artifacts(self):
        cases = [{"coverage": p} for p in (0, -1, 101, float("nan"), float("inf"), True, "5",10**1000)]
        cases += [{"max_definitions": n} for n in (0,-1,1.5,True,"2",200001)]
        cases += [{"coverage": 50,"max_definitions": 2}, {"all_definitions": True,"coverage": 100}, {"all_definitions": True,"max_definitions": 999}]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.map(**options)
            self.assertFalse(self.out.exists())

    def test_cli_human_readable_conflicts_with_any_explicit_format_before_artifacts(self):
        self.write("a.py", "def a():\n    pass\n")
        for explicit in ("compact","grouped","lines"):
            result = subprocess.run([sys.executable,str(SCRIPTS/"repo_map.py"),str(self.repo),"--output-dir",str(self.out),"--human-readable","--format",explicit],capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertFalse(self.out.exists())
        result = subprocess.run([sys.executable,str(SCRIPTS/"repo_map.py"),str(self.repo),"--output-dir",str(self.out),"--human-readable"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("```text",(self.out/"repo-map.md").read_text())



    def test_caps_apply_to_every_format_without_counting_incidental_class_headers(self):
        self.write("owners.py", "class Owner:\n    def chosen(self):\n        pass\n    def other(self):\n        pass\n")
        for style in ("compact", "grouped", "lines"):
            with self.subTest(style=style):
                meta, text = self.map(map_format=style, max_definitions=1, focus_symbols=["chosen"])
                self.assertEqual(meta["coverage"]["definitions_found"], 3)
                self.assertEqual(meta["coverage"]["definitions_in_map"], 1)
                self.assertIn("def chosen", text)
                self.assertNotIn("def other", text)
                self.assertAlmostEqual(meta["selection"]["coverage_percent"], 100 / 3)
                self.assertTrue(meta["selection"]["selection_limit_reached"])
                if style != "lines":
                    self.assertIn("class Owner:", text)

    def test_budget_can_prevent_requested_cap_without_claiming_limit_reached(self):
        self.write("many.py", "".join(f"def function_{i:02}(\n    argument: str,\n) -> str:\n    return argument\n" for i in range(20)))
        meta, text = self.map(max_definitions=15, budget=64)
        self.assertLess(meta["coverage"]["definitions_in_map"], 15)
        self.assertFalse(meta["selection"]["selection_limit_reached"])
        self.assertTrue(meta["truncated"])
        self.assertLessEqual(len(text),256)

    def test_compact_clipping_is_explicit_and_not_silently_complete(self):
        self.write("long.py", "def huge(\n" + "".join(f"    value{i}: str,\n" for i in range(90)) + "):\n    pass\n")
        meta, text = self.map(all_definitions=True)
        self.assertEqual(meta["coverage"]["definitions_in_map"],1)
        self.assertTrue(meta["truncated"])
        self.assertEqual(len(meta["rendering"]["clipped_declarations"]),1)
        self.assertIn("declaration clipped: L1-L92; line limit",text)
        self.assertNotIn("```",text)

    def test_compact_fragment_merge_never_retains_giant_whitespace_gap_or_source_body(self):
        import repo_render
        physical = '    class A {' + ' ' * 50000 + 'void method() {' + 'BODY' * 10000
        first_end = physical.index('{') + 1
        method_start = physical.index('void')
        last_end = physical.index('{',method_start) + 1
        first = repo_render.LineFragments.excerpt(physical,0,first_end,compact=True)
        method = repo_render.LineFragments.excerpt(physical,method_start,last_end,compact=True)
        merged = first.merge(method,physical).bounded(8000)
        self.assertEqual(merged.text(),'class A { void method() {')
        self.assertLess(merged.rendered_characters(),100)
        self.assertLess(merged.characters(),100)
        self.assertEqual(len(merged.intervals),2)
        self.assertFalse(any('BODY' in value for value in vars(merged).values() if isinstance(value,str)))

    def test_cli_default_caps_invalid_combinations_and_existing_artifact_preservation(self):
        self.write("a.py", "def alpha():\n    pass\ndef beta():\n    pass\n")
        command = [sys.executable,str(SCRIPTS/"repo_map.py"),str(self.repo),"--output-dir",str(self.out)]
        result = subprocess.run(command+["--coverage","50"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        metadata = json.loads((self.out/"map.meta.json").read_text())
        self.assertEqual(metadata["rendering"]["format"],"compact")
        self.assertEqual(metadata["coverage"]["definitions_in_map"],1)
        before = {p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        cases = [["--coverage","0"],["--coverage","NaN"],["--coverage","101"],["--max-definitions","0"],["--max-definitions","200001"],["--coverage","50","--max-definitions","1"],["--all-definitions","--coverage","100"],["--all-definitions","--max-definitions","2"]]
        for flags in cases:
            with self.subTest(flags=flags):
                result = subprocess.run(command+flags,capture_output=True,text=True)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertEqual(before,{p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()})


if __name__ == "__main__":
    unittest.main()
