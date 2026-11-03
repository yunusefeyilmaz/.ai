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
    CorruptStateError,
    lock_path,
    normalize_rel_path,
    read_json_checked,
    write_json_atomic,
)
from lib.core.timeutil import (
    iso,
    now,
    parse_iso,
)
from lib.runtime.dirs import ensure_dirs
from lib.runtime.events import append_event, read_events
from lib.runtime.mutex import registry_mutex

# A lock must be at least this old before the PID liveness probe is applied.
# This avoids false positives for recently claimed tasks whose owner has simply
# exited between CLI invocations (e.g. `ai start` claims and exits).
_PID_LIVENESS_MIN_AGE_SECONDS = 30


def path_covers(pattern: str, resource: str) -> bool:
    """Does the lock `pattern` (maybe a glob or a directory) cover `resource`?"""
    from lib.tasks.scope import matches

    return matches(pattern, resource) or resource.startswith(pattern.rstrip("/") + "/")


def lock_is_stale(payload: dict | None, stale_after: int) -> bool:
    # Staleness is TTL-based on purpose. A task claim outlives the CLI process
    # that created it, so PID liveness would mark every held task lock stale.
    # The PID and host are kept as diagnostics only.
    if not isinstance(payload, dict):
        return True
    try:
        updated = parse_iso(payload.get("updated_at") or payload.get("started_at"))
        # parse_iso already normalizes naive datetimes to UTC, but keep this
        # guard in case a future change removes that normalization.
        if updated.tzinfo is None:
            import datetime as dt

            updated = updated.replace(tzinfo=dt.timezone.utc)
        age = (now() - updated).total_seconds()
    except (TypeError, ValueError):
        # If we cannot parse the timestamp, treat the lock as stale so that
        # recover/clean can remove it.
        return True
    if age > stale_after:
        return True
    # Secondary liveness signal: task locks only. A crashed worker holding
    # task-XXXX should not block for the full TTL. Infrastructure locks
    # (git.index, project, tasks.index) use TTL only to preserve cross-process
    # mutual exclusion for short-lived guards such as `git begin`/`git end`.
    # Only apply when the lock is old enough that a recently-exited owner
    # (e.g. `ai start` claiming and exiting) is not a false positive.
    resource = payload.get("resource", "")
    if (
        isinstance(resource, str)
        and resource.startswith("task-")
        and age > _PID_LIVENESS_MIN_AGE_SECONDS
    ):
        host = payload.get("host")
        pid = payload.get("pid")
        if host == HOST and isinstance(pid, int) and pid > 0 and not _pid_alive(pid):
            return True
    return False


def _pid_alive(pid: int) -> bool:
    """Return True if `pid` is still running on this machine.

    Used only as a secondary liveness signal when host == HOST. PID reuse is
    handled by keeping TTL as the primary cross-host staleness signal.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it.
        return True
    except OSError:
        return False
    return True


def normalize_resource(resource: str) -> str:
    raw = normalize_rel_path(resource)
    if not raw:
        raise ValueError("lock resource is empty")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError("lock resources must be repo-relative, not absolute")
    if raw == ".." or raw.startswith("../"):
        raise ValueError("lock resources must stay inside the repository")
    return raw.rstrip("/") or "."


def resource_has_glob(resource: str) -> bool:
    return any(char in resource for char in "*?[")


def resources_overlap(first: str, second: str) -> bool:
    first = normalize_resource(first)
    second = normalize_resource(second)
    # If either resource is corrupt (e.g. None after _corrupt_payload), treat as conflicting
    if first is None or second is None:
        return True
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


def _corrupt_payload(path: str, error: Exception) -> dict:
    return {
        "resource": None,
        "agent": "unknown",
        "corrupt": True,
        "error": f"{os.path.basename(path)} is not valid JSON: {error}",
    }


def _read_holder(path: str) -> dict | None:
    """Read a lock payload; a corrupt file becomes a conflict, never "free"."""
    try:
        payload = read_json_checked(path)
    except CorruptStateError as exc:
        return _corrupt_payload(path, exc)
    return payload if isinstance(payload, dict) else None


def _write_lock_file(path: str, payload: dict) -> None:
    """Create a lock file with fsync so a crash cannot leave partial JSON."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        os.write(descriptor, text.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def effective_holder(resource: str) -> dict:
    """The live holder of `resource`, or {} when it is free or stale.

    `ai task done` used to read the lease file raw and refuse whenever one
    existed, so a crashed reviewer's stale lock kept a finished task in review
    forever even though `ai task claim` and `ai recover` already treated the same
    lock as gone. One helper now answers "who really holds this?".

    A corrupt lease is returned with ``corrupt: True`` instead of ``{}``: it
    cannot prove the resource is free, so callers must still fail closed.
    """
    try:
        holder = _read_holder(lock_path(normalize_resource(resource)))
    except ValueError as exc:
        return {"corrupt": True, "agent": "unknown", "error": str(exc)}
    if not holder:
        return {}
    if holder.get("corrupt"):
        return holder
    try:
        _, stale_after = lock_settings()
    except (OSError, ValueError):
        # A broken config is reported by `ai doctor`; staleness still needs a value.
        stale_after = 3600
    return {} if lock_is_stale(holder, stale_after) else holder


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
    path = lock_path(resource)
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
    forced: list[dict] = []  # emitted after the registry mutex is released
    try:
        with registry_mutex():
            # A stale lock on this exact resource is replaceable; TTL staleness
            # exists so a crashed worker does not need `--force` forever.
            if os.path.exists(path):
                holder = _read_holder(path)
                if holder is not None:
                    same_resource = holder.get("resource") in (None, resource)
                    if not same_resource:
                        # A digest collision should never happen; stay safe.
                        return {"ok": False, "holder": holder, "path": path}
                    if holder.get("corrupt"):
                        if not force:
                            return {"ok": False, "holder": holder, "path": path}
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        forced.append(dict(
                            event="lock_forced", resource=resource, agent=agent, task=task,
                            previous_agent="corrupt", previous_resource=holder.get("resource") or resource,
                        ))
                    elif force:
                        # Explicit --force always takes over, leaving a lock_forced trail.
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        forced.append(dict(
                            event="lock_forced", resource=resource, agent=agent, task=task,
                            previous_agent=holder.get("agent"), previous_task=holder.get("task"),
                            previous_resource=holder.get("resource") or resource,
                        ))
                    elif lock_is_stale(holder, stale_after):
                        # A stale lock on this exact resource is replaceable; TTL
                        # staleness exists so a crashed worker does not need
                        # `--force` forever.
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                        forced.append(dict(
                            event="lock_replaced_stale",
                            resource=resource, agent=agent, task=task,
                            previous_agent=holder.get("agent"),
                            previous_task=holder.get("task"),
                        ))
                    else:
                        return {"ok": False, "holder": holder, "path": path}
            for name in os.listdir(LOCKS_DIR):
                if not name.endswith(".lock") or name == os.path.basename(path):
                    continue
                other_path = os.path.join(LOCKS_DIR, name)
                other = _read_holder(other_path)
                if other is None:
                    continue
                other_resource = str(other.get("resource") or "")
                if other.get("corrupt"):
                    # Fail closed: a damaged lease may be protecting a resource
                    # we cannot see, so it must not read as "no conflict".
                    if force:
                        try:
                            os.remove(other_path)
                        except OSError:
                            pass
                        forced.append(dict(
                            event="lock_forced", resource=resource, agent=agent, task=task,
                            previous_agent="corrupt", previous_resource=name,
                        ))
                        continue
                    return {"ok": False, "holder": other, "path": other_path}
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
                # Already covered by a broader lock the same agent holds for the same
                # task (e.g. the task's declared `locks`): nothing more to take.
                if (
                    other.get("agent") == agent
                    and str(other.get("task") or "") == str(task or "")
                    and path_covers(other_resource, resource)
                ):
                    return {"ok": True, "lock": other, "path": other_path, "covered_by": other_resource}
                if force:
                    try:
                        os.remove(other_path)
                    except OSError:
                        pass
                    # A forced takeover of a live lease must leave a trail.
                    forced.append(dict(
                        event="lock_forced", resource=resource, agent=agent, task=task,
                        previous_agent=other.get("agent"), previous_task=other.get("task"),
                        previous_resource=other_resource,
                    ))
                    continue
                return {"ok": False, "holder": other, "path": other_path}
            try:
                _write_lock_file(path, payload)
            except FileExistsError:
                return {"ok": False, "holder": _read_holder(path), "path": path}
            # Verify the bytes landed intact; a truncated lock must not be
            # mistaken for a valid one by the next reader.
            written = _read_holder(path)
            if not isinstance(written, dict) or written.get("corrupt") or written.get("resource") != resource:
                try:
                    os.remove(path)
                except OSError:
                    pass
                return {"ok": False, "holder": written, "error": "could not write a valid lock file"}
            return {"ok": True, "lock": payload, "path": path}
    except TimeoutError as exc:
        return {"ok": False, "holder": None, "error": str(exc)}
    finally:
        for fields in forced:
            event = fields.pop("event", "lock_forced")
            append_event(event, **fields)


def release_lock(
    resource: str, agent: str | None = None, force: bool = False, quiet: bool = False
) -> int:
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = lock_path(resource)
    try:
        with registry_mutex():
            holder = _read_holder(path)
            if holder is not None and holder.get("resource") not in (None, resource):
                holder = None  # a different resource that merely shares the file name
            if holder is None:
                if not quiet:
                    print(f"No lock held for '{resource}'.")
                return 0
            if holder.get("corrupt"):
                if not force:
                    print(f"Refusing to release '{resource}': {holder.get('error')}. Use --force to remove it.", file=sys.stderr)
                    return 1
            elif agent and holder.get("agent") != agent and not force:
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
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not quiet:
        print(f"Released '{resource}'.")
    return 0


def heartbeat_lock(resource: str, agent: str | None = None, quiet: bool = False) -> int:
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = lock_path(resource)
    try:
        with registry_mutex():
            holder = _read_holder(path)
            if holder is not None and holder.get("resource") not in (None, resource):
                holder = None  # a different resource that merely shares the file name
            def warn(message: str) -> None:
                if not quiet:
                    print(message, file=sys.stderr)

            if holder is None:
                warn(f"No lock held for '{resource}'.")
                return 1
            if holder.get("corrupt"):
                warn(f"Lock '{resource}' is corrupt: {holder.get('error')}")
                return 1
            if agent and holder.get("agent") != agent:
                warn(f"Lock '{resource}' is held by {holder.get('agent')}.")
                return 1
            holder["updated_at"] = iso()
            write_json_atomic(path, holder)
            if not quiet:
                print(f"Heartbeat '{resource}' at {holder['updated_at']}.")
            return 0
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def list_locks(ensure: bool = True) -> list[dict]:
    if ensure:
        ensure_dirs()
    if not os.path.isdir(LOCKS_DIR):
        return []
    items = []
    for name in sorted(os.listdir(LOCKS_DIR)):
        if not name.endswith(".lock"):
            continue
        path = os.path.join(LOCKS_DIR, name)
        try:
            payload = _read_holder(path) or {}
        except OSError:
            payload = {}
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
        item["state"] = "corrupt" if lock.get("corrupt") else (
            "stale" if lock_is_stale(lock, stale_after) else "held"
        )
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
        if lock.get("corrupt"):
            state = "corrupt"
        else:
            state = "stale"
            try:
                updated = parse_iso(lock.get("updated_at") or lock.get("started_at"))
                seconds = int((now() - updated).total_seconds())
                age = f"{seconds}s"
                state = "stale" if lock_is_stale(lock, stale_after) else "held"
            except (TypeError, ValueError):
                pass
        print(
            f"{str(lock.get('resource') or '?')[:28]:<28} "
            f"{str(lock.get('agent'))[:18]:<18} "
            f"{str(lock.get('task') or '-'):<8} {age:>7}  {state}"
        )
