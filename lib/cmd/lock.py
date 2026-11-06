"""cmd.lock: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import sys

from lib.runtime.events import append_event
from lib.runtime.leases import (
    acquire_lock,
    heartbeat_lock,
    list_locks,
    lock_status_payload,
    print_lock_table,
    release_lock,
    resource_has_glob,
)
from lib.tasks import scope as task_scope
from lib.tasks import store


def _widen_scope(task_id: str | None, resource: str, agent: str) -> str | None:
    """Add a manually acquired path to the task's commit scope.

    Taking a lease proved the worker owns the file; the commit gate used to
    disagree because `scope_allowed` still held only the plan's locks. Return a
    note when the scope changed, None otherwise.
    """
    if not task_id or resource_has_glob(resource) or resource.startswith("@"):
        return None
    path = store.find_task(task_id)
    if not path:
        return None
    meta, body = store.parse_task(path)
    if str(meta.get("owner") or "") not in ("", agent):
        return None
    allowed = task_scope.split_globs(meta.get("scope_allowed"))
    if not allowed or any(task_scope.matches(glob, resource) for glob in allowed):
        return None
    meta["scope_allowed"] = task_scope.join_globs(allowed + [resource])
    store.write_task(path, meta, body)
    return resource


def cmd_lock(args) -> int:
    if args.action == "acquire":
        result = acquire_lock(
            args.resource,
            agent=args.agent,
            task=args.task,
            ttl=args.ttl,
            force=args.force,
        )
        if result["ok"]:
            if result.get("covered_by"):
                print(f"'{args.resource}' is already covered by {args.agent}'s lock '{result['covered_by']}'.")
            else:
                print(f"Acquired '{args.resource}' for {args.agent}.")
            widened = _widen_scope(args.task, args.resource, args.agent)
            if widened:
                print(f"Added '{widened}' to task {args.task}'s scope_allowed (so the commit gate accepts it).")
            return 0
        error = result.get("error")
        if error:
            print(f"Cannot acquire '{args.resource}': {error}", file=sys.stderr)
            return 1
        holder = result["holder"] or {}
        print(
            f"'{args.resource}' is held by {holder.get('agent')} "
            f"(task {holder.get('task') or '-'}, since {holder.get('started_at')}).",
            file=sys.stderr,
        )
        append_event(
            "lock_refused",
            resource=args.resource,
            agent=args.agent,
            task=args.task,
            conflict=holder.get("resource"),
            conflict_agent=holder.get("agent"),
        )
        return 1
    if args.action == "release":
        return release_lock(args.resource, agent=args.agent, force=args.force)
    if args.action == "heartbeat":
        return heartbeat_lock(args.resource, agent=args.agent)
    locks = list_locks()
    if getattr(args, "json", False):
        print(json.dumps(lock_status_payload(locks), indent=2, default=str))
        return 0
    print_lock_table(locks)
    return 0


ORDER = 70


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    lock = sub.add_parser("lock", help="manage advisory resource locks")
    lock_sub = lock.add_subparsers(dest="action", required=True)

    lock_acquire = lock_sub.add_parser("acquire")
    lock_acquire.add_argument("resource")
    lock_acquire.add_argument("--agent", default="unknown")
    lock_acquire.add_argument("--task", default=None)
    lock_acquire.add_argument("--ttl", type=int, default=None)
    lock_acquire.add_argument("--force", action="store_true")
    lock_acquire.set_defaults(func=cmd_lock)

    lock_release = lock_sub.add_parser("release")
    lock_release.add_argument("resource")
    lock_release.add_argument("--agent", default=None)
    lock_release.add_argument("--force", action="store_true")
    lock_release.set_defaults(func=cmd_lock)

    lock_heartbeat = lock_sub.add_parser("heartbeat")
    lock_heartbeat.add_argument("resource")
    lock_heartbeat.add_argument("--agent", default=None)
    lock_heartbeat.set_defaults(func=cmd_lock)

    lock_status = lock_sub.add_parser("status")
    lock_status.add_argument("--json", action="store_true")
    lock_status.set_defaults(func=cmd_lock)
