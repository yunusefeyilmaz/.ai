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
    CorruptStateError,
    lock_path,
    normalize_id,
    read_json,
    slugify,
)
from lib.runtime.events import append_event
from lib.runtime.mutex import registry_mutex
from lib.runtime.leases import (
    acquire_lock,
    heartbeat_lock,
    list_locks,
    lock_is_stale,
    normalize_resource,
    resources_overlap,
)


_ROOT: list[str | None] = [None]  # active override of the git working directory
_GIT_TIMEOUT = 300  # seconds; a credential/hook prompt must not hang the CLI forever
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


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


def commits_ahead(base: str) -> int | None:
    """Commits on the current branch that `base` does not have (None if unknown)."""
    code, out, _ = run_git(["rev-list", "--count", f"{base}..HEAD"])
    return int(out) if code == 0 and out.strip().isdigit() else None


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
            timeout=_GIT_TIMEOUT,
            creationflags=_CREATE_NO_WINDOW,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"git {args[0] if args else ''} timed out after {_GIT_TIMEOUT}s"
    except (OSError, ValueError):
        return 127, "", "git is not available"


def run_git_stdout(args: list[str]) -> str:
    """Git stdout without stripping: NUL-separated porcelain is path-safe."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=current_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def parse_porcelain_z(output: str) -> list[tuple[str, str]]:
    """Parse `git status --porcelain -z` into (status, path) records.

    In -z form a rename/copy record is two NUL-separated tokens: the new path
    followed by the old path. Consuming both keeps the old path from being
    read as its own entry (which used to slice three characters off it and
    report a phantom dirty file, making clean-tree checks unreliable).
    """
    tokens = output.split("\0")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 3:
            continue
        status, path = entry[:2], entry[3:]
        if not path:
            continue
        if "R" in status or "C" in status:
            index += 1  # the old path belongs to this record
        entries.append((status, path))
    return entries


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
    for code_part, path in parse_porcelain_z(run_git_stdout(["status", "--porcelain", "-z"])):
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


def acquire_git_guard(agent: str, task_id: str, ttl: int = 600) -> tuple[bool, bool, str]:
    """Take the git index for one orchestrating step.

    `ttl` must cover the longest child command run while the guard is held
    (e.g. a project check), or the lease expires mid-step and another agent can
    interleave a commit between the check and the merge.
    """
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
    result = acquire_lock("@git/index", agent=agent, task=task_id, ttl=ttl)
    if not result["ok"]:
        holder = result["holder"] or {}
        append_event("lock_refused", resource="@git/index", agent=agent, task=task_id)
        return False, False, (
            f"git index is locked by {holder.get('agent')} "
            f"(task {holder.get('task') or '-'})."
        )
    return True, True, ""


def heartbeat_git_guard(agent: str) -> bool:
    """Prove the index lease is still ours after a long child command."""
    return heartbeat_lock("@git/index", agent=agent, quiet=True) == 0


def ledger_path(path: str) -> str:
    """A git-comparable form of `path`: git reports `/`, Windows builds report `\\`."""
    return str(path).replace("\\", "/")


def unexpected_staged(rels: list[str], staged: list[str]) -> list[str]:
    """Staged paths the metadata commit does not own.

    `commit_task_metadata` may only amend the task file and the board. Anything
    else in the index belongs to the user's own work and must never be folded
    into a previous commit.
    """
    expected = {ledger_path(item) for item in rels}
    return sorted({ledger_path(item) for item in staged} - expected)


def commit_task_metadata(task_path: str, message: str, amend: bool = False) -> str | None:
    """Record the task/board metadata in git; returns the short hash or None.

    "None" used to swallow every failure - a locked index, a hook that rejected
    the commit - which left the task ledger silently out of sync with git. Every
    failure now names itself on stderr and lands in the event log; only a
    "nothing to commit" case is silent.

    The amend path is deliberately narrow: it runs only when the staged paths are
    exactly the task file and the board. A path the user staged earlier would
    otherwise be swallowed by `git commit --amend`.
    """
    paths = [task_path, BOARD_PATH]
    rels = [
        ledger_path(os.path.relpath(item, PROJECT))
        for item in paths
        if os.path.exists(item)
    ]
    if not rels:
        return None
    code, _, err = run_git(["add", "--"] + rels)
    if code != 0:
        _metadata_failure("git add", err)
        return None
    staged = [ledger_path(item) for item in (git_state().get("staged") or [])]
    owned = [path for path in rels if path in staged]
    if not owned:
        return None
    if amend:
        unexpected = unexpected_staged(rels, staged)
        if unexpected:
            listed = ", ".join(unexpected[:5]) + (" ..." if len(unexpected) > 5 else "")
            print(
                f"WARN  task metadata was not amended: unrelated staged paths ({listed}) "
                "stay staged and out of the commit. Unstage them (`git restore --staged "
                "<path>`) or commit them, then re-run the command.",
                file=sys.stderr,
            )
            try:
                append_event("git_metadata_amend_skipped", paths=unexpected)
            except Exception:  # the ledger must never mask the original result
                pass
            return None
        args = ["commit", "--amend", "--no-edit"]
    else:
        # Pathspec commit: record only the ledger paths and leave anything else
        # the user staged untouched.
        args = ["commit", "-m", message, "--"] + owned
    code, _, err = run_git(args)
    if code != 0:
        _metadata_failure("git commit", err)
        return None
    _, short, _ = run_git(["rev-parse", "--short", "HEAD"])
    return short or None


def _metadata_failure(step: str, error: str) -> None:
    detail = (error or "").strip().splitlines()
    summary = detail[-1] if detail else "unknown error"
    print(f"WARN  task metadata was not committed ({step}): {summary}", file=sys.stderr)
    try:
        append_event("git_metadata_failed", step=step, error=summary)
    except Exception:  # the ledger must never mask the original failure
        pass


def release_git_guard(owned: bool, agent: str) -> None:
    if not owned:
        return
    path = lock_path(normalize_resource("@git/index"))
    try:
        with registry_mutex():
            # Re-read inside the mutex: the lease may have expired and been
            # taken by another agent between the check and the delete.
            try:
                holder = read_json(path) or {}
            except CorruptStateError:
                # We cannot prove ownership of a damaged lease, so keep it: the
                # next holder expires it and `ai doctor` reports it.
                return
            if holder.get("agent") == agent:
                try:
                    os.remove(path)
                except OSError:
                    pass
    except TimeoutError:
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
        # Coordination state (tasks/specs/config/decisions) is committed by the
        # CLI itself and is not product code; it never needs a file lease.
        if is_workspace_ledger_path(path):
            continue
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


SENSITIVE = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx)|id_(rsa|dsa|ecdsa|ed25519)|credentials(\..*)?|secrets?(\..*)?)$",
    re.IGNORECASE,
)


def confirm_initial_baseline(
    production: str, assume_yes: bool = False, json_out: bool = False
) -> tuple[bool, int]:
    code, listed, err = run_git(["ls-files", "--cached", "--others", "--exclude-standard"])
    if code != 0:
        print(f"Could not list files for the initial Git baseline: {err}", file=sys.stderr)
        return False, 1
    files = [line for line in listed.splitlines() if line]
    if assume_yes:
        # The user already agreed to Git during `ai setup`; an agent cannot type the phrase.
        risky = [path for path in files if SENSITIVE.search(path)]
        if risky:
            print(
                "Refusing --yes: the baseline would commit files that look like secrets: "
                + ", ".join(risky[:8])
                + ". Add them to .gitignore (or review in a terminal without --yes).",
                file=sys.stderr,
            )
            return False, 1
        print(f"Committing the initial baseline ({len(files)} file(s), confirmed with --yes):")
        for path in files[:30]:
            print(f"  {path}")
        if len(files) > 30:
            print(f"  ... and {len(files) - 30} more")
    elif json_out:
        print(json.dumps({
            "repo": True,
            "baselineConfirmationRequired": True,
            "production": production,
            "files": files,
        }, indent=2))
        return False, 2
    if not assume_yes and not sys.stdin.isatty():
        print(
            "Initial Git baseline needs the user's confirmation and no terminal is attached. "
            "If the user already agreed to Git (ai setup), run `ai git setup --yes`; it lists "
            "the files and refuses secrets. Otherwise run `ai git setup` in a terminal.",
            file=sys.stderr,
        )
        return False, 1
    if not assume_yes:
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
