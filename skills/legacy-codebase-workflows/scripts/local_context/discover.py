"""Streaming, bounded inventory with literal safe paths and root ownership."""
from __future__ import annotations
import fnmatch
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from repo_files import (_git, git_context, _safe_relative, SECRET_NAMES, SECRET_SUFFIXES, SECRET_PATTERN,
                        contains_control_characters, safe_path_display, _ignored_non_git)
from .units import Root, RetrievalError

SKIP_DIRS = {".git", ".svn", "CVS", ".hg", "node_modules", "__pycache__", ".venv", "venv", "target", "dist", "build", "bin", "obj", "out", ".gradle", ".idea", ".vs", ".next", ".cache"}
DOCS = {".md", ".mdx", ".rst", ".adoc", ".asciidoc", ".rmd", ".qmd"}
LANGUAGES = {".py":"python", ".java":"java", ".js":"javascript", ".mjs":"javascript", ".cjs":"javascript", ".jsx":"javascript", ".ts":"typescript", ".tsx":"tsx", ".cs":"c_sharp", ".c":"c", ".h":"c", ".cc":"cpp", ".cpp":"cpp", ".hpp":"cpp", ".rs":"rust", ".go":"go", ".rb":"ruby", ".php":"php", ".pas":"pascal", ".dpr":"pascal", ".dpk":"pascal", ".dfm":"pascal", ".vb":"vb", ".bas":"vb", ".cls":"vb", ".frm":"vb", ".cbl":"cobol", ".cob":"cobol", ".cpy":"cobol", ".pl":"perl", ".pm":"perl", ".pod":"perl", ".r":"r", ".kt":"kotlin", ".kts":"kotlin", ".swift":"swift", ".dart":"dart", ".scala":"scala", ".groovy":"groovy", ".gradle":"groovy", ".ps1":"powershell", ".psm1":"powershell", ".bat":"batch", ".cmd":"batch", ".sh":"bash", ".bash":"bash", ".sql":"sql", ".pls":"sql", ".pkb":"sql", ".pks":"sql", ".pck":"sql", ".prc":"sql", ".fnc":"sql", ".trg":"sql", ".html":"html", ".htm":"html", ".css":"css", ".xml":"xml", ".xaml":"xml", ".config":"xml", ".cshtml":"html", ".razor":"html", ".aspx":"html", ".ascx":"html", ".asp":"html", ".jsp":"html", ".json":"json", ".toml":"toml", ".yaml":"yaml", ".yml":"yaml", ".ini":"ini", ".properties":"properties", ".cfg":"ini", ".conf":"text"}
CONFIG = {"json", "toml", "yaml", "ini", "properties", "xml"}


def secret_name(path: PurePosixPath) -> bool:
    # Do not reject ordinary source files such as secrets.py or credentials.md.
    for part in path.parts:
        lower = part.lower()
        if lower in SECRET_NAMES or lower in {".ssh", ".aws", ".azure", ".kube", "secrets"} or lower.startswith((".env.", ".env-")):
            return True
    suffix = path.suffix.lower()
    ordinary = suffix in DOCS | {".txt",".html",".htm"} or (suffix in LANGUAGES and LANGUAGES[suffix] not in CONFIG | {"text"})
    return suffix in SECRET_SUFFIXES or suffix == ".env" or (not ordinary and bool(SECRET_PATTERN.search(path.name)))


def normalize_excludes(excludes) -> tuple[str, ...]:
    if isinstance(excludes, str):
        raise RetrievalError("Exclusions must be a sequence of relative paths")
    result = []
    for value in excludes or ():
        if not isinstance(value, str) or not value.strip() or value.startswith(("/", "\\")) or ".." in PurePosixPath(value.replace("\\", "/")).parts or re.match(r"^[A-Za-z]:", value) or contains_control_characters(value):
            raise RetrievalError("Invalid exclusion; use relative paths or patterns")
        value = value.replace("\\", "/").rstrip("/")
        if value in ("", "."):
            raise RetrievalError("Invalid exclusion")
        if value not in result:
            result.append(value)
    return tuple(result)


def matches(path: str, patterns) -> bool:
    return any(path == p or path.startswith(p + "/") or fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(PurePosixPath(path).name, p) for p in patterns)


def revision(root: Path) -> str:
    value = _git(root, "rev-parse", "HEAD")
    return value.stdout.decode("ascii", "replace").strip() if value.returncode == 0 else "non-git"


def roots_for(root: Path | None, docs_roots) -> list[Root]:
    declared = [(root, "code")] if root is not None else []
    declared += [(p, "docs") for p in docs_roots]
    result = []
    for path, role in declared:
        original = Path(path).expanduser().absolute()
        if original.is_symlink() or any(p.is_symlink() for p in original.parents):
            raise RetrievalError("Root must be a nonsymlink directory", "invalid_scope")
        resolved = original.resolve(strict=True)
        if not resolved.is_dir():
            raise RetrievalError("Root must be a directory", "invalid_scope")
        for old in result:
            other = Path(old.path)
            if resolved == other or (role == "docs" and other.is_relative_to(resolved)) or (role == old.role and (other.is_relative_to(resolved) or resolved.is_relative_to(other))):
                raise RetrievalError("Docs root must not equal or contain the source root; ambiguous overlapping roots", "invalid_scope")
        index_info = _git(resolved,"rev-parse","--git-path","index")
        index_path = Path(os.fsdecode(index_info.stdout.strip())) if index_info.returncode == 0 else None
        if index_path and not index_path.is_absolute():
            index_path = resolved / index_path
        result.append(Root(f"r{len(result)}", str(resolved), role, revision(resolved),resolved.stat().st_mtime_ns,str(index_path or ""),index_path.stat().st_mtime_ns if index_path and index_path.is_file() else 0))
    if not result:
        raise RetrievalError("Provide ROOT or at least one --docs-root")
    return result


def classify(path: str, role: str) -> tuple[str, str, str]:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in DOCS or suffix == ".txt" or (role == "docs" and suffix in {".html", ".htm"}):
        fmt = "rst" if suffix in {".rst", ".txt"} else "asciidoc" if suffix in {".adoc", ".asciidoc"} else "html" if suffix in {".html", ".htm"} else "markdown"
        return "docs", fmt, fmt
    language = LANGUAGES.get(suffix, "text")
    return ("docs" if role == "docs" else "code"), language, ("notebook" if suffix == ".ipynb" else "config" if language in CONFIG else "code")


def safe_path(root: Path, relative: str) -> Path:
    try:
        rel = _safe_relative(relative)
    except ValueError as exc:
        raise RetrievalError("Unsafe source path", "invalid_scope") from exc
    if secret_name(rel):
        raise RetrievalError("Secret filename excluded", "secret_range", 403)
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents) or not path.resolve().is_relative_to(root):
        raise RetrievalError("Symlink or outside source", "invalid_scope")
    return path


def inventory(roots: list[Root], excludes=(), includes=(), discovery_limit=2_000_000, counters=None):
    counters = counters if counters is not None else {}
    counters.update(visited=0, discovered=0, eligible=0, excluded=0, excludedExamples=[])
    for owner in roots:
        base = Path(owner.path)
        git_repo = git_context(base)
        ignore_cache = {"files": {}, "bytes": 0}
        # git ls-files handles exact Git ignore semantics; bounded line reader avoids
        # the old helper's hard 100k candidate ceiling. Walk only for --include.
        def paths():
            if git_repo and not includes:
                env = {k:v for k,v in os.environ.items() if not k.upper().startswith("GIT_")}
                env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0")
                proc = subprocess.Popen(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, "-C", str(base), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--deduplicate"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=env)
                try:
                    buffer = b""
                    while block := proc.stdout.read(65536):
                        pieces = (buffer + block).split(b"\0")
                        buffer = pieces.pop()
                        for item in pieces:
                            if item:
                                yield os.fsdecode(item)
                    if proc.wait():
                        raise RetrievalError("Git inventory failed", "invalid_scope")
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait()
                    proc.stdout.close()
            else:
                stack = [base]
                while stack:
                    directory = stack.pop()
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            rel = Path(entry.path).relative_to(base).as_posix()
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name not in {".git", ".hg", ".svn", "CVS"} and not secret_name(PurePosixPath(rel)) and (includes or (entry.name not in SKIP_DIRS and not matches(rel, excludes) and not _ignored_non_git(base, PurePosixPath(rel), ignore_cache=ignore_cache, is_directory=True))):
                                    stack.append(Path(entry.path))
                                else:
                                    excluded(rel)
                            else:
                                if _ignored_non_git(base, PurePosixPath(rel), ignore_cache=ignore_cache) and not matches(rel,includes):
                                    excluded(rel)
                                    continue
                                yield rel
        def check_bound():
            if counters["visited"] > discovery_limit:
                raise RetrievalError(f"Discovery entry limit {discovery_limit} exceeded at {counters['visited']}; scope roots or raise --discovery-limit", "discovery_limit", 413)
        def excluded(rel):
            counters["excluded"] += 1
            if len(counters["excludedExamples"]) < 20:
                counters["excludedExamples"].append(safe_path_display(rel))
        for relative in paths():
            try:
                relative.encode("utf-8")
                if contains_control_characters(relative):
                    raise ValueError()
            except (UnicodeEncodeError, ValueError):
                excluded(relative)
                continue
            rel = PurePosixPath(relative)
            override = matches(relative, includes)
            if secret_name(rel) or (not override and (any(p in SKIP_DIRS for p in rel.parts) or matches(relative, excludes))):
                excluded(relative)
                continue
            counters["visited"] += 1
            counters["discovered"] += 1
            check_bound()
            try:
                path = safe_path(base, relative)
                if not path.is_file():
                    continue
                stat = path.stat()
            except (OSError, RetrievalError):
                excluded(relative)
                continue
            kind, language, fmt = classify(relative, owner.role)
            # Nested documentation roots own only docs, code beneath stays code.
            if owner.role == "code" and (kind == "docs" or language == "html" or fmt == "notebook" or PurePosixPath(relative).suffix.lower() not in LANGUAGES) and any(r.role == "docs" and path.is_relative_to(Path(r.path)) for r in roots):
                continue
            if owner.role == "docs" and any(r.role == "code" and base.is_relative_to(Path(r.path)) for r in roots) and PurePosixPath(relative).suffix.lower() in LANGUAGES and fmt not in {"markdown", "rst", "asciidoc", "html", "notebook"}:
                continue
            counters["eligible"] += 1
            yield owner, relative, kind, language, fmt, stat
