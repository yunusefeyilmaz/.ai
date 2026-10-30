"""tasks.discard: split out of the former monolithic ai.py."""

from __future__ import annotations

import os

from lib.core.paths import (
    CHECKPOINT_ARCHIVE,
    LOCKS_DIR,
    PROJECT,
    SPECS_ACTIVE_DIR,
    SPECS_DONE_DIR,
    WORKSPACE,
)
from lib.config.settings import lock_settings
from lib.core.fsio import (
    normalize_id,
    read_json,
    safe_name,
)
from lib.runtime.leases import (
    list_locks,
    lock_is_stale,
    resources_overlap,
)
from lib.runtime import checkpoints as ckpt
from lib.tasks import store


def task_discard_spec_path(meta: dict, task_id: str) -> tuple[str | None, str | None]:
    reference = str(meta.get("spec") or "").strip()
    if not reference:
        return None, None
    reference = reference.replace("\\", "/")
    if reference.startswith(".ai/") and os.path.basename(WORKSPACE) == ".ai":
        reference = reference[4:]
    candidate = os.path.realpath(os.path.join(WORKSPACE, reference.replace("/", os.sep)))
    roots = [
        os.path.realpath(SPECS_ACTIVE_DIR),
        os.path.realpath(SPECS_DONE_DIR),
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
    spec_meta, _ = store.parse_task(candidate)
    if normalize_id(str(spec_meta.get("task") or "")) != normalize_id(task_id):
        return None, f"Linked spec does not identify task {task_id}: {reference}"
    return candidate, None


def task_discard_targets(task_path: str, spec_path: str | None, task_id: str) -> list[str]:
    targets = [
        ckpt.checkpoint_path(task_id),
        ckpt.checkpoint_sidecar(task_id),
        ckpt.handoff_marker(task_id),
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
