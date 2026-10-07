"""Bounded, read-only source inventory shared by the local map and retrieval tools."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_FILE_BYTES = 2_000_000
HARD_MAX_FILES = 100_000
HARD_MAX_FILE_BYTES = 20_000_000
MAX_DISCOVERY_ENTRIES = 100_000
MAX_IGNORE_BYTES = 256_000
MAX_IGNORE_TOTAL_BYTES = 2_000_000

LANGUAGES = {
    ".py": "python", ".java": "java", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
    ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".cs": "c_sharp",
    ".go": "go", ".rs": "rust",
}
DESCRIPTOR_SUFFIXES = {".xml", ".properties", ".toml", ".yaml", ".yml", ".json", ".gradle", ".mod", ".csproj", ".sln", ".vcxproj", ".props", ".targets"}
DESCRIPTOR_NAMES = {"pom.xml", "gradlew", "build.gradle", "settings.gradle", "build.gradle.kts", "settings.gradle.kts", "makefile", "cmakelists.txt", "dockerfile", "gemfile", "cargo.lock", "package-lock.json", "pnpm-lock.yaml", "requirements.txt"}
SECRET_NAMES = {".env", ".envrc", ".npmrc", ".pypirc", ".netrc", ".git-credentials", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "credentials", "credentials.json", "service-account.json", "secrets.json"}
SECRET_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".keystore", ".jks", ".asc", ".gpg", ".p8", ".pkcs8", ".kdbx"}
SECRET_PATTERN = re.compile(r"(?:^|[-_.])(?:credential|credentials|secret|secrets)(?:$|[-_.])", re.IGNORECASE)
IGNORED_DIRS = {".git", ".aider.tags.cache", "node_modules", ".venv", "venv", "__pycache__"}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1"})
    if args and args[0] == "check-ignore":
        env.pop("GIT_LITERAL_PATHSPECS", None)  # This command accepts literal filenames, not pathspecs.
    command = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args]
    try:
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, stdout=b"", stderr=b"")


def _safe_relative(relative_path: str, *, cli_input=False) -> PurePosixPath:
    """Keep source/citation identities literal; normalize separators only for CLI scope."""
    path = PurePosixPath(relative_path.replace("\\", "/") if cli_input else relative_path)
    if not relative_path or path.is_absolute() or ".." in path.parts or "." in path.parts or (os.name == "nt" and not cli_input and "\\" in relative_path):
        raise ValueError(f"unsafe relative path: {relative_path!r}")
    return path


def contains_control_characters(path: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) < 160 or character in "\u2028\u2029" for character in path)


def safe_path_display(path: str) -> str:
    """JSON string content, reversible for UTF-8 paths and safe for display."""
    display = os.fsencode(path).decode("utf-8", "replace")
    escaped = json.dumps(display, ensure_ascii=False)[1:-1]
    return "".join(f"\\u{ord(character):04x}" if 127 <= ord(character) < 160 or character in "\u2028\u2029" else character for character in escaped)


def _secret(path: PurePosixPath) -> bool:
    for part in path.parts:
        lowered = part.lower()
        if lowered in SECRET_NAMES or lowered.startswith(".env.") or lowered.startswith(".env-"):
            return True
        if lowered in {".ssh", ".aws", ".azure", ".kube", "secrets"}:
            return True
    lower = path.name.lower()
    return path.suffix.lower() in SECRET_SUFFIXES or bool(SECRET_PATTERN.search(lower))


def git_context(root: Path) -> bool:
    """Recognize ordinary worktree subtrees, without adopting an explicitly ignored root."""
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return False
    enclosing = Path(os.fsdecode(top.stdout.strip())).resolve()
    if not root.is_relative_to(enclosing):
        return False
    # An explicitly supplied root excluded by its enclosing repository is an
    # independent source tree (e.g. an exported fixture below another project).
    if root == enclosing:
        return True
    ignored = _git(root, "check-ignore", "-q", ".").returncode
    if ignored not in (0, 1):
        raise ValueError("cannot safely inspect enclosing Git ignore policy")
    return ignored == 1


def _read_gitignore(root: Path, directory: Path, cache=None) -> list[tuple[str, str, bool, bool]]:
    cache = cache if cache is not None else {"files": {}, "bytes": 0}
    rules = []
    current = root
    folders = [current]
    for part in directory.relative_to(root).parts:
        current = current / part
        folders.append(current)
    for folder in folders:
        if folder not in cache["files"]:
            local = []
            ignore = folder / ".gitignore"
            if ignore.is_file() and not ignore.is_symlink():
                text, _ = read_safe_text(root, ignore.relative_to(root).as_posix(), max_file_bytes=MAX_IGNORE_BYTES)
                cache["bytes"] += len(text.encode("utf-8"))
                if cache["bytes"] > MAX_IGNORE_TOTAL_BYTES:
                    raise ValueError(f"ignore-file byte limit exceeded ({MAX_IGNORE_TOTAL_BYTES}); select a smaller source tree")
                for raw in text.splitlines():
                    rule = raw.strip()
                    if not rule or rule.startswith("#"):
                        continue
                    negated = rule.startswith("!")
                    rule = rule[1:] if negated else rule
                    scope = folder.relative_to(root).as_posix() if folder != root else ""
                    local.append((scope, rule, negated, rule.endswith("/")))
            cache["files"][folder] = local
        rules.extend(cache["files"][folder])
    return rules


def _ignored_non_git(root: Path, relative: PurePosixPath, *, ignore_cache=None, is_directory=False) -> bool:
    ignored = False
    for scope, pattern, negated, directory_only in _read_gitignore(root, (root / str(relative)).parent, ignore_cache):
        local = relative.as_posix()
        if scope:
            if not local.startswith(scope + "/"):
                continue
            local = local[len(scope) + 1:]
        anchored = pattern.startswith("/")
        pattern = pattern.removesuffix("/").removeprefix("/")
        if not pattern:
            continue
        if directory_only and not is_directory:
            continue
        # Match this entry only: the walker already prunes ignored parents.
        # A negation for an ancestor must not re-include its ignored children.
        parts = PurePosixPath(local).parts
        if not anchored and "/" not in pattern:
            matches = fnmatch.fnmatchcase(relative.name, pattern)
        else:
            patterns = pattern.split("/")
            matches = len(parts) == len(patterns) and all(
                fnmatch.fnmatchcase(part, rule) for part, rule in zip(parts, patterns)
            )
        if matches:
            ignored = not negated
    return ignored


def _candidates(root: Path, git_repo: bool, subtrees, *, max_discovery_entries=None):
    if git_repo:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1"})
        args = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        if subtrees:
            args.extend(["--", *subtrees])
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        try:
            buffer = b""
            seen = set()
            while chunk := proc.stdout.read(64 * 1024):
                buffer += chunk
                pieces = buffer.split(b"\0")
                buffer = pieces.pop()
                for piece in pieces:
                    if piece and piece not in seen:
                        # Allow the extra candidate that reports max_files
                        # truncation, while bounding de-duplication memory.
                        if len(seen) >= HARD_MAX_FILES + 1:
                            raise ValueError("Git discovery entry limit exceeded; select a smaller source tree")
                        seen.add(piece)
                        yield os.fsdecode(piece).replace(os.sep, "/")
            if proc.wait() != 0:
                raise ValueError("git ls-files failed")
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
            proc.stdout.close()
        return
    limit = MAX_DISCOVERY_ENTRIES if max_discovery_entries is None else max_discovery_entries
    visited = 0
    ignore_cache = {"files": {}, "bytes": 0}
    scopes = [_safe_relative(s).as_posix() for s in subtrees if _safe_relative(s).as_posix() != "."]

    def selected(relative):
        return not scopes or any(relative == scope or relative.startswith(scope + "/") or scope.startswith(relative + "/") for scope in scopes)

    pending = [(True, root)]
    while pending:
        is_directory, item = pending.pop()
        if not is_directory:
            yield item.relative_to(root).as_posix()
            continue
        entries = []
        try:
            with os.scandir(item) as iterator:
                for entry in iterator:
                    visited += 1
                    if visited > limit:
                        raise ValueError(f"filesystem discovery entry limit exceeded ({limit}); select a smaller source tree")
                    entries.append(entry)
        except OSError as error:
            raise ValueError(f"cannot inventory directory: {error.filename}: {error.strerror}") from error
        directories, leaves = [], []
        for entry in sorted(entries, key=lambda e: e.name):
            relative = Path(entry.path).relative_to(root).as_posix()
            rel = PurePosixPath(relative)
            if not selected(relative):
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in IGNORED_DIRS and not _secret(rel) and not _ignored_non_git(root, rel, ignore_cache=ignore_cache, is_directory=True):
                    directories.append(Path(entry.path))
            elif not _ignored_non_git(root, rel, ignore_cache=ignore_cache):
                leaves.append(Path(entry.path))
        # Match sorted os.walk order: current-directory files first, then
        # depth-first traversal of sorted child directories. The stack is LIFO.
        pending.extend((True, directory) for directory in reversed(directories))
        pending.extend((False, leaf) for leaf in reversed(leaves))


def read_safe_text(root: str | Path, relative_path: str, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> tuple[str, str]:
    root = Path(root).resolve(strict=True)
    rel = _safe_relative(relative_path)
    if _secret(rel):
        raise ValueError("secret-looking file")
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
        raise ValueError("symlink excluded")
    try:
        if not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("missing or outside source")
        size = path.stat().st_size
        if size > max_file_bytes:
            raise ValueError("file exceeds max_file_bytes")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            data = handle.read(max_file_bytes + 1)
        if len(data) > max_file_bytes:
            raise ValueError("file exceeds max_file_bytes")
    except OSError as exc:
        raise ValueError(f"cannot read file: {exc.strerror}") from exc
    if b"\0" in data:
        raise ValueError("binary file")
    try:
        return data.decode("utf-8"), hashlib.sha256(data).hexdigest()
    except UnicodeDecodeError as exc:
        raise ValueError("non-UTF-8 file") from exc


def split_source_lines(text: str) -> list[str]:
    """Count LF lines like Tree-sitter/Git; accept CRLF without treating form feeds as newlines."""
    if not text:
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def scan_repository(root: str | Path, *, subtrees=(), excludes=(), max_files: int = DEFAULT_MAX_FILES, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> dict:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source is not a directory")
    if not 1 <= max_files <= HARD_MAX_FILES or not 1 <= max_file_bytes <= HARD_MAX_FILE_BYTES:
        raise ValueError(f"limits must be 1..{HARD_MAX_FILES} files and 1..{HARD_MAX_FILE_BYTES} bytes")
    subtrees = tuple(_safe_relative(s, cli_input=True).as_posix() for s in subtrees)
    subtrees = tuple(s for s in subtrees if s != ".")
    git_repo = git_context(root)
    head = _git(root, "rev-parse", "HEAD") if git_repo else None
    revision = head.stdout.decode("ascii", "replace").strip() if head is not None and head.returncode == 0 else None
    git_notes = []
    dirty = None
    if git_repo:
        filters = _git(root, "config", "--name-only", "--get-regexp", r"^filter\..*\.(clean|process)$")
        if filters.returncode not in (0, 1):
            git_notes.append("dirty state unavailable: cannot safely inspect Git filter configuration")
        elif filters.returncode == 0:
            git_notes.append("dirty state not checked: Git clean/process filters can execute repository commands")
        else:
            state = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=all", "--", ".")
            if state.returncode == 0:
                dirty = bool(state.stdout)
            else:
                git_notes.append("dirty state unavailable: git status failed")
    files, skipped = [], []
    candidates = 0
    iterator = _candidates(root, git_repo, subtrees)
    try:
        for relative in iterator:
            rel = _safe_relative(relative)
            if subtrees and not any(rel.as_posix() == s.rstrip("/") or rel.as_posix().startswith(s.rstrip("/") + "/") for s in subtrees):
                continue
            candidates += 1
            if candidates > max_files:
                skipped.append({"path": "*", "reason": f"max_files exceeded ({max_files}); map a subtree"})
                break
            try:
                relative.encode("utf-8")
            except UnicodeEncodeError:
                skipped.append({"path": safe_path_display(relative), "reason": "non-UTF-8 path"})
                continue
            if contains_control_characters(relative):
                skipped.append({"path": safe_path_display(relative), "reason": "control character in path"})
                continue
            if any(fnmatch.fnmatchcase(rel.as_posix(), pattern) or fnmatch.fnmatchcase(rel.name, pattern) for pattern in excludes):
                skipped.append({"path": relative, "reason": "explicit exclusion"})
                continue
            try:
                text, digest = read_safe_text(root, relative, max_file_bytes=max_file_bytes)
            except ValueError as exc:
                skipped.append({"path": relative, "reason": str(exc)})
                continue
            language = LANGUAGES.get(rel.suffix.lower())
            kind = "source" if language else "descriptor" if rel.suffix.lower() in DESCRIPTOR_SUFFIXES or rel.name.lower() in DESCRIPTOR_NAMES else "other"
            files.append({"path": relative, "sha256": digest, "size": len(text.encode("utf-8")), "language": language, "kind": kind})
    finally:
        iterator.close()
    fingerprint_input = "\n".join([*(f"{f['path']}\0{f['sha256']}" for f in files), *(f"SKIP\0{s['path']}\0{s['reason']}" for s in skipped)])
    return {
        "root": str(root), "git": git_repo, "revision": revision, "dirty": dirty, "git_notes": git_notes,
        "fingerprint": hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest(),
        "files": files, "skipped": skipped,
        "totals": {"candidates_seen": candidates, "selected_files": len(files), "skipped_files": len(skipped)},
    }
