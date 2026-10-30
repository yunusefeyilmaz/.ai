"""runtime.checkpoints: split out of the former monolithic ai.py."""

from __future__ import annotations

import hashlib
import os
import shutil

from lib.core.paths import (
    CHECKPOINT_ARCHIVE,
    CHECKPOINT_DIR,
    HANDOFF_DIR,
    PROJECT,
    ws_prefix,
    ws_rel,
)
from lib.core.fsio import (
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
from lib.tasks import store


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


def list_handoff_markers(ensure: bool = True) -> list[dict]:
    if ensure:
        ensure_dirs()
    if not os.path.isdir(HANDOFF_DIR):
        return []
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
    meta, body = store.parse_task(path)
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
