"""runtime.leases: split out of the former monolithic ai.py."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys

from lib.core.paths import (
    HOST,
    LOCKS_DIR,
)
from lib.config.settings import (
    lock_settings,
    max_lock_ttl,
)
from lib.core.fsio import (
    read_json,
    safe_name,
    write_json_atomic,
)
from lib.core.timeutil import (
    iso,
    now,
    parse_iso,
)
from lib.runtime.dirs import ensure_dirs
from lib.runtime.events import read_events
from lib.runtime.mutex import registry_mutex


def lock_is_stale(payload: dict | None, stale_after: int) -> bool:
    # Staleness is TTL-based on purpose. A task claim outlives the CLI process
    # that created it, so PID liveness would mark every held task lock stale.
    # The PID and host are kept as diagnostics only.
    if not isinstance(payload, dict):
        return True
    try:
        updated = parse_iso(payload.get("updated_at") or payload.get("started_at"))
    except (TypeError, ValueError):
        return True
    return (now() - updated).total_seconds() > stale_after


def normalize_resource(resource: str) -> str:
    raw = resource.replace("\\", "/").strip()
    if not raw:
        raise ValueError("lock resource is empty")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError("lock resources must be repo-relative, not absolute")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw.rstrip("/") or "."


def resource_has_glob(resource: str) -> bool:
    return any(char in resource for char in "*?[")


def resources_overlap(first: str, second: str) -> bool:
    first = normalize_resource(first)
    second = normalize_resource(second)
    if first == second:
        return True
    if "." in (first, second) or "project" in (first, second):
        return True
    if resource_has_glob(first) or resource_has_glob(second):
        if fnmatch.fnmatch(first, second) or fnmatch.fnmatch(second, first):
            return True
        first_prefix = re.split(r"[*?[]", first, 1)[0].rstrip("/")
        second_prefix = re.split(r"[*?[]", second, 1)[0].rstrip("/")
        if first_prefix and (second == first_prefix or second.startswith(first_prefix + "/")):
            return True
        if second_prefix and (first == second_prefix or first.startswith(second_prefix + "/")):
            return True
        return False
    return first.startswith(second + "/") or second.startswith(first + "/")


def acquire_lock(
    resource: str,
    agent: str | None = None,
    task: str | None = None,
    ttl: int | None = None,
    force: bool = False,
) -> dict:
    ensure_dirs()
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        return {"ok": False, "holder": None, "error": str(exc)}
    default_ttl, stale_after = lock_settings()
    ttl = ttl or default_ttl
    if ttl > max_lock_ttl():
        return {"ok": False, "holder": None, "error": f"ttl must be <= {max_lock_ttl()} seconds"}
    path = os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")
    payload = {
        "resource": resource,
        "agent": agent or "unknown",
        "task": task,
        "host": HOST,
        "pid": os.getpid(),
        "started_at": iso(),
        "updated_at": iso(),
        "ttl_seconds": ttl,
    }
    try:
        with registry_mutex():
            for name in os.listdir(LOCKS_DIR):
                if not name.endswith(".lock"):
                    continue
                other_path = os.path.join(LOCKS_DIR, name)
                other = read_json(other_path)
                if not isinstance(other, dict):
                    continue
                other_resource = str(other.get("resource") or "")
                # Task claims protect task metadata ownership. They are a
                # separate namespace from file leases and must not conflict
                # with broad resources such as `project`.
                if resource.startswith("task-") or other_resource.startswith("task-"):
                    continue
                if lock_is_stale(other, stale_after):
                    if force:
                        try:
                            os.remove(other_path)
                        except OSError:
                            pass
                    continue
                try:
                    overlaps = resources_overlap(resource, other_resource)
                except ValueError:
                    overlaps = False
                if not overlaps:
                    continue
                if force:
                    try:
                        os.remove(other_path)
                    except OSError:
                        pass
                    continue
                return {"ok": False, "holder": other, "path": other_path}
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return {"ok": False, "holder": read_json(path), "path": path}
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            return {"ok": True, "lock": payload, "path": path}
    except TimeoutError as exc:
        return {"ok": False, "holder": None, "error": str(exc)}


def release_lock(
    resource: str, agent: str | None = None, force: bool = False, quiet: bool = False
) -> int:
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")
    holder = read_json(path)
    if holder is None:
        if not quiet:
            print(f"No lock held for '{resource}'.")
        return 0
    if agent and holder.get("agent") != agent and not force:
        print(
            f"Refusing to release '{resource}': held by {holder.get('agent')} "
            f"(task {holder.get('task')}). Use --force to override.",
            file=sys.stderr,
        )
        return 1
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    if not quiet:
        print(f"Released '{resource}'.")
    return 0


def heartbeat_lock(resource: str, agent: str | None = None) -> int:
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")
    holder = read_json(path)
    if holder is None:
        print(f"No lock held for '{resource}'.", file=sys.stderr)
        return 1
    if agent and holder.get("agent") != agent:
        print(f"Lock '{resource}' is held by {holder.get('agent')}.", file=sys.stderr)
        return 1
    holder["updated_at"] = iso()
    write_json_atomic(path, holder)
    print(f"Heartbeat '{resource}' at {holder['updated_at']}.")
    return 0


def list_locks(ensure: bool = True) -> list[dict]:
    if ensure:
        ensure_dirs()
    if not os.path.isdir(LOCKS_DIR):
        return []
    items = []
    for name in sorted(os.listdir(LOCKS_DIR)):
        if not name.endswith(".lock"):
            continue
        payload = read_json(os.path.join(LOCKS_DIR, name)) or {}
        payload["_file"] = name
        items.append(payload)
    return items


def lock_remaining_seconds(lock: dict) -> int | None:
    ttl = lock.get("ttl_seconds")
    try:
        updated = parse_iso(lock.get("updated_at") or lock.get("started_at"))
        age = (now() - updated).total_seconds()
    except (TypeError, ValueError):
        return None
    if not isinstance(ttl, int):
        return None
    return max(0, int(ttl - age))


def recent_refusals(limit: int = 5) -> list[dict]:
    events = [event for event in read_events() if event.get("event") == "lock_refused"]
    return events[-limit:]


def refusal_detail(event: dict) -> str:
    conflict = event.get("conflict")
    if not conflict:
        return "conflict unknown"
    holder = event.get("conflict_agent")
    return f"conflict: {conflict} held by {holder}" if holder else f"conflict: {conflict}"


def lock_status_payload(locks: list[dict]) -> list[dict]:
    """Annotate each lease with its state, remaining time and matching refusals."""
    _, stale_after = lock_settings()
    refusals = [event for event in read_events() if event.get("event") == "lock_refused"]
    payload = []
    for lock in locks:
        item = dict(lock)
        resource = str(lock.get("resource") or "")
        item["state"] = "stale" if lock_is_stale(lock, stale_after) else "held"
        item["remaining_seconds"] = lock_remaining_seconds(lock)
        item["refusals"] = [
            {
                "timestamp": event.get("timestamp"),
                "agent": event.get("agent"),
                "task": event.get("task"),
                "resource": event.get("resource"),
                "conflict": event.get("conflict"),
                "holder": event.get("conflict_agent"),
                "reason": refusal_detail(event),
            }
            for event in refusals
            if resource and str(event.get("conflict") or "") == resource
        ]
        payload.append(item)
    return payload


def print_lock_table(locks: list[dict]) -> None:
    _, stale_after = lock_settings()
    if not locks:
        print("No locks held.")
        return
    print(f"{'RESOURCE':<28} {'AGENT':<18} {'TASK':<8} {'AGE':>7}  STATE")
    for lock in locks:
        age = "?"
        state = "stale"
        try:
            updated = parse_iso(lock.get("updated_at") or lock.get("started_at"))
            seconds = int((now() - updated).total_seconds())
            age = f"{seconds}s"
            state = "stale" if lock_is_stale(lock, stale_after) else "held"
        except (TypeError, ValueError):
            pass
        print(
            f"{str(lock.get('resource'))[:28]:<28} "
            f"{str(lock.get('agent'))[:18]:<18} "
            f"{str(lock.get('task') or '-'):<8} {age:>7}  {state}"
        )
