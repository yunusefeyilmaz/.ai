"""Command helper: run a task-bound command inside the task's worktree.

Commands that read or write the git state of one task (checkpoint, handoff,
resume, check --task) must look at the task's own checkout, not at the main
one. Modules starting with `_` are not command groups.
"""

from __future__ import annotations

import functools

from lib.git import repo
from lib.tasks import store


def task_meta(raw) -> dict:
    task_id = store.resolve_task_id(raw)
    path = store.find_task(task_id) if task_id else None
    return store.parse_task(path)[0] if path else {}


def task_scoped(func):
    """Decorator: `args.task_id` (or `args.task`) selects the working tree."""

    @functools.wraps(func)
    def wrapper(args):
        raw = getattr(args, "task_id", None) or getattr(args, "task", None)
        with repo.in_task(task_meta(raw)):
            return func(args)

    return wrapper
