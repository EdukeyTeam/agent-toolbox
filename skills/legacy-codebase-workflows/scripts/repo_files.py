"""Bounded, read-only source inventory shared by the local map and retrieval tools."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_FILE_BYTES = 2_000_000
HARD_MAX_FILES = 100_000
HARD_MAX_FILE_BYTES = 20_000_000

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
    env = os.environ.copy()
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
    command = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args]
    try:
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, stdout=b"", stderr=b"")


def _safe_relative(relative_path: str) -> PurePosixPath:
    path = PurePosixPath(relative_path.replace("\\", "/"))
    if not relative_path or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"unsafe relative path: {relative_path!r}")
    return path


def _secret(path: PurePosixPath) -> bool:
    for part in path.parts:
        lowered = part.lower()
        if lowered in SECRET_NAMES or lowered.startswith(".env.") or lowered.startswith(".env-"):
            return True
        if lowered in {".ssh", ".aws", ".azure", ".kube", "secrets"}:
            return True
    lower = path.name.lower()
    return path.suffix.lower() in SECRET_SUFFIXES or bool(SECRET_PATTERN.search(lower))


def _read_gitignore(root: Path, directory: Path) -> list[tuple[str, bool, bool]]:
    rules = []
    current = root
    folders = [current]
    for part in directory.relative_to(root).parts:
        current = current / part
        folders.append(current)
    for folder in folders:
        ignore = folder / ".gitignore"
        if ignore.is_file() and not ignore.is_symlink():
            try:
                for raw in ignore.read_text(encoding="utf-8").splitlines():
                    rule = raw.strip()
                    if not rule or rule.startswith("#"):
                        continue
                    negated = rule.startswith("!")
                    rule = rule[1:] if negated else rule
                    rules.append((f"{folder.relative_to(root).as_posix()}/{rule}" if folder != root else rule, negated, rule.endswith("/")))
            except (OSError, UnicodeError):
                pass
    return rules


def _ignored_non_git(root: Path, relative: PurePosixPath) -> bool:
    ignored = False
    for pattern, negated, directory_only in _read_gitignore(root, (root / str(relative)).parent):
        pattern = pattern.removesuffix("/").removeprefix("./")
        segments = relative.parts
        candidates = [relative.as_posix()]
        if directory_only:
            candidates.extend("/".join(segments[:i]) for i in range(1, len(segments)))
        elif "/" not in pattern:
            candidates.append(relative.name)
        if any(fnmatch.fnmatchcase(candidate, pattern) or candidate.startswith(pattern + "/") for candidate in candidates):
            ignored = not negated
    return ignored


def _candidates(root: Path, git_repo: bool, subtrees):
    if git_repo:
        env = os.environ.copy()
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
        args = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        if subtrees:
            args.extend(["--", *subtrees])
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        try:
            buffer = b""
            while chunk := proc.stdout.read(64 * 1024):
                buffer += chunk
                pieces = buffer.split(b"\0")
                buffer = pieces.pop()
                for piece in pieces:
                    if piece:
                        yield os.fsdecode(piece).replace(os.sep, "/")
            if proc.wait() != 0:
                raise ValueError("git ls-files failed")
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
            proc.stdout.close()
        return
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if not _ignored_non_git(root, PurePosixPath(relative)):
                yield relative


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
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read file: {exc.strerror}") from exc
    if b"\0" in data:
        raise ValueError("binary file")
    try:
        return data.decode("utf-8"), hashlib.sha256(data).hexdigest()
    except UnicodeDecodeError as exc:
        raise ValueError("non-UTF-8 file") from exc


def scan_repository(root: str | Path, *, subtrees=(), excludes=(), max_files: int = DEFAULT_MAX_FILES, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> dict:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source is not a directory")
    if not 1 <= max_files <= HARD_MAX_FILES or not 1 <= max_file_bytes <= HARD_MAX_FILE_BYTES:
        raise ValueError(f"limits must be 1..{HARD_MAX_FILES} files and 1..{HARD_MAX_FILE_BYTES} bytes")
    for subtree in subtrees:
        _safe_relative(subtree)
    top_result = _git(root, "rev-parse", "--show-toplevel")
    git_repo = top_result.returncode == 0 and Path(os.fsdecode(top_result.stdout.strip())).resolve() == root
    revision = _git(root, "rev-parse", "HEAD").stdout.decode("ascii", "replace").strip() if git_repo else None
    dirty = bool(_git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout) if git_repo else None
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
        "root": str(root), "git": git_repo, "revision": revision, "dirty": dirty,
        "fingerprint": hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest(),
        "files": files, "skipped": skipped,
        "totals": {"candidates_seen": candidates, "selected_files": len(files), "skipped_files": len(skipped)},
    }
