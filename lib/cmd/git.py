"""cmd.git: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import sys

from lib.runtime.leases import (
    acquire_lock,
    release_lock,
)
from lib.git import flow
from lib.git import repo
from lib.tasks import scope as task_scope
from lib.tasks import store


def cmd_git(args) -> int:
    if args.action == "setup":
        return flow.cmd_git_setup(args)
    if args.action == "start":
        return flow.cmd_git_start(args)
    if args.action == "commit":
        return flow.cmd_git_commit(args)
    if args.action == "finish":
        return flow.cmd_git_finish(args)
    if args.action == "begin":
        result = acquire_lock("@git/index", agent=args.agent, task=args.task, ttl=args.ttl)
        if not result["ok"]:
            holder = result["holder"] or {}
            print(
                f"git index is locked by {holder.get('agent')} (task {holder.get('task') or '-'}).",
                file=sys.stderr,
            )
            return 1
        print("Acquired @git/index. Stage and commit only what you own, then run `ai git end`.")
        return 0
    if args.action == "end":
        return release_lock("@git/index", agent=args.agent, force=args.force)
    state = repo.git_state()
    if not state.get("repo"):
        print("Not a git repository; nothing to verify.")
        return 0
    uncovered, locks = repo.uncovered_staged(state)
    out_of_scope: list[str] = []
    if getattr(args, "task", None):
        path = store.find_task(args.task)
        if not path:
            print(f"No task with id {args.task}.", file=sys.stderr)
            return 1
        meta, _ = store.parse_task(path)
        out_of_scope = task_scope.violations(
            meta, [p for p in state.get("staged", []) if not repo.is_workspace_ledger_path(p)]
        )
    if args.json:
        print(json.dumps({"staged": state.get("staged", []), "uncovered": uncovered,
                          "out_of_scope": out_of_scope, "locks": locks}, indent=2))
    else:
        if uncovered:
            print("Staged paths with no held file lock:")
            for path in uncovered:
                print(f"  {path}")
        else:
            print("All staged paths are covered by a held lock.")
        if out_of_scope:
            print(f"Staged paths outside the scope of task {args.task}:")
            for item in out_of_scope:
                print(f"  {item}")
        elif getattr(args, "task", None):
            print(f"All staged paths are inside the scope of task {args.task}.")
    return 1 if ((args.strict and uncovered) or out_of_scope) else 0


ORDER = 110


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    git = sub.add_parser("git", help="Gitflow branches, commits and guarded merges")
    git_sub = git.add_subparsers(dest="action", required=True)
    git_setup = git_sub.add_parser("setup", help="initialize Gitflow branches and commit template")
    git_setup.add_argument("--json", action="store_true")
    git_setup.set_defaults(func=cmd_git)
    git_start = git_sub.add_parser("start", help="create or switch to a task branch")
    git_start.add_argument("--task", required=True)
    git_start.add_argument("--agent", required=True)
    git_start.add_argument("--type", default="feature")
    git_start.add_argument("--base", default=None)
    git_start.add_argument("--force", action="store_true")
    git_start.add_argument("--json", action="store_true")
    git_start.set_defaults(func=cmd_git)
    git_commit = git_sub.add_parser("commit", help="commit staged files with a Conventional Commit message")
    git_commit.add_argument("--task", required=True)
    git_commit.add_argument("--agent", required=True)
    git_commit.add_argument("--type", default="feat", choices=repo.COMMIT_TYPES)
    git_commit.add_argument("--scope", default=None)
    git_commit.add_argument("--message", required=True)
    git_commit.add_argument("--body", default="")
    git_commit.add_argument("--allow-empty", action="store_true")
    git_commit.add_argument("--verify", action="store_true", help="require a held lock for each staged path")
    git_commit.add_argument("--force", action="store_true")
    git_commit.add_argument("--json", action="store_true")
    git_commit.add_argument("--ci", default=None, help="record CI result URL or identifier in task log")
    git_commit.set_defaults(func=cmd_git)
    git_finish = git_sub.add_parser("finish", help="check, no-ff merge the task branch, and clean up")
    git_finish.add_argument("--task", required=True)
    git_finish.add_argument("--agent", required=True)
    git_finish.add_argument("--force", action="store_true")
    git_finish.add_argument("--json", action="store_true")
    git_finish.set_defaults(func=cmd_git)
    git_begin = git_sub.add_parser("begin", help="take the @git/index lock")
    git_begin.add_argument("--agent", required=True)
    git_begin.add_argument("--task", default=None)
    git_begin.add_argument("--ttl", type=int, default=300)
    git_begin.set_defaults(func=cmd_git)
    git_end = git_sub.add_parser("end", help="release the @git/index lock")
    git_end.add_argument("--agent", default=None)
    git_end.add_argument("--force", action="store_true")
    git_end.set_defaults(func=cmd_git)
    git_verify = git_sub.add_parser("verify", help="verify staged paths are covered by a held lock")
    git_verify.add_argument("--strict", action="store_true")
    git_verify.add_argument("--task", default=None, help="also check staged paths against this task's scope")
    git_verify.add_argument("--json", action="store_true")
    git_verify.set_defaults(func=cmd_git)
