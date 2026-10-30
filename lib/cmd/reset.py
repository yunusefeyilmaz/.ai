"""cmd.reset: split out of the former monolithic ai.py."""

from __future__ import annotations

import os
import sys

from lib.core.paths import (
    WORKSPACE,
)
from lib.core.fsio import safe_name
from lib.runtime.leases import (
    acquire_lock,
    release_lock,
)
from lib.runtime import reset as runtime_reset
from lib.tasks import board
from lib.tasks import store


def cmd_reset(args) -> int:
    if not args.hard:
        print("Specify --hard to reset .ai project task, spec, decision and runtime state.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("Hard reset requires an interactive terminal; no files were changed.", file=sys.stderr)
        return 1
    locks = runtime_reset.reset_lock_files()
    if locks:
        print("Hard reset requires all locks to be released. Existing lock files:", file=sys.stderr)
        for path in locks:
            print(f"  {os.path.relpath(path, WORKSPACE)}", file=sys.stderr)
        print("Resolve stale locks with `ai recover --apply`, then retry.", file=sys.stderr)
        return 1
    decisions_error = runtime_reset.reset_decisions_dir_error()
    if decisions_error:
        print(decisions_error, file=sys.stderr)
        return 1
    targets = runtime_reset.workspace_reset_targets()
    target_error = runtime_reset.reset_target_error(targets)
    if target_error:
        print(target_error, file=sys.stderr)
        return 1
    print("Hard reset removes task/spec/decision records, checkpoints, handoffs,")
    print("artifacts, logs and the task counter. It keeps framework docs and Git history.")
    print(f"Files to remove: {len(targets)}")
    expected = "reset .ai hard"
    try:
        confirmation = input(f"Type '{expected}' to continue: ").strip()
    except EOFError:
        confirmation = ""
    if confirmation != expected:
        print("Confirmation did not match; no files were changed.", file=sys.stderr)
        return 1

    resource = "project"
    agent = "operator-reset"
    result = acquire_lock(resource, agent=agent, task=None, ttl=600)
    if not result["ok"]:
        holder = result["holder"] or {}
        print(
            f"Could not start reset; '{resource}' overlaps a lock held by "
            f"{holder.get('agent')} ({holder.get('resource')}).",
            file=sys.stderr,
        )
        return 1
    try:
        unexpected_locks = [path for path in runtime_reset.reset_lock_files() if os.path.basename(path) != safe_name(resource) + ".lock"]
        if unexpected_locks:
            print("A lock appeared during confirmation; reset cancelled.", file=sys.stderr)
            return 1
        decisions_error = runtime_reset.reset_decisions_dir_error()
        if decisions_error:
            print(decisions_error, file=sys.stderr)
            return 1
        targets = runtime_reset.workspace_reset_targets()
        target_error = runtime_reset.reset_target_error(targets)
        if target_error:
            print(target_error, file=sys.stderr)
            return 1
        removed = 0
        try:
            for target in targets:
                if os.path.islink(target) and os.path.isdir(target):
                    os.rmdir(target)
                else:
                    os.remove(target)
                removed += 1
        finally:
            # Keep the board accurate even if the operator needs to retry after
            # a partial filesystem failure.
            board.write_board(store.load_tasks())
        print(f"Hard reset complete; removed {removed} file(s).")
        return 0
    except OSError as exc:
        print(f"Hard reset stopped after a partial cleanup: {exc}. Run `ai reset --hard` again.", file=sys.stderr)
        return 1
    finally:
        release_lock(resource, agent=agent)


ORDER = 140


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    reset = sub.add_parser("reset", help="reset .ai operational state (interactive operator action)")
    reset.add_argument("--hard", action="store_true", help="remove task/spec/decision/runtime state after confirmation")
    reset.set_defaults(func=cmd_reset)
