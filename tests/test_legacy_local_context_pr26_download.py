"""PR #26: setup's next command carries one-time model download consent."""
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


class DownloadCommandTests(unittest.TestCase):
    def test_next_command_preserves_explicit_download_flag_only_when_approved(self):
        for approved in (False, True):
            with self.subTest(approved=approved), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "source with spaces"
                root.mkdir()
                output = io.StringIO()
                arguments = [str(root), "--library-id", "/local/download", "--embed-provider", "local-python"]
                if approved:
                    arguments.append("--download-model")
                with mock.patch.object(setup_context7, "runtime_for", return_value=base / "runtime"), contextlib.redirect_stdout(output):
                    self.assertEqual(setup_context7.main(arguments), 0)
                command = json.loads(output.getvalue())["nextCommand"]
                expected = [sys.executable, str(root / "tools/local_context7.py"), "index"]
                if approved:
                    expected.append("--download-model")
                self.assertEqual(command, setup_context7.shell_command(expected))


if __name__ == "__main__":
    unittest.main()
