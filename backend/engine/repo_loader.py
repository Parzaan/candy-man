"""
Step 0: Repo Loader
====================
Accepts either a local filesystem path or a GitHub URL, walks all `.py`
files (skipping vendored/irrelevant directories), and parses each one with
`ast.parse` inside its own try/except so a single malformed file can never
take down the whole scan.

Returns a `LoadedRepo` containing enough information for the rest of the
pipeline (parsed ASTs, source text, relative paths, the set of local
top-level module names for classifier.py) plus the list of files that could
not be parsed.
"""
from __future__ import annotations

import ast
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import git  # GitPython
    from git.exc import GitCommandError
except ImportError:  # pragma: no cover - GitPython is a declared dependency
    git = None
    GitCommandError = Exception


# Directories that never contain the user's own source and would otherwise
# blow up scan time / produce noise (dependency trees, VCS internals, caches).
IGNORED_DIR_NAMES = {
    ".git", ".hg", ".svn",
    "node_modules",
    "venv", ".venv", "env", ".env", "virtualenv",
    "__pycache__",
    "build", "dist", "site-packages",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode",
    "egg-info",
}

_GITHUB_URL_RE = re.compile(
    r"^(https?://|git@)([\w.-]+)[:/]([\w.\-/]+?)(\.git)?/?$"
)


class RepoLoadError(Exception):
    """Raised with an API_CONTRACT.md error code so main.py can translate it
    directly into the documented error response."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ParsedFile:
    relative_path: str      # posix-style path relative to repo root, used in API responses
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

    def cleanup(self) -> None:
        if self._cleanup_dir:
            shutil.rmtree(self._cleanup_dir, ignore_errors=True)


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIR_NAMES or part.endswith(".egg-info") for part in path.parts)


def _compute_local_top_level(py_files: List[Path], root: Path) -> set:
    """Every path component that could plausibly appear as the first token of
    an import statement inside this repo: top-level package directories and
    top-level module file stems (e.g. `utils.py` -> "utils", `pkg/sub/mod.py`
    -> "pkg")."""
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


def _walk_python_files(root: Path) -> List[Path]:
    py_files = []
    for path in root.rglob("*.py"):
        if _is_ignored(path.relative_to(root)):
            continue
        if path.is_file():
            py_files.append(path)
    return py_files


def _parse_files(py_files: List[Path], root: Path) -> tuple:
    parsed: List[ParsedFile] = []
    unscannable: List[str] = []
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
            # A single broken file must never abort the whole repository scan.
            unscannable.append(rel)
            continue
        parsed.append(ParsedFile(relative_path=rel, absolute_path=str(path), source=source, tree=tree))
    return parsed, unscannable


def _looks_like_git_url(target: str) -> bool:
    return bool(_GITHUB_URL_RE.match(target.strip()))


def _clone_repo(target: str) -> str:
    if git is None:
        raise RepoLoadError(
            "target_unreachable",
            "GitPython is not installed on the server; cannot clone GitHub repositories.",
        )
    if not _looks_like_git_url(target):
        raise RepoLoadError(
            "not_a_git_repo",
            f"'{target}' does not look like a valid git repository URL.",
        )
    tmp_dir = tempfile.mkdtemp(prefix="candyman_")
    try:
        git.Repo.clone_from(target, tmp_dir, depth=1)
    except GitCommandError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RepoLoadError(
            "target_unreachable",
            f"Could not clone repository: {exc}",
        ) from exc
    except Exception as exc:  # defensive: any other clone failure is still unreachable, not a crash
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RepoLoadError("target_unreachable", f"Could not clone repository: {exc}") from exc
    return tmp_dir


def load_repository(target: str, target_type: str) -> LoadedRepo:
    """Accepts target path/URL and type ('local' | 'github').

    Raises RepoLoadError with one of the API_CONTRACT.md error codes
    (target_unreachable, not_a_git_repo, no_python_files_found) on failure.
    """
    cleanup_dir: Optional[str] = None

    if target_type == "github":
        cleanup_dir = _clone_repo(target)
        root = Path(cleanup_dir)
    elif target_type == "local":
        root = Path(target).expanduser()
        if not root.exists() or not root.is_dir():
            raise RepoLoadError(
                "target_unreachable",
                f"Local path '{target}' does not exist or is not a directory.",
            )
    else:
        raise RepoLoadError("target_unreachable", f"Unknown target type '{target_type}'.")

    py_files = _walk_python_files(root)
    if not py_files:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise RepoLoadError(
            "no_python_files_found",
            f"No Python (.py) files were found in '{target}'.",
        )

    local_top_level = _compute_local_top_level(py_files, root)
    parsed_files, unscannable_files = _parse_files(py_files, root)

    if not parsed_files:
        # Every discovered .py file failed to parse -- still "no usable
        # Python files", surfaced with the same contract error code.
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        raise RepoLoadError(
            "no_python_files_found",
            f"No parsable Python files were found in '{target}' "
            f"({len(unscannable_files)} file(s) failed to parse).",
        )

    return LoadedRepo(
        root=str(root),
        parsed_files=parsed_files,
        unscannable_files=unscannable_files,
        local_top_level=local_top_level,
        _cleanup_dir=cleanup_dir,
    )
