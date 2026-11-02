"""tasks.store: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import re
import sys

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


def _parse_frontmatter(text: str) -> tuple[dict, str, list[str]]:
    """Parse the front matter without silently guessing.

    Returns (meta, body, problems). `problems` names what the old parser used to
    swallow: an unterminated block, a line without a colon, a duplicate key and
    a stray indented continuation. `|`/`>` block scalars are joined instead of
    being dropped.
    """
    problems: list[str] = []
    if not text.startswith("---"):
        return {}, text, ["missing front matter"]
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text, ["unterminated front matter (no closing ---)"]
    head = rest[:end].strip("\n")
    body = rest[end + 4 :].lstrip("\n")
    meta: dict = {}
    block_key: str | None = None
    block_lines: list[str] = []
    block_separator = " "

    def flush_block() -> None:
        nonlocal block_key, block_lines
        if block_key is not None:
            meta[block_key] = block_separator.join(block_lines)
            block_key = None
            block_lines = []

    for line in head.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            if block_key is not None:
                block_lines.append(stripped)
            else:
                problems.append(f"stray indented line: {stripped!r}")
            continue
        if ":" not in line:
            problems.append(f"line without a colon: {stripped!r}")
            continue
        flush_block()
        key, value = line.split(":", 1)
        key = key.strip()
        if key in meta:
            problems.append(f"duplicate key: {key}")
        raw = value.strip()
        if raw in ("|", "|-", ">", ">-"):
            block_key = key
            block_separator = "\n" if raw.startswith("|") else " "
            meta.setdefault(key, None)
            continue
        meta[key] = parse_value(value)
    flush_block()
    return meta, body, problems


def parse_task(path: str) -> tuple[dict, str]:
    meta, body, _ = _parse_frontmatter(read_text(path))
    return meta, body


def frontmatter_problems(path: str) -> list[str]:
    """Structural problems in a task file's front matter (empty = fine)."""
    try:
        _, _, problems = _parse_frontmatter(read_text(path))
    except OSError as exc:
        return [f"unreadable: {exc}"]
    return problems


def validate_task_meta(meta: dict) -> list[str]:
    """Return a list of validation errors for a task meta dict.

    Required fields: id, title, status.  An empty list means the task is valid.
    """
    errors: list[str] = []
    task_id = meta.get("id")
    if not task_id or not str(task_id).strip():
        errors.append("missing required field: id")
    title = meta.get("title")
    if not title or not str(title).strip():
        errors.append("missing required field: title")
    status = meta.get("status")
    valid_statuses = {"todo", "in_progress", "review", "changes_requested", "blocked", "done"}
    if status not in valid_statuses:
        errors.append(f"missing or invalid status: {status!r}")
    return errors


# The one schema every reader relies on: `tasks/TEMPLATE.md` and
# `docs/conventions.md` list the same fields in the same order.
FRONTMATTER_ORDER = (
    "id", "title", "status", "owner", "priority", "spec", "depends_on",
    "scope_allowed", "scope_forbidden", "locks", "branch", "worktree",
    "created", "updated", "lock",
)


def write_task(path: str, meta: dict, body: str) -> None:
    order = list(FRONTMATTER_ORDER)
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
    try:
        wanted = normalize_id(task_id)
    except ValueError:
        return None
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
            errors = validate_task_meta(meta) + frontmatter_problems(path)
            if errors:
                print(
                    f"WARN  skipping invalid task file {path}: {'; '.join(errors)}",
                    file=sys.stderr,
                )
                continue
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
    out = []
    for part in parts:
        if not part or part.strip() in ("", "null"):
            continue
        try:
            out.append(normalize_id(part))
        except ValueError:
            continue
    return out


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
