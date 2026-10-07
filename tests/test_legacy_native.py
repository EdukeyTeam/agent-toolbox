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
"""

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_inherited_git_trace_cannot_write_into_source(self):
        trace = self.source / "trace.log"
        env = {**os.environ, "GIT_TRACE": str(trace), "GIT_DIR": str(self.base / "wrong-git-dir")}
        result = subprocess.run([str(RUST_BINARY), str(self.source), "--output-dir", str(self.base / "trace-map")], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.load("trace-map", "inventory.json")["git"])
        self.assertFalse(trace.exists())

    def test_corrupt_git_index_records_inventory_failure_and_invalidates_old_outputs(self):
        good = self.rust("same-output")
        self.assertEqual(good.returncode, 0, good.stderr)
        (self.source / ".git" / "index").write_bytes(b"invalid git index")
        failed = self.rust("same-output")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.load("same-output", "map.meta.json")["failure"]["stage"], "inventory")
        self.assertEqual(self.load("same-output", "map.meta.json")["status"], "failed")
        self.assertFalse((self.base / "same-output" / "inventory.json").exists())
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

    @unittest.skipIf(os.name != "posix", "requires POSIX byte paths")
    def test_invalid_utf8_filenames_respect_max_files(self):
        source = self.base / "byte-paths"
        source.mkdir()
        for index in range(4):
            with open(os.fsencode(source) + b"/file-" + bytes([0xff, 48 + index]), "wb") as handle:
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
                self.assertIn("Aider", self.call(program, env, "notices").stdout)

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


class BuildHelperTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
