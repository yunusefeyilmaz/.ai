"""cmd.spec: tick and show a task's acceptance criteria.

Acceptance criteria used to be decoration: the parser dropped `[x]`, nothing
could tick a box, and an archived spec still said `draft` with every box empty.
The spec is the one place where "done" is defined, so it needs the two commands
an implementer actually runs while working:

    ai spec check <task-id> <n>   # tick criterion n once it is true
    ai spec show  <task-id>       # every criterion with its box and done/total
"""

from __future__ import annotations

import json
import os
import sys

from lib.core.fsio import read_text, write_text_atomic
from lib.core.paths import ws_rel
from lib.specs import spec as spec_lib
from lib.tasks import store

ORDER = 66


def _no_subcommand(args) -> int:
    print("Usage: ai spec show <task-id> | ai spec check <task-id> <n>", file=sys.stderr)
    return 1


def _linked_spec(meta: dict) -> tuple[str | None, str | None]:
    """(spec path, error): the spec a task points at, or why it has none."""
    ref = str(meta.get("spec") or "")
    if not ref or ref == "null":
        return None, f"Task {meta.get('id')} has no spec: it was created with --no-spec."
    path = spec_lib.resolve_spec_path(meta)
    if not path:
        return None, f"Task {meta.get('id')} points at a spec that does not exist: {ref}"
    return path, None


def _progress_line(criteria: list[tuple[bool, str]]) -> str:
    done, total = spec_lib.criteria_progress(criteria)
    if total == 0:
        return "no real acceptance criteria yet"
    return f"{done}/{total} done"


def cmd_spec_show(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = store.parse_task(path)
    spec_path, error = _linked_spec(meta)
    if error or not spec_path:
        print(error, file=sys.stderr)
        return 1
    try:
        text = read_text(spec_path)
    except OSError as exc:
        print(f"Cannot read {ws_rel(spec_path)}: {exc}", file=sys.stderr)
        return 1
    criteria = spec_lib.acceptance_criteria(text)
    if args.json:
        done, total = spec_lib.criteria_progress(criteria)
        payload = {
            "task": str(meta.get("id")),
            "spec": ws_rel(spec_path),
            "criteria": [[is_done, item] for is_done, item in criteria],
            "done": done,
            "total": total,
        }
        print(json.dumps(payload, indent=2))
        return 0
    print(f"Spec:     {ws_rel(spec_path)}")
    print(f"Progress: {_progress_line(criteria)}")
    for done, item in criteria:
        print(f"  [{'x' if done else ' '}] {item}")
    return 0


def cmd_spec_check(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = store.parse_task(path)
    spec_path, error = _linked_spec(meta)
    if error or not spec_path:
        print(error, file=sys.stderr)
        return 1
    try:
        text = read_text(spec_path)
    except OSError as exc:
        print(f"Cannot read {ws_rel(spec_path)}: {exc}", file=sys.stderr)
        return 1
    try:
        updated, changed = spec_lib.tick_criterion(text, args.number)
    except ValueError as exc:
        print(f"Cannot tick criterion {args.number} of task {meta.get('id')}: {exc}.", file=sys.stderr)
        print(f"Inspect the spec with `ai spec show {meta.get('id')}`.", file=sys.stderr)
        return 1
    criteria = spec_lib.acceptance_criteria(updated)
    item = criteria[args.number - 1][1]
    if changed:
        write_text_atomic(spec_path, updated)
        print(f"Ticked {args.number}: {item}")
    else:
        print(f"Criterion {args.number} was already ticked: {item}")
    print(f"Progress: {_progress_line(criteria)}")
    unticked = spec_lib.unticked_criteria(updated)
    if not unticked:
        print(f"Every acceptance criterion in {os.path.basename(spec_path)} is ticked.")
    return 0


def register(sub) -> None:
    spec = sub.add_parser(
        "spec",
        help="tick and show a task's acceptance criteria",
    )
    actions = spec.add_subparsers(dest="spec_command")
    spec.set_defaults(func=_no_subcommand)

    show = actions.add_parser("show", help="print each criterion with its box and done/total")
    show.add_argument("task_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_spec_show)

    check = actions.add_parser("check", help="tick criterion N (1-based) of a task's spec")
    check.add_argument("task_id")
    check.add_argument("number", type=int)
    check.set_defaults(func=cmd_spec_check)
