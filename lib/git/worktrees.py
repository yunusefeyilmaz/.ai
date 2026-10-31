"""git.worktrees: one isolated checkout per task, managed by the workspace.

Why: two workers cannot share one working directory, because a branch switch
changes every file under both of them. With `git.isolation = worktree` each
claimed task gets `<workspace>/worktrees/<branch>/`, a real checkout on the
task's own branch. Everything coordinating the work (tasks, locks, runtime,
config) stays in the single main workspace; only product files differ.

    main checkout            <project>/            develop, ledger, `.ai/`
    task worktree            <workspace>/worktrees/feature-0001-login/

The workspace folder is git-ignored in host projects (`ai adopt`), and the
worktrees folder is additionally written to `info/exclude`, so the main
checkout's `git status` never sees them.
"""

from __future__ import annotations

import os
import sys

from lib.core.fsio import write_text_atomic
from lib.core.paths import PROJECT, WORKSPACE, WORKTREES_DIR
from lib.git import repo

BRIEFING_FILES = ("AGENTS.md", "CLAUDE.md")


def worktree_name(branch: str) -> str:
    return branch.replace("/", "-").replace("\\", "-")


def relative(path: str) -> str:
    return os.path.relpath(path, WORKSPACE).replace(os.sep, "/")


def cli_command() -> str:
    """Absolute command a worker inside a worktree uses to reach the main workspace."""
    python = "python" if os.name == "nt" else "python3"
    return f'{python} "{os.path.join(WORKSPACE, "ai.py")}"'


def ensure_excluded(root: str) -> None:
    """Keep worktrees (and the briefing files) out of every checkout's status."""
    code, exclude, _ = repo.run_git(["rev-parse", "--git-path", "info/exclude"], cwd=root)
    if code != 0 or not exclude:
        return
    exclude = exclude if os.path.isabs(exclude) else os.path.join(root, exclude)
    wanted = []
    prefix = os.path.relpath(WORKTREES_DIR, PROJECT).replace(os.sep, "/")
    if not prefix.startswith(".."):
        wanted.append("/" + prefix + "/")
    wanted += ["/" + name for name in BRIEFING_FILES]
    try:
        existing = open(exclude, encoding="utf-8").read() if os.path.exists(exclude) else ""
        missing = [line for line in wanted if line not in existing.splitlines()]
        if missing:
            os.makedirs(os.path.dirname(exclude), exist_ok=True)
            with open(exclude, "a", encoding="utf-8", newline="\n") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write("# ai workspace: task worktrees are local\n" + "\n".join(missing) + "\n")
    except OSError:
        pass


def briefing(meta: dict, branch: str) -> str:
    cli = cli_command()
    return f"""# Task worktree (managed by the .ai workspace)

You are inside an isolated checkout for task {meta.get('id')} ({meta.get('title')}),
branch `{branch}`. Edit product files **only here**; never touch the main checkout.

The coordination state (tasks, locks, runtime, config) lives in the main
workspace. Run its CLI by absolute path from this directory:

    {cli} now --agent <name>
    {cli} task show {meta.get('id')}
    {cli} git commit --task {meta.get('id')} --agent <name> --type feat --message "<subject>"
    {cli} task review {meta.get('id')} --agent <name>

Read the workspace rules in `{os.path.join(WORKSPACE, 'AGENTS.md')}`.
"""


def create(meta: dict, branch: str, base: str) -> tuple[bool, str, str]:
    """Create (or reuse) the task's worktree. Returns (ok, path, message)."""
    path = os.path.join(WORKTREES_DIR, worktree_name(branch))
    if os.path.isdir(path):
        return True, path, "reused"
    os.makedirs(WORKTREES_DIR, exist_ok=True)
    main = PROJECT
    ensure_excluded(main)
    if repo.branch_exists(branch):
        args = ["worktree", "add", path, branch]
    else:
        args = ["worktree", "add", "-b", branch, path, base]
    code, _, err = repo.run_git(args, cwd=main)
    if code != 0:
        return False, path, err or "git worktree add failed"
    for name in BRIEFING_FILES:
        target = os.path.join(path, name)
        if not os.path.exists(target):  # a tracked AGENTS.md already tells the host's rules
            write_text_atomic(target, briefing(meta, branch))
    return True, path, "created"


def remove(path: str, force: bool = False) -> tuple[bool, str]:
    args = ["worktree", "remove"] + (["--force"] if force else []) + [path]
    code, _, err = repo.run_git(args, cwd=PROJECT)
    if code != 0 and os.path.isdir(path):
        return False, err or "git worktree remove failed"
    repo.run_git(["worktree", "prune"], cwd=PROJECT)
    return True, ""


def listing(tasks: list[dict]) -> list[dict]:
    """Every folder under worktrees/, with the task that owns it (if any)."""
    rows = []
    if not os.path.isdir(WORKTREES_DIR):
        return rows
    by_path = {str(t.get("worktree")): t for t in tasks if t.get("worktree")}
    for name in sorted(os.listdir(WORKTREES_DIR)):
        full = os.path.join(WORKTREES_DIR, name)
        if not os.path.isdir(full):
            continue
        rel = relative(full)
        task = by_path.get(rel)
        _, branch, _ = repo.run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=full)
        _, dirty, _ = repo.run_git(["status", "--porcelain"], cwd=full)
        rows.append({
            "path": full, "name": name, "branch": branch or None,
            "task": task.get("id") if task else None,
            "status": task.get("status") if task and task["_folder"] == "active" else (
                "done" if task else None),
            "owner": task.get("owner") if task else None,
            "dirty": len([line for line in dirty.splitlines() if line.strip()]),
            "orphan": not task or task["_folder"] != "active",
        })
    return rows
