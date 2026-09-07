from __future__ import annotations

import ast
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import git
    from git.exc import GitCommandError
except ImportError:
    git = None
    GitCommandError = Exception

IGNORED_DIR_NAMES = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", ".env",
    "virtualenv", "__pycache__", "build", "dist", "site-packages",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "egg-info",
}

_GITHUB_URL_RE = re.compile(r"^(https?://|git@)([\w.-]+)[:/]([\w.\-/]+?)(\.git)?/?$")


class RepoLoadError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ParsedFile:
    relative_path: str
    absolute_path: str
    source: str
    tree: ast.AST


@dataclass
class LoadedRepo:
    root: str
    parsed_files: List[ParsedFile] = field(default_factory=list)
    unscannable_files: List[str] = field(default_factory=list)
    local_top_level: set = field(default_factory=set)
    _cleanup_dir: Optional[str] = None

    def cleanup(self):
        if self._cleanup_dir:
            shutil.rmtree(self._cleanup_dir, ignore_errors=True)


def _is_ignored(path):
    return any(part in IGNORED_DIR_NAMES or part.endswith(".egg-info") for part in path.parts)


def _compute_local_top_level(py_files, root):
    names = set()
    for f in py_files:
        rel = f.relative_to(root)
        parts = rel.parts
        if not parts:
            continue
        first = parts[0]
        if first.endswith(".py"):
            names.add(first[:-3])
        else:
            names.add(first)
    return names


def _walk_python_files(root):
    py_files = []
    for path in root.rglob("*.py"):
        if _is_ignored(path.relative_to(root)):
            continue
        if path.is_file():
            py_files.append(path)
    return py_files


def _parse_files(py_files, root):
    parsed = []
    unscannable = []
    for path in sorted(py_files):
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            unscannable.append(rel)
            continue
        try:
            tree = ast.parse(source, filename=rel)
        except (SyntaxError, ValueError):
            unscannable.append(rel)
            continue
        parsed.append(ParsedFile(relative_path=rel, absolute_path=str(path), source=source, tree=tree))
    return parsed, unscannable


def _looks_like_git_url(target):
    return bool(_GITHUB_URL_RE.match(target.strip()))


def _clone_repo(target):
    if git is None:
        raise RepoLoadError("target_unreachable", "GitPython is not installed.")
    if not _looks_like_git_url(target):
        raise RepoLoadError("not_a_git_repo", f"'{target}' does not look like a valid git repository URL.")
    tmp_dir = tempfile.mkdtemp(prefix="candyman_")
    try:
        git.Repo.clone_from(target, tmp_dir, depth=1)
    except GitCommandError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Human-readable message, not the raw git CLI stderr dump (fixed
        # after review -- that dump exposed internal command syntax and
        # temp paths to end users for no benefit).
        reason = "repository not found or not accessible" if "not found" in str(exc).lower() or "128" in str(exc) else "clone failed"
        raise RepoLoadError("target_unreachable", f"Could not clone '{target}': {reason}. Check the URL and that the repository is public.") from exc
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RepoLoadError("target_unreachable", f"Could not clone '{target}': {type(exc).__name__}.") from exc
    return tmp_dir


def load_repository(target, target_type):
    cleanup_dir = None
    if target_type == "github":
        cleanup_dir = _clone_repo(target)
        root = Path(cleanup_dir)
    elif target_type == "local":
        root = Path(target).expanduser()
        if not root.exists() or not root.is_dir():
            raise RepoLoadError("target_unreachable", f"Local path '{target}' does not exist or is not a directory.")
    else:
        raise RepoLoadError("target_unreachable", f"Unknown target type '{target_type}'.")

    py_files = _walk_python_files(root)
    if not py_files:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise RepoLoadError("no_python_files_found", f"No Python (.py) files were found in '{target}'.")

    local_top_level = _compute_local_top_level(py_files, root)
    parsed_files, unscannable_files = _parse_files(py_files, root)

    if not parsed_files:
        # Every discovered .py file failed to parse. This is different from
        # finding zero .py files at all (handled above as a hard error) --
        # here there IS real information (which files failed) that the API
        # contract promises to surface, never silently drop. Return a valid,
        # empty-but-informative LoadedRepo instead of raising.
        return LoadedRepo(
            root=str(root), parsed_files=[], unscannable_files=unscannable_files,
            local_top_level=local_top_level, _cleanup_dir=cleanup_dir,
        )

    return LoadedRepo(
        root=str(root), parsed_files=parsed_files, unscannable_files=unscannable_files,
        local_top_level=local_top_level, _cleanup_dir=cleanup_dir,
    )