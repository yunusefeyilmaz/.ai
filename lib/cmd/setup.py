"""cmd.setup: the chief's questionnaire: how much process does this project get?"""

from __future__ import annotations

import json
import sys

from lib.config import preferences

ORDER = 4


def cmd_setup(args) -> int:
    if args.defaults or args.set or args.check:
        answers = preferences.defaults() if args.defaults else {}
        for item in args.set or []:
            key, sep, value = item.partition("=")
            if not sep:
                print(f"--set expects KEY=VALUE, got '{item}'", file=sys.stderr)
                return 1
            answers[key.strip()] = value
        try:
            result = preferences.apply(answers, args.check)
        except ValueError as exc:
            print(f"Cannot store the answers: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, indent=2))
            return 0
        print("Saved to config/workspace.json:")
    else:
        result = preferences.status()
        if args.json:
            print(json.dumps(result, indent=2))
            return 0
        print("Ask the user these questions (in their language), then store the answers.")
    for row in result["questions"]:
        mark = "answered" if row["answered"] else "ASK"
        current = row["current"]
        shown = "yes" if current is True else "no" if current is False else current
        print(f"  [{mark:<8}] {row['key']:<9} now={shown!s:<5} recommended={'yes' if row['recommended'] is True else 'no' if row['recommended'] is False else row['recommended']}")
        print(f"             {row['ask']}")
    if result["checks"]:
        print(f"  project checks: {', '.join(result['checks'])}")
    if result["confirmed"]:
        print("Preferences are confirmed. Next: plan the work with `ai plan apply <plan.json>` (see AGENTS.md, chief flow).")
    else:
        print("Store answers: ai setup --set review=yes checks=yes git=yes tests=yes continue=no workers=2 "
              "--check \"tests=<your test command>\"   (or `ai setup --defaults`)")
    return 0


def register(sub) -> None:
    setup = sub.add_parser("setup", help="chief: ask the user which workflow features to use; stored in config")
    setup.add_argument("--set", nargs="+", metavar="KEY=VALUE", help="review, checks, git, tests, continue, workers")
    setup.add_argument("--check", action="append", metavar="NAME=COMMAND", help="add a project check command")
    setup.add_argument("--defaults", action="store_true", help="accept the recommended answers")
    setup.add_argument("--json", action="store_true")
    setup.set_defaults(func=cmd_setup)
