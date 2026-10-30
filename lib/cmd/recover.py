"""cmd.recover: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import sys

from lib.core.paths import (
    DONE_DIR,
    HANDOFF_DIR,
    LOCKS_DIR,
)
from lib.config.settings import lock_settings
from lib.core.fsio import safe_name
from lib.core.timeutil import iso
from lib.runtime.leases import (
    list_locks,
    lock_is_stale,
)
from lib.runtime.mutex import workspace_state_guard
from lib.runtime import checkpoints as ckpt
from lib.tasks import store


def cmd_recover(args) -> int:
    if not args.apply:
        return cmd_recover_inner(args)
    try:
        with workspace_state_guard():
            return cmd_recover_inner(args)
    except RuntimeError as exc:
        print(f"Cannot apply recovery while {exc}.", file=sys.stderr)
        return 1


def cmd_recover_inner(args) -> int:
    actions: list[tuple[str, str]] = []
    repairs = []
    handled_locks: set[str] = set()

    tasks = store.load_tasks()
    _, stale_after = lock_settings()
    locks = {
        str(lock.get("resource")): lock
        for lock in list_locks()
        if not lock_is_stale(lock, stale_after)
    }
    for task in tasks:
        task_id = str(task.get("id"))
        path = task["_path"]
        status = task.get("status")
        owner = task.get("owner")
        resource = f"task-{task_id}"
        lock = locks.get(resource)
        if task["_folder"] == "active" and status == "done":
            actions.append((f"move task {task_id} active -> done", "status is done but file is in active/"))
            repairs.append(lambda p=path: os.replace(p, os.path.join(DONE_DIR, os.path.basename(p))))
            if lock:
                handled_locks.add(resource)
                repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))
        if task["_folder"] == "done" and status != "done":
            actions.append((f"set task {task_id} status done", "file is in done/"))
            def fix_status(p=path, m=task):
                meta, body = store.parse_task(p)
                meta["status"] = "done"
                meta["updated"] = iso()
                store.write_task(p, meta, body)
            repairs.append(fix_status)
        if task["_folder"] == "active" and owner and not lock:
            actions.append((f"clear stale owner on {task_id}", f"owner '{owner}' has no lock"))
            def fix_owner(p=path):
                meta, body = store.parse_task(p)
                meta["owner"] = None
                meta["lock"] = None
                if meta.get("status") == "in_progress":
                    meta["status"] = "todo"
                meta["updated"] = iso()
                store.write_task(p, meta, body)
            repairs.append(fix_owner)
        if task["_folder"] == "active" and lock and not owner:
            actions.append((f"restore owner on {task_id}", f"lock held by {lock.get('agent')}"))
            def fix_owner2(p=path, agent=lock.get("agent"), res=resource):
                meta, body = store.parse_task(p)
                meta["owner"] = agent
                meta["lock"] = res
                meta["updated"] = iso()
                store.write_task(p, meta, body)
            repairs.append(fix_owner2)
        if task["_folder"] == "done" and lock:
            actions.append((f"release lock {resource}", "task is done"))
            handled_locks.add(resource)
            repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))

    known = {str(task.get("id")) for task in tasks}
    for resource in list(locks):
        if resource.startswith("task-") and resource[5:] not in known:
            actions.append((f"remove orphan lock {resource}", "no task file"))
            handled_locks.add(resource)
            repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))

    for lock in list_locks():
        resource = str(lock.get("resource"))
        if resource in handled_locks:
            continue
        if lock_is_stale(lock, stale_after):
            actions.append((f"remove stale lock {resource}", f"held by {lock.get('agent')}"))
            handled_locks.add(resource)
            repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))

    for marker in ckpt.list_handoff_markers():
        task_id = str(marker.get("task"))
        path = store.find_task(task_id)
        if not path or os.path.dirname(path) == DONE_DIR:
            actions.append((f"remove orphan handoff marker for {task_id}", "task is gone or done"))
            repairs.append(lambda p=os.path.join(HANDOFF_DIR, marker["_file"]): os.remove(p))

    if args.json:
        print(json.dumps({"actions": [action for action, _ in actions], "applied": args.apply}, indent=2))
        if not args.apply:
            return 0
    if not actions:
        print("No inconsistencies found.")
        return 0
    for action, reason in actions:
        print(f"{'FIX' if args.apply else 'FIND'}  {action}  ({reason})")
    if not args.apply:
        print("\nRun `ai recover --apply` to repair these.")
        return 0
    for repair in repairs:
        try:
            repair()
        except OSError as exc:
            print(f"WARN  could not apply repair: {exc}", file=sys.stderr)
    if not args.json:
        print("\nRecovery applied. Run `ai check`.")
    return 0


ORDER = 100


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    recover = sub.add_parser("recover", help="detect or repair inconsistent workspace state")
    recover.add_argument("--apply", action="store_true", help="apply the repairs")
    recover.add_argument("--json", action="store_true")
    recover.set_defaults(func=cmd_recover)
