"""tasks.gates: the required transitions of the task state machine.

    todo --claim--> in_progress --review--> review --done--> done
                         ^  |                 |
                         |  +---block-------> blocked --unblock--> todo

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

from lib.config.settings import configured_checks, load_config
from lib.core.fsio import read_json, safe_name
from lib.core.paths import LOCKS_DIR
from lib.git import repo
from lib.runtime import evidence


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
    }


def check_required() -> bool:
    flow = workflow_config()
    value = flow["requireCheck"]
    if value == "strict":
        return flow["mode"] == "strict"
    return bool(value)


def _claim_started(task_id: str) -> str | None:
    holder = read_json(os.path.join(LOCKS_DIR, safe_name(f"task-{task_id}") + ".lock")) or {}
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
    head = repo.git_state().get("head")
    ok, text = evidence.task_green(task_id, head, _claim_started(task_id))
    if check_required() and not ok:
        return (
            f"Task {task_id} cannot enter review: {text}. "
            f"Run `ai check --task {task_id} --agent {agent}` and fix what it reports first."
        ), ""
    return None, text if ok else ""


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
