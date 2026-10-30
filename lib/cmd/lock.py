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
)


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
            print(f"Acquired '{args.resource}' for {args.agent}.")
            return 0
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
