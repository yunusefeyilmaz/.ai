"""Shared, cached throwaway workspaces for the CLI tests.

Before this module, every test copied the whole project (`shutil.copytree(ROOT)`),
normalised the config and, for Git-backed tests, ran five `git` processes
(`init`, two `config`, `add`, `commit`). Hundreds of tests did that, so most of
the suite's wall time went into building fixtures, not into testing.

Now the expensive part happens **once per process and variant** (a "template"),
and each test only gets a plain directory copy of that template:

    from _workspace import GitSpec, make_workspace

    def make_workspace(self, git_repo=True):
        git = GitSpec("develop", "Review Gate Test", "review@example.test", ("master",)) if git_repo else None
        return make_workspace(self, "ai-review-gate-", git=git)

Each test still gets its own private, writable workspace, so tests stay
independent. A template is never handed to a test and never modified after it is
built.

Set `AI_TEST_KEEP_TEMPLATES=1` to keep the template folders for debugging.
"""

from __future__ import annotations

import atexit
import functools
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple, Optional

ROOT = Path(__file__).resolve().parents[2]

COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "*.pyc", "*.pyo",
)

# Folders the tests never need can be listed here to make every copy smaller,
# e.g. EXTRA_IGNORE = ("worktrees", "node_modules"). Empty = copy what the old
# tests copied.
EXTRA_IGNORE: tuple[str, ...] = ("worktrees", "node_modules", ".venv", "dist")

def _ignore():
    """COPY_IGNORE plus EXTRA_IGNORE, as one callable for shutil.copytree."""
    if not EXTRA_IGNORE:
        return COPY_IGNORE
    extra = shutil.ignore_patterns(*EXTRA_IGNORE)

    def ignore(directory, names):
        return set(COPY_IGNORE(directory, names)) | set(extra(directory, names))

    return ignore


def _precompile(workspace: Path) -> None:
    """Ship .pyc files inside the template so the first `ai.py` call of every
    test does not recompile lib/ from source. copytree keeps mtimes, so the
    .pyc files stay valid in every copy."""
    subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(workspace / "lib")],
        check=False, capture_output=True, timeout=120,
    )


class GitSpec(NamedTuple):
    """How to turn a template into a Git repository with one baseline commit."""

    branch: str = "main"
    name: str = "Test Runner"
    email: str = "test@example.com"
    extra_branches: tuple[str, ...] = ()  # created at the baseline commit


_TEMPLATE_DIRS: list[Path] = []


def _force_rmtree(path: Path) -> None:
    """rmtree that also removes read-only files (Git objects on Windows)."""

    def _retry(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda f, t, e: _retry(f, t, e))
    else:
        shutil.rmtree(path, onerror=lambda f, t, e: _retry(f, t, e))


def _cleanup_templates() -> None:
    if os.environ.get("AI_TEST_KEEP_TEMPLATES"):
        return
    for path in _TEMPLATE_DIRS:
        _force_rmtree(path)


atexit.register(_cleanup_templates)


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(workspace), check=True, capture_output=True, text=True, timeout=60
    )


def _pin_require_check(config: dict) -> None:
    """Pin the mode-driven check gate so a developer's `ai setup` answer cannot leak.

    `ai setup --set checks=yes` writes `workflow.requireCheck = true` into the
    checkout. A fixture that copied that value would demand project checks it
    does not have, so every fixture resets it to `"strict"`: lite mode never
    requires checks, strict mode decides for itself.
    """
    config.setdefault("workflow", {})["requireCheck"] = "strict"


def _normalise(workspace: Path, mode: Optional[str], configure: Optional[Callable[[dict], None]]) -> None:
    """The reset every old `make_workspace` did, kept byte-for-byte equivalent."""
    for relative in ("tasks/active", "tasks/done", "specs/active", "specs/done"):
        folder = workspace / relative
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    for relative in ("runtime/locks", "runtime/state", "runtime/artifacts", "runtime/logs"):
        shutil.rmtree(workspace / relative, ignore_errors=True)
    (workspace / "tasks" / "BOARD.md").write_text("# Task board\n", encoding="utf-8")

    config_path = workspace / "config" / "workspace.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if mode is not None:
        config["mode"] = mode
    config["checks"] = []
    # The developer's `ai setup` answers must not change what the suite gates on:
    # pin the mode-driven default so a local `checks=yes` cannot make every
    # throwaway workspace demand checks it does not have.
    _pin_require_check(config)
    config.setdefault("preferences", {})["confirmed"] = False
    config["preferences"]["answered"] = []
    config["workflow"]["chiefOnlyTasks"] = False  # the gate has its own tests
    config["workflow"]["requireSpec"] = False
    if configure is not None:
        configure(config)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


@functools.lru_cache(maxsize=None)
def _template(
    mode: Optional[str],
    git: Optional[GitSpec],
    configure: Optional[Callable[[dict], None]],
) -> Path:
    base = Path(tempfile.mkdtemp(prefix="ai-template-"))
    _TEMPLATE_DIRS.append(base)
    workspace = base / "project"
    shutil.copytree(ROOT, workspace, ignore=_ignore())
    _normalise(workspace, mode, configure)
    _precompile(workspace)
    if git is not None:
        _git(workspace, "init", "-q", "--template=", f"--initial-branch={git.branch}")
        _git(workspace, "config", "user.name", git.name)
        _git(workspace, "config", "user.email", git.email)
        _git(workspace, "add", "-A")
        _git(workspace, "commit", "-qm", "test baseline")
        # One pack file instead of hundreds of loose objects: copying the
        # template for every test then touches far fewer files.
        _git(workspace, "repack", "-ad", "-q")
        for branch in git.extra_branches:
            _git(workspace, "branch", branch)
    return workspace


@functools.lru_cache(maxsize=None)
def _plain_template() -> Path:
    base = Path(tempfile.mkdtemp(prefix="ai-plain-"))
    _TEMPLATE_DIRS.append(base)
    project = base / "project"
    shutil.copytree(ROOT, project, ignore=_ignore())
    shutil.rmtree(project / "runtime" / "temp", ignore_errors=True)
    _precompile(project)
    return project


def copy_project(destination: Path, *, pin_checks: bool = True) -> None:
    """Drop-in for `shutil.copytree(ROOT, destination, ignore=COPY_IGNORE)`:
    the source tree is read once per process, EXTRA_IGNORE applies, and the
    copy already carries .pyc files.

    With `pin_checks` (the default), `workflow.requireCheck` is reset to
    `"strict"` so a host-project fixture never inherits the developer's
    `ai setup --set checks=yes` answer."""
    shutil.copytree(_plain_template(), destination)
    if pin_checks:
        config_path = destination / "config" / "workspace.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        _pin_require_check(config)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def make_workspace(
    case,
    prefix: str,
    *,
    mode: Optional[str] = None,
    git: Optional[GitSpec] = None,
    configure: Optional[Callable[[dict], None]] = None,
) -> Path:
    """Return a fresh private workspace for one test (removed after the test).

    `mode`       value for config["mode"]; None leaves the project's own value.
    `git`        GitSpec to make it a repo with a baseline commit; None = no Git.
    `configure`  optional module-level function(config: dict) applied after the
                 standard reset (must be a stable function object: it is part of
                 the cache key).
    """
    temp = Path(tempfile.mkdtemp(prefix=prefix))
    case.addCleanup(_force_rmtree, temp)
    workspace = temp / "project"
    shutil.copytree(_template(mode, git, configure), workspace)
    return workspace
