"""runtime.health: split out of the former monolithic ai.py."""

from __future__ import annotations

import os
import re
import subprocess
import sys

from lib.core.paths import (
    PROJECT,
    REQUIRED_PATHS,
    SCAN_SKIP,
    TASK_STATUSES,
    WORKSPACE,
    workspace_shape,
)
from lib.config.settings import (
    config_path,
    default_config,
    load_config,
    lock_settings,
)
from lib.core.findings import Finding
from lib.core.fsio import (
    normalize_id,
    write_json_atomic,
)
from lib.core.timeutil import age_minutes
from lib.runtime.dirs import (
    ensure_placeholders,
    workspace_dirs,
)
from lib.runtime.leases import (
    list_locks,
    lock_is_stale,
)
from lib.config import adopt as config_adopt
from lib.git import repo
from lib.runtime import checkpoints as ckpt
from lib.tasks import store


def adapter_findings() -> list[Finding]:
    """A subfolder install works only when its host points at the workspace."""
    if workspace_shape() != "subfolder":
        return []
    findings: list[Finding] = []
    try:
        for path, state in config_adopt.adopt_root(check=True):
            if state != "ok":
                findings.append(
                    Finding("warn", f"missing adapter pointer: {path}", "ai doctor --fix")
                )
        _, missing = config_adopt.adopt_gitignore(check=True)
    except OSError as exc:
        return [Finding("warn", f"could not inspect the host adapters: {exc}")]
    if missing:
        findings.append(
            Finding(
                "warn",
                "project .gitignore is missing: " + ", ".join(missing),
                "ai doctor --fix",
            )
        )
    return findings


def apply_safe_fixes() -> list[str]:
    """Repair missing, regenerable state. Never overwrite files or touch Git."""
    fixes: list[str] = []
    for path in workspace_dirs():
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            fixes.append(f"created {os.path.relpath(path, WORKSPACE).replace(os.sep, '/')}/")
    fixes.extend(f"created {item}" for item in ensure_placeholders())
    if not os.path.exists(config_path()):
        write_json_atomic(config_path(), default_config())
        fixes.append("created config/workspace.json")
    if workspace_shape() == "subfolder":
        missing = [path for path, state in config_adopt.adopt_root(check=True) if state != "ok"]
        if missing:
            config_adopt.adopt_root()
            fixes.extend(f"wired {path}" for path in missing)
        _, missing_ignore = config_adopt.adopt_gitignore(check=True)
        if missing_ignore:
            config_adopt.adopt_gitignore()
            fixes.append("added .gitignore rules: " + ", ".join(missing_ignore))
    return fixes


def collect_checks() -> list[Finding]:
    problems: list[Finding] = []
    for rel in REQUIRED_PATHS:
        # The config loader below owns this one: it knows whether the file is
        # absent (safe to recreate) or corrupt (never overwrite).
        if rel == "config/workspace.json":
            continue
        if not os.path.exists(os.path.join(WORKSPACE, rel)):
            if rel.startswith("runtime"):
                hint = "ai doctor --fix"
            elif workspace_shape() == "subfolder":
                hint = f"restore {rel} from the .ai workspace copy"
            else:
                hint = f"git checkout -- {rel}"
            problems.append(Finding("error", f"missing required path: {rel}", hint))
    try:
        config = load_config()
    except FileNotFoundError:
        problems.append(Finding("error", "config/workspace.json is missing", "ai doctor --fix"))
        config = {}
    except (OSError, ValueError) as exc:
        problems.append(
            Finding(
                "error",
                f"config/workspace.json is unreadable: {exc}",
                "move config/workspace.json aside and run `ai init`",
            )
        )
        config = {}
    if config:
        if config.get("mode") not in ("lite", "strict"):
            problems.append(
                Finding(
                    "error",
                    "config mode must be 'lite' or 'strict'",
                    'set "mode" to "lite" or "strict" in config/workspace.json',
                )
            )
        for key in ("version", "language", "locks", "handoff", "budget", "artifacts"):
            if key not in config:
                problems.append(
                    Finding(
                        "warn",
                        f"config is missing key: {key}",
                        f'add "{key}" to config/workspace.json',
                    )
                )

    locks = list_locks(ensure=False)
    lock_by_task = {}
    for lock in locks:
        resource = str(lock.get("resource") or "")
        if resource.startswith("task-"):
            lock_by_task[resource[5:]] = lock

    ids: dict[str, str] = {}
    tasks = store.load_tasks()
    for task in tasks:
        path = os.path.relpath(task["_path"], WORKSPACE)
        task_id = task.get("id")
        if not task_id:
            problems.append(Finding("error", f"{path}: missing id", f"add an `id:` field to {path}"))
        else:
            task_id = str(task_id)
            if task_id in ids:
                problems.append(
                    Finding(
                        "error",
                        f"duplicate task id {task_id}: {path} and {ids[task_id]}",
                        "give one of the tasks a different id, then rerun `ai check`",
                    )
                )
            ids[task_id] = path
            if task["_folder"] == "active" and normalize_id(task_id) + "-" not in os.path.basename(path):
                problems.append(
                    Finding(
                        "warn",
                        f"{path}: filename does not start with {task_id}-",
                        f"rename {path} to {task_id}-<slug>.md",
                    )
                )
        if not task.get("title"):
            problems.append(Finding("error", f"{path}: missing title", f"add a `title:` field to {path}"))
        status = task.get("status")
        if status not in TASK_STATUSES:
            problems.append(
                Finding(
                    "error",
                    f"{path}: invalid status '{status}'",
                    f"set `status:` to one of {', '.join(sorted(TASK_STATUSES))} in {path}",
                )
            )
        if task["_folder"] == "done" and status != "done":
            problems.append(
                Finding(
                    "warn",
                    f"{path}: file in done/ but status is '{status}'",
                    f"set `status: done` in {path}",
                )
            )
        if task["_folder"] == "active" and status == "done":
            problems.append(
                Finding(
                    "warn",
                    f"{path}: status is done but file is in active/",
                    f"run `ai task done {task_id} --agent <name>` to archive it",
                )
            )
        depends = task.get("depends_on")
        if depends:
            for dependency in re.split(r"[,\s]+", str(depends)):
                dependency = dependency.strip()
                if dependency and normalize_id(dependency) not in ids and not store.find_task(dependency):
                    problems.append(
                        Finding(
                            "warn",
                            f"{path}: depends_on unknown task {dependency}",
                            f"remove `{dependency}` from depends_on in {path}, or create it with `ai task new`",
                        )
                    )
        if task["_folder"] == "active":
            owner = task.get("owner")
            held = lock_by_task.get(str(task_id))
            if owner and not held:
                problems.append(
                    Finding(
                        "warn",
                        f"{path}: owner '{owner}' has no task lock",
                        "ai recover --apply",
                    )
                )
            if held and not owner:
                problems.append(
                    Finding(
                        "warn",
                        f"{path}: task lock held by {held.get('agent')} but owner is empty",
                        "ai recover --apply",
                    )
                )
            if owner and held and held.get("agent") != owner:
                problems.append(
                    Finding(
                        "warn",
                        f"{path}: owner '{owner}' differs from lock holder '{held.get('agent')}'",
                        "ai recover --apply",
                    )
                )
            if status == "in_progress":
                warn_after = int(config.get("handoff", {}).get("warnAfterMinutes", 30)) if config else 30
                checkpoint_hint = f"ai checkpoint {task_id} --agent {owner or 'agent'} --next \"<step>\""
                age = ckpt.checkpoint_age_minutes(task_id)
                if age is None:
                    claimed_age = age_minutes(
                        (held or {}).get("started_at") or task.get("updated")
                    )
                    # Lite mode gives a small task time to finish before asking
                    # for a checkpoint; strict mode holds the full standard.
                    grace = (
                        str(config.get("mode") or "lite") == "lite"
                        and claimed_age is not None
                        and claimed_age <= warn_after
                    )
                    if not grace:
                        problems.append(
                            Finding(
                                "warn",
                                f"{path}: in_progress with no checkpoint",
                                checkpoint_hint,
                            )
                        )
                elif age > warn_after:
                    problems.append(
                        Finding(
                            "warn",
                            f"{path}: last checkpoint is {int(age)} min old",
                            checkpoint_hint,
                        )
                    )
        if task["_folder"] == "done" and str(task_id) in lock_by_task:
            problems.append(
                Finding(
                    "warn",
                    f"{path}: done task still holds task lock",
                    "ai recover --apply",
                )
            )

    try:
        _, stale_after = lock_settings()
    except (OSError, ValueError):
        # A missing or corrupt config is already reported above; staleness is
        # still useful, so fall back to the documented defaults.
        stale_after = 3600
    for lock in locks:
        if lock_is_stale(lock, stale_after):
            problems.append(
                Finding(
                    "warn",
                    f"stale lock: {lock.get('resource')} held by {lock.get('agent')}",
                    "ai clean --stale-locks",
                )
            )
    for lock in locks:
        resource = str(lock.get("resource") or "")
        if resource.startswith("task-") and resource[5:] not in ids:
            problems.append(
                Finding(
                    "warn",
                    f"orphan task lock: {resource} has no task file",
                    "ai recover --apply",
                )
            )

    for marker in ckpt.list_handoff_markers(ensure=False):
        task_id = str(marker.get("task") or "")
        hint = f"ai checkpoint {task_id} --agent {marker.get('agent')} --next \"<step>\""
        data = ckpt.read_checkpoint(task_id)
        if not data:
            problems.append(
                Finding("warn", f"handoff requested for {task_id} but no checkpoint exists", hint)
            )
        elif str(data[0].get("created") or "") < str(marker.get("created") or ""):
            problems.append(
                Finding("warn", f"handoff requested for {task_id} but the checkpoint is older", hint)
            )

    watch = config.get("artifacts", {}).get("watch", []) if config else []
    try:
        top_level = set(os.listdir(PROJECT))
    except OSError:
        top_level = set()
    for name in watch:
        if name in top_level and name not in SCAN_SKIP:
            problems.append(
                Finding(
                    "error",
                    f"AI scratch path outside the workspace: {name}/",
                    f"ai artifact put {name} --reason \"agent scratch\"",
                )
            )

    if config.get("security", {}).get("warnTrackedSecrets", True):
        code, tracked, _ = repo.run_git(["ls-files"])
        if code == 0 and tracked:
            risky = [
                item for item in tracked.splitlines()
                if item in (".env", ".env.local")
                or item.endswith((".pem", ".key", ".p12", ".pfx"))
                or os.path.basename(item) in ("id_rsa", "id_ed25519", "credentials.json")
            ]
            for item in risky:
                problems.append(
                    Finding(
                        "warn",
                        f"tracked secret-shaped file: {item}",
                        f"git rm --cached {item}  (then rotate the secret)",
                    )
                )

    problems.extend(adapter_findings())
    return problems


def report_problems(problems: list[Finding]) -> int:
    errors = [finding for finding in problems if finding.level == "error"]
    warnings = [finding for finding in problems if finding.level == "warn"]
    for label, group in (("ERROR", errors), ("WARN ", warnings)):
        for finding in group:
            print(f"{label}  {finding.message}")
            if finding.hint:
                print(f"       fix: {finding.hint}")
    if not problems:
        print("OK     workspace structure and task state are consistent")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def run_commands(fast_only: bool) -> list[Finding]:
    problems: list[Finding] = []
    config = load_config()
    checks = config.get("checks", [])
    if not checks:
        print(
            "NOTE  no project checks configured: add your test/lint commands under "
            '"checks" in config/workspace.json, e.g. {"name": "tests", "command": "npm test"}. '
            "(`ai check` never runs the workspace's own tests.)",
            file=sys.stderr,
        )
    for item in checks:
        if fast_only and not item.get("fast", False):
            continue
        name = item.get("name") or item.get("command", "check")
        command = item.get("command")
        if not command:
            continue
        print(f"\n$ {command}")
        result = subprocess.run(command, shell=True, cwd=PROJECT)
        if result.returncode != 0:
            problems.append(
                Finding(
                    "error",
                    f"check '{name}' failed with exit code {result.returncode}",
                    f"run the failing command yourself: {command}",
                )
            )
    return problems


def adapters() -> list[str]:
    directory = os.path.join(WORKSPACE, "adapters")
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory) if os.path.isdir(os.path.join(directory, name)))


def problems_to_dict(problems: list[Finding]) -> dict:
    return {
        "ok": not any(finding.level == "error" for finding in problems),
        "errors": [finding.message for finding in problems if finding.level == "error"],
        "warnings": [finding.message for finding in problems if finding.level == "warn"],
        "findings": [
            {"level": finding.level, "message": finding.message, "hint": finding.hint}
            for finding in problems
        ],
    }
