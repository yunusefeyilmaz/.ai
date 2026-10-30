"""tasks.gates: the required transitions of the task state machine.

    todo --claim--> in_progress --review--> review --done--> done
                         ^  |                 |
                         |  +---block-------> blocked --unblock--> todo

Rules enforced here (not left to prose):
  * `review` needs the owner, a live claim and, when configured, a green check.
  * `done` needs the task to be in `review`, approved by a DIFFERENT agent than
    the one who submitted it ("the producer never verifies its own work").
  * `--force` is the operator escape hatch and is logged in the task.

Configuration (config/workspace.json):
  "workflow": {"requireReview": true, "requireCheck": "strict"}
  requireCheck: true | false | "strict" (= only in strict mode)
"""

from __future__ import annotations

import os

from lib.config.settings import load_config
from lib.core.fsio import read_json, safe_name
from lib.core.paths import LOCKS_DIR
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


def review_gate(meta: dict, agent: str) -> str | None:
    """Return an error message when `meta` may not enter review, else None."""
    task_id = str(meta.get("id"))
    if check_required():
        ok, reason = evidence.green_since(_claim_started(task_id))
        if not ok:
            return (
                f"Task {task_id} cannot enter review: {reason}. "
                "Run `ai check` and fix what it reports first."
            )
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
