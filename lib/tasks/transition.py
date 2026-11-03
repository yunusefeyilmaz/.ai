"""tasks.transition: one guarded, re-validated write per task state change.

Each transition used to repeat the same sequence inside `lib/cmd/task.py`:
re-find the task under `workspace_state_guard()`, compare the path, re-parse,
validate, mutate, write and refresh the board. This module owns that sequence so
`lib/cmd/task.py` keeps argument handling and the printed messages.

The write is skipped when `mutate` raises, so a refusal can never half-apply.
"""

from __future__ import annotations

import os

from lib.core.paths import ACTIVE_DIR
from lib.core.timeutil import iso
from lib.runtime.mutex import workspace_state_guard
from lib.tasks import board, store


class TransitionError(RuntimeError):
    """Base class for a transition that did not happen."""


class Refused(TransitionError):
    """A user-facing refusal; print the message as-is."""


class GuardError(TransitionError):
    """The state guard failed (e.g. a reset is in progress)."""


class Skip(TransitionError):
    """Nothing needed to change; the caller reports success."""


def apply(
    task_id: str,
    path: str,
    mutate,
    *,
    active_only: bool = False,
    finalize=None,
) -> dict:
    """Run `mutate(meta, body) -> body` under the guard, then persist it.

    `mutate` may mutate `meta` in place and must return the new body. Raising
    `Refused`/`Skip` there leaves the file untouched. `finalize(meta)` runs
    after the write but before the board refresh (used by `done` to archive the
    file), so the board sees the final layout.
    """
    try:
        with workspace_state_guard():
            current = store.find_task(task_id)
            if current != path or (
                active_only and os.path.dirname(current or "") != ACTIVE_DIR
            ):
                raise Refused(f"Task {task_id} changed before it could be updated; retry.")
            meta, body = store.parse_task(current)
            new_body = mutate(meta, body)
            meta["updated"] = iso()
            store.write_task(current, meta, new_body)
            if finalize is not None:
                finalize(meta)
            board.write_board(store.load_tasks())
            return dict(meta)
    except (Refused, Skip):
        raise
    except OSError as exc:
        raise GuardError(str(exc)) from exc
    except RuntimeError as exc:
        raise GuardError(str(exc)) from exc
