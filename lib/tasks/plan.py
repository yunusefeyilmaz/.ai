"""tasks.plan: turn one plan document into many linked tasks.

The chief writes a single JSON file instead of N shell commands; symbolic keys
become real task ids, dependencies are validated (unknown keys, cycles) before
anything is written, and file locks that can collide between unordered tasks are
reported.

    {"tasks": [
      {"key": "api", "title": "Build the REST API", "priority": "high",
       "intent": "why", "acceptance": ["POST /login returns a token"],
       "locks": ["src/api/**"], "allow": ["src/api/**"], "forbid": [],
       "depends_on": [], "spec": true, "tests": true},
      {"key": "ui", "title": "Login form", "depends_on": ["api"], "locks": ["src/ui/**"]}
    ]}

`locks` are acquired automatically when a worker claims the task. `allow`
defaults to `locks`. `tests` defaults to the project preference `testing.writeTests`.
"""

from __future__ import annotations

import re

from lib.config.settings import preference
from lib.runtime.leases import resources_overlap
from lib.tasks import lifecycle
from lib.tasks import scope as task_scope

KEY = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
EXAMPLE = {
    "tasks": [
        {"key": "api", "title": "Build the REST API", "priority": "high",
         "intent": "Why this exists and for whom.",
         "acceptance": ["Observable criterion one"], "locks": ["src/api/**"], "depends_on": []},
        {"key": "ui", "title": "Login form", "priority": "medium",
         "acceptance": ["Observable criterion"], "locks": ["src/ui/**"], "depends_on": ["api"]},
    ]
}


def _list(value) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else task_scope.split_globs(value)


def validate(plan) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Nothing is written."""
    errors: list[str] = []
    warnings: list[str] = []
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return ['plan must be {"tasks": [ ... ]} with at least one task'], warnings
    keys: dict[str, dict] = {}
    for index, item in enumerate(tasks, 1):
        if not isinstance(item, dict):
            errors.append(f"task #{index} is not an object")
            continue
        key = str(item.get("key") or "")
        if not KEY.match(key):
            errors.append(f"task #{index}: key must match [a-z0-9][a-z0-9_-]* (got '{key}')")
        elif key in keys:
            errors.append(f"duplicate key '{key}'")
        keys[key] = item
        if not str(item.get("title") or "").strip():
            errors.append(f"task '{key}': title is required")
        if item.get("priority", "medium") not in ("low", "medium", "high"):
            errors.append(f"task '{key}': priority must be low, medium or high")
    for key, item in keys.items():
        for dep in _list(item.get("depends_on")):
            if dep not in keys:
                errors.append(f"task '{key}' depends on unknown key '{dep}'")
            elif dep == key:
                errors.append(f"task '{key}' depends on itself")
    if not errors and not _order(list(keys.values())):
        errors.append("dependency cycle between tasks")
    if not errors:
        warnings = _lock_warnings(list(keys.values()))
    return errors, warnings


def _order(items: list[dict]) -> list[dict] | None:
    remaining = list(items)
    placed: list[dict] = []
    done: set[str] = set()
    while remaining:
        ready = [t for t in remaining if all(d in done for d in _list(t.get("depends_on")))]
        if not ready:
            return None
        for task in ready:
            placed.append(task)
            done.add(task["key"])
            remaining.remove(task)
    return placed


def _ancestors(key: str, by_key: dict, seen: set | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    for dep in _list(by_key[key].get("depends_on")):
        if dep not in seen:
            seen.add(dep)
            _ancestors(dep, by_key, seen)
    return seen


def _lock_warnings(items: list[dict]) -> list[str]:
    by_key = {t["key"]: t for t in items}
    warnings = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a["key"] in _ancestors(b["key"], by_key) or b["key"] in _ancestors(a["key"], by_key):
                continue
            for x in _list(a.get("locks")):
                for y in _list(b.get("locks")):
                    try:
                        clash = resources_overlap(x, y)
                    except ValueError:
                        clash = False
                    if clash:
                        warnings.append(
                            f"'{a['key']}' and '{b['key']}' both lock overlapping paths ({x} / {y}) "
                            "without a dependency: they cannot run in parallel. Add depends_on or split the paths."
                        )
    return warnings


def apply(plan: dict, actor: str | None = None) -> list[dict]:
    """Create the tasks (already validated) in dependency order."""
    writes_tests = bool(preference("testing.writeTests", True))
    ids: dict[str, str] = {}
    created: list[dict] = []
    for item in _order(plan["tasks"]) or []:
        locks = _list(item.get("locks"))
        allow = _list(item.get("allow")) or locks
        acceptance = _list(item.get("acceptance"))
        if item.get("tests", writes_tests):
            acceptance = acceptance + ["Tests cover the new behavior and pass"]
        deps = [ids[d] for d in _list(item.get("depends_on"))]
        result = lifecycle.create_task(
            str(item["title"]), str(item.get("priority", "medium")), None,
            ", ".join(deps) or None,
            make_spec=bool(item.get("spec", True)),
            scope_allowed=task_scope.join_globs(allow),
            scope_forbidden=task_scope.join_globs(_list(item.get("forbid"))),
            actor=actor, locks=task_scope.join_globs(locks),
            intent=str(item.get("intent") or "") or None, acceptance=acceptance or None,
        )
        ids[item["key"]] = result["id"]
        created.append({"key": item["key"], "id": result["id"], "title": item["title"],
                        "depends_on": deps, "locks": locks})
    return created
