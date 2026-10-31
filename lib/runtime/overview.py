"""runtime.overview: one compact, token-cheap picture of the whole workspace.

Both `ai now` (what do I do next?) and `ai context` (what has happened?) render
this structure. Keep it small: every extra line costs an agent tokens.
"""

from __future__ import annotations

from lib.config.settings import load_config
from lib.decisions import adr
from lib.git import repo
from lib.runtime import checkpoints as ckpt
from lib.runtime.events import read_events
from lib.runtime.leases import list_locks, lock_is_stale
from lib.config.settings import lock_settings
from lib.tasks import lifecycle, store, workflow

PRIORITY = store.PRIORITY_ORDER


def _line_of(task: dict) -> str:
    return f"{task.get('id')} [{task.get('priority') or '-'}] {task.get('title')}"


def build(agent: str | None = None, history: int = 5) -> dict:
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

    recommended = None
    if mine:
        task = sorted(mine, key=lambda t: str(t.get("updated") or ""), reverse=True)[0]
        recommended = {"task": task.get("id"), **workflow.next_action(task, agent, state, git_ready)}
    elif handoffs:
        h = handoffs[0]
        recommended = {"task": h.get("task"), "cmd": f"ai resume {h.get('task')}", "why": f"handoff from {h.get('agent')}: {h.get('reason')}", "extra": []}
    elif agent and any(
        t.get("status") == "changes_requested" and t.get("submitted_by") == agent for t in ready_all
    ):
        t = next(t for t in ready_all if t.get("status") == "changes_requested" and t.get("submitted_by") == agent)
        recommended = {"task": t.get("id"), **workflow.next_action(t, agent, state, git_ready)}
    elif review_queue and agent:
        t = review_queue[0]
        recommended = {"task": t.get("id"), **workflow.next_action(t, agent, state, git_ready)}
    elif ready_all:
        t = ready_all[0]
        recommended = {"task": t.get("id"), "cmd": f"ai task next --agent {agent or '<n>'}", "why": f"claims the highest-priority ready task ({_line_of(t)})", "extra": []}
    else:
        recommended = {"task": None, "cmd": 'ai task new "<title>"', "why": "nothing ready; create a task (and its spec) first", "extra": []}

    last_done = sorted(done, key=lambda t: str(t.get("updated") or ""), reverse=True)[:history]
    events = [e for e in read_events() if str(e.get("event", "")).startswith(("task_", "checkpoint", "resume"))][-history * 2:]

    return {
        "mode": config.get("mode"),
        "git": {"ready": git_ready, "branch": state.get("branch"), "head": (state.get("head") or "")[:8] or None,
                "dirty": len(state.get("dirty") or []), "integration": branches["integration"]},
        "agent": agent,
        "mine": mine, "recommended": recommended,
        "ready": ready_all, "waiting": waiting_all,
        "review_queue": review_queue, "others": others, "blocked": blocked,
        "handoffs": handoffs, "locks": locks,
        "active": active, "done": last_done, "done_total": len(done),
        "events": events, "decisions": adr.list_decisions(),
    }
