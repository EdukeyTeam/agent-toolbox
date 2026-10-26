#!/usr/bin/env python3
"""Plan or publish an immutable pinned release. Mutations are CI/main-only."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

spec = importlib.util.spec_from_file_location("release_check", Path(__file__).with_name("check-legacy-release.py"))
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
ROOT = contract.ROOT


def api(repository, endpoint, *, data=None, missing=False):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{endpoint}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                 "Accept": "application/vnd.github+json", "User-Agent": "legacy-tools-release",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        if missing and code == 404:
            return None
        raise ValueError(f"GitHub {endpoint} failed with HTTP {code}; refusing to assume absence") from exc


def main_source(root, source):
    # Full history is fetched. Do not accept feature-branch/tag dispatches.
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_EVENT_NAME") not in ("push", "workflow_dispatch"):
        raise ValueError("publication is only allowed from a main push or main workflow_dispatch")
    sha = contract.git(root, "rev-parse", f"{source}^{{commit}}")
    subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=root, check=True)
    return sha


def tag_source(root, tag, remote):
    local_object = contract.git(root, "rev-parse", f"refs/tags/{tag}")
    if remote["object"]["sha"] != local_object:
        raise ValueError("remote tag changed since checkout; refusing stale tag identity, rerun with freshly fetched tags")
    return main_source(root, f"refs/tags/{tag}")


def plan(root=ROOT, requested=""):
    policy = contract.validate(root)
    if requested and requested != policy["release_tag"]:
        raise ValueError("requested release_tag must match the checked-in distribution policy")
    if policy["repository"] != os.environ["GITHUB_REPOSITORY"]:
        raise ValueError("distribution repository does not match this workflow repository")
    source = main_source(root, "HEAD")
    repository, tag = policy["repository"], policy["release_tag"]
    release = api(repository, f"releases/tags/{tag}", missing=True)
    if release is not None:
        if release.get("draft") or release.get("prerelease"):
            raise ValueError("an existing draft/prerelease occupies this tag; inspect it for recovery, never overwrite")
        required = {policy["release_manifest"], "SHA256SUMS", *(item["archive"] for item in policy["platforms"].values())}
        available = {asset["name"] for asset in release.get("assets", []) if asset.get("state") == "uploaded"}
        if not required <= available:
            raise ValueError("existing published release lacks required assets; never overwrite it, inspect recovery or bump the version")
        return {"release_tag": tag, "source_commit": source, "build": "false", "reason": "release already published; unchanged"}
    existing = api(repository, f"git/ref/tags/{tag}", missing=True)
    if existing is not None:
        # Peel annotated tags locally; checkout fetched all tag objects.
        source = tag_source(root, tag, existing)
        contract.validate(root, source)
        if contract.changed_inputs(root, source, "HEAD"):
            raise ValueError("existing tag has different release inputs; never move it, bump the pinned version")
    return {"release_tag": tag, "source_commit": source, "build": "true", "reason": "pinned release is missing"}


def publish(root, assets, source):
    selected = plan(root)
    if selected["build"] == "false":
        return selected
    if selected["source_commit"] != source:
        raise ValueError("release source changed after planning; refusing to publish")
    policy = contract.validate(root)
    manifest = json.loads((assets / policy["release_manifest"]).read_text())
    for key in ("repository", "release_tag", "native_version", "source_contract"):
        if manifest[key] != policy[key]:
            raise ValueError(f"aggregated release {key} differs from checked-in policy")
    if manifest["source_commit"] != source or manifest["source_dirty"] is not False or set(manifest["platforms"]) != set(policy["platforms"]):
        raise ValueError("aggregated release lacks clean source/all-platform provenance")
    tag, repository = policy["release_tag"], policy["repository"]
    existing = api(repository, f"git/ref/tags/{tag}", missing=True)
    if existing is None:
        # POST creates only. There is deliberately no PATCH, force or delete.
        api(repository, "git/refs", data={"ref": f"refs/tags/{tag}", "sha": source})
    elif tag_source(root, tag, existing) != source:
        raise ValueError("existing tag no longer identifies the verified source; refusing to publish")
    notes = assets.parent / "legacy-release-notes.md"
    notes.write_text(f"Native repository mapper {policy['native_version']} for legacy-codebase-workflows.\n\nSource: {source}\n\nAll three platform packages retain licenses and verified checksums/source manifests.\n", encoding="utf-8")
    subprocess.run(["gh", "release", "create", tag, "--repo", repository, "--verify-tag", "--target", source,
                    "--title", tag, "--notes-file", str(notes), *map(str, sorted(assets.iterdir()))], cwd=root, check=True)
    return {**selected, "reason": "published"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "publish"))
    parser.add_argument("--requested-tag", default="")
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--source")
    args = parser.parse_args()
    try:
        if args.command == "publish":
            if not args.assets or not args.source:
                raise ValueError("publish requires --assets and --source")
            result = publish(ROOT, args.assets, args.source)
        else:
            result = plan(requested=args.requested_tag)
        print(json.dumps(result, sort_keys=True))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                for key in ("release_tag", "source_commit", "build"):
                    output.write(f"{key}={result[key]}\n")
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"legacy-release: {exc}\n")


if __name__ == "__main__":
    main()
