"""Offline release tests. Git mutations use disposable fixture repositories."""

import ast
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("legacy_release", Path(__file__).resolve().parents[1] / "scripts/legacy-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
check = release.contract


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Release fixture")
        self.policy = {"repository": "owner/repo", "native_version": "0.3.0", "release_tag": "legacy-tools-v0.3.0",
                       "source_contract": "repo_map.py 1.2.0", "release_manifest": "legacy-tools-release.json",
                       "platforms": {name: {"archive": name + ".zip"} for name in ("linux-x86_64", "windows-x86_64", "macos-arm64")}}
        self.write_pins("0.3.0")
        self.write(check.CRATE + "src/main.rs", 'const BASELINE_CONTRACT: &str = "repo_map.py 1.2.0";\n')
        self.write(check.SKILL + "scripts/repo_map.py", 'VERSION = "1.2.0"\n')
        self.commit()
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        env = patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": "owner/repo"})
        env.start()
        self.addCleanup(env.stop)

    def git(self, *args):
        return check.git(self.root, *args)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def write_pins(self, version):
        self.policy.update(native_version=version, release_tag=f"legacy-tools-v{version}")
        self.write(check.POLICY, json.dumps(self.policy))
        self.write(check.CRATE + "Cargo.toml", f'[package]\nname = "legacy-repo-map"\nversion = "{version}"\n')
        self.write(check.CRATE + "Cargo.lock", f'[[package]]\nname = "legacy-repo-map"\nversion = "{version}"\n')
        for path in ("SKILL.md", "references/distribution.md", "references/setup.md"):
            self.write(check.SKILL + path, f"Pinned legacy-tools-v{version}; native version {version}; repo_map.py 1.2.0\n")
        self.write(check.SKILL + "references/native-tooling.md", f"current {version} package\n")

    def commit(self):
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and ".git" not in path.relative_to(self.root).parts:
                self.git("add", str(path.relative_to(self.root)))
        self.git("commit", "-m", "Fixture release inputs")

    def test_current_repository_pins_agree(self):
        check.validate()

    def test_docs_tests_and_workflow_changes_need_no_bump(self):
        for path in (check.SKILL + "references/new.md", "tests/test_fixture.py", ".github/workflows/release-legacy-tools.yml"):
            self.write(path, "# orchestration or consumer\n")
            self.git("add", path)
        self.assertEqual(check.check(self.root, base=self.base)["changed_inputs"], [])

    def test_each_release_input_change_requires_bump(self):
        paths = [check.CRATE + "src/new.rs", check.CRATE + "licenses/new.txt", check.SKILL + "vendor/queries/new.scm",
                 check.SKILL + "scripts/repo_map.py", check.SKILL + "scripts/repo_files.py",
                 check.SKILL + "scripts/repo_render.py", check.SKILL + "scripts/legacy_common.py",
                 check.SKILL + "scripts/setup_native.py", check.SKILL + "scripts/new_helper.py",
                 check.SKILL + "scripts/requirements-retrieval.txt", check.SKILL + "scripts/retrieval/embed.mjs",
                 check.SKILL + "vendor/queries/README.md", *sorted(check.INPUT_FILES)]
        for path in paths:
            with self.subTest(path=path):
                target = self.root / path
                original = target.read_text() if target.exists() else None
                self.write(path, (original or "") + "\n")
                self.git("add", path)
                with self.assertRaisesRegex(ValueError, "without a version bump"):
                    check.check(self.root, base=self.base)
                if original is None:
                    target.unlink()
                    self.git("rm", "--cached", path)
                else:
                    self.write(path, original)
                    self.git("add", path)

    def test_repo_render_alone_requires_a_version_bump(self):
        path = check.SKILL + "scripts/repo_render.py"
        self.write(path, "# changed rendering behavior\n")
        self.git("add", path)
        with self.assertRaisesRegex(ValueError, "without a version bump.*repo_render.py"):
            check.check(self.root, base=self.base)

    def test_mapper_transitive_local_imports_are_release_inputs(self):
        # Parse without importing optional parser dependencies. Follow imports
        # recursively so a future unlisted helper outside scripts/ fails here.
        roots = [check.ROOT / "scripts", check.ROOT / (check.SKILL + "scripts"), check.ROOT / (check.SKILL + "vendor")]
        modules = {path.stem: path for root in roots for path in root.rglob("*.py") if "__pycache__" not in path.parts}
        pending = [modules["repo_map"], modules["build-legacy-tools"], modules["create-legacy-release-manifest"]]
        visited = set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            self.assertTrue(check.covered(path.relative_to(check.ROOT).as_posix()), f"unlisted local import: {path}")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
                pending.extend(modules[name.split(".")[0]] for name in names if name and name.split(".")[0] in modules)
        self.assertTrue({"repo_render", "repo_files", "aider_rank", "setup_native"} <= {path.stem for path in visited})

    def test_all_builder_staged_resources_are_release_inputs(self):
        skill = check.ROOT / check.SKILL
        paths = [*skill.joinpath("scripts").glob("*.py"),
                 *(path for path in skill.joinpath("scripts/retrieval").iterdir() if path.is_file()),
                 *(path for path in skill.joinpath("vendor").rglob("*") if path.is_file() and "__pycache__" not in path.parts),
                 *(skill / name for name in ("LICENSE.txt", "NOTICE.txt", "THIRD_PARTY.md", "requirements-map.txt", "scripts/requirements-retrieval.txt"))]
        for path in paths:
            self.assertTrue(check.covered(path.relative_to(check.ROOT).as_posix()), f"unlisted staged resource: {path}")

    def test_repository_license_is_not_a_native_release_input(self):
        # The native builder never reads the root MIT LICENSE; the bundle ships the
        # skill's own Apache LICENSE.txt and notices, which stay covered above.
        self.assertFalse(check.covered("LICENSE"))

    def test_coordinated_bump_allows_fix_but_rejects_downgrade(self):
        self.write(check.CRATE + "src/fix.rs", "// fix\n")
        self.git("add", check.CRATE + "src/fix.rs")
        self.write_pins("0.3.1")
        self.assertEqual(check.check(self.root, base=self.base)["release_tag"], "legacy-tools-v0.3.1")
        self.write_pins("0.2.9")
        with self.assertRaisesRegex(ValueError, "without a version bump"):
            check.check(self.root, base=self.base)

    def test_sequential_same_version_merges_fail_against_previous_main(self):
        heads = []
        for branch in ("first", "second"):
            self.git("switch", "-c", branch, self.base)
            self.write_pins("0.3.1")
            self.write(check.CRATE + f"src/{branch}.rs", f"// {branch} fix\n")
            self.commit()
            heads.append(self.git("rev-parse", "HEAD"))
            self.assertEqual(check.check(self.root, base=self.base, head=heads[-1])["release_tag"], "legacy-tools-v0.3.1")
        self.git("switch", "main")
        self.git("merge", "--ff-only", heads[0])
        self.git("merge", "--no-ff", heads[1], "-m", "Second same-version merge")
        with self.assertRaisesRegex(ValueError, "without a version bump"):
            check.check(self.root, base=heads[0], head="HEAD")

    def test_renamed_deleted_and_control_named_release_inputs_need_bump(self):
        self.git("mv", check.CRATE + "src/main.rs", check.CRATE + "src/renamed.rs")
        self.write(check.CRATE + "src/main.rs", 'const BASELINE_CONTRACT: &str = "repo_map.py 1.2.0";\n')
        with self.assertRaisesRegex(ValueError, "without a version bump"):
            check.check(self.root, base=self.base)
        if os.name != "nt":
            path = check.SKILL + "vendor/queries/new\nquery.scm"
            self.write(path, "fixture query\n")
            self.git("add", path)
            self.assertIn(path, check.changed_inputs(self.root, self.base))

    def test_disagreeing_pins_contract_and_docs_fail(self):
        mutations = {
            check.CRATE + "Cargo.toml": '[package]\nversion = "0.3.1"\n',
            check.CRATE + "Cargo.lock": '[[package]]\nname = "legacy-repo-map"\nversion = "0.3.1"\n',
            check.CRATE + "src/main.rs": 'const BASELINE_CONTRACT: &str = "repo_map.py 1.3.0";\n',
            check.SKILL + "scripts/repo_map.py": 'VERSION = "1.3.0"\n',
            check.SKILL + "SKILL.md": "Pinned legacy-tools-v0.2.0\n",
            check.SKILL + "references/distribution.md": "native version 0.2.0\n",
            check.SKILL + "references/setup.md": "repo_map.py 1.1.0\n",
            check.SKILL + "references/native-tooling.md": "current 0.2.0 package\n",
        }
        for path, text in mutations.items():
            with self.subTest(path=path):
                original = (self.root / path).read_text()
                self.write(path, text)
                with self.assertRaises(ValueError):
                    check.validate(self.root)
                self.write(path, original)
        for key, value in (("release_tag", "legacy-tools-v0.2.0"), ("source_contract", "repo_map.py 1.1.0")):
            self.write(check.POLICY, json.dumps({**self.policy, key: value}))
            with self.assertRaises(ValueError):
                check.validate(self.root)

    def test_missing_release_selects_main_without_mutation(self):
        with patch.object(release, "api", return_value=None) as api:
            result = release.plan(self.root)
        self.assertEqual(result["source_commit"], self.base)
        self.assertEqual(result["build"], "true")
        self.assertTrue(all(not call.kwargs.get("data") for call in api.call_args_list))

    def published_release(self):
        names = [self.policy["release_manifest"], "SHA256SUMS", *(item["archive"] for item in self.policy["platforms"].values())]
        return {"draft": False, "prerelease": False, "assets": [{"name": name, "state": "uploaded"} for name in names]}

    def test_published_release_is_successful_noop_on_rerun(self):
        self.git("tag", "-a", self.policy["release_tag"], "-m", "Published fixture")
        remote = {"object": {"sha": self.git("rev-parse", self.policy["release_tag"])}}
        with patch.object(release, "api", side_effect=[self.published_release(), remote]), patch.object(release.subprocess, "run", wraps=subprocess.run) as run:
            result = release.publish(self.root, self.root / "nonexistent-assets", self.base)
        self.assertEqual(result["build"], "false")
        self.assertEqual(result["source_commit"], self.base)
        self.assertFalse(any(call.args[0][0] == "gh" for call in run.call_args_list))

    def test_published_release_rejects_changed_inputs_in_plan_and_publisher(self):
        # Both builds can plan before either release exists. The serialized
        # publisher must check again after the other run publishes its tag.
        with patch.object(release, "api", return_value=None):
            self.assertEqual(release.plan(self.root)["build"], "true")
        self.git("tag", self.policy["release_tag"])
        self.write(check.CRATE + "src/late.rs", "// second merge under the same version\n")
        self.commit()
        head = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", head)
        for publish in (False, True):
            with self.subTest(publish=publish), patch.object(release, "api", side_effect=[self.published_release(), {"object": {"sha": self.base}}]), patch.object(release.subprocess, "run", wraps=subprocess.run) as run:
                with self.assertRaisesRegex(ValueError, "release inputs changed after this version was published; bump the pinned version"):
                    if publish:
                        release.publish(self.root, self.root / "nonexistent-assets", head)
                    else:
                        release.plan(self.root)
                self.assertFalse(any(call.args[0][0] == "gh" for call in run.call_args_list))

    def test_published_release_allows_documentation_only_head(self):
        self.git("tag", self.policy["release_tag"])
        self.write("README.md", "Documentation after publication\n")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        with patch.object(release, "api", side_effect=[self.published_release(), {"object": {"sha": self.base}}]):
            result = release.plan(self.root)
        self.assertEqual(result["build"], "false")
        self.assertEqual(result["source_commit"], self.base)

    def test_published_release_rejects_changed_remote_tag_identity(self):
        self.git("tag", self.policy["release_tag"])
        with patch.object(release, "api", side_effect=[self.published_release(), {"object": {"sha": "f" * 40}}]):
            with self.assertRaisesRegex(ValueError, "remote tag changed"):
                release.plan(self.root)

    def test_partial_published_release_is_reported_without_overwriting(self):
        with patch.object(release, "api", return_value={"draft": False, "assets": []}), self.assertRaisesRegex(ValueError, "lacks required assets"):
            release.plan(self.root)

    def test_draft_or_prerelease_is_never_overwritten(self):
        for state in ({"draft": True}, {"prerelease": True}):
            with patch.object(release, "api", return_value=state), self.assertRaisesRegex(ValueError, "never overwrite"):
                release.plan(self.root)

    def test_annotated_tag_reused_but_changed_source_rejected(self):
        self.git("tag", "-a", self.policy["release_tag"], "-m", "Fixture tag")
        remote = {"object": {"sha": self.git("rev-parse", self.policy["release_tag"])}}
        with patch.object(release, "api", side_effect=[None, remote]):
            self.assertEqual(release.plan(self.root)["source_commit"], self.base)
        self.write(check.CRATE + "src/fix.rs", "// unversioned fix\n")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        with patch.object(release, "api", side_effect=[None, remote]), self.assertRaisesRegex(ValueError, "different release inputs"):
            release.plan(self.root)

    def test_remote_tag_changed_since_fetch_is_rejected(self):
        self.git("tag", self.policy["release_tag"])
        remote = {"object": {"sha": "f" * 40}}
        with patch.object(release, "api", side_effect=[None, remote]), self.assertRaisesRegex(ValueError, "remote tag changed"):
            release.plan(self.root)

    def test_feature_branch_tag_and_pr_cannot_publish(self):
        for ref, event in (("refs/heads/feature", "workflow_dispatch"), ("refs/tags/x", "workflow_dispatch"), ("refs/heads/main", "pull_request")):
            with patch.dict(os.environ, {"GITHUB_REF": ref, "GITHUB_EVENT_NAME": event}), patch.object(release, "api") as api:
                with self.assertRaisesRegex(ValueError, "only allowed"):
                    release.plan(self.root)
                api.assert_not_called()

    def test_source_must_be_on_main_and_requested_pin_must_match(self):
        with self.assertRaisesRegex(ValueError, "requested release_tag"):
            release.plan(self.root, "legacy-tools-v9.0.0")
        self.write("feature.txt", "not on main\n")
        self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            release.plan(self.root)

    def test_publication_creates_only_missing_tag_and_uses_verify_tag(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / self.policy["release_manifest"]).write_text(json.dumps({**self.policy, "source_commit": self.base, "source_dirty": False}))
        selected = {"release_tag": self.policy["release_tag"], "source_commit": self.base, "build": "true"}
        self.git("tag", self.policy["release_tag"])
        real_run = subprocess.run

        def execute(command, **options):
            if command[0] == "gh":
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **options)

        for existing in (None, {"object": {"sha": self.base}}):
            with self.subTest(existing=existing), patch.object(release, "plan", return_value=selected), patch.object(release, "api", side_effect=[existing, {}] if existing is None else [existing]) as api, patch.object(release.subprocess, "run", side_effect=execute) as run:
                release.publish(self.root, assets, self.base)
                mutations = [call for call in api.call_args_list if call.kwargs.get("data")]
                self.assertEqual(len(mutations), 1 if existing is None else 0)
                if mutations:
                    self.assertEqual(mutations[0].args[1], "git/refs")
                    self.assertEqual(mutations[0].kwargs["data"], {"ref": "refs/tags/legacy-tools-v0.3.0", "sha": self.base})
                command = run.call_args.args[0]
                self.assertIn("--verify-tag", command)
                self.assertNotIn("--clobber", command)

    def test_only_http_404_means_missing(self):
        for code in (403, 429, 500, 404):
            error = urllib.error.HTTPError("https://api.github.com/example", code, "fixture", {}, io.BytesIO())
            with patch.dict(os.environ, {"GH_TOKEN": "fixture-not-a-secret"}), patch.object(release.urllib.request, "urlopen", side_effect=error):
                if code == 404:
                    self.assertIsNone(release.api("owner/repo", "releases/tags/test", missing=True))
                else:
                    with self.assertRaisesRegex(ValueError, f"HTTP {code}"):
                        release.api("owner/repo", "releases/tags/test", missing=True)


if __name__ == "__main__":
    unittest.main()
