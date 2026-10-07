#!/usr/bin/env python3
"""Build standalone legacy-codebase-workflows tools for the current OS.

Targets:
  python-bundle  `legacy-tools`: the skill's Python tools frozen with
                 PyInstaller, so the result runs without a Python install.
  rust           `legacy-repo-map`: the experimental native repository map.

Nothing is written inside this repository. Builds are OS-local: run the
helper on each platform that needs an artifact. Nothing is published.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "legacy-codebase-workflows"
CRATE = REPO / "src" / "legacy-repo-map"
# Pinned build tools. PyInstaller 6.22.3 declares support for Python 3.8-3.15.
TOOL_REQUIREMENTS = ["pyinstaller==6.22.3", "pyinstaller-hooks-contrib==2026.8"]
MAP_REQUIREMENTS = SKILL / "requirements-map.txt"
# Parser names the language pack serves from separate distributions.
SEPARATE_PARSERS = {"csharp": "tree_sitter_c_sharp", "yaml": "tree_sitter_yaml", "embeddedtemplate": "tree_sitter_embedded_template"}
RUNTIME_DISTRIBUTIONS = ["tree-sitter", "tree-sitter-language-pack", "tree-sitter-c-sharp", "tree-sitter-yaml", "tree-sitter-embedded-template", "networkx"]
PIN_IMPORTS = {"pyinstaller": "PyInstaller", "pyinstaller-hooks-contrib": "_pyinstaller_hooks_contrib"}
METADATA_DISTRIBUTIONS = ["tree-sitter", "tree-sitter-language-pack", "networkx"]
# Optional accelerators that networkx can import; the map does not use them.
EXCLUDED_MODULES = ["numpy", "scipy", "pandas", "matplotlib", "tkinter", "IPython", "pytest", "setuptools", "pip", "lxml", "pygraphviz", "pydot", "sympy", "PIL", "yaml", "defusedxml"]
# Third-party import packages the bundle may contain. Anything else that the
# build machine happens to have installed fails the build instead of shipping.
ALLOWED_PACKAGES = {"networkx", "tree_sitter", "tree_sitter_c_sharp", "tree_sitter_embedded_template", "tree_sitter_language_pack", "tree_sitter_yaml"}
LICENSE_PREFIXES = ("license", "licence", "copying", "notice", "authors", "unlicense")
EXE = ".exe" if os.name == "nt" else ""


class BuildError(Exception):
    pass


def platform_tag() -> str:
    system = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    return f"{system}-{machine}"


def outside_repository(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise BuildError(f"{label} must be outside the repository: {resolved}")
    return resolved


def run(command: list[str], *, env: dict | None = None, cwd: Path | None = None) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    completed = subprocess.run(command, env=env, cwd=cwd)
    if completed.returncode != 0:
        raise BuildError(f"command failed with exit code {completed.returncode}: {command[0]}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def importable(module: str, search: list[Path]) -> bool:
    code = f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(path) for path in search)}
    return subprocess.run([sys.executable, "-c", code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def import_from_target(module: str, target: Path) -> bool:
    code = """import importlib.util, pathlib, sys
spec = importlib.util.find_spec(sys.argv[1])
root = pathlib.Path(sys.argv[2]).resolve()
paths = [] if spec is None else [spec.origin, *(spec.submodule_search_locations or [])]
sys.exit(0 if any(path and pathlib.Path(path).resolve().is_relative_to(root) for path in paths) else 1)
"""
    env = {**os.environ, "PYTHONPATH": str(target)}
    return subprocess.run([sys.executable, "-c", code, module, str(target)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def pinned_versions(requirements: list[str]) -> dict[str, str]:
    pins = {}
    for requirement in requirements:
        line = requirement.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)", line)
        if not match:
            raise BuildError(f"build requires an exact package pin: {line}")
        pins[match[1].lower().replace("_", "-")] = match[2]
    return pins


def selected_distributions(target: Path | None) -> dict[str, importlib.metadata.Distribution]:
    sources = importlib.metadata.distributions(path=[str(target)]) if target else importlib.metadata.distributions()
    selected = {}
    for dist in sources:
        name = dist.metadata.get("Name")
        if name:
            key = name.lower().replace("_", "-")
            if key in selected and selected[key].version != dist.version:
                raise BuildError(f"multiple versions of {name} in the selected environment")
            selected[key] = dist
    return selected


def ensure_python_packages(label: str, probe: str, target: Path | None, pip_arguments: list[str], pins: dict[str, str], install: bool) -> None:
    """Require exact versions in the environment selected for the build."""
    selected = selected_distributions(target)
    missing = [name for name in pins if name not in selected]
    if missing and install and target:
        target.mkdir(parents=True, exist_ok=True)
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location", "--target", str(target), *pip_arguments])
        selected = selected_distributions(target)
        missing = [name for name in pins if name not in selected]
    if missing:
        raise BuildError(f"{label} is not importable at the pinned versions: {', '.join(missing)}; use a clean target directory with --install")
    mismatches = [f"{name}: expected {version}, found {selected[name].version}" for name, version in pins.items() if selected[name].version != version]
    if mismatches:
        raise BuildError(f"{label} version mismatch in selected environment: {'; '.join(mismatches)}; use a clean target directory")
    for name in pins:
        module = PIN_IMPORTS.get(name, name.replace("-", "_"))
        available = import_from_target(module, target) if target else importable(module, [])
        if not available:
            raise BuildError(f"{label} has matching {name} metadata but {module} is not importable from the selected {'target directory' if target else 'environment'}")


def imported_modules(sources: list[Path]) -> set[str]:
    """Absolute imports of the bundled scripts; PyInstaller cannot see them
    because the scripts ship as source files, not as frozen modules."""
    local = {path.stem for path in sources}
    found: set[str] = set()
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module)
    return {name for name in found if name.split(".")[0] not in local and name != "__future__"}


def map_parser_names() -> list[str]:
    """Parser names `repo_map.py` requests, read from its literal tables."""
    values = {}
    for node in ast.parse((SKILL / "scripts" / "repo_map.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("QUERY_PATHS", "PARSER_NAMES"):
            values[node.targets[0].id] = ast.literal_eval(node.value)
    if "QUERY_PATHS" not in values:
        raise BuildError("cannot read QUERY_PATHS from repo_map.py")
    renamed = values.get("PARSER_NAMES", {})
    return sorted({renamed.get(language, language) for language in values["QUERY_PATHS"]})


def license_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir() if path.is_file() and path.name.lower().startswith(LICENSE_PREFIXES)) if directory.is_dir() else []


def copy_license(source: Path, destination: Path) -> Path:
    if not source.is_file() or not source.read_bytes().strip():
        raise BuildError(f"required license text is missing or empty: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def python_license() -> Path:
    candidates = [
        Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.base_prefix) / "Doc" / "license.rst",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise BuildError("CPython PSF license text is unavailable; supply a Python installation containing LICENSE.txt")


def distribution_license_files(dist: importlib.metadata.Distribution) -> list[Path]:
    found = []
    for item in dist.files or []:
        if Path(str(item)).name.lower().startswith(LICENSE_PREFIXES):
            source = Path(dist.locate_file(item))
            if source.is_file():
                found.append(source)
    return sorted(set(found))


def collected_binaries(toc: Path) -> list[tuple[str, Path, str]]:
    analysis = ast.literal_eval(toc.read_text(encoding="utf-8"))
    binaries = analysis[15]
    if not isinstance(binaries, list) or not binaries or not all(len(item) == 3 and item[2] in ("BINARY", "EXTENSION") for item in binaries):
        raise BuildError("cannot identify PyInstaller Analysis BINARY TOC; refuse unlicensed bundle")
    return [(name.replace("\\", "/"), Path(source), kind) for name, source, kind in binaries]


def verify_collected_archive(toc: Path, mode: str, records: list[dict]) -> None:
    filename = "COLLECT-00.toc" if mode == "onedir" else "PKG-00.toc"
    archive_toc = ast.literal_eval((toc.parent / filename).read_text(encoding="utf-8"))
    entries = archive_toc[0] if mode == "onedir" else archive_toc[2]
    archived = {item[0].replace("\\", "/") for item in entries if len(item) == 3 and item[2] in ("BINARY", "EXTENSION")}
    licensed = {item["name"] for item in records}
    if archived != licensed:
        raise BuildError(f"PyInstaller {mode} binary inventory differs from licensed Analysis: unlicensed={sorted(archived - licensed)}, absent={sorted(licensed - archived)}")


def system_binary_license(source: Path, supplied: Path | None) -> tuple[str, Path, str]:
    if supplied:
        provided = supplied / source.name
        if provided.is_file():
            manifest_path = supplied / "manifest.json"
            if not manifest_path.is_file():
                raise BuildError(f"{manifest_path} must identify the component and source of supplied license texts")
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = entries.get(source.name)
            if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) and entry[key].strip() for key in ("component", "source")):
                raise BuildError(f"supplied license for {source.name} needs component and source in manifest.json")
            return entry["component"], provided, entry["source"]
    if sys.platform == "linux" and shutil.which("dpkg-query"):
        for candidate in (source, source.resolve()):
            lookup = subprocess.run(["dpkg-query", "-S", str(candidate)], capture_output=True, text=True)
            if lookup.returncode:
                continue
            for line in lookup.stdout.splitlines():
                package = line.split(": ", 1)[0].split(":", 1)[0]
                copyright_file = Path("/usr/share/doc") / package / "copyright"
                if copyright_file.is_file():
                    return f"debian:{package}", copyright_file, f"Debian package {package} copyright file"
    raise BuildError(f"no local license text for collected binary {source.name}; supply --binary-license-dir with a file named {source.name}")


def license_collected_binaries(stage: Path, toc: Path, search: list[Path], supplied: Path | None, runtime_root: Path | None = None) -> list[dict]:
    license_root = stage / "skill" / "licenses"
    psf = copy_license(python_license(), license_root / "python" / f"cpython-{platform.python_version()}" / "LICENSE.txt")
    distributions = {**selected_distributions(None)}
    for directory in search:
        distributions.update(selected_distributions(directory))
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    records = []
    for name, source, kind in collected_binaries(toc):
        if not source.is_file():
            raise BuildError(f"PyInstaller listed a binary that is missing: {name}")
        package_name = name.split("/", 1)[0].lower().replace("_", "-")
        if source.resolve().is_relative_to(stdlib) or source.name.lower().startswith(("libpython", "python3", "python.exe")):
            component, license_source = f"CPython {platform.python_version()}", psf
            origin = f"CPython {platform.python_version()} installed LICENSE.txt"
        elif package_name in distributions:
            if runtime_root and package_name in RUNTIME_DISTRIBUTIONS and not source.resolve().is_relative_to(runtime_root):
                raise BuildError(f"collected extension {name} came from outside the selected target directories")
            dist = distributions[package_name]
            files = distribution_license_files(dist)
            if not files:
                raise BuildError(f"no license text for collected Python extension {name} ({package_name})")
            component = f"{package_name} {dist.version}"
            origin = f"{package_name} {dist.version} distribution license metadata"
            license_source = license_root / "python" / f"{package_name}-{dist.version}" / files[0].name
            if not license_source.is_file():
                copy_license(files[0], license_source)
        else:
            component, local_license, origin = system_binary_license(source, supplied)
            license_source = copy_license(local_license, license_root / "system" / component.replace(":", "-") / local_license.name)
            # A copyright notice may refer to a separate common license text.
            for common in sorted(set(re.findall(r"/usr/share/common-licenses/([A-Za-z0-9.+-]+)", local_license.read_text(encoding="utf-8", errors="replace")))):
                if not (Path("/usr/share/common-licenses") / common).is_file():
                    common = common.rstrip(".,;:)")
                copy_license(Path("/usr/share/common-licenses") / common, license_root / "system" / "common" / common)
        records.append({"name": name, "kind": kind, "sha256": sha256(source), "component": component, "license": license_source.relative_to(stage / "skill").as_posix(), "license_sha256": sha256(license_source), "license_source": origin})
    return records


def stage_skill(stage: Path, search: list[Path]) -> list[Path]:
    """Copy the tools and their resources into the layout the bundle keeps."""
    skill = stage / "skill"
    (skill / "scripts" / "retrieval").mkdir(parents=True)
    scripts = sorted((SKILL / "scripts").glob("*.py"))
    for path in scripts:
        shutil.copy2(path, skill / "scripts" / path.name)
    for path in sorted((SKILL / "scripts" / "retrieval").iterdir()):
        if path.is_file():
            shutil.copy2(path, skill / "scripts" / "retrieval" / path.name)
    for path in [SKILL / "THIRD_PARTY.md", MAP_REQUIREMENTS, SKILL / "scripts" / "requirements-retrieval.txt"]:
        if path.is_file():
            shutil.copy2(path, skill / path.relative_to(SKILL))
    for name in ("LICENSE.txt", "NOTICE.txt"):
        copy_license(SKILL / name, skill / name)
    shutil.copytree(SKILL / "vendor", skill / "vendor", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    lines = ["# Licenses of bundled runtime components", "", "This program was frozen with PyInstaller and contains a CPython runtime plus the distributions below. Their license files are in `licenses/python/`.", "", "| Distribution | Version | License |", "| --- | --- | --- |"]
    distributions = selected_distributions(None)
    for directory in search:
        distributions.update(selected_distributions(directory))
    for name in [*RUNTIME_DISTRIBUTIONS, "pyinstaller"]:
        dist = distributions.get(name)
        if dist is None:
            raise BuildError(f"distribution metadata not found for {name}")
        declared = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see license file"
        lines.append(f"| {name} | {dist.version} | {declared.splitlines()[0][:80]} |")
        target = skill / "licenses" / "python" / f"{name}-{dist.version}"
        files = distribution_license_files(dist)
        if not files:
            raise BuildError(f"required license text for {name} {dist.version} is unavailable")
        for source in files:
            copy_license(source, target / source.name)
    copy_license(python_license(), skill / "licenses" / "python" / f"cpython-{platform.python_version()}" / "LICENSE.txt")
    lines += ["", f"CPython {platform.python_version()} PSF license text is in `licenses/python/cpython-{platform.python_version()}/LICENSE.txt`.", "The PyInstaller bootloader license and exception are in `licenses/python/pyinstaller-6.22.3/COPYING.txt`.", "Every collected binary and its license text are listed in `BUILD-INFO.json` beside the program.", ""]
    (skill / "BUNDLED_LICENSES.md").write_text("\n".join(lines), encoding="utf-8")
    return scripts


def frozen_packages(table_of_contents: Path) -> set[str]:
    """Top-level non-stdlib packages PyInstaller froze into the archive."""
    entries = ast.literal_eval(table_of_contents.read_text(encoding="utf-8"))[1]
    names = {entry[0].split(".")[0] for entry in entries}
    return {name for name in names if name not in sys.stdlib_module_names and not name.startswith(("_sysconfigdata", "pyi_", "_pyi"))}


def build_python_bundle(work: Path, out: Path, mode: str, deps: Path | None, tools: Path | None, install: bool, binary_licenses: Path | None = None) -> dict:
    ensure_python_packages("PyInstaller", "PyInstaller", tools, TOOL_REQUIREMENTS, pinned_versions(TOOL_REQUIREMENTS), install)
    ensure_python_packages("the map dependencies", "tree_sitter_language_pack", deps, ["-r", str(MAP_REQUIREMENTS)], pinned_versions(MAP_REQUIREMENTS.read_text(encoding="utf-8").splitlines()), install)
    search = [path for path in (tools, deps) if path]
    stage = work / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    scripts = stage_skill(stage, search)
    sources = scripts + sorted((SKILL / "vendor").glob("*.py"))
    wanted = imported_modules(sources)
    for parser in map_parser_names():
        wanted.add(SEPARATE_PARSERS.get(parser, f"tree_sitter_language_pack.bindings.{parser}"))
    # An import that cannot be resolved here is an optional extra of a tool.
    hidden = {name for name in wanted if importable(name, search)}
    optional_missing = sorted(wanted - hidden)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--name", "legacy-tools", f"--{mode}", "--console",
        "--distpath", str(work / "dist"), "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
        "--add-data", f"{stage / 'skill'}{os.pathsep}skill",
    ]
    for path in search:
        command += ["--paths", str(path)]
    for name in sorted(hidden):
        command += ["--hidden-import", name]
    for name in METADATA_DISTRIBUTIONS:
        command += ["--copy-metadata", name]
    for name in EXCLUDED_MODULES:
        command += ["--exclude-module", name]
    command.append(str(SKILL / "scripts" / "legacy_tools.py"))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(path) for path in search), "PYTHONDONTWRITEBYTECODE": "1"}
    run(command, env=env, cwd=work)
    packages = frozen_packages(work / "pyinstaller" / "legacy-tools" / "PYZ-00.toc")
    unexpected = sorted(packages - ALLOWED_PACKAGES)
    if unexpected:
        raise BuildError(f"the bundle picked up unaudited packages from this machine: {', '.join(unexpected)}; add them to EXCLUDED_MODULES or build in a clean environment")
    binaries = license_collected_binaries(stage, work / "pyinstaller" / "legacy-tools" / "Analysis-00.toc", search, binary_licenses, deps)
    verify_collected_archive(work / "pyinstaller" / "legacy-tools" / "Analysis-00.toc", mode, binaries)

    artifact = out / f"legacy-tools-{platform_tag()}"
    shutil.rmtree(artifact, ignore_errors=True)
    built = work / "dist" / "legacy-tools" if mode == "onedir" else work / "dist"
    if mode == "onedir":
        shutil.copytree(built, artifact, symlinks=True)
    else:
        artifact.mkdir(parents=True)
        shutil.copy2(built / f"legacy-tools{EXE}", artifact / f"legacy-tools{EXE}")
    shutil.copytree(stage / "skill" / "licenses", artifact / "licenses")
    shutil.copytree(stage / "skill" / "vendor" / "licenses", artifact / "licenses" / "tag-queries")
    shutil.copy2(stage / "skill" / "vendor" / "LICENSE.txt", artifact / "licenses" / "Aider-LICENSE.txt")
    for name in ("THIRD_PARTY.md", "BUNDLED_LICENSES.md"):
        shutil.copy2(stage / "skill" / name, artifact / name)
    for name in ("LICENSE.txt", "NOTICE.txt"):
        shutil.copy2(stage / "skill" / name, artifact / name)
    selected = selected_distributions(None)
    for directory in search:
        selected.update(selected_distributions(directory))
    versions = {name: selected[name].version for name in [*RUNTIME_DISTRIBUTIONS, "pyinstaller", "pyinstaller-hooks-contrib"] if name in selected}
    info = {
        "artifact": artifact.name, "program": f"legacy-tools{EXE}", "mode": mode, "platform": platform_tag(),
        "python": platform.python_version(), "distributions": dict(sorted(versions.items())),
        "bundled_scripts": {path.name: sha256(path) for path in sorted((stage / "skill" / "scripts").glob("*.py"))},
        "collected_binaries": binaries,
        "bundled_python_packages": sorted(packages),
        "optional_modules_not_bundled": optional_missing,
        "semantic_runtime_included": False,
        "note": "Semantic retrieval needs a separately installed Node.js runtime, the pinned Transformers.js package and a model; none are inside this bundle.",
    }
    (artifact / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return {"directory": artifact, "program": artifact / f"legacy-tools{EXE}", "info": info}


def rust_dependencies(env: dict) -> list[dict]:
    """Crates linked into the binary: normal dependencies for this host."""
    host = next(line.split(": ", 1)[1] for line in subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout.splitlines() if line.startswith("host: "))
    raw = subprocess.run(["cargo", "metadata", "--format-version", "1", "--locked", "--filter-platform", host, "--manifest-path", str(CRATE / "Cargo.toml")], check=True, capture_output=True, text=True, env=env).stdout
    metadata = json.loads(raw)
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    root = metadata["resolve"]["root"]
    reached, pending = set(), [root]
    while pending:
        current = pending.pop()
        for dependency in nodes[current]["deps"]:
            if any(kind["kind"] is None for kind in dependency["dep_kinds"]) and dependency["pkg"] not in reached:
                reached.add(dependency["pkg"])
                pending.append(dependency["pkg"])
    return sorted(({"name": packages[i]["name"], "version": packages[i]["version"], "license": packages[i].get("license") or "see crate", "repository": packages[i].get("repository") or "", "directory": str(Path(packages[i]["manifest_path"]).parent)} for i in reached), key=lambda item: (item["name"], item["version"]))


def build_rust(work: Path, out: Path) -> dict:
    if not shutil.which("cargo"):
        raise BuildError("cargo is not on PATH; install a Rust toolchain or build only --target python-bundle")
    target = outside_repository(Path(os.environ.get("CARGO_TARGET_DIR") or work / "cargo-target"), "CARGO_TARGET_DIR")
    env = {**os.environ, "CARGO_TARGET_DIR": str(target)}
    run(["cargo", "build", "--release", "--locked", "--manifest-path", str(CRATE / "Cargo.toml")], env=env)
    binary = target / "release" / f"legacy-repo-map{EXE}"
    artifact = out / f"legacy-repo-map-{platform_tag()}"
    shutil.rmtree(artifact, ignore_errors=True)
    artifact.mkdir(parents=True)
    program = artifact / binary.name
    shutil.copy2(binary, program)
    for name in ("LICENSE.txt", "NOTICE.txt"):
        copy_license(CRATE / name, artifact / name)
    notices = subprocess.run([str(program), "--notices"], check=True, capture_output=True, text=True).stdout
    (artifact / "NOTICES.txt").write_text(notices, encoding="utf-8")
    dependencies = rust_dependencies(env)
    lines = ["# Rust crates linked into legacy-repo-map", "", "| Crate | Version | License | Source | License text |", "| --- | --- | --- | --- | --- |"]
    for crate in dependencies:
        files = license_files(Path(crate["directory"]))
        folder = f"{crate['name']}-{crate['version']}"
        if files:
            destination = artifact / "licenses" / "rust" / folder
            destination.mkdir(parents=True)
            for path in files:
                shutil.copy2(path, destination / path.name)
            where = f"`licenses/rust/{folder}/`"
        elif f"==== {crate['name']} (" in notices:
            # Some crate packages omit the file; the binary embeds the text.
            where = "`NOTICES.txt`"
        else:
            raise BuildError(f"no license text found for crate {folder}; add it to the crate's embedded notices")
        lines.append(f"| {crate['name']} | {crate['version']} | {crate['license']} | {crate['repository']} | {where} |")
        crate["license_files"] = [path.name for path in files]
        crate["license_text"] = where.strip("`")
        del crate["directory"]
    (artifact / "THIRD_PARTY_RUST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    info = {
        "artifact": artifact.name, "program": binary.name, "platform": platform_tag(), "status": "experimental",
        "version": subprocess.run([str(program), "--version"], check=True, capture_output=True, text=True).stdout.strip(),
        "rustc": subprocess.run(["rustc", "--version"], check=True, capture_output=True, text=True).stdout.strip(),
        "cargo_lock_sha256": sha256(CRATE / "Cargo.lock"), "crates": dependencies,
    }
    (artifact / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return {"directory": artifact, "program": program, "info": info}


def archive(directory: Path) -> Path:
    if os.name == "nt":
        target = directory.with_suffix(".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(directory.rglob("*")):
                bundle.write(path, Path(directory.name) / path.relative_to(directory))
        return target
    target = directory.parent / f"{directory.name}.tar.gz"
    with tarfile.open(target, "w:gz") as bundle:
        bundle.add(directory, arcname=directory.name)
    return target


def clean_environment(scratch: Path) -> dict:
    """An environment without Python settings whose PATH offers only git, so
    a bundle that needed an installed interpreter would fail here."""
    env = {key: value for key, value in os.environ.items() if key.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL", "COMSPEC", "PATHEXT")}
    git = shutil.which("git")
    if os.name == "nt":
        env["PATH"] = str(Path(git).parent) if git else ""
    else:
        tools = scratch / "path"
        tools.mkdir()
        if git:
            (tools / "git").symlink_to(git)
        env["PATH"] = str(tools)
    return env


def smoke(python_bundle: dict | None, rust: dict | None) -> list[dict]:
    """Run the built programs on a throwaway repository."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail[:400]})
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + detail[:200] if detail and not ok else ''}", flush=True)

    with tempfile.TemporaryDirectory(prefix="legacy-tools-smoke-") as scratch_name:
        scratch = Path(scratch_name).resolve()
        env = clean_environment(scratch)
        source = scratch / "source tree"
        files = {
            "src/app/TransferService.java": "package app;\n\npublic class TransferService extends BaseService {\n    public void startTransfer() {\n        channel.openChannel();\n    }\n}\n",
            "src/app/Channel.java": "package app;\n\npublic class Channel {\n    public void openChannel() {}\n}\n",
            "web/cart.ts": "export function totalPrice(): number { return 1; }\n",
            "pom.xml": "<project/>\n",
            "docs/guide.md": "# Transfers\n\nA transfer opens a channel before sending data.\n",
            ".env": "TOKEN=smoke-secret-value\n",
        }
        for relative, content in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        before = {relative: sha256(source / relative) for relative in files}

        def call(program: Path, *arguments: str) -> subprocess.CompletedProcess:
            return subprocess.run([str(program), *arguments], env=env, cwd=scratch, capture_output=True, text=True, encoding="utf-8", timeout=300)

        if python_bundle:
            program = python_bundle["program"]
            info = call(program, "info")
            data = json.loads(info.stdout) if info.returncode == 0 else {}
            check("bundle: info reports a frozen runtime", data.get("frozen") is True, info.stderr)
            check("bundle: bundled scripts are the staged repository scripts", data.get("scripts") == python_bundle["info"]["bundled_scripts"])
            mapped = call(program, "map", str(source), "--output-dir", str(scratch / "map-python"), "--focus-symbol", "openChannel")
            text = (scratch / "map-python" / "repo-map.md").read_text(encoding="utf-8") if mapped.returncode == 0 else ""
            check("bundle: map lists a Java definition with its line", "src/app/Channel.java:L4: public void openChannel() {}" in text, mapped.stderr)
            check("bundle: map lists a TypeScript definition", "web/cart.ts:L1:" in text)
            produced = "".join(path.read_text(encoding="utf-8") for path in (scratch / "map-python").glob("*.*")) if mapped.returncode == 0 else "smoke-secret-value"
            check("bundle: secret file content is not in any output", "smoke-secret-value" not in produced)
            card = {"path": "src/app/Channel.java", "sha256": before["src/app/Channel.java"], "start_line": 4, "end_line": 4, "quote": "public void openChannel() {}"}
            (scratch / "cards.json").write_text(json.dumps({"citations": [card]}), encoding="utf-8")
            (scratch / "stale.json").write_text(json.dumps({"citations": [{**card, "sha256": "0" * 64}]}), encoding="utf-8")
            check("bundle: check-citations accepts a current citation", call(program, "check-citations", str(source), str(scratch / "cards.json")).returncode == 0)
            check("bundle: check-citations rejects a stale citation", call(program, "check-citations", str(source), str(scratch / "stale.json")).returncode == 1)
            database = scratch / "index.sqlite"
            indexed = call(program, "index", str(source), "--database", str(database), "--library-id", "/local/smoke")
            check("bundle: index builds a lexical database", indexed.returncode == 0 and database.is_file(), indexed.stderr)
            queried = call(program, "query", "--database", str(database), "--query", "openChannel")
            check("bundle: query returns the indexed source", queried.returncode == 0 and "Channel.java" in queried.stdout, queried.stderr)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = subprocess.Popen([str(program), "serve", "--database", str(database), "--port", str(port)], env=env, cwd=scratch, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                answer = ""
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v2/libs/search?libraryName=smoke", timeout=2) as response:
                            answer = response.read().decode("utf-8")
                        break
                    except OSError:
                        time.sleep(0.2)
                check("bundle: serve answers on loopback", "/local/smoke" in answer)
            finally:
                server.terminate()
                server.wait(timeout=10)
            check("bundle: notices include the Aider attribution", "Aider" in call(program, "notices").stdout)

        if rust:
            program = rust["program"]
            mapped = call(program, str(source), "--output-dir", str(scratch / "map-rust"), "--focus-symbol", "openChannel")
            text = (scratch / "map-rust" / "repo-map.md").read_text(encoding="utf-8") if mapped.returncode == 0 else ""
            check("rust: map lists a Java definition with its line", "src/app/Channel.java:L4: public void openChannel() {}" in text, mapped.stderr)
            check("rust: output inside the source is refused", call(program, str(source), "--output-dir", str(source / "out")).returncode == 2)
            check("rust: notices include the Apache license", "Apache License" in call(program, "--notices").stdout)

        if python_bundle and rust:
            same_map = (scratch / "map-python" / "repo-map.md").read_bytes() == (scratch / "map-rust" / "repo-map.md").read_bytes()
            inventories = [json.loads((scratch / name / "inventory.json").read_text(encoding="utf-8")) for name in ("map-python", "map-rust")]
            same_inventory = all(inventories[0][key] == inventories[1][key] for key in ("files", "skipped", "fingerprint"))
            check("parity: Python bundle and Rust binary agree on this fixture", same_map and same_inventory, f"map equal: {same_map}; inventory equal: {same_inventory}")
        check("source files are unchanged", before == {relative: sha256(source / relative) for relative in files} and sorted(str(path.relative_to(source)).replace(os.sep, "/") for path in source.rglob("*") if path.is_file()) == sorted(files))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True, type=Path, help="artifact directory outside this repository")
    parser.add_argument("--target", choices=("python-bundle", "rust", "all"), default="all")
    parser.add_argument("--mode", choices=("onedir", "onefile"), default="onedir", help="PyInstaller layout; onedir starts faster, onefile is a single program")
    parser.add_argument("--deps-dir", type=Path, help="directory holding the map dependencies (pip --target layout); default: this interpreter's environment")
    parser.add_argument("--tools-dir", type=Path, help="directory holding PyInstaller (pip --target layout); default: this interpreter's environment")
    parser.add_argument("--binary-license-dir", type=Path, help="optional directory of license texts named for collected system binaries when local package notices are unavailable")
    parser.add_argument("--install", action="store_true", help="pip-install missing pinned packages into --deps-dir and --tools-dir; never into this interpreter's environment")
    parser.add_argument("--skip-smoke", action="store_true", help="do not run the built programs")
    parser.add_argument("--require-parity", action="store_true", help="fail when the Rust binary and the Python bundle disagree in the smoke test")
    args = parser.parse_args(argv)
    try:
        out = outside_repository(args.output_dir, "--output-dir")
        deps = outside_repository(args.deps_dir, "--deps-dir") if args.deps_dir else None
        tools = outside_repository(args.tools_dir, "--tools-dir") if args.tools_dir else None
        binary_licenses = args.binary_license_dir.resolve() if args.binary_license_dir else None
        work = out / "work"
        work.mkdir(parents=True, exist_ok=True)
        python_bundle = build_python_bundle(work, out, args.mode, deps, tools, args.install, binary_licenses) if args.target in ("python-bundle", "all") else None
        rust = build_rust(work, out) if args.target in ("rust", "all") else None
        checks = [] if args.skip_smoke else smoke(python_bundle, rust)
        built = [item for item in (python_bundle, rust) if item]
        archives = [archive(item["directory"]) for item in built]
        sums = [(sha256(path), path.name) for path in archives] + [(sha256(item["program"]), f"{item['directory'].name}/{item['program'].name}") for item in built]
        (out / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for digest, name in sums), encoding="utf-8")
        manifest = {"platform": platform_tag(), "artifacts": [item["info"] for item in built], "archives": [path.name for path in archives], "smoke": checks, "smoke_skipped": args.skip_smoke}
        (out / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        print(f"build-legacy-tools: {exc}", file=sys.stderr)
        return 1
    failed = [item["name"] for item in checks if not item["ok"] and (args.require_parity or not item["name"].startswith("parity:"))]
    print(json.dumps({"output": str(out), "archives": [path.name for path in archives], "smoke_failed": failed}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
