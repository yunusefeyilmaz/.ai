"""git.flow: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from lib.config import roles
from lib.config.settings import load_config
from lib.core.paths import (
    ACTIVE_DIR,
    PROJECT,
    SCRIPT_DIR,
)
from lib.core.timeutil import iso
from lib.git import repo, worktrees
from lib.git.setup import setup_git  # re-exported for lib.cmd.git
from lib.runtime.events import append_event
from lib.runtime.mutex import workspace_state_guard
from lib.tasks import board, store
from lib.tasks import scope as task_scope


def checks_seconds_budget() -> int:
    """Longest wall time the configured checks may take, in seconds.

    The index guard is held while `ai check` runs; its TTL has to cover every
    configured check's own timeout, or the lease expires mid-check and another
    agent can slip a commit between the check and the merge.
    """
    try:
        config = load_config()
    except (OSError, ValueError):
        return 1800
    total = 0
    for item in config.get("checks", []) or []:
        try:
            total += int(item.get("timeoutSeconds") or config.get("checksTimeoutSeconds") or 1800)
        except (TypeError, ValueError):
            total += 1800
    return total or 1800


def cmd_git_setup(args) -> int:
    return setup_git(yes=bool(getattr(args, "yes", False)), json_out=bool(getattr(args, "json", False)))


def cmd_git_start(args) -> int:
    return start_branch(
        args.task,
        args.agent,
        branch_type=getattr(args, "type", "feature"),
        base=getattr(args, "base", None),
        force=bool(getattr(args, "force", False)),
        carry=bool(getattr(args, "carry", False)),
        json_out=bool(getattr(args, "json", False)),
    )


def start_branch(
    task_id: str,
    agent: str,
    branch_type: str = "feature",
    base: str | None = None,
    force: bool = False,
    carry: bool = False,
    json_out: bool = False,
) -> int:
    """Create or switch to a task's branch.

    Explicit parameters on purpose: `ai task claim` calls this in-process, and a
    fabricated argparse Namespace would break silently when a flag is renamed.
    """
    path = store.find_task(task_id)
    if not path:
        print(f"No task with id {task_id}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) != ACTIVE_DIR:
        print("The task is already in done/. Start a branch before finishing it.", file=sys.stderr)
        return 1
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    owner_error = store.task_owner_error(meta, agent, force)
    if owner_error:
        print(owner_error, file=sys.stderr)
        return 1
    state = repo.git_state()
    if not state.get("repo"):
        print("Not a git repository.", file=sys.stderr)
        return 1
    isolated = repo.git_config()["isolation"] == "worktree"
    if not isolated and not carry and not repo.git_clean(ignore_ledger=True):
        print(
            "Working tree has product changes (uncommitted or untracked files outside tasks/specs/config). "
            "If they belong to this task, carry them onto the new branch: "
            f"`ai git start --task {task_id} --agent {agent} --carry`. "
            "Otherwise commit or stash them first.",
            file=sys.stderr,
        )
        return 1
    config = repo.git_config()
    if branch_type not in config["branchTypes"]:
        print(
            f"Unknown branch type '{branch_type}'. Use one of: {', '.join(config['branchTypes'])}.",
            file=sys.stderr,
        )
        return 1
    if not repo.branch_exists(config["integration"]):
        print(f"Integration branch '{config['integration']}' is missing. Run `ai git setup`.", file=sys.stderr)
        return 1
    base = base or (
        config["production"] if branch_type == "hotfix" else config["integration"]
    )
    if not repo.branch_exists(base):
        print(f"Base branch '{base}' does not exist.", file=sys.stderr)
        return 1
    branch = repo.task_branch_name(meta, branch_type)
    ok, owned, error = repo.acquire_git_guard(agent, task_id)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
        worktree_path = None
        if isolated:
            made, worktree_path, note = worktrees.create(meta, branch, base)
            if not made:
                print(f"Could not create the worktree for {branch}: {note}", file=sys.stderr)
                return 1
            meta["worktree"] = worktrees.relative(worktree_path)
            action = f"{note} worktree on"
        else:
            current = repo.git_state().get("branch")
            if repo.branch_exists(branch):
                if current != branch:
                    code, _, err = repo.run_git(["checkout", branch])
                    if code != 0:
                        print(f"Could not switch to {branch}: {err}", file=sys.stderr)
                        return 1
                action = "switched to"
            else:
                code, _, err = repo.run_git(["checkout", "-b", branch, base])
                if code != 0:
                    print(f"Could not create {branch}: {err}", file=sys.stderr)
                    return 1
                action = "created"
        meta["branch"] = branch
        meta["updated"] = iso()
        body = body.rstrip("\n") + f"\n- {iso()} {action} branch {branch} from {base} by {agent}\n"
        store.write_task(path, meta, body)
        board.write_board(store.load_tasks())
    finally:
        repo.release_git_guard(owned, agent)
    if json_out:
        print(json.dumps({"task": task_id, "branch": branch, "base": base, "action": action,
                          "worktree": worktree_path}, indent=2))
    else:
        print(f"{action.capitalize()} {branch} from {base}.")
        if worktree_path:
            print(f"  worktree: {worktree_path}")
            print("  Edit product files ONLY there (cd into it). Run the workspace CLI by absolute path:")
            print(f"  {worktrees.cli_command()} now --agent {agent}")
        else:
            print(f"Task {task_id} now points at that branch. Commit only files you own.")
    return 0


def cmd_git_commit(args) -> int:
    path = store.find_task(args.task)
    meta = store.parse_task(path)[0] if path else {}
    with repo.in_task(meta):
        return _git_commit(args)


def _git_commit(args) -> int:
    path = store.find_task(args.task)
    if not path:
        print(f"No task with id {args.task}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) != ACTIVE_DIR:
        print("The task is already in done/; no commit is needed.", file=sys.stderr)
        return 1
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    owner_error = store.task_owner_error(meta, args.agent, args.force)
    if owner_error:
        print(owner_error, file=sys.stderr)
        return 1
    branch = str(meta.get("branch") or "")
    if not branch:
        print(f"Task {task_id} has no branch. Run `ai git start --task {task_id} --agent {args.agent}`.", file=sys.stderr)
        return 1
    current = repo.git_state().get("branch")
    if current != branch:
        print(f"Current branch is {current}, but task {task_id} uses {branch}.", file=sys.stderr)
        return 1
    if args.type not in repo.COMMIT_TYPES:
        print(f"Unknown commit type '{args.type}'. Use one of: {', '.join(repo.COMMIT_TYPES)}.", file=sys.stderr)
        return 1
    message = " ".join(args.message.split())
    if not message:
        print("Commit message is empty.", file=sys.stderr)
        return 1
    scope = (args.scope or "").strip()
    if scope and not re.fullmatch(r"[a-z0-9_.-]+", scope):
        print("Scope must be lowercase letters, digits, dot, dash or underscore.", file=sys.stderr)
        return 1
    subject = f"{args.type}({scope}): {message}" if scope else f"{args.type}: {message}"
    state = repo.git_state()
    if not state.get("staged") and not args.allow_empty:
        print("Nothing is staged. Stage only the files you own, then retry.", file=sys.stderr)
        return 1
    scope_problems = task_scope.staged_violations(
        meta, state.get("staged", []), repo.is_workspace_ledger_path
    )
    if scope_problems and not getattr(args, "force", False):
        print(f"Refusing commit; staged paths leave the scope of task {task_id}:", file=sys.stderr)
        for item in scope_problems:
            print(f"  {item}", file=sys.stderr)
        print("Unstage them, or widen the task's scope_allowed/scope_forbidden deliberately.", file=sys.stderr)
        return 1
    # Verification is on by default when the task declares `locks`/scope: the
    # docs promise a refusal, so silence must not be the difference. `--no-verify`
    # is the deliberate, visible bypass for a task that only edits ledger files.
    declared = bool(meta.get("locks") or meta.get("scope_allowed"))
    verify = bool(getattr(args, "verify", False)) or (
        declared and not getattr(args, "no_verify", False)
    )
    if verify:
        uncovered, _ = repo.uncovered_staged(state)
        if uncovered:
            print("Refusing commit; staged paths have no held file lock:", file=sys.stderr)
            for item in uncovered:
                print(f"  {item}", file=sys.stderr)
            print("Run `ai lock acquire <path>` for each, or pass `--no-verify` deliberately.", file=sys.stderr)
            return 1
    ok, owned, error = repo.acquire_git_guard(args.agent, task_id)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
        trailers = f"Task: {task_id}\nAgent: {args.agent}"
        body_text = (args.body.strip() + "\n\n" + trailers) if args.body else trailers
        commit_args = ["commit", "-m", subject, "-m", body_text]
        if args.allow_empty:
            commit_args.append("--allow-empty")
        code, _, err = repo.run_git(commit_args)
        if code != 0:
            print(f"git commit failed: {err}", file=sys.stderr)
            return 1
        _, short, _ = repo.run_git(["rev-parse", "--short", "HEAD"])
        meta["updated"] = iso()
        body = body.rstrip("\n") + f"\n- {iso()} committed: {subject}\n"
        if args.ci:
            body += f"- {iso()} CI: {args.ci}\n"
        with workspace_state_guard():
            store.write_task(path, meta, body)
            board.write_board(store.load_tasks())
        amended = repo.commit_task_metadata(path, "", amend=True)
        if amended:
            short = amended
    finally:
        repo.release_git_guard(owned, args.agent)
    if args.json:
        print(json.dumps({"task": task_id, "branch": branch, "commit": short, "subject": subject}, indent=2))
    else:
        print(f"{short} {subject}")
    return 0


def cmd_git_finish(args) -> int:
    path = store.find_task(args.task)
    if not path:
        print(f"No task with id {args.task}.", file=sys.stderr)
        return 1
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    denied = None if args.force else roles.authorize(getattr(args, "agent", None), "git.finish")
    if denied:
        print(denied, file=sys.stderr)
        return 1
    submitter = meta.get("submitted_by")
    if not args.force and submitter and submitter == getattr(args, "agent", None):
        print(
            f"Task {task_id} was submitted by {submitter}; the producer never merges its own work. "
            "A different agent must run `ai git finish`.",
            file=sys.stderr,
        )
        return 1
    branch = str(meta.get("branch") or "")
    if not branch:
        print(f"Task {task_id} has no branch to merge.", file=sys.stderr)
        return 1
    status = str(meta.get("status") or "")
    if status not in ("review", "done") and not args.force:
        print(
            f"Task {task_id} is {status or 'unknown'}; move it to review after a separate "
            "verification, or use --force.",
            file=sys.stderr,
        )
        return 1
    if not repo.git_clean(ignore_ledger=True):
        print("Working tree has product changes. Commit or stash before merging.", file=sys.stderr)
        return 1
    worktree = repo.task_root(meta)
    if worktree:
        with repo.working_in(worktree):
            leftover = [p for p in repo.git_state().get("dirty", [])
                        if p not in worktrees.BRIEFING_FILES]
        if leftover:
            print(f"The task worktree has uncommitted changes ({', '.join(leftover[:5])}). "
                  "The producer must commit them before the merge.", file=sys.stderr)
            return 1
    if not repo.branch_exists(branch):
        print(f"Task branch '{branch}' does not exist.", file=sys.stderr)
        return 1
    config = repo.git_config()
    integration = config["integration"]
    if not repo.branch_exists(integration):
        print(f"Integration branch '{integration}' is missing. Run `ai git setup`.", file=sys.stderr)
        return 1
    ok, owned, error = repo.acquire_git_guard(
        args.agent, task_id, ttl=600 + checks_seconds_budget()
    )
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
        check = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "ai.py"), "check", "--strict", "--task", task_id]
            + (["--agent", args.agent] if getattr(args, "agent", None) else []),
            cwd=worktree or PROJECT,
            stdout=sys.stderr if getattr(args, "json", False) else None,  # keep --json parseable
        )
        if check.returncode != 0:
            print("ai check --strict failed; refusing to merge.", file=sys.stderr)
            return 1
        if not repo.heartbeat_git_guard(args.agent):
            print(
                "The git index guard expired while the checks ran; nothing was merged. "
                "Run `ai git finish` again.",
                file=sys.stderr,
            )
            return 1
        current = repo.git_state().get("branch")
        if current != branch and not worktree:
            code, _, err = repo.run_git(["checkout", branch])
            if code != 0:
                print(f"Could not switch to {branch}: {err}", file=sys.stderr)
                return 1
        code, _, err = repo.run_git(["checkout", integration])
        if code != 0:
            print(f"Could not switch to {integration}: {err}", file=sys.stderr)
            return 1
        merge_message = f"merge: {branch} ({task_id})"
        merge_args = ["merge", branch, "-m", merge_message]
        if config.get("merge") == "ff":
            merge_args.insert(1, "--ff")
        else:
            merge_args.insert(1, "--no-ff")
        code, _, err = repo.run_git(merge_args)
        if code != 0:
            abort_code, _, abort_err = repo.run_git(["merge", "--abort"])
            if abort_code == 0:
                print(f"Merge failed and was aborted: {err}", file=sys.stderr)
            else:
                print(
                    "Merge failed and could NOT be aborted "
                    f"({abort_err or 'git merge --abort failed'}); the repository is still mid-merge. "
                    "Resolve it manually before retrying: " + (err or "unknown merge error"),
                    file=sys.stderr,
                )
            return 1
        _, merged_head, _ = repo.run_git(["rev-parse", "--short", "HEAD"])
        deleted = False
        if worktree:
            freed, note = worktrees.remove(worktree, force=True)  # only briefing files are left
            if not freed:
                print(f"WARN  merged, but could not remove the worktree: {note}", file=sys.stderr)
            else:
                meta["worktree"] = None
        if config["deleteAfterMerge"]:
            code, _, err = repo.run_git(["branch", "-d", branch])
            if code == 0:
                deleted = True
            else:
                print(f"WARN  merged, but could not delete {branch}: {err}", file=sys.stderr)
            meta["branch"] = None
        meta["merged_into"] = integration
        meta["merged_at"] = iso()
        meta["updated"] = iso()
        body = body.rstrip("\n") + f"\n- {iso()} merged {branch} into {integration} by {args.agent}\n"
        with workspace_state_guard():
            store.write_task(path, meta, body)
            board.write_board(store.load_tasks())
        repo.commit_task_metadata(path, f"chore(task): record merge {task_id}")
    finally:
        repo.release_git_guard(owned, args.agent)
    append_event("task_merged", task=task_id, agent=args.agent, branch=branch, integration=integration)
    if args.json:
        print(json.dumps({
            "task": task_id,
            "branch": branch,
            "integration": integration,
            "mergeCommit": merged_head,
            "branchDeleted": deleted,
        }, indent=2))
    else:
        print(f"Merged {branch} into {integration} ({merged_head}).")
        print("Branch deleted." if deleted else "Branch kept.")
    return 0
