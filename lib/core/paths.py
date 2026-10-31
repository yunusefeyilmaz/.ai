"""core.paths: every filesystem location the workspace knows about.

Layout (WORKSPACE is the `.ai` folder that holds `ai.py`):

    ai.py                 entry point (thin)
    lib/<domain>/         SCRIPTS ONLY (core, config, runtime, tasks, specs,
                          git, decisions, cmd, tests)
    tasks/ specs/ runtime/ config/ templates/ docs/decisions/ skills/
                          DATA, in their original locations
"""

from __future__ import annotations

import os
import socket
import sys

VERSION = "0.8.0"
HOST = socket.gethostname()

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.dirname(CORE_DIR)
WORKSPACE = os.path.dirname(LIB_DIR)
SCRIPT_DIR = WORKSPACE  # entry point (ai.py) lives at the workspace root


def project_root_for_workspace() -> str:
    """Resolve the host project, including a standalone checkout named `.ai`."""
    if os.path.basename(WORKSPACE) != ".ai":
        return WORKSPACE

    parent = os.path.dirname(WORKSPACE)
    # A host repository wins when `.ai` is installed inside it, even if the
    # host has no Git metadata yet. `adopt` writes this rule before setup.
    if os.path.lexists(os.path.join(parent, ".git")):
        return parent
    host_markers = (
        ".gitignore", "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "pom.xml", "composer.json", "Gemfile", "requirements.txt", "src",
        "app", "index.html",
    )
    if any(os.path.lexists(os.path.join(parent, name)) for name in host_markers):
        return parent
    # The framework repository itself is also commonly checked out into a
    # directory named `.ai`; in that layout its Git root is the project root.
    if os.path.lexists(os.path.join(WORKSPACE, ".git")):
        return WORKSPACE
    return parent


# `adopt` is the explicit subfolder-install operation, so it must target the
# containing host even before `.gitignore` or host Git metadata exists.
PROJECT = (
    os.path.dirname(WORKSPACE)
    if os.path.basename(WORKSPACE) == ".ai"
    and len(sys.argv) > 1
    and sys.argv[1] == "adopt"
    else project_root_for_workspace()
)

# --- data owned by each domain -------------------------------------------
CONFIG_DIR = os.path.join(WORKSPACE, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "workspace.json")

TASKS_DIR = os.path.join(WORKSPACE, "tasks")
ACTIVE_DIR = os.path.join(TASKS_DIR, "active")
DONE_DIR = os.path.join(TASKS_DIR, "done")
BOARD_PATH = os.path.join(TASKS_DIR, "BOARD.md")

SPECS_DIR = os.path.join(WORKSPACE, "specs")
SPECS_ACTIVE_DIR = os.path.join(SPECS_DIR, "active")
SPECS_DONE_DIR = os.path.join(SPECS_DIR, "done")
SPECS_TEMPLATE = os.path.join(SPECS_DIR, "TEMPLATE.md")

DECISIONS_DIR = os.path.join(WORKSPACE, "docs", "decisions")
WORKTREES_DIR = os.path.join(WORKSPACE, "worktrees")  # one checkout per task (git.isolation=worktree)
GIT_TEMPLATES_DIR = os.path.join(WORKSPACE, "templates", "git")
SKILLS_DIR = os.path.join(WORKSPACE, "skills")
TESTS_DIR = os.path.join(LIB_DIR, "tests")

RUNTIME_DIR = os.path.join(WORKSPACE, "runtime")
LOCKS_DIR = os.path.join(RUNTIME_DIR, "locks")
STATE_DIR = os.path.join(RUNTIME_DIR, "state")
CHECKPOINT_DIR = os.path.join(STATE_DIR, "checkpoints")
CHECKPOINT_ARCHIVE = os.path.join(CHECKPOINT_DIR, "archive")
HANDOFF_DIR = os.path.join(STATE_DIR, "handoff")
EVENTS_FILE = os.path.join(STATE_DIR, "events.jsonl")
ARTIFACTS_DIR = os.path.join(RUNTIME_DIR, "artifacts")
LOGS_DIR = os.path.join(RUNTIME_DIR, "logs")
COUNTER_PATH = os.path.join(STATE_DIR, "task-counter.json")
MANIFEST_PATH = os.path.join(ARTIFACTS_DIR, "MANIFEST.json")
LAST_CHECK_PATH = os.path.join(STATE_DIR, "last-check.json")
EVIDENCE_DIR = os.path.join(STATE_DIR, "evidence")
REGISTRY_MUTEX = os.path.join(LOCKS_DIR, ".registry.mutex")

REQUIRED_PATHS = [
    "AGENTS.md",
    "README.md",
    "GUIDE.md",
    "ai.py",
    "config/workspace.json",
    "tasks/README.md",
    "tasks/TEMPLATE.md",
    "specs/README.md",
    "templates/git/commit-template.txt",
    "templates/git/pull-request.md",
    "runtime",
    "docs/architecture.md",
    "docs/git-workflow.md",
    "docs/task-flow.md",
    "docs/multi-agent.md",
    "docs/artifact-hygiene.md",
    "docs/recovery.md",
    "docs/orchestration.md",
    "agents/README.md",
]

TASK_STATUSES = {"todo", "in_progress", "review", "changes_requested", "blocked", "done"}

SCAN_SKIP = {
    ".ai", ".git", ".github", "node_modules", "vendor", "dist", "build",
    "target", "out", "bin", "obj", ".venv", "venv", "__pycache__",
}


def ws_prefix() -> str:
    return "" if os.path.abspath(WORKSPACE) == os.path.abspath(PROJECT) else ".ai/"


def ws_rel(path: str) -> str:
    return os.path.relpath(path, PROJECT).replace(os.sep, "/")


def workspace_shape() -> str:
    """Report whether the workspace is the project root or a `.ai` subfolder."""
    if (
        os.path.basename(WORKSPACE) == ".ai"
        and os.path.abspath(PROJECT) != os.path.abspath(WORKSPACE)
    ):
        return "subfolder"
    return "root"
