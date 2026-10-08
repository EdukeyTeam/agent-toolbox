#!/usr/bin/env python3
"""Prepare a pinned native release index from reviewed local build outputs.

This prepares files only. It never creates a Git tag, invokes CI, or publishes.
Native binaries are smoked; the complete license tree is retained and hashed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "skills/legacy-codebase-workflows/scripts"))
import setup_native as setup


def prepare(packages, output_dir, source_commit, *, source_dirty=False, artifact_dirs=(), ci_run_head_commit=None, ci_run_id=None):
    policy = setup.load_policy()
    if not setup.COMMIT.fullmatch(source_commit):
        raise setup.SetupError("--source-commit must be a full reviewed 40-character Git commit SHA")
    output = Path(output_dir).resolve()
    if output.is_relative_to(REPO):
        raise setup.SetupError("release output must be outside the source checkout")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise setup.SetupError("release output directory must be empty")
    selected = [Path(package).resolve(strict=True) for package in packages]
    build_manifests = {}
    original_archives = {}
    for build_dir in artifact_dirs:
        directory = Path(build_dir).resolve(strict=True)
        manifest = setup._object(directory / "build-manifest.json")
        if manifest.get("smoke_skipped") is not False or not isinstance(manifest.get("smoke"), list) or not manifest["smoke"] or any(check.get("ok") is not True for check in manifest["smoke"]):
            raise setup.SetupError("build artifact manifest must show completed passing smoke checks")
        native = [entry for entry in manifest.get("artifacts", []) if entry.get("artifact", "").startswith("legacy-repo-map-")]
        if len(native) != 1:
            raise setup.SetupError("build artifact manifest needs one native package")
        tag = native[0].get("platform")
        if tag not in policy["platforms"] or native[0]["artifact"] != policy["platforms"][tag]["archive_root"]:
            raise setup.SetupError("build manifest native package path/platform differs from policy")
        selected.append(directory / native[0]["artifact"])
        original_archives[tag] = directory / policy["platforms"][tag]["archive"]
        build_manifests[tag] = manifest
    if not selected:
        raise setup.SetupError("provide --package-dir or --artifact-dir")
    release = {"schema_version": 1, "repository": policy["repository"], "release_tag": policy["release_tag"],
               "native_version": policy["native_version"], "source_contract": policy["source_contract"],
               "source_commit": source_commit, "source_dirty": source_dirty, "platforms": {}}
    if ci_run_head_commit is not None or ci_run_id is not None:
        if source_dirty or not isinstance(ci_run_head_commit, str) or not setup.COMMIT.fullmatch(ci_run_head_commit) or not isinstance(ci_run_id, str) or not ci_run_id.isdecimal():
            raise setup.SetupError("CI provenance needs a clean build plus full run head commit and numeric run ID")
        release.update(ci_run_head_commit=ci_run_head_commit, ci_run_id=ci_run_id)
    prepared = []
    for package in selected:
        info = setup._object(package / "BUILD-INFO.json")
        tag = info.get("platform")
        if tag not in policy["platforms"] or tag in release["platforms"]:
            raise setup.SetupError("unsupported or duplicate native package platform")
        target = policy["platforms"][tag]
        if package.name != target["archive_root"] or info.get("program") != target["program"] or info.get("version") != f"legacy-repo-map {policy['native_version']} (experimental)":
            raise setup.SetupError("native package/version differs from the pinned distribution policy")
        files = {path.relative_to(package).as_posix(): setup._digest(path) for path in package.rglob("*") if path.is_file()}
        setup._verify_files(package, files, target["program"])
        if setup.detect_platform() != tag:
            raise setup.SetupError("prepare each package on its executing platform, then aggregate the verified indexes")
        setup._probe_binary(package / target["program"], policy, smoke=True)
        release["platforms"][tag] = {**{key: target[key] for key in ("archive", "archive_root", "program")}, "files": files}
        prepared.append((tag, package))
    output.mkdir(parents=True, exist_ok=True)
    for tag, package in prepared:
        record = release["platforms"][tag]
        archive = output / record["archive"]
        if archive.exists():
            raise setup.SetupError("release output already exists; use a new directory")
        if tag in original_archives:
            shutil.copy2(original_archives[tag], archive)
        elif archive.suffix == ".zip":
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as handle:
                for path in sorted(package.rglob("*")):
                    handle.write(path, Path(package.name) / path.relative_to(package))
        else:
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(package, arcname=package.name)
        with tempfile.TemporaryDirectory(prefix="legacy-release-archive-") as temporary:
            extracted = Path(temporary) / "extracted"
            setup.extract_archive(archive, extracted)
            if {path.name for path in extracted.iterdir()} != {record["archive_root"]}:
                raise setup.SetupError("native archive has unexpected package roots")
            setup._verify_files(extracted / record["archive_root"], record["files"], record["program"])
        record["archive_sha256"] = setup._digest(archive)
        if tag in build_manifests:
            name = f"build-manifest.{tag}.json"
            enriched = {**build_manifests[tag], "distribution_source_commit": source_commit, "distribution_source_dirty": source_dirty}
            (output / name).write_text(json.dumps(enriched, indent=2) + "\n", encoding="utf-8")
            record["build_manifest_asset"] = name
    (output / policy["release_manifest"]).write_text(json.dumps(release, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    sums = [f"{record['archive_sha256']}  {record['archive']}\n" for _, record in sorted(release["platforms"].items())]
    (output / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    return release


def aggregate(index_dirs, output_dir, *, require_all=False):
    policy = setup.load_policy()
    output = Path(output_dir).resolve()
    if output.is_relative_to(REPO):
        raise setup.SetupError("release output must be outside source")
    combined = None
    sources = []
    for root in index_dirs:
        root = Path(root).resolve(strict=True)
        manifest = setup._object(root / policy["release_manifest"])
        if not manifest.get("platforms"):
            raise setup.SetupError("empty platform release index")
        for tag in manifest["platforms"]:
            record = setup._validated_manifest(manifest, policy, tag, ci=True)
            if combined is None:
                combined = {**manifest, "platforms": {}}
            if manifest["source_commit"] != combined["source_commit"] or tag in combined["platforms"]:
                raise setup.SetupError("platform release indexes disagree on source or duplicate a platform")
            if setup._digest(root / record["archive"]) != record["archive_sha256"]:
                raise setup.SetupError("platform archive checksum mismatch")
            combined["platforms"][tag] = record
            sources.append((root, record))
    if combined is None or (require_all and set(combined["platforms"]) != set(policy["platforms"])):
        raise setup.SetupError("release aggregation lacks required platform indexes")
    if output.exists() and any(output.iterdir()):
        raise setup.SetupError("aggregate output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    for root, record in sources:
        shutil.copy2(root / record["archive"], output / record["archive"])
        if record.get("build_manifest_asset"):
            name = record["build_manifest_asset"]
            setup._relative(name)
            shutil.copy2(root / name, output / name)
    (output / policy["release_manifest"]).write_text(json.dumps(combined, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS").write_text("".join(f"{record['archive_sha256']}  {record['archive']}\n" for _, record in sorted(combined["platforms"].items())), encoding="utf-8")
    return combined


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("--package-dir", type=Path, action="append", default=[])
    create.add_argument("--artifact-dir", type=Path, action="append", default=[])
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--ci-run-head-commit", help="workflow run head commit; PR merge build source remains --source-commit")
    create.add_argument("--ci-run-id", help="workflow run ID bound to the run head and checked-out build source")
    create.add_argument("--source-dirty", action="store_true", help="explicit local working-copy evidence; dirty indexes cannot become releases/CI installs")
    merge = commands.add_parser("aggregate")
    merge.add_argument("--index-dir", type=Path, action="append", required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge.add_argument("--require-all", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            manifest = prepare(args.package_dir, args.output_dir, args.source_commit, source_dirty=args.source_dirty, artifact_dirs=args.artifact_dir, ci_run_head_commit=args.ci_run_head_commit, ci_run_id=args.ci_run_id)
        else:
            manifest = aggregate(args.index_dir, args.output_dir, require_all=args.require_all)
    except (setup.SetupError, OSError, ValueError, KeyError) as exc:
        print(f"create-legacy-release-manifest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"release_tag": manifest["release_tag"], "source_commit": manifest["source_commit"], "platforms": sorted(manifest["platforms"]), "output_dir": str(args.output_dir.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
