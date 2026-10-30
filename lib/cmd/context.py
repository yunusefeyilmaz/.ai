"""cmd.context: project memory for a fresh agent: what was done, what is open.

Compact on purpose (default ~40 lines). Bodies stay in the task files; this
only points at them. Use `--limit` for more history.
"""

from __future__ import annotations

import json

from lib.runtime import checkpoints as ckpt
from lib.runtime import overview

ORDER = 6


def cmd_context(args) -> int:
    data = overview.build(args.agent, history=args.limit)
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0
    out = ["# Project context"]
    out.append(f"mode {data['mode']} | {len(data['active'])} active | {data['done_total']} done")
    out.append("")
    out.append("## Open work")
    if not data["active"]:
        out.append("(none)")
    for task in data["active"]:
        task_id = str(task.get("id"))
        line = f"- {task_id} {task.get('status')} owner={task.get('owner') or '-'} [{task.get('priority') or '-'}] {task.get('title')}"
        out.append(line)
        sections = ckpt.checkpoint_sections(task_id)
        nxt = (sections.get("next") or "").strip().splitlines()
        if nxt:
            out.append(f"    next: {nxt[0][:140]}")
        elif task.get("spec"):
            out.append(f"    spec: {task.get('spec')}")
        if task.get("depends_on"):
            out.append(f"    depends_on: {task.get('depends_on')}")
    out.append("")
    out.append(f"## Done (last {len(data['done'])} of {data['done_total']})")
    if not data["done"]:
        out.append("(nothing shipped yet)")
    for task in data["done"]:
        out.append(f"- {task.get('id')} {task.get('title')} ({str(task.get('updated') or '')[:10]}, by {task.get('reviewed_by') or task.get('owner') or '?'})")
    if data["decisions"]:
        out.append("")
        out.append("## Decisions (ADR)")
        for item in data["decisions"][-args.limit:]:
            out.append(f"- {item['file'][:-3]}: {item['title']}" + (f" [{item['status']}]" if item["status"] else ""))
    if data["handoffs"]:
        out.append("")
        out.append("## Pending handoffs")
        for h in data["handoffs"]:
            out.append(f"- task {h.get('task')} from {h.get('agent')}: {h.get('reason')} -> ai resume {h.get('task')}")
    if data["events"]:
        out.append("")
        out.append("## Recent activity")
        for event in data["events"][-args.limit:]:
            out.append(f"- {str(event.get('timestamp'))[:16]} {event.get('event')} task={event.get('task') or '-'} agent={event.get('agent') or '-'}")
    print("\n".join(out))
    return 0


def register(sub) -> None:
    ctx = sub.add_parser("context", help="project memory: open work, shipped work, decisions, recent activity")
    ctx.add_argument("--agent", default=None)
    ctx.add_argument("--limit", type=int, default=5, help="history length (default 5)")
    ctx.add_argument("--json", action="store_true")
    ctx.set_defaults(func=cmd_context)
