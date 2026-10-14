"""Behavior checks for the Java member outline, slices and the refactoring ledger."""

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
from check_citations import check_cards
from member_ledger import ScanError, build_baseline, compare, main, outline_file, render_comparison, render_outline, scan_java, slice_file

TRICKY = '''package a.b;

import java.util.*;

/** Doc for Big. */
@SuppressWarnings({"unchecked", "rawtypes"})
public class Big<T extends Comparable<T>> extends Base implements Runnable {
    private static final long serialVersionUID = 1L; // trailing
    private Map<String, List<Integer>> index = new HashMap<String, List<Integer>>(), other;
    static final String[] NAMES = { "a{", "b}" };
    private Enumeration enum;
    char brace = '{', quote = '\\'';
    String s = "} // not a comment \\" {";
    Runnable r = new Runnable() { public void run() { } };
    Comparator<String> cmp = (x, y) -> { return x.compareTo(y); };
    static Logger LOG = Logger.getLogger(Big.class);

    static {
        NAMES[0] = "x";
    }

    { index = null; }

    /**
     * Constructor { brace in documentation
     */
    public Big(Config config) { }

    @Override
    public void run() {
        /* } */
        if (brace > quote) { brace++; }
    }

    @Deprecated @Named(value = "x", other = {1, 2})
    protected static <K, V extends List<K>> Map<K, V> convert(final Map<K, V> in, String[] names, int flags[], Object... rest) throws IOException {
        return in;
    }

    void run(int x) {}
    abstract int size();
    public void Big() {}

    private static class Inner {
        Inner() {}
        <X> Inner(X x) {}
    }

    enum Color implements Runnable {
        RED, @Deprecated GREEN(2) { void x() {} }, BLUE;
        Color() {}
        public void run() {}
    }

    interface Api {
        int LIMIT = 5;
        default void twice() { call(); call(); }
    }

    @interface Marker {
        String[] tags() default {"a"};
    }

    record Point(int x, int y) {
        Point { if (x < 0) throw new IllegalArgumentException(); }
    }
}

class Second { }
'''

BIG = '''package app;

public class Orders {
    private int count;
    private static final String NAME = "orders";

    public Orders() { count = 0; }

    public int total(int a, int b) {
        return a + b;
    }

    private static int tax(int net) {
        return net * 23 / 100;
    }

    void audit(String who) {
        System.out.println("audit " + who);
    }

    static class Line {
        int quantity;
        int price() { return quantity * 2; }
    }
}
'''


def members(text):
    return {member["id"]: member for member in scan_java(text)["members"]}


class ScannerTests(unittest.TestCase):
    def test_every_member_kind_is_found_with_exact_lines(self):
        scanned = scan_java(TRICKY)
        found = {member["id"]: (member["kind"], member["start_line"], member["end_line"]) for member in scanned["members"]}
        self.assertEqual(found, {
            "Big#<type>": ("type", 6, 7),
            "Big#field:serialVersionUID": ("field", 8, 8), "Big#field:index": ("field", 9, 9), "Big#field:NAMES": ("field", 10, 10),
            "Big#field:enum": ("field", 11, 11), "Big#field:brace": ("field", 12, 12), "Big#field:s": ("field", 13, 13),
            "Big#field:r": ("field", 14, 14), "Big#field:cmp": ("field", 15, 15), "Big#field:LOG": ("field", 16, 16),
            "Big#<static-init>": ("static-init", 18, 20), "Big#<init>": ("instance-init", 22, 22),
            "Big#Big(Config)": ("constructor", 27, 27), "Big#run()": ("method", 29, 33),
            "Big#convert(Map<K,V>,String[],int[],Object...)": ("method", 35, 38),
            "Big#run(int)": ("method", 40, 40), "Big#size()": ("method", 41, 41), "Big#Big()": ("method", 42, 42),
            "Big.Inner#<type>": ("type", 44, 44), "Big.Inner#Inner()": ("constructor", 45, 45), "Big.Inner#Inner(X)": ("constructor", 46, 46),
            "Big.Color#<type>": ("type", 49, 49), "Big.Color#constant:RED": ("enum-constant", 50, 50),
            "Big.Color#constant:GREEN": ("enum-constant", 50, 50), "Big.Color#constant:BLUE": ("enum-constant", 50, 50),
            "Big.Color#Color()": ("constructor", 51, 51), "Big.Color#run()": ("method", 52, 52),
            "Big.Api#<type>": ("type", 55, 55), "Big.Api#field:LIMIT": ("field", 56, 56), "Big.Api#twice()": ("method", 57, 57),
            "Big.Marker#<type>": ("type", 60, 60), "Big.Marker#tags()": ("method", 61, 61),
            "Big.Point#<type>": ("type", 64, 64), "Big.Point#Point": ("constructor", 65, 65),
            "Second#<type>": ("type", 69, 69),
        })
        self.assertEqual([(entry["name"], entry["kind"], entry["start_line"], entry["end_line"], entry["members"]) for entry in scanned["types"]], [
            ("Big", "class", 6, 67, 17), ("Big.Inner", "class", 44, 47, 2), ("Big.Color", "enum", 49, 53, 5),
            ("Big.Api", "interface", 55, 58, 2), ("Big.Marker", "annotation", 60, 62, 1), ("Big.Point", "record", 64, 66, 1), ("Second", "class", 69, 69, 0),
        ])

    def test_modifiers_documentation_and_headers_are_reported(self):
        found = members(TRICKY)
        self.assertEqual(found["Big#convert(Map<K,V>,String[],int[],Object...)"]["modifiers"], ["protected", "static"])
        self.assertEqual(found["Big#run()"]["modifiers"], ["public"])
        self.assertEqual(found["Big.Api#twice()"]["modifiers"], ["default"])
        self.assertEqual(found["Big#Big(Config)"]["doc_start_line"], 24)
        self.assertEqual(found["Big#<type>"]["doc_start_line"], 5)
        # The comment that ends the previous field's line does not document this field.
        self.assertNotIn("doc_start_line", found["Big#field:index"])
        self.assertEqual(found["Big#Big(Config)"]["header"], "public Big(Config config)")
        self.assertEqual(found["Big#field:index"]["header"], "private Map<String, List<Integer>> index")
        self.assertEqual(found["Big#convert(Map<K,V>,String[],int[],Object...)"]["header"],
                         '@Deprecated @Named(value = "x", other = { 1, 2 }) protected static <K, V extends List<K>> Map<K, V> convert(final Map<K, V> in, String[] names, int flags[], Object... rest) throws IOException')

    def test_token_identity_ignores_layout_and_comments_only(self):
        base = members("class A { int f(int a, int b) { return a++ + b; } List<List<String>> g; }")
        relaid = members("class A {\n  // note\n  int f(int a,\n        int b) {\n    return a++ + b; /* x */\n  }\n  List<List<String> > g;\n}")
        for key in ("A#f(int,int)", "A#field:g"):
            self.assertEqual(base[key]["token_sha256"], relaid[key]["token_sha256"])
        for changed in ("class A { int f(int a, int b) { return a + ++b; } }", "class A { int f(int a, int b) { return a++ - b; } }", "class A { int f(int a, int b) { return a++ + b + 0; } }"):
            with self.subTest(changed=changed):
                self.assertNotEqual(base["A#f(int,int)"]["token_sha256"], members(changed)["A#f(int,int)"]["token_sha256"])
        literal = members('class A { String s() { return "a b"; } }')["A#s()"]
        self.assertNotEqual(literal["token_sha256"], members('class A { String s() { return "a  b"; } }')["A#s()"]["token_sha256"])
        # The header is part of the member; the body alone identifies a moved method whose modifiers changed.
        private, public = members("class A { private int f() { return 1; } }")["A#f()"], members("class A { public static int f() { return 1; } }")["A#f()"]
        self.assertNotEqual(private["token_sha256"], public["token_sha256"])
        self.assertEqual(private["body_sha256"], public["body_sha256"])

    def test_repeated_identifiers_stay_distinct(self):
        found = members("class A { static { } static { } { } }")
        self.assertEqual(sorted(found), ["A#<init>", "A#<static-init>", "A#<static-init>~2", "A#<type>"])

    def test_broken_source_is_refused_instead_of_outlined(self):
        for source, message in (
            ("class A { void f() { if (x) { }", "unclosed '{' opened at line 1"),
            ("class A { void f() { } } }", "unbalanced '}' at line 1"),
            ("class A { void f( { } }", "unbalanced '}'"),
            ("class A {\n /* never closed\n void f() {} }", "unterminated block comment at line 2"),
            ('class A { String s = "open; }', "unterminated string or character literal at line 1"),
            ("class A { int x }", "declaration starting at line 1 has no end"),
            ("class A {\r void f() {}\r}", "bare CR line endings"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ScanError, message):
                scan_java(source)

    def test_text_blocks_and_crlf_lines(self):
        found = members('class A {\r\n  String q = """\r\n    select "x" } {\r\n    """;\r\n  void f() {}\r\n}\r\n')
        self.assertEqual((found["A#field:q"]["start_line"], found["A#field:q"]["end_line"]), (2, 4))
        self.assertEqual(found["A#f()"]["start_line"], 5)


class RepositoryCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.repo = self.base / "repo"
        (self.repo / "src/app").mkdir(parents=True)
        self.big = "src/app/Orders.java"
        self.write(self.big, BIG)

    def write(self, path, text, encoding="utf-8"):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode(encoding))

    def statuses(self, result):
        return {record["member"].split("::", 1)[1]: record["status"] for record in result["members"] if record["status"] != "unchanged"}


class OutlineAndSliceTests(RepositoryCase):
    def test_outline_is_one_line_per_member_with_source_identity(self):
        outline = outline_file(self.repo, self.big)
        digest = hashlib.sha256(BIG.encode()).hexdigest()
        self.assertEqual((outline["sha256"], outline["lines"]), (digest, 25))
        self.assertEqual(render_outline(outline), "\n".join([
            f"src/app/Orders.java 25 lines sha256={digest} encoding=utf-8",
            "2 types, 8 members: 1 constructor, 3 field, 4 method",
            "largest: Orders#total(int,int) 3 lines; Orders#tax(int) 3 lines; Orders#audit(String) 3 lines; Orders#field:count 1 lines; Orders#field:NAME 1 lines",
            "class Orders L3-L25 (6 members)",
            "L4 1 field field:count [private]",
            "L5 1 field field:NAME [private static final]",
            "L7 1 constructor Orders() [public]",
            "L9-L11 3 method total(int,int) [public]",
            "L13-L15 3 method tax(int) [private static]",
            "L17-L19 3 method audit(String)",
            "class Orders.Line L21-L24 (2 members)",
            "L22 1 field field:quantity",
            "L23 1 method price()",
        ]) + "\n")

    def test_slice_selects_by_id_or_unique_name_and_pages_long_members(self):
        digest = hashlib.sha256(BIG.encode()).hexdigest()
        expected = f"src/app/Orders.java L13-L15 of 25 sha256={digest} encoding=utf-8 member=Orders#tax(int)\n13:     private static int tax(int net) {{\n14:         return net * 23 / 100;\n15:     }}\n"
        for selector in ("Orders#tax(int)", "tax(int)", "tax"):
            self.assertEqual(slice_file(self.repo, self.big, member=selector), expected)
        self.write("src/app/Doc.java", "class Doc {\n    int a; // trailing\n\n    /** Explains f. */\n    // second comment\n    void f() {}\n}\n")
        self.assertEqual(slice_file(self.repo, "src/app/Doc.java", member="f").splitlines()[1:], ["6:     void f() {}"])
        self.assertEqual(slice_file(self.repo, "src/app/Doc.java", member="f", with_doc=True).splitlines()[1:], ["4:     /** Explains f. */", "5:     // second comment", "6:     void f() {}"])
        paged = slice_file(self.repo, self.big, lines=(9, 19), max_lines=4)
        self.assertEqual(paged.splitlines()[0], f"src/app/Orders.java L9-L12 of 25 sha256={digest} encoding=utf-8")
        self.assertEqual(paged.splitlines()[-1], "[truncated: 7 more lines; continue with --lines 13-19]")
        self.write("src/app/Two.java", "class Two { void f() {} void f(int a) {} }")
        with self.assertRaisesRegex(ValueError, r"matches several members: Two#f\(\), Two#f\(int\)"):
            slice_file(self.repo, "src/app/Two.java", member="f")
        with self.assertRaisesRegex(ValueError, "no member matches"):
            slice_file(self.repo, self.big, member="absent")
        with self.assertRaisesRegex(ValueError, "outside"):
            slice_file(self.repo, self.big, lines=(20, 99))

    def test_legacy_encoding_is_explicit_and_citations_use_original_bytes(self):
        source = 'class Faktura {\n    String nazwa() { return "Zażółć gęślą jaźń"; }\n}\n'
        self.write("src/app/Faktura.java", source, encoding="cp1250")
        with self.assertRaisesRegex(ValueError, "not valid UTF-8.*--encoding"):
            outline_file(self.repo, "src/app/Faktura.java")
        with self.assertRaisesRegex(ValueError, "not valid UTF-8.*--encoding"):
            outline_file(self.repo, "src/app/Faktura.java", "UTF8")
        for unknown in ("no-such-codec", "hex"):
            with self.subTest(unknown=unknown), self.assertRaisesRegex(ValueError, "unknown text encoding"):
                outline_file(self.repo, "src/app/Faktura.java", unknown)
        outline = outline_file(self.repo, "src/app/Faktura.java", "cp1250")
        self.assertEqual(outline["sha256"], hashlib.sha256(source.encode("cp1250")).hexdigest())
        self.assertIn('2:     String nazwa() { return "Zażółć gęślą jaźń"; }', slice_file(self.repo, "src/app/Faktura.java", member="nazwa", encoding="cp1250"))
        card = {"path": "src/app/Faktura.java", "sha256": outline["sha256"], "start_line": 2, "end_line": 2, "quote": 'return "Zażółć gęślą jaźń";'}
        self.assertEqual(check_cards(self.repo, {"citations": [card]})["results"][0]["errors"], ["non-UTF-8 file"])
        self.assertTrue(check_cards(self.repo, {"citations": [card]}, "cp1250")["valid"])
        # The ledger keeps the declared encoding; a literal rewritten in another encoding is a modification.
        baseline = build_baseline(self.repo, ["src/app/Faktura.java"], encoding="cp1250")
        self.assertTrue(compare(self.repo, baseline)["passed"])
        self.write("src/app/Faktura.java", source, encoding="iso-8859-2")
        self.assertEqual(self.statuses(compare(self.repo, baseline)), {"Faktura#nazwa()": "modified"})
        self.write("src/app/Faktura.java", source, encoding="utf-8")
        self.assertEqual(self.statuses(compare(self.repo, baseline)), {"Faktura#nazwa()": "modified"})
        self.write("src/app/Faktura.java", source, encoding="cp1250")
        self.assertTrue(check_cards(self.repo, {"citations": [{**card, "encoding": "cp1250"}]})["valid"])
        self.assertFalse(check_cards(self.repo, {"citations": [{**card, "encoding": "iso-8859-2"}]})["valid"])

    def test_only_java_inside_the_repository_is_read(self):
        self.write("src/app/notes.txt", "class A {}")
        for path, message in (("src/app/notes.txt", "only Java source"), ("../outside.java", "unsafe relative path"), ("src/app/Missing.java", "missing or outside")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, message):
                outline_file(self.repo, path)


class LedgerTests(RepositoryCase):
    def baseline(self, **options):
        return build_baseline(self.repo, [self.big], ["src/app"], **options)

    def test_untouched_and_reformatted_files_pass(self):
        baseline = self.baseline()
        self.assertTrue(compare(self.repo, baseline)["passed"])
        self.write(self.big, BIG.replace("    ", "\t").replace("return a + b;", "return a + b; // sum"))
        result = compare(self.repo, baseline)
        self.assertEqual((result["passed"], result["counts"]), (True, {"unchanged": 10}))

    def test_extraction_reports_moves_stubs_signature_changes_and_additions(self):
        baseline = self.baseline()
        self.write(self.big, BIG.replace("return net * 23 / 100;", "return Tax.tax(net);")
                   .replace('    void audit(String who) {\n        System.out.println("audit " + who);\n    }\n\n', "")
                   .replace("    static class Line {\n        int quantity;\n        int price() { return quantity * 2; }\n    }\n", ""))
        self.write("src/app/Tax.java", "package app;\n\nfinal class Tax {\n    private static int tax(int net) {\n        return net * 23 / 100;\n    }\n    static int rounded(int net) { return tax(net); }\n}\n")
        self.write("src/app/audit/Audit.java", 'package app.audit;\n\npublic class Audit {\n    public static void audit(String who) {\n        System.out.println("audit " + who);\n    }\n}\n')
        self.write("src/app/Line.java", "package app;\n\nclass Line {\n    int quantity;\n    int price() { return quantity * 2; }\n}\n")
        result = compare(self.repo, baseline)
        self.assertEqual(self.statuses(result), {
            "Orders#tax(int)": "moved", "Orders#audit(String)": "signature-changed",
            "Orders.Line#<type>": "signature-changed", "Orders.Line#field:quantity": "moved", "Orders.Line#price()": "moved",
        })
        by_member = {record["member"]: record for record in result["members"]}
        tax = by_member["src/app/Orders.java::Orders#tax(int)"]
        self.assertEqual((tax["now"][0]["member"], tax["origin"]), ("src/app/Tax.java::Tax#tax(int)", "still present with different content"))
        audit = by_member["src/app/Orders.java::Orders#audit(String)"]
        self.assertEqual((audit["was"]["modifiers"], audit["now"][0]["modifiers"]), ([], ["public", "static"]))
        self.assertEqual(result["added"], ["src/app/Tax.java::Tax#<type>", "src/app/Tax.java::Tax#rounded(int)", "src/app/audit/Audit.java::Audit#<type>"])
        self.assertTrue(result["passed"])
        report = render_comparison(result)
        self.assertIn("10 tracked members: 5 unchanged, 3 moved, 2 signature-changed, 0 modified, 0 missing; 3 added", report)
        self.assertIn("MOVED src/app/Orders.java::Orders#tax(int) was L13-L15 -> src/app/Tax.java::Tax#tax(int) L4-L6 (origin still present with different content)", report)
        self.assertIn("SIGNATURE-CHANGED src/app/Orders.java::Orders#audit(String) was L17-L19 -> src/app/audit/Audit.java::Audit#audit(String) L4-L6 modifiers [] -> [public static]", report)
        self.assertIn("moved verbatim: 2 -> src/app/Line.java", report)
        self.assertTrue(report.splitlines()[-1].startswith("PASS."))
        # Strict review needs a recorded decision for every member whose code or header changed.
        strict = compare(self.repo, baseline, strict=True)
        self.assertEqual((strict["passed"], strict["unaccounted"]), (False, ["src/app/Orders.java::Orders#audit(String)", "src/app/Orders.java::Orders.Line#<type>"]))

    def test_a_dropped_or_rewritten_member_fails_until_a_decision_is_recorded(self):
        baseline = self.baseline()
        self.write(self.big, BIG.replace('    void audit(String who) {\n        System.out.println("audit " + who);\n    }\n\n', "").replace("return a + b;", "return a - b;"))
        result = compare(self.repo, baseline)
        self.assertEqual(self.statuses(result), {"Orders#audit(String)": "missing", "Orders#total(int,int)": "modified"})
        self.assertEqual((result["passed"], result["unaccounted"]), (False, ["src/app/Orders.java::Orders#audit(String)"]))
        report = render_comparison(result)
        self.assertIn("MISSING src/app/Orders.java::Orders#audit(String) was L17-L19 NEEDS DECISION", report)
        self.assertIn("MODIFIED src/app/Orders.java::Orders#total(int,int) was L9-L11, now L9-L11\n", report)
        self.assertIn("FAIL: unaccounted members 1, unscanned files 0.", report)
        decisions = {"decisions": [{"member": "src/app/Orders.java::Orders#audit(String)", "disposition": "deleted", "reason": "no callers; confirmed with the owner"},
                                   {"member": "src/app/Orders.java::Orders#gone()", "disposition": "deleted", "reason": "stale entry"}]}
        accepted = compare(self.repo, baseline, decisions)
        self.assertEqual((accepted["passed"], accepted["unused_decisions"]), (True, ["src/app/Orders.java::Orders#gone()"]))
        self.assertFalse(compare(self.repo, baseline, decisions, strict=True)["passed"])
        for invalid in ({"member": "x", "disposition": "ignored", "reason": "r"}, {"member": "x", "disposition": "deleted", "reason": " "}, {"disposition": "deleted", "reason": "r"}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "each decision needs"):
                compare(self.repo, baseline, {"decisions": [invalid]})

    def test_code_that_already_existed_is_never_a_move_destination(self):
        self.write("src/app/Other.java", "package app;\n\nclass Other {\n    private int count;\n    void audit(String who) {\n        System.out.println(\"audit \" + who);\n    }\n}\n")
        baseline = self.baseline()
        self.assertEqual(sorted(baseline["preexisting"]), ["src/app/Other.java"])
        self.write(self.big, BIG.replace("    private int count;\n", "").replace('    void audit(String who) {\n        System.out.println("audit " + who);\n    }\n\n', ""))
        result = compare(self.repo, baseline)
        self.assertEqual(self.statuses(result), {"Orders#field:count": "missing", "Orders#audit(String)": "missing"})
        # The same text added to that file after the baseline does count.
        self.write("src/app/Other.java", "package app;\n\nclass Other {\n    private int count;\n    void audit(String who) {\n        System.out.println(\"audit \" + who);\n    }\n    static class Kept { private int count; }\n}\n")
        self.assertEqual(self.statuses(compare(self.repo, baseline)), {"Orders#field:count": "moved", "Orders#audit(String)": "missing"})

    def test_a_truncated_or_deleted_tracked_file_cannot_pass(self):
        baseline = self.baseline()
        self.write(self.big, BIG[: BIG.index("void audit")])
        result = compare(self.repo, baseline)
        self.assertFalse(result["passed"])
        self.assertEqual(result["unscanned"], [{"path": self.big, "reason": "unclosed '{' opened at line 3"}])
        self.assertEqual(result["counts"], {"missing": 10})
        self.assertIn("UNSCANNED src/app/Orders.java: unclosed '{' opened at line 3", render_comparison(result))
        (self.repo / self.big).unlink()
        self.assertEqual(compare(self.repo, baseline)["counts"], {"missing": 10})

    def test_unscannable_scope_files_block_only_when_new_or_changed(self):
        self.write("src/app/Broken.java", "class Broken { void f() {")
        baseline = self.baseline()
        self.assertEqual([item["path"] for item in baseline["unscanned"]], ["src/app/Broken.java"])
        self.assertTrue(compare(self.repo, baseline)["passed"])
        self.write("src/app/Broken.java", "class Broken { void g() {")
        result = compare(self.repo, baseline)
        self.assertEqual((result["passed"], [item["path"] for item in result["unscanned"]]), (False, ["src/app/Broken.java"]))

    def test_scope_is_bounded_and_outside_code_is_not_searched(self):
        self.write("lib/Elsewhere.java", 'class Elsewhere {\n    void audit(String who) {\n        System.out.println("audit " + who);\n    }\n}\n')
        self.write("src/app/Small.java", "class Small { }")
        with self.assertRaisesRegex(ValueError, "more than 1 Java files"):
            self.baseline(max_files=1)
        baseline = self.baseline()
        self.write(self.big, BIG.replace('    void audit(String who) {\n        System.out.println("audit " + who);\n    }\n\n', ""))
        self.write("lib/Moved.java", 'class Moved {\n    void audit(String who) {\n        System.out.println("audit " + who);\n    }\n}\n')
        result = compare(self.repo, baseline)
        self.assertEqual(self.statuses(result), {"Orders#audit(String)": "missing"})
        self.assertIn("scope: src/app", render_comparison(result))
        with self.assertRaisesRegex(ValueError, "not a member-ledger/1 file"):
            compare(self.repo, {"schema": "other"})

    def test_git_repositories_use_the_same_scope_rules(self):
        if subprocess.run(["git", "--version"], capture_output=True, check=False).returncode:
            self.skipTest("git is not installed")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        baseline = self.baseline()
        self.write(self.big, BIG.replace("    private static int tax(int net) {\n        return net * 23 / 100;\n    }\n\n", ""))
        self.write("src/app/build/Generated.java", "class Generated {\n    private static int tax(int net) {\n        return net * 23 / 100;\n    }\n}\n")
        self.assertEqual(self.statuses(compare(self.repo, baseline)), {"Orders#tax(int)": "missing"})
        self.write("src/app/Tax.java", "class Tax {\n    private static int tax(int net) {\n        return net * 23 / 100;\n    }\n}\n")
        self.assertEqual(self.statuses(compare(self.repo, baseline)), {"Orders#tax(int)": "moved"})


class CommandLineTests(RepositoryCase):
    def run_tool(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPTS / "member_ledger.py"), *arguments], capture_output=True, text=True, encoding="utf-8", check=False)

    def test_commands_write_reports_and_exit_codes(self):
        outline_json, baseline_json, ledger_json = (str(self.base / name) for name in ("outline.json", "baseline.json", "ledger.json"))
        outline = self.run_tool("outline", str(self.repo), self.big, "--json", outline_json)
        self.assertEqual(outline.returncode, 0, outline.stderr)
        self.assertIn("L13-L15 3 method tax(int) [private static]", outline.stdout)
        self.assertEqual(len(json.loads(Path(outline_json).read_text(encoding="utf-8"))["members"]), 10)
        sliced = self.run_tool("slice", str(self.repo), self.big, "--lines", "L13-L15")
        self.assertEqual(sliced.stdout.splitlines()[1:], ["13:     private static int tax(int net) {", "14:         return net * 23 / 100;", "15:     }"])
        recorded = self.run_tool("baseline", str(self.repo), "--track", self.big, "--scope", "src/app", "--output", baseline_json)
        self.assertEqual((recorded.returncode, recorded.stdout), (0, "recorded 10 members of 1 tracked files; 0 other files in scope; 0 unscanned\n"))
        self.assertEqual(self.run_tool("compare", str(self.repo), baseline_json).returncode, 0)
        self.write(self.big, BIG.replace("    private int count;\n", ""))
        failed = self.run_tool("compare", str(self.repo), baseline_json, "--json", ledger_json)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("MISSING src/app/Orders.java::Orders#field:count was L4-L4 NEEDS DECISION", failed.stdout)
        self.assertEqual(json.loads(Path(ledger_json).read_text(encoding="utf-8"))["unaccounted"], ["src/app/Orders.java::Orders#field:count"])
        for arguments, message in ((("outline", str(self.repo), "src/app/Missing.java"), "missing or outside"), (("compare", str(self.repo), str(self.base / "absent.json")), "absent.json")):
            broken = self.run_tool(*arguments)
            self.assertEqual(broken.returncode, 2)
            self.assertIn(message, broken.stderr)

    def test_the_shared_dispatcher_passes_arguments_and_exit_codes_through(self):
        dispatcher = [sys.executable, str(SCRIPTS / "legacy_tools.py"), "members"]
        outline = subprocess.run([*dispatcher, "outline", str(self.repo), self.big], capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(outline.returncode, 0, outline.stderr)
        self.assertEqual(outline.stdout, self.run_tool("outline", str(self.repo), self.big).stdout)
        missing = subprocess.run([*dispatcher, "outline", str(self.repo), "src/app/Missing.java"], capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(missing.returncode, 2)

    def test_main_reports_scan_failures_as_operational_errors(self):
        self.write("src/app/Cut.java", "class Cut { void f() {")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(["outline", str(self.repo), "src/app/Cut.java"]), 2)
        self.assertEqual(errors.getvalue(), "member_ledger: src/app/Cut.java: unclosed '{' opened at line 1\n")


if __name__ == "__main__":
    unittest.main()
