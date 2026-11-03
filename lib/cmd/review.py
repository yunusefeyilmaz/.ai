"""cmd.review: the whole review package for one task, in one command.

A reviewer needs five things to decide: the task, its spec and acceptance
criteria, the diff against the integration branch, the recorded check evidence,
and the transition history. Assembling them by hand means five commands and two
file reads, and doing it partially is easy. This command is read-only: it claims
nothing and writes nothing, so a reviewer can look before committing to the
claim.
"""

from __future__ import annotations

import json
import sys

from lib.config.settings import git_enabled
from lib.core.paths import ws_rel
from lib.core.fsio import read_text
from lib.git import repo
from lib.runtime import evidence
from lib.specs import spec as spec_lib
from lib.tasks import history, store

ORDER = 64

DEFAULT_MAX_DIFF_LINES = 400

CHECKLIST = (
    "every acceptance criterion is met by the diff (cite the criterion, not a summary)",
    "no product change outside the task's scope_allowed / declared locks",
    "tests cover the new behavior; existing behavior the spec lists as preserved still holds",
    "the recorded check evidence is green on this exact HEAD",
    "the working tree is clean and the branch is the task's branch",
)


def _task_payload(meta: dict, path: str) -> dict:
    keys = (
        "id", "title", "status", "owner", "submitted_by", "reviewed_by", "priority",
        "spec", "branch", "worktree", "depends_on", "changes_requested_by",
        "scope_allowed", "scope_forbidden", "locks", "updated",
    )
    payload = {key: meta.get(key) for key in keys if meta.get(key) is not None}
    payload["file"] = ws_rel(path)
    return payload


def _spec_payload(meta: dict) -> dict:
    path = spec_lib.resolve_spec_path(meta)
    if not path:
        return {"path": None, "criteria": [], "problem": "no spec is linked to this task", "body": None}
    try:
        text = read_text(path)
    except OSError as exc:
        return {"path": ws_rel(path), "criteria": [], "problem": f"the spec cannot be read: {exc}", "body": None}
    criteria = spec_lib.acceptance_criteria(text)
    problem = spec_lib.spec_problem(meta)
    return {"path": ws_rel(path), "criteria": criteria, "problem": problem, "body": text}


def _diff_payload(meta: dict, integration: str, max_lines: int, stat_only: bool) -> dict:
    """The branch's diff against the merge base with the integration branch."""
    payload = {
        "base": None, "stat": "", "patch": "", "lines": 0, "truncated": False,
        "total_lines": 0, "error": None,
    }
    branch = str(meta.get("branch") or "")
    if not branch:
        payload["error"] = "the task has no branch"
        return payload
    if not git_enabled():
        payload["error"] = "Git is disabled for this workspace"
        return payload
    if not repo.branch_exists(branch):
        payload["error"] = f"branch {branch} does not exist in the checkout"
        return payload
    code, base, err = repo.run_git(["merge-base", integration, branch])
    if code != 0 or not base:
        payload["error"] = err or f"no merge base between {integration} and {branch}"
        return payload
    payload["base"] = base
    _, payload["stat"], _ = repo.run_git(["diff", "--stat", f"{base}..{branch}"])
    if stat_only:
        return payload
    _, patch, _ = repo.run_git(["diff", f"{base}..{branch}"])
    lines = patch.splitlines()
    payload["total_lines"] = len(lines)
    if max_lines > 0 and len(lines) > max_lines:
        payload["truncated"] = True
        lines = lines[:max_lines]
    payload["lines"] = len(lines)
    payload["patch"] = "\n".join(lines)
    return payload


def _evidence_payload(task_id: str, head: str | None) -> dict:
    verdict = evidence.task_status(task_id, head)
    record = verdict.get("record") or {}
    return {
        "state": verdict.get("state"),
        "reason": verdict.get("reason"),
        "summary": verdict.get("summary"),
        "head": record.get("head"),
        "on_this_head": bool(head and record.get("head") == head),
        "at": record.get("at"),
        "agent": record.get("agent"),
        "checks": record.get("checks") or [],
    }


def _evidence_lines(payload: dict) -> list[str]:
    state = payload["state"]
    lines = [f"state: {state}"]
    if state == "none":
        lines.append("  (no check was ever recorded for this task)")
        return lines
    if payload.get("summary"):
        lines.append(f"  {payload['summary']}")
    if state != "green" and payload.get("reason"):
        lines.append(f"  PROBLEM: {payload['reason']}")
    if payload.get("on_this_head") is False:
        lines.append(
            f"  PROBLEM: the evidence belongs to {(payload.get('head') or 'no-git')[:8]}, "
            "not to HEAD"
        )
    for item in payload.get("checks") or []:
        verdict = "ok" if item.get("exit_code") == 0 else f"FAILED (exit {item.get('exit_code')})"
        seconds = item.get("seconds")
        suffix = f", {seconds}s" if seconds is not None else ""
        lines.append(f"  - {item.get('name')}: {verdict}{suffix}")
    return lines


def _history_lines(body: str) -> list[str]:
    lines = []
    for entry in history.parse(body):
        if entry["kind"] == "note":
            lines.append(f"  note  {entry['text']}")
            continue
        line = f"  {str(entry['at'])[:19]}  {entry['actor']:<12} {(entry['from'] or '-')} -> {entry['to']}"
        if entry["reason"]:
            line += f"  | {entry['reason']}"
        if entry["evidence"]:
            line += f"  | proof: {entry['evidence']}"
        lines.append(line)
    return lines or ["  (no transitions recorded)"]


def cmd_review(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(
            f"No task with id {args.task_id}. `ai task list` shows the active ids; "
            "`ai task list --all` includes the archived ones.",
            file=sys.stderr,
        )
        return 1
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    integration = repo.git_config()["integration"]
    max_lines = args.max_lines if args.max_lines is not None else DEFAULT_MAX_DIFF_LINES

    with repo.in_task(meta):
        state = repo.git_state()
        diff = _diff_payload(meta, integration, max_lines, args.stat)
        evidence_payload = _evidence_payload(task_id, state.get("head"))

    spec = _spec_payload(meta)
    checklist = list(CHECKLIST)
    checklist.append("claim it before approving: ai task next --review --agent <you>")

    payload = {
        "task": _task_payload(meta, path),
        "git": {
            "branch": state.get("branch"), "head": state.get("head"),
            "integration": integration, "dirty": state.get("dirty") or [],
        },
        "spec": spec,
        "diff": diff,
        "evidence": evidence_payload,
        "history": history.parse(body),
        "checklist": checklist,
    }

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    task = payload["task"]
    out = [
        f"=== REVIEW PACKAGE {task_id} ===",
        f"Task:     {task.get('title')}",
        f"Status:   {task.get('status')}"
        + (f" (submitted by {task['submitted_by']})" if task.get("submitted_by") else "")
        + (f" (changes requested by {task['changes_requested_by']})" if task.get("changes_requested_by") else ""),
        f"Owner:    {task.get('owner') or '-'}",
        f"Priority: {task.get('priority') or '-'}",
        f"Branch:   {task.get('branch') or '-'}"
        + (f"  (worktree {task['worktree']})" if task.get("worktree") else ""),
        f"Spec:     {spec['path'] or '-'}",
        "",
        "Acceptance criteria",
    ]
    if spec["problem"]:
        out.append(f"  PROBLEM: {spec['problem']}")
    if spec["criteria"]:
        for criterion in spec["criteria"]:
            out.append(f"  - {criterion}")
    elif not spec["problem"]:
        out.append("  (the spec lists no criteria)")
    out.append("")

    out.append(f"Diff  {task.get('branch') or '(no branch)'} vs {integration}")
    if diff["error"]:
        out.append(f"  PROBLEM: {diff['error']}")
    else:
        out.append(f"  base {diff['base'][:8] if diff['base'] else '-'}")
        out.extend("  " + line for line in (diff["stat"] or "(no changes)").splitlines())
        if diff["patch"]:
            out.append("")
            out.extend(diff["patch"].splitlines())
        if diff["truncated"]:
            out.append(
                f"  [truncated: {diff['lines']} of {diff['total_lines']} lines; "
                f"raise it with --max-lines {diff['total_lines']}]"
            )
        elif args.stat:
            out.append("  (--stat: run without it for the full patch)")
    out.append("")

    out.append("Evidence")
    out.extend(_evidence_lines(evidence_payload))
    out.append("")

    out.append("History")
    out.extend(_history_lines(body))
    out.append("")

    out.append("Checklist")
    out.extend(f"  [ ] {item}" for item in checklist)
    out.append("")
    out.append("=== END REVIEW PACKAGE ===")
    print("\n".join(out))
    return 0


def register(sub) -> None:
    review = sub.add_parser(
        "review",
        help="print the review package for one task: spec, criteria, diff, evidence, history",
    )
    review.add_argument("task_id")
    review.add_argument("--stat", action="store_true", help="show only the diff summary")
    review.add_argument(
        "--max-lines", type=int, default=None, metavar="N",
        help=f"truncate the patch after N lines (default {DEFAULT_MAX_DIFF_LINES}; 0 = no limit)",
    )
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)
