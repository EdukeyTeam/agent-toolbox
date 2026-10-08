"""Offline behavior checks for the pinned native installer and its cache."""

import contextlib
import copy
import hashlib
import shutil
import importlib.util
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/legacy-codebase-workflows/scripts"
sys.path.insert(0, str(SCRIPTS))
import setup_native as setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.cache = self.base / "cache"
        self.artifacts = self.base / "artifacts"
        self.artifacts.mkdir()
        self.policy = setup.load_policy()
        self.platform = "linux-x86_64"
        self.package = self.artifacts / "legacy-repo-map-linux-x86_64"
        self.package.mkdir()
        self.binary = self.package / "legacy-repo-map"
        self.binary.write_bytes(b"FAKE NATIVE BINARY FOR OFFLINE FIXTURE")
        for name in ("LICENSE.txt", "NOTICE.txt", "NOTICES.txt", "THIRD_PARTY_RUST.md"):
            (self.package / name).write_text("fixture license/notice text", encoding="utf-8")
        self.info = {"platform": self.platform, "artifact": self.package.name, "program": "legacy-repo-map",
                     "version": "legacy-repo-map 0.2.0 (experimental)"}
        (self.package / "BUILD-INFO.json").write_text(json.dumps(self.info))
        self.manifest = {"schema_version": 1, "repository": self.policy["repository"], "release_tag": self.policy["release_tag"],
                         "native_version": "0.2.0", "source_contract": "repo_map.py 1.1.0", "source_commit": "a" * 40,
                         "source_dirty": False, "platforms": {}}
        self.refresh()
        self.real_detect = setup.detect_platform
        self.detect = patch.object(setup, "detect_platform", return_value=self.platform)
        self.detect.start()
        self.addCleanup(self.detect.stop)
        self.probe = patch.object(setup, "_probe_binary", return_value={"version": "0.2.0", "source_contract": "repo_map.py 1.1.0"})
        self.mock_probe = self.probe.start()
        self.addCleanup(self.probe.stop)

    def refresh(self):
        files = {path.relative_to(self.package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in self.package.rglob("*") if path.is_file()}
        archive = self.artifacts / "legacy-repo-map-linux-x86_64.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(self.package, arcname=self.package.name)
        self.manifest["platforms"][self.platform] = {
            "archive": archive.name, "archive_root": self.package.name, "program": "legacy-repo-map",
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": files,
        }
        (self.artifacts / "legacy-tools-release.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        return archive

    def install(self, **options):
        return setup.install(cache_dir=self.cache, local_package=self.artifacts, **options)

    def forged_override(self):
        forged = copy.deepcopy(self.manifest)
        forged.update(source_commit="f" * 40, ci_run_head_commit="b" * 40, ci_run_id="42")
        override = self.base / "unauthenticated-override.json"
        override.write_text(json.dumps(forged), encoding="utf-8")
        return override

    def test_ci_manifest_override_cannot_forge_source_identity_with_matching_archive(self):
        override = self.forged_override()
        self.manifest.update(ci_run_head_commit="b" * 40, ci_run_id="42")
        self.refresh()
        with patch.object(setup, "_ci_source", return_value=(self.artifacts, "b" * 40)) as fetched:
            with self.assertRaisesRegex(setup.SetupError, "manifest.*local-package", msg="A caller override must not publish ready for a forged source SHA"):
                setup.install(cache_dir=self.cache, from_ci="42", expected_source="f" * 40, manifest_path=override)
        fetched.assert_not_called()
        self.mock_probe.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_release_manifest_override_rejected_before_download_or_cache_creation(self):
        override = self.forged_override()
        def authentic_download(url, destination, **options):
            shutil.copyfile(self.artifacts / url.rsplit("/", 1)[-1], destination)
        with patch.object(setup, "_download", side_effect=authentic_download) as fetched:
            with self.assertRaisesRegex(setup.SetupError, "manifest.*local-package", msg="A local override must not replace the pinned release source identity"):
                setup.install(cache_dir=self.cache, expected_source="f" * 40, manifest_path=override)
        fetched.assert_not_called()
        self.mock_probe.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_invalid_manifest_source_preserves_existing_verified_cache(self):
        installed = self.install()
        destination = Path(installed["cache_directory"])
        before = {p.relative_to(destination).as_posix(): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
        override = self.forged_override()
        self.mock_probe.reset_mock()
        with patch.object(setup, "_ci_source") as ci, patch.object(setup, "_download") as release:
            for options in ({"from_ci": "42", "replace": True, "expected_source": "f" * 40},
                            {"replace": True, "expected_source": "f" * 40},
                            {"expected_source": "a" * 40}):
                with self.subTest(options=options), self.assertRaisesRegex(setup.SetupError, "manifest.*local-package"):
                    setup.install(cache_dir=self.cache, manifest_path=override, **options)
            ci.assert_not_called()
            release.assert_not_called()
        self.mock_probe.assert_not_called()
        after = {p.relative_to(destination).as_posix(): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(setup.status(cache_dir=self.cache)["source_commit"], "a" * 40)

    def test_local_archive_with_separate_manifest_remains_supported(self):
        archive = self.refresh()
        separate = self.base / "separate-reviewed-local-index.json"
        separate.write_text(json.dumps(self.manifest), encoding="utf-8")
        with patch.object(setup, "_download") as release, patch.object(setup, "_ci_source") as ci:
            installed = setup.install(cache_dir=self.cache, local_package=archive, manifest_path=separate, expected_source="a" * 40)
            release.assert_not_called()
            ci.assert_not_called()
        self.assertEqual(installed["state"], "ready")
        self.assertEqual(installed["source_commit"], "a" * 40)
        self.assertEqual(installed["source_kind"], "local")

    def test_cli_manifest_without_local_package_reports_error_before_fetch(self):
        override = self.forged_override()
        output = io.StringIO()
        with patch.object(setup, "_download") as release, patch.object(setup, "_ci_source") as ci, contextlib.redirect_stdout(output):
            result = setup.main(["install", "--cache-dir", str(self.cache), "--manifest", str(override)])
        self.assertEqual(result, 2)
        response = json.loads(output.getvalue())
        self.assertEqual(response["state"], "error")
        self.assertIn("--local-package", response["reason"])
        release.assert_not_called()
        ci.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_platform_normalization_uses_executing_os_not_wsl_host(self):
        for system, machine, expected in (("Windows", "AMD64", "windows-x86_64"), ("Linux", "x86_64", "linux-x86_64"),
                                          ("Darwin", "arm64", "macos-arm64"), ("Linux", "aarch64", "linux-arm64")):
            with self.subTest(system=system, machine=machine):
                with patch.object(setup.platform, "system", return_value=system), patch.object(setup.platform, "machine", return_value=machine):
                    self.assertEqual(self.real_detect(), expected)

    def test_status_before_setup_reports_explicit_pinned_install_location(self):
        result = setup.status(cache_dir=self.cache)
        self.assertEqual(result["state"], "needs-setup")
        self.assertEqual(result["release_tag"], "legacy-tools-v0.2.0")
        self.assertIn("install", result["setup_command"])
        self.assertFalse(self.cache.exists())
        self.mock_probe.assert_not_called()

    def test_local_install_preserves_licenses_and_revalidates_hash_and_version(self):
        result = self.install()
        self.assertEqual(result["state"], "ready")
        program = Path(result["program"])
        self.assertEqual(program.read_bytes(), self.binary.read_bytes())
        self.assertEqual((program.parent / "NOTICES.txt").read_bytes(), (self.package / "NOTICES.txt").read_bytes())
        receipt = json.loads((program.parent.parent / "receipt.json").read_text())
        self.assertEqual(receipt["source_commit"], "a" * 40)
        self.assertEqual(receipt["source_kind"], "local")
        self.assertEqual(receipt["native_version"], "0.2.0")
        self.assertEqual(setup.status(cache_dir=self.cache)["state"], "ready")
        self.assertGreaterEqual(self.mock_probe.call_count, 2)
        calls = self.mock_probe.call_count
        program.write_bytes(b"tampered")
        stale = setup.status(cache_dir=self.cache)
        self.assertEqual(stale["state"], "needs-setup")
        self.assertIn("hash", stale["reason"])
        self.assertEqual(self.mock_probe.call_count, calls)

    def test_stale_receipt_and_wrong_version_never_claim_ready(self):
        result = self.install()
        receipt_file = Path(result["program"]).parent.parent / "receipt.json"
        receipt = json.loads(receipt_file.read_text())
        receipt["source_contract"] = "repo_map.py 1.0.0"
        receipt_file.write_text(json.dumps(receipt))
        self.assertEqual(setup.status(cache_dir=self.cache)["state"], "needs-setup")
        receipt["source_contract"] = "repo_map.py 1.1.0"
        receipt_file.write_text(json.dumps(receipt))
        self.mock_probe.side_effect = setup.SetupError("native version mismatch")
        self.assertEqual(setup.status(cache_dir=self.cache)["state"], "needs-setup")

    def test_existing_unknown_destination_refused_without_replace(self):
        destination = self.cache / "native/0.2.0/linux-x86_64"
        destination.mkdir(parents=True)
        marker = destination / "unrelated.txt"
        marker.write_text("keep me")
        with self.assertRaisesRegex(setup.SetupError, "replace|existing"):
            self.install()
        self.assertEqual(marker.read_text(), "keep me")
        self.assertEqual(self.install(replace=True)["state"], "ready")

    def test_failed_reinstall_preserves_existing_receipt_and_binary(self):
        result = self.install()
        directory = Path(result["program"]).parent.parent
        before = {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        self.mock_probe.side_effect = setup.SetupError("injected smoke failure")
        with self.assertRaisesRegex(setup.SetupError, "smoke failure"):
            self.install(replace=True)
        self.assertEqual(before, {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()})

    def test_archive_checksum_mismatch_prevents_execution(self):
        archive = self.refresh()
        archive.write_bytes(archive.read_bytes() + b"tamper")
        with self.assertRaisesRegex(setup.SetupError, "checksum|hash"):
            self.install()
        self.mock_probe.assert_not_called()
        self.assertFalse((self.cache / "native/0.2.0/linux-x86_64/receipt.json").exists())

    def test_manifest_source_contract_and_old_ci_version_rejected(self):
        self.manifest["native_version"] = "0.1.0"
        (self.artifacts / "legacy-tools-release.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(setup.SetupError, "version"):
            self.install()
        self.manifest["native_version"] = "0.2.0"
        self.manifest["source_contract"] = "repo_map.py 1.0.0"
        (self.artifacts / "legacy-tools-release.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(setup.SetupError, "contract"):
            self.install()
        self.mock_probe.assert_not_called()

    def test_zip_traversal_symlink_and_duplicate_members_rejected(self):
        for scenario in ("traversal", "symlink", "duplicate"):
            with self.subTest(scenario=scenario):
                archive = self.base / (scenario + ".zip")
                with zipfile.ZipFile(archive, "w") as handle:
                    if scenario == "traversal":
                        handle.writestr("../escape", "bad")
                    elif scenario == "symlink":
                        entry = zipfile.ZipInfo("link")
                        entry.create_system = 3
                        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                        handle.writestr(entry, "../escape")
                    else:
                        handle.writestr("duplicate", "first")
                        handle.writestr("./duplicate", "second")
                with self.assertRaises(setup.SetupError):
                    setup.extract_archive(archive, self.base / (scenario + "-output"))
                self.assertFalse((self.base / "escape").exists())

    def test_tar_symlink_hardlink_and_traversal_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.REGTYPE):
            with self.subTest(kind=kind):
                archive = self.base / "malicious.tar.gz"
                entry = tarfile.TarInfo("../escape" if kind == tarfile.REGTYPE else "link")
                entry.type = kind
                entry.linkname = "../escape"
                with tarfile.open(archive, "w:gz") as handle:
                    handle.addfile(entry, io.BytesIO(b""))
                with self.assertRaises(setup.SetupError):
                    setup.extract_archive(archive, self.base / "tar-output")
                self.assertFalse((self.base / "escape").exists())

    def test_archive_expansion_limit_is_enforced_before_writing(self):
        archive = self.base / "oversize.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("large", b"x" * 100)
        with patch.object(setup, "MAX_EXPANDED_BYTES", 50):
            with self.assertRaisesRegex(setup.SetupError, "size|expanded|limit"):
                setup.extract_archive(archive, self.base / "oversize-output")
        self.assertFalse((self.base / "oversize-output/large").exists())

    def test_unpublished_release_error_is_clear_and_does_not_change_policy(self):
        before = (SCRIPTS.parent / "tool-distribution.json").read_bytes()
        error = urllib.error.HTTPError("https://github.com/example", 404, "missing", {}, None)
        with patch.object(setup.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(setup.SetupError, "not published|unpublished"):
                setup.install(cache_dir=self.cache)
        self.assertEqual(before, (SCRIPTS.parent / "tool-distribution.json").read_bytes())
        self.mock_probe.assert_not_called()

    def test_ci_requires_successful_run_and_exact_expected_source(self):
        with self.assertRaisesRegex(setup.SetupError, "expected-source"):
            setup.install(cache_dir=self.cache, from_ci="37633697013")
        with patch.object(setup, "_gh_json", return_value={"headSha": "b" * 40, "status": "completed", "conclusion": "failure"}):
            with self.assertRaisesRegex(setup.SetupError, "source|commit"):
                setup.install(cache_dir=self.cache, from_ci="37633697013", expected_source="a" * 40)
        self.mock_probe.assert_not_called()

    def test_matching_ci_index_installs_only_current_compatible_native_binary(self):
        self.manifest.update(ci_run_head_commit="b" * 40, ci_run_id="123")
        archive = self.refresh()
        outer = self.base / "ci.zip"
        with zipfile.ZipFile(outer, "w") as handle:
            handle.write(archive, archive.name)
            handle.write(self.artifacts / "legacy-tools-release.json", "legacy-tools-release.json")
        # PR run head differs from the checked-out merge commit recorded as source_commit.
        run = {"headSha": "b" * 40, "status": "completed", "conclusion": "success"}
        listing = {"artifacts": [{"id": 42, "name": self.policy["platforms"][self.platform]["ci_artifact"], "expired": False, "size_in_bytes": outer.stat().st_size}]}

        def download(_identifier, _repository, destination):
            destination.write_bytes(outer.read_bytes())

        with patch.object(setup, "_gh_json", side_effect=[run, listing]), patch.object(setup, "_gh_artifact", side_effect=download):
            result = setup.install(cache_dir=self.cache, from_ci="123", expected_source="a" * 40)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["version"], "0.2.0")
        self.assertEqual(result["source_kind"], "ci")
        self.assertEqual(result["source_commit"], "a" * 40)

    def test_https_download_stream_is_bounded_and_never_falls_back(self):
        class Response:
            headers = {"Content-Length": "100"}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        with patch.object(setup.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaisesRegex(setup.SetupError, "size limit"):
                setup._download("https://github.com/example", self.base / "download", limit=10)
        self.mock_probe.assert_not_called()

    def test_replacement_publication_failure_restores_previous_installation(self):
        result = self.install()
        directory = Path(result["program"]).parent.parent
        before = {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        real_rename = Path.rename

        def interrupt(path, target):
            if path.name == "install":
                raise OSError("injected publication failure")
            return real_rename(path, target)

        with patch.object(Path, "rename", autospec=True, side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "publication"):
                self.install(replace=True)
        self.assertEqual(before, {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()})

    def release_helper(self):
        path = SCRIPTS.parents[2] / "scripts/create-legacy-release-manifest.py"
        specification = importlib.util.spec_from_file_location("legacy_release_manifest_fixture", path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    def test_release_helper_indexes_original_ci_archive_bytes_and_all_licenses(self):
        helper = self.release_helper()
        original_archive = self.refresh()
        build = {"platform": self.platform, "artifacts": [self.info], "smoke_skipped": False,
                 "smoke": [{"name": "fixture-only build smoke", "ok": True}]}
        (self.artifacts / "build-manifest.json").write_text(json.dumps(build))
        output = self.base / "release-index"
        manifest = helper.prepare([], output, "a" * 40, artifact_dirs=[self.artifacts], ci_run_head_commit="b" * 40, ci_run_id="123")
        record = manifest["platforms"][self.platform]
        self.assertEqual((output / record["archive"]).read_bytes(), original_archive.read_bytes())
        self.assertEqual(record["archive_sha256"], hashlib.sha256(original_archive.read_bytes()).hexdigest())
        self.assertIn("NOTICES.txt", record["files"])
        self.assertEqual(manifest["ci_run_head_commit"], "b" * 40)
        self.assertEqual(manifest["source_commit"], "a" * 40)
        self.assertEqual(setup.install(cache_dir=self.cache, local_package=output)["state"], "ready")

    def test_release_aggregation_requires_all_platforms_and_clean_source(self):
        helper = self.release_helper()
        index = self.base / "single-platform"
        helper.prepare([self.package], index, "a" * 40)
        with self.assertRaisesRegex(setup.SetupError, "platform"):
            helper.aggregate([index], self.base / "missing-platforms", require_all=True)
        self.assertFalse((self.base / "missing-platforms").exists())
        dirty = self.base / "dirty-platform"
        helper.prepare([self.package], dirty, "a" * 40, source_dirty=True)
        with self.assertRaisesRegex(setup.SetupError, "clean"):
            helper.aggregate([dirty], self.base / "dirty-release")
        self.assertFalse((self.base / "dirty-release").exists())

    def test_ci_index_cannot_substitute_a_different_run_identity(self):
        self.manifest.update(ci_run_head_commit="c" * 40, ci_run_id="123")
        archive = self.refresh()
        outer = self.base / "wrong-ci.zip"
        with zipfile.ZipFile(outer, "w") as handle:
            handle.write(archive, archive.name)
            handle.write(self.artifacts / "legacy-tools-release.json", "legacy-tools-release.json")
        run = {"headSha": "b" * 40, "status": "completed", "conclusion": "success"}
        listing = {"artifacts": [{"id": 42, "name": self.policy["platforms"][self.platform]["ci_artifact"], "expired": False, "size_in_bytes": outer.stat().st_size}]}
        with patch.object(setup, "_gh_json", side_effect=[run, listing]), \
             patch.object(setup, "_gh_artifact", side_effect=lambda _id, _repo, destination: destination.write_bytes(outer.read_bytes())):
            with self.assertRaisesRegex(setup.SetupError, "run ID/head"):
                setup.install(cache_dir=self.cache, from_ci="123", expected_source="a" * 40)
        self.mock_probe.assert_not_called()

    def test_unsupported_platform_fails_without_creating_cache(self):
        with patch.object(setup, "detect_platform", return_value="linux-arm64"):
            with self.assertRaisesRegex(setup.SetupError, "unsupported"):
                self.install()
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
