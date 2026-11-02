"""core.fsio: split out of the former monolithic ai.py.

Every state write goes through this module so a crash cannot leave a
half-written JSON/Markdown file behind: content is flushed and fsynced before
the atomic rename, and the rename is retried briefly on Windows where antivirus
and indexers hold destination files open.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import time


class CorruptStateError(ValueError):
    """A state file exists but cannot be parsed."""


def read_json(path: str, default=None):
    """Return the parsed payload, or `default` when missing.

    Raises `CorruptStateError` when the file exists but is unreadable or is not
    valid JSON. Callers that guard shared state should use :func:`read_json_checked`
    instead, which fails closed instead of silently treating a damaged lock as "free".
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise CorruptStateError(f"{path}: {exc}") from exc


def read_json_checked(path: str):
    """Return the parsed payload, None when the file does not exist.

    Raises `CorruptStateError` when the file exists but is unreadable or is not
    valid JSON. Callers that guard shared state use this to fail closed instead
    of silently treating a damaged lock as "free".
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise CorruptStateError(f"{path}: {exc}") from exc


def _sync_directory(directory: str) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _replace_with_retry(source: str, target: str, attempts: int = 10) -> None:
    """os.replace with a short retry for Windows sharing violations."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def write_json_atomic(path: str, payload) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
        _sync_directory(directory)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "resource"


def lock_path(resource: str) -> str:
    """Lock file of a resource.

    `safe_name` alone maps `src/a` and `src-a` to the same name, so two different
    resources would share one lock file. A short digest of the exact resource
    keeps names readable and unique.
    """
    from lib.core.paths import LOCKS_DIR

    digest = hashlib.sha1(resource.encode("utf-8")).hexdigest()[:8]
    return os.path.join(LOCKS_DIR, f"{safe_name(resource)}-{digest}.lock")


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "task"


def normalize_rel_path(path: str) -> str:
    """Lexically normalize a repo-relative path (`/` separated, no `.`/`..`)."""
    raw = str(path).replace("\\", "/").strip()
    absolute = raw.startswith("/") or bool(re.match(r"^[A-Za-z]:/", raw))
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not absolute:
                parts.append("..")
            continue
        parts.append(part)
    result = "/".join(parts) or "."
    return "/" + result if absolute else result


_TASK_ID = re.compile(r"^(?:T-|task-)?([0-9]{1,9})$", re.IGNORECASE)


def normalize_id(task_id: str) -> str:
    """Canonical four-digit task id; rejects anything that is not numeric.

    Task ids end up inside file names, so a value such as `../../etc/passwd`
    must never be joined into a path. Only pure numeric ids (optionally
    prefixed with `T-` or `task-`) are accepted, and leading zeros do not
    let a caller smuggle in an arbitrarily long value.

    The regex is strict: the entire id (minus the optional T-/task- prefix)
    must be digits only, 1-9 characters long. This prevents collisions such as
    "12" and "012" both normalizing to "0012" or "T-12a" being accepted.
    """
    text = str(task_id).strip()
    match = _TASK_ID.fullmatch(text)
    if not match:
        raise ValueError(f"invalid task id: {task_id!r}")
    digits = match.group(1).lstrip("0") or "0"
    if len(digits) > 4:
        raise ValueError(f"invalid task id: {task_id!r} — id exceeds 4 digits")
    return f"{int(digits):04d}"
