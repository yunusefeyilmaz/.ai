"""runtime.checkpoints: split out of the former monolithic ai.py."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys

from lib.core.paths import (
    CHECKPOINT_ARCHIVE,
    CHECKPOINT_DIR,
    HANDOFF_DIR,
    ws_prefix,
    ws_rel,
)
from lib.core.fsio import (
    CorruptStateError,
    normalize_id,
    read_json,
    write_json_atomic,
)
from lib.core.timeutil import (
    iso,
    now,
    parse_iso,
)
from lib.runtime.dirs import ensure_dirs
from lib.git import repo
from lib.runtime import evidence
from lib.tasks import store


def fingerprint_file(relative: str) -> dict | None:
    path = os.path.join(repo.current_root(), relative.replace("\\", "/"))
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


def list_handoff_markers(ensure: bool = True) -> list[dict]:
    if ensure:
        ensure_dirs()
    if not os.path.isdir(HANDOFF_DIR):
        return []
    items = []
    for name in sorted(os.listdir(HANDOFF_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            payload = read_json(os.path.join(HANDOFF_DIR, name)) or {}
        except CorruptStateError as exc:
            # A handoff marker is a display/queue hint, never a reason to make
            # `ai now` or `ai context` traceback. `ai doctor` reports it.
            print(f"WARN  skipping corrupt handoff file {name}: {exc}", file=sys.stderr)
            continue
        payload["_file"] = name
        items.append(payload)
    return items


def read_checkpoint(task_id: str) -> tuple[dict, str, dict] | None:
    path = checkpoint_path(task_id)
    if not os.path.exists(path):
        return None
    meta, body = store.parse_task(path)
    try:
        sidecar = read_json(checkpoint_sidecar(task_id)) or {}
    except CorruptStateError as exc:
        print(f"WARN  checkpoint sidecar for task {task_id} is corrupt: {exc}", file=sys.stderr)
        sidecar = {}
    return meta, body, sidecar


def sidecar_mismatch(task_id: str) -> str | None:
    """Why a checkpoint's `.json` sidecar does not match its `.md` (None = fine).

    The two files are written one after the other; a crash between them used to
    leave a stale or missing sidecar with nothing to notice or repair it.
    """
    path = checkpoint_path(task_id)
    if not os.path.exists(path):
        return None
    meta, _ = store.parse_task(path)
    sidecar = checkpoint_sidecar(task_id)
    if not os.path.exists(sidecar):
        return f"checkpoint {task_id} has a .md but no sidecar"
    try:
        payload = read_json(sidecar) or {}
    except CorruptStateError as exc:
        return f"checkpoint sidecar {task_id} is corrupt: {exc}"
    if str(payload.get("created") or "") != str(meta.get("created") or ""):
        return f"checkpoint sidecar {task_id} belongs to a different checkpoint"
    return None


def rebuild_sidecar(task_id: str) -> bool:
    """Recreate a checkpoint sidecar from its Markdown when they diverge."""
    path = checkpoint_path(task_id)
    if not os.path.exists(path):
        return False
    meta, _ = store.parse_task(path)
    write_json_atomic(
        checkpoint_sidecar(task_id),
        {
            "task": task_id,
            "created": meta.get("created"),
            "agent": meta.get("agent"),
            "reason": meta.get("reason"),
            "percent": meta.get("percent"),
            "git": {},
            "files": {},
            "rebuilt": True,
        },
    )
    return True


def checkpoint_age_minutes(task_id: str) -> float | None:
    data = read_checkpoint(task_id)
    if not data:
        return None
    meta, _, _ = data
    try:
        return (now() - parse_iso(str(meta.get("created") or ""))).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None


def checkpoint_required(
    task_id: str,
    claimed_at: str | None,
    warn_after_minutes: float | None,
) -> str | None:
    """Return the refusal text when a long-running claim has no fresh checkpoint.

    Delivery is the moment a task changes hands, so a claim older than
    `handoff.warnAfterMinutes` must carry recoverable state. A checkpoint made
    before the current claim does not count: the next agent would resume a
    previous attempt. A fresh task (or a workspace without a claim timestamp)
    is never blocked, so short work needs no busywork.
    """
    if not claimed_at or warn_after_minutes is None:
        return None
    try:
        started = parse_iso(str(claimed_at))
        threshold = float(warn_after_minutes)
    except (TypeError, ValueError):
        return None
    elapsed = (now() - started).total_seconds() / 60.0
    if elapsed <= threshold:
        return None
    data = read_checkpoint(task_id)
    if data:
        try:
            if parse_iso(str(data[0].get("created") or "")) >= started:
                return None
        except (TypeError, ValueError):
            pass
    return (
        f"Task {task_id} has been claimed for {int(elapsed)} minutes without a checkpoint "
        f"(the warn threshold is {int(threshold)} minutes). Save recoverable state first: "
        f'`ai checkpoint {task_id} --agent <name> --next "<step>"`, then deliver again.'
    )


def write_checkpoint(
    task_id: str,
    agent: str,
    reason: str,
    percent: int | None,
    fields: dict,
) -> str:
    ensure_dirs()
    task_id = normalize_id(str(task_id))
    state = repo.git_state()
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
    title = fields.get("title") or "task"
    branch = state.get("branch") or "no branch"
    head = str(state.get("head") or "")
    head_short = head[:8] if head else "no commit"
    status_line = fields.get("status_line") or "in progress"
    # The writer, not the caller, is responsible for recording where the task
    # stands: a checkpoint that only says "in progress" cannot be resumed.
    auto_status = f"{status_line} on branch {branch} at {head_short}."
    auto_next = fields.get("next") or (
        f"Continue task {task_id} ({title}) from the current step; "
        "re-read the task and its spec before editing."
    )
    meta = {
        "task": task_id,
        "agent": agent,
        "created": iso(),
        "reason": reason,
        "percent": percent,
        "branch": state.get("branch"),
        "head": state.get("head"),
        "next": auto_next,
        "status_line": fields.get("status_line"),
    }
    body = f"""# Checkpoint {task_id} - {title}

## Objective

{fields.get('objective') or f'Task {task_id}: {title}'}

## Status

{fields.get('status') or auto_status}

## Done

{fields.get('done') or 'Nothing recorded yet.'}

## In progress

{fields.get('in_progress') or auto_status}

## Next steps

{auto_next}

## Decisions

{fields.get('decisions') or 'No decisions recorded.'}

## Do not

{fields.get('do_not') or 'No constraints recorded.'}

## Open questions

{fields.get('questions') or 'None open.'}

## Files

{fields.get('files_text') or 'No files recorded.'}

## Verification

{fields.get('verification') or 'No verification run yet.'}
"""
    store.write_task(checkpoint_path(task_id), meta, body)
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


def format_checkpoint_age(task_id: str) -> str:
    age = checkpoint_age_minutes(task_id)
    if age is None:
        return "none"
    minutes = int(age)
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 48 * 60:
        return f"{minutes // 60}h ago"
    return f"{minutes // (24 * 60)}d ago"


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


def current_drift(task_id: str) -> dict:
    data = read_checkpoint(task_id)
    if not data:
        return {"checkpoint": False}
    meta, _, sidecar = data
    current = repo.git_state()
    saved_git = sidecar.get("git") or {}
    drift = {
        "checkpoint": True,
        "branch": current.get("branch"),
        "head": current.get("head"),
        "dirty": current.get("dirty", []),
        "commits_since": None,
        "files": {},
        "evidence": evidence.task_status(task_id, current.get("head")),
    }
    old_head = saved_git.get("head")
    if old_head and current.get("head") and old_head != current["head"]:
        code, count, _ = repo.run_git(["rev-list", "--count", f"{old_head}..{current['head']}"])
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
    path = store.find_task(task_id)
    prefix = ws_prefix()
    rel = ws_rel(path) if path else f"{prefix}tasks/active/{task_id}-..."
    checkpoint = ws_rel(checkpoint_path(task_id))
    cli = f"{prefix}ai"
    return f"""You are resuming task {task_id} in the .ai engineering workspace.

1. Read {prefix}AGENTS.md, {prefix}GUIDE.md and {prefix}docs/task-flow.md.
2. Read {rel} and {checkpoint}.
3. Verify the real repository state before trusting the checkpoint (git status, git log, tests).
4. Claim or refresh ownership: `{cli} task claim {task_id} --agent <name>` (or `{cli} lock heartbeat task-{task_id}`).
5. Continue from the first unchecked item in "Next steps". Do not redo "Done" items.
6. Checkpoint at the next milestone, and always before your context window fills: `{cli} checkpoint {task_id} --agent <name>`.
7. Never call it done without `{cli} check`.
"""
