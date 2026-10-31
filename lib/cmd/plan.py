"""cmd.plan: the chief's one-shot planning: many linked tasks from one JSON file."""

from __future__ import annotations

import json
import sys

from lib.config import preferences, roles
from lib.tasks import plan

ORDER = 7


def cmd_plan(args) -> int:
    if args.action == "example":
        print(json.dumps(plan.EXAMPLE, indent=2))
        return 0
    try:
        raw = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        document = json.loads(raw)
    except (OSError, ValueError) as exc:
        print(f"Cannot read the plan: {exc}", file=sys.stderr)
        return 1
    errors, warnings = plan.validate(document)
    if errors:
        print("Plan rejected; nothing was created:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1
    denied = roles.authorize(args.agent, "task.new")
    if denied:
        print(denied, file=sys.stderr)
        return 1
    for item in warnings:
        print(f"WARN  {item}", file=sys.stderr)
    if args.dry_run:
        print(f"Plan is valid: {len(document['tasks'])} task(s). Dry run, nothing created.")
        return 0
    if not preferences.status()["confirmed"]:
        print("NOTE  workflow preferences are not confirmed yet: run `ai setup` and ask the user.", file=sys.stderr)
    created = plan.apply(document, args.agent)
    if args.json:
        print(json.dumps({"created": created, "warnings": warnings}, indent=2))
        return 0
    print(f"Created {len(created)} task(s):")
    for item in created:
        deps = f" after {', '.join(item['depends_on'])}" if item["depends_on"] else ""
        print(f"  {item['id']}  {item['key']:<14} {item['title']}{deps}")
    print("Workers now: `ai now --agent <n>` (they claim ready tasks themselves). Fill specs/ for each task first.")
    return 0


def register(sub) -> None:
    p = sub.add_parser("plan", help="chief: create many linked tasks (deps, locks, scope) from one JSON file")
    actions = p.add_subparsers(dest="action", required=True)
    apply_ = actions.add_parser("apply", help="validate and create the tasks")
    apply_.add_argument("file", help="plan JSON path, or - for stdin")
    apply_.add_argument("--agent", default=None, help="the chief creating the tasks")
    apply_.add_argument("--dry-run", action="store_true")
    apply_.add_argument("--json", action="store_true")
    apply_.set_defaults(func=cmd_plan)
    example = actions.add_parser("example", help="print a plan skeleton")
    example.set_defaults(func=cmd_plan)
