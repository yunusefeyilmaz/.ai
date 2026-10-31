"""tasks.lifecycle: split out of the former monolithic ai.py."""

from __future__ import annotations

import contextlib
import os
import sys

from lib.core.paths import (
    ACTIVE_DIR,
    COUNTER_PATH,
    LOCKS_DIR,
    SPECS_ACTIVE_DIR,
    WORKSPACE,
)
from lib.config.settings import lock_settings
from lib.core.fsio import (
    read_json,
    safe_name,
    slugify,
    write_json_atomic,
    write_text_atomic,
)
from lib.core.timeutil import iso
from lib.runtime.dirs import ensure_dirs
from lib.runtime.events import append_event
from lib.runtime.leases import (
    acquire_lock,
    heartbeat_lock,
    list_locks,
    lock_is_stale,
    release_lock,
)
from lib.specs import spec as spec_lib
from lib.config import roles
from lib.tasks import board
from lib.tasks import history
from lib.tasks import store


@contextlib.contextmanager
def task_index_guard():
    resource = "tasks.index"
    result = acquire_lock(resource, agent="task-index", ttl=60)
    if not result["ok"]:
        holder = result.get("holder") or {}
        print(
            "Could not allocate a task id: the task index is locked by "
            f"{holder.get('agent')}.",
            file=sys.stderr,
        )
        raise RuntimeError("task index is locked")
    try:
        yield
    finally:
        release_lock(resource, agent="task-index", quiet=True)


def allocate_task_number() -> int:
    """Allocate an ID while the caller holds task_index_guard()."""
    resource = "tasks.index"
    holder = read_json(os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")) or {}
    if holder.get("agent") != "task-index":
        raise RuntimeError("task ID allocation requires the tasks.index lock")
    state = read_json(COUNTER_PATH) or {"last": 0}
    last = int(state.get("last", 0) or 0)
    for task in store.load_tasks():
        digits = "".join(ch for ch in str(task.get("id") or "") if ch.isdigit())
        if digits:
            last = max(last, int(digits))
    number = last + 1
    write_json_atomic(COUNTER_PATH, {"last": number})
    return number


def create_task(
    title: str,
    priority: str = "medium",
    spec: str | None = None,
    depends_on: str | None = None,
    make_spec: bool = True,
    scope_allowed: str | None = None,
    scope_forbidden: str | None = None,
    actor: str | None = None,
) -> dict:
    """Create a task and, unless told otherwise, its spec skeleton."""
    ensure_dirs()
    with task_index_guard():
        number = allocate_task_number()
        task_id = f"{number:04d}"
        title = title.strip()
        slug = slugify(title)
        path = os.path.join(ACTIVE_DIR, f"{task_id}-{slug}.md")
        spec_ref = spec
        if not spec_ref and make_spec:
            spec_path = os.path.join(SPECS_ACTIVE_DIR, f"{task_id}-{slug}.md")
            write_text_atomic(spec_path, spec_lib.spec_from_template(title, task_id))
            spec_ref = os.path.relpath(spec_path, WORKSPACE).replace(os.sep, "/")
        meta = {
            "id": task_id,
            "title": title,
            "status": "todo",
            "owner": None,
            "priority": priority,
            "spec": spec_ref,
            "depends_on": depends_on,
            "scope_allowed": scope_allowed,
            "scope_forbidden": scope_forbidden,
            "created": iso(),
            "updated": iso(),
            "lock": None,
        }
        plan = (
            f"Spec: `{spec_ref}`\n\n<!-- Filled by the planner. -->"
            if spec_ref
            else "<!-- Filled by the planner. Link the spec when one exists. -->"
        )
        body = f"""# {task_id} - {title}

## Intent

<!-- What problem does this solve? Who is it for? -->

## Acceptance criteria

- [ ] 

## Plan

{plan}

## Notes

## Log

{history.line(actor, None, 'todo', 'created')}
"""
        store.write_task(path, meta, body)
        board.write_board(store.load_tasks())
    append_event("task_created", task=task_id)
    return {"id": task_id, "path": path, "spec": spec_ref, "slug": slug}


def claim_task(path: str, agent: str, force: bool = False) -> tuple[bool, str]:
    denied = roles.authorize(agent, "task.claim")
    if denied and not force:
        return False, denied
    if os.path.dirname(path) != ACTIVE_DIR:
        return False, "This task is already in done/."
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    if meta.get("status") == "blocked" and not force:
        return False, f"Task {task_id} is blocked. Unblock it with `ai task unblock {task_id}`."
    blockers = store.dependency_blockers(meta)
    if blockers and not force:
        return False, f"Task {task_id} is blocked by " + ", ".join(blockers) + ". Use --force to override."
    resource = f"task-{task_id}"
    result = acquire_lock(resource, agent=agent, task=task_id, force=force)
    new_claim = bool(result["ok"])
    if not result["ok"]:
        if result.get("error"):
            append_event("lock_refused", resource=resource, agent=agent, task=task_id)
            return False, f"Could not claim task {task_id}: {result['error']}"
        holder = result["holder"] or {}
        if holder.get("agent") == agent:
            heartbeat_lock(resource, agent=agent)
        else:
            append_event(
                "lock_refused",
                resource=resource,
                agent=agent,
                task=task_id,
                conflict=holder.get("resource"),
                conflict_agent=holder.get("agent"),
            )
            return False, (
                f"Task {task_id} is locked by {holder.get('agent')} "
                f"(pid {holder.get('pid')}, since {holder.get('started_at')})."
            )
    if store.find_task(task_id) != path:
        release_lock(resource, agent=agent, force=True)
        return False, f"Task {task_id} was removed while it was being claimed."
    previous = meta.get("status")
    meta["owner"] = agent
    # A reviewer taking over a task in review keeps it in review.
    meta["status"] = "review" if previous == "review" else "in_progress"
    meta["updated"] = iso()
    meta["lock"] = resource
    body = history.append(body, agent, previous, meta["status"], "claimed")
    store.write_task(path, meta, body)
    board.write_board(store.load_tasks())
    if new_claim:
        append_event("task_claimed", task=task_id, agent=agent)
    return True, task_id


def ready_and_waiting() -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    active = [task for task in store.load_tasks() if task["_folder"] == "active"]
    locks = {str(lock.get("resource")): lock for lock in list_locks()}
    _, stale_after = lock_settings()
    ready = []
    waiting = []
    for task in active:
        if task.get("status") not in ("todo", "changes_requested"):
            continue
        reasons = store.dependency_blockers(task)
        lock = locks.get(f"task-{task.get('id')}")
        if lock and not lock_is_stale(lock, stale_after):
            reasons.append(f"leased by {lock.get('agent')}")
        if reasons:
            waiting.append((task, reasons))
        else:
            ready.append(task)
    ready.sort(key=lambda item: (
        0 if item.get("status") == "changes_requested" else 1,
        store.PRIORITY_ORDER.get(str(item.get("priority")), 1),
        str(item.get("id")),
    ))
    return ready, waiting
