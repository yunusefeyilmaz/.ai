"""git.repo: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import contextlib
import os
import re
import subprocess
import sys

from lib.core.paths import (
    BOARD_PATH,
    CONFIG_DIR,
    DECISIONS_DIR,
    LOCKS_DIR,
    PROJECT,
    SPECS_DIR,
    TASKS_DIR,
    WORKSPACE,
)
from lib.config.settings import (
    load_config,
    lock_settings,
)
from lib.core.fsio import (
    normalize_id,
    read_json,
    safe_name,
    slugify,
)
from lib.runtime.events import append_event
from lib.runtime.leases import (
    acquire_lock,
    list_locks,
    lock_is_stale,
    normalize_resource,
    resources_overlap,
)


_ROOT: list[str | None] = [None]  # active override of the git working directory


def current_root() -> str:
    """Directory git commands run in: the main project, or a task's worktree."""
    return _ROOT[0] or PROJECT


@contextlib.contextmanager
def working_in(path: str | None):
    """Run the enclosed git/check operations inside `path` (no-op when None)."""
    previous = _ROOT[0]
    _ROOT[0] = path or previous
    try:
        yield
    finally:
        _ROOT[0] = previous


def task_root(meta: dict) -> str | None:
    """Absolute path of the task's worktree when it has one and it exists."""
    rel = meta.get("worktree")
    if not rel:
        return None
    absolute = os.path.join(WORKSPACE, str(rel))
    return absolute if os.path.isdir(absolute) else None


def in_task(meta: dict):
    """Context manager: operate in the task's worktree if it has one."""
    return working_in(task_root(meta))


def run_git(
    args: list[str], cwd: str | None = None, input_text: str | None = None
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or current_root(),
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, ValueError):
        return 127, "", "git is not available"


def run_git_stdout(args: list[str]) -> str:
    """Git stdout without stripping: porcelain's first column is meaningful."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=current_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, ValueError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def git_state() -> dict:
    state = {"repo": False, "branch": None, "head": None, "dirty": [], "staged": [], "error": None}
    code, top, err = run_git(["rev-parse", "--show-toplevel"])
    if code != 0 or not top:
        state["error"] = err or None
        return state
    state["repo"] = True
    branch_code, branch, _ = run_git(["symbolic-ref", "--short", "HEAD"])
    if branch_code != 0 or not branch:
        _, branch, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    state["branch"] = branch if branch and branch != "HEAD" else "detached"
    head_code, head, _ = run_git([
        "rev-parse", "--verify", "--quiet", "HEAD^{commit}",
    ])
    state["head"] = head if head_code == 0 and re.fullmatch(r"[0-9a-fA-F]{40,64}", head) else None
    for line in run_git_stdout(["status", "--porcelain"]).splitlines():
        if len(line) < 3:
            continue
        code_part = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if not path:
            continue
        state["dirty"].append(path)
        if code_part[0] not in (" ", "?"):
            state["staged"].append(path)
    return state


COMMIT_TYPES = (
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert",
)


def git_config() -> dict:
    config = load_config().get("git", {}) or {}
    branch_types = config.get("branchTypes") or [
        "feature", "fix", "chore", "docs", "refactor", "hotfix",
    ]
    return {
        "integration": str(config.get("integrationBranch") or "develop"),
        "production": str(config.get("productionBranch") or "master"),
        "branchTypes": [str(item) for item in branch_types],
        "template": str(config.get("commitTemplate") or "templates/git/commit-template.txt"),
        "merge": str(config.get("merge") or "no-ff"),
        "isolation": "worktree" if config.get("isolation") == "worktree" else "branch",
        "deleteAfterMerge": bool(config.get("deleteAfterMerge", True)),
    }


def git_template_path() -> str:
    template = git_config()["template"].replace("\\", "/")
    if template.startswith(".ai/") and os.path.basename(WORKSPACE) == ".ai":
        template = template[4:]
    return os.path.join(WORKSPACE, template.replace("/", os.sep))


def branch_exists(name: str) -> bool:
    # A symbolic unborn branch is not a usable Gitflow base.
    return git_commit_id(f"refs/heads/{name}") is not None


def branch_ref_exists(name: str) -> bool:
    code, _, _ = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
    return code == 0


def git_commit_id(revision: str) -> str | None:
    code, commit, _ = run_git(["rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"])
    return commit if code == 0 and commit else None


def is_workspace_ledger_path(path: str) -> bool:
    """True for tasks/, specs/, config/ and decisions: coordination state, not product code."""
    try:
        absolute = os.path.realpath(os.path.join(PROJECT, path))
    except OSError:
        return False
    for folder in (TASKS_DIR, SPECS_DIR, CONFIG_DIR, DECISIONS_DIR):
        root = os.path.realpath(folder)
        try:
            if os.path.commonpath([absolute, root]) == root:
                return True
        except ValueError:
            continue
    return False


def git_clean(ignore_ledger: bool = False) -> bool:
    dirty = git_state().get("dirty") or []
    if ignore_ledger:
        dirty = [path for path in dirty if not is_workspace_ledger_path(path)]
    return not dirty


def task_branch_name(meta: dict, branch_type: str) -> str:
    slug = slugify(str(meta.get("title") or "task"))[:40].strip("-")
    return f"{branch_type}/{normalize_id(str(meta.get('id')))}-{slug or 'task'}"


def acquire_git_guard(agent: str, task_id: str) -> tuple[bool, bool, str]:
    _, stale_after = lock_settings()
    current = next(
        (
            lock for lock in list_locks()
            if str(lock.get("resource")) == "@git/index"
            and not lock_is_stale(lock, stale_after)
        ),
        None,
    )
    if current:
        if current.get("agent") != agent:
            append_event("lock_refused", resource="@git/index", agent=agent, task=task_id)
            return False, False, (
                f"git index is locked by {current.get('agent')} "
                f"(task {current.get('task') or '-'})."
            )
        return True, False, ""
    result = acquire_lock("@git/index", agent=agent, task=task_id, ttl=600)
    if not result["ok"]:
        holder = result["holder"] or {}
        append_event("lock_refused", resource="@git/index", agent=agent, task=task_id)
        return False, False, (
            f"git index is locked by {holder.get('agent')} "
            f"(task {holder.get('task') or '-'})."
        )
    return True, True, ""


def commit_task_metadata(task_path: str, message: str, amend: bool = False) -> str | None:
    paths = [task_path, BOARD_PATH]
    rels = [
        os.path.relpath(item, PROJECT).replace(os.sep, "/")
        for item in paths
        if os.path.exists(item)
    ]
    if not rels:
        return None
    code, _, _ = run_git(["add", "--"] + rels)
    if code != 0:
        return None
    if not git_state().get("staged"):
        return None
    args = ["commit", "--amend", "--no-edit"] if amend else ["commit", "-m", message]
    code, _, _ = run_git(args)
    if code != 0:
        return None
    _, short, _ = run_git(["rev-parse", "--short", "HEAD"])
    return short


def release_git_guard(owned: bool, agent: str) -> None:
    if not owned:
        return
    path = os.path.join(LOCKS_DIR, safe_name(normalize_resource("@git/index")) + ".lock")
    holder = read_json(path) or {}
    if holder.get("agent") == agent:
        try:
            os.remove(path)
        except OSError:
            pass


def uncovered_staged(state: dict) -> tuple[list[str], list[dict]]:
    locks = [
        lock for lock in list_locks()
        if not lock_is_stale(lock, lock_settings()[1])
        and str(lock.get("resource")) not in ("@git/index", "tasks.index")
        and not str(lock.get("resource")).startswith("task-")
    ]
    uncovered = []
    for path in state.get("staged", []):
        covered = False
        for lock in locks:
            try:
                if resources_overlap(path, lock.get("resource", "")):
                    covered = True
                    break
            except ValueError:
                continue
        if not covered:
            uncovered.append(path)
    return uncovered, locks


def confirm_initial_baseline(args, production: str) -> tuple[bool, int]:
    code, listed, err = run_git(["ls-files", "--cached", "--others", "--exclude-standard"])
    if code != 0:
        print(f"Could not list files for the initial Git baseline: {err}", file=sys.stderr)
        return False, 1
    files = [line for line in listed.splitlines() if line]
    if args.json:
        print(json.dumps({
            "repo": True,
            "baselineConfirmationRequired": True,
            "production": production,
            "files": files,
        }, indent=2))
        return False, 2
    if not sys.stdin.isatty():
        print(
            "Initial Git baseline requires interactive confirmation. Rerun `ai git setup` "
            "in a terminal to review the file list and confirm.",
            file=sys.stderr,
        )
        return False, 1
    print("Gitflow needs an initial production commit so task branches can start cleanly.")
    print("The following non-ignored project files will be included:")
    for path in files:
        print(f"  {path}")
    if not files:
        print("  (no files; an empty baseline commit will be created)")
    expected = "commit project baseline"
    try:
        confirmation = input(f"Type '{expected}' to continue: ").strip()
    except EOFError:
        confirmation = ""
    if confirmation != expected:
        print("Confirmation did not match; no project files were staged or committed.", file=sys.stderr)
        return False, 1
    code, _, err = run_git(["add", "-A"])
    if code != 0:
        print(f"Could not stage the initial project baseline: {err}", file=sys.stderr)
        return False, 1
    code, _, err = run_git(["commit", "--allow-empty", "-m", "chore: initialize repository"])
    if code != 0:
        print(
            "Could not create the initial baseline commit. Configure Git author "
            f"identity if needed, then rerun setup: {err}", file=sys.stderr,
        )
        return False, 1
    return True, 0
