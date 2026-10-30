"""cmd.decision: record and list lasting decisions (ADRs)."""

from __future__ import annotations

import json

from lib.core.paths import ws_rel
from lib.decisions import adr

ORDER = 125


def cmd_decision(args) -> int:
    if args.action == "new":
        path = adr.create_decision(args.title, deciders=args.agent or "-", task=args.task or "-")
        print(f"Created {ws_rel(path)}")
        print("Fill Context/Decision/Consequences; set Status to accepted when agreed.")
        return 0
    items = adr.list_decisions()
    if args.json:
        print(json.dumps(items, indent=2))
        return 0
    if not items:
        print("No decisions recorded.")
    for item in items:
        print(f"{item['file'][:4]}  {item['status'] or '-':<11} {item['title']}")
    return 0


def register(sub) -> None:
    decision = sub.add_parser("decision", help="record and list architecture decisions (ADR)")
    decision_sub = decision.add_subparsers(dest="action", required=True)
    new = decision_sub.add_parser("new", help="create the next numbered ADR")
    new.add_argument("title")
    new.add_argument("--agent", default=None)
    new.add_argument("--task", default=None)
    new.set_defaults(func=cmd_decision)
    listing = decision_sub.add_parser("list", help="list ADRs")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_decision)
