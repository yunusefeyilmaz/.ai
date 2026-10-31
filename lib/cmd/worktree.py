"""cmd.worktree: inspect and clean the per-task Git worktrees."""

from __future__ import annotations

import json
import sys

from lib.git import repo, worktrees
from lib.tasks import store

ORDER = 140


def cmd_worktree(args) -> int:
    tasks = store.load_tasks()
    if args.action == "path":
        path = store.find_task(args.task_id)
        meta = store.parse_task(path)[0] if path else {}
        root = repo.task_root(meta)
        if not root:
            print(f"Task {args.task_id} has no worktree.", file=sys.stderr)
            return 1
        print(root)
        return 0
    rows = worktrees.listing(tasks)
    if args.action == "list":
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("No task worktrees.")
        for row in rows:
            owner = f"task {row['task']} ({row['status']}, {row['owner'] or 'unowned'})" if row["task"] else "NO TASK"
            flag = " ORPHAN" if row["orphan"] else ""
            print(f"{row['name']:<34} {row['branch'] or '?':<28} {owner}{flag}"
                  + (f"  dirty:{row['dirty']}" if row["dirty"] else ""))
        return 0
    # prune: remove worktrees whose task is finished or gone; never one with uncommitted work
    removed = 0
    for row in rows:
        if not row["orphan"]:
            continue
        if row["dirty"] and not args.force:
            print(f"Kept {row['name']}: uncommitted changes (use --force to discard them).", file=sys.stderr)
            continue
        ok, note = worktrees.remove(row["path"], force=args.force)
        print(f"{'Removed' if ok else 'Could not remove'} {row['name']}" + (f": {note}" if not ok else ""))
        removed += 1 if ok else 0
    repo.run_git(["worktree", "prune"])
    print(f"{removed} worktree(s) removed.")
    return 0


def register(sub) -> None:
    wt = sub.add_parser("worktree", help="list or prune the per-task Git worktrees")
    actions = wt.add_subparsers(dest="action", required=True)
    lst = actions.add_parser("list", help="worktrees and the task that owns each")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(func=cmd_worktree)
    path = actions.add_parser("path", help="print a task's worktree directory")
    path.add_argument("task_id")
    path.set_defaults(func=cmd_worktree)
    prune = actions.add_parser("prune", help="remove worktrees of finished or discarded tasks")
    prune.add_argument("--force", action="store_true", help="also discard uncommitted changes")
    prune.set_defaults(func=cmd_worktree)
