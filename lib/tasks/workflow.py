"""tasks.workflow: "what is the next required command?" for one task.

Pure decision logic over already-loaded state, so `ai now`, `ai context` and
future skills all give the same answer. It never mutates anything.
"""

from __future__ import annotations

from lib.runtime import checkpoints as ckpt
from lib.config.settings import configured_checks, preference
from lib.git import repo
from lib.runtime import evidence
from lib.tasks import gates


def next_action(task: dict, agent: str | None, git: dict, git_ready: bool, git_on: bool = True) -> dict:
    """Return {"cmd": str, "why": str, "extra": [str]} for the task's current state."""
    task_id = str(task.get("id"))
    status = str(task.get("status"))
    owner = task.get("owner")
    a = agent or "<n>"
    extra: list[str] = []

    if status == "done":
        return {"cmd": None, "why": "task is done", "extra": extra}
    if status == "blocked":
        return {"cmd": f"ai task unblock {task_id} --agent {a}", "why": "blocked; unblock when the cause is gone", "extra": extra}

    if status == "changes_requested":
        return {
            "cmd": f"ai task claim {task_id} --agent {a}",
            "why": f"{task.get('changes_requested_by') or 'the reviewer'} sent it back: read `ai history {task_id}`, fix, then re-review",
            "extra": extra,
        }

    if status == "todo":
        if owner:
            return {"cmd": f"ai task claim {task_id} --agent {a}", "why": f"leased by {owner}", "extra": extra}
        return {"cmd": f"ai task claim {task_id} --agent {a}", "why": "claim before touching anything", "extra": extra}

    if status == "review":
        submitter = task.get("submitted_by")
        if agent and submitter and agent == submitter:
            return {
                "cmd": f"ai task release {task_id} --agent {a}",
                "why": "you submitted it; a different agent must review. Release so the reviewer can take over",
                "extra": extra,
            }
        return {
            "cmd": f"ai git finish --task {task_id} --agent {a}",
            "why": f"independent review (producer: {submitter or '?'}): read spec + diff, then merge; afterwards `ai task done {task_id} --agent {a}`",
            "extra": extra,
        }

    # in_progress ---------------------------------------------------------
    if git_on and not git_ready:
        return {"cmd": "ai git setup", "why": "Gitflow base is missing (skip only if the user said no Git)", "extra": extra}
    branch = task.get("branch")
    if git_on and (not branch or git.get("branch") != branch):
        return {
            "cmd": f"ai git start --task {task_id} --agent {a} --type feature",
            "why": "work on the task branch, never on develop/master",
            "extra": extra,
        }
    age = ckpt.checkpoint_age_minutes(task_id)
    if age is None or age > preference("handoff.warnAfterMinutes", 30):
        extra.append(f'ai checkpoint {task_id} --agent {a} --next "<step>"   # {"none yet" if age is None else f"{int(age)}m old"}')
    dirty = [] if not git_on else [p for p in (git.get("dirty") or []) if not repo.is_workspace_ledger_path(p) and not p.startswith(".ai/")]
    if dirty:
        return {
            "cmd": f'ai git verify --strict && ai git commit --task {task_id} --agent {a} --type feat --message "<subject>"',
            "why": f"{len(dirty)} uncommitted product path(s); stage your owned paths first",
            "extra": extra,
        }
    if gates.check_required():
        if not configured_checks():
            return {"cmd": 'ai setup --check "tests=<command>"', "why": "verification is required but no project checks are configured", "extra": extra}
        ok, reason = evidence.task_green(task_id, git.get("head"))
        if not ok:
            # `ai task review` would run the checks itself; running them first shows failures early
            return {"cmd": f"ai check --task {task_id} --agent {a}", "why": f"review needs fresh evidence ({reason})", "extra": extra}
    return {
        "cmd": f"ai task review {task_id} --agent {a}",
        "why": "work is committed and checked; submit for independent review",
        "extra": extra,
    }
