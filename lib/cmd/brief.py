"""cmd.brief: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os

from lib.core.paths import (
    PROJECT,
    ws_prefix,
    ws_rel,
)
from lib.config.settings import load_config
from lib.core.fsio import read_text
from lib.core.timeutil import iso
from lib.git import repo
from lib.runtime import checkpoints as ckpt
from lib.specs import spec as spec_lib
from lib.tasks import store


def cmd_brief(args) -> int:
    config = load_config()
    tasks = store.load_tasks()
    active = [task for task in tasks if task["_folder"] == "active"]
    task_id = store.resolve_task_id(args.task_id)
    meta = body = None
    task_path = None
    if task_id:
        task_path = store.find_task(task_id)
        if task_path:
            meta, body = store.parse_task(task_path)
    spec_path = spec_lib.resolve_spec_path(meta)
    checkpoint = ckpt.read_checkpoint(task_id) if task_id else None
    state = repo.git_state()
    cli = "ai"

    lines = [
        "=== .ai WORKSPACE BRIEF ===",
        f"Generated: {iso()}",
        f"Project:   {os.path.basename(PROJECT)}",
        f"Workspace: {ws_prefix() or './'}",
        f"Mode:      {config.get('mode')}",
        "",
        "You are an external assistant. You may not have filesystem or shell access.",
        "Never claim that you ran a command, test or check. Ask the human to run the",
        "commands below and paste the output back. Keep every AI-generated note, spec",
        "or scratch file inside the .ai workspace; the rest of the repository is",
        "product code.",
        "",
        "--- Operating rules ---",
        "1. One task per session. Claim it before editing anything.",
        "2. Lease the files or subsystem you will touch; a live lease is a refusal.",
        "3. A behavior change needs a spec with testable acceptance criteria.",
        "4. The producer never reviews its own work.",
        "5. Work is done only when `ai check` is green and its output is recorded.",
        "6. Checkpoint at milestones and before the context window fills.",
        f"7. Record lasting decisions as an ADR under {ws_prefix()}docs/decisions/.",
        "8. Every file-changing task must use Gitflow unless the user explicitly says not to use Git. Run `ai git setup`; it initializes Git and asks before an initial commit.",
        "9. After claim, run `ai git start` before editing; stop if setup or branch creation fails. Commit with `ai git commit`; a different reviewer must merge with `ai git finish` before done. Read-only work needs no branch.",
        "",
    ]

    if meta:
        lines += [
            "--- Current task ---",
            f"ID:         {meta.get('id')}",
            f"Title:      {meta.get('title')}",
            f"Status:     {meta.get('status')}",
            f"Owner:      {meta.get('owner') or '-'}",
            f"Priority:   {meta.get('priority') or '-'}",
            f"Spec:       {ws_rel(spec_path) if spec_path else (meta.get('spec') or 'none')}",
            f"Depends on: {meta.get('depends_on') or '-'}",
            f"File:       {ws_rel(task_path)}",
            "",
            (body or "(task body is empty)").strip(),
            "",
        ]
    else:
        lines += [
            "--- Current task ---",
            "No active task selected." if not active else "No task id was given. Active tasks:",
        ]
        for item in active:
            lines.append(f"- {item.get('id')} [{item.get('status')}] {item.get('title')} (owner: {item.get('owner') or '-'})")
        lines.append("")

    lines += ["--- Spec ---"]
    if spec_path:
        lines += [f"File: {ws_rel(spec_path)}", "", read_text(spec_path).strip(), ""]
    else:
        lines += ["No spec is linked to this task.", ""]

    lines += ["--- Last checkpoint ---"]
    if checkpoint:
        lines += [
            f"Created: {checkpoint[0].get('created')}",
            f"Reason:  {checkpoint[0].get('reason')}",
            f"Next:    {checkpoint[0].get('next') or '-'}",
            "",
            checkpoint[1].strip(),
            "",
        ]
    else:
        lines += ["No checkpoint exists.", ""]

    lines += ["--- Repository state ---"]
    lines.append(f"Branch: {state.get('branch') or '-'}")
    lines.append(f"HEAD:   {state.get('head') or '-'}")
    dirty = state.get("dirty") or []
    if dirty:
        lines.append("Uncommitted paths:")
        for path in dirty[:20]:
            lines.append(f"- {path}")
        if len(dirty) > 20:
            lines.append(f"- ... {len(dirty) - 20} more")
    else:
        lines.append("Working tree is clean.")
    lines += [
        "",
        "--- How to answer ---",
        "- If the human asks for implementation: give a short plan first, then minimal",
        "  patches or diffs and exact commands. Do not invent file contents.",
        "- Tie every change to an acceptance criterion. Flag ambiguity before coding.",
        "- Mark anything you could not verify as unverified.",
        "",
        "--- Commands available to the human ---",
        f"{cli} now --agent <n>",
        f"{cli} doctor",
        f"{cli} status",
        f"{cli} task show <id>",
        f"{cli} task claim <id> --agent <name>",
        f"{cli} lock acquire <path> --agent <name> --task <id>",
        f"{cli} checkpoint <id> --agent <name> --next \"...\"",
        f"{cli} check --strict",
        f"{cli} task done <id> --agent <name>",
        "",
        "=== END BRIEF ===",
    ]

    text = "\n".join(lines)
    if args.max_chars and len(text) > args.max_chars:
        text = text[: args.max_chars].rstrip() + "\n\n[truncated by ai brief]\n=== END BRIEF ==="
    if args.json:
        print(json.dumps({
            "project": os.path.basename(PROJECT),
            "workspace": ws_prefix() or "./",
            "mode": config.get("mode"),
            "task": meta,
            "task_body": body,
            "spec_path": ws_rel(spec_path) if spec_path else None,
            "spec_body": read_text(spec_path) if spec_path else None,
            "checkpoint": checkpoint[0] if checkpoint else None,
            "checkpoint_body": checkpoint[1] if checkpoint else None,
            "git": state,
            "brief": text,
        }, indent=2, default=str))
        return 0
    print(text)
    return 0


ORDER = 90


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    brief = sub.add_parser("brief", help="print a paste-ready brief for an external chat AI")
    brief.add_argument("task_id", nargs="?", default=None)
    brief.add_argument("--max-chars", type=int, default=0)
    brief.add_argument("--json", action="store_true")
    brief.set_defaults(func=cmd_brief)
