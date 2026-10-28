#!/usr/bin/env python3
"""Local, cross-platform CLI for the .ai engineering workspace.

Stdlib only. Invoked through `scripts/ai` (POSIX) or `scripts/ai.cmd`
(Windows), which auto-detect a Python 3 interpreter. The file protocol is
the contract; this CLI is the fast, race-safe path through it.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

VERSION = "0.3.2"
HOST = socket.gethostname()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SCRIPT_DIR)
PROJECT = os.path.dirname(WORKSPACE) if os.path.basename(WORKSPACE) == ".ai" else WORKSPACE

REQUIRED_PATHS = [
    "AGENTS.md",
    "README.md",
    "GUIDE.md",
    "config/workspace.json",
    "docs/architecture.md",
    "docs/git-workflow.md",
    "docs/task-flow.md",
    "docs/multi-agent.md",
    "docs/artifact-hygiene.md",
    "docs/recovery.md",
    "docs/orchestration.md",
    "agents/README.md",
    "tasks/README.md",
    "tasks/TEMPLATE.md",
    "specs/README.md",
    "scripts/ai.py",
    "templates/git/commit-template.txt",
    "templates/git/pull-request.md",
    "runtime",
]

TASK_STATUSES = {"todo", "in_progress", "review", "blocked", "done"}
ACTIVE_DIR = os.path.join(WORKSPACE, "tasks", "active")
DONE_DIR = os.path.join(WORKSPACE, "tasks", "done")
LOCKS_DIR = os.path.join(WORKSPACE, "runtime", "locks")
STATE_DIR = os.path.join(WORKSPACE, "runtime", "state")
CHECKPOINT_DIR = os.path.join(STATE_DIR, "checkpoints")
CHECKPOINT_ARCHIVE = os.path.join(CHECKPOINT_DIR, "archive")
HANDOFF_DIR = os.path.join(STATE_DIR, "handoff")
ARTIFACTS_DIR = os.path.join(WORKSPACE, "runtime", "artifacts")
LOGS_DIR = os.path.join(WORKSPACE, "runtime", "logs")
COUNTER_PATH = os.path.join(STATE_DIR, "task-counter.json")
MANIFEST_PATH = os.path.join(ARTIFACTS_DIR, "MANIFEST.json")
REGISTRY_MUTEX = os.path.join(LOCKS_DIR, ".registry.mutex")

SCAN_SKIP = {
    ".ai", ".git", ".github", "node_modules", "vendor", "dist", "build",
    "target", "out", "bin", "obj", ".venv", "venv", "__pycache__",
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def ensure_dirs() -> None:
    for path in (
        os.path.join(WORKSPACE, "config"),
        os.path.join(WORKSPACE, "docs", "decisions"),
        os.path.join(WORKSPACE, "agents"),
        ACTIVE_DIR,
        DONE_DIR,
        os.path.join(WORKSPACE, "specs", "active"),
        os.path.join(WORKSPACE, "specs", "done"),
        LOCKS_DIR,
        STATE_DIR,
        CHECKPOINT_DIR,
        CHECKPOINT_ARCHIVE,
        HANDOFF_DIR,
        ARTIFACTS_DIR,
        LOGS_DIR,
    ):
        os.makedirs(path, exist_ok=True)


def config_path() -> str:
    return os.path.join(WORKSPACE, "config", "workspace.json")


def load_config() -> dict:
    with open(config_path(), encoding="utf-8") as handle:
        return json.load(handle)


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def write_json_atomic(path: str, payload) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "resource"


def ws_prefix() -> str:
    return "" if os.path.abspath(WORKSPACE) == os.path.abspath(PROJECT) else ".ai/"


def ws_rel(path: str) -> str:
    return os.path.relpath(path, PROJECT).replace(os.sep, "/")


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "task"


def normalize_id(task_id: str) -> str:
    digits = "".join(ch for ch in task_id if ch.isdigit())
    return digits.zfill(4) if digits else task_id


# ---------------------------------------------------------------------------
# Locking (race-condition safe, advisory)
# ---------------------------------------------------------------------------


def lock_settings() -> tuple[int, int]:
    locks = load_config().get("locks", {})
    return (
        int(locks.get("defaultTtlSeconds", 1800)),
        int(locks.get("staleAfterSeconds", 3600)),
    )


def max_lock_ttl() -> int:
    return int(load_config().get("locks", {}).get("maxTtlSeconds", 7200))


def lock_is_stale(payload: dict | None, stale_after: int) -> bool:
    # Staleness is TTL-based on purpose. A task claim outlives the CLI process
    # that created it, so PID liveness would mark every held task lock stale.
    # The PID and host are kept as diagnostics only.
    if not isinstance(payload, dict):
        return True
    try:
        updated = parse_iso(payload.get("updated_at") or payload.get("started_at"))
    except (TypeError, ValueError):
        return True
    return (now() - updated).total_seconds() > stale_after


def normalize_resource(resource: str) -> str:
    raw = resource.replace("\\", "/").strip()
    if not raw:
        raise ValueError("lock resource is empty")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError("lock resources must be repo-relative, not absolute")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw.rstrip("/") or "."


def resource_has_glob(resource: str) -> bool:
    return any(char in resource for char in "*?[")


def resources_overlap(first: str, second: str) -> bool:
    first = normalize_resource(first)
    second = normalize_resource(second)
    if first == second:
        return True
    if "." in (first, second) or "project" in (first, second):
        return True
    if resource_has_glob(first) or resource_has_glob(second):
        if fnmatch.fnmatch(first, second) or fnmatch.fnmatch(second, first):
            return True
        first_prefix = re.split(r"[*?[]", first, 1)[0].rstrip("/")
        second_prefix = re.split(r"[*?[]", second, 1)[0].rstrip("/")
        if first_prefix and (second == first_prefix or second.startswith(first_prefix + "/")):
            return True
        if second_prefix and (first == second_prefix or first.startswith(second_prefix + "/")):
            return True
        return False
    return first.startswith(second + "/") or second.startswith(first + "/")


@contextlib.contextmanager
def registry_mutex(timeout: float = 5.0):
    ensure_dirs()
    started = time.monotonic()
    while True:
        try:
            os.mkdir(REGISTRY_MUTEX)
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(REGISTRY_MUTEX)
            except OSError:
                age = 0
            if age > 30:
                try:
                    os.rmdir(REGISTRY_MUTEX)
                except OSError:
                    pass
                continue
            if time.monotonic() - started > timeout:
                raise TimeoutError("lock registry is busy")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.rmdir(REGISTRY_MUTEX)
        except OSError:
            pass


@contextlib.contextmanager
def workspace_state_guard():
    """Serialize state writes against `ai reset --hard`."""
    with registry_mutex():
        reset_lock = os.path.join(LOCKS_DIR, safe_name("project") + ".lock")
        if os.path.exists(reset_lock):
            raise RuntimeError("workspace reset is in progress")
        yield


def acquire_lock(
    resource: str,
    agent: str | None = None,
    task: str | None = None,
    ttl: int | None = None,
    force: bool = False,
) -> dict:
    ensure_dirs()
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        return {"ok": False, "holder": None, "error": str(exc)}
    default_ttl, stale_after = lock_settings()
    ttl = ttl or default_ttl
    if ttl > max_lock_ttl():
        return {"ok": False, "holder": None, "error": f"ttl must be <= {max_lock_ttl()} seconds"}
    path = os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")
    payload = {
        "resource": resource,
        "agent": agent or "unknown",
        "task": task,
        "host": HOST,
        "pid": os.getpid(),
        "started_at": iso(),
        "updated_at": iso(),
        "ttl_seconds": ttl,
    }
    try:
        with registry_mutex():
            for name in os.listdir(LOCKS_DIR):
                if not name.endswith(".lock"):
                    continue
                other_path = os.path.join(LOCKS_DIR, name)
                other = read_json(other_path)
                if not isinstance(other, dict):
                    continue
                if lock_is_stale(other, stale_after):
                    if force:
                        try:
                            os.remove(other_path)
                        except OSError:
                            pass
                    continue
                try:
                    overlaps = resources_overlap(resource, other.get("resource", ""))
                except ValueError:
                    overlaps = False
                if not overlaps:
                    continue
                if force:
                    try:
                        os.remove(other_path)
                    except OSError:
                        pass
                    continue
                return {"ok": False, "holder": other, "path": other_path}
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return {"ok": False, "holder": read_json(path), "path": path}
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            return {"ok": True, "lock": payload, "path": path}
    except TimeoutError as exc:
        return {"ok": False, "holder": None, "error": str(exc)}


def release_lock(resource: str, agent: str | None = None, force: bool = False) -> int:
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")
    holder = read_json(path)
    if holder is None:
        print(f"No lock held for '{resource}'.")
        return 0
    if agent and holder.get("agent") != agent and not force:
        print(
            f"Refusing to release '{resource}': held by {holder.get('agent')} "
            f"(task {holder.get('task')}). Use --force to override.",
            file=sys.stderr,
        )
        return 1
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    print(f"Released '{resource}'.")
    return 0


def heartbeat_lock(resource: str, agent: str | None = None) -> int:
    try:
        resource = normalize_resource(resource)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")
    holder = read_json(path)
    if holder is None:
        print(f"No lock held for '{resource}'.", file=sys.stderr)
        return 1
    if agent and holder.get("agent") != agent:
        print(f"Lock '{resource}' is held by {holder.get('agent')}.", file=sys.stderr)
        return 1
    holder["updated_at"] = iso()
    write_json_atomic(path, holder)
    print(f"Heartbeat '{resource}' at {holder['updated_at']}.")
    return 0


def list_locks() -> list[dict]:
    ensure_dirs()
    items = []
    for name in sorted(os.listdir(LOCKS_DIR)):
        if not name.endswith(".lock"):
            continue
        payload = read_json(os.path.join(LOCKS_DIR, name)) or {}
        payload["_file"] = name
        items.append(payload)
    return items


# ---------------------------------------------------------------------------
# Task files (Markdown + front matter)
# ---------------------------------------------------------------------------


def parse_value(raw: str):
    value = raw.strip()
    if value in ("", "null", "~", "None"):
        return None
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.startswith('"'):
        try:
            return json.loads(value)
        except ValueError:
            return value.strip('"')
    return value


def format_value(value) -> str:
    if value is None or value == "":
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", text) and not text.startswith("-"):
        return text
    return json.dumps(text, ensure_ascii=False)


def parse_task(path: str) -> tuple[dict, str]:
    text = read_text(path)
    if not text.startswith("---"):
        return {}, text
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    head = rest[:end].strip("\n")
    body = rest[end + 4 :].lstrip("\n")
    meta: dict = {}
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = parse_value(value)
    return meta, body


def write_task(path: str, meta: dict, body: str) -> None:
    order = ["id", "title", "status", "owner", "priority", "spec", "created", "updated", "lock"]
    keys = [key for key in order if key in meta] + [key for key in meta if key not in order]
    lines = ["---"]
    for key in keys:
        lines.append(f"{key}: {format_value(meta[key])}")
    lines.append("---")
    write_text_atomic(path, "\n".join(lines) + "\n\n" + body.lstrip("\n").rstrip("\n") + "\n")


def task_paths(folder: str) -> list[str]:
    directory = os.path.join(WORKSPACE, "tasks", folder)
    if not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.endswith(".md") and not name.startswith("TEMPLATE")
    ]


def find_task(task_id: str) -> str | None:
    wanted = normalize_id(task_id)
    for folder in ("active", "done"):
        for path in task_paths(folder):
            name = os.path.basename(path)
            if name.startswith(wanted + "-") or name.startswith(wanted + "."):
                return path
    return None


def load_tasks() -> list[dict]:
    items = []
    for folder in ("active", "done"):
        for path in task_paths(folder):
            meta, body = parse_task(path)
            meta["_path"] = path
            meta["_folder"] = folder
            meta["_body"] = body
            items.append(meta)
    return items


# ---------------------------------------------------------------------------
# Git, checkpoints and handoff
# ---------------------------------------------------------------------------


def run_git(
    args: list[str], cwd: str | None = None, input_text: str | None = None
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or PROJECT,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, ValueError):
        return 127, "", "git is not available"


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
    _, head, _ = run_git(["rev-parse", "HEAD"])
    state["head"] = head or None
    _, status, _ = run_git(["status", "--porcelain"])
    for line in status.splitlines():
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
        "production": str(config.get("productionBranch") or "main"),
        "branchTypes": [str(item) for item in branch_types],
        "template": str(config.get("commitTemplate") or "templates/git/commit-template.txt"),
        "merge": str(config.get("merge") or "no-ff"),
        "deleteAfterMerge": bool(config.get("deleteAfterMerge", True)),
    }


def git_template_path() -> str:
    template = git_config()["template"].replace("\\", "/")
    if template.startswith(".ai/") and os.path.basename(WORKSPACE) == ".ai":
        template = template[4:]
    return os.path.join(WORKSPACE, template.replace("/", os.sep))


def branch_exists(name: str) -> bool:
    code, _, _ = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
    return code == 0


def git_clean() -> bool:
    return not git_state().get("dirty")


def task_branch_name(meta: dict, branch_type: str) -> str:
    slug = slugify(str(meta.get("title") or "task"))[:40].strip("-")
    return f"{branch_type}/{normalize_id(str(meta.get('id')))}-{slug or 'task'}"


def task_owner_error(meta: dict, agent: str, force: bool = False) -> str | None:
    owner = meta.get("owner")
    if owner and owner != agent and not force:
        return f"Task {meta.get('id')} is owned by {owner}."
    return None


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
            return False, False, (
                f"git index is locked by {current.get('agent')} "
                f"(task {current.get('task') or '-'})."
            )
        return True, False, ""
    result = acquire_lock("@git/index", agent=agent, task=task_id, ttl=600)
    if not result["ok"]:
        holder = result["holder"] or {}
        return False, False, (
            f"git index is locked by {holder.get('agent')} "
            f"(task {holder.get('task') or '-'})."
        )
    return True, True, ""


def commit_task_metadata(task_path: str, message: str, amend: bool = False) -> str | None:
    paths = [task_path, os.path.join(WORKSPACE, "tasks", "BOARD.md")]
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


def fingerprint_file(relative: str) -> dict | None:
    path = os.path.join(PROJECT, relative.replace("\\", "/"))
    if not os.path.isfile(path):
        return None
    try:
        stat = os.stat(path)
        if stat.st_size > 5 * 1024 * 1024:
            return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "large": True}
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return {"sha256": digest.hexdigest(), "size": stat.st_size}
    except OSError:
        return None


def checkpoint_path(task_id: str) -> str:
    return os.path.join(CHECKPOINT_DIR, normalize_id(str(task_id)) + ".md")


def checkpoint_sidecar(task_id: str) -> str:
    return os.path.join(CHECKPOINT_DIR, normalize_id(str(task_id)) + ".json")


def handoff_marker(task_id: str) -> str:
    return os.path.join(HANDOFF_DIR, normalize_id(str(task_id)) + ".json")


def list_handoff_markers() -> list[dict]:
    ensure_dirs()
    items = []
    for name in sorted(os.listdir(HANDOFF_DIR)):
        if not name.endswith(".json"):
            continue
        payload = read_json(os.path.join(HANDOFF_DIR, name)) or {}
        payload["_file"] = name
        items.append(payload)
    return items


def read_checkpoint(task_id: str) -> tuple[dict, str, dict] | None:
    path = checkpoint_path(task_id)
    if not os.path.exists(path):
        return None
    meta, body = parse_task(path)
    return meta, body, (read_json(checkpoint_sidecar(task_id)) or {})


def checkpoint_age_minutes(task_id: str) -> float | None:
    data = read_checkpoint(task_id)
    if not data:
        return None
    meta, _, _ = data
    try:
        return (now() - parse_iso(meta.get("created"))).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None


def write_checkpoint(
    task_id: str,
    agent: str,
    reason: str,
    percent: int | None,
    fields: dict,
) -> str:
    ensure_dirs()
    task_id = normalize_id(str(task_id))
    state = git_state()
    previous = checkpoint_path(task_id)
    if os.path.exists(previous):
        stamp = now().strftime("%Y%m%dT%H%M%SZ")
        try:
            shutil.copy2(previous, os.path.join(CHECKPOINT_ARCHIVE, f"{task_id}-{stamp}.md"))
        except OSError:
            pass
    files = {}
    for rel in fields.get("files", []):
        fingerprint = fingerprint_file(rel)
        if fingerprint:
            files[rel.replace("\\", "/")] = fingerprint
    for rel in state.get("dirty", []):
        if rel and rel not in files:
            fingerprint = fingerprint_file(rel)
            if fingerprint:
                files[rel] = fingerprint
    if not fields.get("files_text") and files:
        lines = []
        for rel, item in sorted(files.items()):
            detail = "large file (size/mtime only)" if item.get("large") else str(item.get("sha256") or "")[:12]
            lines.append(f"- `{rel}` {detail}".rstrip())
        fields["files_text"] = "\n".join(lines)
    meta = {
        "task": task_id,
        "agent": agent,
        "created": iso(),
        "reason": reason,
        "percent": percent,
        "branch": state.get("branch"),
        "head": state.get("head"),
        "next": fields.get("next"),
        "status_line": fields.get("status_line"),
    }
    body = f"""# Checkpoint {task_id} - {fields.get('title') or 'task'}

## Objective

{fields.get('objective') or '<!-- restate the task intent in one paragraph -->'}

## Status

{fields.get('status') or '<!-- what is true right now -->'}

## Done

{fields.get('done') or '<!-- finished items, with evidence -->'}

## In progress

{fields.get('in_progress') or '<!-- exact step being executed, and where it stopped -->'}

## Next steps

{fields.get('next') or '<!-- ordered, concrete, resume from step 1 -->'}

## Decisions

{fields.get('decisions') or '<!-- choices made and why, so the next agent does not relitigate -->'}

## Do not

{fields.get('do_not') or '<!-- failed approaches, forbidden actions, user constraints -->'}

## Open questions

{fields.get('questions') or '<!-- what needs a human answer -->'}

## Files

{fields.get('files_text') or '<!-- files touched or opened, with why -->'}

## Verification

{fields.get('verification') or '<!-- commands already run and their results -->'}
"""
    write_task(checkpoint_path(task_id), meta, body)
    write_json_atomic(
        checkpoint_sidecar(task_id),
        {
            "task": task_id,
            "created": meta["created"],
            "agent": agent,
            "reason": reason,
            "percent": percent,
            "git": state,
            "files": files,
        },
    )
    marker = handoff_marker(task_id)
    if os.path.exists(marker):
        try:
            os.remove(marker)
        except OSError:
            pass
    return checkpoint_path(task_id)


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def print_lock_table(locks: list[dict]) -> None:
    _, stale_after = lock_settings()
    if not locks:
        print("No locks held.")
        return
    print(f"{'RESOURCE':<28} {'AGENT':<18} {'TASK':<8} {'AGE':>7}  STATE")
    for lock in locks:
        age = "?"
        state = "stale"
        try:
            updated = parse_iso(lock.get("updated_at") or lock.get("started_at"))
            seconds = int((now() - updated).total_seconds())
            age = f"{seconds}s"
            state = "stale" if lock_is_stale(lock, stale_after) else "held"
        except (TypeError, ValueError):
            pass
        print(
            f"{str(lock.get('resource'))[:28]:<28} "
            f"{str(lock.get('agent'))[:18]:<18} "
            f"{str(lock.get('task') or '-'):<8} {age:>7}  {state}"
        )


def write_board(tasks: list[dict]) -> None:
    _, stale_after = lock_settings()
    lines = ["# Task Board", "", "Generated by `ai task list`. Do not edit by hand.", ""]
    active = [task for task in tasks if task.get("_folder") == "active"]
    done = [task for task in tasks if task.get("_folder") == "done"]
    lines.append(f"Active: {len(active)} | Done: {len(done)} | Updated: {iso()}")
    lines.append("")
    if active:
        lines.append("## Active")
        lines.append("")
        lines.append("| ID | Status | Owner | Priority | Title |")
        lines.append("|----|--------|-------|----------|-------|")
        for task in active:
            lines.append(
                f"| {task.get('id', '?')} | {task.get('status', '?')} | "
                f"{task.get('owner') or '-'} | {task.get('priority') or '-'} | "
                f"{task.get('title', '?')} |"
            )
        lines.append("")
    else:
        lines.append("_No active tasks._")
        lines.append("")
    if done:
        lines.append("## Recently done")
        lines.append("")
        for task in sorted(done, key=lambda item: str(item.get("updated") or ""), reverse=True)[:20]:
            lines.append(f"- {task.get('id', '?')} — {task.get('title', '?')} ({task.get('updated', '?')})")
        lines.append("")
    write_text_atomic(os.path.join(WORKSPACE, "tasks", "BOARD.md"), "\n".join(lines))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def default_config() -> dict:
    return {
        "version": 1,
        "name": os.path.basename(PROJECT),
        "mode": "lite",
        "language": {"documents": "en", "interviews": "en"},
        "agents": ["orchestrator", "planner", "implementer", "reviewer", "qa"],
        "locks": {
            "defaultTtlSeconds": 1800,
            "staleAfterSeconds": 3600,
            "maxTtlSeconds": 7200,
        },
        "handoff": {
            "checkpointEveryMinutes": 20,
            "warnAfterMinutes": 30,
        },
        "budget": {
            "contextTokens": 200000,
            "warnAtPercent": 70,
            "checkpointAtPercent": 85,
        },
        "artifacts": {
            "quarantine": "runtime/artifacts",
            "watch": ["tmp", "temp", "scratch", ".cache", "ai-notes", "notes-ai"],
        },
        "security": {"warnTrackedSecrets": True},
        "checks": [],
    }


def cmd_init(args) -> int:
    ensure_dirs()
    if not os.path.exists(config_path()):
        write_json_atomic(config_path(), default_config())
    root_ignore = os.path.join(WORKSPACE, "runtime", ".gitignore")
    if not os.path.exists(root_ignore):
        write_text_atomic(
            root_ignore,
            "# Keep the shape, ignore transient state.\n*\n!.gitignore\n!**/\n!**/.gitkeep\n",
        )
    for folder in (LOCKS_DIR, STATE_DIR, CHECKPOINT_DIR, HANDOFF_DIR, ARTIFACTS_DIR, LOGS_DIR):
        keep = os.path.join(folder, ".gitkeep")
        if not os.path.exists(keep):
            write_text_atomic(keep, "")
    print(f"Workspace ready: {WORKSPACE}")
    print(f"Project root:    {PROJECT}")
    if args.wire:
        if os.path.basename(WORKSPACE) != ".ai":
            print("Template install detected: the workspace is the project root; no wiring needed.")
        else:
            for path, state in adopt_root():
                print(f"{state.upper():<10} {path}")
            state, _ = adopt_gitignore()
            print(f"{state.upper():<10} .gitignore")
            print("Local adapters are in place. Each clone runs `ai adopt` to create its own copies.")
    print("Next: run `ai doctor`.")
    return 0


ROOT_BLOCK = """<!-- ai-workspace:start -->
## AI workspace

This project uses the `.ai` engineering workspace. Task state, specs, locks,
checkpoints, logs and scratch artifacts live under `.ai/` and nowhere else.

Before any file-changing task, use Gitflow unless the user explicitly asks not
to use Git:
1. Read `.ai/AGENTS.md`, `.ai/GUIDE.md`, `.ai/docs/task-flow.md` and
   `.ai/docs/git-workflow.md`.
2. Run `.ai/scripts/ai git setup`. It initializes Git if needed and, when the
   repo has no commits, previews non-ignored files and asks before the initial
   commit. If Git reports dubious ownership, ask the user
   to approve trusting only this exact checkout; never use a wildcard entry.
3. Create or claim one task, then successfully run
   `.ai/scripts/ai git start --task <id> --agent <name> --type <type>`. If it
   fails, stop before editing and report the blocker.
4. Stage only owned paths, run `.ai/scripts/ai git verify --strict`, then commit
   with `.ai/scripts/ai git commit`. Submit the task for review; a different
   reviewer runs `.ai/scripts/ai git finish` before the task is marked done.

Read-only tasks do not need a branch. Do not skip Gitflow just because `.git`
is absent; setup initializes the repository.

Checkpoint before the context window fills. Verify with
`.ai/scripts/ai check`; "done" requires its output.

Never create task notes, scratch files or generated logs outside `.ai/`.
<!-- ai-workspace:end -->
"""

BOOTSTRAP_PROMPT = """This project uses the .ai engineering workspace.

1. Read .ai/AGENTS.md, .ai/GUIDE.md, .ai/docs/task-flow.md,
   .ai/docs/multi-agent.md and .ai/docs/git-workflow.md.
2. Run `.ai/scripts/ai adopt` once so every AI tool in this project finds the workspace.
3. Run `.ai/scripts/ai doctor`. Before file-changing work, run
   `.ai/scripts/ai git setup` once in this clone; it initializes Git when
   needed. Then claim a task and successfully run `.ai/scripts/ai git start`
   before editing; follow the commit and independent review flow in
   `.ai/docs/git-workflow.md`.

Read-only tasks need no branch. Skip Gitflow only when the user explicitly asks
not to use Git. If Git reports dubious ownership, ask approval to trust only
this exact checkout. All AI state stays under .ai/. Claim a task before editing,
checkpoint before your context fills, and never call work done without
`.ai/scripts/ai check`.
"""


def upsert_managed(path: str, block: str, force: bool = False) -> str:
    start_marker = "<!-- ai-workspace:start -->"
    end_marker = "<!-- ai-workspace:end -->"
    existing = read_text(path) if os.path.exists(path) else ""
    if start_marker in existing and end_marker in existing:
        if not force:
            return "unchanged"
        start = existing.index(start_marker)
        end = existing.index(end_marker) + len(end_marker)
        updated = existing[:start].rstrip("\n") + "\n" + block.strip() + "\n" + existing[end:].lstrip("\n")
        write_text_atomic(path, updated)
        return "updated"
    separator = "\n\n" if existing.strip() else ""
    write_text_atomic(path, existing.rstrip("\n") + separator + block.strip() + "\n")
    return "written"


def adopt_root(force: bool = False, check: bool = False) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    targets = [
        os.path.join(PROJECT, "AGENTS.md"),
        os.path.join(PROJECT, "CLAUDE.md"),
        os.path.join(PROJECT, ".cursor", "rules", "ai-workspace.mdc"),
        os.path.join(PROJECT, ".github", "copilot-instructions.md"),
    ]
    for path in targets:
        if check:
            existing = read_text(path) if os.path.exists(path) else ""
            state = "ok" if "<!-- ai-workspace:start -->" in existing else "missing"
            results.append((os.path.relpath(path, PROJECT), state))
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if path.endswith(".mdc") and not os.path.exists(path):
            write_text_atomic(
                path,
                "---\ndescription: AI workspace entry rules\nalwaysApply: true\n---\n\n" + ROOT_BLOCK.strip() + "\n",
            )
            results.append((os.path.relpath(path, PROJECT), "written"))
            continue
        results.append((os.path.relpath(path, PROJECT), upsert_managed(path, ROOT_BLOCK, force)))
    return results


ADOPT_IGNORE_ENTRIES = (
    ".ai/",
    "/AGENTS.md",
    "/CLAUDE.md",
    ".cursor/rules/ai-workspace.mdc",
    ".github/copilot-instructions.md",
    ".github/workflows/ai-check.yml",
)


def normalized_ignore_entry(line: str) -> str | None:
    value = line.strip()
    if not value or value.startswith("#") or value.startswith("!"):
        return None
    while value.startswith("/"):
        value = value[1:]
    value = value.replace("\\", "/")
    if value.endswith("/"):
        value = value[:-1]
    return value


def adopt_gitignore(check: bool = False) -> tuple[str, list[str]]:
    path = os.path.join(PROJECT, ".gitignore")
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as handle:
            existing = handle.read()
    present = {
        normalized_ignore_entry(line)
        for line in existing.splitlines()
    }
    missing = [
        entry for entry in ADOPT_IGNORE_ENTRIES
        if normalized_ignore_entry(entry) not in present
    ]
    if check:
        return ("ok" if not missing else "missing"), missing
    if not missing:
        return "unchanged", []

    newline = "\r\n" if "\r\n" in existing else "\n"
    separator = "" if not existing or existing.endswith(("\n", "\r")) else newline
    addition = newline.join([
        "# Added by ai adopt: keep the workspace and generated adapters local.",
        *missing,
    ]) + newline
    write_text_atomic(path, existing + separator + addition)
    return ("created" if not existing else "updated"), missing


def cmd_adopt(args) -> int:
    if not args.check:
        ensure_dirs()
    if not args.check and not os.path.exists(config_path()):
        write_json_atomic(config_path(), default_config())
    if args.print:
        print(BOOTSTRAP_PROMPT)
        return 0
    if os.path.basename(WORKSPACE) != ".ai":
        print("Template install detected: the workspace is the project root.")
        print("Root AGENTS.md already acts as the signpost; no wiring needed.")
        if not args.check:
            print("Run `ai doctor` to verify the workspace.")
        return 0
    results = adopt_root(force=args.force, check=args.check)
    for path, state in results:
        print(f"{state.upper():<10} {path}")
    try:
        ignore_state, missing_ignore = adopt_gitignore(check=args.check)
    except OSError as exc:
        print(f"Could not update the project .gitignore: {exc}", file=sys.stderr)
        return 1
    print(f"{ignore_state.upper():<10} .gitignore")
    if missing_ignore:
        print("Missing ignore rules: " + ", ".join(missing_ignore))
    if args.check:
        missing = [path for path, state in results if state != "ok"]
        return 1 if missing or missing_ignore else 0
    if args.ci:
        write_ci()
    print("\nLocal adapters are in place. Each clone runs `ai adopt` to create its own copies.")
    print("Next: ai doctor")
    return 0


CI_WORKFLOW = """name: ai-workspace

on:
  push:
  pull_request:

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Workspace health
        run: python .ai/scripts/ai.py doctor --strict
      - name: Verification contract
        run: python .ai/scripts/ai.py check --strict
"""


def write_ci() -> None:
    path = os.path.join(PROJECT, ".github", "workflows", "ai-check.yml")
    if os.path.exists(path):
        print(f"CI workflow already exists: {os.path.relpath(path, PROJECT)}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text_atomic(path, CI_WORKFLOW)
    print(f"CI workflow: {os.path.relpath(path, PROJECT)}")


def collect_checks() -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    for rel in REQUIRED_PATHS:
        if not os.path.exists(os.path.join(WORKSPACE, rel)):
            problems.append(("error", f"missing required path: {rel}"))
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        problems.append(("error", f"config/workspace.json is unreadable: {exc}"))
        config = {}
    if config:
        if config.get("mode") not in ("lite", "strict"):
            problems.append(("error", "config mode must be 'lite' or 'strict'"))
        for key in ("version", "language", "locks", "handoff", "budget", "artifacts"):
            if key not in config:
                problems.append(("warn", f"config is missing key: {key}"))

    locks = list_locks()
    lock_by_task = {}
    for lock in locks:
        resource = str(lock.get("resource") or "")
        if resource.startswith("task-"):
            lock_by_task[resource[5:]] = lock

    ids: dict[str, str] = {}
    tasks = load_tasks()
    for task in tasks:
        path = os.path.relpath(task["_path"], WORKSPACE)
        task_id = task.get("id")
        if not task_id:
            problems.append(("error", f"{path}: missing id"))
        else:
            task_id = str(task_id)
            if task_id in ids:
                problems.append(("error", f"duplicate task id {task_id}: {path} and {ids[task_id]}"))
            ids[task_id] = path
            if task["_folder"] == "active" and normalize_id(task_id) + "-" not in os.path.basename(path):
                problems.append(("warn", f"{path}: filename does not start with {task_id}-"))
        if not task.get("title"):
            problems.append(("error", f"{path}: missing title"))
        status = task.get("status")
        if status not in TASK_STATUSES:
            problems.append(("error", f"{path}: invalid status '{status}'"))
        if task["_folder"] == "done" and status != "done":
            problems.append(("warn", f"{path}: file in done/ but status is '{status}'"))
        if task["_folder"] == "active" and status == "done":
            problems.append(("warn", f"{path}: status is done but file is in active/"))
        depends = task.get("depends_on")
        if depends:
            for dependency in re.split(r"[,\s]+", str(depends)):
                dependency = dependency.strip()
                if dependency and normalize_id(dependency) not in ids and not find_task(dependency):
                    problems.append(("warn", f"{path}: depends_on unknown task {dependency}"))
        if task["_folder"] == "active":
            owner = task.get("owner")
            held = lock_by_task.get(str(task_id))
            if owner and not held:
                problems.append(("warn", f"{path}: owner '{owner}' has no task lock (use `ai recover`)"))
            if held and not owner:
                problems.append(("warn", f"{path}: task lock held by {held.get('agent')} but owner is empty"))
            if owner and held and held.get("agent") != owner:
                problems.append(("warn", f"{path}: owner '{owner}' differs from lock holder '{held.get('agent')}'"))
            if status == "in_progress":
                warn_after = int(config.get("handoff", {}).get("warnAfterMinutes", 30)) if config else 30
                age = checkpoint_age_minutes(task_id)
                if age is None:
                    problems.append(
                        ("warn", f"{path}: in_progress with no checkpoint "
                                 f"(run `ai checkpoint {task_id} --agent {owner or 'agent'}`)")
                    )
                elif age > warn_after:
                    problems.append(
                        ("warn", f"{path}: last checkpoint is {int(age)} min old "
                                 f"(checkpoint before the context window fills)")
                    )
        if task["_folder"] == "done" and str(task_id) in lock_by_task:
            problems.append(("warn", f"{path}: done task still holds task lock (use `ai recover --apply`)"))

    _, stale_after = lock_settings()
    for lock in locks:
        if lock_is_stale(lock, stale_after):
            problems.append(
                ("warn", f"stale lock: {lock.get('resource')} held by {lock.get('agent')} "
                         f"(use `ai clean --stale-locks`)")
            )
    for lock in locks:
        resource = str(lock.get("resource") or "")
        if resource.startswith("task-") and resource[5:] not in ids:
            problems.append(("warn", f"orphan task lock: {resource} has no task file"))

    for marker in list_handoff_markers():
        task_id = str(marker.get("task") or "")
        data = read_checkpoint(task_id)
        if not data:
            problems.append(("warn", f"handoff requested for {task_id} but no checkpoint exists"))
        elif str(data[0].get("created") or "") < str(marker.get("created") or ""):
            problems.append(("warn", f"handoff requested for {task_id} but the checkpoint is older"))

    watch = config.get("artifacts", {}).get("watch", []) if config else []
    try:
        top_level = set(os.listdir(PROJECT))
    except OSError:
        top_level = set()
    for name in watch:
        if name in top_level and name not in SCAN_SKIP:
            problems.append(
                ("error", f"AI scratch path outside the workspace: {name}/ "
                          f"(move it with `ai artifact put {name}`)")
            )

    if config.get("security", {}).get("warnTrackedSecrets", True):
        code, tracked, _ = run_git(["ls-files"])
        if code == 0 and tracked:
            risky = [
                item for item in tracked.splitlines()
                if item in (".env", ".env.local")
                or item.endswith((".pem", ".key", ".p12", ".pfx"))
                or os.path.basename(item) in ("id_rsa", "id_ed25519", "credentials.json")
            ]
            for item in risky:
                problems.append(("warn", f"tracked secret-shaped file: {item}"))
    return problems


def report_problems(problems: list[tuple[str, str]]) -> int:
    errors = [msg for level, msg in problems if level == "error"]
    warnings = [msg for level, msg in problems if level == "warn"]
    for message in errors:
        print(f"ERROR  {message}")
    for message in warnings:
        print(f"WARN   {message}")
    if not problems:
        print("OK     workspace structure and task state are consistent")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def run_commands(fast_only: bool) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    config = load_config()
    for item in config.get("checks", []):
        if fast_only and not item.get("fast", False):
            continue
        name = item.get("name") or item.get("command", "check")
        command = item.get("command")
        if not command:
            continue
        print(f"\n$ {command}")
        result = subprocess.run(command, shell=True, cwd=PROJECT)
        if result.returncode != 0:
            problems.append(("error", f"check '{name}' failed with exit code {result.returncode}"))
    return problems


def adapters() -> list[str]:
    directory = os.path.join(WORKSPACE, "adapters")
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory) if os.path.isdir(os.path.join(directory, name)))


def problems_to_dict(problems: list[tuple[str, str]]) -> dict:
    return {
        "ok": not any(level == "error" for level, _ in problems),
        "errors": [message for level, message in problems if level == "error"],
        "warnings": [message for level, message in problems if level == "warn"],
    }


def cmd_doctor(args) -> int:
    problems = collect_checks()
    code = report_problems(problems) if not args.json else 0
    if args.strict and any(level == "warn" for level, _ in problems):
        code = 1
    if args.json:
        payload = {
            "workspace": WORKSPACE,
            "project": PROJECT,
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "version": VERSION,
            "adapters": adapters(),
            "check": problems_to_dict(problems),
        }
        print(json.dumps(payload, indent=2))
        return code
    print(f"workspace: {WORKSPACE}")
    print(f"project:   {PROJECT}")
    print(f"platform:  {sys.platform} ({os.name})")
    print(f"python:    {sys.version.split()[0]}")
    print(f"version:   {VERSION}")
    print()
    for adapter in adapters():
        print(f"adapter:   {adapter}")
    print()
    return code


def cmd_check(args) -> int:
    problems = collect_checks()
    if not args.no_commands:
        try:
            problems.extend(run_commands(args.fast))
        except (OSError, ValueError) as exc:
            problems.append(("error", f"could not run configured checks: {exc}"))
    code = 1 if any(level == "error" for level, _ in problems) else 0
    if args.strict and any(level == "warn" for level, _ in problems):
        code = 1
    if args.json:
        print(json.dumps(problems_to_dict(problems), indent=2))
        return code
    report_problems(problems)
    return code


def cmd_status(args) -> int:
    config = load_config()
    tasks = load_tasks()
    active = [task for task in tasks if task["_folder"] == "active"]
    locks = list_locks()
    artifacts = read_json(MANIFEST_PATH) or []
    markers = list_handoff_markers()
    checkpoints = [
        {"task": path.split(os.sep)[-1][:-3], "age_minutes": checkpoint_age_minutes(path.split(os.sep)[-1][:-3])}
        for path in sorted(
            os.path.join(CHECKPOINT_DIR, name)
            for name in os.listdir(CHECKPOINT_DIR)
            if name.endswith(".md")
        )
    ] if os.path.isdir(CHECKPOINT_DIR) else []
    if args.json:
        print(json.dumps({
            "workspace": WORKSPACE,
            "project": PROJECT,
            "mode": config.get("mode"),
            "active": active,
            "locks": locks,
            "handoffs": markers,
            "checkpoints": checkpoints,
            "artifacts": artifacts,
        }, indent=2, default=str))
        return 0
    print(f"Workspace  : {WORKSPACE}")
    print(f"Mode       : {config.get('mode')}")
    print(f"Active     : {len(active)} task(s)")
    print(f"Locks      : {len(locks)} held")
    print(f"Checkpoints: {len(checkpoints)}")
    print(f"Handoffs   : {len(markers)} pending")
    print(f"Artifacts  : {len(artifacts)} quarantined")
    print()
    if active:
        print(f"{'ID':<6} {'STATUS':<12} {'OWNER':<18} TITLE")
        for task in active:
            print(
                f"{str(task.get('id')):<6} {str(task.get('status')):<12} "
                f"{str(task.get('owner') or '-'):<18} {task.get('title')}"
            )
        print()
    for marker in markers:
        print(f"HANDOFF    task {marker.get('task')} requested by {marker.get('agent')} ({marker.get('reason')})")
    print_lock_table(locks)
    return 0


@contextlib.contextmanager
def task_index_guard():
    resource = "tasks.index"
    result = acquire_lock(resource, agent="task-index", ttl=60)
    if not result["ok"]:
        holder = result.get("holder") or {}
        print(
            "Could not allocate a task id: the task index is locked by "
            f"{holder.get('agent')}.",
            file=sys.stderr,
        )
        raise RuntimeError("task index is locked")
    try:
        yield
    finally:
        release_lock(resource, agent="task-index")


def allocate_task_number() -> int:
    """Allocate an ID while the caller holds task_index_guard()."""
    resource = "tasks.index"
    holder = read_json(os.path.join(LOCKS_DIR, safe_name(resource) + ".lock")) or {}
    if holder.get("agent") != "task-index":
        raise RuntimeError("task ID allocation requires the tasks.index lock")
    state = read_json(COUNTER_PATH) or {"last": 0}
    last = int(state.get("last", 0) or 0)
    for task in load_tasks():
        digits = "".join(ch for ch in str(task.get("id") or "") if ch.isdigit())
        if digits:
            last = max(last, int(digits))
    number = last + 1
    write_json_atomic(COUNTER_PATH, {"last": number})
    return number


def cmd_task_new(args) -> int:
    ensure_dirs()
    try:
        with task_index_guard():
            number = allocate_task_number()
            task_id = f"{number:04d}"
            title = args.title.strip()
            slug = slugify(title)
            path = os.path.join(ACTIVE_DIR, f"{task_id}-{slug}.md")
            meta = {
                "id": task_id,
                "title": title,
                "status": "todo",
                "owner": None,
                "priority": args.priority,
                "spec": args.spec,
                "depends_on": getattr(args, "depends_on", None),
                "created": iso(),
                "updated": iso(),
                "lock": None,
            }
            body = f"""# {task_id} - {title}

## Intent

<!-- What problem does this solve? Who is it for? -->

## Acceptance criteria

- [ ] 

## Plan

<!-- Filled by the planner. Link the spec when one exists. -->

## Notes

## Log

- {iso()} created
"""
            write_task(path, meta, body)
            write_board(load_tasks())
    except RuntimeError:
        return 1
    print(f"Created {os.path.relpath(path, PROJECT)}")
    if args.spec:
        print(f"Spec: {args.spec}")
    print(f"Claim it: ai task claim {task_id} --agent <name>")
    return 0


def cmd_task_list(args) -> int:
    try:
        with workspace_state_guard():
            tasks = load_tasks()
            write_board(tasks)
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
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, body = parse_task(path)
    if args.json:
        print(json.dumps({"meta": meta, "body": body}, indent=2, default=str))
        return 0
    print(f"File: {os.path.relpath(path, PROJECT)}")
    for key, value in meta.items():
        print(f"{key}: {value}")
    print()
    print(body)
    return 0


def dependency_blockers(meta: dict) -> list[str]:
    blockers = []
    depends = meta.get("depends_on")
    if not depends:
        return blockers
    for dependency in re.split(r"[,\s]+", str(depends)):
        dependency = dependency.strip()
        if not dependency:
            continue
        dep_path = find_task(dependency)
        if not dep_path:
            blockers.append(f"unknown task {dependency}")
            continue
        dep_meta, _ = parse_task(dep_path)
        if dep_meta.get("status") != "done":
            blockers.append(f"{dependency} is {dep_meta.get('status') or 'unknown'}")
    return blockers


def claim_task(path: str, agent: str, force: bool = False) -> tuple[bool, str]:
    if os.path.dirname(path) != ACTIVE_DIR:
        return False, "This task is already in done/."
    meta, body = parse_task(path)
    task_id = str(meta.get("id"))
    if meta.get("status") == "blocked" and not force:
        return False, f"Task {task_id} is blocked. Unblock it with `ai task unblock {task_id}`."
    blockers = dependency_blockers(meta)
    if blockers and not force:
        return False, f"Task {task_id} is blocked by " + ", ".join(blockers) + ". Use --force to override."
    resource = f"task-{task_id}"
    result = acquire_lock(resource, agent=agent, task=task_id, force=force)
    if not result["ok"]:
        if result.get("error"):
            return False, f"Could not claim task {task_id}: {result['error']}"
        holder = result["holder"] or {}
        if holder.get("agent") == agent:
            heartbeat_lock(resource, agent=agent)
        else:
            return False, (
                f"Task {task_id} is locked by {holder.get('agent')} "
                f"(pid {holder.get('pid')}, since {holder.get('started_at')})."
            )
    if find_task(task_id) != path:
        release_lock(resource, agent=agent, force=True)
        return False, f"Task {task_id} was removed while it was being claimed."
    meta["owner"] = agent
    meta["status"] = "in_progress"
    meta["updated"] = iso()
    meta["lock"] = resource
    body = body.rstrip("\n") + f"\n- {iso()} claimed by {agent}\n"
    write_task(path, meta, body)
    write_board(load_tasks())
    return True, task_id


def cmd_task_claim(args) -> int:
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    ok, message = claim_task(path, args.agent, args.force)
    if not ok:
        print(message, file=sys.stderr)
        return 1
    print(f"Claimed {message} for {args.agent}.")
    print(f"Release when done: ai task release {message} --agent {args.agent}")
    return 0


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def ready_and_waiting() -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    active = [task for task in load_tasks() if task["_folder"] == "active"]
    locks = {str(lock.get("resource")): lock for lock in list_locks()}
    _, stale_after = lock_settings()
    ready = []
    waiting = []
    for task in active:
        if task.get("status") != "todo":
            continue
        reasons = dependency_blockers(task)
        lock = locks.get(f"task-{task.get('id')}")
        if lock and not lock_is_stale(lock, stale_after):
            reasons.append(f"leased by {lock.get('agent')}")
        if reasons:
            waiting.append((task, reasons))
        else:
            ready.append(task)
    ready.sort(key=lambda item: (PRIORITY_ORDER.get(str(item.get("priority")), 1), str(item.get("id"))))
    return ready, waiting


def cmd_task_ready(args) -> int:
    ready, waiting = ready_and_waiting()
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


def cmd_task_next(args) -> int:
    ready, waiting = ready_and_waiting()
    for task in ready:
        ok, message = claim_task(task["_path"], args.agent)
        if not ok:
            print(f"Skipped {task.get('id')}: {message}", file=sys.stderr)
            continue
        claimed_path = find_task(message)
        meta, body = parse_task(claimed_path)
        if args.json:
            print(json.dumps({"meta": meta, "body": body}, indent=2, default=str))
            return 0
        print(f"Claimed {message} - {meta.get('title')}")
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
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = parse_task(path)
    task_id = str(meta.get("id"))
    resource = f"task-{task_id}"
    try:
        with workspace_state_guard():
            current_path = find_task(task_id)
            if current_path != path:
                print(f"Task {task_id} changed before release.", file=sys.stderr)
                return 1
            meta, body = parse_task(current_path)
            if meta.get("owner") and meta.get("owner") != args.agent and not args.force:
                print(
                    f"Task {task_id} is owned by {meta.get('owner')}. Use --force to override.",
                    file=sys.stderr,
                )
                return 1
            meta["owner"] = None
            meta["lock"] = None
            if meta.get("status") == "in_progress":
                meta["status"] = "todo"
            meta["updated"] = iso()
            body = body.rstrip("\n") + f"\n- {iso()} released by {args.agent}\n"
            write_task(current_path, meta, body)
            write_board(load_tasks())
    except RuntimeError as exc:
        print(f"Cannot release task {task_id}: {exc}.", file=sys.stderr)
        return 1
    return release_lock(resource, agent=args.agent, force=args.force)


def cmd_task_review(args) -> int:
    path = find_task(args.task_id)
    if not path or os.path.dirname(path) != ACTIVE_DIR:
        print(f"No active task with id {args.task_id}.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = find_task(args.task_id)
            if current_path != path or os.path.dirname(current_path or "") != ACTIVE_DIR:
                print(f"Task {args.task_id} changed before review.", file=sys.stderr)
                return 1
            meta, body = parse_task(current_path)
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
            meta["status"] = "review"
            meta["updated"] = iso()
            body = body.rstrip("\n") + f"\n- {iso()} submitted for independent review by {args.agent}\n"
            write_task(current_path, meta, body)
            write_board(load_tasks())
    except RuntimeError as exc:
        print(f"Cannot submit task {args.task_id} for review: {exc}.", file=sys.stderr)
        return 1
    print(f"Task {task_id} is ready for independent review. Release it before reviewer takeover.")
    return 0


def cmd_task_block(args) -> int:
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = find_task(args.task_id)
            if current_path != path:
                print(f"Task {args.task_id} changed before it could be blocked.", file=sys.stderr)
                return 1
            meta, body = parse_task(current_path)
            meta["status"] = "blocked"
            meta["updated"] = iso()
            body = body.rstrip("\n") + f"\n- {iso()} blocked by {args.agent}: {args.reason}\n"
            write_task(current_path, meta, body)
            write_board(load_tasks())
    except RuntimeError as exc:
        print(f"Cannot block task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Blocked {meta.get('id')}: {args.reason}")
    return 0


def cmd_task_unblock(args) -> int:
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            current_path = find_task(args.task_id)
            if current_path != path:
                print(f"Task {args.task_id} changed before it could be unblocked.", file=sys.stderr)
                return 1
            meta, body = parse_task(current_path)
            meta["status"] = "todo"
            meta["updated"] = iso()
            body = body.rstrip("\n") + f"\n- {iso()} unblocked by {args.agent}\n"
            write_task(current_path, meta, body)
            write_board(load_tasks())
    except RuntimeError as exc:
        print(f"Cannot unblock task {args.task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Unblocked {meta.get('id')}.")
    return 0


def cmd_task_done(args) -> int:
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) == DONE_DIR:
        print("Task is already done.")
        return 0
    meta, body = parse_task(path)
    task_id = str(meta.get("id"))
    resource = f"task-{task_id}"
    holder = read_json(os.path.join(LOCKS_DIR, safe_name(resource) + ".lock"))
    if not holder:
        result = acquire_lock(resource, agent=args.agent, task=task_id, force=args.force)
        if not result["ok"]:
            print(f"Task {task_id} is locked by {result['holder'].get('agent')}.", file=sys.stderr)
            return 1
    elif holder.get("agent") != args.agent and not args.force:
        print(f"Task {task_id} is locked by {holder.get('agent')}.", file=sys.stderr)
        return 1
    meta["status"] = "done"
    meta["updated"] = iso()
    meta["lock"] = None
    body = body.rstrip("\n") + f"\n- {iso()} marked done by {args.agent}\n"
    write_task(path, meta, body)
    target = os.path.join(DONE_DIR, os.path.basename(path))
    os.replace(path, target)
    release_lock(resource, force=True)
    marker = handoff_marker(task_id)
    if os.path.exists(marker):
        try:
            os.remove(marker)
        except OSError:
            pass
    write_board(load_tasks())
    print(f"Done: {os.path.relpath(target, PROJECT)}")
    return 0


def task_discard_spec_path(meta: dict, task_id: str) -> tuple[str | None, str | None]:
    reference = str(meta.get("spec") or "").strip()
    if not reference:
        return None, None
    reference = reference.replace("\\", "/")
    if reference.startswith(".ai/") and os.path.basename(WORKSPACE) == ".ai":
        reference = reference[4:]
    candidate = os.path.realpath(os.path.join(WORKSPACE, reference.replace("/", os.sep)))
    roots = [
        os.path.realpath(os.path.join(WORKSPACE, "specs", "active")),
        os.path.realpath(os.path.join(WORKSPACE, "specs", "done")),
    ]
    try:
        inside_specs = any(os.path.commonpath([candidate, root]) == root for root in roots)
    except ValueError:
        inside_specs = False
    if not inside_specs:
        return None, f"Linked spec is outside specs/active or specs/done: {reference}"
    if not os.path.exists(candidate):
        # A previous interrupted discard may already have removed the spec;
        # allow the operator to retry and finish removing the task.
        return None, None
    if not os.path.isfile(candidate):
        return None, f"Linked spec is not a file: {reference}"
    spec_meta, _ = parse_task(candidate)
    if normalize_id(str(spec_meta.get("task") or "")) != normalize_id(task_id):
        return None, f"Linked spec does not identify task {task_id}: {reference}"
    return candidate, None


def task_discard_targets(task_path: str, spec_path: str | None, task_id: str) -> list[str]:
    targets = [
        checkpoint_path(task_id),
        checkpoint_sidecar(task_id),
        handoff_marker(task_id),
    ]
    if os.path.isdir(CHECKPOINT_ARCHIVE):
        archive_prefix = f"{task_id}-"
        targets.extend(
            os.path.join(CHECKPOINT_ARCHIVE, name)
            for name in os.listdir(CHECKPOINT_ARCHIVE)
            if name.startswith(archive_prefix) and name.endswith(".md")
        )
    if spec_path:
        targets.append(spec_path)
    targets.append(task_path)
    return [target for target in targets if os.path.isfile(target)]


def task_discard_lock_error(task_id: str, targets: list[str]) -> str | None:
    lock_path = os.path.join(LOCKS_DIR, safe_name(f"task-{task_id}") + ".lock")
    holder = read_json(lock_path)
    if holder:
        return (
            f"Task {task_id} still has a lock held by {holder.get('agent')}. "
            "Release it normally or run `ai recover --apply` after it is stale."
        )
    _, stale_after = lock_settings()
    for lock in list_locks():
        if lock_is_stale(lock, stale_after):
            continue
        resource = str(lock.get("resource") or "")
        for target in targets:
            aliases = {
                os.path.relpath(target, WORKSPACE).replace(os.sep, "/"),
                os.path.relpath(target, PROJECT).replace(os.sep, "/"),
            }
            try:
                overlaps = any(resources_overlap(alias, resource) for alias in aliases)
            except ValueError:
                overlaps = False
            if overlaps:
                return (
                    f"Task {task_id} has a related live file lock held by "
                    f"{lock.get('agent')} ({resource}); refusing discard."
                )
    return None


def cmd_task_discard(args) -> int:
    path = find_task(args.task_id)
    if not path:
        print(f"No task with id {args.task_id}.", file=sys.stderr)
        return 1
    meta, _ = parse_task(path)
    task_id = normalize_id(str(meta.get("id") or args.task_id))
    if not sys.stdin.isatty():
        print("Discard requires an interactive terminal; no files were changed.", file=sys.stderr)
        return 1

    spec_path, spec_error = task_discard_spec_path(meta, task_id)
    if spec_error:
        print(f"Cannot safely discard task: {spec_error}", file=sys.stderr)
        return 1
    targets = task_discard_targets(path, spec_path, task_id)
    lock_error = task_discard_lock_error(task_id, targets)
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
            current_path = find_task(task_id)
            if current_path != path:
                print(f"Task {task_id} changed while awaiting confirmation; retry.", file=sys.stderr)
                return 1
            current_meta, _ = parse_task(current_path)
            if current_meta.get("title") != meta.get("title") or current_meta.get("spec") != meta.get("spec"):
                print(f"Task {task_id} changed while awaiting confirmation; retry.", file=sys.stderr)
                return 1
            current_spec, error = task_discard_spec_path(current_meta, task_id)
            if error:
                print(f"Cannot safely discard task: {error}", file=sys.stderr)
                return 1
            current_targets = task_discard_targets(current_path, current_spec, task_id)
            lock_error = task_discard_lock_error(task_id, current_targets)
            if lock_error:
                print(lock_error, file=sys.stderr)
                return 1
            # Keep the task file until all linked state is removed, so a failed
            # cleanup remains visible and can be retried.
            for target in current_targets[:-1]:
                os.remove(target)
            os.remove(current_path)
            write_board(load_tasks())
    except OSError as exc:
        print(f"Could not discard task {task_id}: {exc}", file=sys.stderr)
        return 1
    print(f"Discarded task {task_id}; removed {len(current_targets)} file(s).")
    return 0


def workspace_reset_targets() -> list[str]:
    targets: set[str] = set()
    preserved_names = {".gitkeep", "TEMPLATE.md", "README.md"}
    for directory in (ACTIVE_DIR, DONE_DIR):
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if name not in preserved_names and name.endswith(".md") and os.path.isfile(path):
                    targets.add(path)
    for directory in (
        os.path.join(WORKSPACE, "specs", "active"),
        os.path.join(WORKSPACE, "specs", "done"),
    ):
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if name not in preserved_names and name.endswith(".md") and os.path.isfile(path):
                    targets.add(path)
    decisions_dir = os.path.join(WORKSPACE, "docs", "decisions")
    if os.path.isdir(decisions_dir) and not os.path.islink(decisions_dir):
        for name in os.listdir(decisions_dir):
            path = os.path.join(decisions_dir, name)
            if re.fullmatch(r"\d{4}-.+\.md", name) and os.path.isfile(path):
                targets.add(path)
    for root in (CHECKPOINT_DIR, HANDOFF_DIR, ARTIFACTS_DIR, LOGS_DIR):
        if not os.path.isdir(root):
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            for name in list(directories):
                path = os.path.join(current, name)
                if os.path.islink(path):
                    targets.add(path)
                    directories.remove(name)
            for name in files:
                if name != ".gitkeep":
                    targets.add(os.path.join(current, name))
    if os.path.isfile(COUNTER_PATH):
        targets.add(COUNTER_PATH)
    return sorted(targets)


def reset_lock_files() -> list[str]:
    if not os.path.isdir(LOCKS_DIR):
        return []
    return sorted(
        os.path.join(LOCKS_DIR, name)
        for name in os.listdir(LOCKS_DIR)
        if name.endswith(".lock")
    )


def reset_decisions_dir_error() -> str | None:
    decisions_dir = os.path.join(WORKSPACE, "docs", "decisions")
    if os.path.islink(decisions_dir):
        return "Refusing to reset decision records through a symlinked docs/decisions directory."
    if os.path.exists(decisions_dir) and os.path.realpath(decisions_dir) != os.path.abspath(decisions_dir):
        return "Refusing to reset decision records outside docs/decisions."
    return None


def reset_target_error(targets: list[str]) -> str | None:
    workspace = os.path.realpath(WORKSPACE)
    allowed_roots = [
        ACTIVE_DIR,
        DONE_DIR,
        os.path.join(WORKSPACE, "specs", "active"),
        os.path.join(WORKSPACE, "specs", "done"),
        os.path.join(WORKSPACE, "docs", "decisions"),
        CHECKPOINT_DIR,
        HANDOFF_DIR,
        ARTIFACTS_DIR,
        LOGS_DIR,
        os.path.dirname(COUNTER_PATH),
    ]
    for target in targets:
        resolved = os.path.realpath(target)
        try:
            contained = os.path.commonpath([resolved, workspace]) == workspace
            in_reset_scope = any(
                os.path.commonpath([resolved, os.path.realpath(root)]) == os.path.realpath(root)
                for root in allowed_roots
            )
        except ValueError:
            contained = False
            in_reset_scope = False
        if not contained or not in_reset_scope:
            return f"Refusing to reset a path outside the approved state folders: {target}"
        decisions_dir = os.path.join(WORKSPACE, "docs", "decisions")
        if os.path.dirname(os.path.abspath(target)) == os.path.abspath(decisions_dir):
            if os.path.realpath(os.path.dirname(target)) != os.path.abspath(decisions_dir):
                return f"Refusing to reset a decision record through an unexpected directory: {target}"
            if not re.fullmatch(r"\d{4}-.+\.md", os.path.basename(target)):
                return f"Refusing to reset a non-ADR file in docs/decisions: {target}"
        if not (os.path.isfile(target) or os.path.islink(target)):
            return f"Refusing to reset a non-file path: {target}"
    return None


def cmd_reset(args) -> int:
    if not args.hard:
        print("Specify --hard to reset .ai project task, spec, decision and runtime state.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("Hard reset requires an interactive terminal; no files were changed.", file=sys.stderr)
        return 1
    locks = reset_lock_files()
    if locks:
        print("Hard reset requires all locks to be released. Existing lock files:", file=sys.stderr)
        for path in locks:
            print(f"  {os.path.relpath(path, WORKSPACE)}", file=sys.stderr)
        print("Resolve stale locks with `ai recover --apply`, then retry.", file=sys.stderr)
        return 1
    decisions_error = reset_decisions_dir_error()
    if decisions_error:
        print(decisions_error, file=sys.stderr)
        return 1
    targets = workspace_reset_targets()
    target_error = reset_target_error(targets)
    if target_error:
        print(target_error, file=sys.stderr)
        return 1
    print("Hard reset removes task/spec/decision records, checkpoints, handoffs,")
    print("artifacts, logs and the task counter. It keeps framework docs and Git history.")
    print(f"Files to remove: {len(targets)}")
    expected = "reset .ai hard"
    try:
        confirmation = input(f"Type '{expected}' to continue: ").strip()
    except EOFError:
        confirmation = ""
    if confirmation != expected:
        print("Confirmation did not match; no files were changed.", file=sys.stderr)
        return 1

    resource = "project"
    agent = "operator-reset"
    result = acquire_lock(resource, agent=agent, task=None, ttl=600)
    if not result["ok"]:
        holder = result["holder"] or {}
        print(
            f"Could not start reset; '{resource}' overlaps a lock held by "
            f"{holder.get('agent')} ({holder.get('resource')}).",
            file=sys.stderr,
        )
        return 1
    try:
        unexpected_locks = [path for path in reset_lock_files() if os.path.basename(path) != safe_name(resource) + ".lock"]
        if unexpected_locks:
            print("A lock appeared during confirmation; reset cancelled.", file=sys.stderr)
            return 1
        decisions_error = reset_decisions_dir_error()
        if decisions_error:
            print(decisions_error, file=sys.stderr)
            return 1
        targets = workspace_reset_targets()
        target_error = reset_target_error(targets)
        if target_error:
            print(target_error, file=sys.stderr)
            return 1
        removed = 0
        try:
            for target in targets:
                if os.path.islink(target) and os.path.isdir(target):
                    os.rmdir(target)
                else:
                    os.remove(target)
                removed += 1
        finally:
            # Keep the board accurate even if the operator needs to retry after
            # a partial filesystem failure.
            write_board(load_tasks())
        print(f"Hard reset complete; removed {removed} file(s).")
        return 0
    except OSError as exc:
        print(f"Hard reset stopped after a partial cleanup: {exc}. Run `ai reset --hard` again.", file=sys.stderr)
        return 1
    finally:
        release_lock(resource, agent=agent)


def resolve_task_id(task_id: str | None) -> str | None:
    if task_id:
        path = find_task(task_id)
        return str(parse_task(path)[0].get("id")) if path else None
    active = [task for task in load_tasks() if task["_folder"] == "active"]
    if not active:
        return None
    active.sort(key=lambda item: str(item.get("updated") or ""), reverse=True)
    return str(active[0].get("id"))


CHECKPOINT_SECTIONS = {
    "objective": "objective",
    "status": "status",
    "done": "done",
    "in progress": "in_progress",
    "next steps": "next",
    "decisions": "decisions",
    "do not": "do_not",
    "open questions": "questions",
    "files": "files_text",
    "verification": "verification",
}


def checkpoint_sections(task_id: str) -> dict:
    data = read_checkpoint(task_id)
    if not data:
        return {}
    sections: dict[str, str] = {}
    current = None
    for line in data[1].splitlines():
        if line.startswith("## "):
            current = CHECKPOINT_SECTIONS.get(line[3:].strip().lower())
            if current:
                sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return {
        key: "\n".join(
            line for line in value.splitlines() if not line.strip().startswith("<!--")
        ).strip()
        for key, value in sections.items()
    }


def merge_existing_checkpoint(task_id: str, args) -> None:
    explicit_files = bool(getattr(args, "files", None))
    explicit_files_text = bool(getattr(args, "files_text", None))
    existing = checkpoint_sections(task_id)
    for key in (
        "objective", "status", "done", "in_progress", "next",
        "decisions", "do_not", "questions", "files_text", "verification",
    ):
        if not getattr(args, key, None) and existing.get(key):
            setattr(args, key, existing[key])
    if explicit_files and not explicit_files_text:
        args.files_text = None
    if getattr(args, "percent", None) is None:
        data = read_checkpoint(task_id)
        if data:
            args.percent = data[0].get("percent")
    if not getattr(args, "files", None):
        data = read_checkpoint(task_id)
        if data:
            saved = data[2].get("files") or {}
            if saved:
                args.files = ",".join(sorted(saved))


def cmd_checkpoint(args) -> int:
    task_id = resolve_task_id(args.task_id)
    if not task_id:
        print("No task to checkpoint. Create or claim a task first.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            path = find_task(task_id)
            if not path:
                print(f"No task with id {task_id}.", file=sys.stderr)
                return 1
            meta, body = parse_task(path)
            if meta.get("owner") and meta.get("owner") != args.agent and not args.force:
                print(
                    f"Task {task_id} is owned by {meta.get('owner')}. Use --force to checkpoint anyway.",
                    file=sys.stderr,
                )
                return 1
            merge_existing_checkpoint(task_id, args)
            files = [item.strip() for item in (args.files or "").split(",") if item.strip()]
            fields = {
                "title": meta.get("title"),
                "objective": args.objective,
                "status": args.status,
                "done": args.done,
                "in_progress": args.in_progress,
                "next": args.next,
                "decisions": args.decisions,
                "do_not": args.do_not,
                "questions": args.questions,
                "files": files,
                "files_text": args.files_text,
                "verification": args.verification,
                "status_line": meta.get("status"),
            }
            checkpoint = write_checkpoint(task_id, args.agent, args.reason, args.percent, fields)
            meta["updated"] = iso()
            reason = args.reason
            body = body.rstrip("\n") + f"\n- {iso()} checkpoint by {args.agent} ({reason}, {args.percent or '?'}%)\n"
            write_task(path, meta, body)
    except RuntimeError as exc:
        print(f"Cannot checkpoint task {task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Checkpoint: {ws_rel(checkpoint)}")
    if args.next:
        print(f"Next: {args.next}")
    print(f"Resume later with: ai resume {task_id}")
    return 0


def cmd_handoff(args) -> int:
    task_id = resolve_task_id(args.task_id)
    if not task_id:
        print("No task to hand off.", file=sys.stderr)
        return 1
    try:
        with workspace_state_guard():
            path = find_task(task_id)
            if not path:
                print(f"No task with id {task_id}.", file=sys.stderr)
                return 1
            meta, body = parse_task(path)
            if meta.get("owner") and meta.get("owner") != args.agent:
                print(f"Task {task_id} is owned by {meta.get('owner')}.", file=sys.stderr)
                return 1
            merge_existing_checkpoint(task_id, args)
            fields = {
                "title": meta.get("title"),
                "objective": args.objective,
                "status": args.status,
                "done": args.done,
                "in_progress": args.in_progress,
                "next": args.next,
                "decisions": args.decisions,
                "do_not": args.do_not,
                "questions": args.questions,
                "files": [item.strip() for item in (args.files or "").split(",") if item.strip()],
                "files_text": args.files_text,
                "verification": args.verification,
                "status_line": meta.get("status"),
            }
            checkpoint = write_checkpoint(task_id, args.agent, "handoff", args.percent, fields)
            write_json_atomic(
                handoff_marker(task_id),
                {
                    "task": task_id,
                    "agent": args.agent,
                    "reason": args.reason,
                    "created": iso(),
                    "checkpoint": os.path.relpath(checkpoint, WORKSPACE),
                },
            )
            meta["updated"] = iso()
            body = body.rstrip("\n") + f"\n- {iso()} handoff requested by {args.agent}: {args.reason}\n"
            write_task(path, meta, body)
    except RuntimeError as exc:
        print(f"Cannot hand off task {task_id}: {exc}.", file=sys.stderr)
        return 1
    print(f"Handoff marker: {ws_rel(handoff_marker(task_id))}")
    print(f"Checkpoint:     {ws_rel(checkpoint)}")
    print("\nPaste this into the next agent:\n")
    print(resume_prompt(task_id))
    return 0


def current_drift(task_id: str) -> dict:
    data = read_checkpoint(task_id)
    if not data:
        return {"checkpoint": False}
    meta, _, sidecar = data
    current = git_state()
    saved_git = sidecar.get("git") or {}
    drift = {
        "checkpoint": True,
        "branch": current.get("branch"),
        "head": current.get("head"),
        "dirty": current.get("dirty", []),
        "commits_since": None,
        "files": {},
    }
    old_head = saved_git.get("head")
    if old_head and current.get("head") and old_head != current["head"]:
        code, count, _ = run_git(["rev-list", "--count", f"{old_head}..{current['head']}"])
        if code == 0 and count.isdigit():
            drift["commits_since"] = int(count)
    for rel, fingerprint in (sidecar.get("files") or {}).items():
        now_fingerprint = fingerprint_file(rel)
        if now_fingerprint is None:
            drift["files"][rel] = "gone"
        elif now_fingerprint.get("sha256") and fingerprint.get("sha256"):
            drift["files"][rel] = "verified" if now_fingerprint["sha256"] == fingerprint["sha256"] else "changed"
        elif now_fingerprint.get("mtime_ns") is not None and fingerprint.get("mtime_ns") is not None:
            same = (
                now_fingerprint.get("mtime_ns") == fingerprint.get("mtime_ns")
                and now_fingerprint.get("size") == fingerprint.get("size")
            )
            drift["files"][rel] = "verified" if same else "changed"
        else:
            drift["files"][rel] = "unknown"
    return drift


def resume_prompt(task_id: str) -> str:
    path = find_task(task_id)
    prefix = ws_prefix()
    rel = ws_rel(path) if path else f"{prefix}tasks/active/{task_id}-..."
    checkpoint = ws_rel(checkpoint_path(task_id))
    cli = f"{prefix}scripts/ai"
    return f"""You are resuming task {task_id} in the .ai engineering workspace.

1. Read {prefix}AGENTS.md, {prefix}GUIDE.md and {prefix}docs/task-flow.md.
2. Read {rel} and {checkpoint}.
3. Verify the real repository state before trusting the checkpoint (git status, git log, tests).
4. Claim or refresh ownership: `{cli} task claim {task_id} --agent <name>` (or `{cli} lock heartbeat task-{task_id}`).
5. Continue from the first unchecked item in "Next steps". Do not redo "Done" items.
6. Checkpoint at the next milestone, and always before your context window fills: `{cli} checkpoint {task_id} --agent <name>`.
7. Never call it done without `{cli} check`.
"""


def cmd_resume(args) -> int:
    task_id = resolve_task_id(args.task_id)
    if not task_id:
        print("No task to resume.", file=sys.stderr)
        return 1
    path = find_task(task_id)
    meta, body = parse_task(path)
    data = read_checkpoint(task_id)
    drift = current_drift(task_id)
    markers = [marker for marker in list_handoff_markers() if str(marker.get("task")) == task_id]
    payload = {
        "task": meta,
        "checkpoint": data[0] if data else None,
        "checkpoint_body": data[1] if data else None,
        "drift": drift,
        "handoff": markers,
        "prompt": resume_prompt(task_id),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0
    print(f"Task      : {task_id} - {meta.get('title')}")
    print(f"Status    : {meta.get('status')} (owner {meta.get('owner') or '-'})")
    print(f"Spec      : {meta.get('spec') or '-'}")
    print(f"File      : {ws_rel(path)}")
    print(f"Checkpoint: {ws_rel(checkpoint_path(task_id)) if data else 'none'}")
    if markers:
        print(f"Handoff   : requested by {markers[0].get('agent')} ({markers[0].get('reason')})")
    print()
    if data:
        checkpoint_meta, checkpoint_body, _ = data
        print(f"Checkpoint age: {int(checkpoint_age_minutes(task_id) or 0)} min ({checkpoint_meta.get('reason')})")
        print(f"Next (saved)  : {checkpoint_meta.get('next') or '-'}")
        print()
        print(checkpoint_body.strip())
        print()
    else:
        print("No checkpoint yet. The task body is the only saved context.")
        print()
        print(body.strip())
        print()
    if drift.get("checkpoint"):
        changed = [rel for rel, status in drift.get("files", {}).items() if status != "verified"]
        print("Drift:")
        print(f"  branch: {drift.get('branch')} | head: {str(drift.get('head'))[:8]}")
        if drift.get("commits_since") is not None:
            print(f"  commits since checkpoint: {drift['commits_since']}")
        print(f"  files needing attention: {', '.join(changed) if changed else 'none'}")
        print()
    print("Resume prompt:")
    print("-" * 60)
    print(resume_prompt(task_id).strip())
    print("-" * 60)
    return 0


def cmd_recover(args) -> int:
    if not args.apply:
        return cmd_recover_inner(args)
    try:
        with workspace_state_guard():
            return cmd_recover_inner(args)
    except RuntimeError as exc:
        print(f"Cannot apply recovery while {exc}.", file=sys.stderr)
        return 1


def cmd_recover_inner(args) -> int:
    actions: list[tuple[str, str]] = []
    repairs = []
    handled_locks: set[str] = set()

    tasks = load_tasks()
    _, stale_after = lock_settings()
    locks = {
        str(lock.get("resource")): lock
        for lock in list_locks()
        if not lock_is_stale(lock, stale_after)
    }
    for task in tasks:
        task_id = str(task.get("id"))
        path = task["_path"]
        status = task.get("status")
        owner = task.get("owner")
        resource = f"task-{task_id}"
        lock = locks.get(resource)
        if task["_folder"] == "active" and status == "done":
            actions.append((f"move task {task_id} active -> done", "status is done but file is in active/"))
            repairs.append(lambda p=path: os.replace(p, os.path.join(DONE_DIR, os.path.basename(p))))
            if lock:
                handled_locks.add(resource)
                repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))
        if task["_folder"] == "done" and status != "done":
            actions.append((f"set task {task_id} status done", "file is in done/"))
            def fix_status(p=path, m=task):
                meta, body = parse_task(p)
                meta["status"] = "done"
                meta["updated"] = iso()
                write_task(p, meta, body)
            repairs.append(fix_status)
        if task["_folder"] == "active" and owner and not lock:
            actions.append((f"clear stale owner on {task_id}", f"owner '{owner}' has no lock"))
            def fix_owner(p=path):
                meta, body = parse_task(p)
                meta["owner"] = None
                meta["lock"] = None
                if meta.get("status") == "in_progress":
                    meta["status"] = "todo"
                meta["updated"] = iso()
                write_task(p, meta, body)
            repairs.append(fix_owner)
        if task["_folder"] == "active" and lock and not owner:
            actions.append((f"restore owner on {task_id}", f"lock held by {lock.get('agent')}"))
            def fix_owner2(p=path, agent=lock.get("agent"), res=resource):
                meta, body = parse_task(p)
                meta["owner"] = agent
                meta["lock"] = res
                meta["updated"] = iso()
                write_task(p, meta, body)
            repairs.append(fix_owner2)
        if task["_folder"] == "done" and lock:
            actions.append((f"release lock {resource}", "task is done"))
            handled_locks.add(resource)
            repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))

    known = {str(task.get("id")) for task in tasks}
    for resource in list(locks):
        if resource.startswith("task-") and resource[5:] not in known:
            actions.append((f"remove orphan lock {resource}", "no task file"))
            handled_locks.add(resource)
            repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))

    for lock in list_locks():
        resource = str(lock.get("resource"))
        if resource in handled_locks:
            continue
        if lock_is_stale(lock, stale_after):
            actions.append((f"remove stale lock {resource}", f"held by {lock.get('agent')}"))
            handled_locks.add(resource)
            repairs.append(lambda res=resource: os.remove(os.path.join(LOCKS_DIR, safe_name(res) + ".lock")))

    for marker in list_handoff_markers():
        task_id = str(marker.get("task"))
        path = find_task(task_id)
        if not path or os.path.dirname(path) == DONE_DIR:
            actions.append((f"remove orphan handoff marker for {task_id}", "task is gone or done"))
            repairs.append(lambda p=os.path.join(HANDOFF_DIR, marker["_file"]): os.remove(p))

    if args.json:
        print(json.dumps({"actions": [action for action, _ in actions], "applied": args.apply}, indent=2))
        if not args.apply:
            return 0
    if not actions:
        print("No inconsistencies found.")
        return 0
    for action, reason in actions:
        print(f"{'FIX' if args.apply else 'FIND'}  {action}  ({reason})")
    if not args.apply:
        print("\nRun `ai recover --apply` to repair these.")
        return 0
    for repair in repairs:
        try:
            repair()
        except OSError as exc:
            print(f"WARN  could not apply repair: {exc}", file=sys.stderr)
    if not args.json:
        print("\nRecovery applied. Run `ai check`.")
    return 0


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


def cmd_git_setup(args) -> int:
    state = git_state()
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
        code, _, err = run_git(["init"])
        if code != 0:
            print(f"Could not initialize Git in {PROJECT}: {err}", file=sys.stderr)
            return 1
        code, _, err = run_git(["symbolic-ref", "HEAD", f"refs/heads/{git_config()['production']}"])
        if code != 0:
            print(f"Could not select the production branch: {err}", file=sys.stderr)
            return 1
        initialized = True
        state = git_state()
        if not state.get("repo"):
            print(f"Git initialization did not produce a readable repository: {state.get('error') or 'unknown error'}", file=sys.stderr)
            return 1
    config = git_config()
    template = git_template_path()
    if not os.path.isfile(template):
        print(f"Commit template not found: {os.path.relpath(template, PROJECT)}", file=sys.stderr)
        return 1
    code, _, err = run_git(["config", "--local", "commit.template", template])
    if code != 0:
        print(f"Could not set commit.template: {err}", file=sys.stderr)
        return 1
    created_production = False
    created_integration = False
    created_baseline = False
    if not state.get("head"):
        refs_code, refs_output, refs_err = run_git([
            "for-each-ref", "--format=%(refname:short)", "refs/heads",
        ])
        if refs_code != 0:
            print(f"Could not inspect local Git branches: {refs_err}", file=sys.stderr)
            return 1
        refs = [line for line in refs_output.splitlines() if line]
        if branch_exists(config["production"]):
            pass
        elif refs:
            base = state.get("branch") if state.get("branch") in refs else refs[0]
            code, _, err = run_git(["branch", config["production"], base])
            if code != 0:
                print(f"Could not create production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            created_production = True
        else:
            code, _, err = run_git(["symbolic-ref", "HEAD", f"refs/heads/{config['production']}"])
            if code != 0:
                print(f"Could not select production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            completed, result = confirm_initial_baseline(args, config["production"])
            if not completed:
                return result
            created_baseline = True
            created_production = True
        if not branch_exists(config["production"]):
            print(f"Production branch '{config['production']}' is still missing.", file=sys.stderr)
            return 1
        state = git_state()
        if not state.get("head"):
            code, _, err = run_git(["symbolic-ref", "HEAD", f"refs/heads/{config['production']}"])
            if code != 0:
                print(f"Could not select production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            state = git_state()
        if not state.get("head"):
            print("Gitflow setup could not establish a committed production base.", file=sys.stderr)
            return 1
    elif not branch_exists(config["production"]):
        base = state.get("branch")
        if not base or base == "detached":
            base = "HEAD"
        code, _, err = run_git(["branch", config["production"], base])
        if code != 0:
            print(f"Could not create production branch '{config['production']}': {err}", file=sys.stderr)
            return 1
        created_production = True
    if not branch_exists(config["integration"]):
        code, _, err = run_git(["branch", config["integration"], config["production"]])
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
    path = find_task(args.task)
    if not path:
        print(f"No task with id {args.task}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) != ACTIVE_DIR:
        print("The task is already in done/. Start a branch before finishing it.", file=sys.stderr)
        return 1
    meta, body = parse_task(path)
    task_id = str(meta.get("id"))
    owner_error = task_owner_error(meta, args.agent, args.force)
    if owner_error:
        print(owner_error, file=sys.stderr)
        return 1
    state = git_state()
    if not state.get("repo"):
        print("Not a git repository.", file=sys.stderr)
        return 1
    if not git_clean():
        print("Working tree is dirty. Commit or stash before starting a task branch.", file=sys.stderr)
        return 1
    config = git_config()
    branch_type = args.type
    if branch_type not in config["branchTypes"]:
        print(
            f"Unknown branch type '{branch_type}'. Use one of: {', '.join(config['branchTypes'])}.",
            file=sys.stderr,
        )
        return 1
    if not branch_exists(config["integration"]):
        print(f"Integration branch '{config['integration']}' is missing. Run `ai git setup`.", file=sys.stderr)
        return 1
    base = args.base or (
        config["production"] if branch_type == "hotfix" else config["integration"]
    )
    if not branch_exists(base):
        print(f"Base branch '{base}' does not exist.", file=sys.stderr)
        return 1
    branch = task_branch_name(meta, branch_type)
    ok, owned, error = acquire_git_guard(args.agent, task_id)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
        current = git_state().get("branch")
        if branch_exists(branch):
            if current != branch:
                code, _, err = run_git(["checkout", branch])
                if code != 0:
                    print(f"Could not switch to {branch}: {err}", file=sys.stderr)
                    return 1
            action = "switched to"
        else:
            code, _, err = run_git(["checkout", "-b", branch, base])
            if code != 0:
                print(f"Could not create {branch}: {err}", file=sys.stderr)
                return 1
            action = "created"
        meta["branch"] = branch
        meta["updated"] = iso()
        body = body.rstrip("\n") + f"\n- {iso()} {action} branch {branch} from {base} by {args.agent}\n"
        write_task(path, meta, body)
        write_board(load_tasks())
    finally:
        release_git_guard(owned, args.agent)
    if args.json:
        print(json.dumps({"task": task_id, "branch": branch, "base": base, "action": action}, indent=2))
    else:
        print(f"{action.capitalize()} {branch} from {base}.")
        print(f"Task {task_id} now points at that branch. Commit only files you own.")
    return 0


def cmd_git_commit(args) -> int:
    path = find_task(args.task)
    if not path:
        print(f"No task with id {args.task}.", file=sys.stderr)
        return 1
    if os.path.dirname(path) != ACTIVE_DIR:
        print("The task is already in done/; no commit is needed.", file=sys.stderr)
        return 1
    meta, body = parse_task(path)
    task_id = str(meta.get("id"))
    owner_error = task_owner_error(meta, args.agent, args.force)
    if owner_error:
        print(owner_error, file=sys.stderr)
        return 1
    branch = str(meta.get("branch") or "")
    if not branch:
        print(f"Task {task_id} has no branch. Run `ai git start --task {task_id} --agent {args.agent}`.", file=sys.stderr)
        return 1
    current = git_state().get("branch")
    if current != branch:
        print(f"Current branch is {current}, but task {task_id} uses {branch}.", file=sys.stderr)
        return 1
    if args.type not in COMMIT_TYPES:
        print(f"Unknown commit type '{args.type}'. Use one of: {', '.join(COMMIT_TYPES)}.", file=sys.stderr)
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
    state = git_state()
    if not state.get("staged") and not args.allow_empty:
        print("Nothing is staged. Stage only the files you own, then retry.", file=sys.stderr)
        return 1
    if args.verify:
        uncovered, _ = uncovered_staged(state)
        if uncovered:
            print("Refusing commit; staged paths have no held file lock:", file=sys.stderr)
            for item in uncovered:
                print(f"  {item}", file=sys.stderr)
            return 1
    ok, owned, error = acquire_git_guard(args.agent, task_id)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    try:
        trailers = f"Task: {task_id}\nAgent: {args.agent}"
        body_text = (args.body.strip() + "\n\n" + trailers) if args.body else trailers
        commit_args = ["commit", "-m", subject, "-m", body_text]
        if args.allow_empty:
            commit_args.append("--allow-empty")
        code, _, err = run_git(commit_args)
        if code != 0:
            print(f"git commit failed: {err}", file=sys.stderr)
            return 1
        _, short, _ = run_git(["rev-parse", "--short", "HEAD"])
        meta["updated"] = iso()
        body = body.rstrip("\n") + f"\n- {iso()} committed: {subject}\n"
        write_task(path, meta, body)
        write_board(load_tasks())
        amended = commit_task_metadata(path, "", amend=True)
        if amended:
            short = amended
    finally:
        release_git_guard(owned, args.agent)
    if args.json:
        print(json.dumps({"task": task_id, "branch": branch, "commit": short, "subject": subject}, indent=2))
    else:
        print(f"{short} {subject}")
    return 0


def cmd_git_finish(args) -> int:
    path = find_task(args.task)
    if not path:
        print(f"No task with id {args.task}.", file=sys.stderr)
        return 1
    meta, body = parse_task(path)
    task_id = str(meta.get("id"))
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
    state = git_state()
    if state.get("dirty"):
        print("Working tree is dirty. Commit or stash before merging.", file=sys.stderr)
        return 1
    if not branch_exists(branch):
        print(f"Task branch '{branch}' does not exist.", file=sys.stderr)
        return 1
    config = git_config()
    integration = config["integration"]
    if not branch_exists(integration):
        print(f"Integration branch '{integration}' is missing. Run `ai git setup`.", file=sys.stderr)
        return 1
    ok, owned, error = acquire_git_guard(args.agent, task_id)
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
        current = git_state().get("branch")
        if current != branch:
            code, _, err = run_git(["checkout", branch])
            if code != 0:
                print(f"Could not switch to {branch}: {err}", file=sys.stderr)
                return 1
        code, _, err = run_git(["checkout", integration])
        if code != 0:
            print(f"Could not switch to {integration}: {err}", file=sys.stderr)
            return 1
        merge_message = f"merge: {branch} ({task_id})"
        code, _, err = run_git(["merge", "--no-ff", branch, "-m", merge_message])
        if code != 0:
            run_git(["merge", "--abort"])
            print(f"Merge failed and was aborted: {err}", file=sys.stderr)
            return 1
        _, merged_head, _ = run_git(["rev-parse", "--short", "HEAD"])
        deleted = False
        if config["deleteAfterMerge"]:
            code, _, err = run_git(["branch", "-d", branch])
            if code == 0:
                deleted = True
            else:
                print(f"WARN  merged, but could not delete {branch}: {err}", file=sys.stderr)
            meta["branch"] = None
        meta["merged_into"] = integration
        meta["merged_at"] = iso()
        meta["updated"] = iso()
        body = body.rstrip("\n") + f"\n- {iso()} merged {branch} into {integration} by {args.agent}\n"
        write_task(path, meta, body)
        write_board(load_tasks())
        commit_task_metadata(path, f"chore(task): record merge {task_id}")
    finally:
        release_git_guard(owned, args.agent)
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


def cmd_git(args) -> int:
    if args.action == "setup":
        return cmd_git_setup(args)
    if args.action == "start":
        return cmd_git_start(args)
    if args.action == "commit":
        return cmd_git_commit(args)
    if args.action == "finish":
        return cmd_git_finish(args)
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
    state = git_state()
    if not state.get("repo"):
        print("Not a git repository; nothing to verify.")
        return 0
    uncovered, locks = uncovered_staged(state)
    if args.json:
        print(json.dumps({"staged": state.get("staged", []), "uncovered": uncovered, "locks": locks}, indent=2))
    else:
        if uncovered:
            print("Staged paths with no held file lock:")
            for path in uncovered:
                print(f"  {path}")
        else:
            print("All staged paths are covered by a held lock.")
    return 1 if (args.strict and uncovered) else 0


def resolve_spec_path(meta: dict | None) -> str | None:
    if not meta:
        return None
    spec = meta.get("spec")
    if not spec:
        return None
    spec = str(spec).strip()
    candidates = []
    if os.path.isabs(spec):
        candidates.append(spec)
    else:
        candidates.extend([os.path.join(PROJECT, spec), os.path.join(WORKSPACE, spec)])
    if re.fullmatch(r"\d{1,4}", spec):
        prefix = normalize_id(spec) + "-"
        for folder in ("active", "done"):
            directory = os.path.join(WORKSPACE, "specs", folder)
            if os.path.isdir(directory):
                for name in sorted(os.listdir(directory)):
                    if name.startswith(prefix) and name.endswith(".md"):
                        candidates.append(os.path.join(directory, name))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def cmd_brief(args) -> int:
    config = load_config()
    tasks = load_tasks()
    active = [task for task in tasks if task["_folder"] == "active"]
    task_id = resolve_task_id(args.task_id)
    meta = body = None
    task_path = None
    if task_id:
        task_path = find_task(task_id)
        if task_path:
            meta, body = parse_task(task_path)
    spec_path = resolve_spec_path(meta)
    checkpoint = read_checkpoint(task_id) if task_id else None
    state = git_state()
    cli = "ai"

    lines = [
        "=== .ai WORKSPACE BRIEF ===",
        f"Generated: {iso()}",
        f"Project:   {os.path.basename(PROJECT)}",
        f"Workspace: {ws_prefix() or './'}",
        f"Mode:      {config.get('mode')}",
        "",
        "You are an external assistant. You may not have filesystem or shell access.",
        "Never claim that you ran a command, test or check. Ask the human to run the",
        "commands below and paste the output back. Keep every AI-generated note, spec",
        "or scratch file inside the .ai workspace; the rest of the repository is",
        "product code.",
        "",
        "--- Operating rules ---",
        "1. One task per session. Claim it before editing anything.",
        "2. Lease the files or subsystem you will touch; a live lease is a refusal.",
        "3. A behavior change needs a spec with testable acceptance criteria.",
        "4. The producer never reviews its own work.",
        "5. Work is done only when `ai check` is green and its output is recorded.",
        "6. Checkpoint at milestones and before the context window fills.",
        f"7. Record lasting decisions as an ADR under {ws_prefix()}docs/decisions/.",
        "8. Every file-changing task must use Gitflow unless the user explicitly says not to use Git. Run `ai git setup`; it initializes Git and asks before an initial commit.",
        "9. After claim, run `ai git start` before editing; stop if setup or branch creation fails. Commit with `ai git commit`; a different reviewer must merge with `ai git finish` before done. Read-only work needs no branch.",
        "",
    ]

    if meta:
        lines += [
            "--- Current task ---",
            f"ID:         {meta.get('id')}",
            f"Title:      {meta.get('title')}",
            f"Status:     {meta.get('status')}",
            f"Owner:      {meta.get('owner') or '-'}",
            f"Priority:   {meta.get('priority') or '-'}",
            f"Spec:       {ws_rel(spec_path) if spec_path else (meta.get('spec') or 'none')}",
            f"Depends on: {meta.get('depends_on') or '-'}",
            f"File:       {ws_rel(task_path)}",
            "",
            (body or "(task body is empty)").strip(),
            "",
        ]
    else:
        lines += [
            "--- Current task ---",
            "No active task selected." if not active else "No task id was given. Active tasks:",
        ]
        for item in active:
            lines.append(f"- {item.get('id')} [{item.get('status')}] {item.get('title')} (owner: {item.get('owner') or '-'})")
        lines.append("")

    lines += ["--- Spec ---"]
    if spec_path:
        lines += [f"File: {ws_rel(spec_path)}", "", read_text(spec_path).strip(), ""]
    else:
        lines += ["No spec is linked to this task.", ""]

    lines += ["--- Last checkpoint ---"]
    if checkpoint:
        lines += [
            f"Created: {checkpoint[0].get('created')}",
            f"Reason:  {checkpoint[0].get('reason')}",
            f"Next:    {checkpoint[0].get('next') or '-'}",
            "",
            checkpoint[1].strip(),
            "",
        ]
    else:
        lines += ["No checkpoint exists.", ""]

    lines += ["--- Repository state ---"]
    lines.append(f"Branch: {state.get('branch') or '-'}")
    lines.append(f"HEAD:   {state.get('head') or '-'}")
    dirty = state.get("dirty") or []
    if dirty:
        lines.append("Uncommitted paths:")
        for path in dirty[:20]:
            lines.append(f"- {path}")
        if len(dirty) > 20:
            lines.append(f"- ... {len(dirty) - 20} more")
    else:
        lines.append("Working tree is clean.")
    lines += [
        "",
        "--- How to answer ---",
        "- If the human asks for implementation: give a short plan first, then minimal",
        "  patches or diffs and exact commands. Do not invent file contents.",
        "- Tie every change to an acceptance criterion. Flag ambiguity before coding.",
        "- Mark anything you could not verify as unverified.",
        "",
        "--- Commands available to the human ---",
        f"{cli} doctor",
        f"{cli} status",
        f"{cli} task show <id>",
        f"{cli} task claim <id> --agent <name>",
        f"{cli} lock acquire <path> --agent <name> --task <id>",
        f"{cli} checkpoint <id> --agent <name> --next \"...\"",
        f"{cli} check --strict",
        f"{cli} task done <id> --agent <name>",
        "",
        "=== END BRIEF ===",
    ]

    text = "\n".join(lines)
    if args.max_chars and len(text) > args.max_chars:
        text = text[: args.max_chars].rstrip() + "\n\n[truncated by ai brief]\n=== END BRIEF ==="
    if args.json:
        print(json.dumps({
            "project": os.path.basename(PROJECT),
            "workspace": ws_prefix() or "./",
            "mode": config.get("mode"),
            "task": meta,
            "task_body": body,
            "spec_path": ws_rel(spec_path) if spec_path else None,
            "spec_body": read_text(spec_path) if spec_path else None,
            "checkpoint": checkpoint[0] if checkpoint else None,
            "checkpoint_body": checkpoint[1] if checkpoint else None,
            "git": state,
            "brief": text,
        }, indent=2, default=str))
        return 0
    print(text)
    return 0


CAPABILITIES = {
    "name": "ai",
    "version": VERSION,
    "workspace": ".ai",
    "exit_codes": {"0": "success", "1": "check failed or operation refused", "127": "python 3 not found"},
    "state": {
        "tasks": "tasks/active, tasks/done",
        "locks": "runtime/locks/*.lock (advisory, TTL leases)",
        "checkpoints": "runtime/state/checkpoints",
        "handoffs": "runtime/state/handoff",
        "artifacts": "runtime/artifacts",
    },
    "commands": {
        "adopt": "wire root adapters for every AI tool",
        "doctor": "workspace health; --strict, --json",
        "check": "single verification contract; --fast, --strict, --json",
        "status": "tasks, locks, checkpoints, handoffs; --json",
        "reset": "--hard: interactively clear task/spec/decision/runtime state; preserves framework files",
        "task": "new | list | show | ready | next | claim | release | review | done | discard | block | unblock",
        "lock": "acquire | release | heartbeat | status",
        "checkpoint": "save resumable context",
        "resume": "print a compact resume brief with drift",
        "brief": "print a paste-ready brief for an external chat AI",
        "handoff": "write a marker and checkpoint for another agent",
        "recover": "detect or repair inconsistent state; --apply, --json",
        "git": "setup | start | commit | finish | begin | end | verify",
        "artifact": "put | list | clean",
        "clean": "remove stale locks and logs",
        "capabilities": "this contract",
    },
    "rules": [
        "one task per agent session",
        "claim before editing",
        "live lock is a refusal",
        "producer never verifies its own work",
        "checkpoint before the context window fills",
        "done requires ai check",
    ],
}


def cmd_capabilities(args) -> int:
    print(json.dumps(CAPABILITIES, indent=2))
    return 0


def cmd_lock(args) -> int:
    if args.action == "acquire":
        result = acquire_lock(
            args.resource,
            agent=args.agent,
            task=args.task,
            ttl=args.ttl,
            force=args.force,
        )
        if result["ok"]:
            print(f"Acquired '{args.resource}' for {args.agent}.")
            return 0
        holder = result["holder"] or {}
        print(
            f"'{args.resource}' is held by {holder.get('agent')} "
            f"(task {holder.get('task') or '-'}, since {holder.get('started_at')}).",
            file=sys.stderr,
        )
        return 1
    if args.action == "release":
        return release_lock(args.resource, agent=args.agent, force=args.force)
    if args.action == "heartbeat":
        return heartbeat_lock(args.resource, agent=args.agent)
    locks = list_locks()
    if getattr(args, "json", False):
        print(json.dumps(locks, indent=2, default=str))
        return 0
    print_lock_table(locks)
    return 0


def cmd_artifact(args) -> int:
    if args.action in ("put", "clean"):
        try:
            with workspace_state_guard():
                return cmd_artifact_inner(args)
        except RuntimeError as exc:
            print(f"Cannot update artifacts: {exc}.", file=sys.stderr)
            return 1
    return cmd_artifact_inner(args)


def cmd_artifact_inner(args) -> int:
    ensure_dirs()
    manifest = read_json(MANIFEST_PATH) or []
    if args.action == "put":
        source = os.path.abspath(args.path)
        if not os.path.exists(source):
            print(f"No such path: {args.path}", file=sys.stderr)
            return 1
        workspace_abs = os.path.abspath(WORKSPACE)
        if os.path.commonpath([source, workspace_abs]) == workspace_abs:
            print("Path is already inside the workspace.", file=sys.stderr)
            return 1
        if os.path.commonpath([source, os.path.abspath(PROJECT)]) != os.path.abspath(PROJECT):
            print("Refusing to move paths outside the project.", file=sys.stderr)
            return 1
        stamp = now().strftime("%Y%m%dT%H%M%SZ")
        name = safe_name(os.path.basename(source) or "artifact")
        target = os.path.join(ARTIFACTS_DIR, f"{stamp}-{name}")
        shutil.move(source, target)
        manifest.append(
            {
                "original": os.path.relpath(source, PROJECT),
                "stored": os.path.relpath(target, WORKSPACE),
                "reason": args.reason,
                "moved_at": iso(),
                "agent": args.agent,
            }
        )
        write_json_atomic(MANIFEST_PATH, manifest)
        print(f"Quarantined {os.path.relpath(source, PROJECT)} -> {os.path.relpath(target, PROJECT)}")
        return 0
    if args.action == "clean":
        if not args.all:
            print("Pass --all to delete quarantined artifacts.", file=sys.stderr)
            return 1
        for item in manifest:
            target = os.path.join(WORKSPACE, item.get("stored", ""))
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            elif os.path.exists(target):
                os.remove(target)
        write_json_atomic(MANIFEST_PATH, [])
        print("Quarantined artifacts removed.")
        return 0
    if getattr(args, "json", False):
        print(json.dumps(manifest, indent=2, default=str))
        return 0
    if not manifest:
        print("No quarantined artifacts.")
        return 0
    print(f"{'MOVED AT':<22} {'ORIGINAL':<40} REASON")
    for item in manifest:
        print(
            f"{str(item.get('moved_at')):<22} "
            f"{str(item.get('original'))[:40]:<40} {item.get('reason') or '-'}"
        )
    return 0


def cmd_clean(args) -> int:
    removed = 0
    try:
        with workspace_state_guard():
            if args.stale_locks:
                _, stale_after = lock_settings()
                for lock in list_locks():
                    if lock_is_stale(lock, stale_after):
                        try:
                            os.remove(os.path.join(LOCKS_DIR, lock["_file"]))
                            removed += 1
                            print(f"Removed stale lock: {lock.get('resource')}")
                        except OSError:
                            pass
            if args.logs:
                for name in os.listdir(LOGS_DIR):
                    path = os.path.join(LOGS_DIR, name)
                    if os.path.isfile(path) and name != ".gitkeep":
                        os.remove(path)
                        removed += 1
    except RuntimeError as exc:
        print(f"Cannot clean workspace state: {exc}.", file=sys.stderr)
        return 1
    print(f"Cleaned {removed} item(s).")
    return 0


def cmd_version(args) -> int:
    print(f"ai workspace {VERSION}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai",
        description="Local, cross-platform CLI for the .ai engineering workspace.",
    )
    parser.add_argument("--version", action="version", version=f"ai workspace {VERSION}")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="prepare runtime directories and config")
    init.add_argument("--wire", action="store_true", help="also wire the root adapters (same as `ai adopt`)")
    init.set_defaults(func=cmd_init)

    adopt = sub.add_parser("adopt", help="wire the workspace into root AI tool configs")
    adopt.add_argument("--check", action="store_true", help="only report missing root adapters")
    adopt.add_argument("--print", dest="print", action="store_true", help="print the bootstrap prompt")
    adopt.add_argument("--force", action="store_true", help="rewrite managed blocks")
    adopt.add_argument("--ci", action="store_true", help="also write the CI workflow")
    adopt.set_defaults(func=cmd_adopt)

    doctor = sub.add_parser("doctor", help="check workspace health")
    doctor.add_argument("--strict", action="store_true", help="treat warnings as failures")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    check = sub.add_parser("check", help="run the single verification contract")
    check.add_argument("--fast", action="store_true", help="run only fast checks")
    check.add_argument("--no-commands", action="store_true", help="structure/state checks only")
    check.add_argument("--strict", action="store_true", help="treat warnings as failures")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

    status = sub.add_parser("status", help="show tasks, locks, checkpoints, handoffs and artifacts")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    task = sub.add_parser("task", help="manage local tasks")
    task_sub = task.add_subparsers(dest="action", required=True)

    task_new = task_sub.add_parser("new", help="create a task")
    task_new.add_argument("title")
    task_new.add_argument("--priority", default="medium", choices=["low", "medium", "high"])
    task_new.add_argument("--spec", default=None)
    task_new.add_argument("--depends-on", dest="depends_on", default=None)
    task_new.set_defaults(func=cmd_task_new)

    task_list = task_sub.add_parser("list", help="list tasks and refresh the board")
    task_list.add_argument("--all", action="store_true", help="include done tasks")
    task_list.add_argument("--json", action="store_true")
    task_list.set_defaults(func=cmd_task_list)

    task_show = task_sub.add_parser("show", help="print a task")
    task_show.add_argument("task_id")
    task_show.add_argument("--json", action="store_true")
    task_show.set_defaults(func=cmd_task_show)

    task_ready = task_sub.add_parser("ready", help="list claimable tasks whose dependencies are done")
    task_ready.add_argument("--json", action="store_true")
    task_ready.set_defaults(func=cmd_task_ready)

    task_next = task_sub.add_parser("next", help="atomically claim the highest-priority ready task")
    task_next.add_argument("--agent", required=True)
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

    lock = sub.add_parser("lock", help="manage advisory resource locks")
    lock_sub = lock.add_subparsers(dest="action", required=True)

    lock_acquire = lock_sub.add_parser("acquire")
    lock_acquire.add_argument("resource")
    lock_acquire.add_argument("--agent", default="unknown")
    lock_acquire.add_argument("--task", default=None)
    lock_acquire.add_argument("--ttl", type=int, default=None)
    lock_acquire.add_argument("--force", action="store_true")
    lock_acquire.set_defaults(func=cmd_lock)

    lock_release = lock_sub.add_parser("release")
    lock_release.add_argument("resource")
    lock_release.add_argument("--agent", default=None)
    lock_release.add_argument("--force", action="store_true")
    lock_release.set_defaults(func=cmd_lock)

    lock_heartbeat = lock_sub.add_parser("heartbeat")
    lock_heartbeat.add_argument("resource")
    lock_heartbeat.add_argument("--agent", default=None)
    lock_heartbeat.set_defaults(func=cmd_lock)

    lock_status = lock_sub.add_parser("status")
    lock_status.add_argument("--json", action="store_true")
    lock_status.set_defaults(func=cmd_lock)

    def add_checkpoint_flags(command: argparse.ArgumentParser) -> None:
        command.add_argument("task_id", nargs="?", default=None)
        command.add_argument("--agent", required=True)
        command.add_argument("--reason", default="checkpoint")
        command.add_argument("--percent", type=int, default=None)
        command.add_argument("--objective", default=None)
        command.add_argument("--status", default=None)
        command.add_argument("--done", default=None)
        command.add_argument("--in-progress", dest="in_progress", default=None)
        command.add_argument("--next", default=None)
        command.add_argument("--decisions", default=None)
        command.add_argument("--do-not", dest="do_not", default=None)
        command.add_argument("--questions", default=None)
        command.add_argument("--files", default=None, help="comma-separated repo-relative paths")
        command.add_argument("--files-text", dest="files_text", default=None)
        command.add_argument("--verification", default=None)
        command.add_argument("--force", action="store_true")

    checkpoint = sub.add_parser("checkpoint", help="save resumable context for a task")
    add_checkpoint_flags(checkpoint)
    checkpoint.set_defaults(func=cmd_checkpoint)

    handoff = sub.add_parser("handoff", help="checkpoint and mark a task for another agent")
    add_checkpoint_flags(handoff)
    handoff.set_defaults(func=cmd_handoff)

    resume = sub.add_parser("resume", help="print a compact resume brief with drift")
    resume.add_argument("task_id", nargs="?", default=None)
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=cmd_resume)

    brief = sub.add_parser("brief", help="print a paste-ready brief for an external chat AI")
    brief.add_argument("task_id", nargs="?", default=None)
    brief.add_argument("--max-chars", type=int, default=0)
    brief.add_argument("--json", action="store_true")
    brief.set_defaults(func=cmd_brief)

    recover = sub.add_parser("recover", help="detect or repair inconsistent workspace state")
    recover.add_argument("--apply", action="store_true", help="apply the repairs")
    recover.add_argument("--json", action="store_true")
    recover.set_defaults(func=cmd_recover)

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
    git_commit.add_argument("--type", default="feat", choices=COMMIT_TYPES)
    git_commit.add_argument("--scope", default=None)
    git_commit.add_argument("--message", required=True)
    git_commit.add_argument("--body", default="")
    git_commit.add_argument("--allow-empty", action="store_true")
    git_commit.add_argument("--verify", action="store_true", help="require a held lock for each staged path")
    git_commit.add_argument("--force", action="store_true")
    git_commit.add_argument("--json", action="store_true")
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
    git_verify.add_argument("--json", action="store_true")
    git_verify.set_defaults(func=cmd_git)

    capabilities = sub.add_parser("capabilities", help="print the machine-readable CLI contract")
    capabilities.set_defaults(func=cmd_capabilities)

    artifact = sub.add_parser("artifact", help="quarantine AI scratch files")
    artifact_sub = artifact.add_subparsers(dest="action", required=True)

    artifact_put = artifact_sub.add_parser("put")
    artifact_put.add_argument("path")
    artifact_put.add_argument("--reason", default=None)
    artifact_put.add_argument("--agent", default="unknown")
    artifact_put.set_defaults(func=cmd_artifact)

    artifact_list = artifact_sub.add_parser("list")
    artifact_list.add_argument("--json", action="store_true")
    artifact_list.set_defaults(func=cmd_artifact)

    artifact_clean = artifact_sub.add_parser("clean")
    artifact_clean.add_argument("--all", action="store_true")
    artifact_clean.set_defaults(func=cmd_artifact)

    clean = sub.add_parser("clean", help="remove stale locks and logs")
    clean.add_argument("--stale-locks", action="store_true")
    clean.add_argument("--logs", action="store_true")
    clean.set_defaults(func=cmd_clean)

    reset = sub.add_parser("reset", help="reset .ai operational state (interactive operator action)")
    reset.add_argument("--hard", action="store_true", help="remove task/spec/decision/runtime state after confirmation")
    reset.set_defaults(func=cmd_reset)

    version = sub.add_parser("version", help="print the workspace version")
    version.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
