"""runtime.overview: one compact, token-cheap picture of the whole workspace.

Both `ai now` (what do I do next?) and `ai context` (what has happened?) render
this structure. Keep it small: every extra line costs an agent tokens.
"""

from __future__ import annotations

import shlex

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


def _argv(cmd: str | None) -> list[str]:
    """`ai task next --agent x` -> `['task', 'next', '--agent', 'x']`.

    The JSON contract hands a harness an argv it can run unchanged; the printed
    line stays as it is. A command that is not `ai ...` is kept whole so nothing
    is silently dropped.
    """
    if not cmd:
        return []
    try:
        tokens = shlex.split(cmd)
    except ValueError:  # unbalanced quotes in a message: never crash the overview
        return []
    return tokens[1:] if tokens[:1] == ["ai"] else tokens


def _human_question(recommended: dict) -> str | None:
    """The question to put to the user when the next move is theirs, else None.

    Derived from the recommendation so JSON consumers never have to read the
    prose in `why` to know whether the agent should act or ask.
    """
    cmd = str(recommended.get("cmd") or "")
    why = str(recommended.get("why") or "")
    if cmd == "ai setup":
        return (
            "Before planning: how much process do you want for this project "
            "(independent review, checks required, Git, tests, auto-continue, number of workers)?"
        )
    if not cmd:
        return why or "nothing can proceed without a decision from the user"
    return None


def _contract(recommended: dict) -> dict:
    """Attach the machine-readable part of a recommendation (args, needs_human)."""
    question = _human_question(recommended)
    recommended["next_args"] = _argv(recommended.get("cmd"))
    recommended["needs_human"] = question is not None
    recommended["question"] = question
    recommended["blocker"] = (question or "nothing to do") if question is not None else None
    return recommended


def _answer_text(value) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def _setup_extras(preference_state: dict) -> list[str]:
    """The chief's unanswered questions, inline, so `ai now` is self-contained."""
    rows = preference_state["questions"]
    pending = [row for row in rows if not row["answered"]]
    if not pending:
        return []
    asks = ", ".join(
        f"{row['key']} ({'yes' if row['recommended'] is True else 'no' if row['recommended'] is False else row['recommended']})"
        for row in pending
    )
    answers = " ".join(f"{row['key']}={_answer_text(row['recommended'])}" for row in rows)
    command = f"then: ai setup --set {answers}"
    if not preference_state["checks"]:
        command += ' --check "tests=<command>"'
    return [f"ask the user: {asks}", command]


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
    review_queue = [
        t for t in active
        if t.get("status") == "review" and not t.get("owner") and (not agent or t.get("submitted_by") != agent)
    ]
    others = [t for t in active if t.get("status") == "in_progress" and t.get("owner") != agent]
    blocked = [t for t in active if t.get("status") == "blocked"]
    handoffs = ckpt.list_handoff_markers(ensure=False)

    git_on = settings.git_enabled()
    role = resolve_role(agent, role)
    preference_state = preferences.status(config)
    confirmed = preference_state["confirmed"]
    autocontinue = bool((config.get("workflow") or {}).get("autoContinue", False))
    delivered = [t for t in active if agent and t.get("status") == "review" and t.get("submitted_by") == agent]
    rework = [t for t in ready_all if agent and t.get("status") == "changes_requested" and t.get("submitted_by") == agent]
    who = agent or "<n>"
    nothing = {"task": None, "cmd": None, "extra": []}

    if mine:
        task = sorted(mine, key=lambda t: str(t.get("updated") or ""), reverse=True)[0]
        with repo.in_task(task):
            task_state = repo.git_state()
            task_state["ahead"] = repo.commits_ahead(branches["integration"]) if git_on else None
        recommended = {"task": task.get("id"), **workflow.next_action(task, agent, task_state, git_ready, git_on)}
        if repo.task_root(task):
            recommended.setdefault("extra", []).insert(0, f"cd {repo.task_root(task)}   # your isolated worktree; edit files only there")
    elif handoffs and role != "chief":
        h = handoffs[0]
        recommended = {"task": h.get("task"), "cmd": f"ai resume {h.get('task')}", "why": f"handoff from {h.get('agent')}: {h.get('reason')}", "extra": []}
    elif not active and not done and not confirmed:
        recommended = {**nothing, "cmd": "ai setup", "extra": _setup_extras(preference_state), "why": "new project: ask the user which workflow features to use (review, checks, git, tests), then store the answers"}
    elif role == "chief" or (role is None and not active and not done):
        if not confirmed:
            recommended = {**nothing, "cmd": "ai setup", "extra": _setup_extras(preference_state), "why": "ask the user the setup questions first; answers are stored in config"}
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

    _contract(recommended)

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


_KEEP = ("id", "title", "status", "owner", "priority", "spec", "depends_on", "branch",
         "worktree", "submitted_by", "reviewed_by", "changes_requested_by", "updated")


def _slim(task: dict) -> dict:
    return {key: task.get(key) for key in _KEEP if task.get(key) is not None}


def compact(data: dict) -> dict:
    """JSON-safe, token-cheap copy: task bodies and internal fields are dropped."""
    out = dict(data)
    for key in ("mine", "ready", "review_queue", "others", "blocked", "active", "done"):
        out[key] = [_slim(task) for task in data.get(key, [])]
    out["waiting"] = [{"task": _slim(task), "reasons": reasons} for task, reasons in data.get("waiting", [])]
    return out
