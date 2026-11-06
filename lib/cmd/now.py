"""cmd.now: the 10-line answer to "where am I and what is the next command?"

This is the first command an agent should run in a session. It is built to be
cheap: no file bodies, no history, one recommended command.
"""

from __future__ import annotations

import json

from lib.core.paths import VERSION
from lib.runtime import overview

ORDER = 5


def _task_line(task: dict) -> str:
    owner = task.get("owner") or "-"
    return f"{task.get('id')} {task.get('status')} ({owner}) {task.get('title')}"


def cmd_now(args) -> int:
    data = overview.build(args.agent, role=args.role)
    if args.json:
        payload = overview.compact(data)
        payload["schema"] = 2  # contract version of this payload
        # Promoted out of `recommended` so a harness reads four flat fields: act
        # with next_args, or ask the user `question`. `blocker` says why there is
        # no command to run.
        rec = data.get("recommended") or {}
        payload["needs_human"] = bool(rec.get("needs_human"))
        payload["question"] = rec.get("question")
        payload["next_args"] = list(rec.get("next_args") or [])
        payload["blocker"] = rec.get("blocker")
        print(json.dumps(payload, indent=2, default=str))
        return 0
    git = data["git"]
    tree = "dirty:%d" % git["dirty"] if git["dirty"] else "clean"
    lines = [
        f"ai {VERSION} | mode {data['mode']} | git "
        + (f"{git['branch']}@{git['head']} {tree}" if git["ready"] or git["branch"] else "not initialized")
        + f" | {len(data['active'])} active, {data['done_total']} done, {len(data['locks'])} locks"
    ]
    for task in data["mine"]:
        lines.append(f"YOU   {_task_line(task)}")
    rec = data["recommended"]
    lines.append(f"NEXT  {rec['cmd'] or '(nothing to run)'}")
    lines.append(f"WHY   {rec['why']}")
    for extra in rec.get("extra", []):
        lines.append(f"ALSO  {extra}")
    if rec["cmd"] == "ai setup":
        # AGENTS.md promises the chief sees the questions here, not only in
        # `ai setup`; print the unanswered ones so the doc and the CLI agree.
        from lib.config import preferences

        try:
            for row in preferences.status()["questions"]:
                if not row["answered"]:
                    lines.append(f"ASK   {row['key']}: {row['ask']}")
        except (OSError, ValueError):
            pass
    if data["handoffs"] and not (rec["cmd"] or "").startswith("ai resume"):
        h = data["handoffs"][0]
        lines.append(f"HANDOFF task {h.get('task')} from {h.get('agent')}: {h.get('reason')} -> ai resume {h.get('task')}")
    if data["review_queue"]:
        lines.append("REVIEW " + "; ".join(_task_line(t) for t in data["review_queue"][:3]))
    if data["ready"]:
        lines.append("READY  " + "; ".join(f"{t.get('id')} [{t.get('priority')}] {t.get('title')}" for t in data["ready"][:3]))
    if data["blocked"] or data["waiting"]:
        waits = [f"{t.get('id')} blocked" for t in data["blocked"]] + [f"{t.get('id')} waits {', '.join(r)}" for t, r in data["waiting"][:3]]
        lines.append("WAIT   " + "; ".join(waits))
    if data["others"]:
        lines.append("BUSY   " + "; ".join(_task_line(t) for t in data["others"][:3]))
    lines.append("More: ai context (history) | ai task show <id> | ai resume <id>")
    print("\n".join(lines))
    return 0


def register(sub) -> None:
    now = sub.add_parser("now", help="compact state + the single next required command")
    now.add_argument("--agent", default=None, help="your agent name (personalizes NEXT)")
    now.add_argument("--role", default=None, choices=["chief", "implementer", "reviewer", "orchestrator", "planner", "qa"],
                     help="the role you were given; overrides the team table")
    now.add_argument("--json", action="store_true")
    now.set_defaults(func=cmd_now)
