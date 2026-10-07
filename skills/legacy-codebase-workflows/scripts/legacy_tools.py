#!/usr/bin/env python3
"""One entry point for the skill's local tools.

Runs from source (`python legacy_tools.py map ...`) and is the program frozen
into the standalone `legacy-tools` bundle. Arguments after the command are
passed unchanged to the tool that owns them.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import platform
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
# The bundle keeps the skill layout so each tool finds its own resources.
SKILL = Path(sys._MEIPASS) / "skill" if FROZEN else Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"

# command -> (module, arguments placed before the user's arguments)
COMMANDS = {
    "map": ("repo_map", []),
    "check-citations": ("check_citations", []),
    "index": ("context7_backend", ["index"]),
    "query": ("context7_backend", ["query"]),
    "serve": ("context7_backend", ["serve"]),
}
PACKAGES = ("tree-sitter", "tree-sitter-language-pack", "networkx")
USAGE = """\
usage: legacy-tools <command> [arguments]

commands:
  map               generate a repository map (repo_map.py)
  check-citations   check evidence cards against current source (check_citations.py)
  index             build the local retrieval index (context7_backend.py index)
  query             query the local retrieval index (context7_backend.py query)
  serve             serve the index on loopback (context7_backend.py serve)
  info              print versions and hashes of the bundled tools as JSON
  notices           print third-party notices

Run `legacy-tools <command> --help` for a command's own options.
Semantic retrieval needs a separately installed Node.js runtime and model;
neither is part of this program.
"""


def _info() -> dict:
    from importlib import metadata

    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    scripts = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(SCRIPTS.glob("*.py"))}
    return {
        "tool": "legacy-tools",
        "frozen": FROZEN,
        "python": platform.python_version(),
        "platform": f"{platform.system()}-{platform.machine()}".lower(),
        "packages": packages,
        "scripts": scripts,
        "semantic_runtime_included": False,
    }


def _notices() -> str:
    parts = []
    notices_root = Path(sys.executable).resolve().parent if FROZEN else SKILL
    for path in (notices_root / "THIRD_PARTY.md", notices_root / "BUNDLED_LICENSES.md", notices_root / "NOTICE.txt"):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8").rstrip())
    licenses = [notices_root / "LICENSE.txt", SKILL / "vendor" / "LICENSE.txt", *sorted((SKILL / "vendor" / "licenses").glob("*")), *sorted((notices_root / "licenses").rglob("*"))]
    parts.append("License texts:\n" + "\n".join(f"- {path.relative_to(notices_root).as_posix() if path.is_relative_to(notices_root) else path.name}" for path in licenses if path.is_file()))
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(USAGE)
        return 2
    command, rest = argv[0], argv[1:]
    if command in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    if command in ("info", "--version"):
        print(json.dumps(_info(), indent=2, sort_keys=True))
        return 0
    if command == "notices":
        sys.stdout.write(_notices())
        return 0
    if command not in COMMANDS:
        sys.stderr.write(f"legacy-tools: unknown command {command!r}\n\n{USAGE}")
        return 2
    module_name, prefix = COMMANDS[command]
    if FROZEN:
        sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPTS))
    sys.argv[0] = "legacy-tools" if prefix else f"legacy-tools {command}"
    module = importlib.import_module(module_name)
    return int(module.main([*prefix, *rest]) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
