"""runtime.evidence: verification proof, kept apart from what an agent *says*.

Four different things must never stand in for each other:
  agent assertion        "tests pass"            (worthless alone)
  verification evidence  recorded by `ai check`  (this module)
  review approval        a different agent       (tasks/gates.py)
  integration approval   merge to the mainline   (`ai git finish`)

`ai check --task <id>` appends a record to `runtime/state/evidence/<id>.jsonl`:
which commands ran, their exit codes, who ran them and on which commit. A
record is only valid for the HEAD it was taken on, so new commits make older
evidence stale. The review gate (tasks/gates.py) and `ai resume` read it.
"""

from __future__ import annotations

import json
import os

from lib.core.fsio import safe_name
from lib.core.paths import EVIDENCE_DIR
from lib.core.timeutil import iso, parse_iso


def _task_file(task_id: str) -> str:
    return os.path.join(EVIDENCE_DIR, safe_name(task_id) + ".jsonl")


def record_task_check(
    task_id: str, agent: str | None, ok: bool, *, head: str | None, checks: list[dict],
    strict: bool, ran_commands: bool, fast: bool,
) -> dict:
    record = {
        "task": task_id, "agent": agent, "at": iso(), "head": head, "ok": ok,
        "result": "passed" if ok else "failed", "strict": strict,
        "ran_commands": ran_commands, "fast": fast, "checks": checks,
    }
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    with open(_task_file(task_id), "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def invalidate(task_id: str, reason: str) -> None:
    """Void earlier evidence (e.g. after changes were requested): it must be re-earned."""
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    with open(_task_file(task_id), "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"task": task_id, "at": iso(), "invalidated": True, "reason": reason}) + "\n")


def task_records(task_id: str) -> list[dict]:
    path = _task_file(task_id)
    if not os.path.isfile(path):
        return []
    records = []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def summary(record: dict) -> str:
    if record.get("invalidated"):
        return f"evidence invalidated: {record.get('reason')}"
    names = ", ".join(
        f"{c.get('name')} {'passed' if c.get('exit_code') == 0 else 'FAILED (exit ' + str(c.get('exit_code')) + ')'}"
        for c in record.get("checks", [])
    ) or "no commands"
    head = (record.get("head") or "no-git")[:8]
    return f"check {record.get('result')} @{head} by {record.get('agent') or '-'} ({names})"


# Every verdict this module can reach, ordered by precedence: the first match
# wins. `resume`, `review`, `done`, `history` and `doctor` all read `evaluate`.
STATES = ("none", "invalidated", "failed", "partial", "stale", "green")


def evaluate(task_id: str, head: str | None, since_iso: str | None = None) -> dict:
    """The single evidence verdict shared by every reader of the ledger.

    `task_status` used to call a partial check "valid" while `task_green`
    rejected it, so `ai resume` promised proof that `ai task review` refused.
    One function now decides:

        none        no check was ever recorded for the task
        invalidated changes were requested; the proof must be re-earned
        failed      the newest check ran and failed
        partial     it passed but skipped work (`--fast` or `--no-commands`)
        stale       it passed on another HEAD, or before the current claim
        green       full, passing proof for this HEAD

    `since_iso` is the claim time: review and done want proof that is no older
    than the claim, while a plain status read does not.
    """
    records = task_records(task_id)
    if not records:
        return {
            "state": "none",
            "record": None,
            "summary": "",
            "reason": f"no verification evidence is recorded for task {task_id}",
        }
    latest = records[-1]
    base = {"record": latest, "summary": summary(latest)}
    if latest.get("invalidated"):
        return {
            **base,
            "state": "invalidated",
            "reason": f"the earlier evidence was invalidated ({latest.get('reason')}); "
                      "run the checks again",
        }
    if not latest.get("ok"):
        return {
            **base,
            "state": "failed",
            "reason": f"the latest check for task {task_id} failed ({latest.get('at')})",
        }
    if latest.get("fast") or not latest.get("ran_commands"):
        return {
            **base,
            "state": "partial",
            "reason": "the latest check was partial (--fast or --no-commands); run the full check",
        }
    if latest.get("head") != head:
        return {
            **base,
            "state": "stale",
            "reason": (
                f"the evidence was taken on {(latest.get('head') or 'no-git')[:8]} but HEAD is "
                f"{(head or 'no-git')[:8]}; the code changed since"
            ),
        }
    if since_iso:
        try:
            if parse_iso(str(latest.get("at"))) < parse_iso(since_iso):
                return {
                    **base,
                    "state": "stale",
                    "reason": f"the latest green check ({latest.get('at')}) is older than "
                              f"the claim ({since_iso})",
                }
        except (TypeError, ValueError):
            pass
    return {**base, "state": "green", "reason": ""}


def task_status(task_id: str, head: str | None, since_iso: str | None = None) -> dict:
    """State of the newest evidence for a task relative to the current HEAD."""
    verdict = evaluate(task_id, head, since_iso)
    payload = {"state": verdict["state"]}
    if verdict.get("record"):
        payload["record"] = verdict["record"]
    if verdict.get("summary"):
        payload["summary"] = verdict["summary"]
    if verdict["state"] != "green":
        payload["reason"] = verdict["reason"]
    return payload


def task_green(task_id: str, head: str | None, since_iso: str | None = None) -> tuple[bool, str]:
    """Is there green, full evidence for this task on the current HEAD?"""
    verdict = evaluate(task_id, head, since_iso)
    if verdict["state"] == "green":
        return True, verdict.get("summary") or ""
    return False, verdict["reason"]
