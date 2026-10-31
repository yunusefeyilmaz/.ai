"""git.flow: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from lib.core.paths import (
    ACTIVE_DIR,
    PROJECT,
    SCRIPT_DIR,
)
from lib.core.timeutil import iso
from lib.runtime.events import append_event
from lib.config import roles
from lib.git import repo
from lib.tasks import scope as task_scope
from lib.tasks import board
from lib.tasks import store


def cmd_git_setup(args) -> int:
    state = repo.git_state()
    if not state.get("repo") and state.get("error"):
        error = str(state["error"])
        if "dubious ownership" in error.lower():
            project_path = os.path.abspath(PROJECT).replace("\\", "/")
            print(
                "Git found this repository but refused it because its ownership is untrusted. "
                "Ask the user to approve this exact checkout with `git config --global "
                f"--add safe.directory \"{project_path}\"`, then rerun `ai git setup`. "
                "Do not use a wildcard safe.directory entry.",
                file=sys.stderr,
            )
            return 1
        if "not a git repository" not in error.lower():
            print(f"Could not inspect the project Git repository: {error}", file=sys.stderr)
            return 1

    initialized = False
    if not state.get("repo"):
        production = repo.git_config()["production"]
        code, _, err = repo.run_git(["init", f"--initial-branch={production}"])
        if code != 0 and any(
            marker in err.lower()
            for marker in ("unknown option", "unrecognized option", "unknown switch")
        ):
            code, _, err = repo.run_git(["init"])
        if code != 0:
            print(f"Could not initialize Git in {PROJECT}: {err}", file=sys.stderr)
            return 1
        code, _, err = repo.run_git(["symbolic-ref", "HEAD", f"refs/heads/{production}"])
        if code != 0:
            print(f"Could not select the production branch: {err}", file=sys.stderr)
            return 1
        initialized = True
        state = repo.git_state()
        if not state.get("repo"):
            print(f"Git initialization did not produce a readable repository: {state.get('error') or 'unknown error'}", file=sys.stderr)
            return 1
    config = repo.git_config()
    template = repo.git_template_path()
    if not os.path.isfile(template):
        print(f"Commit template not found: {os.path.relpath(template, PROJECT)}", file=sys.stderr)
        return 1
    config_code, current_template, _ = repo.run_git(["config", "--local", "--get", "commit.template"])
    if (
        config_code != 0
        or os.path.normcase(os.path.abspath(current_template)) != os.path.normcase(os.path.abspath(template))
    ):
        code, _, err = repo.run_git(["config", "--local", "commit.template", template])
        if code != 0:
            print(f"Could not set commit.template: {err}", file=sys.stderr)
            return 1
    created_production = False
    created_integration = False
    created_baseline = False
    if repo.branch_ref_exists(config["production"]) and not repo.branch_exists(config["production"]):
        print(
            f"Production branch '{config['production']}' exists but does not resolve to a commit. "
            "Repair that ref manually before rerunning setup.",
            file=sys.stderr,
        )
        return 1
    if not state.get("head"):
        refs_code, refs_output, refs_err = repo.run_git([
            "for-each-ref", "--format=%(refname:short)", "refs/heads",
        ])
        if refs_code != 0:
            print(f"Could not inspect local Git branches: {refs_err}", file=sys.stderr)
            return 1
        refs: list[tuple[str, str]] = []
        for line in refs_output.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            commit = repo.git_commit_id(f"refs/heads/{candidate}")
            if commit:
                refs.append((candidate, commit))
        if repo.branch_exists(config["production"]):
            pass
        elif refs:
            current_ref = f"refs/heads/{state.get('branch')}"
            base_commit = next(
                (commit for ref, commit in refs if ref == current_ref), refs[0][1],
            )
            code, _, err = repo.run_git(["branch", config["production"], base_commit])
            if code != 0:
                print(f"Could not create production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            created_production = True
        else:
            code, _, err = repo.run_git(["symbolic-ref", "HEAD", f"refs/heads/{config['production']}"])
            if code != 0:
                print(f"Could not select production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            completed, result = repo.confirm_initial_baseline(args, config["production"])
            if not completed:
                return result
            created_baseline = True
            created_production = True
        if not repo.branch_exists(config["production"]):
            print(f"Production branch '{config['production']}' is still missing.", file=sys.stderr)
            return 1
        state = repo.git_state()
        if not state.get("head"):
            code, _, err = repo.run_git(["symbolic-ref", "HEAD", f"refs/heads/{config['production']}"])
            if code != 0:
                print(f"Could not select production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            state = repo.git_state()
        if not state.get("head"):
            print("Gitflow setup could not establish a committed production base.", file=sys.stderr)
            return 1
    elif not repo.branch_exists(config["production"]):
        base_commit = state.get("head") or repo.git_commit_id("HEAD")
        if not base_commit:
            print("Cannot create the production branch: current HEAD has no commit.", file=sys.stderr)
            return 1
        code, _, err = repo.run_git(["branch", config["production"], base_commit])
        if code != 0:
            print(f"Could not create production branch '{config['production']}': {err}", file=sys.stderr)
            return 1
        created_production = True
    if not repo.branch_exists(config["integration"]):
        if repo.branch_ref_exists(config["integration"]):
            print(
                f"Integration branch '{config['integration']}' exists but does not resolve to a commit. "
                "Repair that ref manually before rerunning setup.",
                file=sys.stderr,
            )
            return 1
        production_commit = repo.git_commit_id(f"refs/heads/{config['production']}")
        if not production_commit:
            print(
                f"Cannot create integration branch '{config['integration']}': "
                f"production branch '{config['production']}' has no commit.",
                file=sys.stderr,
            )
            return 1
        code, _, err = repo.run_git([
            "branch", config["integration"], production_commit,
        ])
        if code != 0:
            print(f"Could not create integration branch '{config['integration']}': {err}", file=sys.stderr)
            return 1
        created_integration = True
    if args.json:
        print(json.dumps({
            "repo": True,
            "commitTemplate": os.path.relpath(template, PROJECT).replace(os.sep, "/"),
            "integration": config["integration"],
            "production": config["production"],
            "initializedRepository": initialized,
            "createdBaseline": created_baseline,
            "createdProduction": created_production,
            "createdIntegration": created_integration,
        }, indent=2))
        return 0
    print(f"commit.template = {os.path.relpath(template, PROJECT)}")
    if initialized:
        print("Git repository: initialized")
    if created_baseline:
        print(f"production branch: {config['production']} (created with the confirmed baseline)")
    else:
        print(f"production branch: {config['production']}" + (" (created)" if created_production else " (exists)"))
    print(f"integration branch: {config['integration']}" + (" (created)" if created_integration else " (exists)"))
    print("Next: ai task claim <id> --agent <name>, then ai git start ...")
    return 0


def cmd_git_start(args) -> int:
    path = store.find_task(args.task)
    if not path:
        print(f"No task with id {args.task}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) != ACTIVE_DIR:
        print("The task is already in done/. Start a branch before finishing it.", file=sys.stderr)
        return 1
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    owner_error = store.task_owner_error(meta, args.agent, args.force)
    if owner_error:
        print(owner_error, file=sys.stderr)
        return 1
    state = repo.git_state()
    if not state.get("repo"):
        print("Not a git repository.", file=sys.stderr)
        return 1
    if not repo.git_clean(ignore_ledger=True):
        print(
            "Working tree has product changes. Commit or stash them before "
            "starting a task branch (only tasks/ and specs/ may stay uncommitted).",
            file=sys.stderr,
        )
        return 1
    config = repo.git_config()
    branch_type = args.type
    if branch_type not in config["branchTypes"]:
        print(
            f"Unknown branch type '{branch_type}'. Use one of: {', '.join(config['branchTypes'])}.",
            file=sys.stderr,
        )
        return 1
    if not repo.branch_exists(config["integration"]):
        print(f"Integration branch '{config['integration']}' is missing. Run `ai git setup`.", file=sys.stderr)
        return 1
    base = args.base or (
        config["production"] if branch_type == "hotfix" else config["integration"]
    )
    if not repo.branch_exists(base):
        print(f"Base branch '{base}' does not exist.", file=sys.stderr)
        return 1
    branch = repo.task_branch_name(meta, branch_type)
    ok, owned, error = repo.acquire_git_guard(args.agent, task_id)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
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
        body = body.rstrip("\n") + f"\n- {iso()} {action} branch {branch} from {base} by {args.agent}\n"
        store.write_task(path, meta, body)
        board.write_board(store.load_tasks())
    finally:
        repo.release_git_guard(owned, args.agent)
    if args.json:
        print(json.dumps({"task": task_id, "branch": branch, "base": base, "action": action}, indent=2))
    else:
        print(f"{action.capitalize()} {branch} from {base}.")
        print(f"Task {task_id} now points at that branch. Commit only files you own.")
    return 0


def cmd_git_commit(args) -> int:
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
    if args.verify:
        uncovered, _ = repo.uncovered_staged(state)
        if uncovered:
            print("Refusing commit; staged paths have no held file lock:", file=sys.stderr)
            for item in uncovered:
                print(f"  {item}", file=sys.stderr)
            return 1
    scope_problems = task_scope.violations(
        meta, [p for p in state.get("staged", []) if not repo.is_workspace_ledger_path(p)]
    )
    if scope_problems and not getattr(args, "force", False):
        print(f"Refusing commit; staged paths leave the scope of task {task_id}:", file=sys.stderr)
        for item in scope_problems:
            print(f"  {item}", file=sys.stderr)
        print("Unstage them, or widen the task's scope_allowed/scope_forbidden deliberately.", file=sys.stderr)
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
    state = repo.git_state()
    if state.get("dirty"):
        print("Working tree is dirty. Commit or stash before merging.", file=sys.stderr)
        return 1
    if not repo.branch_exists(branch):
        print(f"Task branch '{branch}' does not exist.", file=sys.stderr)
        return 1
    config = repo.git_config()
    integration = config["integration"]
    if not repo.branch_exists(integration):
        print(f"Integration branch '{integration}' is missing. Run `ai git setup`.", file=sys.stderr)
        return 1
    ok, owned, error = repo.acquire_git_guard(args.agent, task_id)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
        check = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "ai.py"), "check", "--strict"],
            cwd=PROJECT,
        )
        if check.returncode != 0:
            print("ai check --strict failed; refusing to merge.", file=sys.stderr)
            return 1
        current = repo.git_state().get("branch")
        if current != branch:
            code, _, err = repo.run_git(["checkout", branch])
            if code != 0:
                print(f"Could not switch to {branch}: {err}", file=sys.stderr)
                return 1
        code, _, err = repo.run_git(["checkout", integration])
        if code != 0:
            print(f"Could not switch to {integration}: {err}", file=sys.stderr)
            return 1
        merge_message = f"merge: {branch} ({task_id})"
        code, _, err = repo.run_git(["merge", "--no-ff", branch, "-m", merge_message])
        if code != 0:
            repo.run_git(["merge", "--abort"])
            print(f"Merge failed and was aborted: {err}", file=sys.stderr)
            return 1
        _, merged_head, _ = repo.run_git(["rev-parse", "--short", "HEAD"])
        deleted = False
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
