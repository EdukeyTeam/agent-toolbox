#!/usr/bin/env python3
"""Prepare local Context7; hooks and AGENTS.md need separate user consent."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets/context7"
sys.path.insert(0, str(SKILL / "scripts"))
import context7_backend as backend

def backend_files(skill=SKILL):
    fixed = ("scripts/context7_backend.py", "scripts/repo_files.py", "scripts/legacy_common.py", "LICENSE.txt", "THIRD_PARTY.md")
    python = tuple(p.relative_to(skill).as_posix() for p in sorted((skill / "scripts/local_context").rglob("*.py")))
    helpers = tuple(p.relative_to(skill).as_posix() for p in sorted((skill / "scripts/retrieval").rglob("*")) if p.is_file() and p.suffix in {".mjs", ".json", ".yaml"} and not {"node_modules", "__pycache__"}.intersection(p.relative_to(skill / "scripts/retrieval").parts))
    return fixed + python + helpers


BACKEND_FILES = backend_files()
DEFAULT_EXCLUDES = (".agents", ".claude", ".codex", ".github", ".vscode", "tools", "mcp.json", ".mcp.json", "AGENTS.md", "CLAUDE.md", "docs/repo-maps", "repo-maps", "docs/RepoMix", "RepoMix", "docs/analysis", "analysis")


def runtime_for(root: Path) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    runtime = (base / "local-context7" / identity).resolve()
    if runtime.is_relative_to(root) or root.is_relative_to(runtime):
        raise ValueError("Runtime must be outside the repository and must not contain it")
    return runtime


def bootstrap(filename: str) -> str:
    # Static code only; never interpolate hook inputs or user commands.
    return ("import pathlib,runpy,sys; p=pathlib.Path.cwd(); "
            "root=next((r for r in (p,*p.parents) if (r/'tools/context7/project.json').is_file()),None); "
            "sys.exit(0) if root is None else None; "
            "sys.path.insert(0,str(root/'tools')); "
            f"runpy.run_path(str(root/'tools/{filename}'),run_name='__main__')")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path}")
    return value


def add_hooks(config: dict, handler: dict, matcher: str) -> dict:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Hook configuration must contain an object")
    for event in ("PostToolUse", "Stop"):
        group = {"hooks": [handler]}
        if event == "PostToolUse":
            group["matcher"] = matcher
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError("Hook event configuration must be a list")
        if group not in groups:
            groups.append(group)
    return config


def prepare(args) -> dict:
    if args.with_hooks and not args.consent_hooks and not args.dry_run:
        raise ValueError("Ask the user first; --with-hooks requires --consent-hooks")
    if args.with_agents_md and not args.consent_agents_md and not args.dry_run:
        raise ValueError("Ask the user first; --with-agents-md requires --consent-agents-md")
    if args.with_hooks and not args.agent:
        raise ValueError("Choose the consenting user's client with --agent")
    root = args.root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root must be a directory")
    if not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.library_id):
        raise ValueError("Library ID must be /namespace/name")
    runtime = runtime_for(root)
    docs = args.docs_root if args.docs_root is not None else ("docs" if (root / "docs").is_dir() else None)
    if docs:
        relative = Path(docs)
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise ValueError("Quick setup docs root must be nested and relative; use the backend directly for separate docs")
        candidate = root / relative
        if not candidate.is_dir() or candidate.is_symlink() or not candidate.resolve().is_relative_to(root) or any(parent.is_symlink() for parent in candidate.parents if parent != root and root in parent.parents):
            raise ValueError("Docs root must be an existing nonsymlink directory")
        docs = relative.as_posix()
    project = {"libraryId": args.library_id, "docsRoot": docs, "excludes": list(backend.normalize_excludes([*DEFAULT_EXCLUDES, *args.exclude]))}
    manifest = {"origin": "EdukeyTeam/agent-toolbox: legacy-codebase-workflows", "files": {name: hashlib.sha256((SKILL / name).read_bytes()).hexdigest() for name in BACKEND_FILES}}
    planned: dict[Path, str] = {}

    def validate_target(path: Path, boundary: Path):
        if not path.resolve().is_relative_to(boundary) or path.is_symlink() or any(p.is_symlink() for p in path.parents if p != boundary and boundary in p.parents):
            raise ValueError(f"Refuse configuration through a symlink: {path.name}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Not a regular file: {path.name}")

    for relative in (".codex/config.toml", ".codex/hooks.json", ".claude/settings.json", ".mcp.json", "AGENTS.md"):
        validate_target(root / relative, root)
    for relative in BACKEND_FILES:
        validate_target(runtime / "backend" / relative, runtime)

    def plan(relative: str, text: str, *, merge=False):
        path = root / relative
        validate_target(path, root)
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            raise ValueError(f"Refuse configuration through a symlink: {relative}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Not a regular file: {relative}")
        if path.exists() and path.read_text(encoding="utf-8") != text and not merge:
            raise ValueError(f"Existing file differs; preserve it and review manually: {relative}")
        planned[path] = text

    plan("tools/local_context7.py", (ASSETS / "local_context7.py").read_text(encoding="utf-8"))
    if args.with_hooks:
        plan("tools/context7_refresh_hook.py", (ASSETS / "context7_refresh_hook.py").read_text(encoding="utf-8"))
    for name in ("package.json", "pnpm-lock.yaml"):
        plan("tools/context7/" + name, (ASSETS / name).read_text(encoding="utf-8"))
    plan("tools/context7/project.json", json.dumps(project, indent=2) + "\n")
    plan("tools/context7/backend-manifest.json", json.dumps(manifest, indent=2) + "\n")
    python_command = "python" if shutil.which("python") else "python3"
    server = {"command": python_command, "args": ["-c", bootstrap("local_context7.py"), "mcp"]}
    if "codex" in args.agent:
        path = root / ".codex/config.toml"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        configured = tomllib.loads(existing).get("mcp_servers", {}).get("context7-local")
        if configured and (configured.get("command"), configured.get("args")) != (server["command"], server["args"]):
            raise ValueError("Existing Codex context7-local differs; review it without changing hosted Context7")
        if not configured:
            existing += "\n[mcp_servers.context7-local]\ncommand = " + json.dumps(python_command) + "\nargs = " + json.dumps(server["args"]) + "\nstartup_timeout_sec = 20\ntool_timeout_sec = 60\n"
        plan(".codex/config.toml", existing, merge=True)
        if args.with_hooks:
            hook = {"type": "command", "command": python_command + ' -c "' + bootstrap("context7_refresh_hook.py") + '"', "timeout": 30}
            config = add_hooks(read_json(root / ".codex/hooks.json"), hook, "^(apply_patch|Edit|Write|Bash)$")
            plan(".codex/hooks.json", json.dumps(config, indent=2) + "\n", merge=True)
    if "claude" in args.agent:
        config = read_json(root / ".mcp.json")
        servers = config.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcpServers must be an object")
        if "context7-local" in servers and servers["context7-local"] != server:
            raise ValueError("Existing Claude context7-local differs; review it manually")
        servers["context7-local"] = server
        plan(".mcp.json", json.dumps(config, indent=2) + "\n", merge=True)
        if args.with_hooks:
            hook = {"type": "command", "command": sys.executable, "args": ["-c", bootstrap("context7_refresh_hook.py")], "timeout": 30}
            config = add_hooks(read_json(root / ".claude/settings.json"), hook, "^(Write|Edit|MultiEdit|Bash|PowerShell)$")
            plan(".claude/settings.json", json.dumps(config, indent=2) + "\n", merge=True)
    if args.with_agents_md:
        q = chr(96)
        note = ("<!-- local-context7 -->\n"
                f"Use MCP context7-local ({args.library_id}) for this repository's source and docs; hosted Context7 is for public external libraries. Verify cited original lines before editing. "
                f"After source/docs changes or commits, refresh hooks run automatically when enabled; without hooks or on HTTP 409, run {q}{python_command} tools/local_context7.py refresh{q}. "
                f'CLI fallback: {q}{python_command} tools/local_context7.py docs "ExactIdentifier"{q}.\n'
                "<!-- /local-context7 -->\n")
        path = root / "AGENTS.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if "<!-- local-context7 -->" in existing:
            if note not in existing:
                raise ValueError("Existing Context7 instruction differs; preserve it and review manually")
        else:
            existing += ("\n" if existing else "") + note
        plan("AGENTS.md", existing, merge=True)
    report = {"libraryId": args.library_id, "runtime": str(runtime), "database": str(runtime / "index.sqlite"),
              "files": [str(path.relative_to(root)) for path in planned], "hooksRequested": args.with_hooks,
              "agentsInstructionRequested": args.with_agents_md, "clientsInstalled": False,
              "nativeHooksVerified": False, "dryRun": args.dry_run}
    if args.with_agents_md:
        report["proposedInstruction"] = note
    if args.with_hooks:
        report["hookEvents"] = ["PostToolUse", "Stop"]
        report["hookClients"] = args.agent
    if args.dry_run:
        return report
    # Resolve every conflict and consent gate before the first write.
    for path, text in planned.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        newline = "\r\n" if (b"\r\n" in path.read_bytes() if path.exists() else os.name == "nt") else "\n"
        path.write_text(text, encoding="utf-8", newline=newline)
    for relative in BACKEND_FILES:
        destination = runtime / "backend" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((SKILL / relative).read_bytes())
    if args.clients:
        subprocess.run([sys.executable, str(root / "tools/local_context7.py"), "setup", "--skill-root", str(SKILL)], check=True)
        report["clientsInstalled"] = True
    report["nextCommand"] = "python tools/local_context7.py index"
    report["hookActivation"] = "Review Codex definitions in /hooks and follow Claude workspace trust; restart the agent"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--library-id", required=True)
    parser.add_argument("--docs-root")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--agent", choices=("codex", "claude"), action="append", default=[])
    for flag in ("clients", "with-hooks", "consent-hooks", "with-agents-md", "consent-agents-md", "dry-run"):
        parser.add_argument("--" + flag, action="store_true")
    try:
        print(json.dumps(prepare(parser.parse_args(argv)), indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Local Context7 setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
