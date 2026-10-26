"""Setup carries per-invocation remote consent into the first index command."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"))
import setup_context7


class RemoteSetupCommandTests(unittest.TestCase):
    def test_next_command_preserves_remote_flag_only_when_approved(self):
        for remote in (False, True):
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "source with spaces"
                root.mkdir()
                arguments = [str(root), "--library-id", "/local/setup", "--embed-provider", "openai-compatible", "--embed-model", "fixture-model",
                             "--embed-base-url", "https://remote.example/v1" if remote else "http://localhost:8080/v1"]
                if remote:
                    arguments.append("--allow-remote-embeddings")
                output = io.StringIO()
                with mock.patch.object(setup_context7, "runtime_for", return_value=base / "runtime"), contextlib.redirect_stdout(output):
                    self.assertEqual(setup_context7.main(arguments), 0)
                expected = [sys.executable, str(root / "tools/local_context7.py"), "index"]
                if remote:
                    expected.append("--allow-remote-embeddings")
                self.assertEqual(json.loads(output.getvalue())["nextCommand"], setup_context7.shell_command(expected))
