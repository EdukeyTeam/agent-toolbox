"""Project generator and runtime checks; synthetic corpora only."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows"
spec = importlib.util.spec_from_file_location("context7_setup", SKILL / "scripts/setup_context7.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "repository with spaces"
        self.root.mkdir()
        (self.root / "docs").mkdir()
        (self.root / "src").mkdir()
        self.java = self.root / "src/Demo.java"
        self.java.write_text("public class Demo {\n public void retryTransfer() {}\n}\n", encoding="utf-8")
        (self.root / "docs/api.md").write_text("Demo.retryTransfer retries a transfer.\n", encoding="utf-8")
        self.environment = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "cache"), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def prepare(self, *flags, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup.main([str(self.root), "--library-id", "/local/demo", *flags])
        self.assertEqual(code, expected, err.getvalue())
        return json.loads(out.getvalue()) if code == 0 else err.getvalue()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(self.root / "tools/local_context7.py"), *args], cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_each_optional_addition_requires_consent_before_writes(self):
        original = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for flags in (("--with-agents-md",), ("--agent", "codex", "--with-hooks"), ("--agent", "codex", "--with-hooks", "--consent-hooks", "--with-agents-md")):
            self.assertIn("Ask the user first", self.prepare(*flags, expected=1))
            self.assertEqual(original, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
            self.assertFalse((self.base / "cache").exists())

    def test_default_leaves_instructions_and_hooks_untouched(self):
        (self.root / "AGENTS.md").write_text("Existing user rules\n")
        report = self.prepare()
        self.assertEqual((self.root / "AGENTS.md").read_text(), "Existing user rules\n")
        self.assertFalse((self.root / ".codex").exists())
        self.assertFalse((self.root / ".claude").exists())
        self.assertFalse(report["clientsInstalled"])
        self.assertTrue((Path(report["runtime"]) / "backend/scripts/context7_backend.py").is_file())

    def test_preview_lists_proposal_without_writes_or_inferred_consent(self):
        report = self.prepare("--agent", "codex", "--with-hooks", "--with-agents-md", "--dry-run")
        self.assertIn("AGENTS.md", report["files"])
        self.assertIn(str(Path(".codex/hooks.json")), report["files"])
        self.assertFalse((self.root / "tools").exists())
        self.assertFalse(Path(report["runtime"]).exists())

    def test_approved_merge_preserves_existing_settings_and_is_idempotent(self):
        (self.root / ".codex").mkdir()
        (self.root / ".codex/config.toml").write_text('model_context_window = 1000000\n[mcp_servers.context7]\nurl = "https://public.example.invalid/mcp"\n')
        (self.root / ".claude").mkdir()
        (self.root / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(synthetic-command)"]}}))
        flags = ("--agent", "codex", "--agent", "claude", "--with-hooks", "--consent-hooks", "--with-agents-md", "--consent-agents-md")
        self.prepare(*flags)
        settings = tomllib.loads((self.root / ".codex/config.toml").read_text())
        self.assertEqual(settings["model_context_window"], 1000000)
        self.assertEqual(settings["mcp_servers"]["context7"]["url"], "https://public.example.invalid/mcp")
        self.assertEqual(json.loads((self.root / ".claude/settings.json").read_text())["permissions"]["deny"], ["Bash(synthetic-command)"])
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.prepare(*flags)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual((self.root / "AGENTS.md").read_text().count("<!-- local-context7 -->"), 1)

    def test_missing_python_alias_uses_python3_in_configuration_and_guidance(self):
        with mock.patch.object(setup.shutil, "which", return_value=None):
            self.prepare("--agent", "codex", "--with-agents-md", "--consent-agents-md")
        config = tomllib.loads((self.root / ".codex/config.toml").read_text())
        self.assertEqual(config["mcp_servers"]["context7-local"]["command"], "python3")
        self.assertIn("python3 tools/local_context7.py refresh", (self.root / "AGENTS.md").read_text())

    def test_conflicting_existing_server_refuses_all_writes(self):
        (self.root / ".mcp.json").write_text(json.dumps({"mcpServers": {"context7-local": {"url": "https://other.example.invalid"}}}))
        self.assertIn("differs", self.prepare("--agent", "claude", expected=1))
        self.assertFalse((self.root / "tools").exists())
        self.assertFalse((self.base / "cache").exists())

    def test_docs_cannot_escape_through_a_parent_symlink(self):
        external = self.base / "external"
        (external / "docs").mkdir(parents=True)
        try:
            (self.root / "link").symlink_to(external, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Directory symlinks unavailable: {exc}")
        self.assertIn("nonsymlink", self.prepare("--docs-root", "link/docs", expected=1))
        self.assertFalse((self.root / "tools").exists())

    def test_owned_runtime_stays_outside_the_corpus(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            self.assertIn("outside", self.prepare(expected=1))
        self.assertFalse((self.root / "tools").exists())

    def test_prepared_cli_preserves_unchanged_chunks_and_refresh_is_noop(self):
        report = self.prepare()
        indexed = json.loads(self.cli("index").stdout)
        self.assertEqual(indexed["files"], 2)
        database = Path(report["database"])
        with setup.backend.connect(database) as con:
            original = [tuple(r) for r in con.execute("SELECT id,path,body FROM chunks WHERE kind='docs'")]
        self.assertFalse(json.loads(self.cli("refresh").stdout)["refreshed"])
        self.java.write_text("public class Demo { public void cancelTransfer() {} }\n")
        result = json.loads(self.cli("refresh").stdout)
        self.assertEqual((result["changed"], result["deleted"]), (1, 0))
        with setup.backend.connect(database) as con:
            self.assertEqual(original, [tuple(r) for r in con.execute("SELECT id,path,body FROM chunks WHERE kind='docs'")])
        self.java.unlink()
        result = json.loads(self.cli("refresh").stdout)
        self.assertEqual((result["changed"], result["deleted"]), (0, 1))

    def test_configured_hook_from_nested_directory_refreshes_then_is_silent(self):
        self.prepare("--agent", "claude", "--with-hooks", "--consent-hooks")
        self.cli("index")
        self.java.write_text("public class Demo { public void hookTransfer() {} }\n")
        config = json.loads((self.root / ".claude/settings.json").read_text())
        handler = config["hooks"]["PostToolUse"][0]["hooks"][0]
        event = {"hook_event_name": "PostToolUse", "cwd": str(self.root / "src"), "tool_name": "Edit"}
        command = [handler["command"], *handler["args"]]
        for expected in ("1 changed", ""):
            result = subprocess.run(command, input=json.dumps(event), cwd=self.root / "src", capture_output=True, text=True, timeout=20, check=True)
            self.assertIn(expected, result.stdout)
            if expected == "":
                self.assertEqual(result.stdout, "")
        self.assertTrue(json.loads(self.cli("query", "hookTransfer").stdout)["results"])

    def test_backend_hash_failure_is_explicit(self):
        report = self.prepare()
        path = Path(report["runtime"]) / "backend/scripts/repo_files.py"
        path.write_text("# modified fixture\n")
        self.assertIn("Missing or changed pinned backend", self.cli("index", expected=1).stderr)

    @unittest.skipUnless(os.environ.get("LEGACY_CONTEXT7_CLIENTS") == "1", "explicit pinned-client integration opt-in")
    def test_real_official_mcp_and_cli_use_prepared_local_backend(self):
        for args in (("init",), ("add", "src/Demo.java", "docs/api.md"), ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "core.hooksPath=/dev/null", "commit", "-m", "Synthetic source")):
            subprocess.run(["git", *args], cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, check=True)
        self.prepare("--clients", "--agent", "codex", "--with-hooks", "--consent-hooks")
        self.cli("index")
        settings = tomllib.loads((self.root / ".codex/config.toml").read_text())
        server = settings["mcp_servers"]["context7-local"]
        command = [server["command"], *server["args"]]
        with MCP(command, self.root / "src") as mcp:
            names = {t["name"] for t in mcp.request("tools/list")["tools"]}
            self.assertEqual(names, {"resolve-library-id", "query-docs"})
            result = mcp.request("tools/call", {"name": "resolve-library-id", "arguments": {"libraryName": "demo", "query": "retryTransfer"}})
            self.assertIn("/local/demo", result["content"][0]["text"])
            args = {"name": "query-docs", "arguments": {"libraryId": "/local/demo", "query": "retryTransfer"}}
            result = mcp.request("tools/call", args)
            self.assertIn("src/Demo.java", result["content"][0]["text"])
            self.java.unlink()
            self.assertIn("409", mcp.request("tools/call", args)["content"][0]["text"])
        self.cli("refresh")
        cli = json.loads(self.cli("library", "retryTransfer").stdout)
        self.assertEqual(cli[0]["id"], "/local/demo")


class MCP:
    def __init__(self, command, cwd):
        self.command, self.cwd = command, cwd

    def __enter__(self):
        self.proc = subprocess.Popen(self.command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.messages = queue.Queue()
        self.serial = 0
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        try:
            self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "source-skill-test", "version": "1"}})
            self.write({"jsonrpc": "2.0", "method": "notifications/initialized"})
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def read(self):
        for line in self.proc.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                self.messages.put({"error": "non-JSON MCP output"})
        self.messages.put({"error": "MCP closed stdout"})

    def write(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params=None):
        self.serial += 1
        self.write({"jsonrpc": "2.0", "id": self.serial, "method": method, "params": params or {}})
        deadline = time.monotonic() + 20
        while True:
            result = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if "error" in result:
                raise AssertionError(result["error"])
            if result.get("id") == self.serial:
                return result["result"]

    def __exit__(self, *_):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.reader.join(timeout=2)
        self.proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
