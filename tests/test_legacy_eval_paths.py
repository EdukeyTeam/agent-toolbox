"""Benchmark helpers locate a relocated checkout without developer paths."""
import ast
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkPathTests(unittest.TestCase):
    def test_embedded_helpers_derive_repository_from_their_location(self):
        with tempfile.TemporaryDirectory() as directory:
            relocated = Path(directory) / 'checkout with spaces'
            for name, variable in (('vector-scan-source.py', 'root'), ('report-source.py', 'REPO'), ('benchmark-source.py', 'REPO')):
                with self.subTest(name=name):
                    relative = Path('evals/retrieval/results/embeddings') / name
                    tree = ast.parse((ROOT / relative).read_text())
                    assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets))
                    namespace = {'Path': Path, '__file__': str(relocated / relative)}
                    exec(compile(ast.Module(body=[assignment], type_ignores=[]), name, 'exec'), namespace)
                    self.assertEqual(namespace[variable], relocated)

    def test_evaluation_scripts_and_instructions_have_no_machine_home_paths(self):
        for path in (ROOT / 'evals').rglob('*'):
            if path.suffix in {'.py', '.md', '.sh', '.mjs', '.cjs', '.js'}:
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertNotRegex(path.read_text(), r'/home/[^/]+/|/Users/[^/]+/|[A-Z]:[\\/]Users[\\/]')
