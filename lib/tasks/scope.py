"""tasks.scope: which paths a task may touch.

Front matter keys (comma-separated globs, `**` crosses directories):

    scope_allowed:   src/auth/**, tests/auth/**
    scope_forbidden: src/payment/**

A path is a violation when it matches a forbidden glob, or when an allowed
list exists and the path matches none of it. Workspace ledger files (tasks and
specs) are exempt: they are coordination state, not product code.
"""

from __future__ import annotations

import re

from lib.core.fsio import normalize_rel_path


def split_globs(raw) -> list[str]:
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"\s*,\s*", str(raw))
    return [
        normalize_rel_path(item)
        for item in items
        if item and item.strip() not in ("", "null")
    ]


def join_globs(values) -> str | None:
    flat: list[str] = []
    for value in values or []:
        flat.extend(split_globs(value))
    return ", ".join(flat) if flat else None


def _regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(pattern: str, path: str) -> bool:
    # `lstrip("./")` used to be a character strip, so "../secret" became
    # "secret" and matched an allowed glob. Normalize lexically instead, and
    # refuse anything that escapes the repository.
    from lib.core.fsio import normalize_rel_path

    pattern = pattern.replace("\\", "/")
    path = normalize_rel_path(path)
    if path == ".." or path.startswith("../"):
        return False
    if pattern.endswith("/"):
        pattern = pattern.rstrip("/")
    # A plain path (no wildcard) is a directory or file lock: it covers the
    # path itself and everything below it. This matches the lease semantics in
    # `resources_overlap`, so a plan's `locks: ["src/api"]` can also be its
    # commit scope instead of silently refusing every file under it.
    if not any(char in pattern for char in "*?["):
        pattern = normalize_rel_path(pattern)
        return path == pattern or path.startswith(pattern + "/")
    return bool(_regex(normalize_rel_path(pattern)).match(path))


def staged_violations(meta: dict, staged: list[str], is_ledger) -> list[str]:
    """Scope violations for staged product paths.

    Ledger paths (`tasks/`, `specs/`, `config/`, decisions) are the CLI's own
    bookkeeping and are never in a task's scope. Shared by `ai git commit` and
    `ai git verify` so the two cannot disagree.
    """
    return violations(meta, [path for path in staged if not is_ledger(path)])


def violations(meta: dict, paths: list[str]) -> list[str]:
    """Return human-readable violations for `paths` against the task's scope."""
    allowed = split_globs(meta.get("scope_allowed"))
    forbidden = split_globs(meta.get("scope_forbidden"))
    if not allowed and not forbidden:
        return []
    found = []
    for path in paths:
        hit = next((g for g in forbidden if matches(g, path)), None)
        if hit:
            found.append(f"{path}: forbidden by scope `{hit}`")
        elif allowed and not any(matches(g, path) for g in allowed):
            found.append(f"{path}: outside allowed scope ({', '.join(allowed)})")
    return found
