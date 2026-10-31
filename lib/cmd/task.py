"""cmd.task: split out of the former monolithic ai.py."""

from __future__ import annotations

import argparse
import json
import os
import sys

from lib.core.paths import (
    ACTIVE_DIR,
    DONE_DIR,
    LOCKS_DIR,
    PROJECT,
    WORKSPACE,
)
from lib.config.settings import lock_settings
from lib.core.fsio import (
    normalize_id,
    read_json,
    safe_name,
)
from lib.core.timeutil import iso
from lib.runtime.events import append_event
from lib.runtime.leases import (
    acquire_lock,
    list_locks,
    lock_is_stale,
    release_lock,
    resources_overlap,
)
from lib.runtime.mutex import (
    registry_mutex,
    workspace_state_guard,
)
from lib.runtime import checkpoints as ckpt
from lib.config import roles
from lib.config import settings
from lib.git import flow
from lib.git import repo
from lib.runtime import evidence
from lib.runtime import health
from lib.tasks import gates
from lib.tasks import history
from lib.tasks import scope
from lib.tasks import board
from lib.tasks import discard
from lib.tasks import lifecycle
from lib.tasks import links
from lib.tasks import store


def cmd_task_new(args) -> int:
    denied = roles.authorize(getattr(args, "agent", None), "task.new")
    if denied:
        print(denied, file=sys.stderr)
        return 1
    try:
        created = lifecycle.create_task(
            args.title,
            args.priority,
            args.spec,
            getattr(args, "depends_on", None),
            make_spec=not getattr(args, "no_spec", False),
            scope_allowed=scope.join_globs(getattr(args, "allow", None)),
            scope_forbidden=scope.join_globs(getattr(args, "forbid", None)),
            actor=getattr(args, "agent", None),
        )
    except RuntimeError:
        return 1
    print(f"Created {os.path.relpath(created['path'], PROJECT)}")
    if created["spec"]:
        print(f"Spec: {created['spec']}")
    print(f"Claim it: ai task claim {created['id']} --agent <name>")
    return 0


def cmd_task_list(args) -> int:
    try:
        with workspace_state_guard():
            tasks = store.load_tasks()
            board.write_board(tasks)
    except RuntimeError as exc:
        print(f"Cannot refresh the task board: {exc}.", file=sys.stderr)
        return 1
    active = [task for task in tasks if task["_folder"] == "active"]
    done = [task for task in tasks if task["_folder"] == "done"]
    if args.json:
        print(json.dumps({"active": active, "done": done}, indent=2, default=str))
        return 0
    print(f"{'ID':<6} {'FOLDER':<8} {'STATUS':<12} {'OWNER':<18} TITLE")
    for task in active + done if args.all else active:
        print(
            f"{str(task.get('id')):<6} {task['_folder']:<8} {str(task.get('status')):<12} "
            f"{str(task.get('owner') or '-'):<18} {task.get('title')}"
        )
    print(f"\nActive: {len(active)} | Done: {len(done)} | Board: tasks/BOARD.md")
    return 0


def cmd_task_show(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, body = store.parse_task(path)
    ci_results = [
        line.strip().lstrip("- ")
        for line in body.splitlines()
        if "CI:" in line
    ]
    if args.json:
        payload = {"meta": meta, "body": body}
        if ci_results:
            payload["ci_results"] = ci_results
        print(json.dumps(payload, indent=2, default=str))
        return 0
    print(f"File: {os.path.relpath(path, PROJECT)}")
    for key, value in meta.items():
        print(f"{key}: {value}")
    if ci_results:
        print("\nCI results:")
        for r in ci_results:
            print(f"  {r}")
    print()
    print(body)
    return 0


def cmd_task_claim(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    ok, message = _claim(path, args.agent, args.force)
    if not ok:
        print(message, file=sys.stderr)
        return 1
    print(f"Release without delivering: ai task release {message} --agent {args.agent}")
    return 0


def _claim(path: str, agent: str, force: bool = False) -> tuple[bool, str]:
    """Claim a task and do the standard set-up so the worker does not have to.

    One command: task lock + in_progress, every file lock the task declared
    (all or nothing), and the task branch when Git is enabled.
    """
    meta, _ = store.parse_task(path)
    held_ok, held = lifecycle.acquire_task_locks(meta, agent) if meta.get("status") != "review" else (True, "")
    if not held_ok:
        return False, held
    ok, message = lifecycle.claim_task(path, agent, force)
    if not ok:
        if meta.get("status") != "review":
            lifecycle.release_task_locks(meta, agent)
        return False, message
    print(f"Claimed {message} for {agent}.")
    if held:
        print(f"  file locks: {held}")
    if meta.get("status") != "review" and settings.git_enabled():
        state = repo.git_state()
        if not state.get("repo") or not state.get("head"):
            print("  git: not initialized; run `ai git setup` once (or `ai setup --set git=no`).")
        else:
            started = flow.cmd_git_start(argparse.Namespace(
                task=message, agent=agent, type="feature", base=None, force=False, json=False,
            ))
            if started != 0:
                print(f"  git: could not start the task branch; fix the message above, then `ai git start --task {message} --agent {agent}`.")
    return True, message


def cmd_task_ready(args) -> int:
    ready, waiting = lifecycle.ready_and_waiting()
    if args.json:
        print(json.dumps({
            "ready": ready,
            "waiting": [{"task": task, "reasons": reasons} for task, reasons in waiting],
        }, indent=2, default=str))
        return 0
    if ready:
        print(f"{'ID':<6} {'PRIORITY':<10} {'SPEC':<28} TITLE")
        for task in ready:
            print(
                f"{str(task.get('id')):<6} {str(task.get('priority') or '-'):<10} "
                f"{str(task.get('spec') or '-'):<28} {task.get('title')}"
            )
    else:
        print("No ready task.")
    if waiting:
        print("\nWaiting:")
        for task, reasons in waiting:
            print(f"  {task.get('id')} {task.get('title')}: {'; '.join(reasons)}")
    return 0


def _next_review(args) -> int:
    queue = [
        t for t in store.load_tasks()
        if t["_folder"] == "active" and t.get("status") == "review"
        and t.get("submitted_by") != args.agent and not t.get("owner")
    ]
    queue.sort(key=lambda t: str(t.get("id")))
    for task in queue:
        ok, message = _claim(task["_path"], args.agent)
        if not ok:
            print(f"Skipped {task.get('id')}: {message}", file=sys.stderr)
            continue
        meta, _ = store.parse_task(store.find_task(message))
        if args.json:
            print(json.dumps({"meta": meta}, indent=2, default=str))
            return 0
        print(f"Review: {meta.get('title')} (submitted by {meta.get('submitted_by')})")
        if meta.get("spec"):
            print(f"Spec: {meta.get('spec')}")
        print(f"History: ai history {message}")
        print(f"Approve:  ai git finish --task {message} --agent {args.agent}, then ai task done {message} --agent {args.agent}")
        print(f"Reject:   ai task request-changes {message} --agent {args.agent} --reason \"...\"")
        return 0
    print("Nothing is waiting for review.", file=sys.stderr)
    return 1


def cmd_task_next(args) -> int:
    if getattr(args, "review", False):
        return _next_review(args)
    ready, waiting = lifecycle.ready_and_waiting()
    for task in ready:
        ok, message = _claim(task["_path"], args.agent)
        if not ok:
            print(f"Skipped {task.get('id')}: {message}", file=sys.stderr)
            continue
        claimed_path = store.find_task(message)
        meta, body = store.parse_task(claimed_path)
        if args.json:
            print(json.dumps({"meta": meta, "body": body}, indent=2, default=str))
            return 0
        print(f"Task: {meta.get('title')}")
        if meta.get("spec"):
            print(f"Spec: {meta.get('spec')}")
        print(f"Read it: ai task show {message}")
        return 0
    if args.json:
        print(json.dumps({
            "ready": [],
            "waiting": [{"task": task, "reasons": reasons} for task, reasons in waiting],
        }, indent=2, default=str))
        return 1
    print("No ready task. Nothing was claimed.", file=sys.stderr)
    for task, reasons in waiting:
        print(f"  {task.get('id')} {task.get('title')}: {'; '.join(reasons)}", file=sys.stderr)
    return 1


def cmd_task_release(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = store.parse_task(path)
    task_id = str(meta.get("id"))
    resource = f"task-{task_id}"
    lifecycle.release_task_locks(meta, args.agent if not args.force else None)
    try:
        with workspace_state_guard():
            current_path = store.find_task(task_id)
            if current_path != path:
                print(f"Task {task_id} changed before release.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(current_path)
            if meta.get("owner") and meta.get("owner") != args.agent and not args.force:
                print(
                    f"Task {task_id} is owned by {meta.get('owner')}. Use --force to override.",
                    file=sys.stderr,
                )
                return 1
            meta["owner"] = None
            meta["lock"] = None
            previous = meta.get("status")
            if previous == "in_progress":
                meta["status"] = "todo"
            meta["updated"] = iso()
            body = history.append(body, args.agent, previous, meta["status"], "released")
            store.write_task(current_path, meta, body)
            board.write_board(store.load_tasks())
    except RuntimeError as exc:
        print(f"Cannot release task {task_id}: {exc}.", file=sys.stderr)
        return 1
    result = release_lock(resource, agent=args.agent, force=args.force)
    if result == 0:
        append_event("task_released", task=task_id, agent=args.agent)
    return result


def _auto_verify(path: str, agent: str) -> str | None:
    """Run the project checks for the task when verification is required and not yet green.

    `ai task review` is the single delivery command: it verifies first, so the
    worker never has to remember a separate `ai check` step.
    """
    if not gates.check_required() or not settings.configured_checks():
        return None
    meta, _ = store.parse_task(path)
    if meta.get("owner") != agent or meta.get("status") != "in_progress":
        return None  # the normal review checks will explain
    task_id = str(meta.get("id"))
    head = repo.git_state().get("head")
    if evidence.task_green(task_id, head)[0]:
        return None
    print(f"Running the project checks for task {task_id} before review...", file=sys.stderr)
    results: list[dict] = []
    problems = health.run_commands(False, results)
    ok = not any(item.level == "error" for item in problems)
    evidence.record_task_check(
        task_id, agent, ok, head=head, checks=results, strict=False, ran_commands=True, fast=False,
    )
    if not ok:
        return (
            f"Task {task_id} cannot enter review: the project checks failed. Fix them, then run "
            f"`ai task review {task_id} --agent {agent}` again."
        )
    return None


def cmd_task_review(args) -> int:
    path = store.find_task(args.task_id)
    if not path or os.path.dirname(path) != ACTIVE_DIR:
        print(f"No active task with id {args.task_id}.", file=sys.stderr)
        return 1
    auto_error = _auto_verify(path, args.agent)
    if auto_error:
        print(auto_error, file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = store.find_task(args.task_id)
            if current_path != path or os.path.dirname(current_path or "") != ACTIVE_DIR:
                print(f"Task {args.task_id} changed before review.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(current_path)
            task_id = str(meta.get("id"))
            if meta.get("status") != "in_progress":
                print(f"Task {task_id} must be in_progress to enter review.", file=sys.stderr)
                return 1
            if meta.get("owner") != args.agent:
                print(f"Task {task_id} is not owned by {args.agent}.", file=sys.stderr)
                return 1
            holder = read_json(os.path.join(LOCKS_DIR, safe_name(f"task-{task_id}") + ".lock")) or {}
            if holder.get("agent") != args.agent:
                print(f"Task {task_id} does not have a live claim for {args.agent}.", file=sys.stderr)
                return 1
            denied = roles.authorize(args.agent, "task.review")
            if denied:
                print(denied, file=sys.stderr)
                return 1
            gate_error, proof = gates.review_gate(meta, args.agent)
            if gate_error:
                print(gate_error, file=sys.stderr)
                return 1
            meta["status"] = "review"
            meta["submitted_by"] = args.agent
            meta["updated"] = iso()
            body = history.append(body, args.agent, "in_progress", "review", "submitted for independent review", proof)
            store.write_task(current_path, meta, body)
            board.write_board(store.load_tasks())
    except RuntimeError as exc:
        print(f"Cannot submit task {args.task_id} for review: {exc}.", file=sys.stderr)
        return 1
    append_event("task_reviewed", task=task_id, agent=args.agent)
    lifecycle.release_task_locks(meta, args.agent)
    print(f"Task {task_id} is delivered for review. Release it before reviewer takeover: ai task release {task_id} --agent {args.agent}")
    print(f"Reviewer next: ai git finish --task {task_id} --agent <reviewer>, then ai task done {task_id} --agent <reviewer>")
    if not gates.workflow_config()["autoContinue"]:
        print("STOP: report what you delivered and wait for the user before starting another task.")
    return 0


def cmd_task_request_changes(args) -> int:
    path = store.find_task(args.task_id)
    if not path or os.path.dirname(path) != ACTIVE_DIR:
        print(f"No active task with id {args.task_id}.", file=sys.stderr)
        return 1
    denied = roles.authorize(args.agent, "task.request_changes")
    if denied:
        print(denied, file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = store.find_task(args.task_id)
            if current_path != path:
                print(f"Task {args.task_id} changed before changes could be requested.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(current_path)
            task_id = str(meta.get("id"))
            gate_error = gates.request_changes_gate(meta, args.agent)
            if gate_error:
                print(gate_error, file=sys.stderr)
                return 1
            meta["status"] = "changes_requested"
            meta["changes_requested_by"] = args.agent
            meta["owner"] = None
            meta["lock"] = None
            meta["updated"] = iso()
            body = history.append(body, args.agent, "review", "changes_requested", args.reason)
            store.write_task(current_path, meta, body)
            board.write_board(store.load_tasks())
        release_lock(f"task-{task_id}", force=True)
    except RuntimeError as exc:
        print(f"Cannot request changes on task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    append_event("task_changes_requested", task=task_id, agent=args.agent)
    print(f"Task {task_id} sent back to its producer ({meta.get('submitted_by')}): {args.reason}")
    print(f"Producer next: ai task claim {task_id} --agent <producer>")
    return 0


def cmd_task_block(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = store.find_task(args.task_id)
            if current_path != path:
                print(f"Task {args.task_id} changed before it could be blocked.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(current_path)
            previous = meta.get("status")
            meta["status"] = "blocked"
            meta["updated"] = iso()
            body = history.append(body, args.agent, previous, "blocked", args.reason)
            store.write_task(current_path, meta, body)
            board.write_board(store.load_tasks())
    except RuntimeError as exc:
        print(f"Cannot block task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Blocked {meta.get('id')}: {args.reason}")
    return 0


def cmd_task_unblock(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = store.find_task(args.task_id)
            if current_path != path:
                print(f"Task {args.task_id} changed before it could be unblocked.", file=sys.stderr)
                return 1
            meta, body = store.parse_task(current_path)
            previous = meta.get("status")
            meta["status"] = "todo"
            meta["updated"] = iso()
            body = history.append(body, args.agent, previous, "todo", "unblocked")
            store.write_task(current_path, meta, body)
            board.write_board(store.load_tasks())
    except RuntimeError as exc:
        print(f"Cannot unblock task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Unblocked {meta.get('id')}.")
    return 0


def cmd_task_done(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) == DONE_DIR:
        print("Task is already done.")
        return 0
    meta, body = store.parse_task(path)
    task_id = str(meta.get("id"))
    denied = None if args.force else roles.authorize(args.agent, "task.done")
    if denied:
        print(denied, file=sys.stderr)
        return 1
    gate_error = gates.done_gate(meta, args.agent, args.force)
    if gate_error:
        print(gate_error, file=sys.stderr)
        return 1
    resource = f"task-{task_id}"
    holder = read_json(os.path.join(LOCKS_DIR, safe_name(resource) + ".lock"))
    if not holder:
        result = acquire_lock(resource, agent=args.agent, task=task_id, force=args.force)
        if not result["ok"]:
            append_event("lock_refused", resource=resource, agent=args.agent, task=task_id)
            print(f"Task {task_id} is locked by {result['holder'].get('agent')}.", file=sys.stderr)
            return 1
    elif holder.get("agent") != args.agent and not args.force:
        append_event("lock_refused", resource=resource, agent=args.agent, task=task_id)
        print(f"Task {task_id} is locked by {holder.get('agent')}.", file=sys.stderr)
        return 1
    previous = meta.get("status")
    meta["status"] = "done"
    meta["reviewed_by"] = args.agent
    meta["updated"] = iso()
    meta["lock"] = None
    forced = "forced: review gate bypassed" if args.force and meta.get("submitted_by") in (None, args.agent) else "approved"
    records = evidence.task_records(task_id)
    proof = evidence.summary(records[-1]) if records else ""
    body = history.append(body, args.agent, previous, "done", forced, proof)
    store.write_task(path, meta, body)
    target = os.path.join(DONE_DIR, os.path.basename(path))
    os.replace(path, target)
    release_lock(resource, force=True)
    lifecycle.release_task_locks(meta, None)
    marker = ckpt.handoff_marker(task_id)
    if os.path.exists(marker):
        try:
            os.remove(marker)
        except OSError:
            pass
    board.write_board(store.load_tasks())
    append_event(
        "task_done", task=task_id, agent=args.agent, forced=True if args.force else None,
        submitted_by=meta.get("submitted_by"),
    )
    print(f"Done: {os.path.relpath(target, PROJECT)}")
    return 0


def cmd_task_discard(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = store.parse_task(path)
    task_id = normalize_id(str(meta.get("id") or args.task_id))
    if not sys.stdin.isatty():
        print("Discard requires an interactive terminal; no files were changed.", file=sys.stderr)
        return 1

    spec_path, spec_error = discard.task_discard_spec_path(meta, task_id)
    if spec_error:
        print(f"Cannot safely discard task: {spec_error}", file=sys.stderr)
        return 1
    targets = discard.task_discard_targets(path, spec_path, task_id)
    lock_error = discard.task_discard_lock_error(task_id, targets)
    if lock_error:
        print(lock_error, file=sys.stderr)
        return 1
    _, stale_after = lock_settings()
    for lock in list_locks():
        if lock_is_stale(lock, stale_after):
            continue
        resource = str(lock.get("resource") or "")
        overlaps = False
        for target in targets:
            aliases = {
                os.path.relpath(target, WORKSPACE).replace(os.sep, "/"),
                os.path.relpath(target, PROJECT).replace(os.sep, "/"),
            }
            try:
                if any(resources_overlap(alias, resource) for alias in aliases):
                    overlaps = True
                    break
            except ValueError:
                continue
        if overlaps:
            print(
                f"Task {task_id} has a related live file lock held by {lock.get('agent')} "
                f"({resource}); refusing discard.",
                file=sys.stderr,
            )
            return 1
    print(f"This permanently discards task {task_id}: {meta.get('title')}")
    print("It removes the task, its matching spec, and its continuation files.")
    expected = f"discard task {task_id}"
    try:
        confirmation = input(f"Type '{expected}' to continue: ").strip()
    except EOFError:
        confirmation = ""
    if confirmation != expected:
        print("Confirmation did not match; no files were changed.", file=sys.stderr)
        return 1

    try:
        with registry_mutex():
            current_path = store.find_task(task_id)
            if current_path != path:
                print(f"Task {task_id} changed while awaiting confirmation; retry.", file=sys.stderr)
                return 1
            current_meta, _ = store.parse_task(current_path)
            if current_meta.get("title") != meta.get("title") or current_meta.get("spec") != meta.get("spec"):
                print(f"Task {task_id} changed while awaiting confirmation; retry.", file=sys.stderr)
                return 1
            current_spec, error = discard.task_discard_spec_path(current_meta, task_id)
            if error:
                print(f"Cannot safely discard task: {error}", file=sys.stderr)
                return 1
            current_targets = discard.task_discard_targets(current_path, current_spec, task_id)
            lock_error = discard.task_discard_lock_error(task_id, current_targets)
            if lock_error:
                print(lock_error, file=sys.stderr)
                return 1
            # Keep the task file until all linked state is removed, so a failed
            # cleanup remains visible and can be retried.
            for target in current_targets[:-1]:
                os.remove(target)
            os.remove(current_path)
            board.write_board(store.load_tasks())
    except OSError as exc:
        print(f"Could not discard task {task_id}: {exc}", file=sys.stderr)
        return 1
    print(f"Discarded task {task_id}; removed {len(current_targets)} file(s).")
    return 0


def cmd_task_link(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    if not args.issue and not args.pr:
        print("Specify at least --issue or --pr.", file=sys.stderr)
        return 1
    meta, body = links.link_task_github(path, issue=args.issue, pr=args.pr, agent=args.agent)
    if args.json:
        print(json.dumps({"ok": True, "meta": meta, "task": args.task_id}, indent=2, default=str))
        return 0
    print(f"Linked task {args.task_id} to GitHub: issue={args.issue}, pr={args.pr}")
    return 0


ORDER = 60


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    task = sub.add_parser("task", help="manage local tasks")
    task_sub = task.add_subparsers(dest="action", required=True)

    task_new = task_sub.add_parser("new", help="create a task")
    task_new.add_argument("title")
    task_new.add_argument("--priority", default="medium", choices=["low", "medium", "high"])
    task_new.add_argument("--spec", default=None)
    task_new.add_argument("--no-spec", dest="no_spec", action="store_true",
                          help="do not create a spec skeleton")
    task_new.add_argument("--depends-on", dest="depends_on", default=None)
    task_new.add_argument("--allow", action="append", default=None, metavar="GLOB",
                          help="path the task may touch (repeatable, `**` allowed); enforced by git verify/commit")
    task_new.add_argument("--forbid", action="append", default=None, metavar="GLOB",
                          help="path the task must not touch (repeatable)")
    task_new.add_argument("--agent", default=None, help="who creates the task (checked against roles)")
    task_new.set_defaults(func=cmd_task_new)

    task_list = task_sub.add_parser("list", help="list tasks and refresh the board")
    task_list.add_argument("--all", action="store_true", help="include done tasks")
    task_list.add_argument("--json", action="store_true")
    task_list.set_defaults(func=cmd_task_list)

    task_show = task_sub.add_parser("show", help="print a task")
    task_show.add_argument("task_id")
    task_show.add_argument("--json", action="store_true")
    task_show.set_defaults(func=cmd_task_show)

    task_link = task_sub.add_parser("link", help="link GitHub issue and/or PR to task")
    task_link.add_argument("task_id")
    task_link.add_argument("--issue", default=None, help="GitHub issue URL or number")
    task_link.add_argument("--pr", default=None, help="GitHub pull request URL or number")
    task_link.add_argument("--agent", default=None)
    task_link.add_argument("--json", action="store_true")
    task_link.set_defaults(func=cmd_task_link)

    task_ready = task_sub.add_parser("ready", help="list claimable tasks whose dependencies are done")
    task_ready.add_argument("--json", action="store_true")
    task_ready.set_defaults(func=cmd_task_ready)

    task_next = task_sub.add_parser("next", help="atomically claim the highest-priority ready task")
    task_next.add_argument("--agent", required=True)
    task_next.add_argument("--review", action="store_true", help="reviewer: claim the oldest task waiting for review")
    task_next.add_argument("--json", action="store_true")
    task_next.set_defaults(func=cmd_task_next)

    task_claim = task_sub.add_parser("claim", help="atomically claim a task")
    task_claim.add_argument("task_id")
    task_claim.add_argument("--agent", required=True)
    task_claim.add_argument("--force", action="store_true")
    task_claim.set_defaults(func=cmd_task_claim)

    task_release = task_sub.add_parser("release", help="release a claimed task")
    task_release.add_argument("task_id")
    task_release.add_argument("--agent", required=True)
    task_release.add_argument("--force", action="store_true")
    task_release.set_defaults(func=cmd_task_release)

    task_review = task_sub.add_parser("review", help="submit an owned task for independent review")
    task_review.add_argument("task_id")
    task_review.add_argument("--agent", required=True)
    task_review.set_defaults(func=cmd_task_review)

    task_changes = task_sub.add_parser(
        "request-changes", help="send a task in review back to its producer"
    )
    task_changes.add_argument("task_id")
    task_changes.add_argument("--agent", required=True, help="the reviewer (not the submitter)")
    task_changes.add_argument("--reason", required=True)
    task_changes.set_defaults(func=cmd_task_request_changes)

    task_done = task_sub.add_parser("done", help="mark a task done and archive it")
    task_done.add_argument("task_id")
    task_done.add_argument("--agent", required=True)
    task_done.add_argument("--force", action="store_true")
    task_done.set_defaults(func=cmd_task_done)

    task_discard = task_sub.add_parser(
        "discard", help="permanently remove one unwanted task (interactive operator action)"
    )
    task_discard.add_argument("task_id")
    task_discard.set_defaults(func=cmd_task_discard)

    task_block = task_sub.add_parser("block", help="mark a task blocked")
    task_block.add_argument("task_id")
    task_block.add_argument("--agent", required=True)
    task_block.add_argument("--reason", required=True)
    task_block.set_defaults(func=cmd_task_block)

    task_unblock = task_sub.add_parser("unblock", help="return a blocked task to todo")
    task_unblock.add_argument("task_id")
    task_unblock.add_argument("--agent", required=True)
    task_unblock.set_defaults(func=cmd_task_unblock)
