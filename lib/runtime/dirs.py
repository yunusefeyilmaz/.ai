"""runtime.dirs: split out of the former monolithic ai.py."""

from __future__ import annotations

import os

from lib.core.paths import (
    ACTIVE_DIR,
    ARTIFACTS_DIR,
    CHECKPOINT_ARCHIVE,
    CHECKPOINT_DIR,
    CONFIG_DIR,
    DECISIONS_DIR,
    DONE_DIR,
    HANDOFF_DIR,
    LOCKS_DIR,
    LOGS_DIR,
    RUNTIME_DIR,
    SPECS_ACTIVE_DIR,
    SPECS_DONE_DIR,
    STATE_DIR,
    WORKSPACE,
)
from lib.core.fsio import write_text_atomic


def workspace_dirs() -> tuple[str, ...]:
    """Every directory the workspace owns and may recreate safely."""
    return (
        CONFIG_DIR,
        DECISIONS_DIR,
        os.path.join(WORKSPACE, "agents"),
        ACTIVE_DIR,
        DONE_DIR,
        SPECS_ACTIVE_DIR,
        SPECS_DONE_DIR,
        LOCKS_DIR,
        STATE_DIR,
        CHECKPOINT_DIR,
        CHECKPOINT_ARCHIVE,
        HANDOFF_DIR,
        ARTIFACTS_DIR,
        LOGS_DIR,
    )


def ensure_dirs() -> None:
    for path in workspace_dirs():
        os.makedirs(path, exist_ok=True)


def ensure_placeholders() -> list[str]:
    """Create runtime keep files and return the ones that were missing."""
    created: list[str] = []
    root_ignore = os.path.join(RUNTIME_DIR, ".gitignore")
    if not os.path.exists(root_ignore):
        write_text_atomic(
            root_ignore,
            "# Keep the shape, ignore transient state.\n*\n!.gitignore\n!**/\n!**/.gitkeep\n",
        )
        created.append("runtime/.gitignore")
    for folder in (LOCKS_DIR, STATE_DIR, CHECKPOINT_DIR, HANDOFF_DIR, ARTIFACTS_DIR, LOGS_DIR):
        keep = os.path.join(folder, ".gitkeep")
        if not os.path.exists(keep):
            write_text_atomic(keep, "")
            created.append(os.path.relpath(keep, WORKSPACE).replace(os.sep, "/"))
    return created
