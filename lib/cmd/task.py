"""cmd.task: split out of the former monolithic ai.py."""

from __future__ import annotations

import contextlib
import json
import os
import sys

from lib.config import roles, settings
from lib.config.settings import lock_settings
from lib.core.fsio import (
    CorruptStateError,
    lock_path,
    normalize_id,
    read_json,
    read_text,
)
from lib.core.paths import (
    ACTIVE_DIR,
    BOARD_PATH,
    DONE_DIR,
    PROJECT,
    WORKSPACE,
)
from lib.core.timeutil import iso
from lib.git import flow, repo, worktrees
from lib.runtime import checkpoints as ckpt
from lib.runtime import evidence, health
from lib.runtime.events import append_event
from lib.runtime.leases import (
    acquire_lock,
    effective_holder,
    list_locks,
    lock_is_stale,
    release_lock,
    resources_overlap,
)
from lib.runtime.mutex import (
    registry_mutex,
    workspace_state_guard,
)
from lib.specs import spec as spec_lib
from lib.tasks import board, discard, gates, history, lifecycle, links, scope, store, transition


def cmd_task_new(args) -> int:
    blocked = gates.creation_gate(getattr(args, "role", None))
    if blocked:
        print(blocked, file=sys.stderr)
        return 1
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
            locks=scope.join_globs(getattr(args, "lock", None)),
            actor=getattr(args, "agent", None),
        )
    except RuntimeError as exc:
        print(f"Cannot create the task: {exc}.", file=sys.stderr)
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
    shown = active + done if args.all else active
    for line in board.text_table(
        [("ID", 6), ("FOLDER", 8), ("STATUS", 12), ("OWNER", 18), ("TITLE", 0)],
        [[task.get("id"), task["_folder"], task.get("status"), task.get("owner"), task.get("title")]
         for task in shown],
    ):
        print(line)
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
    _print_spec_criteria(meta)
    return 0


def _print_spec_criteria(meta: dict) -> None:
    """Show the linked spec's criteria, so the task body need not duplicate them."""
    path = spec_lib.resolve_spec_path(meta)
    if not path:
        return
    try:
        text = read_text(path)
    except OSError:
        return
    criteria = spec_lib.acceptance_criteria(text)
    if not criteria:
        return
    done, total = spec_lib.criteria_progress(criteria)
    print()
    print(f"Acceptance criteria (from {meta.get('spec')}; {done}/{total} done)")
    for is_done, item in criteria:
        print(f"  [{'x' if is_done else ' '}] {item}")


def claim_task(path: str, agent: str, force: bool = False) -> tuple[bool, str]:
    """Public one-command claim, shared with `ai start` (no fabricated args)."""
    return _claim(path, agent, force)


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
    (all or nothing), and the task branch when Git is enabled. The claim is
    atomic: if the branch cannot start, the task and its locks are released
    again so the next agent is not stuck behind a half-claim.
    """
    meta, _ = store.parse_task(path)
    previous_status = meta.get("status")
    held_ok, held = lifecycle.acquire_task_locks(meta, agent) if previous_status != "review" else (True, "")
    if not held_ok:
        return False, held
    ok, message = lifecycle.claim_task(path, agent, force)
    if not ok:
        if previous_status != "review":
            lifecycle.release_task_locks(meta, agent)
        return False, message
    if previous_status != "review" and settings.git_enabled():
        state = repo.git_state()
        integration = repo.git_config()["integration"]
        if not state.get("repo") or not state.get("head"):
            print("  git: not initialized; run `ai git setup` once (or `ai setup --set git=no`).")
        elif not repo.branch_exists(integration):
            print(
                f"  git: integration branch '{integration}' is missing; run `ai git setup` once, "
                "then `ai git start` for this task."
            )
        else:
            try:
                started = flow.start_branch(message, agent)
            except Exception as exc:  # noqa: BLE001 - a failed branch must roll the claim back
                print(f"  git: starting the task branch raised: {exc}", file=sys.stderr)
                started = 1
            if started != 0:
                rolled_back = lifecycle.rollback_claim(
                    path, agent, previous_status, "the task branch could not start"
                )
                if rolled_back is None:
                    return False, (
                        f"Task {message} changed while its branch was starting; "
                        "inspect it with `ai task show " + str(message) + "`."
                    )
                return False, (
                    f"Claim of {message} was rolled back: the task branch could not start. "
                    "The task is unowned again and its file locks were released; fix the Git "
                    f"problem, then reclaim with `ai task claim {message} --agent {agent}`."
                )
    print(f"Claimed {message} for {agent}.")
    if held:
        print(f"  file locks: {held}")
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
        for line in board.text_table(
            [("ID", 6), ("PRIORITY", 10), ("SPEC", 28), ("TITLE", 0)],
            [[task.get("id"), task.get("priority"), task.get("spec"), task.get("title")]
             for task in ready],
        ):
            print(line)
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
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            ok, message = _claim(task["_path"], args.agent)
        if not ok:
            print(f"Skipped {task.get('id')}: {message}", file=sys.stderr)
            continue
        claimed_path = store.find_task(message)
        if not claimed_path:
            print(f"Claimed {message}, but its task file disappeared.", file=sys.stderr)
            return 1
        meta, _ = store.parse_task(claimed_path)
        if args.json:
            print(json.dumps({"meta": meta}, indent=2, default=str))
            return 0
        print(f"Review: {meta.get('title')} (submitted by {meta.get('submitted_by')})")
        if meta.get("spec"):
            print(f"Spec: {meta.get('spec')}")
        print(f"History: ai history {message}")
        print(f"Approve:  {_approve_steps(message, args.agent)}")
        print(f"Reject:   ai task request-changes {message} --agent {args.agent} --reason \"...\"")
        return 0
    print("Nothing is waiting for review.", file=sys.stderr)
    return 1


def cmd_task_next(args) -> int:
    if getattr(args, "review", False):
        return _next_review(args)
    ready, waiting = lifecycle.ready_and_waiting()
    for task in ready:
        # in --json mode all human text goes to stderr so stdout stays one JSON document
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            ok, message = _claim(task["_path"], args.agent)
        if not ok:
            print(f"Skipped {task.get('id')}: {message}", file=sys.stderr)
            continue
        claimed_path = store.find_task(message)
        if not claimed_path:
            print(f"Claimed {message}, but its task file disappeared.", file=sys.stderr)
            return 1
        meta, body = store.parse_task(claimed_path)
        if args.json:
            payload: dict = {"meta": meta, "body": body}
            if meta.get("worktree"):
                payload["worktree"] = meta.get("worktree")
                payload["cli"] = worktrees.cli_command()
            print(json.dumps(payload, indent=2, default=str))
            return 0
        print(f"Task: {meta.get('title')}")
        if meta.get("spec"):
            print(f"Spec: {meta.get('spec')}")
        if meta.get("worktree"):
            print(f"Worktree: {meta.get('worktree')} (cd there; run the CLI by absolute path)")
            print(f"CLI: {worktrees.cli_command()}")
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
            if (
                not meta.get("owner")
                and meta.get("status") == "review"
                and meta.get("submitted_by") == args.agent
            ):
                print(f"Task {task_id} was already handed over by `ai task review`; nothing to release.")
                return 0
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
    with repo.in_task(meta):  # verify the task's own checkout
        head = repo.git_state().get("head")
        if evidence.task_green(task_id, head, gates.claim_started(task_id))[0]:
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


def _approve_steps(task_id: str, who: str) -> str:
    if settings.git_enabled():
        return f"ai git finish --task {task_id} --agent {who}, then ai task done {task_id} --agent {who}"
    return f"ai task done {task_id} --agent {who}   (Git is off: nothing to merge)"


def cmd_task_review(args) -> int:
    path = store.find_task(args.task_id)
    if not path or os.path.dirname(path) != ACTIVE_DIR:
        print(f"No active task with id {args.task_id}.", file=sys.stderr)
        return 1
    current_meta, _ = store.parse_task(path)
    git_error = gates.review_git_gate(current_meta, args.agent, include_evidence=False)
    if git_error:
        print(git_error, file=sys.stderr)
        return 1
    auto_error = _auto_verify(path, args.agent)
    if auto_error:
        print(auto_error, file=sys.stderr)
        return 1
    def mutate(meta, body):
        task_id = str(meta.get("id"))
        if meta.get("status") != "in_progress":
            raise transition.Refused(f"Task {task_id} must be in_progress to enter review.")
        if meta.get("owner") != args.agent:
            raise transition.Refused(f"Task {task_id} is not owned by {args.agent}.")
        try:
            holder = read_json(lock_path(f"task-{task_id}")) or {}
        except CorruptStateError:
            holder = {}
        if holder.get("agent") != args.agent:
            raise transition.Refused(f"Task {task_id} does not have a live claim for {args.agent}.")
        checkpoint_error = ckpt.checkpoint_required(
            task_id,
            gates.claim_started(task_id),
            settings.preference("handoff.warnAfterMinutes", 30),
        )
        if checkpoint_error:
            raise transition.Refused(checkpoint_error)
        denied = roles.authorize(args.agent, "task.review")
        if denied:
            raise transition.Refused(denied)
        if gates.workflow_config()["requireSpec"]:
            unticked = spec_lib.spec_unticked(meta)
            if unticked:
                listed = "; ".join(f"{number}. {text}" for number, text in unticked)
                raise transition.Refused(
                    f"Task {task_id} cannot enter review: {len(unticked)} acceptance "
                    f"criteria are still unticked in {meta.get('spec')}: {listed}. Tick each one "
                    f"with `ai spec check {task_id} <n>` once the work makes it true."
                )
        gate_error, proof = gates.review_gate(meta, args.agent)
        if gate_error:
            raise transition.Refused(gate_error)
        git_gate_error = gates.review_git_gate(meta, args.agent)
        if git_gate_error:
            raise transition.Refused(git_gate_error)
        meta["status"] = "review"
        meta["submitted_by"] = args.agent
        meta["owner"] = None   # delivery hands the task over: no separate release step
        meta["lock"] = None
        return history.append(
            body, args.agent, "in_progress", "review", "submitted for independent review", proof
        )

    try:
        meta = transition.apply(args.task_id, path, mutate, active_only=True)
    except transition.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except transition.GuardError as exc:
        print(f"Cannot submit task {args.task_id} for review: {exc}.", file=sys.stderr)
        return 1
    task_id = str(meta.get("id"))
    append_event("task_reviewed", task=task_id, agent=args.agent)
    lifecycle.release_task_locks(meta, args.agent)
    release_lock(f"task-{task_id}", agent=args.agent, quiet=True)
    print(f"Task {task_id} is delivered for independent review and handed over.")
    print(f"Reviewer next: {_approve_steps(task_id, '<reviewer>')}")
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
    def mutate(meta, body):
        gate_error = gates.request_changes_gate(meta, args.agent)
        if gate_error:
            raise transition.Refused(gate_error)
        meta["status"] = "changes_requested"
        meta["changes_requested_by"] = args.agent
        meta["owner"] = None
        meta["lock"] = None
        return history.append(body, args.agent, "review", "changes_requested", args.reason)

    try:
        meta = transition.apply(args.task_id, path, mutate, active_only=True)
    except transition.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except transition.GuardError as exc:
        print(f"Cannot request changes on task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    task_id = str(meta.get("id"))
    release_lock(f"task-{task_id}", force=True)
    evidence.invalidate(task_id, f"changes requested by {args.agent}")
    append_event("task_changes_requested", task=task_id, agent=args.agent)
    print(f"Task {task_id} sent back to its producer ({meta.get('submitted_by')}): {args.reason}")
    print(f"Producer next: ai task claim {task_id} --agent <producer>")
    return 0


def cmd_task_block(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = store.parse_task(path)
    owner = meta.get("owner")
    if owner and owner != args.agent:
        print(
            f"Task {args.task_id} is owned by {owner}; only the owner (or the chief) may block it.",
            file=sys.stderr,
        )
        return 1
    task_id = str(meta.get("id"))

    def mutate(current, body):
        previous = current.get("status")
        if previous == "blocked":
            raise transition.Skip(f"Task {task_id} is already blocked.")
        current["blocked_from"] = previous
        current["status"] = "blocked"
        if previous == "in_progress":
            # A blocked worker no longer holds the task: release ownership
            # and its claim lease so it is not reported as "leased by X".
            current["owner"] = None
            current["lock"] = None
        return history.append(body, args.agent, previous, "blocked", args.reason)

    try:
        meta = transition.apply(args.task_id, path, mutate)
    except transition.Skip as exc:
        print(str(exc))
        return 0
    except transition.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except transition.GuardError as exc:
        print(f"Cannot block task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    if meta.get("blocked_from") == "in_progress":
        release_lock(f"task-{task_id}", force=True)
    print(f"Blocked {meta.get('id')}: {args.reason}")
    return 0


def cmd_task_unblock(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    def mutate(meta, body):
        previous = meta.get("status")
        if previous != "blocked":
            raise transition.Refused(
                f"Task {args.task_id} is {previous or 'unknown'}, not blocked."
            )
        restore = meta.get("blocked_from")
        if restore not in ("review", "changes_requested"):
            # in_progress is deliberately not restored: the worker that was
            # interrupted must reclaim the task and its lease explicitly.
            restore = "todo"
        meta["status"] = restore
        meta.pop("blocked_from", None)
        if restore == "todo":
            meta["owner"] = None
            meta["lock"] = None
        return history.append(body, args.agent, previous, restore, "unblocked")

    try:
        meta = transition.apply(args.task_id, path, mutate)
    except transition.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except transition.GuardError as exc:
        print(f"Cannot unblock task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Unblocked {meta.get('id')} to {meta.get('status')}.")
    return 0


def _commit_done_ledger(
    target_path: str,
    previous_task_path: str,
    meta: dict,
    previous_spec: str | None,
    agent: str,
) -> None:
    """Record the archived task, shipped spec and board on the current branch.

    `done` is the last ledger write in a task's life; leaving it uncommitted
    hands the next agent a dirty tree. Only coordination paths are staged, so
    product work the user has in flight stays untouched.
    """
    if not settings.git_enabled() or not repo.git_state().get("repo"):
        return
    candidates = [target_path, previous_task_path, BOARD_PATH]
    archived_spec = meta.get("spec")
    if archived_spec and archived_spec != previous_spec:
        candidates.append(os.path.join(WORKSPACE, str(archived_spec).replace("/", os.sep)))
        if previous_spec:
            candidates.append(os.path.join(WORKSPACE, str(previous_spec).replace("/", os.sep)))
    rels: list[str] = []
    for item in candidates:
        rel = repo.ledger_path(os.path.relpath(item, PROJECT))
        if rel in rels or not repo.is_workspace_ledger_path(rel):
            continue
        if not os.path.exists(os.path.join(PROJECT, rel)):
            # A moved file no longer exists; stage its deletion only when git
            # already tracks it (an untracked file leaves nothing to record).
            code, _, _ = repo.run_git(["ls-files", "--error-unmatch", "--", rel])
            if code != 0:
                continue
        rels.append(rel)
    if not rels:
        return
    code, _, err = repo.run_git(["add", "--"] + rels)
    if code != 0:
        print(f"WARN  could not stage the task ledger: {err}", file=sys.stderr)
        return
    # Commit by pathspec so staged product work never joins the ledger commit.
    # The explicit list also records the old paths a move deleted, which git
    # reports as renames rather than as separate staged deletions.
    code, _, _ = repo.run_git(["diff", "--cached", "--quiet", "--"] + rels)
    if code == 0:
        return
    task_id = meta.get("id")
    code, _, err = repo.run_git(
        ["commit", "-m", f"chore(task): record done {task_id}", "--"] + rels
    )
    if code != 0:
        print(
            f"WARN  task {task_id} was archived but its ledger was not committed: {err}. "
            "Commit tasks/, specs/ and tasks/BOARD.md manually.",
            file=sys.stderr,
        )


def cmd_task_done(args) -> int:
    path = store.find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) == DONE_DIR:
        print("Task is already done.")
        return 0
    meta, _ = store.parse_task(path)
    task_id = str(meta.get("id"))
    previous_spec = meta.get("spec")
    denied = None if args.force else roles.authorize(args.agent, "task.done")
    if denied:
        print(denied, file=sys.stderr)
        return 1
    gate_error = gates.done_gate(meta, args.agent, args.force)
    if gate_error:
        print(gate_error, file=sys.stderr)
        return 1
    resource = f"task-{task_id}"
    holder = effective_holder(resource)
    if holder.get("corrupt") and not args.force:
        append_event("lock_refused", resource=resource, agent=args.agent, task=task_id)
        print(
            f"Task {task_id} has a corrupt task lock ({resource}), which cannot prove the task "
            f"is free. Inspect it, then repair it with `ai lock release {resource} --force`.",
            file=sys.stderr,
        )
        return 1
    if not holder or holder.get("agent") != args.agent:
        # Free, stale (a crashed reviewer) or held by someone else: `acquire_lock`
        # takes over a stale lease - recording `lock_replaced_stale` - and refuses
        # a live one, so a finished task can never stay stuck in review.
        result = acquire_lock(resource, agent=args.agent, task=task_id, force=args.force)
        if not result["ok"]:
            append_event("lock_refused", resource=resource, agent=args.agent, task=task_id)
            print(f"Task {task_id} is locked by {result['holder'].get('agent')}.", file=sys.stderr)
            return 1
    target = os.path.join(DONE_DIR, os.path.basename(path))
    if os.path.exists(target):
        print(
            f"Cannot archive task {task_id}: {os.path.relpath(target, PROJECT)} already exists. "
            "Rename one of the files, then rerun.",
            file=sys.stderr,
        )
        return 1

    def mutate(current, body):
        if (
            gates.workflow_config()["requireReview"]
            and current.get("status") not in ("review", "done")
            and not args.force
        ):
            raise transition.Refused(f"Task {task_id} is no longer in review; retry.")
        previous = current.get("status")
        current["status"] = "done"
        current["reviewed_by"] = args.agent
        current["reviewed_at"] = iso()
        current["lock"] = None
        forced = (
            "forced: review gate bypassed"
            if args.force and current.get("submitted_by") in (None, args.agent)
            else "approved"
        )
        records = evidence.task_records(task_id)
        proof = evidence.summary(records[-1]) if records else ""
        # Archive the spec first so the written task points at specs/done.
        archived_spec = spec_lib.archive_spec(current)
        if archived_spec:
            current["spec"] = archived_spec
        return history.append(body, args.agent, previous, "done", forced, proof)

    def finalize(current):
        # Move the archived task inside the same guard as the write, so a
        # failure leaves the active file readable and retryable.
        os.replace(path, target)

    try:
        meta = transition.apply(task_id, path, mutate, finalize=finalize)
    except transition.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except transition.GuardError as exc:
        print(f"Cannot archive task {task_id}: {exc}.", file=sys.stderr)
        return 1
    release_lock(resource, force=True)
    lifecycle.release_task_locks(meta, None)
    marker = ckpt.handoff_marker(task_id)
    if os.path.exists(marker):
        try:
            os.remove(marker)
        except OSError:
            pass
    _commit_done_ledger(target, path, meta, previous_spec, args.agent)
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
    try:
        task_id = normalize_id(str(meta.get("id") or args.task_id))
    except ValueError:
        print(f"Task file has an invalid id: {meta.get('id')!r}.", file=sys.stderr)
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
    # Ask for the terminal only once the discard can actually happen: a held
    # task must report the holder, not a generic "needs a terminal".
    if not sys.stdin.isatty():
        print("Discard requires an interactive terminal; no files were changed.", file=sys.stderr)
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
    task_new.add_argument("--lock", action="append", default=None, metavar="GLOB",
                          help="paths locked when the task is claimed (default: the --allow paths)")
    task_new.add_argument("--agent", default=None, help="who creates the task (checked against roles)")
    task_new.add_argument("--role", default=None, choices=["chief", "orchestrator", "planner"],
                          help="only the chief creates tasks (see `ai setup`, `ai plan`)")
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
