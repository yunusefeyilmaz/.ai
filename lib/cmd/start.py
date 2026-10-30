"""cmd.start: split out of the former monolithic ai.py."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys

from lib.core.paths import (
    PROJECT,
    VERSION,
    WORKSPACE,
    workspace_shape,
)
from lib.config.settings import (
    config_path,
    default_config,
    load_config,
)
from lib.core.fsio import write_json_atomic
from lib.runtime.dirs import ensure_dirs
from lib.config import adopt as config_adopt
from lib.git import flow
from lib.git import repo
from lib.tasks import lifecycle
from lib.tasks import store


def cmd_start(args) -> int:
    """Prepare the workspace, report what exists, and name the next two steps."""
    ensure_dirs()
    if not os.path.exists(config_path()):
        write_json_atomic(config_path(), default_config())

    shape = workspace_shape()
    adapter_report: list[tuple[str, str]] = []
    ignore_report = {"state": "not-needed", "missing": []}
    if shape == "subfolder":
        try:
            adapter_report = config_adopt.adopt_root()
            state, missing = config_adopt.adopt_gitignore()
            ignore_report = {"state": state, "missing": missing}
        except OSError as exc:
            print(f"Could not wire the local adapters: {exc}", file=sys.stderr)
            return 1

    state = repo.git_state()
    setup_error = ""
    if state.get("repo") and state.get("head"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            setup_code = flow.cmd_git_setup(argparse.Namespace(json=False))
        if setup_code != 0:
            setup_error = (out.getvalue() + err.getvalue()).strip()
            print(setup_error, file=sys.stderr)
        state = repo.git_state()
    branches = repo.git_config()
    git_ready = bool(
        state.get("repo")
        and state.get("head")
        and repo.branch_exists(branches["integration"])
        and repo.branch_exists(branches["production"])
    )

    created = None
    try:
        tasks = store.load_tasks()
    except OSError:
        tasks = []
    active_tasks = [task for task in tasks if task["_folder"] == "active"]
    if not active_tasks and args.demo:
        try:
            created = lifecycle.create_task("Try the workspace")
        except RuntimeError:
            created = None
        if created:
            active_tasks = [task for task in store.load_tasks() if task["_folder"] == "active"]

    target = active_tasks[0] if active_tasks else None

    claimed = False
    claim_error = None
    if target and args.agent and not target.get("owner"):
        ok, message = lifecycle.claim_task(target["_path"], args.agent)
        if ok:
            claimed = True
            target = next(
                (task for task in store.load_tasks() if str(task.get("id")) == str(message)),
                target,
            )
        else:
            claim_error = message

    next_steps: list[str] = []
    if not git_ready:
        next_steps.append("ai git setup")
    if target:
        owner = target.get("owner") or (args.agent if claimed else None)
        current_branch = state.get("branch")
        if owner and target.get("branch") and target.get("branch") == current_branch:
            pass  # The task branch is already checked out.
        elif owner:
            next_steps.append(
                f"ai git start --task {target.get('id')} --agent {owner} --type feature"
            )
        else:
            next_steps.append(f"ai task claim {target.get('id')} --agent <name>")
    else:
        next_steps.append('ai task new "<title>"')
    next_steps.append("ai check --fast")

    if claim_error:
        print(claim_error, file=sys.stderr)

    if args.json:
        payload = {
            "workspace": WORKSPACE,
            "project": PROJECT,
            "version": VERSION,
            "shape": shape,
            "mode": load_config().get("mode"),
            "adapters": [{"path": path, "state": item} for path, item in adapter_report],
            "gitignore": ignore_report,
            "git": {
                "repo": bool(state.get("repo")),
                "head": bool(state.get("head")),
                "branch": state.get("branch"),
                "integration": branches["integration"],
                "production": branches["production"],
                "ready": git_ready,
                "error": setup_error or None,
            },
            "task": {
                "id": target.get("id"),
                "title": target.get("title"),
                "owner": target.get("owner"),
                "spec": target.get("spec"),
            } if target else None,
            "claimed": claimed,
            "created": bool(created),
            "next": next_steps,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 1 if claim_error else 0

    print(f"Workspace : {WORKSPACE}")
    print(f"Shape     : {shape}" + (" install" if shape == "subfolder" else " template"))
    print(f"Mode      : {load_config().get('mode')}")
    if shape == "subfolder":
        written = [item for _, item in adapter_report if item != "unchanged"]
        print(f"Adapters  : {len(adapter_report)} local file(s), {len(written)} changed")
    else:
        print("Adapters  : not needed (the root AGENTS.md is the entry point)")
    if git_ready:
        print(
            f"Git       : ready (integration {branches['integration']}, "
            f"production {branches['production']})"
        )
    elif state.get("repo"):
        print("Git       : repository found, Gitflow base missing")
    else:
        print("Git       : not initialized")
    if target:
        owner = f" ({target.get('owner')})" if target.get("owner") else ""
        print(f"Task      : {target.get('id')} {target.get('title')}{owner}")
        if target.get("spec"):
            print(f"Spec      : {target.get('spec')}")
    else:
        print("Task      : none yet")
    print("\nNext:")
    for index, step in enumerate(next_steps, 1):
        print(f"  {index}. {step}")
    print("\nFull loop: GUIDE.md#first-pass-clone-to-verified-change")
    return 1 if claim_error else 0


ORDER = 50


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    start = sub.add_parser(
        "start", help="prepare the workspace and leave a first task ready to claim"
    )
    start.add_argument("--agent", default=None, help="claim the first task for this agent")
    start.add_argument(
        "--demo", dest="demo", action="store_true", default=True,
        help="create a starter task when the ledger is empty (default)",
    )
    start.add_argument("--no-demo", dest="demo", action="store_false")
    start.add_argument("--json", action="store_true")
    start.set_defaults(func=cmd_start)
