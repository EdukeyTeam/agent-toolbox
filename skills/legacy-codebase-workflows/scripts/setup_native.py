#!/usr/bin/env python3
"""Inspect or install the skill's pinned native package in a user cache.

No Rust builds, latest-release discovery, global PATH changes, signing bypasses,
security-policy changes, or mutable status in the installed skill. Releases and
explicit CI/local packages share the same verified distribution manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

POLICY_PATH = Path(__file__).resolve().parents[1] / "tool-distribution.json"
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 768 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
HASH = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
REQUIRED_NOTICES = ("LICENSE.txt", "NOTICE.txt", "NOTICES.txt", "THIRD_PARTY_RUST.md", "BUILD-INFO.json")


class SetupError(ValueError):
    pass


def _object(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
        raise SetupError(f"missing, unsafe, or oversized metadata: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SetupError(f"invalid metadata: {path.name}") from exc
    if not isinstance(value, dict):
        raise SetupError(f"metadata must be an object: {path.name}")
    return value


def load_policy(path=None):
    policy = _object(Path(path) if path is not None else POLICY_PATH)
    if policy.get("schema_version") != 1 or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", policy.get("repository", "")):
        raise SetupError("invalid distribution policy")
    for key in ("release_tag", "native_version", "source_contract", "release_manifest"):
        if not isinstance(policy.get(key), str) or not policy[key]:
            raise SetupError(f"missing distribution policy field: {key}")
    if not isinstance(policy.get("platforms"), dict):
        raise SetupError("distribution policy lacks platforms")
    _relative(policy["release_manifest"])
    if not re.fullmatch(r"legacy-tools-v[0-9]+\.[0-9]+\.[0-9]+", policy["release_tag"]):
        raise SetupError("distribution release tag must be an explicit pinned version")
    return policy


def detect_platform():
    system = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    return f"{system}-{machine}"


def _target(policy):
    tag = detect_platform()
    if tag not in policy["platforms"]:
        raise SetupError(f"unsupported execution platform {tag}; supported: {', '.join(sorted(policy['platforms']))}. Use the Python source workflow.")
    return tag, policy["platforms"][tag]


def _relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name):
        raise SetupError("unsafe package path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.rstrip("/").split("/")):
        raise SetupError(f"unsafe package path: {name!r}")
    if any(part.rstrip(" .") != part for part in path.parts):
        raise SetupError("package paths must be portable across supported platforms")
    return path


def _digest(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EXPANDED_BYTES:
        raise SetupError(f"unsafe or oversized package file: {path.name}")
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def extract_archive(archive, destination):
    """Validate every member before extracting; never follow archive links."""
    archive, destination = Path(archive), Path(destination)
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise SetupError("archive download size limit exceeded or unsafe archive")
    if zipfile.is_zipfile(archive):
        handle = zipfile.ZipFile(archive)
        members = [(entry.filename, entry.file_size, entry.is_dir(), (entry.external_attr >> 16), entry) for entry in handle.infolist()]
        kind = "zip"
    else:
        try:
            handle = tarfile.open(archive, "r:gz")
            members = []
            for entry in handle:
                if not entry.isdir() and not entry.isfile():
                    raise SetupError("archive symlinks, hardlinks, devices and special entries are forbidden")
                members.append((entry.name, entry.size, entry.isdir(), entry.mode, entry))
                if len(members) > MAX_ARCHIVE_ENTRIES:
                    raise SetupError("archive entry count limit exceeded")
        except SetupError:
            handle.close()
            raise
        except (tarfile.TarError, OSError) as exc:
            raise SetupError("not a supported ZIP or tar.gz archive") from exc
        kind = "tar"
    try:
        if len(members) > MAX_ARCHIVE_ENTRIES:
            raise SetupError("archive entry count limit exceeded")
        seen = set()
        expanded = 0
        for name, size, directory, mode, _entry in members:
            relative = _relative(name)
            identity = relative.as_posix().casefold()
            if identity in seen:
                raise SetupError("duplicate or case-colliding archive path")
            seen.add(identity)
            if kind == "zip" and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise SetupError("archive symlink or special entry is forbidden")
            if size < 0 or size > MAX_EXPANDED_BYTES:
                raise SetupError("archive member size limit exceeded")
            expanded += 0 if directory else size
            if expanded > MAX_EXPANDED_BYTES:
                raise SetupError("archive expanded size limit exceeded")
        ordinary_files = {_relative(name).as_posix().casefold() for name, _, directory, _, _ in members if not directory}
        for name, _, _, _, _ in members:
            if any(parent.as_posix().casefold() in ordinary_files for parent in _relative(name).parents if parent != PurePosixPath(".")):
                raise SetupError("archive file conflicts with a parent directory")
        if destination.is_symlink() or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
            raise SetupError("archive extraction needs a fresh ordinary directory")
        destination.mkdir(parents=True, exist_ok=True)
        for name, size, directory, mode, entry in members:
            target = destination.joinpath(*_relative(name).parts)
            if directory:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = handle.open(entry) if kind == "zip" else handle.extractfile(entry)
            if source is None:
                raise SetupError("archive member could not be read")
            actual = 0
            with source, target.open("xb") as output:
                while True:
                    block = source.read(min(1 << 20, size - actual + 1))
                    if not block:
                        break
                    actual += len(block)
                    if actual > size:
                        raise SetupError("archive member exceeds its declared size")
                    output.write(block)
            if actual != size:
                raise SetupError("archive member size mismatch")
            target.chmod(0o755 if mode & 0o111 else 0o644)
    finally:
        handle.close()


def _cache_root(cache_dir):
    if cache_dir is not None:
        root = Path(cache_dir).expanduser().resolve()
    elif platform.system().lower() == "windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "legacy-codebase-workflows"
    elif platform.system().lower() == "darwin":
        root = Path.home() / "Library/Caches/legacy-codebase-workflows"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "legacy-codebase-workflows"
    root = root.resolve()
    if root.is_relative_to(POLICY_PATH.parent.resolve()):
        raise SetupError("machine readiness/cache must live outside the installed skill")
    return root


def _destination(cache, policy, tag):
    destination = cache / "native" / policy["native_version"] / tag
    if not destination.resolve().is_relative_to(cache) or any(path.is_symlink() for path in (cache / "native", destination.parent, destination)):
        raise SetupError("native cache path must not follow symlinks outside its owned destination")
    return destination


def _probe_binary(binary, policy, *, smoke=False):
    try:
        completed = subprocess.run([str(binary), "--version"], capture_output=True, text=True, encoding="utf-8", timeout=15, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("native binary version probe failed; platform/security restrictions were not bypassed") from exc
    expected = f"legacy-repo-map {policy['native_version']} (experimental)"
    if completed.stdout.strip() != expected:
        raise SetupError(f"native version mismatch: expected {expected}")
    if smoke:
        with tempfile.TemporaryDirectory(prefix="legacy-native-smoke-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "Fixture.java").write_text("class Fixture { void render(String value) {} }\n", encoding="utf-8")
            output = root / "output"
            try:
                subprocess.run([str(binary), str(source), "--output-dir", str(output), "--budget", "256", "--format", "grouped", "--all-definitions"],
                               capture_output=True, timeout=30, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SetupError("native isolated map smoke failed; source package remains uninstalled") from exc
            metadata = _object(output / "map.meta.json")
            if metadata.get("status") != "complete" or metadata.get("baseline_contract") != policy["source_contract"] or metadata.get("rendering", {}).get("format") != "grouped" or metadata.get("coverage", {}).get("definitions_in_map") != 2:
                raise SetupError("native smoke/source contract mismatch")
            text = (output / "repo-map.md").read_text(encoding="utf-8")
            if "Fixture" not in text or "render(String value)" not in text or _digest(output / "repo-map.md") != metadata.get("map_sha256"):
                raise SetupError("native isolated map smoke produced invalid output")
    return {"version": policy["native_version"], "source_contract": policy["source_contract"]}


def _verify_files(package, files, program):
    if package.is_symlink() or not package.is_dir():
        raise SetupError("package root must be an ordinary directory")
    if not isinstance(files, dict) or not files or len(files) > MAX_ARCHIVE_ENTRIES:
        raise SetupError("manifest lacks bounded package file hashes")
    for name in (program, *REQUIRED_NOTICES):
        if name not in files:
            raise SetupError(f"manifest lacks required binary/license metadata: {name}")
    present = set()
    total = 0
    for path in package.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise SetupError("package links and special files are forbidden")
        if path.is_file():
            present.add(path.relative_to(package).as_posix())
            total += path.stat().st_size
    if present != set(files) or total > MAX_EXPANDED_BYTES:
        raise SetupError("package file inventory or expanded size differs from manifest")
    for name, digest in files.items():
        relative = _relative(name)
        if not isinstance(digest, str) or not HASH.fullmatch(digest) or _digest(package.joinpath(*relative.parts)) != digest:
            raise SetupError(f"package file hash mismatch: {name}")
    for name in REQUIRED_NOTICES:
        if not (package / name).read_bytes().strip():
            raise SetupError(f"required license/metadata file is empty: {name}")


def _validated_manifest(manifest, policy, tag, expected_source=None, *, ci=False):
    if manifest.get("schema_version") != 1:
        raise SetupError("unsupported release manifest schema")
    for key in ("repository", "release_tag", "native_version", "source_contract"):
        if manifest.get(key) != policy[key]:
            raise SetupError(f"distribution {key} mismatch; this skill requires {policy[key]}")
    if not isinstance(manifest.get("source_commit"), str) or not COMMIT.fullmatch(manifest["source_commit"]):
        raise SetupError("release manifest lacks a full source commit")
    if type(manifest.get("source_dirty")) is not bool or (ci and manifest["source_dirty"]):
        raise SetupError("CI/release manifest must identify a clean source revision")
    if expected_source is not None and manifest["source_commit"] != expected_source:
        raise SetupError("release/CI manifest source commit does not match --expected-source")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict):
        raise SetupError("release manifest lacks platform records")
    record = platforms.get(tag)
    if not isinstance(record, dict):
        raise SetupError("release manifest lacks this execution platform")
    for key in ("archive", "archive_root", "program"):
        if record.get(key) != policy["platforms"][tag][key]:
            raise SetupError(f"release platform {key} differs from the pinned distribution policy")
        _relative(record[key])
    if not isinstance(record.get("archive_sha256"), str) or not HASH.fullmatch(record["archive_sha256"]):
        raise SetupError("manifest lacks archive checksum")
    return record


def status(cache_dir=None, *, policy_path=None):
    policy = load_policy(policy_path)
    tag, target = _target(policy)
    cache = _cache_root(cache_dir)
    destination = _destination(cache, policy, tag)
    result = {"state": "needs-setup", "platform": tag, "version": policy["native_version"], "release_tag": policy["release_tag"],
              "cache_directory": str(destination), "publication": policy.get("publication"),
              "consumer_verified": target.get("consumer_verified", False),
              "setup_command": [sys.executable, str(Path(__file__).resolve()), "install", "--cache-dir", str(cache)]}
    try:
        receipt = _object(destination / "receipt.json")
        if receipt.get("source_kind") not in ("local", "ci", "release"):
            raise SetupError("receipt lacks a verified package source identity")
        _validated_manifest(receipt, policy, tag)
        record = receipt["platforms"][tag]
        package = destination / "package"
        _verify_files(package, record["files"], target["program"])
        _probe_binary(package / target["program"], policy)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["reason"] = str(exc)
        return result
    result.update(state="ready", program=str(package / target["program"]), source_kind=receipt["source_kind"],
                  source_commit=receipt["source_commit"], source_dirty=receipt["source_dirty"])
    result.pop("reason", None)
    return result


class _GithubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not (host in ("github.com", "api.github.com") or host.endswith(".githubusercontent.com")):
            raise SetupError("download redirect left HTTPS GitHub asset hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url, destination, *, limit=MAX_DOWNLOAD_BYTES):
    request = urllib.request.Request(url, headers={"User-Agent": "legacy-codebase-workflows-setup/1"})
    try:
        # Retain normal HTTPS validation and restrict redirects on this opener.
        opener = urllib.request.build_opener(_GithubRedirects())
        with opener.open(request, timeout=30) as response, destination.open("xb") as output:
            claimed = response.headers.get("Content-Length")
            if claimed is not None and int(claimed) > limit:
                raise SetupError("download size limit exceeded")
            size = 0
            while True:
                block = response.read(min(1 << 20, limit - size + 1))
                if not block:
                    break
                size += len(block)
                if size > limit:
                    raise SetupError("download size limit exceeded")
                output.write(block)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            raise SetupError("pinned release is not published or this asset is missing; no Rust build or latest-release fallback was attempted") from exc
        raise SetupError(f"GitHub release download failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SetupError("GitHub release download failed; verify network access and use an explicitly verified local package") from exc


def _gh_json(arguments):
    try:
        completed = subprocess.run(["gh", *arguments], capture_output=True, timeout=45, check=True,
                                   env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_DEBUG": ""})
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("authenticated GitHub CLI request failed; configure gh or use a verified local package") from exc
    if len(completed.stdout) > MAX_METADATA_BYTES:
        raise SetupError("GitHub CLI metadata size limit exceeded")
    try:
        return json.loads(completed.stdout)
    except ValueError as exc:
        raise SetupError("invalid GitHub CLI metadata") from exc


def _gh_artifact(artifact_id, repository, destination):
    with tempfile.TemporaryFile() as errors, destination.open("xb") as output:
        try:
            process = subprocess.Popen(["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"], stdout=subprocess.PIPE, stderr=errors,
                                       env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_DEBUG": ""})
        except OSError as exc:
            raise SetupError("GitHub CLI is unavailable") from exc
        timer = threading.Timer(120, process.kill)
        timer.start()
        size = 0
        try:
            while True:
                block = process.stdout.read(1 << 20)
                if not block:
                    break
                size += len(block)
                if size > MAX_DOWNLOAD_BYTES:
                    process.kill()
                    raise SetupError("CI artifact download size limit exceeded")
                output.write(block)
            if process.wait() != 0:
                raise SetupError("authenticated CI artifact download failed or timed out")
        finally:
            timer.cancel()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()


def _ci_source(run_id, expected_source, policy, tag, scratch):
    if not expected_source or not COMMIT.fullmatch(expected_source):
        raise SetupError("--from-ci requires --expected-source with the full reviewed 40-character commit SHA")
    if not re.fullmatch(r"[0-9]+", str(run_id)):
        raise SetupError("CI run ID must be numeric")
    run = _gh_json(["run", "view", str(run_id), "--repo", policy["repository"], "--json", "headSha,status,conclusion"])
    if not isinstance(run.get("headSha"), str) or not COMMIT.fullmatch(run["headSha"]) or run.get("status") != "completed" or run.get("conclusion") != "success":
        raise SetupError("CI run must be successful and identify its source head commit")
    listing = _gh_json(["api", f"repos/{policy['repository']}/actions/runs/{run_id}/artifacts?per_page=100"])
    matching = [item for item in listing.get("artifacts", []) if item.get("name") == policy["platforms"][tag]["ci_artifact"] and not item.get("expired")]
    if len(matching) != 1 or type(matching[0].get("id")) is not int or matching[0]["id"] <= 0 or type(matching[0].get("size_in_bytes")) is not int or not 0 <= matching[0]["size_in_bytes"] <= MAX_DOWNLOAD_BYTES:
        raise SetupError("matching CI artifact is missing, expired, ambiguous or oversized")
    archive = scratch / "ci-artifact.zip"
    _gh_artifact(matching[0]["id"], policy["repository"], archive)
    content = scratch / "ci-content"
    extract_archive(archive, content)
    return content, run["headSha"]


def install(*, cache_dir=None, local_package=None, manifest_path=None, from_ci=None, expected_source=None, replace=False, policy_path=None):
    if manifest_path is not None and local_package is None:
        raise SetupError("--manifest requires --local-package; CI and release installs use their fetched provenance index")
    policy = load_policy(policy_path)
    tag, target = _target(policy)
    cache = _cache_root(cache_dir)
    destination = _destination(cache, policy, tag)
    if local_package is not None and from_ci is not None:
        raise SetupError("choose only one package source")
    if expected_source is not None and not COMMIT.fullmatch(expected_source):
        raise SetupError("--expected-source must be a full 40-character commit SHA")
    if destination.exists() and not replace:
        current = status(cache, policy_path=policy_path)
        if current["state"] == "ready" and (expected_source is None or current["source_commit"] == expected_source):
            return current
        raise SetupError("existing cache destination has no verified matching identity; use --replace explicitly")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-setup-", dir=cache) as temporary:
        scratch = Path(temporary)
        source_kind = "local" if local_package is not None else "ci" if from_ci is not None else "release"
        if from_ci is not None:
            source, ci_head = _ci_source(from_ci, expected_source, policy, tag, scratch)
        elif local_package is not None:
            source = Path(local_package).expanduser().resolve(strict=True)
        else:
            base = f"https://github.com/{policy['repository']}/releases/download/{policy['release_tag']}"
            manifest_file = scratch / policy["release_manifest"]
            _download(base + "/" + policy["release_manifest"], manifest_file, limit=MAX_METADATA_BYTES)
            source = scratch
        if manifest_path is not None:
            manifest_file = Path(manifest_path).expanduser().resolve(strict=True)
        else:
            manifest_file = (source if source.is_dir() else source.parent) / policy["release_manifest"]
        manifest = _object(manifest_file)
        record = _validated_manifest(manifest, policy, tag, expected_source, ci=source_kind != "local")
        if source_kind == "ci" and (manifest.get("ci_run_head_commit") != ci_head or manifest.get("ci_run_id") != str(from_ci)):
            raise SetupError("CI index must bind the authenticated run ID/head commit separately from its reviewed build source commit")
        if source_kind == "release":
            archive = scratch / record["archive"]
            _download(base + "/" + record["archive"], archive)
        elif source.is_file():
            archive = source
        elif (source / "BUILD-INFO.json").is_file():
            archive = None
        else:
            archive = source / record["archive"]
        if archive is not None:
            if _digest(archive) != record["archive_sha256"]:
                raise SetupError("archive checksum mismatch")
            extracted = scratch / "extracted"
            extract_archive(archive, extracted)
            package = extracted / record["archive_root"]
            if {path.name for path in extracted.iterdir()} != {record["archive_root"]}:
                raise SetupError("archive contains unexpected package roots")
        else:
            package = source
        _verify_files(package, record["files"], target["program"])
        info = _object(package / "BUILD-INFO.json")
        if info.get("platform") != tag or info.get("program") != target["program"] or info.get("version") != f"legacy-repo-map {policy['native_version']} (experimental)":
            raise SetupError("package build metadata/platform/version mismatch")
        staged = scratch / "install"
        staged.mkdir()
        shutil.copytree(package, staged / "package", symlinks=False)
        _verify_files(staged / "package", record["files"], target["program"])
        binary = staged / "package" / target["program"]
        if os.name != "nt":
            binary.chmod(0o755)
        _probe_binary(binary, policy, smoke=True)
        receipt = {**manifest, "platforms": {tag: record}, "source_kind": source_kind, "ci_run": str(from_ci) if from_ci is not None else None}
        (staged / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _destination(cache, policy, tag)
        backup = destination.with_name(destination.name + ".backup-" + uuid.uuid4().hex)
        moved_old = False
        try:
            if destination.exists():
                if not replace:
                    raise SetupError("destination appeared concurrently; rerun with an explicit --replace")
                destination.rename(backup)
                moved_old = True
            staged.rename(destination)
        except BaseException:
            if moved_old and not destination.exists():
                backup.rename(destination)
            raise
        if moved_old:
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink()
    return status(cache, policy_path=policy_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "install"):
        command = commands.add_parser(name)
        command.add_argument("--cache-dir", type=Path, help="override the platform user cache; useful for isolated verification")
        command.add_argument("--policy", type=Path, dest="policy_path", help="explicit distribution policy for maintainers/tests")
        if name == "install":
            sources = command.add_mutually_exclusive_group()
            sources.add_argument("--local-package", type=Path, help="explicit verified artifact directory, native package directory, or archive")
            sources.add_argument("--from-ci", help="successful authenticated GitHub run; requires --expected-source and matching release manifest")
            command.add_argument("--manifest", type=Path, dest="manifest_path", help="separate release index; only supported with --local-package")
            command.add_argument("--expected-source", help="full reviewed source commit SHA; mandatory for CI")
            command.add_argument("--replace", action="store_true", help="explicitly replace this version/platform cache only after verification succeeds")
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        result = status(**args) if command == "status" else install(**args)
    except (SetupError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"state": "error", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
