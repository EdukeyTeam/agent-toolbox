#!/usr/bin/env python3
"""Project-local Context7 runtime with explicit engine and endpoint policy."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tools" / "context7"
PROJECT = json.loads((CONFIG / "project.json").read_text(encoding="utf-8"))
LIBRARY_ID = PROJECT["libraryId"]
DOCS_ROOT = ROOT / PROJECT["docsRoot"] if PROJECT["docsRoot"] else None
EXCLUDES = tuple(PROJECT["excludes"])
ENGINE = PROJECT.get("engine", {"parser": "auto", "embed_provider": "none"})
DEFAULT_MODE = PROJECT.get("defaultMode", "lexical")


def runtime_path(override: Path | None = None) -> Path:
    if override:
        runtime = override.expanduser().resolve()
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
        identity = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
        runtime = (base / "local-context7" / identity).resolve()
    if runtime.is_relative_to(ROOT) or ROOT.is_relative_to(runtime):
        raise ValueError("Runtime must be outside the repository and must not contain it")
    return runtime


def manifest() -> dict:
    return json.loads((CONFIG / "backend-manifest.json").read_text(encoding="utf-8"))


def validate_backend(folder: Path) -> None:
    for relative, expected in manifest()["files"].items():
        path = folder / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Missing or changed pinned backend: {relative}; run setup with the matching skill")


def client_environment(runtime: Path, url: str | None = None) -> dict[str, str]:
    # Forward OS startup paths, never inherited provider keys, proxies or NODE_OPTIONS.
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    for name in ("CONFIG", "STATE", "CACHE", "DATA"):
        env[f"XDG_{name}_HOME"] = str(runtime / "xdg" / name.lower())
    env["CTX7_TELEMETRY_DISABLED"] = "1"
    env["CONTEXT7_TELEMETRY_DISABLED"] = "1"
    if url:
        env["CONTEXT7_API_URL"] = url + "/api"
    return env


def client_entry(runtime: Path, package: str) -> Path:
    clients = runtime / "clients"
    metadata = json.loads((clients / "node_modules" / package / "package.json").read_text(encoding="utf-8"))
    expected = json.loads((CONFIG / "package.json").read_text(encoding="utf-8"))["dependencies"][package]
    if metadata["version"] != expected:
        raise ValueError(f"Unexpected {package} version; run setup")
    for name in ("package.json", "pnpm-lock.yaml"):
        if (clients / name).read_bytes() != (CONFIG / name).read_bytes():
            raise ValueError("Client dependency lock changed; run setup")
    return clients / "node_modules" / package / "dist" / "index.js"


def setup(runtime: Path, skill: Path) -> None:
    validate_backend(skill)
    backend = runtime / "backend"
    for relative in manifest()["files"]:
        destination = backend / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(skill / relative, destination)
    clients = runtime / "clients"
    clients.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "pnpm-lock.yaml"):
        shutil.copyfile(CONFIG / name, clients / name)
    # Prevent ctx7's automatic migration of ~/.context7 credentials.
    credentials = runtime / "xdg" / "config" / "context7" / "credentials.json"
    credentials.parent.mkdir(parents=True, exist_ok=True)
    credentials.write_text("{}\n", encoding="utf-8")
    pnpm = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if not pnpm or not shutil.which("node"):
        raise ValueError("Node.js and pnpm are required for the pinned Context7 clients")
    install_env = {**os.environ, "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    subprocess.run([pnpm, "install", "--frozen-lockfile", "--ignore-scripts"], cwd=clients, env=install_env, check=True)
    for package in ("ctx7", "@upstash/context7-mcp"):
        client_entry(runtime, package)
    print(json.dumps({"runtime": str(runtime), "database": str(runtime / "index.sqlite"), "libraryId": LIBRARY_ID}))


def load_backend(runtime: Path):
    folder = runtime / "backend"
    validate_backend(folder)
    path = folder / "scripts" / "context7_backend.py"
    spec = importlib.util.spec_from_file_location("project_context7_backend", path)
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    # Backend startup diagnostics must never contaminate MCP's stdout.
    backend.print = partial(print, file=sys.stderr)
    return backend


@contextmanager
def local_server(backend, database: Path, port: int = 0):
    """Own the server in this process, so it cannot outlive a killed MCP session."""
    ready = queue.Queue(maxsize=1)
    original = backend.ThreadingHTTPServer

    class ReportingServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            ready.put(self)

    def run():
        try:
            backend.serve(database, "127.0.0.1", port, default_mode=DEFAULT_MODE, default_library=LIBRARY_ID)
        except Exception as exc:
            ready.put(exc)

    backend.ThreadingHTTPServer = ReportingServer
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    server = None
    try:
        server = ready.get(timeout=10)
        if isinstance(server, Exception):
            raise server
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        if server is not None and not isinstance(server, Exception):
            server.shutdown()
            worker.join(timeout=5)
        backend.ThreadingHTTPServer = original


def index(backend, runtime: Path, *, download_model=False, allow_remote_embeddings=False, automatic=False) -> dict:
    if download_model and not PROJECT.get("consent", {}).get("modelDownload"):
        raise ValueError("Model download was not approved in project setup; record consent first")
    # Project policy, never ambient LEGACY_EMBED_* settings, owns this index.
    # Build the saved provider contract explicitly to avoid environment defaults.
    from local_context.embed import EmbedConfig
    from dataclasses import asdict
    provider = asdict(EmbedConfig(
        provider=ENGINE.get("embed_provider", "none"), model=ENGINE.get("embed_model"),
        revision=ENGINE.get("model_revision"), base_url=ENGINE.get("embed_base_url") or None,
        api_key_env=ENGINE.get("embed_api_key_env") or None, model_dir=ENGINE.get("model_dir"),
        cache_dir=ENGINE.get("model_cache"), allow_remote=ENGINE.get("allow_remote_embeddings", False)))
    return backend.index(ROOT, runtime / "index.sqlite", LIBRARY_ID, DOCS_ROOT,
                         excludes=EXCLUDES, parser=ENGINE.get("parser", "auto"),
                         model_cache=ENGINE.get("model_cache"), model_dir=ENGINE.get("model_dir"),
                         _saved=provider, download_model=download_model,
                         allow_remote_embeddings=allow_remote_embeddings, _automatic=automatic)


def policy_matches(con) -> bool:
    row = con.execute("SELECT scope_json,embedding_json FROM libraries WHERE id=?", (LIBRARY_ID,)).fetchone()
    if row is None:
        return False
    scope, embeddings = json.loads(row[0]), json.loads(row[1]).get("config", {})
    mapping = {"provider": "embed_provider", "model": "embed_model", "revision": "model_revision", "base_url": "embed_base_url", "api_key_env": "embed_api_key_env", "model_dir": "model_dir", "cache_dir": "model_cache", "allow_remote": "allow_remote_embeddings"}
    return (scope.get("parser", "auto") == ENGINE.get("parser", "auto")
            and scope.get("excludes", []) == list(EXCLUDES)
            and all((embeddings.get(k) or None) == (ENGINE.get(v) or None) for k, v in mapping.items()))


def refresh(backend, runtime: Path, *, allow_remote_embeddings=False, automatic=False) -> dict:
    """Check freshness first; write incremental updates only when necessary."""
    database = runtime / "index.sqlite"
    from local_context.embed import is_loopback_url
    remote = ENGINE.get("embed_provider") == "openai-compatible" and not is_loopback_url(ENGINE.get("embed_base_url"))
    if remote and not automatic and not allow_remote_embeddings:
        raise backend.RetrievalError("Remote embedding consent required: indexed code leaves this machine; after endpoint approval, run python tools/local_context7.py refresh --allow-remote-embeddings", "consent_required", 403)
    refresh_options = {"allow_remote_embeddings": allow_remote_embeddings, "automatic": automatic}
    if database.is_file():
        with backend.connect(database) as con:
            metadata = backend.indexed_metadata(con)
            if (metadata["root"], metadata["docs_root"], metadata["library_id"]) != (str(ROOT), str(DOCS_ROOT or ""), LIBRARY_ID):
                raise ValueError("Database belongs to another corpus; use a new runtime")
            if policy_matches(con):
                try:
                    backend.assert_fresh(con, metadata)
                except backend.RetrievalError:
                    # Native refresh retains per-library provider, scan and parser
                    # settings; repeating the old lexical index call would reset them.
                    native_refresh = getattr(backend, "refresh", None)
                    if callable(native_refresh):
                        return {**native_refresh(database, LIBRARY_ID, **refresh_options), "refreshed": True}
                else:
                    if con.execute("SELECT 1 FROM files WHERE library_id=? AND embedding_status='pending' LIMIT 1", (LIBRARY_ID,)).fetchone():
                        return {**backend.refresh(database, LIBRARY_ID, **refresh_options), "refreshed": True}
                    return {"libraryId": LIBRARY_ID, "refreshed": False, "changed": 0, "deleted": 0, "revision": metadata["revision"]}
    return {**index(backend, runtime, **refresh_options), "refreshed": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, help="External runtime override; use consistently for all commands")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("setup", help="Copy the pinned backend and install locked clients; network permitted here only")
    install.add_argument("--skill-root", type=Path, default=Path.home() / ".agents" / "skills" / "legacy-codebase-workflows")
    indexing = commands.add_parser("index", help="Explicitly refresh original code and docs")
    indexing.add_argument("--download-model", action="store_true", help="Use previously recorded download consent for this explicit index run only")
    indexing.add_argument("--allow-remote-embeddings", action="store_true", help="Authorize uploading indexed code to the approved remote endpoint for this index run only")
    refreshing = commands.add_parser("refresh", help="Check freshness and incrementally update only if stale; remote embeddings need renewed consent")
    refreshing.add_argument("--allow-remote-embeddings", action="store_true", help="Re-authorize uploading indexed code to the saved remote endpoint for this refresh run only")
    commands.add_parser("status", help="Verify source freshness and print index metadata")
    serve = commands.add_parser("serve", help="Serve Context7 HTTP compatibility routes until Ctrl+C")
    serve.add_argument("--port", type=int, default=8765)
    commands.add_parser("mcp", help="Start the official Context7 MCP with a private loopback backend")
    for name in ("library", "docs", "query"):
        command = commands.add_parser(name)
        command.add_argument("query", help="Exact identifier or focused question")
        if name == "query":
            command.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default=DEFAULT_MODE)
            command.add_argument("--refresh", choices=("auto", "off", "strict"), default="auto")
    expansion = commands.add_parser("expand", help="Read a verified unit or exact source range")
    for name in ("unit-id", "path", "root-id"):
        expansion.add_argument("--" + name)
    for name in ("start-line", "end-line", "tokens"):
        expansion.add_argument("--" + name, type=int, default=4000 if name == "tokens" else None)
    args = parser.parse_args(argv)
    try:
        runtime = runtime_path(args.runtime)
        if args.command == "setup":
            setup(runtime, args.skill_root.resolve())
            return 0
        backend = load_backend(runtime)
        database = runtime / "index.sqlite"
        if args.command in {"query", "expand", "serve", "mcp", "library", "docs"}:
            with backend.connect(database) as con:
                if not policy_matches(con):
                    raise ValueError("Project engine policy changed; run local_context7.py refresh before querying")
        if args.command == "index":
            print(json.dumps(index(backend, runtime, download_model=args.download_model, allow_remote_embeddings=args.allow_remote_embeddings), indent=2))
        elif args.command == "refresh":
            print(json.dumps(refresh(backend, runtime, allow_remote_embeddings=args.allow_remote_embeddings), indent=2))
        elif args.command in ("status", "query", "expand"):
            with backend.connect(database) as con:
                if args.command == "status":
                    print(json.dumps({"runtime": str(runtime), **backend.status(con, LIBRARY_ID, verify_all=True)}, indent=2))
                elif args.command == "expand":
                    print(json.dumps(backend.expand(con, library_id=LIBRARY_ID, unit_id=args.unit_id, path=args.path, root_id=args.root_id, start_line=args.start_line, end_line=args.end_line, tokens=args.tokens), indent=2))
                else:
                    print(json.dumps(backend.query(con, args.query, args.mode, None, 5, library_id=LIBRARY_ID, refresh_policy=args.refresh), indent=2))
        elif args.command == "serve":
            backend.serve(database, "127.0.0.1", args.port, default_mode=DEFAULT_MODE, default_library=LIBRARY_ID)
        else:
            package = "@upstash/context7-mcp" if args.command == "mcp" else "ctx7"
            entry = client_entry(runtime, package)
            with local_server(backend, database) as url:
                command = ["node", str(entry)]
                if args.command != "mcp":
                    command.extend(["--base-url", url, args.command])
                    command.extend([LIBRARY_ID.rsplit("/", 1)[-1] if args.command == "library" else LIBRARY_ID, args.query, "--json"])
                # Inherit stdio so the MCP client owns the session; no cloud fallback.
                return subprocess.call(command, env=client_environment(runtime, url))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if getattr(exc, "code", None) == "consent_required":
            print(json.dumps({"error": str(exc), "code": exc.code}), file=sys.stderr)
            return 5
        print(f"Local Context7: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
