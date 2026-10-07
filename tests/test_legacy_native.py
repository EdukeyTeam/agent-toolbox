"""Checks for the native tooling: the Rust map binary, the tool dispatcher,
the standalone bundle and the build helper. Every test runs a program.

Environment:
  LEGACY_REPO_MAP_BIN  built `legacy-repo-map`; otherwise it is built with
                       cargo into a directory outside the repository, and the
                       Rust tests are skipped when cargo is missing or
                       LEGACY_NATIVE_BUILD=0.
  LEGACY_TOOLS_BIN     built `legacy-tools` bundle program; bundle tests are
                       skipped without it.
  LEGACY_MAP_DEPS      optional directory holding the Python map dependencies
                       (pip --target layout) when they are not installed.
  LEGACY_BUILD_TOOLS   pinned build tools for real onefile archive verification.
  LEGACY_LICENSE_SOURCES  optional directory holding the source archives named
                       in `src/legacy-repo-map/licenses/manifest.json`, to
                       check the pinned notices against them again.
"""

import ast
import contextlib
import io
import hashlib
import errno
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import struct
import tarfile
import zlib
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "legacy-codebase-workflows"
SCRIPTS = SKILL / "scripts"
CRATE = REPO / "src" / "legacy-repo-map"
BUILD_HELPER = REPO / "scripts" / "build-legacy-tools.py"
MAP_DEPS = os.environ.get("LEGACY_MAP_DEPS")
EXE = ".exe" if os.name == "nt" else ""
ARTIFACTS = ("repo-map.md", "inventory.json", "map.meta.json")

SERVICE = "package app;\n\npublic class TransferService extends BaseService {\n    private Channel channel = new Channel();\n\n    public void startTransfer() {\n        channel.openChannel();\n        AuditLog.recordTransfer(this);\n    }\n}\n"
CHANNEL = "package app;\n\npublic class Channel {\n    public void openChannel() {}\n\n    void rarelyUsedHelper() {}\n}\n"
AUDIT = "package app;\n\npublic class AuditLog {\n    public static void recordTransfer(Object source) {\n        new Channel().openChannel();\n    }\n}\n"
FILES = {
    "src/app/TransferService.java": SERVICE,
    "src/app/Channel.java": CHANNEL,
    "src/app/AuditLog.java": AUDIT,
    "src/zażółć gęślą/Jaźń Service.java": "package a;\r\n\r\npublic class JaznService {\r\n    void obsłuż() { new Channel(); }\r\n}\r\n",
    "tools/ledger.py": "class Ledger:\n    def post_entry(self):\n        return total_rows()\n\n\ndef total_rows():\n    return 10\n",
    "web/cart.ts": "export interface CartPort { open(): void }\n\nexport function totalPrice(port: CartPort): number {\n  return 1;\n}\n",
    "web/View.tsx": "export function CartView() {\n  return <div>{totalPrice(null as any)}</div>;\n}\n",
    "native/pool.c": "struct pool { int size; };\n\nint acquire_slot(struct pool *p) { return p->size; }\n",
    "legacy/gen/Generated.java": "class GeneratedThing { void generated() {} }\n",
    "pom.xml": "<project><artifactId>demo</artifactId></project>\n",
    "conf/app.properties": "handler.class=app.TransferService\n",
    "web/page.jsp": "<% out.print(1); %>\n",
    "notes.txt": "plain text\n",
    ".gitignore": "*.log\nbuild/\n",
    "debug.log": "ignored noise\n",
    "build/Out.java": "class BuiltOutput {}\n",
    ".env": "API_TOKEN=native-test-secret\n",
    "deploy/id_rsa": "native-test-secret-key\n",
    "ops/db-credentials.yaml": "password: native-test-secret-yaml\n",
    "ops/client_secret.json": "{\"value\": \"native-test-secret-json\"}\n",
    "src/app/Secretary.java": "package app;\n\nclass Secretary { void fileMinutes() {} }\n",
    "src/app/CredentialsHelper.java": "package app;\n\nclass CredentialsHelper { void describe() {} }\n",
}
BINARY_FILES = {"lib/tool.bin": b"\0\x01\x02binary", "docs/latin1.txt": b"caf\xe9\n"}
CASES = {
    "default": [],
    "small budget": ["--budget", "64"],
    "focus symbol": ["--focus-symbol", "rarelyUsedHelper", "--budget", "128"],
    "focus file": ["--focus-file", "src/app/AuditLog.java", "--budget", "128"],
    "subtree": ["--subtree", "src"],
    "root subtree": ["--subtree", "."],
    "dot subtree": ["--subtree", "./src/"],
    "exclude": ["--exclude", "legacy/gen/*", "--exclude", "*.tsx"],
    "file cap": ["--max-files", "5"],
    "size cap": ["--max-file-bytes", "120"],
    "absent symbol": ["--focus-symbol", "resumeBrokenUpload"],
}


def python_environment():
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if MAP_DEPS:
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [MAP_DEPS, env.get("PYTHONPATH")]))
    return env


def python_map_available():
    if MAP_DEPS:
        return (Path(MAP_DEPS) / "tree_sitter_language_pack").is_dir() and (Path(MAP_DEPS) / "networkx").is_dir()
    return all(importlib.util.find_spec(name) for name in ("tree_sitter_language_pack", "networkx"))


def outside_repository(path):
    resolved = Path(path).resolve()
    return resolved != REPO and REPO not in resolved.parents


def locate_rust_binary():
    """Return (path, reason); path is None when the Rust tests cannot run."""
    configured = os.environ.get("LEGACY_REPO_MAP_BIN")
    if configured:
        return Path(configured), None
    if os.environ.get("LEGACY_NATIVE_BUILD") == "0":
        return None, "LEGACY_NATIVE_BUILD=0 and LEGACY_REPO_MAP_BIN is not set"
    if not shutil.which("cargo"):
        return None, "cargo is not installed and LEGACY_REPO_MAP_BIN is not set"
    target = Path(os.environ.get("CARGO_TARGET_DIR") or Path(tempfile.gettempdir()) / "legacy-repo-map-target")
    if not outside_repository(target):
        return None, "CARGO_TARGET_DIR points inside the repository"
    build = subprocess.run(
        ["cargo", "build", "--release", "--locked", "--manifest-path", str(CRATE / "Cargo.toml")],
        env={**os.environ, "CARGO_TARGET_DIR": str(target)}, capture_output=True, text=True,
    )
    if build.returncode != 0:
        raise RuntimeError(f"cargo build failed:\n{build.stderr[-4000:]}")
    return target / "release" / f"legacy-repo-map{EXE}", None


RUST_BINARY, RUST_SKIP = None, "not located"
TOOLS_BINARY = os.environ.get("LEGACY_TOOLS_BIN")


def setUpModule():
    global RUST_BINARY, RUST_SKIP
    RUST_BINARY, RUST_SKIP = locate_rust_binary()


class FixtureCase(unittest.TestCase):
    git = False

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.source = self.base / "source tree"
        for relative, content in FILES.items():
            self.write(relative, content.encode("utf-8"))
        for relative, content in BINARY_FILES.items():
            self.write(relative, content)
        if self.git:
            if not shutil.which("git"):
                self.skipTest("git is not installed")
            self.run_git("init", "-q")
            tracked = sorted((set(FILES) | set(BINARY_FILES)) - {"notes.txt", "debug.log", "build/Out.java"})
            self.run_git("add", "--", *tracked)
            self.run_git("commit", "-q", "-m", "fixture")

    def write(self, relative, content):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def run_git(self, *arguments):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        identity = ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
        subprocess.run(["git", "-C", str(self.source), *identity, *arguments], check=True, env=env, capture_output=True)

    def snapshot(self):
        return {path.relative_to(self.source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(self.source.rglob("*")) if path.is_file() and not path.is_symlink()}

    def rust(self, name, *arguments):
        return subprocess.run([str(RUST_BINARY), str(self.source), "--output-dir", str(self.base / name), *arguments], capture_output=True, text=True, encoding="utf-8")

    def python(self, name, *arguments):
        return subprocess.run([sys.executable, str(SCRIPTS / "repo_map.py"), str(self.source), "--output-dir", str(self.base / name), *arguments], capture_output=True, text=True, encoding="utf-8", env=python_environment())

    def load(self, name, artifact):
        return json.loads((self.base / name / artifact).read_text(encoding="utf-8"))


class RustParityTests(FixtureCase):
    """The Rust binary and the Python baseline on identical inputs."""

    def setUp(self):
        if RUST_BINARY is None:
            self.skipTest(RUST_SKIP)
        if not python_map_available():
            self.skipTest("Python map dependencies are not installed")
        super().setUp()

    def assert_same(self, label, arguments):
        rust = self.rust(f"rust-{label}", *arguments)
        python = self.python(f"python-{label}", *arguments)
        self.assertEqual(rust.returncode, 0, rust.stderr)
        self.assertEqual(python.returncode, 0, python.stderr)
        rust_map = (self.base / f"rust-{label}" / "repo-map.md").read_bytes()
        python_map = (self.base / f"python-{label}" / "repo-map.md").read_bytes()
        self.assertEqual(rust_map.decode("utf-8"), python_map.decode("utf-8"), label)
        rust_inventory, python_inventory = self.load(f"rust-{label}", "inventory.json"), self.load(f"python-{label}", "inventory.json")
        for key in ("files", "skipped", "fingerprint", "totals", "git", "revision", "dirty", "git_notes"):
            self.assertEqual(rust_inventory[key], python_inventory[key], f"{label}: inventory {key}")
        rust_meta, python_meta = self.load(f"rust-{label}", "map.meta.json"), self.load(f"python-{label}", "map.meta.json")
        for key in ("status", "coverage", "inventory_summary", "truncated", "estimated_tokens", "estimator", "map_sha256", "working_copy_fingerprint", "fingerprint_scope", "descriptors", "unsupported_languages", "selection", "skipped", "parse_failures"):
            self.assertEqual(rust_meta[key], python_meta[key], f"{label}: metadata {key}")
        self.assertEqual(json.loads(rust.stdout), {**json.loads(python.stdout), "map": str(self.base / f"rust-{label}" / "repo-map.md"), "metadata": str(self.base / f"rust-{label}" / "map.meta.json")})
        return rust_meta, rust_map.decode("utf-8")

    @unittest.skipUnless(os.name == "posix", "requires POSIX byte paths")
    def test_non_utf8_directory_leaves_and_scopes_match_python(self):
        self.source = self.base / "byte-directory-source"
        self.source.mkdir()
        bad = os.fsencode(self.source) + b"/a-\xff"
        try:
            os.mkdir(bad)
        except OSError as error:
            if error.errno == errno.EILSEQ:
                self.skipTest("Filesystem rejects invalid UTF-8 directory names (EILSEQ)")
            raise
        nested = bad + b"/nested-\xfe"
        os.mkdir(nested)
        for path in (bad + b"/One.java", nested + b"/Two.java"):
            with open(path, "wb") as handle:
                handle.write(b"class Hidden {}\n")
        self.write("a-�/Good.java", b"class Good {}\n")
        self.write("z-valid/Later.java", b"class Later {}\n")
        for label, arguments in (("byte-dirs", []), ("byte-dirs-capped", ["--max-files", "2"]), ("byte-dirs-scope", ["--subtree", "a-�"])):
            with self.subTest(case=label):
                meta, text = self.assert_same(label, arguments)
                self.assertNotIn("Hidden", text)
                inventory = self.load(f"rust-{label}", "inventory.json")
                if label == "byte-dirs":
                    self.assertEqual(inventory["totals"]["candidates_seen"], 4)
                    self.assertEqual([entry["path"] for entry in inventory["skipped"]], ["a-�/One.java", "a-�/nested-�/Two.java"])
                    self.assertFalse(meta["truncated"])
                elif label == "byte-dirs-capped":
                    self.assertEqual(inventory["totals"]["candidates_seen"], 3)
                    self.assertTrue(meta["truncated"])
                else:
                    self.assertEqual(inventory["totals"]["candidates_seen"], 1)
                    self.assertEqual(inventory["skipped"], [])
        # Both descendant files remain byte-for-byte unchanged.
        for path in (bad + b"/One.java", nested + b"/Two.java"):
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), b"class Hidden {}\n")

    def test_maps_inventories_and_coverage_agree(self):
        before = self.snapshot()
        for label, arguments in CASES.items():
            with self.subTest(case=label):
                self.assert_same(label.replace(" ", "-"), arguments)
        self.assertEqual(before, self.snapshot())

    def test_agreed_output_has_the_expected_content(self):
        meta, text = self.assert_same("content", [])
        self.assertIn("src/app/Channel.java:L4: public void openChannel() {}\n", text)
        self.assertIn("src/zażółć gęślą/Jaźń Service.java:L4: void obsłuż() { new Channel(); }\n", text)
        self.assertIn("tools/ledger.py:L2: def post_entry(self):\n", text)
        self.assertIn("web/cart.ts:L3: export function totalPrice(port: CartPort): number {\n", text)
        self.assertNotIn("\r", text)
        self.assertNotIn("native-test-secret", "".join((self.base / "rust-content" / name).read_text(encoding="utf-8") for name in ARTIFACTS))
        reasons = {item["path"]: item["reason"] for item in meta["skipped"]}
        self.assertEqual(reasons[".env"], "secret-looking file")
        self.assertEqual(reasons["deploy/id_rsa"], "secret-looking file")
        self.assertEqual(reasons["ops/db-credentials.yaml"], "secret-looking file")
        self.assertEqual(reasons["ops/client_secret.json"], "secret-looking file")
        # A word inside a longer name is not a secret marker.
        self.assertIn("src/app/Secretary.java:L3: class Secretary { void fileMinutes() {} }\n", text)
        self.assertIn("src/app/CredentialsHelper.java:L3:", text)
        self.assertEqual(reasons["lib/tool.bin"], "binary file")
        self.assertEqual(reasons["docs/latin1.txt"], "non-UTF-8 file")
        self.assertNotIn("debug.log", reasons)
        self.assertIn("pom.xml", meta["descriptors"])
        self.assertIn("web/page.jsp", meta["unsupported_languages"])

    def test_inventory_only_agrees(self):
        rust, python = self.rust("rust-inventory", "--inventory-only"), self.python("python-inventory", "--inventory-only")
        self.assertEqual((rust.returncode, python.returncode), (0, 0), rust.stderr + python.stderr)
        for artifact in ("repo-map.md", "inventory.json"):
            self.assertEqual((self.base / "rust-inventory" / artifact).read_bytes(), (self.base / "python-inventory" / artifact).read_bytes(), artifact)
        rust_meta, python_meta = self.load("rust-inventory", "map.meta.json"), self.load("python-inventory", "map.meta.json")
        self.assertEqual(rust_meta["status"], "inventory-only")
        for key in ("status", "coverage", "inventory_summary", "truncated", "estimated_tokens", "map_sha256", "skipped", "selection", "working_copy_fingerprint"):
            self.assertEqual(rust_meta[key], python_meta[key], key)

    def test_absent_symbol_is_not_invented_by_either_tool(self):
        meta, text = self.assert_same("absent", ["--focus-symbol", "resumeBrokenUpload"])
        self.assertNotIn("resumeBrokenUpload", text)
        self.assertEqual(meta["focus_not_found"]["symbols_without_definitions"], ["resumeBrokenUpload"])

    def test_known_gap_python_module_constants(self):
        # The crates.io Python grammar wraps a module-level assignment in an
        # expression_statement node, which the vendored query expects; the
        # grammar build inside tree-sitter-language-pack 0.13.0 does not. The
        # Rust map therefore lists module constants that the baseline omits.
        self.write("tools/settings.py", b"MAX_ROWS = 10\n\n\ndef row_limit():\n    return MAX_ROWS\n")
        rust, python = self.rust("rust-constants"), self.python("python-constants")
        self.assertEqual((rust.returncode, python.returncode), (0, 0), rust.stderr + python.stderr)
        rust_lines = set((self.base / "rust-constants" / "repo-map.md").read_text(encoding="utf-8").splitlines())
        python_lines = set((self.base / "python-constants" / "repo-map.md").read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(python_lines, rust_lines)
        self.assertLessEqual(rust_lines - python_lines, {"tools/settings.py:L1: MAX_ROWS = 10"})
        self.assertIn("tools/settings.py:L4: def row_limit():", rust_lines & python_lines)
        self.assertEqual(self.load("rust-constants", "inventory.json")["fingerprint"], self.load("python-constants", "inventory.json")["fingerprint"])

    def test_both_refuse_bad_bounds_and_output_inside_the_source(self):
        cases = [(["--budget", "63"], None), (["--max-files", "0"], None), (["--max-file-bytes", "20000001"], None), ([], self.source / "maps")]
        for arguments, output in cases:
            with self.subTest(arguments=arguments, output=output):
                rust_command = [str(RUST_BINARY), str(self.source), "--output-dir", str(output or self.base / "refused"), *arguments]
                python_command = [sys.executable, str(SCRIPTS / "repo_map.py"), str(self.source), "--output-dir", str(output or self.base / "refused"), *arguments]
                self.assertEqual(subprocess.run(rust_command, capture_output=True).returncode, 2)
                self.assertEqual(subprocess.run(python_command, capture_output=True, env=python_environment()).returncode, 2)
        self.assertFalse((self.source / "maps").exists())

    @unittest.skipIf(os.name == "nt", "symbolic links need privileges on Windows")
    def test_both_skip_links_that_leave_the_source(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Outside.java").write_text("class EscapedOutside {}\n", encoding="utf-8")
        (self.source / "src/app/Linked.java").symlink_to(outside / "Outside.java")
        (self.source / "linked-dir").symlink_to(outside, target_is_directory=True)
        meta, text = self.assert_same("links", [])
        self.assertNotIn("EscapedOutside", text)
        self.assertIn({"path": "src/app/Linked.java", "reason": "symlink excluded"}, meta["skipped"])

    @unittest.skipIf(os.name != "posix", "requires POSIX file names")
    def test_control_characters_in_paths_are_skipped_identically(self):
        hostile = {
            "src/app/Line\nsrc/app/Forged.java:L1: class Forged {}\n.java": "src/app/Line\\nsrc/app/Forged.java:L1: class Forged {}\\n.java",
            "src/app/Tab\tStop.java": "src/app/Tab\\tStop.java",
            "src/app/Del\x7fete.java": "src/app/Del\\u007fete.java",
            "src/app/Nel\x85line.java": "src/app/Nel\\u0085line.java",
            "src/app/Line\u2028break.java": "src/app/Line\\u2028break.java",
            "src/app/Para\u2029break.java": "src/app/Para\\u2029break.java",
            "src/new\rline dir/Inside.java": "src/new\\rline dir/Inside.java",
            "src/app/Esc\x1b[2J \"q\" b\\s ż.java": "src/app/Esc\\u001b[2J \\\"q\\\" b\\\\s ż.java",
        }
        for index, relative in enumerate(hostile):
            self.write(relative, f"class Hostile{index} {{ void injected() {{}} }}\n".encode("utf-8"))
        before = self.snapshot()
        for label, arguments in (("control", []), ("control-capped", ["--max-files", "12"]), ("control-inventory", ["--inventory-only"])):
            with self.subTest(case=label):
                if "--inventory-only" in arguments:
                    self.assertEqual(self.rust(f"rust-{label}", *arguments).returncode, 0)
                    self.assertEqual(self.python(f"python-{label}", *arguments).returncode, 0)
                    inventories = [self.load(f"{tool}-{label}", "inventory.json") for tool in ("rust", "python")]
                    for key in ("files", "skipped", "fingerprint", "totals"):
                        self.assertEqual(inventories[0][key], inventories[1][key], key)
                    continue
                meta, text = self.assert_same(label, arguments)
                self.assertEqual(meta["status"], "complete")
                self.assertNotIn("Hostile", text)
                self.assertNotIn("Forged", text)
        inventory = self.load("rust-control", "inventory.json")
        refused = {item["path"] for item in inventory["skipped"] if item["reason"] == "control character in path"}
        self.assertEqual(refused, set(hostile.values()))
        self.assertEqual({json.loads(f'"{shown}"') for shown in refused}, set(hostile))
        self.assertIn("src/app/Channel.java", [item["path"] for item in inventory["files"]])
        for tool in ("rust", "python"):
            for artifact in ARTIFACTS:
                written = (self.base / f"{tool}-control" / artifact).read_text(encoding="utf-8")
                self.assertFalse([character for character in written if (ord(character) < 32 or ord(character) == 127) and character != "\n"], f"{tool} {artifact}")
        self.assertEqual(before, self.snapshot())

    @unittest.skipUnless(os.name == "posix", "requires literal POSIX backslash filenames")
    def test_literal_backslash_path_identities_agree(self):
        files = {"a\\b.java": "class LiteralBackslash {}\n", "a/b.java": "class NestedIdentity {}\n", "..\\literal.java": "class LegitimateLiteral {}\n"}
        for name, text in files.items():
            self.write(name, text.encode())
        for git in (False, "untracked", "tracked"):
            if git:
                subprocess.run(["git", "-C", str(self.source), "init", "-q"], check=True)
                if git == "tracked":
                    subprocess.run(["git", "-C", str(self.source), "add", "--", *files], check=True)
            before = self.snapshot()
            label = "literal-backslash-" + str(git)
            meta, content = self.assert_same(label, [])
            entries = {entry["path"]: entry for entry in self.load("rust-" + label, "inventory.json")["files"]}
            for name, text in files.items():
                self.assertEqual(entries[name]["sha256"], hashlib.sha256(text.encode()).hexdigest())
                self.assertIn(name + ":L1: " + text.strip(), content)
            self.assert_same(label + "-focused", ["--subtree", "a", "--focus-file", "a\\b.java"])
            self.assertEqual(before, self.snapshot())

    def test_snippet_controls_sanitize_identically_without_source_mutation(self):
        controls = "".join(chr(value) for value in (*range(1, 32), *range(127, 160), 0x2028, 0x2029) if value != 10)
        source = "class Hostile {\tvoid run() {} } // żółć" + controls + " marker\r\n\nclass After {}\n"
        self.write("Hostile.java", source.encode())
        before = self.snapshot()
        meta, text = self.assert_same("snippet-controls", [])
        self.assertIn("Hostile.java:L1: class Hostile {\tvoid run() {} } // żółć", text)
        self.assertIn("Hostile.java:L3: class After {}", text)
        self.assertFalse(any((ord(c) < 32 or 127 <= ord(c) < 160 or c in "\u2028\u2029") and c not in "\t\n" for c in text))
        entry = next(entry for entry in self.load("rust-snippet-controls", "inventory.json")["files"] if entry["path"] == "Hostile.java")
        self.assertEqual(entry["sha256"], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(before, self.snapshot())

    def test_selection_policy_tables_match_the_python_modules(self):
        policy = json.loads(subprocess.run([str(RUST_BINARY), "--print-policy"], check=True, capture_output=True, text=True, encoding="utf-8").stdout)
        code = "import json, re, repo_files as f; print(json.dumps({k: sorted(v) if isinstance(v, (set, frozenset)) else [v.pattern, bool(v.flags & re.IGNORECASE)] if isinstance(v, re.Pattern) else v for k, v in list(vars(f).items()) if k.isupper()}))"
        files = json.loads(subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True, cwd=SCRIPTS, env=python_environment()).stdout)
        self.assertEqual(policy["languages"], files["LANGUAGES"])
        # Names are lowercased before matching in both tools.
        self.assertEqual([policy["secret_name_pattern"], True], files["SECRET_PATTERN"])
        for rust_key, python_key in [("descriptor_suffixes", "DESCRIPTOR_SUFFIXES"), ("descriptor_names", "DESCRIPTOR_NAMES"), ("secret_names", "SECRET_NAMES"), ("secret_suffixes", "SECRET_SUFFIXES"), ("ignored_dirs", "IGNORED_DIRS")]:
            self.assertEqual(sorted(policy[rust_key]), files[python_key], python_key)
        limits = policy["limits"]
        self.assertEqual([limits["default_max_files"], limits["default_max_file_bytes"], limits["hard_max_files"], limits["hard_max_file_bytes"]], [files["DEFAULT_MAX_FILES"], files["DEFAULT_MAX_FILE_BYTES"], files["HARD_MAX_FILES"], files["HARD_MAX_FILE_BYTES"]])
        # Constants of repo_map.py are read without importing its dependencies.
        constants = {}
        for node in ast.parse((SCRIPTS / "repo_map.py").read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper():
                try:
                    constants[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
        self.assertEqual({language: entry["path"] for language, entry in policy["queries"].items()}, constants["QUERY_PATHS"])
        for language, entry in policy["queries"].items():
            vendored = SKILL / "vendor" / "queries" / entry["path"]
            self.assertEqual(entry["sha256"], hashlib.sha256(vendored.read_bytes()).hexdigest(), language)
        self.assertEqual([limits["max_tags_per_file"], limits["max_total_tags"], limits["max_budget"]], [constants["MAX_TAGS_PER_FILE"], constants["MAX_TOTAL_TAGS"], constants["MAX_BUDGET"]])
        self.assertEqual(policy["baseline_contract"], f"repo_map.py {constants['VERSION']}")


class RustGitParityTests(RustParityTests):
    """The same comparisons on a git work tree with an untracked file."""

    git = True

    def test_module_root_inherits_parent_git_policy_and_scopes_dirty_state(self):
        module = self.source / "src"
        self.write("src/temporary.log", b"ignored by parent policy\n")
        self.write("src/new.py", b"def new_work():\n    pass\n")
        self.write("outside.py", b"def outside_work():\n    pass\n")
        results = {}
        for tool, command in (("rust", [str(RUST_BINARY)]), ("python", [sys.executable, str(SCRIPTS / "repo_map.py")])):
            out = self.base / f"module-{tool}"
            env = python_environment() if tool == "python" else os.environ.copy()
            run = subprocess.run([*command, str(module), "--output-dir", str(out)], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            results[tool] = {
                "map": (out / "repo-map.md").read_bytes(),
                "inventory": json.loads((out / "inventory.json").read_text()),
            }
        self.assertEqual(results["rust"], results["python"])
        inventory = results["rust"]["inventory"]
        self.assertTrue(inventory["git"])
        self.assertTrue(inventory["dirty"])
        paths = {item["path"] for item in inventory["files"]}
        self.assertIn("new.py", paths)
        self.assertNotIn("temporary.log", paths)
        self.assertNotIn("outside.py", paths)

        (module / "new.py").unlink()
        clean = subprocess.run([str(RUST_BINARY), str(module), "--output-dir", str(self.base / "module-clean")], capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertFalse(self.load("module-clean", "inventory.json")["dirty"])

    def test_explicit_parent_ignored_root_remains_independent(self):
        ignored = self.source / "build"
        for tool, command in (("rust", [str(RUST_BINARY)]), ("python", [sys.executable, str(SCRIPTS / "repo_map.py")])):
            out = self.base / f"ignored-{tool}"
            env = python_environment() if tool == "python" else os.environ.copy()
            run = subprocess.run([*command, str(ignored), "--output-dir", str(out)], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            inventory = json.loads((out / "inventory.json").read_text())
            self.assertFalse(inventory["git"])
            self.assertIsNone(inventory["revision"])
            self.assertIn("Out.java", {item["path"] for item in inventory["files"]})

    def test_inherited_git_trace_cannot_write_into_source(self):
        trace = self.source / "trace.log"
        env = {**os.environ, "GIT_TRACE": str(trace), "GIT_DIR": str(self.base / "wrong-git-dir")}
        result = subprocess.run([str(RUST_BINARY), str(self.source), "--output-dir", str(self.base / "trace-map")], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.load("trace-map", "inventory.json")["git"])
        self.assertFalse(trace.exists())

    @unittest.skipUnless(os.name == "posix", "requires POSIX byte index paths")
    def test_unmerged_non_utf8_paths_match_python_before_file_cap(self):
        source = self.base / "raw-index"
        source.mkdir()
        (source / "z.java").write_bytes(b"class LaterValid {}\n")
        command = ["git", "-C", str(source)]
        subprocess.run([*command, "init", "-q"], check=True)
        subprocess.run([*command, "add", "--", "z.java"], check=True)
        blob = subprocess.check_output([*command, "hash-object", "z.java"]).strip()
        raw = b"a-\xff.java"
        stages = b"".join(b"100644 " + blob + b" " + str(stage).encode() + b"\t" + raw + b"\0" for stage in (1, 2, 3))
        subprocess.run([*command, "update-index", "-z", "--index-info"], input=stages, check=True)
        self.assertEqual(subprocess.check_output([*command, "ls-files", "-z"]).count(raw + b"\0"), 3)
        outputs = []
        for tool, mapper, env in (("rust", [str(RUST_BINARY)], os.environ.copy()), ("python", [sys.executable, str(SCRIPTS / "repo_map.py")], python_environment())):
            out = self.base / (tool + "-raw-index")
            result = subprocess.run([*mapper, str(source), "--output-dir", str(out), "--max-files", "2"], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            meta = json.loads((out / "map.meta.json").read_text())
            inventory = json.loads((out / "inventory.json").read_text())
            self.assertEqual(meta["coverage"]["candidates_seen"], 2)
            self.assertEqual(meta["coverage"]["selected_files"], 1)
            self.assertFalse(meta["truncated"])
            self.assertEqual(inventory["skipped"], [{"path": "a-\ufffd.java", "reason": "non-UTF-8 path"}])
            outputs.append((inventory, (out / "repo-map.md").read_bytes()))
        self.assertEqual(outputs[0], outputs[1])

    def test_corrupt_git_index_records_inventory_failure_and_invalidates_old_outputs(self):
        good = self.rust("same-output")
        self.assertEqual(good.returncode, 0, good.stderr)
        (self.source / ".git" / "index").write_bytes(b"invalid git index")
        failed = self.rust("same-output")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.load("same-output", "map.meta.json")["failure"]["stage"], "inventory")
        self.assertEqual(self.load("same-output", "map.meta.json")["status"], "failed")
        self.assertEqual(self.load("same-output", "inventory.json")["status"], "failed")
        self.assertNotIn("openChannel", (self.base / "same-output" / "repo-map.md").read_text(encoding="utf-8"))

    def test_dirty_work_tree_and_deleted_tracked_file(self):
        (self.source / "src/app/Channel.java").unlink()
        self.write("src/app/Fresh.java", b"class FreshUntracked {}\n")
        meta, text = self.assert_same("dirty", [])
        self.assertIn("FreshUntracked", text)
        self.assertIn({"path": "src/app/Channel.java", "reason": "missing or outside source"}, meta["skipped"])
        self.assertTrue(self.load("rust-dirty", "inventory.json")["dirty"])


class RustWithoutPythonTests(FixtureCase):
    """The binary needs neither Python nor git on PATH."""

    def setUp(self):
        if RUST_BINARY is None:
            self.skipTest(RUST_SKIP)
        super().setUp()

    def test_runs_with_an_empty_path(self):
        env = {key: value for key, value in os.environ.items() if key.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")}
        env["PATH"] = str(self.base / "empty")
        result = subprocess.run([str(RUST_BINARY), str(self.source), "--output-dir", str(self.base / "out")], env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = self.load("out", "map.meta.json")
        self.assertFalse(meta["git"])
        self.assertEqual(meta["implementation"], "rust (experimental)")
        self.assertIn("openChannel", (self.base / "out" / "repo-map.md").read_text(encoding="utf-8"))

    def test_debug_tags_are_invalidated_when_the_flag_is_not_requested(self):
        result = self.rust("debug-reuse", "--debug-tags")
        self.assertEqual(result.returncode, 0, result.stderr)
        debug = self.base / "debug-reuse/tags.debug.json"
        self.assertTrue(debug.is_file())
        self.write("src/app/Channel.java", CHANNEL.replace("openChannel", "updatedChannel").encode())
        result = self.rust("debug-reuse")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(debug.exists())
        result = self.rust("debug-reuse", "--debug-tags")
        self.assertEqual(result.returncode, 0, result.stderr)
        tags = json.loads(debug.read_text())
        names = {tag["name"] for tag in tags["src/app/Channel.java"]}
        self.assertIn("updatedChannel", names)
        self.assertNotIn("openChannel", names)
        result = self.rust("debug-reuse", "--inventory-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(debug.exists())

    @unittest.skipIf(os.name != "posix", "requires POSIX byte paths")
    def test_invalid_utf8_filenames_respect_max_files(self):
        source = self.base / "byte-paths"
        source.mkdir()
        for index in range(4):
            try:
                handle = open(os.fsencode(source) + b"/file-" + bytes([0xff, 48 + index]), "wb")
            except OSError as error:
                if error.errno == errno.EILSEQ:
                    self.skipTest("Filesystem rejects invalid UTF-8 filenames (EILSEQ)")
                raise
            with handle:
                handle.write(b"class Example {}\n")
        result = subprocess.run([str(RUST_BINARY), str(source), "--output-dir", str(self.base / "byte-out"), "--max-files", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        inventory = self.load("byte-out", "inventory.json")
        self.assertEqual(inventory["totals"]["candidates_seen"], 2)
        self.assertEqual(sum(item["reason"] == "non-UTF-8 path" for item in inventory["skipped"]), 1)
        self.assertTrue(self.load("byte-out", "map.meta.json")["truncated"])

    @unittest.skipIf(os.name != "posix" or getattr(os, "geteuid", lambda: 1)() == 0, "requires non-root POSIX permissions")
    def test_unreadable_directory_fails_instead_of_completing(self):
        unreadable = self.source / "unreadable"
        unreadable.mkdir()
        (unreadable / "Hidden.java").write_text("class Hidden {}\n", encoding="utf-8")
        unreadable.chmod(0)
        self.addCleanup(unreadable.chmod, 0o700)
        result = self.rust("unreadable-out")
        self.assertNotEqual(result.returncode, 0)
        meta = self.load("unreadable-out", "map.meta.json")
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["failure"]["stage"], "inventory")
        self.assertIn("unreadable/", meta["failure"]["message"])


class DispatcherTests(FixtureCase):
    """`legacy_tools.py` from source and, when provided, the frozen bundle."""

    def programs(self):
        yield "source", [sys.executable, str(SCRIPTS / "legacy_tools.py")], python_environment()
        if TOOLS_BINARY:
            # No Python settings and no interpreter on PATH for the bundle.
            env = {key: value for key, value in os.environ.items() if key.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE")}
            git = shutil.which("git")
            env["PATH"] = str(Path(git).parent) if git and os.name == "nt" else str(self.base / "path")
            if git and os.name != "nt":
                (self.base / "path").mkdir(exist_ok=True)
                if not (self.base / "path" / "git").exists():
                    (self.base / "path" / "git").symlink_to(git)
            yield "bundle", [TOOLS_BINARY], env

    def call(self, program, env, *arguments):
        return subprocess.run([*program, *arguments], env=env, capture_output=True, text=True, encoding="utf-8", cwd=self.base)

    def test_csharp_cache_identity_is_available_without_external_python_packages(self):
        folder = self.source / "csharp"
        folder.mkdir()
        (folder / "Example.cs").write_text("class Example { public void Run() {} }\n", encoding="utf-8", newline="\n")
        for label, program, env in self.programs():
            with self.subTest(program=label):
                output = self.base / ("csharp-map-" + label)
                result = self.call(program, env, "map", str(self.source), "--subtree", "csharp", "--output-dir", str(output))
                self.assertEqual(result.returncode, 0, result.stderr)
                metadata = json.loads((output / "map.meta.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["dependencies"]["tree-sitter-c-sharp"], "0.23.5")
                self.assertEqual(metadata["coverage"]["parsed_files"], 1)
                self.assertIn("Example.cs:L1", (output / "repo-map.md").read_text(encoding="utf-8"))
                caches = [json.loads(path.read_text(encoding="utf-8")) for path in (output / "cache").glob("*.json")]
                self.assertEqual(len(caches), 1)
                self.assertTrue(caches[0]["parser_version"].endswith(":0.23.5"))

    def test_info_help_and_unknown_command(self):
        for label, program, env in self.programs():
            with self.subTest(program=label):
                info = json.loads(self.call(program, env, "info").stdout)
                self.assertEqual(info["frozen"], label == "bundle")
                self.assertFalse(info["semantic_runtime_included"])
                self.assertEqual(info["scripts"]["legacy_tools.py"], hashlib.sha256((SCRIPTS / "legacy_tools.py").read_bytes()).hexdigest())
                self.assertIn("check-citations", self.call(program, env, "--help").stdout)
                unknown = self.call(program, env, "explode")
                self.assertEqual(unknown.returncode, 2)
                self.assertIn("unknown command", unknown.stderr)
                self.assertEqual(self.call(program, env).returncode, 2)
                notices = self.call(program, env, "notices").stdout
                self.assertIn("Aider", notices)
                self.assertIn("vendor/licenses/java-LICENSE.txt", notices)
                self.assertNotIn("vendor\\licenses", notices)

    def test_bundle_binary_licenses_match_manifest(self):
        if not TOOLS_BINARY:
            self.skipTest("LEGACY_TOOLS_BIN is not set")
        artifact = Path(TOOLS_BINARY).parent
        manifest = json.loads((artifact / "BUILD-INFO.json").read_text(encoding="utf-8"))
        records = manifest["collected_binaries"]
        self.assertTrue(records)
        self.assertEqual(len({record["name"] for record in records}), len(records))
        for record in records:
            with self.subTest(binary=record["name"]):
                license_path = artifact / record["license"]
                self.assertTrue(license_path.is_file())
                self.assertEqual(hashlib.sha256(license_path.read_bytes()).hexdigest(), record["license_sha256"])
                self.assertTrue(record["license_source"])
                self.assertTrue(record["version"])
                self.assertRegex(record["source_sha256"], r"^[0-9a-f]{64}$")
                if manifest["mode"] == "onedir":
                    self.assertEqual(hashlib.sha256((artifact / "_internal" / record["name"]).read_bytes()).hexdigest(), record["sha256"])
        if manifest["mode"] == "onefile":
            helper = BuildHelperTests.helper()
            tools = os.environ.get("LEGACY_BUILD_TOOLS")
            search = [Path(tools)] if tools else []
            toc = self.base / "Analysis-00.toc"
            entries = [(record["name"], "unused Analysis path", record["kind"]) for record in records]
            (self.base / "PKG-00.toc").write_text(repr((None, None, entries)), encoding="utf-8")
            actual = helper.packaged_binary_hashes(toc, "onefile", artifact, search)
            self.assertEqual(actual, {record["name"]: record["sha256"] for record in records})
        for notice in manifest.get("additional_notices", []):
            path = artifact / notice["license"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), notice["sha256"])
            self.assertIn(notice["license"], self.call([str(TOOLS_BINARY)], os.environ.copy(), "notices").stdout)
        serialized = json.dumps(manifest)
        self.assertNotIn(str(REPO), serialized)
        self.assertNotIn(str(artifact.parent.parent), serialized)

    def test_check_citations_passes_arguments_and_exit_codes_through(self):
        digest = hashlib.sha256((self.source / "src/app/Channel.java").read_bytes()).hexdigest()
        card = {"path": "src/app/Channel.java", "sha256": digest, "start_line": 4, "end_line": 4, "quote": "public void openChannel() {}"}
        (self.base / "good.json").write_text(json.dumps({"citations": [card]}), encoding="utf-8")
        (self.base / "stale.json").write_text(json.dumps({"citations": [{**card, "sha256": "0" * 64}]}), encoding="utf-8")
        (self.base / "wrong-line.json").write_text(json.dumps({"citations": [{**card, "start_line": 6, "end_line": 6}]}), encoding="utf-8")
        for label, program, env in self.programs():
            with self.subTest(program=label):
                good = self.call(program, env, "check-citations", str(self.source), str(self.base / "good.json"))
                self.assertEqual(good.returncode, 0, good.stderr)
                self.assertTrue(json.loads(good.stdout)["valid"])
                self.assertEqual(self.call(program, env, "check-citations", str(self.source), str(self.base / "stale.json")).returncode, 1)
                self.assertEqual(self.call(program, env, "check-citations", str(self.source), str(self.base / "wrong-line.json")).returncode, 1)

    def test_map_through_the_dispatcher_equals_the_direct_tool(self):
        if not python_map_available():
            self.skipTest("Python map dependencies are not installed")
        direct = self.python("direct", "--focus-symbol", "openChannel", "--budget", "256")
        self.assertEqual(direct.returncode, 0, direct.stderr)
        expected = (self.base / "direct" / "repo-map.md").read_bytes()
        for label, program, env in self.programs():
            with self.subTest(program=label):
                result = self.call(program, env, "map", str(self.source), "--output-dir", str(self.base / f"out-{label}"), "--focus-symbol", "openChannel", "--budget", "256")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((self.base / f"out-{label}" / "repo-map.md").read_bytes(), expected)
                self.assertEqual(json.loads(result.stdout)["coverage"], json.loads(direct.stdout)["coverage"])
                refused = self.call(program, env, "map", str(self.source), "--output-dir", str(self.source / "maps"))
                self.assertEqual(refused.returncode, 2)

    def test_unicode_numeric_queries_through_the_dispatcher_keep_citations(self):
        cases = (("latin.py", "café"), ("cjk.py", "你好"), ("number.py", "404"))
        for name, body in cases:
            (self.source / name).write_text(body + "\n", encoding="utf-8", newline="\n")
        for label, program, env in self.programs():
            with self.subTest(program=label):
                database = self.base / f"unicode-index-{label}.sqlite"
                indexed = self.call(program, env, "index", str(self.source), "--database", str(database), "--library-id", "/local/fixture")
                self.assertEqual(indexed.returncode, 0, indexed.stderr)
                before = database.read_bytes()
                for name, body in cases:
                    with self.subTest(query=body):
                        found = self.call(program, env, "query", "--database", str(database), "--query", body)
                        self.assertEqual(found.returncode, 0, found.stderr)
                        results = json.loads(found.stdout)["results"]
                        self.assertEqual(len(results), 1)
                        self.assertEqual(results[0]["text"], body)
                        self.assertEqual(results[0]["source"]["path"], name)
                        self.assertEqual((results[0]["source"]["startLine"], results[0]["source"]["endLine"]), (1, 1))
                        self.assertEqual(results[0]["source"]["fileSha256"], hashlib.sha256((body + "\n").encode("utf-8")).hexdigest())
                self.assertEqual(database.read_bytes(), before)

    def test_index_and_query_through_the_dispatcher(self):
        for label, program, env in self.programs():
            with self.subTest(program=label):
                database = self.base / f"index-{label}.sqlite"
                indexed = self.call(program, env, "index", str(self.source), "--database", str(database), "--library-id", "/local/fixture")
                self.assertEqual(indexed.returncode, 0, indexed.stderr)
                found = self.call(program, env, "query", "--database", str(database), "--query", "recordTransfer")
                self.assertEqual(found.returncode, 0, found.stderr)
                self.assertIn("AuditLog.java", found.stdout)
                self.assertNotIn("native-test-secret", found.stdout)



# Unmodified full notice fixture from https://raw.githubusercontent.com/libffi/libffi/v3.4.4/LICENSE
LIBFFI_NOTICE = "libffi - Copyright (c) 1996-2022  Anthony Green, Red Hat, Inc and others.\nSee source files for details.\n\nPermission is hereby granted, free of charge, to any person obtaining\na copy of this software and associated documentation files (the\n``Software''), to deal in the Software without restriction, including\nwithout limitation the rights to use, copy, modify, merge, publish,\ndistribute, sublicense, and/or sell copies of the Software, and to\npermit persons to whom the Software is furnished to do so, subject to\nthe following conditions:\n\nThe above copyright notice and this permission notice shall be\nincluded in all copies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED ``AS IS'', WITHOUT WARRANTY OF ANY KIND,\nEXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF\nMERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.\nIN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY\nCLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,\nTORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE\nSOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n"

# Unmodified full notice fixture from https://raw.githubusercontent.com/python/cpython/v3.12.10/Modules/expat/COPYING
EXPAT_NOTICE = 'Copyright (c) 1998-2000 Thai Open Source Software Center Ltd and Clark Cooper\nCopyright (c) 2001-2022 Expat maintainers\n\nPermission is hereby granted, free of charge, to any person obtaining\na copy of this software and associated documentation files (the\n"Software"), to deal in the Software without restriction, including\nwithout limitation the rights to use, copy, modify, merge, publish,\ndistribute, sublicense, and/or sell copies of the Software, and to\npermit persons to whom the Software is furnished to do so, subject to\nthe following conditions:\n\nThe above copyright notice and this permission notice shall be included\nin all copies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,\nEXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF\nMERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.\nIN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY\nCLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,\nTORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE\nSOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n'

# Unmodified first full comment from https://raw.githubusercontent.com/madler/zlib/v1.3.1/zlib.h
ZLIB_NOTICE = "/* zlib.h -- interface of the 'zlib' general purpose compression library\n  version 1.3.1, January 22nd, 2024\n\n  Copyright (C) 1995-2024 Jean-loup Gailly and Mark Adler\n\n  This software is provided 'as-is', without any express or implied\n  warranty.  In no event will the authors be held liable for any damages\n  arising from the use of this software.\n\n  Permission is granted to anyone to use this software for any purpose,\n  including commercial applications, and to alter it and redistribute it\n  freely, subject to the following restrictions:\n\n  1. The origin of this software must not be misrepresented; you must not\n     claim that you wrote the original software. If you use this software\n     in a product, an acknowledgment in the product documentation would be\n     appreciated but is not required.\n  2. Altered source versions must be plainly marked as such, and must not be\n     misrepresented as being the original software.\n  3. This notice may not be removed or altered from any source distribution.\n\n  Jean-loup Gailly        Mark Adler\n  jloup@gzip.org          madler@alumni.caltech.edu\n\n\n  The data format used by the zlib library is described by RFCs (Request for\n  Comments) 1950 to 1952 in the files http://tools.ietf.org/html/rfc1950\n  (zlib format), rfc1951 (deflate format) and rfc1952 (gzip format).\n*/"
ZLIB_HEADER = (ZLIB_NOTICE + '\n#define ZLIB_VERSION "1.3.1"\n').encode("utf-8")


class BuildHelperTests(unittest.TestCase):
    @staticmethod
    def helper():
        spec = importlib.util.spec_from_file_location("legacy_build_helper", BUILD_HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Initialize the real host before tests mock platform/base_prefix.
        module.sysconfig.get_config_vars()
        return module

    def test_collected_cpython_extension_does_not_claim_adjacent_library(self):
        helper = self.helper()
        stdlib = Path(helper.sysconfig.get_path("stdlib"))
        self.assertTrue(helper.is_cpython_binary(stdlib / "lib-dynload" / "_ssl.pyd", "EXTENSION"))
        self.assertFalse(helper.is_cpython_binary(stdlib / "lib-dynload" / "libcrypto-3-x64.dll", "BINARY"))
        self.assertFalse(helper.is_cpython_binary(stdlib / "lib-dynload" / "libsqlite3.so", "BINARY"))

    def test_cpython_interpreter_filename_recognition_is_narrow(self):
        helper = self.helper()
        for name in ("libpython3.12.so", "libpython3.12.so.1.0", "libpython3.14t.so.1.0", "libpython3.12.dylib", "python3.dll", "python312.dll", "python312_d.dll"):
            with self.subTest(name=name):
                self.assertTrue(helper.is_cpython_binary(Path(name), "BINARY"))
        for name in ("libcrypto.so.3", "libsqlite3.so.0", "libpython-helper.so", "libpython3.12.so.backup", "python3-helper.dll"):
            with self.subTest(name=name):
                self.assertFalse(helper.is_cpython_binary(Path(name), "BINARY"))

    def test_invalid_filename_fixture_skips_only_encoding_capability_error(self):
        case = RustWithoutPythonTests("test_invalid_utf8_filenames_respect_max_files")
        function = RustWithoutPythonTests.test_invalid_utf8_filenames_respect_max_files
        # Exercise the fixture itself even on platforms where byte paths are
        # unavailable; the production test's POSIX guard remains unchanged.
        function = getattr(function, "__wrapped__", function)
        for code in (errno.EILSEQ, errno.EACCES):
            with tempfile.TemporaryDirectory() as temp, self.subTest(errno=code):
                case.base = Path(temp).resolve()
                error = OSError(code, "controlled fixture creation failure")
                with mock.patch("builtins.open", side_effect=error):
                    if code == errno.EILSEQ:
                        with self.assertRaisesRegex(unittest.SkipTest, "EILSEQ"):
                            function(case)
                    else:
                        with self.assertRaises(OSError) as raised:
                            function(case)
                        self.assertIs(raised.exception, error)

    @staticmethod
    def artifact_builder(helper, name):
        """Replace compilation only; main, cleanup, archives and publication stay real."""
        def build(work, out, *arguments):
            mode = arguments[0] if name == "legacy-tools" else "rust"
            directory = out / f"{name}-{helper.platform_tag()}"
            if directory.is_symlink():
                directory.unlink()
            elif directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True)
            program = directory / (name + EXE)
            program.write_bytes(f"built {name} {mode}\n".encode())
            if mode == "onedir":
                (directory / "_internal").mkdir()
                (directory / "_internal/runtime.bin").write_bytes(b"actual onedir fixture bytes")
            return {"directory": directory, "program": program, "info": {"artifact": directory.name, "program": program.name, "mode": mode}}
        return build

    def test_target_narrowing_removes_only_managed_outputs_before_real_publication(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            out = root / "artifacts"
            out.mkdir()
            unrelated = {
                "manual/keep.txt": b"manual output stays",
                "work/cache/keep.bin": b"build cache stays",
                "legacy-tools-other-platform.tar.gz": b"other platform stays",
                f"legacy-tools-{helper.platform_tag()}.zip.notes": b"unrelated suffix stays",
                "readme.txt": b"unrelated file stays",
            }
            for name, contents in unrelated.items():
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            outside = root / "outside.txt"
            outside.write_bytes(b"manifest must not authorize deleting this")
            (out / "build-manifest.json").write_text(json.dumps({"archives": ["../outside.txt", "manual/keep.txt", "work/cache/keep.bin"]}), encoding="utf-8")
            managed = {f"legacy-tools-{helper.platform_tag()}", f"legacy-repo-map-{helper.platform_tag()}"}
            with mock.patch.object(helper, "build_python_bundle", side_effect=self.artifact_builder(helper, "legacy-tools")), mock.patch.object(helper, "build_rust", side_effect=self.artifact_builder(helper, "legacy-repo-map")):
                for target, mode, archive_os in (("all", "onedir", "posix"), ("rust", "onedir", "nt"), ("python-bundle", "onefile", "posix"), ("python-bundle", "onedir", "nt")):
                    with self.subTest(target=target, mode=mode, archive_os=archive_os):
                        # Only select the actual archive format; pathlib and the
                        # rest of the real host OS retain their native semantics.
                        archive_host = type("ArchiveHost", (), {"name": archive_os})()
                        with mock.patch.object(helper, "os", archive_host), contextlib.redirect_stdout(io.StringIO()):
                            status = helper.main(["--output-dir", str(out), "--target", target, "--mode", mode, "--skip-smoke"])
                        self.assertEqual(status, 0)
                        manifest = json.loads((out / "build-manifest.json").read_text(encoding="utf-8"))
                        selected = managed if target == "all" else {f"{'legacy-tools' if target == 'python-bundle' else 'legacy-repo-map'}-{helper.platform_tag()}"}
                        suffix = ".zip" if archive_os == "nt" else ".tar.gz"
                        expected_archives = {name + suffix for name in selected}
                        actual_managed = {path.name for path in out.iterdir() if any(path.name == name + extension for name in managed for extension in (".zip", ".tar.gz"))}
                        self.assertEqual(actual_managed, expected_archives)
                        self.assertEqual(set(manifest["archives"]), expected_archives)
                        self.assertEqual({item["artifact"] for item in manifest["artifacts"]}, selected)
                        for name in managed - selected:
                            self.assertFalse((out / name).exists())
                            self.assertFalse((out / name).is_symlink())
                        for item in manifest["artifacts"]:
                            directory = out / item["artifact"]
                            if item["artifact"].startswith("legacy-tools-"):
                                self.assertEqual(item["mode"], mode)
                                self.assertEqual((directory / "_internal").exists(), mode == "onedir")
                            program_bytes = (directory / item["program"]).read_bytes()
                            archive = out / (item["artifact"] + suffix)
                            member = item["artifact"] + "/" + item["program"]
                            if suffix == ".zip":
                                with zipfile.ZipFile(archive) as bundle:
                                    self.assertEqual(bundle.read(member), program_bytes)
                            else:
                                with tarfile.open(archive) as bundle:
                                    self.assertEqual(bundle.extractfile(member).read(), program_bytes)
                        sums = dict(line.split("  ", 1)[::-1] for line in (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
                        expected_sums = expected_archives | {item["artifact"] + "/" + item["program"] for item in manifest["artifacts"]}
                        self.assertEqual(set(sums), expected_sums)
                        for name, digest in sums.items():
                            self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)
                        for name, contents in unrelated.items():
                            self.assertEqual((out / name).read_bytes(), contents)
                        self.assertEqual(outside.read_bytes(), b"manifest must not authorize deleting this")

    def test_managed_cleanup_unlinks_symlinks_without_modifying_outside_targets(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            out = root / "artifacts"
            out.mkdir()
            outside = root / "outside"
            outside.mkdir()
            target = outside / "keep.txt"
            target.write_bytes(b"outside source and archive target unchanged")
            tools = out / f"legacy-tools-{helper.platform_tag()}"
            rust = out / f"legacy-repo-map-{helper.platform_tag()}"
            try:
                tools.symlink_to(outside, target_is_directory=True)
                (out / (tools.name + ".zip")).symlink_to(target)
                (out / (rust.name + ".tar.gz")).symlink_to(target)
            except OSError as error:
                if error.errno in (errno.EPERM, errno.EACCES) or getattr(error, "winerror", None) == 1314:
                    self.skipTest("filesystem permission does not allow symlink fixture")
                raise
            with mock.patch.object(helper, "build_rust", side_effect=self.artifact_builder(helper, "legacy-repo-map")), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(helper.main(["--output-dir", str(out), "--target", "rust", "--skip-smoke"]), 0)
            self.assertFalse(tools.is_symlink())
            self.assertFalse(tools.exists())
            self.assertFalse((out / (rust.name + ".tar.gz")).is_symlink())
            self.assertEqual(target.read_bytes(), b"outside source and archive target unchanged")
            # A symlink nested in an omitted real artifact directory is also
            # removed as a link rather than traversed by recursive cleanup.
            tools.mkdir()
            (tools / "linked").symlink_to(outside, target_is_directory=True)
            with mock.patch.object(helper, "build_rust", side_effect=self.artifact_builder(helper, "legacy-repo-map")), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(helper.main(["--output-dir", str(out), "--target", "rust", "--skip-smoke"]), 0)
            self.assertFalse(tools.exists())
            self.assertEqual(target.read_bytes(), b"outside source and archive target unchanged")

    def test_cleanup_permission_error_fails_before_fresh_manifest_and_checksums(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp).resolve() / "artifacts"
            with mock.patch.object(helper, "build_python_bundle", side_effect=self.artifact_builder(helper, "legacy-tools")), mock.patch.object(helper, "build_rust", side_effect=self.artifact_builder(helper, "legacy-repo-map")), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(helper.main(["--output-dir", str(out), "--target", "all", "--skip-smoke"]), 0)
                manifest = (out / "build-manifest.json").read_bytes()
                sums = (out / "SHA256SUMS").read_bytes()
                refused = out / f"legacy-tools-{helper.platform_tag()}{'.zip' if os.name == 'nt' else '.tar.gz'}"
                original_unlink = Path.unlink
                def permission_denied(path, *arguments, **options):
                    if path == refused:
                        raise PermissionError(errno.EACCES, "controlled cleanup permission failure", str(path))
                    return original_unlink(path, *arguments, **options)
                error = io.StringIO()
                with mock.patch.object(Path, "unlink", permission_denied), contextlib.redirect_stderr(error):
                    status = helper.main(["--output-dir", str(out), "--target", "rust", "--skip-smoke"])
                self.assertEqual(status, 1)
                self.assertIn("build-legacy-tools:", error.getvalue())
                self.assertIn("controlled cleanup permission failure", error.getvalue())
                self.assertEqual((out / "build-manifest.json").read_bytes(), manifest)
                self.assertEqual((out / "SHA256SUMS").read_bytes(), sums)
                self.assertTrue(refused.exists())

    def test_windows_archive_clamps_old_timestamp_without_changing_source(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifact"
            root.mkdir()
            source = root / "LICENSE.txt"
            original = b"License contents remain exact.\n"
            source.write_bytes(original)
            os.utime(source, (1, 1))
            before = source.stat().st_mtime_ns
            windows_os = type("WindowsArchiveOS", (), {"name": "nt"})()
            with mock.patch.object(helper, "os", windows_os):
                archive = helper.archive(root)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(bundle.read("artifact/LICENSE.txt"), original)
                self.assertEqual(bundle.getinfo("artifact/LICENSE.txt").date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(source.stat().st_mtime_ns, before)

    def test_windows_spec_excludes_only_known_system_runtimes(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            spec = Path(temp) / "legacy-tools.spec"
            spec.write_text("a = Analysis([])\npyz = PYZ(a.pure)\nexe = EXE(pyz, a.binaries)\n", encoding="utf-8")
            helper.exclude_windows_redist(spec)
            rewritten = spec.read_text(encoding="utf-8")
            self.assertIn("a.binaries = [item for item in a.binaries", rewritten)
            self.assertIn("vcruntime140", rewritten)
            self.assertIn("msvcp140", rewritten)
            self.assertIn("pyz = PYZ(a.pure)", rewritten)
            excluded = [
                "vcruntime140.dll", "VCRUNTIME140_1.DLL", "msvcp140_atomic_wait.dll",
                "api-ms-win-crt-convert-l1-1-0.dll", "api-ms-win-crt-runtime-l1-1-0.dll",
                "ucrtbase.dll", "sub\\UCRTBASE.DLL", "sub/API-MS-WIN-CRT-HEAP-L1-1-0.DLL",
                "api-ms-win-core-file-l1-1-0.dll", "api-ms-win-core-namedpipe-l1-1-0.dll",
                "ext-ms-win-ntuser-window-l1-1-0.dll",
            ]
            retained = [
                "api-ms-win-crtx-custom.dll", "api-ms-winx-core-file-l1-1-0.dll",
                "ext-ms-winx-ntuser-window-l1-1-0.dll", "ucrtbase-helper.dll",
                "libcrypto-3-x64.dll", "unknown.dll", "vcruntime140.txt", "api-ms-win-crt-custom.so",
            ]
            binaries = [(name, "/original/" + name, "BINARY") for name in excluded + retained]
            analysis = type("FakeAnalysis", (), {"binaries": binaries, "pure": []})()
            namespace = {"Analysis": lambda _: analysis, "PYZ": lambda _: None, "EXE": lambda *_: None}
            exec(compile(rewritten, str(spec), "exec"), namespace)
            self.assertEqual(analysis.binaries, binaries[len(excluded):])
            spec.write_text("a = Analysis([])\n", encoding="utf-8")
            with self.assertRaisesRegex(helper.BuildError, "cannot locate"):
                helper.exclude_windows_redist(spec)

    def test_supplied_binary_license_requires_provenance_version_and_matching_hash(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "libcrypto-test.dll"
            binary.write_bytes(b"binary")
            license_file = root / binary.name
            license_file.write_text("Apache License 2.0\n", encoding="utf-8")
            entry = {"component": "OpenSSL", "version": "3.0.16", "source": "https://www.openssl.org/source/", "sha256": helper.sha256(license_file)}
            (root / "manifest.json").write_text(json.dumps({binary.name: entry}), encoding="utf-8")
            self.assertEqual(helper.system_binary_license(binary, root)[:2], ("OpenSSL", "3.0.16"))
            license_file.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(helper.BuildError, "hash mismatch"):
                helper.system_binary_license(binary, root)

    def test_host_preparation_uses_actual_binary_names_and_rejects_unknown(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "libcrypto-3-x64.dll"
            binary.write_bytes(b"binary")

            def fake_download(url, destination, *, marker):
                destination.write_bytes(b"official upstream " + marker)
                return destination

            with mock.patch.object(helper.sys, "platform", "win32"), mock.patch.object(helper.sys, "base_prefix", str(root)), mock.patch.object(helper, "collected_binaries", return_value=[(binary.name, binary, "BINARY")]), mock.patch.object(helper, "cpython_windows_build_versions", return_value={"bzip2": "1.0.8", "xz": "5.2.5", "libffi": "3.4.4"}) as build_versions, mock.patch.object(helper, "download_notice", side_effect=fake_download):
                output = helper.prepare_host_binary_licenses(root / "toc", root / "prepared", {binary.name})
                entry = json.loads((output / "manifest.json").read_text())[binary.name]
                self.assertEqual(entry["component"], "OpenSSL")
                self.assertEqual(entry["sha256"], helper.sha256(output / binary.name))
                self.assertTrue((output / "CPython-THIRD-PARTY.rst").is_file())
                build_versions.assert_called_once()
            unknown = root / "unknown.dll"
            unknown.write_bytes(b"binary")
            with mock.patch.object(helper.sys, "base_prefix", str(root)), mock.patch.object(helper, "collected_binaries", return_value=[(unknown.name, unknown, "BINARY")]):
                with self.assertRaisesRegex(helper.BuildError, "unknown collected host binary"):
                    helper.prepare_host_binary_licenses(root / "toc", root / "other", {unknown.name})

    def test_windows_preparation_uses_cpython_pins_for_static_compression_notices(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "_bz2.pyd"
            binary.write_bytes(b"extension")

            def fake_download(url, destination, *, marker):
                if url.endswith("python.props"):
                    destination.write_text("<bz2Dir>bzip2-1.0.8\\</bz2Dir><lzmaDir>xz-5.2.5\\</lzmaDir><libffiDir>libffi-3.4.4\\</libffiDir>", encoding="utf-8")
                else:
                    destination.write_bytes(b"official upstream " + marker)
                return destination

            with mock.patch.object(helper.sys, "platform", "win32"), mock.patch.object(helper, "collected_binaries", return_value=[(binary.name, binary, "EXTENSION")]), mock.patch.object(helper, "download_notice", side_effect=fake_download):
                out = helper.prepare_host_binary_licenses(root / "toc", root / "prepared", {"_bz2.pyd", "_lzma.pyd"})
            notices = json.loads((out / "additional-notices.json").read_text())
            self.assertEqual({item["component"]: item["version"] for item in notices}, {
                "CPython bundled third-party components": helper.platform.python_version(),
                "bzip2": "1.0.8",
                "XZ Utils liblzma": "5.2.5",
            })
            self.assertEqual(helper.sha256(out / "bzip2-LICENSE.txt"), next(item["sha256"] for item in notices if item["component"] == "bzip2"))

    def test_full_component_notices_preserve_pinned_attribution(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            ffi = root / "libffi-8.dll"
            expat = root / "DLLs" / "pyexpat.pyd"
            expat.parent.mkdir()
            ffi.write_bytes(b"libffi image")
            expat.write_bytes(b"CPython extension image")
            urls = []
            def download(url, destination, *, marker):
                urls.append(url)
                if url.endswith("PCbuild/python.props"):
                    text = "<bz2Dir>bzip2-1.0.8</bz2Dir><lzmaDir>xz-5.2.5</lzmaDir><libffiDir>libffi-3.4.4</libffiDir>"
                elif url == "https://raw.githubusercontent.com/libffi/libffi/v3.4.4/LICENSE":
                    text = LIBFFI_NOTICE
                elif url == "https://raw.githubusercontent.com/python/cpython/v3.12.10/Modules/expat/COPYING":
                    text = EXPAT_NOTICE
                elif url.endswith("Doc/license.rst"):
                    text = "Summary for third-party software; includes historical libffi attribution."
                else:
                    raise AssertionError(f"Unverified notice URL: {url}")
                self.assertIn(marker.lower(), text.encode().lower())
                destination.write_text(text, encoding="utf-8", newline="\n")
                return destination
            binaries = [(ffi.name, ffi, "BINARY"), ("DLLs/pyexpat.pyd", expat, "EXTENSION")]
            with mock.patch.object(helper.sys, "platform", "win32"), mock.patch.object(helper.sys, "base_prefix", str(root)), mock.patch.object(helper.platform, "python_version", return_value="3.12.10"), mock.patch.object(helper, "collected_binaries", return_value=binaries), mock.patch.object(helper, "download_notice", side_effect=download):
                out = helper.prepare_host_binary_licenses(root / "toc", root / "prepared", {name for name, *_ in binaries})
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            notice = (out / ffi.name).read_text(encoding="utf-8")
            self.assertEqual(notice, LIBFFI_NOTICE)
            self.assertIn("1996-2022  Anthony Green", notice)
            self.assertEqual(manifest[ffi.name]["version"], "3.4.4")
            additional = json.loads((out / "additional-notices.json").read_text(encoding="utf-8"))
            record = next(item for item in additional if item["component"] == "Expat (CPython bundled)")
            notice = (out / record["filename"]).read_text(encoding="utf-8")
            self.assertEqual(notice, EXPAT_NOTICE)
            self.assertIn("2001-2022 Expat maintainers", notice)
            for text in (LIBFFI_NOTICE, EXPAT_NOTICE):
                self.assertIn("Permission is hereby granted", text)
                self.assertIn("IN NO EVENT", text)
            self.assertEqual(record["sha256"], helper.sha256(out / record["filename"]))
            self.assertIsNone(helper.host_license_spec("libffi-unknown.dylib"))

    def test_zlib_header_preserves_exact_complete_notice_and_rejects_invalid_sources(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def download(url, destination, *, marker):
                self.assertEqual(url, "https://raw.githubusercontent.com/madler/zlib/v1.3.1/zlib.h")
                self.assertEqual(marker, b"zlib.h")
                destination.write_bytes(ZLIB_HEADER)
                return destination
            with mock.patch.object(helper, "download_notice", side_effect=download), mock.patch.object(helper.zlib, "ZLIB_RUNTIME_VERSION", "1.3.1"):
                spec = helper.host_license_spec("zlib1.dll")
                self.assertEqual(spec[:3], ("zlib", "1.3.1", "https://raw.githubusercontent.com/madler/zlib/v1.3.1/zlib.h"))
                notice = helper.download_zlib_notice(spec[2], root / "notice.txt", "1.3.1")
                self.assertEqual(notice.read_bytes(), ZLIB_NOTICE.encode())
                self.assertEqual(helper.sha256(notice), hashlib.sha256(ZLIB_NOTICE.encode()).hexdigest())
                self.assertIn("1995-2024 Jean-loup Gailly and Mark Adler", ZLIB_NOTICE)
                self.assertIn("Permission is granted to anyone", ZLIB_NOTICE)
                self.assertIn("In no event", ZLIB_NOTICE)
                self.assertNotIn("#define", notice.read_text(encoding="utf-8"))
            for malformed in (
                ZLIB_HEADER.replace(b"version 1.3.1,", b"version 1.3.0,"),
                ZLIB_HEADER.replace(b'#define ZLIB_VERSION "1.3.1"', b'#define ZLIB_VERSION "1.3.0"'),
                ZLIB_HEADER.replace(b"Permission is granted to anyone", b"unverified permission"),
                ZLIB_HEADER.replace(b"*/", b"", 1),
                b"/* zlib.h version 1.3.1, Copyright (C) 1995-2024 */\n#define ZLIB_VERSION \"1.3.1\"\n",
            ):
                def invalid_download(url, destination, *, marker):
                    destination.write_bytes(malformed)
                    return destination
                with self.subTest(header=malformed[:70]), mock.patch.object(helper, "download_notice", side_effect=invalid_download):
                    with self.assertRaises(helper.BuildError):
                        helper.download_zlib_notice(spec[2], root / "invalid.txt", "1.3.1")
            for version in ("unknown", "1.3.1-custom", "../1.3.1"):
                with self.subTest(version=version), mock.patch.object(helper.zlib, "ZLIB_RUNTIME_VERSION", version), mock.patch.object(helper, "download_notice") as download:
                    with self.assertRaisesRegex(helper.BuildError, "unsupported zlib"):
                        helper.host_license_spec("zlib1.dll")
                    with self.assertRaisesRegex(helper.BuildError, "unsupported zlib"):
                        helper.download_zlib_notice("unused", root / "invalid-version", version)
                    download.assert_not_called()

    def test_shared_and_static_zlib_receive_matching_full_attribution(self):
        helper = self.helper()
        for case in ("shared", "extension", "builtin", "shared-and-extension"):
            with tempfile.TemporaryDirectory() as temp, self.subTest(case=case):
                root = Path(temp).resolve()
                shared = root / "zlib1.dll"
                extension = root / "zlib.pyd"
                interpreter = root / "python312.dll"
                for file in (shared, extension, interpreter):
                    file.write_bytes(b"controlled binary fixture")
                cases = {
                    "shared": [(shared.name, shared, "BINARY")],
                    "extension": [(extension.name, extension, "EXTENSION")],
                    "builtin": [(interpreter.name, interpreter, "BINARY")],
                    "shared-and-extension": [(shared.name, shared, "BINARY"), (extension.name, extension, "EXTENSION")],
                }
                binaries = cases[case]
                urls = []
                def download(url, destination, *, marker):
                    urls.append(url)
                    if url == "https://raw.githubusercontent.com/madler/zlib/v1.3.1/zlib.h":
                        data = ZLIB_HEADER
                    elif url.endswith("Doc/license.rst"):
                        data = b"Third-party software: historical zlib summary 1995-2011."
                    else:
                        raise AssertionError(f"Unexpected source: {url}")
                    self.assertIn(marker.lower(), data.lower())
                    destination.write_bytes(data)
                    return destination
                with mock.patch.object(helper.sys, "platform", "win32"), mock.patch.object(helper.sys, "base_prefix", str(root)), mock.patch.object(helper.sys, "builtin_module_names", ("zlib",) if case == "builtin" else ()), mock.patch.object(helper.zlib, "ZLIB_RUNTIME_VERSION", "1.3.1"), mock.patch.object(helper, "collected_binaries", return_value=binaries), mock.patch.object(helper, "cpython_windows_build_versions", return_value={"bzip2": "1.0.8", "xz": "5.2.5", "libffi": "3.4.4"}), mock.patch.object(helper, "download_notice", side_effect=download):
                    out = helper.prepare_host_binary_licenses(root / "toc", root / "prepared", {name for name, *_ in binaries})
                manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                additional = json.loads((out / "additional-notices.json").read_text(encoding="utf-8"))
                records = list(manifest.values()) + [item for item in additional if item["component"] == "zlib"]
                self.assertEqual(len(records), 2 if case == "shared-and-extension" else 1)
                if "shared" in case:
                    self.assertEqual((out / shared.name).read_bytes(), ZLIB_NOTICE.encode())
                if case != "shared":
                    self.assertEqual((out / "zlib-LICENSE.txt").read_bytes(), ZLIB_NOTICE.encode())
                for record in records:
                    self.assertEqual(record["component"], "zlib")
                    self.assertEqual(record["version"], "1.3.1")
                    self.assertEqual(record["source"], "https://raw.githubusercontent.com/madler/zlib/v1.3.1/zlib.h")
                    self.assertEqual(record["sha256"], hashlib.sha256(ZLIB_NOTICE.encode()).hexdigest())
                self.assertEqual(urls.count("https://raw.githubusercontent.com/madler/zlib/v1.3.1/zlib.h"), 1)

    def test_final_onedir_hash_uses_processed_image_and_rejects_missing_image(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            original = root / "original.dll"
            original.write_bytes(b"original binary before relocation")
            image = root / "dist/_internal/sub/image.dll"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"relocated and signed final image")
            toc = root / "Analysis-00.toc"
            analysis = [None] * 16
            analysis[15] = [("sub/image.dll", str(original), "BINARY")]
            toc.write_text(repr(analysis), encoding="utf-8")
            (root / "COLLECT-00.toc").write_text(repr(([("sub/image.dll", str(original), "BINARY")],)), encoding="utf-8")
            hashes = helper.packaged_binary_hashes(toc, "onedir", root / "dist", [])
            self.assertEqual(hashes["sub/image.dll"], helper.sha256(image))
            self.assertNotEqual(hashes["sub/image.dll"], helper.sha256(original))
            psf = root / "LICENSE.txt"
            psf.write_text("CPython fixture license", encoding="utf-8")
            with mock.patch.object(helper, "python_license", return_value=psf), mock.patch.object(helper, "is_cpython_binary", return_value=True), mock.patch.object(helper, "selected_distributions", return_value={}):
                records = helper.license_collected_binaries(root / "stage", toc, [], None)
            self.assertEqual(records[0]["source_sha256"], helper.sha256(original))
            self.assertNotIn("sha256", records[0])
            image.unlink()
            with self.assertRaisesRegex(helper.BuildError, "missing or escaping"):
                helper.packaged_binary_hashes(toc, "onedir", root / "dist", [])

    def test_final_onefile_hash_reads_actual_compressed_carchive(self):
        helper = self.helper()
        tools = os.environ.get("LEGACY_BUILD_TOOLS")
        search = [Path(tools)] if tools else []
        if not helper.importable("PyInstaller.archive.readers", search):
            self.skipTest("pinned PyInstaller archive reader unavailable; set LEGACY_BUILD_TOOLS")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            built = root / "dist"
            built.mkdir()
            name = "sub/image.dll"
            original = root / "original.dll"
            original.write_bytes(b"preprocessed source")
            final = b"relocated signed bytes in actual archive"
            compressed = zlib.compress(final)
            encoded = name.encode() + b"\0"
            entry_length = struct.calcsize("!IIIIBc") + len(encoded)
            entry_length += (-entry_length) % 16
            entry = struct.pack("!IIIIBc", entry_length, 0, len(compressed), len(final), 1, b"b") + encoded
            entry += b"\0" * (entry_length - len(entry))
            cookie_format = "!8sIIII64s"
            cookie_length = struct.calcsize(cookie_format)
            cookie = struct.pack(cookie_format, b"MEI\014\013\012\013\016", len(compressed) + len(entry) + cookie_length, len(compressed), len(entry), 312, b"python312.dll")
            (built / f"legacy-tools{EXE}").write_bytes(b"fake executable prefix" + compressed + entry + cookie)
            toc = root / "Analysis-00.toc"
            (root / "PKG-00.toc").write_text(repr((None, None, [(name, str(original), "BINARY")])), encoding="utf-8")
            hashes = helper.packaged_binary_hashes(toc, "onefile", built, search)
            self.assertEqual(hashes[name], hashlib.sha256(final).hexdigest())
            self.assertNotEqual(hashes[name], helper.sha256(original))
            (root / "PKG-00.toc").write_text(repr((None, None, [])), encoding="utf-8")
            with self.assertRaisesRegex(helper.BuildError, "differ from licensed archive inventory"):
                helper.packaged_binary_hashes(toc, "onefile", built, search)

    def test_rejects_wrong_selected_tool_version(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp) / "tools"
            (tools / "PyInstaller").mkdir(parents=True)
            (tools / "PyInstaller" / "__init__.py").write_text("", encoding="utf-8")
            for name, version in (("pyinstaller", "0.0.1"), ("pyinstaller-hooks-contrib", "2026.8")):
                metadata = tools / f"{name}-{version}.dist-info"
                metadata.mkdir()
                (metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(BUILD_HELPER), "--target", "python-bundle", "--output-dir", str(Path(temp) / "out"), "--tools-dir", str(tools)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("pyinstaller: expected 6.22.3, found 0.0.1", result.stderr)

    def test_rejects_matching_metadata_without_selected_package(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp) / "tools"
            tools.mkdir()
            for name, version in (("pyinstaller", "6.22.3"), ("pyinstaller-hooks-contrib", "2026.8")):
                metadata = tools / f"{name}-{version}.dist-info"
                metadata.mkdir()
                (metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(BUILD_HELPER), "--target", "python-bundle", "--output-dir", str(Path(temp) / "out"), "--tools-dir", str(tools)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PyInstaller is not importable from the selected target directory", result.stderr)

    def test_refuses_to_write_inside_the_repository(self):
        inside = REPO / "tests" / "native-build-output"
        for option in ("--output-dir", "--deps-dir"):
            arguments = [sys.executable, str(BUILD_HELPER), "--target", "rust", "--skip-smoke"]
            arguments += [option, str(inside)] + ([] if option == "--output-dir" else ["--output-dir", str(Path(tempfile.gettempdir()) / "unused-legacy-build")])
            result = subprocess.run(arguments, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("must be outside the repository", result.stderr)
        self.assertFalse(inside.exists())

    def test_missing_packages_are_reported_without_installing(self):
        with tempfile.TemporaryDirectory() as temp:
            empty = Path(temp) / "empty-tools"
            empty.mkdir()
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
            if importlib.util.find_spec("PyInstaller"):
                self.skipTest("PyInstaller is installed in this interpreter")
            result = subprocess.run([sys.executable, str(BUILD_HELPER), "--target", "python-bundle", "--output-dir", str(Path(temp) / "out"), "--tools-dir", str(empty)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PyInstaller is not importable", result.stderr)
            self.assertEqual(list(empty.iterdir()), [])


def digest(data):
    return hashlib.sha256(data).hexdigest()


# NetworkX 3.4.2: the commit that tag networkx-3.4.2 peels to and its LICENSE.txt.
NETWORKX_COMMIT = "2acf1590f82757c01a57b81b8c5dfb79e60aa416"
NETWORKX_LICENSE_SHA256 = "5b433b90f755eb9bbd06feff1d1a4f5f232c5208a185694199e45fa95d762792"


class LicenseNoticeTests(unittest.TestCase):
    """Notices for third-party code inside a crate package or a wheel."""

    def setUp(self):
        self.helper = BuildHelperTests.helper()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.crate = {"name": "demo", "version": "1.0.0", "checksum": "c" * 64}

    def package(self, files):
        directory = self.base / "registry" / "demo-1.0.0"
        for relative, text in files.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return directory

    @staticmethod
    def pin(path, text, **use):
        data = text.encode("utf-8")
        cargo = {"name": "demo", "version": "1.0.0", "checksum": "c" * 64, "path": path, **use}
        return {"file": f"demo-{path or 'own'}", "title": f"notice for {path or 'demo'}", "sha256": digest(data), "origin": f"https://example.invalid/{path or 'LICENSE'}", "data": data, "cargo": cargo}

    @staticmethod
    def printed(*pins):
        return "header\n" + "".join(f"\n==== {pin['title']} ====\n\n{pin['data'].decode('utf-8').rstrip()}\n" for pin in pins)

    def license(self, files, pins, notices=None, crate=None):
        crate = dict(crate or self.crate)
        self.helper.license_crate(crate, self.package(files), self.base / "artifact", self.printed(*pins) if notices is None else notices, pins)
        return crate

    def test_crate_license_collection_is_recursive_and_keeps_relative_paths(self):
        texts = {"LICENSE": "demo license\n", "src/unicode/LICENSE": "Unicode notice ©\n", "src/tables/LICENSE": "tables notice\n", "vendor/zlib/COPYING.txt": "zlib notice\n"}
        directory = self.package({**texts, "src/license.rs": "// code\n", "src/lib.rs": "", "README.md": "demo\n"})
        self.assertEqual([path.as_posix() for path in self.helper.license_files(directory)], sorted(texts))
        self.assertEqual(self.helper.license_files(self.base / "absent"), [])
        pins = [self.pin(path, text) for path, text in texts.items() if "/" in path]
        crate = self.license(texts, pins)
        root = self.base / "artifact" / "licenses" / "rust" / "demo-1.0.0"
        # Three files named LICENSE stay three files.
        self.assertEqual({path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in root.rglob("*") if path.is_file()}, texts)
        self.assertEqual(crate["license_files"], [{"path": f"licenses/rust/demo-1.0.0/{path}", "source": path, "sha256": digest(texts[path].encode("utf-8"))} for path in sorted(texts)])
        self.assertEqual(crate["license_text"], "licenses/rust/demo-1.0.0/")
        self.assertEqual({item["source"]: (item["sha256"], item["origin"]) for item in crate["embedded_notices"]}, {pin["cargo"]["path"]: (pin["sha256"], pin["origin"]) for pin in pins})

    def test_nested_notice_must_be_verified_and_printed_in_full(self):
        texts = {"LICENSE": "demo license\n", "src/unicode/LICENSE": "first paragraph\n\nsecond paragraph\n"}
        pin = self.pin("src/unicode/LICENSE", texts["src/unicode/LICENSE"])
        cases = [
            ("nested notices that --notices does not print: src/unicode/LICENSE", [], None, None),
            ("is not the src/unicode/LICENSE of crate", [self.pin("src/unicode/LICENSE", "another text\n")], None, None),
            ("verified against demo 0.9.0", [self.pin("src/unicode/LICENSE", texts["src/unicode/LICENSE"], version="0.9.0")], None, None),
            ("verified against demo 1.0.0", [pin], None, {**self.crate, "checksum": "d" * 64}),
            ("lacks the full text", [pin], "header\n\n==== notice for src/unicode/LICENSE ====\n\nfirst paragraph\n", None),
        ]
        for message, pins, notices, crate in cases:
            with self.subTest(message=message), self.assertRaisesRegex(self.helper.BuildError, message):
                self.license(texts, pins, notices, crate)
        with mock.patch.object(self.helper, "license_files", return_value=[Path("LICENSE"), Path("license")]):
            with self.assertRaisesRegex(self.helper.BuildError, "differ only in case"):
                self.license(texts, [pin])

    def test_crate_needs_its_own_license_beside_a_nested_notice(self):
        nested = {"src/unicode/LICENSE": "Unicode notice\n"}
        pin = self.pin("src/unicode/LICENSE", nested["src/unicode/LICENSE"])
        with self.assertRaisesRegex(self.helper.BuildError, "no license text found for crate demo-1.0.0"):
            self.license(nested, [pin])
        own = self.pin(None, "demo license kept beside the program\n")
        crate = self.license(nested, [own, pin])
        self.assertEqual(crate["license_text"], "NOTICES.txt")
        self.assertEqual([item["source"] for item in crate["embedded_notices"]], [None, "src/unicode/LICENSE"])
        self.assertEqual(self.license(nested, [pin], self.printed(pin) + "\n==== demo (MIT) ====\n\ntext\n")["license_text"], "NOTICES.txt")

    def test_pinned_notices_match_the_lockfile_and_the_python_requirement(self):
        pinned = self.helper.pinned_notices()
        checksums = self.helper.locked_checksums()
        requirements = self.helper.pinned_versions(self.helper.MAP_REQUIREMENTS.read_text(encoding="utf-8").splitlines())
        self.assertEqual({record["file"] for record in pinned}, {path.name for path in (CRATE / "licenses").iterdir()} - {"manifest.json"})
        for record in pinned:
            with self.subTest(notice=record["file"]):
                self.assertEqual(digest(record["data"]), record["sha256"])
                self.assertRegex(record["origin"], r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/")
                if "adaptation" in record:
                    # Rewritten source is not a Cargo dependency: nothing in the lockfile stands for it.
                    adapted = record["adaptation"]
                    self.assertNotIn("cargo", record)
                    self.assertNotIn("pypi", record)
                    self.assertNotIn(adapted["name"], {name for name, _ in checksums})
                    self.assertIn(f"/{adapted['commit']}/", record["origin"])
                    self.assertIn(adapted["commit"], (CRATE / adapted["source"]).read_text(encoding="utf-8"))
                    self.assertRegex(adapted["upstream_sha256"], r"^[0-9a-f]{64}$")
                    continue
                use = record["cargo"]
                self.assertEqual(checksums[(use["name"], use["version"])], use["checksum"])
                if "pypi" in record:
                    self.assertEqual(requirements[record["pypi"]["name"]], record["pypi"]["version"])
                    self.assertRegex(record["pypi"]["sdist_sha256"], r"^[0-9a-f]{64}$")
                    self.assertTrue(record["pypi"]["sdist"].endswith(f"/{record['pypi']['name']}-{record['pypi']['version']}.tar.gz"))
        self.assertGreater(len(checksums), 30)
        adapted = [record for record in pinned if "adaptation" in record]
        self.assertEqual([(record["file"], record["sha256"], record["origin"]) for record in adapted], [("networkx-LICENSE.txt", NETWORKX_LICENSE_SHA256, f"https://raw.githubusercontent.com/networkx/networkx/{NETWORKX_COMMIT}/LICENSE.txt")])
        use = adapted[0]["adaptation"]
        self.assertEqual((use["name"], use["version"], use["commit"], use["upstream_path"], use["source"]), ("networkx", requirements["networkx"], NETWORKX_COMMIT, "networkx/algorithms/link_analysis/pagerank_alg.py", "src/rank.rs"))
        self.assertIn(b"Copyright (C) 2004-2024, NetworkX Developers", adapted[0]["data"])

    def test_adapted_source_license_matches_the_installed_distribution(self):
        if not MAP_DEPS:
            self.skipTest("LEGACY_MAP_DEPS is not set")
        record = next(item for item in self.helper.pinned_notices() if "adaptation" in item)
        use = record["adaptation"]
        installed = self.helper.selected_distributions(Path(MAP_DEPS))[use["name"]]
        self.assertEqual(installed.version, use["version"])
        # The Python bundle ships this file; the Rust artifact ships the same bytes.
        self.assertEqual([digest(path.read_bytes().replace(b"\r\n", b"\n")) for path in self.helper.distribution_license_files(installed)], [record["sha256"]])
        self.assertEqual(digest((Path(MAP_DEPS) / use["upstream_path"]).read_bytes().replace(b"\r\n", b"\n")), use["upstream_sha256"])

    def test_adapted_source_notice_is_printed_and_staged_or_the_build_stops(self):
        pinned = self.helper.pinned_notices()
        record = next(item for item in pinned if "adaptation" in item)
        text = record["data"].decode("utf-8")
        printed = f"header\n\n==== {record['title']} ====\n\n{text.rstrip()}\n"
        artifact = self.base / "artifact"
        staged = self.helper.stage_adapted_notices(artifact, printed, pinned, {"tree-sitter", "regex-syntax"})
        self.assertEqual(staged, [{
            "component": record["component"], "name": "networkx", "version": "3.4.2", "title": "NetworkX (BSD 3-Clause)",
            "license": "licenses/adapted/networkx-3.4.2/LICENSE.txt", "sha256": NETWORKX_LICENSE_SHA256, "origin": record["origin"],
            "commit": NETWORKX_COMMIT, "upstream_path": "networkx/algorithms/link_analysis/pagerank_alg.py",
            "upstream_sha256": record["adaptation"]["upstream_sha256"], "adapted_in": "src/rank.rs",
        }])
        self.assertEqual(digest((artifact / staged[0]["license"]).read_bytes()), NETWORKX_LICENSE_SHA256)
        cases = [
            ("lacks the full text of networkx-LICENSE.txt", printed.replace("2004-2024", "2004-2023"), {"tree-sitter"}),
            ("lacks the full text of networkx-LICENSE.txt", "header\n", {"tree-sitter"}),
            ("a crate of that name is linked", printed, {"tree-sitter", "networkx"}),
            ("two license texts of networkx 3.4.2 claim LICENSE.txt", printed, {"tree-sitter"}),
        ]
        for message, notices, linked in cases:
            with self.subTest(message=message), self.assertRaisesRegex(self.helper.BuildError, message):
                self.helper.stage_adapted_notices(artifact if "claim" in message else self.base / "refused", notices, pinned, linked)
        self.assertFalse((self.base / "refused").exists())

    def test_notice_records_must_name_a_verified_use(self):
        copy = self.base / "licenses"
        shutil.copytree(CRATE / "licenses", copy, copy_function=shutil.copyfile)
        original = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
        index = next(position for position, record in enumerate(original["notices"]) if "adaptation" in record)

        def refused(message, change):
            manifest = json.loads(json.dumps(original))
            change(manifest["notices"][index])
            (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(message=message), mock.patch.object(self.helper, "NOTICE_DATA", copy), self.assertRaisesRegex(self.helper.BuildError, message):
                self.helper.pinned_notices()

        cargo = {"name": "networkx", "version": "3.4.2", "checksum": "c" * 64, "path": None}
        refused("names neither a linked crate nor an adapted source", lambda record: record.pop("adaptation"))
        refused("cannot also name a crate", lambda record: record.update(cargo=cargo))
        refused("lacks adaptation fields: commit, upstream_sha256", lambda record: [record["adaptation"].pop(key) for key in ("commit", "upstream_sha256")])
        refused("does not originate from the pinned commit of networkx 3.4.2", lambda record: record["adaptation"].update(commit="0" * 40))
        refused("does not originate from the pinned commit", lambda record: record.update(origin="https://raw.githubusercontent.com/networkx/networkx/main/LICENSE.txt"))
        refused("src/tags.rs does not name commit", lambda record: record["adaptation"].update(source="src/tags.rs"))
        refused("src/absent.rs does not name commit", lambda record: record["adaptation"].update(source="src/absent.rs"))
        refused("networkx-LICENSE.txt differs from the hash pinned", lambda record: record.update(sha256="0" * 64))
        (copy / "manifest.json").write_text(json.dumps(original), encoding="utf-8")
        with mock.patch.object(self.helper, "NOTICE_DATA", copy):
            self.assertEqual(len(self.helper.pinned_notices()), 4)
            (copy / "networkx-LICENSE.txt").write_bytes((copy / "networkx-LICENSE.txt").read_bytes().replace(b"2004-2024", b"2004-2025"))
            with self.assertRaisesRegex(self.helper.BuildError, "networkx-LICENSE.txt differs from the hash pinned"):
                self.helper.pinned_notices()

    def test_pinned_notice_survives_a_crlf_checkout_but_not_an_edit(self):
        copy = self.base / "licenses"
        shutil.copytree(CRATE / "licenses", copy, copy_function=shutil.copyfile)
        target = copy / "tree-sitter-unicode-LICENSE.txt"
        upstream = target.read_bytes().replace(b"\r\n", b"\n")
        target.write_bytes(upstream.replace(b"\n", b"\r\n"))
        with mock.patch.object(self.helper, "NOTICE_DATA", copy):
            record = next(item for item in self.helper.pinned_notices() if item["file"] == target.name)
            self.assertEqual(record["data"], upstream)
            target.write_bytes(upstream.replace(b"1991-2019", b"1991-2020"))
            with self.assertRaisesRegex(self.helper.BuildError, "tree-sitter-unicode-LICENSE.txt differs from the hash pinned"):
                self.helper.pinned_notices()

    def test_linked_crates_carry_exactly_the_pinned_nested_notices(self):
        if RUST_BINARY is None or not shutil.which("cargo"):
            self.skipTest(RUST_SKIP or "cargo is not installed")
        notices = subprocess.run([str(RUST_BINARY), "--notices"], check=True, capture_output=True, text=True, encoding="utf-8").stdout
        pinned = self.helper.pinned_notices()
        crates = self.helper.rust_dependencies(dict(os.environ))
        artifact = self.base / "artifact"
        # The actual crate sources and the actual program output, as in a build.
        for crate in crates:
            self.helper.license_crate(crate, Path(crate.pop("directory")), artifact, notices, pinned)
            self.assertRegex(crate["checksum"], r"^[0-9a-f]{64}$")
            self.assertTrue(crate["source"].startswith("registry+"))
        nested = {(crate["name"], crate["version"], item["source"], item["sha256"]) for crate in crates for item in crate["license_files"] if "/" in item["source"]}
        self.assertEqual(nested, {(record["cargo"]["name"], record["cargo"]["version"], record["cargo"]["path"], record["sha256"]) for record in pinned if "cargo" in record and record["cargo"]["path"]})
        self.assertEqual({name for name, *_ in nested}, {"tree-sitter", "regex-syntax"})
        # NetworkX is adapted source: no crate stands for it, and the real output carries its license.
        linked = {crate["name"] for crate in crates}
        self.assertNotIn("networkx", linked)
        staged = self.helper.stage_adapted_notices(artifact, notices, pinned, linked)
        self.assertEqual([(item["license"], item["sha256"]) for item in staged], [("licenses/adapted/networkx-3.4.2/LICENSE.txt", NETWORKX_LICENSE_SHA256)])
        self.assertEqual(digest((artifact / staged[0]["license"]).read_bytes()), NETWORKX_LICENSE_SHA256)
        for name, version, source, _ in nested:
            copied = artifact / "licenses" / "rust" / f"{name}-{version}" / source
            self.assertIn("Unicode, Inc.", copied.read_text(encoding="utf-8"))
        by_name = {crate["name"]: crate for crate in crates}
        self.assertEqual(by_name["tree-sitter"]["license_text"], "NOTICES.txt")
        self.assertEqual([item["source"] for item in by_name["tree-sitter"]["embedded_notices"]], [None, "src/unicode/LICENSE"])
        self.assertIn("LICENSE-MIT", [item["source"] for item in by_name["regex-syntax"]["license_files"]])

    def test_program_prints_each_pinned_notice_in_full(self):
        if RUST_BINARY is None:
            self.skipTest(RUST_SKIP)
        notices = subprocess.run([str(RUST_BINARY), "--notices"], check=True, capture_output=True, text=True, encoding="utf-8").stdout
        for record in self.helper.pinned_notices():
            with self.subTest(notice=record["file"]):
                self.assertIn(f"\n==== {record['title']} ====\n\n{record['data'].decode('utf-8').rstrip()}\n", notices)
        self.assertIn("Copyright © 1991-2019 Unicode, Inc. All rights reserved.", notices)
        self.assertIn("UNICODE, INC. LICENSE AGREEMENT - DATA FILES AND SOFTWARE", notices)
        self.assertIn("\n==== NetworkX (BSD 3-Clause) ====\n\nNetworkX is distributed with the 3-clause BSD license.\n", notices)
        self.assertIn("Copyright (C) 2004-2024, NetworkX Developers", notices)
        self.assertIn(NETWORKX_COMMIT, notices)

    def test_rust_artifact_ships_every_recorded_license_text(self):
        artifact = Path(RUST_BINARY).parent if RUST_BINARY else None
        if artifact is None or not (artifact / "BUILD-INFO.json").is_file():
            self.skipTest("LEGACY_REPO_MAP_BIN is not inside an artifact of the build helper")
        info = json.loads((artifact / "BUILD-INFO.json").read_text(encoding="utf-8"))
        notices = (artifact / "NOTICES.txt").read_text(encoding="utf-8")
        table = (artifact / "THIRD_PARTY_RUST.md").read_text(encoding="utf-8")
        recorded, nested = set(), set()
        for crate in info["crates"]:
            with self.subTest(crate=crate["name"]):
                self.assertRegex(crate["checksum"], r"^[0-9a-f]{64}$")
                self.assertTrue(crate["license_text"] == "NOTICES.txt" or any("/" not in item["source"] for item in crate["license_files"]))
                for item in crate["license_files"]:
                    self.assertEqual(item["path"], f"licenses/rust/{crate['name']}-{crate['version']}/{item['source']}")
                    self.assertEqual(digest((artifact / item["path"]).read_bytes()), item["sha256"])
                    recorded.add(item["path"])
                for item in crate["embedded_notices"]:
                    self.assertIn(f"\n==== {item['title']} ====\n", notices)
                    if item["source"]:
                        nested.add((crate["name"], crate["version"], item["source"], item["sha256"]))
                        self.assertIn(f"`licenses/rust/{crate['name']}-{crate['version']}/{item['source']}` | `{item['sha256']}` | {item['origin']} |", table)
        self.assertEqual({path.relative_to(artifact).as_posix() for path in (artifact / "licenses" / "rust").rglob("*") if path.is_file()}, recorded)
        pinned = self.helper.pinned_notices()
        self.assertEqual(nested, {(record["cargo"]["name"], record["cargo"]["version"], record["cargo"]["path"], record["sha256"]) for record in pinned if "cargo" in record and record["cargo"]["path"]})
        # Adapted source: the license file, its hash and provenance, and the full text in NOTICES.txt.
        adapted = {record["adaptation"]["name"]: record for record in pinned if "adaptation" in record}
        self.assertEqual({item["name"] for item in info["adapted_sources"]}, set(adapted))
        self.assertFalse(set(adapted) & {crate["name"] for crate in info["crates"]})
        for item in info["adapted_sources"]:
            record = adapted[item["name"]]
            with self.subTest(adapted=item["name"]):
                self.assertEqual((item["sha256"], item["origin"], item["commit"], item["version"]), (record["sha256"], record["origin"], record["adaptation"]["commit"], record["adaptation"]["version"]))
                self.assertEqual(digest((artifact / item["license"]).read_bytes()), record["sha256"])
                self.assertIn(f"\n==== {record['title']} ====\n\n{record['data'].decode('utf-8').rstrip()}\n", notices)
                self.assertIn(f"| `{item['adapted_in']}` | `{item['license']}` | `{item['sha256']}` | {item['origin']} |", table)
        self.assertEqual({path.relative_to(artifact).as_posix() for path in (artifact / "licenses" / "adapted").rglob("*") if path.is_file()}, {item["license"] for item in info["adapted_sources"]})
        self.assertNotIn(str(REPO), json.dumps(info))

    def test_wheel_source_notices_follow_the_selected_distribution(self):
        expected = {record["pypi"]["bundle_path"]: record for record in self.helper.pinned_notices() if "pypi" in record}
        self.assertEqual(set(expected), {"tree_sitter/core/LICENSE", "tree_sitter/core/lib/src/unicode/LICENSE"})
        version = next(iter(expected.values()))["pypi"]["version"]
        selected = type("Distribution", (), {"version": version})()
        skill = self.base / "skill"
        staged = self.helper.stage_source_notices(skill, {"tree-sitter": selected})
        root = skill / "licenses" / "python" / f"tree-sitter-{version}"
        self.assertEqual({path.relative_to(root).as_posix(): digest(path.read_bytes()) for path in root.rglob("*") if path.is_file()}, {path: record["sha256"] for path, record in expected.items()})
        for item in staged:
            record = expected[Path(item["license"]).relative_to(f"licenses/python/tree-sitter-{version}").as_posix()]
            self.assertEqual((item["sha256"], item["source"], item["version"]), (record["sha256"], record["origin"], version))
            self.assertEqual(item["verified_against"]["sdist_sha256"], record["pypi"]["sdist_sha256"])
        self.assertIn("Copyright © 1991-2019 Unicode, Inc.", (root / "tree_sitter/core/lib/src/unicode/LICENSE").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(self.helper.BuildError, "claim tree_sitter/core/"):
            self.helper.stage_source_notices(skill, {"tree-sitter": selected})
        other = type("Distribution", (), {"version": "0.26.0"})()
        for distributions, found in (({"tree-sitter": other}, "not 0.26.0"), ({}, "not an absent distribution")):
            with self.subTest(found=found), self.assertRaisesRegex(self.helper.BuildError, f"verified against the source of tree-sitter {version}, {found}"):
                self.helper.stage_source_notices(self.base / "other", distributions)
        self.assertFalse((self.base / "other").exists())

    def test_staged_bundle_licenses_include_the_notices_the_wheel_omits(self):
        tools = os.environ.get("LEGACY_BUILD_TOOLS")
        if not (MAP_DEPS and tools):
            self.skipTest("LEGACY_MAP_DEPS and LEGACY_BUILD_TOOLS are not set")
        _, staged = self.helper.stage_skill(self.base / "stage", [Path(tools), Path(MAP_DEPS)])
        skill = self.base / "stage" / "skill"
        installed = self.helper.selected_distributions(Path(MAP_DEPS))["tree-sitter"]
        # The wheel itself carries only the binding's license.
        self.assertEqual([path.name for path in self.helper.distribution_license_files(installed)], ["LICENSE"])
        self.assertEqual(len(staged), 2)
        listed = (skill / "BUNDLED_LICENSES.md").read_text(encoding="utf-8")
        for item in staged:
            self.assertEqual(digest((skill / item["license"]).read_bytes()), item["sha256"])
            self.assertIn(f"`{item['license']}` | `{item['sha256']}` | {item['source']} |", listed)
        self.assertTrue((skill / "licenses" / "python" / f"tree-sitter-{installed.version}" / "LICENSE").is_file())

    def test_bundle_ships_the_notices_the_wheel_omits(self):
        if not TOOLS_BINARY:
            self.skipTest("LEGACY_TOOLS_BIN is not set")
        artifact = Path(TOOLS_BINARY).parent
        info = json.loads((artifact / "BUILD-INFO.json").read_text(encoding="utf-8"))
        shipped = {item["license"]: item for item in info["additional_notices"]}
        listed = (artifact / "BUNDLED_LICENSES.md").read_text(encoding="utf-8")
        for record in self.helper.pinned_notices():
            use = record.get("pypi")
            if not use:
                continue
            with self.subTest(notice=record["file"]):
                self.assertEqual(info["distributions"][use["name"]], use["version"])
                path = f"licenses/python/{use['name']}-{use['version']}/{use['bundle_path']}"
                self.assertEqual((shipped[path]["sha256"], shipped[path]["source"]), (record["sha256"], record["origin"]))
                self.assertEqual(digest((artifact / path).read_bytes()), record["sha256"])
                self.assertIn(f"`{path}` | `{record['sha256']}`", listed)

    def test_distribution_license_files_with_one_name_are_refused(self):
        files = ["demo-1.0.dist-info/licenses/LICENSE", "demo/_vendor/other/LICENSE", "demo/__init__.py"]
        for relative in files:
            (self.base / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.base / relative).write_text(relative, encoding="utf-8")
        distribution = type("Distribution", (), {"version": "1.0", "metadata": {"Name": "demo"}, "files": files, "locate_file": lambda _, item: self.base / item})()
        with self.assertRaisesRegex(self.helper.BuildError, "demo 1.0 has license files that share a name"):
            self.helper.distribution_license_files(distribution)
        distribution.files = files[:1] + files[2:]
        self.assertEqual(self.helper.distribution_license_files(distribution), [self.base / files[0]])

    def test_pinned_notices_match_the_published_python_source(self):
        sources = os.environ.get("LEGACY_LICENSE_SOURCES")
        if not sources:
            self.skipTest("LEGACY_LICENSE_SOURCES is not set")
        for record in self.helper.pinned_notices():
            use = record.get("pypi")
            if not use:
                continue
            with self.subTest(notice=record["file"]):
                archive = Path(sources) / use["sdist"].rsplit("/", 1)[1]
                self.assertEqual(digest(archive.read_bytes()), use["sdist_sha256"])
                prefix = f"{use['name']}-{use['version']}/"
                with tarfile.open(archive) as bundle:
                    names = set(bundle.getnames())
                    self.assertIn('"tree_sitter/core/lib/src/lib.c"', bundle.extractfile(prefix + "setup.py").read().decode("utf-8"))
                    if use["sdist_path"]:
                        self.assertEqual(digest(bundle.extractfile(prefix + use["sdist_path"]).read()), record["sha256"])
                    else:
                        # The source release omits this text; its origin is the pinned upstream commit.
                        self.assertNotIn(prefix + use["bundle_path"], names)


if __name__ == "__main__":
    unittest.main()
