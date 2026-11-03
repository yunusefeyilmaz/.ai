"""tasks.gates: the required transitions of the task state machine.

    todo --claim--> in_progress --review--> review --done--> done
                         ^  |                 |  ^
                         |  +---block-------> blocked --unblock--> todo
                         |                    |
                         +----claim-------- changes_requested <--request-changes

Rules enforced here (not left to prose):
  * `review` needs the owner, a live claim and, when configured, green evidence
    recorded for this task on the current HEAD (`ai check --task <id>`).
  * `request-changes` is only for a task in review and never by its submitter.
  * `done` needs the task to be in `review`, approved by a DIFFERENT agent than
    the one who submitted it ("the producer never verifies its own work").
  * `--force` is the operator escape hatch and is logged in the task.

Configuration (config/workspace.json):
  "workflow": {"requireReview": true, "requireCheck": "strict"}
  requireCheck: true | false | "strict" (= only in strict mode)
"""

from __future__ import annotations

import os

from lib.config import preferences
from lib.config.settings import configured_checks, git_enabled, load_config
from lib.core.fsio import (
    CorruptStateError,
    lock_path,
    read_json,
)
from lib.git import repo
from lib.runtime import evidence
from lib.specs import spec as spec_lib


def workflow_config() -> dict:
    try:
        config = load_config()
    except (OSError, ValueError):
        config = {}
    flow = config.get("workflow") or {}
    return {
        "mode": str(config.get("mode") or "lite"),
        "requireReview": bool(flow.get("requireReview", True)),
        "requireCheck": flow.get("requireCheck", "strict"),
        "autoContinue": bool(flow.get("autoContinue", False)),
        "chiefOnlyTasks": bool(flow.get("chiefOnlyTasks", True)),
        "requireSpec": bool(flow.get("requireSpec", True)),
    }


def creation_gate(role: str | None) -> str | None:
    """Only the chief creates tasks, and only after the user chose the workflow.

    Workers that "just start" skip the planning and the user's questions, which
    is exactly what the chief exists to prevent. `--role chief` (or AI_ROLE=chief)
    is a deliberate declaration; implementers and reviewers never make it.
    """
    if not workflow_config()["chiefOnlyTasks"]:
        return None
    role = role or os.environ.get("AI_ROLE")
    if role not in ("chief", "orchestrator", "planner"):
        return (
            "Only the chief creates tasks. If the user asked you to plan or build something and "
            "there are no tasks yet, you are the chief: run `ai now --agent <name> --role chief` and "
            "follow it. Implementers claim existing tasks (`ai task next`); they never create them."
        )
    if not preferences.status()["confirmed"]:
        return (
            "Ask the user how much process they want before planning: run `ai setup`, ask them "
            "the questions (review, checks, git, tests, continue, workers) and store the answers "
            "with `ai setup --set ...`."
        )
    return None


def spec_gate(meta: dict) -> str | None:
    """No spec, no code: a task cannot be claimed while its spec is still the template."""
    if not workflow_config()["requireSpec"]:
        return None
    problem = spec_lib.spec_problem(meta)
    if not problem:
        return None
    return (
        f"Task {meta.get('id')} cannot be claimed: {problem}. The chief fills the spec "
        "(intent, behavior, acceptance criteria) before any worker starts. Ask the chief, or "
        "write the criteria yourself only if the user told you to."
    )


def check_required() -> bool:
    flow = workflow_config()
    value = flow["requireCheck"]
    if value == "strict":
        return flow["mode"] == "strict"
    return bool(value)


def claim_started(task_id: str) -> str | None:
    try:
        holder = read_json(lock_path(f"task-{task_id}")) or {}
    except CorruptStateError:
        # A damaged lease is reported by the caller's own checks; it is not a
        # start time, and it must not crash `review`/`done`.
        return None
    return holder.get("started_at")


def review_gate(meta: dict, agent: str) -> tuple[str | None, str]:
    """Return (error, evidence_text) for a task entering review.

    The error is set only when the gate is enforced and the evidence is missing,
    partial, failed or stale for the current HEAD. `evidence_text` summarizes the
    proof when there is one, so it can be written into the transition history.
    """
    task_id = str(meta.get("id"))
    if check_required() and not configured_checks():
        return (
            f"Task {task_id} cannot enter review: verification is required but no project checks "
            'are configured. Add them: `ai setup --check "tests=<command>"` (or choose '
            "`ai setup --set checks=no` if the user declines verification)."
        ), ""
    with repo.in_task(meta):
        head = repo.git_state().get("head")
    ok, text = evidence.task_green(task_id, head, claim_started(task_id))
    if check_required() and not ok:
        return (
            f"Task {task_id} cannot enter review: {text}. "
            f"Run `ai check --task {task_id} --agent {agent}` and fix what it reports first."
        ), ""
    return None, text if ok else ""


def review_git_gate(meta: dict, agent: str, include_evidence: bool = True) -> str | None:
    """Refuse review while the task checkout is not the one that will be merged.

    `ai git finish` fails *after* handover when the branch is wrong, the tree is
    dirty or HEAD moved past the evidence. Catching those here keeps the
    reviewer's approval meaningful and puts the fix in the producer's hands.
    """
    if not git_enabled():
        return None
    task_id = str(meta.get("id"))
    branch = str(meta.get("branch") or "")
    with repo.in_task(meta):
        state = repo.git_state()
    if not state.get("repo"):
        return None  # Git is enabled in config, but this workspace has no repository yet
    if not branch:
        return (
            f"Task {task_id} has no branch. Start one with "
            f"`ai git start --task {task_id} --agent {agent}` before review."
        )
    current = state.get("branch")
    if current != branch:
        return (
            f"Task {task_id} belongs to branch {branch}, but the checkout is on {current}. "
            f"Switch back with `git checkout {branch}`, then retry "
            f"`ai task review {task_id} --agent {agent}`."
        )
    head = state.get("head")
    if not head:
        return (
            f"Task {task_id} has no commit on {branch}. Commit the work with "
            f"`ai git commit --task {task_id} --agent {agent} ...` before review."
        )
    dirty = [
        path for path in (state.get("dirty") or [])
        if not repo.is_workspace_ledger_path(path)
    ]
    if dirty:
        listed = ", ".join(dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        return (
            f"Task {task_id} has uncommitted product changes ({listed}). Commit them with "
            f"`ai git commit --task {task_id} --agent {agent} ...` before review."
        )
    if include_evidence:
        records = evidence.task_records(task_id)
        if records:
            latest = records[-1]
            if (
                not latest.get("invalidated")
                and latest.get("head")
                and latest.get("head") != head
            ):
                return (
                    f"Task {task_id}: verification evidence belongs to "
                    f"{(latest.get('head') or '')[:8]} but HEAD is {head[:8]}. Re-run "
                    f"`ai check --task {task_id} --agent {agent}` on the current commit "
                    "before review."
                )
    return None


def request_changes_gate(meta: dict, agent: str) -> str | None:
    task_id = str(meta.get("id"))
    if meta.get("status") != "review":
        return f"Task {task_id} is '{meta.get('status')}'; changes can only be requested while it is in review."
    if meta.get("submitted_by") and meta.get("submitted_by") == agent:
        return f"Task {task_id} was submitted by {agent}; an independent agent must request changes."
    return None


def done_gate(meta: dict, agent: str, force: bool = False) -> str | None:
    """Return an error message when `agent` may not mark `meta` done, else None."""
    if force:
        return None
    task_id = str(meta.get("id"))
    if not workflow_config()["requireReview"]:
        return None
    if meta.get("status") != "review":
        return (
            f"Task {task_id} is '{meta.get('status')}', not in review. "
            f"Submit it first: `ai task review {task_id} --agent <producer>`; "
            "a different agent then merges and marks it done."
        )
    submitter = meta.get("submitted_by")
    if submitter and submitter == agent:
        return (
            f"Task {task_id} was submitted by {agent}; the producer never approves "
            "its own work. A different agent must run `ai task done`."
        )
    return None
