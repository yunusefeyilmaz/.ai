"""ui.data: one read-only snapshot of the whole workspace for the dashboard.

Everything is read through the same modules the CLI commands use (tasks.store,
runtime.leases, runtime.events, ...), so the dashboard can never disagree with
`ai status`, `ai now` or `ai doctor`. Nothing here writes state. Each section is
loaded independently: one corrupt file degrades one panel, not the whole UI.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import re
import time

from lib.config import preferences
from lib.config import roles as roles_cfg
from lib.config.settings import load_config, lock_settings
from lib.core.fsio import read_text
from lib.core.paths import (
    CHECKPOINT_DIR,
    MANIFEST_PATH,
    PROJECT,
    SPECS_ACTIVE_DIR,
    SPECS_DONE_DIR,
    VERSION,
    WORKSPACE,
)
from lib.core.timeutil import now, parse_iso
from lib.decisions import adr
from lib.git import repo
from lib.runtime import checkpoints as ckpt
from lib.runtime import evidence, health, leases, overview
from lib.runtime.events import read_events
from lib.runtime.metrics import collect_metrics
from lib.tasks import board, history, scope, store

STATUS_ORDER = ["todo", "in_progress", "changes_requested", "review", "blocked", "done"]
# Order used in lists: what needs attention first, waiting work after, finished last.
LIST_ORDER = ["in_progress", "changes_requested", "review", "blocked", "todo", "done"]
# How much of a task's journey each status represents (used for the weighted progress figure).
STATUS_WEIGHT = {"todo": 0.0, "blocked": 0.0, "in_progress": 0.4, "changes_requested": 0.5, "review": 0.8, "done": 1.0}

_CRITERION = re.compile(r"^\s*- \[(?P<mark>[ xX])\]\s*(?P<text>.*)$")


def criteria_state(text: str) -> list[tuple[bool, str]]:
    """Acceptance-criteria checkboxes as (checked, text), in order."""
    match = re.search(r"## Acceptance criteria\n(.*?)(?:\n## |\Z)", text, flags=re.S)
    if not match:
        return []
    out = []
    for line in match.group(1).splitlines():
        item = _CRITERION.match(line)
        if item:
            out.append((item.group("mark").lower() == "x", item.group("text").strip()))
    return out


def _section(text: str, name: str) -> str:
    match = re.search(rf"## {re.escape(name)}\n(.*?)(?:\n## |\Z)", text, flags=re.S)
    if not match:
        return ""
    body = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.S)
    return "\n".join(line.rstrip() for line in body.strip().splitlines())


def _age_seconds(value) -> float | None:
    try:
        return (now() - parse_iso(str(value))).total_seconds()
    except (TypeError, ValueError):
        return None


def _quiet(func, *args, **kwargs):
    """Call a CLI-layer function whose WARN lines go to stderr; return (result, warnings)."""
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        result = func(*args, **kwargs)
    return result, [line for line in buffer.getvalue().splitlines() if line.strip()]


# --- sections ---------------------------------------------------------------

def _load_specs() -> list[dict]:
    specs = []
    for folder, directory in (("active", SPECS_ACTIVE_DIR), ("done", SPECS_DONE_DIR)):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".md") or name.startswith(("TEMPLATE", ".")):
                continue
            path = os.path.join(directory, name)
            try:
                meta, body = store.parse_task(path)
                text = body
            except OSError:
                continue
            title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), name[:-3])
            crit = criteria_state(text)
            real = [(done, item) for done, item in crit if item and not item.lower().startswith(
                ("criterion one", "criterion two", "existing behavior x", "observable criterion"))]
            specs.append({
                "file": name, "folder": folder, "path": path,
                "ref": f"specs/{folder}/{name}",
                "title": title, "status": str(meta.get("status") or "draft"),
                "task": str(meta.get("task")) if meta.get("task") not in (None, "null") else None,
                "approved_by": meta.get("approved_by"), "approved_on": meta.get("approved_on"),
                "criteria": crit, "real_criteria": real,
                "criteria_done": sum(1 for done, _ in real if done), "criteria_total": len(real),
                "template": bool(crit) and not real,
                "intent": _section(text, "Intent"), "changed": _section(text, "Behavior"),
                "out_of_scope": _section(text, "Out of scope"), "body": text,
            })
    return specs


def _task_view(task: dict, specs_by_ref: dict, specs_by_task: dict, head: str | None,
               waiting: dict, stale_after: int) -> dict:
    body = task.get("_body") or ""
    ref = str(task.get("spec") or "")
    spec = specs_by_ref.get(ref.replace("\\", "/").lstrip("./")) or specs_by_task.get(str(task.get("id")))
    crit = spec["criteria"] if spec else criteria_state(body)
    real = spec["real_criteria"] if spec else [(d, c) for d, c in crit if c]
    task_id = str(task.get("id"))
    verdict = evidence.evaluate(task_id, head) if task["_folder"] == "active" else {"state": "n/a", "summary": ""}
    ckpt_age = ckpt.checkpoint_age_minutes(task_id) if task["_folder"] == "active" else None
    return {
        "id": task_id, "title": str(task.get("title") or ""), "status": str(task.get("status") or "todo"),
        "folder": task["_folder"], "owner": task.get("owner"), "priority": str(task.get("priority") or "medium"),
        "spec_ref": ref or None, "spec": spec,
        "depends_on": store.board_dependencies(task), "waiting_on": waiting.get(task_id, "-"),
        "locks": scope.split_globs(task.get("locks")),
        "scope_allowed": scope.split_globs(task.get("scope_allowed")),
        "scope_forbidden": scope.split_globs(task.get("scope_forbidden")),
        "branch": task.get("branch"), "worktree": task.get("worktree"),
        "created": task.get("created"), "updated": task.get("updated"),
        "submitted_by": task.get("submitted_by"), "reviewed_by": task.get("reviewed_by"),
        "changes_requested_by": task.get("changes_requested_by"),
        "age_seconds": _age_seconds(task.get("created")), "idle_seconds": _age_seconds(task.get("updated")),
        "criteria": crit, "criteria_done": sum(1 for d, _ in real if d), "criteria_total": len(real),
        "intent": _section(body, "Intent"), "plan": _section(body, "Plan"), "notes": _section(body, "Notes"),
        "log": history.parse(body), "evidence": verdict.get("state"), "evidence_summary": verdict.get("summary"),
        "checkpoint_minutes": ckpt_age, "stale_after": stale_after,
    }


def _load_checkpoints() -> list[dict]:
    items = []
    if not os.path.isdir(CHECKPOINT_DIR):
        return items
    for name in sorted(os.listdir(CHECKPOINT_DIR)):
        if not name.endswith(".md"):
            continue
        task_id = name[:-3]
        meta = {}
        try:
            data = ckpt.read_checkpoint(task_id)
            meta = data[0] if data else {}
        except OSError:
            pass
        sections = ckpt.checkpoint_sections(task_id) if meta else {}
        items.append({
            "task": task_id, "agent": meta.get("agent"), "reason": meta.get("reason"),
            "percent": meta.get("percent"), "age_minutes": ckpt.checkpoint_age_minutes(task_id),
            "next": sections.get("next", ""), "status": sections.get("status", ""),
        })
    return items


def _git_section() -> dict:
    state = repo.git_state()
    cfg = repo.git_config()
    info = {
        "repo": bool(state.get("repo")), "branch": state.get("branch"), "head": (state.get("head") or "")[:8] or None,
        "dirty": list(state.get("dirty") or []), "staged": list(state.get("staged") or []),
        "integration": cfg["integration"], "production": cfg["production"], "isolation": cfg["isolation"],
        "merge": cfg["merge"], "ahead": None, "commits": [], "branches": [],
    }
    if info["repo"] and state.get("head"):
        info["ahead"] = repo.commits_ahead(cfg["integration"]) if repo.branch_exists(cfg["integration"]) else None
        code, out, _ = repo.run_git(["log", "--pretty=format:%h\x1f%an\x1f%ar\x1f%s\x1f%D", "-n", "14"])
        if code == 0 and out:
            for line in out.splitlines():
                parts = line.split("\x1f")
                if len(parts) >= 5:
                    info["commits"].append({"hash": parts[0], "author": parts[1], "when": parts[2],
                                            "subject": parts[3], "refs": parts[4]})
        code, out, _ = repo.run_git(["branch", "--format=%(refname:short)"])
        if code == 0:
            info["branches"] = [line.strip() for line in out.splitlines() if line.strip()]
    return info


def _events_section(limit: int = 300) -> dict:
    events = read_events()
    today = now().date()
    days = [0] * 28
    per_agent: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for event in events:
        try:
            age = (today - parse_iso(str(event["timestamp"])).date()).days
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age < 28:
            days[27 - age] += 1
        if event.get("agent"):
            per_agent[str(event["agent"])] = per_agent.get(str(event["agent"]), 0) + 1
        kinds[str(event.get("event"))] = kinds.get(str(event.get("event")), 0) + 1
    return {"recent": events[-limit:], "total": len(events), "per_day": days, "per_agent": per_agent, "kinds": kinds}


def _adapters() -> list[dict]:
    items = []
    base = os.path.join(WORKSPACE, "adapters")
    if not os.path.isdir(base):
        return items
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name, "adapter.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        entry = str(meta.get("entry") or "")
        wired = bool(entry) and os.path.exists(os.path.join(PROJECT, entry))
        items.append({"name": name, "tool": meta.get("tool") or name, "entry": entry,
                      "supports": meta.get("supports") or [], "wired": wired})
    return items


def _agents(tasks: list[dict], locks: list[dict], events: list[dict], config: dict, checkpoints: list[dict]) -> list[dict]:
    names: dict[str, dict] = {}

    def entry(name) -> dict:
        key = str(name)
        return names.setdefault(key, {"name": key, "roles": None, "tasks": [], "reviews": [], "locks": 0,
                                      "events": 0, "last": None, "last_event": None, "checkpoints": 0})

    for key in (config.get("team") or {}):
        if key != "*":
            entry(key)
    for task in tasks:
        if task["folder"] == "done":
            continue
        for field, bucket in (("owner", "tasks"), ("submitted_by", "reviews"), ("reviewed_by", "reviews"),
                              ("changes_requested_by", "reviews")):
            if task.get(field):
                row = entry(task[field])
                if task["id"] not in row[bucket]:
                    row[bucket].append(task["id"])
    for lock in locks:
        if lock.get("agent") and lock.get("agent") != "unknown":
            entry(lock["agent"])["locks"] += 1
    for event in events:
        agent = event.get("agent")
        if agent:
            row = entry(agent)
            row["events"] += 1
            row["last"] = event.get("timestamp")
            row["last_event"] = event.get("event")
    for item in checkpoints:
        if item.get("agent"):
            entry(item["agent"])["checkpoints"] += 1
    for name, row in names.items():
        row["roles"] = roles_cfg.roles_of(name, config)
        row["idle_seconds"] = _age_seconds(row["last"])
    return sorted(names.values(), key=lambda row: (-len(row["tasks"]), -row["events"], row["name"]))


# --- the snapshot -----------------------------------------------------------

def load_snapshot(role: str | None = None, agent: str | None = None, deep: bool = True) -> dict:
    """Read the workspace. `deep=False` skips the slow doctor run and reuses nothing."""
    started = time.time()
    snap: dict = {"errors": [], "warnings": [], "taken_at": now().isoformat(), "demo": False}

    def guard(name: str, default, func):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - one broken section must not kill the dashboard
            snap["errors"].append(f"{name}: {exc}")
            return default

    config = guard("config", {}, load_config)
    snap["config"] = config
    snap["project"] = {
        "name": config.get("name") or os.path.basename(PROJECT), "path": PROJECT, "workspace": WORKSPACE,
        "version": VERSION, "mode": config.get("mode", "lite"),
    }
    raw_tasks, warnings = guard("tasks", ([], []), lambda: _quiet(store.load_tasks))
    snap["warnings"].extend(warnings)
    git = guard("git", {"repo": False, "dirty": [], "commits": [], "branches": [], "branch": None, "head": None,
                        "ahead": None, "staged": [], "integration": "develop", "production": "master",
                        "isolation": "branch", "merge": "no-ff"}, _git_section)
    snap["git"] = git

    specs = guard("specs", [], _load_specs)
    by_ref = {spec["ref"]: spec for spec in specs}
    by_task = {spec["task"]: spec for spec in specs if spec["task"]}
    full_head = guard("head", None, lambda: repo.git_state().get("head"))
    rows = guard("board", [], lambda: board.board_task_rows(raw_tasks))
    waiting = {str(task.get("id")): reason for task, reason in rows}
    _, stale_after = guard("lock_settings", (1800, 3600), lock_settings)
    tasks = []
    for raw in raw_tasks:
        try:
            tasks.append(_task_view(raw, by_ref, by_task, full_head, waiting, stale_after))
        except Exception as exc:  # noqa: BLE001
            snap["errors"].append(f"task {raw.get('id')}: {exc}")
    order = {status: index for index, status in enumerate(LIST_ORDER)}
    prio = store.PRIORITY_ORDER
    tasks.sort(key=lambda t: (t["folder"] == "done", order.get(t["status"], 9), prio.get(t["priority"], 1), t["id"]))
    snap["tasks"] = tasks
    snap["specs"] = specs

    counts = {status: 0 for status in STATUS_ORDER}
    for task in tasks:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    total = len(tasks)
    snap["counts"] = counts
    snap["total_tasks"] = total
    snap["progress"] = (counts.get("done", 0) / total) if total else 0.0
    snap["progress_weighted"] = (sum(STATUS_WEIGHT.get(t["status"], 0.0) for t in tasks) / total) if total else 0.0
    crit_done = sum(t["criteria_done"] for t in tasks)
    crit_total = sum(t["criteria_total"] for t in tasks)
    snap["criteria"] = {"done": crit_done, "total": crit_total}

    locks = guard("locks", [], lambda: leases.lock_status_payload(leases.list_locks(ensure=False)))
    snap["locks"] = locks
    snap["refusals"] = guard("refusals", [], lambda: leases.recent_refusals(10))
    snap["checkpoints"] = guard("checkpoints", [], lambda: _quiet(_load_checkpoints)[0])
    snap["handoffs"] = guard("handoffs", [], lambda: ckpt.list_handoff_markers(ensure=False))
    snap["events"] = guard("events", {"recent": [], "total": 0, "per_day": [0] * 28, "per_agent": {}, "kinds": {}}, _events_section)
    snap["metrics"] = guard("metrics", {}, collect_metrics)
    snap["decisions"] = guard("decisions", [], adr.list_decisions)
    snap["adapters"] = guard("adapters", [], _adapters)
    snap["agents"] = guard("agents", [], lambda: _agents(tasks, locks, snap["events"]["recent"], config, snap["checkpoints"]))
    snap["preferences"] = guard("preferences", {"confirmed": False, "questions": [], "checks": []},
                                lambda: preferences.status(config))
    snap["artifacts"] = guard("artifacts", 0, lambda: len(_read_json_list(MANIFEST_PATH)))
    snap["now"] = guard("overview", {}, lambda: _quiet(overview.build, agent, role=role)[0])
    snap["role"] = role
    if deep:
        snap["findings"] = guard("doctor", [], lambda: [
            {"level": f.level, "message": f.message, "hint": f.hint} for f in _quiet(health.collect_checks)[0]])
    snap["load_ms"] = int((time.time() - started) * 1000)
    return snap


def _read_json_list(path: str) -> list:
    try:
        text = read_text(path)
    except OSError:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def event_time(event: dict) -> dt.datetime | None:
    try:
        return parse_iso(str(event.get("timestamp")))
    except (TypeError, ValueError):
        return None
