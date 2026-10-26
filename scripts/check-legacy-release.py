#!/usr/bin/env python3
"""Fast, offline validation of native release pins and versioned inputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = "skills/legacy-codebase-workflows/"
CRATE = "src/legacy-repo-map/"
POLICY = SKILL + "tool-distribution.json"
# Native payload, Python reference, staged bundle resources and packaging.
# Cover directories rather than only today's helpers: the shared builder stages
# every top-level Python script and retrieval resource, and the index helper
# imports setup_native. Tests and workflow orchestration are outside this set.
INPUT_FILES = {
    POLICY, "LICENSE", ".gitattributes", "scripts/build-legacy-tools.py",
    "scripts/create-legacy-release-manifest.py", SKILL + "requirements-map.txt",
    SKILL + "THIRD_PARTY.md", SKILL + "LICENSE.txt", SKILL + "NOTICE.txt",
}


def covered(path):
    return (path in INPUT_FILES or path.startswith(SKILL + "vendor/")
            or path.startswith(SKILL + "scripts/")
            or (path.startswith(CRATE) and path != CRATE + "README.md"))


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def read(root, path, ref=None):
    if ref is None:
        return (Path(root) / path).read_text(encoding="utf-8")
    return git(root, "show", f"{ref}:{path}")


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError(f"expected a three-part release version, got {value!r}")
    return tuple(map(int, value.split(".")))


def validate(root=ROOT, ref=None):
    policy = json.loads(read(root, POLICY, ref))
    native = policy["native_version"]
    version(native)
    cargo = tomllib.loads(read(root, CRATE + "Cargo.toml", ref))
    lock = tomllib.loads(read(root, CRATE + "Cargo.lock", ref))
    locked = [p["version"] for p in lock["package"] if p["name"] == "legacy-repo-map"]
    if cargo["package"]["version"] != native or locked != [native] or policy["release_tag"] != f"legacy-tools-v{native}":
        raise ValueError("Cargo.toml, Cargo.lock and distribution native_version/release_tag must agree")
    rust = re.search(r'const BASELINE_CONTRACT: &str = "([^"]+)";', read(root, CRATE + "src/main.rs", ref))
    python = re.search(r'^VERSION = "([^"]+)"', read(root, SKILL + "scripts/repo_map.py", ref), re.M)
    if not rust or not python or policy["source_contract"] != rust[1] or rust[1] != f"repo_map.py {python[1]}":
        raise ValueError("distribution source_contract, Rust BASELINE_CONTRACT and Python VERSION must agree")
    for path in ("SKILL.md", "references/distribution.md", "references/setup.md"):
        text = read(root, SKILL + path, ref)
        if any(tag != policy["release_tag"] for tag in re.findall(r"legacy-tools-v[0-9]+\.[0-9]+\.[0-9]+", text)):
            raise ValueError(f"release tag in {path} disagrees with distribution policy")
        for contract in re.findall(r"repo_map\.py [0-9]+\.[0-9]+\.[0-9]+", text):
            if contract != policy["source_contract"]:
                raise ValueError(f"reference contract in {path} disagrees with distribution policy")
        for pinned in re.findall(r"native version ([0-9]+\.[0-9]+\.[0-9]+)", text):
            if pinned != native:
                raise ValueError(f"native version in {path} disagrees with distribution policy")
    tooling = read(root, SKILL + "references/native-tooling.md", ref)
    if any(pinned != native for pinned in re.findall(r"current ([0-9]+\.[0-9]+\.[0-9]+) package", tooling)):
        raise ValueError("current package in native-tooling.md disagrees with distribution policy")
    return policy


def changed_inputs(root, base, head=None):
    args = ["diff", "--name-only", "--no-renames", "-z", base]
    if head is not None:
        args.append(head)
    return sorted(path for path in git(root, *args, "--").split("\0") if covered(path))


def check(root=ROOT, *, base=None, head=None):
    policy = validate(root, head)
    changed = changed_inputs(root, base, head) if base else []
    if changed:
        old = json.loads(read(root, POLICY, base))
        old_cargo = tomllib.loads(read(root, CRATE + "Cargo.toml", base))["package"]["version"]
        if version(policy["native_version"]) <= version(old["native_version"]) or version(policy["native_version"]) <= version(old_cargo):
            raise ValueError("release inputs changed without a version bump in Cargo.toml/Cargo.lock and tool-distribution.json: " + ", ".join(changed))
    return {"release_tag": policy["release_tag"], "changed_inputs": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="PR merge-base or previous main SHA (full history must be fetched)")
    parser.add_argument("--head", help="optional committed revision instead of working tree")
    args = parser.parse_args()
    try:
        print(json.dumps(check(base=args.base, head=args.head)))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"legacy-release-check: {exc}\n")


if __name__ == "__main__":
    main()
