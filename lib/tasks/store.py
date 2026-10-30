"""tasks.store: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import re

from lib.core.paths import (
    TASKS_DIR,
)
from lib.core.fsio import (
    normalize_id,
    read_text,
    write_text_atomic,
)


def parse_value(raw: str):
    value = raw.strip()
    if value in ("", "null", "~", "None"):
        return None
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.startswith('"'):
        try:
            return json.loads(value)
        except ValueError:
            return value.strip('"')
    return value


def format_value(value) -> str:
    if value is None or value == "":
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", text) and not text.startswith("-"):
        return text
    return json.dumps(text, ensure_ascii=False)


def parse_task(path: str) -> tuple[dict, str]:
    text = read_text(path)
    if not text.startswith("---"):
        return {}, text
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    head = rest[:end].strip("\n")
    body = rest[end + 4 :].lstrip("\n")
    meta: dict = {}
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = parse_value(value)
    return meta, body


def write_task(path: str, meta: dict, body: str) -> None:
    order = ["id", "title", "status", "owner", "priority", "spec", "created", "updated", "lock"]
    keys = [key for key in order if key in meta] + [key for key in meta if key not in order]
    lines = ["---"]
    for key in keys:
        lines.append(f"{key}: {format_value(meta[key])}")
    lines.append("---")
    write_text_atomic(path, "\n".join(lines) + "\n\n" + body.lstrip("\n").rstrip("\n") + "\n")


def task_paths(folder: str) -> list[str]:
    directory = os.path.join(TASKS_DIR, folder)
    if not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.endswith(".md") and not name.startswith("TEMPLATE")
    ]


def find_task(task_id: str) -> str | None:
    wanted = normalize_id(task_id)
    for folder in ("active", "done"):
        for path in task_paths(folder):
            name = os.path.basename(path)
            if name.startswith(wanted + "-") or name.startswith(wanted + "."):
                return path
    return None


def load_tasks() -> list[dict]:
    items = []
    for folder in ("active", "done"):
        for path in task_paths(folder):
            meta, body = parse_task(path)
            meta["_path"] = path
            meta["_folder"] = folder
            meta["_body"] = body
            items.append(meta)
    return items


def task_owner_error(meta: dict, agent: str, force: bool = False) -> str | None:
    owner = meta.get("owner")
    if owner and owner != agent and not force:
        return f"Task {meta.get('id')} is owned by {owner}."
    return None


def board_dependencies(task: dict) -> list[str]:
    raw = task.get("depends_on")
    if raw is None or str(raw).strip() in ("", "null", "None"):
        return []
    parts = [str(item) for item in raw] if isinstance(raw, (list, tuple)) else re.split(r"[,\s]+", str(raw))
    return [normalize_id(part) for part in parts if part and part.strip() not in ("", "null")]


def dependency_blockers(meta: dict) -> list[str]:
    blockers = []
    depends = meta.get("depends_on")
    if not depends:
        return blockers
    for dependency in re.split(r"[,\s]+", str(depends)):
        dependency = dependency.strip()
        if not dependency:
            continue
        dep_path = find_task(dependency)
        if not dep_path:
            blockers.append(f"unknown task {dependency}")
            continue
        dep_meta, _ = parse_task(dep_path)
        if dep_meta.get("status") != "done":
            blockers.append(f"{dependency} is {dep_meta.get('status') or 'unknown'}")
    return blockers


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def resolve_task_id(task_id: str | None) -> str | None:
    if task_id:
        path = find_task(task_id)
        return str(parse_task(path)[0].get("id")) if path else None
    active = [task for task in load_tasks() if task["_folder"] == "active"]
    if not active:
        return None
    active.sort(key=lambda item: str(item.get("updated") or ""), reverse=True)
    return str(active[0].get("id"))
