"""runtime.overview: one compact, token-cheap picture of the whole workspace.

Both `ai now` (what do I do next?) and `ai context` (what has happened?) render
this structure. Keep it small: every extra line costs an agent tokens.
"""

from __future__ import annotations

from lib.config import preferences, roles as roles_cfg
from lib.config import settings
from lib.config.settings import load_config
from lib.decisions import adr
from lib.git import repo
from lib.runtime import checkpoints as ckpt
from lib.runtime.events import read_events
from lib.runtime.leases import list_locks, lock_is_stale
from lib.config.settings import lock_settings
from lib.tasks import lifecycle, store, workflow

PRIORITY = store.PRIORITY_ORDER


def resolve_role(agent: str | None, explicit: str | None) -> str | None:
    """chief | implementer | reviewer | None. Explicit `--role` wins over the team table."""
    if explicit:
        return {"orchestrator": "chief", "planner": "chief", "qa": "reviewer"}.get(explicit, explicit)
    assigned = roles_cfg.roles_of(agent) if agent else None
    if not assigned:
        return None
    for names, role in ((("orchestrator", "planner"), "chief"), (("reviewer", "qa"), "reviewer"), (("implementer",), "implementer")):
        if any(n in assigned for n in names):
            return role
    return None


def _line_of(task: dict) -> str:
    return f"{task.get('id')} [{task.get('priority') or '-'}] {task.get('title')}"


def build(agent: str | None = None, history: int = 5, role: str | None = None) -> dict:
    config = load_config()
    tasks = store.load_tasks()
    active = [t for t in tasks if t["_folder"] == "active"]
    done = [t for t in tasks if t["_folder"] == "done"]
    state = repo.git_state()
    branches = repo.git_config()
    git_ready = bool(
        state.get("repo") and state.get("head")
        and repo.branch_exists(branches["integration"]) and repo.branch_exists(branches["production"])
    )
    _, stale_after = lock_settings()
    locks = [lock for lock in list_locks(ensure=False) if not lock_is_stale(lock, stale_after)]

    mine = [t for t in active if agent and t.get("owner") == agent and t.get("status") in ("in_progress", "review")]
    try:
        ready_all, waiting_all = lifecycle.ready_and_waiting()
    except (OSError, ValueError):  # state may be mid-write; never crash the overview
        ready_all, waiting_all = [], []
    review_queue = [t for t in active if t.get("status") == "review" and (not agent or t.get("submitted_by") != agent)]
    others = [t for t in active if t.get("status") == "in_progress" and t.get("owner") != agent]
    blocked = [t for t in active if t.get("status") == "blocked"]
    handoffs = ckpt.list_handoff_markers(ensure=False)

    git_on = settings.git_enabled()
    role = resolve_role(agent, role)
    confirmed = preferences.status(config)["confirmed"]
    autocontinue = bool((config.get("workflow") or {}).get("autoContinue", False))
    delivered = [t for t in active if agent and t.get("status") == "review" and t.get("submitted_by") == agent]
    rework = [t for t in ready_all if agent and t.get("status") == "changes_requested" and t.get("submitted_by") == agent]
    who = agent or "<n>"
    nothing = {"task": None, "cmd": None, "extra": []}

    if mine:
        task = sorted(mine, key=lambda t: str(t.get("updated") or ""), reverse=True)[0]
        with repo.in_task(task):
            task_state = repo.git_state()
        recommended = {"task": task.get("id"), **workflow.next_action(task, agent, task_state, git_ready, git_on)}
        if repo.task_root(task):
            recommended.setdefault("extra", []).insert(0, f"cd {repo.task_root(task)}   # your isolated worktree; edit files only there")
    elif handoffs and role != "chief":
        h = handoffs[0]
        recommended = {"task": h.get("task"), "cmd": f"ai resume {h.get('task')}", "why": f"handoff from {h.get('agent')}: {h.get('reason')}", "extra": []}
    elif not active and not done and not confirmed:
        recommended = {**nothing, "cmd": "ai setup", "why": "new project: ask the user which workflow features to use (review, checks, git, tests), then store the answers"}
    elif role == "chief" or (role is None and not active and not done):
        if not confirmed:
            recommended = {**nothing, "cmd": "ai setup", "why": "ask the user the setup questions first; answers are stored in config"}
        elif not active:
            recommended = {**nothing, "cmd": "ai plan apply plan.json", "why": "no tasks yet: split the request into linked tasks (see `ai plan example`), then fill each spec"}
        else:
            recommended = {**nothing, "cmd": "ai status --board", "why": "the plan is in place; workers claim tasks themselves. Watch progress, unblock, answer questions"}
    elif role == "reviewer":
        if review_queue:
            recommended = {"task": review_queue[0].get("id"), "cmd": f"ai task next --review --agent {who}", "why": f"{len(review_queue)} task(s) wait for independent review; this claims the oldest", "extra": []}
        else:
            recommended = {**nothing, "why": "nothing is waiting for review; tell the user and stop"}
    else:  # implementer, or no role given
        if rework:
            recommended = {"task": rework[0].get("id"), **workflow.next_action(rework[0], agent, state, git_ready, git_on)}
        elif delivered and not autocontinue:
            ids = ", ".join(str(t.get("id")) for t in delivered)
            recommended = {**nothing, "why": f"you delivered {ids}; report it and wait for the user's go-ahead (then: ai task next --agent {who})"}
        elif ready_all:
            t = ready_all[0]
            recommended = {"task": t.get("id"), "cmd": f"ai task next --agent {who}", "why": f"claims the highest-priority ready task ({_line_of(t)}) and sets everything up", "extra": []}
        elif role is None and review_queue and agent:
            recommended = {"task": review_queue[0].get("id"), "cmd": f"ai task next --review --agent {who}", "why": "no ready work; a task waits for independent review", "extra": []}
        else:
            recommended = {**nothing, "why": "nothing is ready; tell the user and stop (the chief plans new work)"}

    last_done = sorted(done, key=lambda t: str(t.get("updated") or ""), reverse=True)[:history]
    events = [e for e in read_events() if str(e.get("event", "")).startswith(("task_", "checkpoint", "resume"))][-history * 2:]

    return {
        "mode": config.get("mode"),
        "git": {"ready": git_ready, "branch": state.get("branch"), "head": (state.get("head") or "")[:8] or None,
                "dirty": len(state.get("dirty") or []), "integration": branches["integration"]},
        "agent": agent, "role": role,
        "mine": mine, "recommended": recommended,
        "ready": ready_all, "waiting": waiting_all,
        "review_queue": review_queue, "others": others, "blocked": blocked,
        "handoffs": handoffs, "locks": locks,
        "active": active, "done": last_done, "done_total": len(done),
        "events": events, "decisions": adr.list_decisions(),
    }
