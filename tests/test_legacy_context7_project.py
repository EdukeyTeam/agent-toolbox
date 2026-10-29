"""Project generator and runtime checks; synthetic corpora only."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shlex
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

    def test_explicit_interpreter_is_used_in_configuration_and_guidance(self):
        with mock.patch.object(setup.shutil, "which", return_value=None):
            self.prepare("--agent", "codex", "--python", "python3", "--with-agents-md", "--consent-agents-md")
        config = tomllib.loads((self.root / ".codex/config.toml").read_text())
        self.assertEqual(config["mcp_servers"]["context7-local"]["command"], "python3")
        note = (self.root / "AGENTS.md").read_text()
        self.assertIn("python3", note)
        self.assertIn(str(self.root / "tools/local_context7.py"), note)
        self.assertIn("refresh", note)

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

    def test_all_agent_formats_preview_merge_and_repeat(self):
        for agent, (relative, key) in setup.JSON_CLIENTS.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"unrelated": {"keep": True}, key: {"other": {"command": "unchanged"}}}))
        original = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        flags = tuple(x for a in setup.AGENTS for x in ("--agent", a)) + ("--with-hooks", "--consent-hooks", "--with-agents-md", "--consent-agents-md")
        report = self.prepare(*flags, "--dry-run")
        self.assertEqual(original, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(set(report["manualRefreshClients"]), {"opencode", "antigravity"})
        self.prepare(*flags)
        for agent, (relative, key) in setup.JSON_CLIENTS.items():
            config = json.loads((self.root / relative).read_text())
            self.assertEqual(config["unrelated"], {"keep": True})
            self.assertEqual(config[key]["other"], {"command": "unchanged"})
            entry = config[key]["context7-local"]
            if agent == "opencode":
                self.assertEqual(entry["type"], "local")
                self.assertIsInstance(entry["command"], list)
            else:
                self.assertEqual(entry["args"][-1], "mcp")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.prepare(*flags)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_replaces_only_marked_instructions_and_claude_is_opt_in(self):
        (self.root / "AGENTS.md").write_text("Before\n<!-- local-context7 -->\nObsolete guidance\n<!-- /local-context7 -->\nAfter\n")
        flags = ("--with-agents-md", "--consent-agents-md")
        self.prepare(*flags)
        note = (self.root / "AGENTS.md").read_text()
        self.assertTrue(note.startswith("Before\n"))
        self.assertTrue(note.endswith("After\n"))
        self.assertNotIn("Obsolete", note)
        for text in ("/local/demo", "query", "expand --unit-id", "refresh", "untrusted data", "empty results do not prove absence"):
            self.assertIn(text, note)
        self.assertFalse((self.root / "CLAUDE.md").exists())
        self.prepare(*flags, "--with-claude-md")
        self.assertEqual((self.root / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        (self.root / "CLAUDE.md").write_text("Human rules\n")
        self.assertIn("Existing file differs", self.prepare(*flags, "--with-claude-md", expected=1))
        self.assertEqual((self.root / "CLAUDE.md").read_text(), "Human rules\n")

    def test_malformed_instruction_markers_refuse_before_writing(self):
        (self.root / "AGENTS.md").write_text("<!-- local-context7 -->\nUser text\n")
        self.assertIn("Malformed", self.prepare("--with-agents-md", "--consent-agents-md", expected=1))
        self.assertFalse((self.root / "tools").exists())

    def test_embedding_settings_are_explicit_and_do_not_download_at_setup(self):
        model = self.base / "model"
        model.mkdir()
        report = self.prepare("--parser", "0", "--embed-provider", "local-python", "--model-dir", str(model))
        project = json.loads((self.root / "tools/context7/project.json").read_text())
        self.assertEqual(report["defaultMode"], "hybrid")
        self.assertEqual(project["engine"]["parser"], "0")
        self.assertEqual(project["engine"]["model_dir"], str(model))
        self.assertEqual(project["engine"]["embed_model"], "minishlab/potion-code-16M-v2")
        self.assertFalse(project["consent"]["modelDownload"])
        self.assertEqual(list(model.iterdir()), [])
        self.assertIn("not approved", self.cli("index", "--download-model", expected=1).stderr)

    def test_remote_consent_and_key_name_validated_before_writes(self):
        flags = ("--embed-provider", "openai-compatible", "--embed-base-url", "https://gateway.example.invalid/v1", "--embed-model", "fixture")
        self.assertIn("Ask the user first", self.prepare(*flags, expected=1))
        self.assertFalse((self.root / "tools").exists())
        self.assertIn("environment variable", self.prepare(*flags, "--allow-remote-embeddings", "--embed-api-key-env", "invalid=value", expected=1))
        report = self.prepare(*flags, "--allow-remote-embeddings", "--embed-api-key-env", "FIXTURE_API_KEY")
        self.assertEqual(report["defaultMode"], "lexical")
        self.assertIn("query", report["defaultModeReason"])
        self.assertIn("remote", report["defaultModeReason"].lower())
        self.assertEqual(json.loads((self.root / "tools/context7/project.json").read_text())["defaultMode"], "lexical")
        self.assertTrue(report["engine"]["allow_remote_embeddings"])
        self.assertEqual(report["engine"]["embed_api_key_env"], "FIXTURE_API_KEY")

    def test_generated_remote_project_default_query_works_without_remote_calls(self):
        from local_context import freshness
        from test_legacy_local_context_review import FakeProvider
        flags = ("--parser", "0", "--embed-provider", "openai-compatible", "--embed-base-url", "https://gateway.example.invalid/v1", "--embed-model", "fixture", "--allow-remote-embeddings")
        report = self.prepare(*flags)
        spec = importlib.util.spec_from_file_location("generated_remote_launcher", self.root / "tools/local_context7.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with mock.patch.object(freshness, "provider_for", return_value=FakeProvider()):
            launcher.index(setup.backend, Path(report["runtime"]), allow_remote_embeddings=True)
        result = json.loads(self.cli("query", "retryTransfer").stdout)
        self.assertEqual(result["mode"], "lexical")
        self.assertTrue(result["results"])
        # Explicit semantic mode continues to fail before connecting to the endpoint.
        forbidden = self.cli("query", "retryTransfer", "--mode", "semantic", expected=1)
        self.assertIn("Remote embeddings", forbidden.stderr)

    def test_loopback_needs_no_remote_grant_and_no_provider_rejects_options(self):
        self.assertIn("Embedding options require", self.prepare("--download-model", expected=1))
        report = self.prepare("--embed-provider", "openai-compatible", "--embed-base-url", "http://127.0.0.1:11434/v1", "--embed-model", "fixture")
        self.assertEqual(report["defaultMode"], "hybrid")
        self.assertFalse(report["engine"]["allow_remote_embeddings"])

    def test_download_permission_is_recorded_without_network_during_setup(self):
        report = self.prepare("--embed-provider", "local-python", "--cache-dir", str(self.base / "model-cache"), "--download-model")
        config = json.loads((self.root / "tools/context7/project.json").read_text())
        self.assertTrue(config["consent"]["modelDownload"])
        self.assertEqual(report["engine"]["model_cache"], str(self.base / "model-cache"))
        self.assertFalse((self.base / "model-cache").exists())

    def test_invalid_endpoint_reports_clean_error_before_writes(self):
        error = self.prepare("--embed-provider", "openai-compatible", "--embed-base-url", "https://user:synthetic@example.invalid/v1", "--embed-model", "fixture", expected=1)
        self.assertIn("without credentials", error)
        self.assertNotIn("synthetic", error)
        self.assertFalse((self.root / "tools").exists())

    def test_ambient_embedding_defaults_do_not_enable_provider(self):
        with mock.patch.dict(os.environ, {"LEGACY_EMBED_PROVIDER": "openai-compatible", "LEGACY_EMBED_BASE_URL": "https://unused.example.invalid/v1", "LEGACY_EMBED_MODEL": "unused"}):
            self.prepare()
            self.cli("index")
            status = json.loads(self.cli("status").stdout)
        self.assertEqual(status["libraries"][0]["embedding"]["config"]["provider"], "none")

    def test_hook_merges_retain_unrelated_handlers_and_metadata(self):
        fixtures = ((".cursor/hooks.json", "afterFileEdit", False), (".gemini/settings.json", "AfterTool", True), (".github/hooks/context7-local.json", "PostToolUse", False))
        for path, event, nested in fixtures:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = {"type": "command", "command": "existing-user-handler"}
            entry = {"hooks": [handler], "matcher": "existing"} if nested else handler
            target.write_text(json.dumps({"metadata": "preserve", "hooks": {event: [entry]}}))
        self.prepare("--agent", "cursor", "--agent", "gemini", "--agent", "copilot", "--with-hooks", "--consent-hooks")
        for path, event, nested in fixtures:
            config = json.loads((self.root / path).read_text())
            self.assertEqual(config["metadata"], "preserve")
            self.assertEqual(len(config["hooks"][event]), 2)
            first = config["hooks"][event][0]
            self.assertEqual((first["hooks"][0] if nested else first)["command"], "existing-user-handler")

    def test_parser_propagates_and_policy_change_refreshes_fresh_index(self):
        self.prepare("--parser", "0")
        self.cli("index")
        before = json.loads(self.cli("status").stdout)["libraries"][0]
        self.prepare("--parser", "auto")
        self.cli("refresh")
        report = self.prepare("--parser", "auto")
        with setup.backend.connect(Path(report["database"])) as con:
            scope = json.loads(con.execute("SELECT scope_json FROM libraries").fetchone()[0])
        self.assertEqual(scope["parser"], "auto")
        self.assertTrue(before)

    def test_expand_uses_project_database_and_library(self):
        self.prepare()
        self.cli("index")
        result = json.loads(self.cli("expand", "--path", "src/Demo.java", "--root-id", "r0", "--start-line", "1", "--end-line", "3").stdout)
        self.assertIn("retryTransfer", json.dumps(result))

    def test_policy_change_blocks_queries_until_refresh(self):
        self.prepare("--parser", "0")
        self.cli("index")
        self.prepare("--parser", "auto")
        self.assertIn("policy changed", self.cli("query", "retryTransfer", expected=1).stderr)
        self.cli("refresh")
        self.assertTrue(json.loads(self.cli("query", "retryTransfer").stdout)["results"])

    def test_refresh_does_not_skip_pending_vectors_with_current_source(self):
        report = self.prepare()
        self.cli("index")
        with setup.backend.connect(Path(report["database"])) as con:
            con.execute("UPDATE files SET embedding_status='pending'")
            con.commit()
        launcher_spec = importlib.util.spec_from_file_location("pending_launcher", self.root / "tools/local_context7.py")
        launcher = importlib.util.module_from_spec(launcher_spec)
        launcher_spec.loader.exec_module(launcher)
        # A candidate refresh can update lexical hashes before vectors. The
        # wrapper must call the provider-preserving refresh even when hashes match.
        with mock.patch.object(setup.backend, "refresh", return_value={"changed": 0, "deleted": 0}) as native:
            result = launcher.refresh(setup.backend, Path(report["runtime"]))
        self.assertTrue(result["refreshed"])
        native.assert_called_once_with(Path(report["database"]), "/local/demo", allow_remote_embeddings=False, automatic=False)

    def test_generated_remote_refresh_requires_new_consent_and_hooks_defer_vectors(self):
        from local_context import freshness
        from test_legacy_local_context_review import FakeProvider
        report = self.prepare("--embed-provider", "openai-compatible", "--embed-base-url", "https://remote.example/v1", "--embed-model", "review-fixture", "--allow-remote-embeddings", "--agent", "claude", "--with-hooks", "--consent-hooks", "--with-agents-md", "--consent-agents-md")
        runtime = Path(report["runtime"])
        spec = importlib.util.spec_from_file_location("remote_launcher", self.root / "tools/local_context7.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        provider = FakeProvider()
        with mock.patch.object(freshness, "provider_for", return_value=provider) as factory:
            # The generated index path must also require invocation-scoped consent.
            with self.assertRaises(setup.backend.RetrievalError):
                launcher.index(setup.backend, runtime)
            factory.assert_not_called()
            launcher.index(setup.backend, runtime, allow_remote_embeddings=True)
        self.java.write_text("public class Demo { public void remoteHookTransfer() {} }\n")
        with mock.patch.object(freshness, "provider_for") as factory:
            with self.assertRaises(setup.backend.RetrievalError) as caught:
                launcher.refresh(setup.backend, runtime)
            self.assertEqual(caught.exception.code, "consent_required")
            factory.assert_not_called()
        # Run the actual generated hook in a child process: the invalid remote
        # test domain would fail if the provider were constructed or contacted.
        handler = json.loads((self.root / ".claude/settings.json").read_text())["hooks"]["PostToolUse"][0]["hooks"][0]
        event = {"hook_event_name": "PostToolUse", "cwd": str(self.root)}
        hook = subprocess.run([handler["command"], *handler["args"]], input=json.dumps(event), cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(hook.returncode, 0, hook.stderr)
        self.assertIn("refresh --allow-remote-embeddings", hook.stdout)
        with setup.backend.connect(Path(report["database"])) as con:
            self.assertEqual(con.execute("SELECT embedding_status FROM files WHERE path='src/Demo.java'").fetchone()[0], "pending")
        with mock.patch.object(freshness, "provider_for", return_value=provider) as factory:
            result = launcher.refresh(setup.backend, runtime, allow_remote_embeddings=True)
            self.assertTrue(factory.called)
            self.assertEqual(result["pendingEmbeddings"], 0)
        # Unchanged corpora cannot silently accept persisted consent either.
        error = self.cli("refresh", expected=5)
        self.assertEqual(json.loads(error.stderr)["code"], "consent_required")
        self.assertIn("refresh --allow-remote-embeddings", (self.root / "AGENTS.md").read_text())

    def test_remote_hook_policy_change_and_first_index_never_embed(self):
        from local_context import freshness
        report = self.prepare("--embed-provider", "openai-compatible", "--embed-base-url", "https://remote.example/v1", "--embed-model", "review-fixture", "--allow-remote-embeddings")
        spec = importlib.util.spec_from_file_location("remote_initial_launcher", self.root / "tools/local_context7.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with mock.patch.object(freshness, "provider_for") as factory:
            initial = launcher.refresh(setup.backend, Path(report["runtime"]), automatic=True)
            self.assertTrue(initial["remoteEmbeddingsDeferred"])
            # Exercise the policy-mismatch reindex path, not just native refresh.
            launcher.ENGINE["parser"] = "0"
            changed = launcher.refresh(setup.backend, Path(report["runtime"]), automatic=True)
            self.assertTrue(changed["remoteEmbeddingsDeferred"])
            factory.assert_not_called()

    def test_each_hook_payload_refreshes_and_ignores_other_checkouts(self):
        flags = tuple(x for a in ("codex", "gemini", "copilot", "cursor") for x in ("--agent", a))
        self.prepare(*flags, "--with-hooks", "--consent-hooks")
        self.cli("index")
        paths = ((".codex/hooks.json", "PostToolUse", True), (".gemini/settings.json", "AfterTool", True), (".github/hooks/context7-local.json", "PostToolUse", False), (".cursor/hooks.json", "afterFileEdit", False))
        for i, (relative, name, nested) in enumerate(paths):
            self.java.write_text(f"public class Demo {{ public void hookVariant{i}() {{}} }}\n")
            handler = json.loads((self.root / relative).read_text())["hooks"][name][0]
            if nested:
                handler = handler["hooks"][0]
            command = shlex.split(handler["command"]) if os.name != "nt" else handler["command"]
            event = {"hook_event_name": name, "cwd": str(self.base / "different")}
            result = subprocess.run(command, input=json.dumps(event), cwd=self.root, capture_output=True, text=True, timeout=20, check=True)
            self.assertEqual(result.stdout, "")
            event = {"hook_event_name": name, **({"workspace_roots": [str(self.root)]} if relative.startswith(".cursor") else {"cwd": str(self.root / "src")})}
            subprocess.run(command, input=json.dumps(event), cwd=self.root / "src", capture_output=True, text=True, timeout=20, check=True)
            self.assertFalse(json.loads(self.cli("refresh").stdout)["refreshed"])
            self.assertTrue(json.loads(self.cli("query", f"hookVariant{i}").stdout)["results"])

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
            # Format 8 refreshes candidate deletions; cached Java source must vanish.
            self.assertNotIn("Source: src/Demo.java", mcp.request("tools/call", args)["content"][0]["text"])
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
