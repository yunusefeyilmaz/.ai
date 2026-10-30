"""runtime.reset: split out of the former monolithic ai.py."""

from __future__ import annotations

from lib.core.paths import (
    ACTIVE_DIR,
    ARTIFACTS_DIR,
    CHECKPOINT_DIR,
    COUNTER_PATH,
    DECISIONS_DIR,
    DONE_DIR,
    HANDOFF_DIR,
    LOCKS_DIR,
    LOGS_DIR,
    SPECS_ACTIVE_DIR,
    SPECS_DONE_DIR,
    WORKSPACE,
)

import os
import re



def workspace_reset_targets() -> list[str]:
    targets: set[str] = set()
    preserved_names = {".gitkeep", "TEMPLATE.md", "README.md"}
    for directory in (ACTIVE_DIR, DONE_DIR):
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if name not in preserved_names and name.endswith(".md") and os.path.isfile(path):
                    targets.add(path)
    for directory in (
        SPECS_ACTIVE_DIR,
        SPECS_DONE_DIR,
    ):
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if name not in preserved_names and name.endswith(".md") and os.path.isfile(path):
                    targets.add(path)
    decisions_dir = DECISIONS_DIR
    if os.path.isdir(decisions_dir) and not os.path.islink(decisions_dir):
        for name in os.listdir(decisions_dir):
            path = os.path.join(decisions_dir, name)
            if re.fullmatch(r"\d{4}-.+\.md", name) and os.path.isfile(path):
                targets.add(path)
    for root in (CHECKPOINT_DIR, HANDOFF_DIR, ARTIFACTS_DIR, LOGS_DIR):
        if not os.path.isdir(root):
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            for name in list(directories):
                path = os.path.join(current, name)
                if os.path.islink(path):
                    targets.add(path)
                    directories.remove(name)
            for name in files:
                if name != ".gitkeep":
                    targets.add(os.path.join(current, name))
    if os.path.isfile(COUNTER_PATH):
        targets.add(COUNTER_PATH)
    return sorted(targets)


def reset_lock_files() -> list[str]:
    if not os.path.isdir(LOCKS_DIR):
        return []
    return sorted(
        os.path.join(LOCKS_DIR, name)
        for name in os.listdir(LOCKS_DIR)
        if name.endswith(".lock")
    )


def reset_decisions_dir_error() -> str | None:
    decisions_dir = DECISIONS_DIR
    if os.path.islink(decisions_dir):
        return "Refusing to reset decision records through a symlinked docs/decisions directory."
    if os.path.exists(decisions_dir) and os.path.realpath(decisions_dir) != os.path.abspath(decisions_dir):
        return "Refusing to reset decision records outside docs/decisions."
    return None


def reset_target_error(targets: list[str]) -> str | None:
    workspace = os.path.realpath(WORKSPACE)
    allowed_roots = [
        ACTIVE_DIR,
        DONE_DIR,
        SPECS_ACTIVE_DIR,
        SPECS_DONE_DIR,
        DECISIONS_DIR,
        CHECKPOINT_DIR,
        HANDOFF_DIR,
        ARTIFACTS_DIR,
        LOGS_DIR,
        os.path.dirname(COUNTER_PATH),
    ]
    for target in targets:
        resolved = os.path.realpath(target)
        try:
            contained = os.path.commonpath([resolved, workspace]) == workspace
            in_reset_scope = any(
                os.path.commonpath([resolved, os.path.realpath(root)]) == os.path.realpath(root)
                for root in allowed_roots
            )
        except ValueError:
            contained = False
            in_reset_scope = False
        if not contained or not in_reset_scope:
            return f"Refusing to reset a path outside the approved state folders: {target}"
        decisions_dir = DECISIONS_DIR
        if os.path.dirname(os.path.abspath(target)) == os.path.abspath(decisions_dir):
            if os.path.realpath(os.path.dirname(target)) != os.path.abspath(decisions_dir):
                return f"Refusing to reset a decision record through an unexpected directory: {target}"
            if not re.fullmatch(r"\d{4}-.+\.md", os.path.basename(target)):
                return f"Refusing to reset a non-ADR file in docs/decisions: {target}"
        if not (os.path.isfile(target) or os.path.islink(target)):
            return f"Refusing to reset a non-file path: {target}"
    return None
