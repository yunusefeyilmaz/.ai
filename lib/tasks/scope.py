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


def split_globs(raw) -> list[str]:
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"\s*,\s*", str(raw))
    return [item.strip().replace("\\", "/").lstrip("./") for item in items if item and item.strip() not in ("", "null")]


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
    path = path.replace("\\", "/").lstrip("./")
    if pattern.endswith("/"):
        pattern += "**"
    return bool(_regex(pattern).match(path))


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
