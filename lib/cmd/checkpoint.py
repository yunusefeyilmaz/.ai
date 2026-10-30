"""cmd.checkpoint: split out of the former monolithic ai.py."""

from __future__ import annotations

import argparse

import json
import os
import sys

from lib.core.paths import (
    WORKSPACE,
    ws_rel,
)
from lib.core.fsio import write_json_atomic
from lib.core.timeutil import iso
from lib.runtime.events import append_event
from lib.runtime.mutex import workspace_state_guard
from lib.runtime import checkpoints as ckpt
from lib.tasks import store


def cmd_checkpoint(args) -> int:
    task_id = store.resolve_task_id(args.task_id)
    if not task_id:
        print("No task to checkpoint. Create or claim a task first.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            path = store.find_task(task_id)
            if not path:
                print(f"No task with id {task_id}.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(path)
            if meta.get("owner") and meta.get("owner") != args.agent and not args.force:
                print(
                    f"Task {task_id} is owned by {meta.get('owner')}. Use --force to checkpoint anyway.",
                    file=sys.stderr,
                )
                return 1
            ckpt.merge_existing_checkpoint(task_id, args)
            files = [item.strip() for item in (args.files or "").split(",") if item.strip()]
            fields = {
                "title": meta.get("title"),
                "objective": args.objective,
                "status": args.status,
                "done": args.done,
                "in_progress": args.in_progress,
                "next": args.next,
                "decisions": args.decisions,
                "do_not": args.do_not,
                "questions": args.questions,
                "files": files,
                "files_text": args.files_text,
                "verification": args.verification,
                "status_line": meta.get("status"),
            }
            checkpoint = ckpt.write_checkpoint(task_id, args.agent, args.reason, args.percent, fields)
            meta["updated"] = iso()
            reason = args.reason
            body = body.rstrip("\n") + f"\n- {iso()} checkpoint by {args.agent} ({reason}, {args.percent or '?'}%)\n"
            store.write_task(path, meta, body)
    except RuntimeError as exc:
        print(f"Cannot checkpoint task {task_id}: {exc}.", file=sys.stderr)
        return 1
    append_event("checkpoint", task=task_id, agent=args.agent)
    print(f"Checkpoint: {ws_rel(checkpoint)}")
    if args.next:
        print(f"Next: {args.next}")
    print(f"Resume later with: ai resume {task_id}")
    return 0


def cmd_handoff(args) -> int:
    task_id = store.resolve_task_id(args.task_id)
    if not task_id:
        print("No task to hand off.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            path = store.find_task(task_id)
            if not path:
                print(f"No task with id {task_id}.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(path)
            if meta.get("owner") and meta.get("owner") != args.agent:
                print(f"Task {task_id} is owned by {meta.get('owner')}.", file=sys.stderr)
                return 1
            ckpt.merge_existing_checkpoint(task_id, args)
            fields = {
                "title": meta.get("title"),
                "objective": args.objective,
                "status": args.status,
                "done": args.done,
                "in_progress": args.in_progress,
                "next": args.next,
                "decisions": args.decisions,
                "do_not": args.do_not,
                "questions": args.questions,
                "files": [item.strip() for item in (args.files or "").split(",") if item.strip()],
                "files_text": args.files_text,
                "verification": args.verification,
                "status_line": meta.get("status"),
            }
            checkpoint = ckpt.write_checkpoint(task_id, args.agent, "handoff", args.percent, fields)
            write_json_atomic(
                ckpt.handoff_marker(task_id),
                {
                    "task": task_id,
                    "agent": args.agent,
                    "reason": args.reason,
                    "created": iso(),
                    "checkpoint": os.path.relpath(checkpoint, WORKSPACE),
                },
            )
            meta["updated"] = iso()
            body = body.rstrip("\n") + f"\n- {iso()} handoff requested by {args.agent}: {args.reason}\n"
            store.write_task(path, meta, body)
    except RuntimeError as exc:
        print(f"Cannot hand off task {task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Handoff marker: {ws_rel(ckpt.handoff_marker(task_id))}")
    print(f"Checkpoint:     {ws_rel(checkpoint)}")
    print("\nPaste this into the next agent:\n")
    print(ckpt.resume_prompt(task_id))
    return 0


def cmd_resume(args) -> int:
    task_id = store.resolve_task_id(args.task_id)
    if not task_id:
        print("No task to resume.", file=sys.stderr)
        return 1
    path = store.find_task(task_id)
    meta, body = store.parse_task(path)
    data = ckpt.read_checkpoint(task_id)
    drift = ckpt.current_drift(task_id)
    markers = [marker for marker in ckpt.list_handoff_markers() if str(marker.get("task")) == task_id]
    append_event("resume", task=task_id, agent=meta.get("owner"))
    payload = {
        "task": meta,
        "checkpoint": data[0] if data else None,
        "checkpoint_body": data[1] if data else None,
        "drift": drift,
        "handoff": markers,
        "prompt": ckpt.resume_prompt(task_id),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0
    print(f"Task      : {task_id} - {meta.get('title')}")
    print(f"Status    : {meta.get('status')} (owner {meta.get('owner') or '-'})")
    print(f"Spec      : {meta.get('spec') or '-'}")
    print(f"File      : {ws_rel(path)}")
    print(f"Checkpoint: {ws_rel(ckpt.checkpoint_path(task_id)) if data else 'none'}")
    if markers:
        print(f"Handoff   : requested by {markers[0].get('agent')} ({markers[0].get('reason')})")
    print()
    if data:
        checkpoint_meta, checkpoint_body, _ = data
        print(f"Checkpoint age: {int(ckpt.checkpoint_age_minutes(task_id) or 0)} min ({checkpoint_meta.get('reason')})")
        print(f"Next (saved)  : {checkpoint_meta.get('next') or '-'}")
        print()
        print(checkpoint_body.strip())
        print()
    else:
        print("No checkpoint yet. The task body is the only saved context.")
        print()
        print(body.strip())
        print()
    if drift.get("checkpoint"):
        changed = [rel for rel, status in drift.get("files", {}).items() if status != "verified"]
        print("Drift:")
        print(f"  branch: {drift.get('branch')} | head: {str(drift.get('head'))[:8]}")
        if drift.get("commits_since") is not None:
            print(f"  commits since checkpoint: {drift['commits_since']}")
        print(f"  files needing attention: {', '.join(changed) if changed else 'none'}")
        print()
    print("Resume prompt:")
    print("-" * 60)
    print(ckpt.resume_prompt(task_id).strip())
    print("-" * 60)
    return 0


ORDER = 80


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    def add_checkpoint_flags(command: argparse.ArgumentParser) -> None:
        command.add_argument("task_id", nargs="?", default=None)
        command.add_argument("--agent", required=True)
        command.add_argument("--reason", default="checkpoint")
        command.add_argument("--percent", type=int, default=None)
        command.add_argument("--objective", default=None)
        command.add_argument("--status", default=None)
        command.add_argument("--done", default=None)
        command.add_argument("--in-progress", dest="in_progress", default=None)
        command.add_argument("--next", default=None)
        command.add_argument("--decisions", default=None)
        command.add_argument("--do-not", dest="do_not", default=None)
        command.add_argument("--questions", default=None)
        command.add_argument("--files", default=None, help="comma-separated repo-relative paths")
        command.add_argument("--files-text", dest="files_text", default=None)
        command.add_argument("--verification", default=None)
        command.add_argument("--force", action="store_true")

    checkpoint = sub.add_parser("checkpoint", help="save resumable context for a task")
    add_checkpoint_flags(checkpoint)
    checkpoint.set_defaults(func=cmd_checkpoint)

    handoff = sub.add_parser("handoff", help="checkpoint and mark a task for another agent")
    add_checkpoint_flags(handoff)
    handoff.set_defaults(func=cmd_handoff)

    resume = sub.add_parser("resume", help="print a compact resume brief with drift")
    resume.add_argument("task_id", nargs="?", default=None)
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=cmd_resume)
