"""cmd.artifact: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import shutil
import sys

from lib.core.paths import (
    ARTIFACTS_DIR,
    LOCKS_DIR,
    LOGS_DIR,
    MANIFEST_PATH,
    PROJECT,
    WORKSPACE,
)
from lib.config.settings import lock_settings
from lib.core.fsio import (
    read_json,
    safe_name,
    write_json_atomic,
)
from lib.core.timeutil import (
    iso,
    now,
)
from lib.runtime.dirs import ensure_dirs
from lib.runtime.leases import (
    list_locks,
    lock_is_stale,
)
from lib.runtime.mutex import workspace_state_guard


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


ORDER = 130


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
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
