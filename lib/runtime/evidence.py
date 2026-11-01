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


def task_status(task_id: str, head: str | None) -> dict:
    """State of the newest evidence for a task relative to the current HEAD."""
    records = task_records(task_id)
    if not records:
        return {"state": "none"}
    latest = records[-1]
    if latest.get("invalidated"):
        return {"state": "invalidated", "record": latest, "summary": summary(latest)}
    state = "valid" if latest.get("head") == head else "stale"
    if not latest.get("ok"):
        state = "failed"
    return {"state": state, "record": latest, "summary": summary(latest)}


def task_green(task_id: str, head: str | None, since_iso: str | None = None) -> tuple[bool, str]:
    """Is there green, full evidence for this task on the current HEAD?"""
    records = task_records(task_id)
    if not records:
        return False, f"no verification evidence is recorded for task {task_id}"
    latest = records[-1]
    if latest.get("invalidated"):
        return False, f"the earlier evidence was invalidated ({latest.get('reason')}); run the checks again"
    if not latest.get("ok"):
        return False, f"the latest check for task {task_id} failed ({latest.get('at')})"
    if latest.get("fast") or not latest.get("ran_commands"):
        return False, "the latest check was partial (--fast or --no-commands); run the full check"
    if latest.get("head") != head:
        return False, (
            f"the evidence was taken on {(latest.get('head') or 'no-git')[:8]} but HEAD is "
            f"{(head or 'no-git')[:8]}; the code changed since"
        )
    if since_iso:
        try:
            if parse_iso(str(latest.get("at"))) < parse_iso(since_iso):
                return False, f"the latest green check ({latest.get('at')}) is older than the claim ({since_iso})"
        except (TypeError, ValueError):
            pass
    return True, summary(latest)
