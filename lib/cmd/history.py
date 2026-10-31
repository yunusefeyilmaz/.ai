"""cmd.history: who moved a task, when, why and on which proof."""

from __future__ import annotations

import json
import sys

from lib.core.paths import ws_rel
from lib.git import repo
from lib.runtime import evidence
from lib.tasks import history, store

ORDER = 66


def cmd_history(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    entries = history.parse(body)
    records = evidence.task_records(task_id)
    if args.json:
        status = evidence.task_status(task_id, repo.git_state().get("head"))
        print(json.dumps({"task": task_id, "status": meta.get("status"), "transitions": entries,
                          "evidence": records, "evidence_state": status.get("state")}, indent=2))
        return 0
    print(f"{task_id} {meta.get('title')}  [{meta.get('status')}]  {ws_rel(path)}")
    for entry in entries:
        if entry["kind"] == "note":
            print(f"  note  {entry['text']}")
            continue
        line = f"  {entry['at'][:19]}  {entry['actor']:<12} {(entry['from'] or '-')} -> {entry['to']}"
        if entry["reason"]:
            line += f"  | {entry['reason']}"
        if entry["evidence"]:
            line += f"  | proof: {entry['evidence']}"
        print(line)
    if args.evidence:
        print("Evidence:")
        if not records:
            print("  (none)")
        for record in records:
            print(f"  {str(record.get('at'))[:19]}  {evidence.summary(record)}")
    elif records:
        state = evidence.task_status(task_id, repo.git_state().get("head"))["state"]
        print(f"Evidence: {len(records)} record(s), latest {state} (use --evidence for details)")
    return 0


def register(sub) -> None:
    hist = sub.add_parser("history", help="transition log and verification evidence of a task")
    hist.add_argument("task_id")
    hist.add_argument("--evidence", action="store_true", help="also list every evidence record")
    hist.add_argument("--json", action="store_true")
    hist.set_defaults(func=cmd_history)
