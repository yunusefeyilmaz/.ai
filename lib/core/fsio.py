"""core.fsio: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def write_json_atomic(path: str, payload) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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


def normalize_id(task_id: str) -> str:
    digits = "".join(ch for ch in task_id if ch.isdigit())
    return digits.zfill(4) if digits else task_id
