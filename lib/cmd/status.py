"""cmd.status: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os

from lib.core.paths import (
    CHECKPOINT_DIR,
    MANIFEST_PATH,
    PROJECT,
    WORKSPACE,
)
from lib.config.settings import load_config
from lib.core.fsio import read_json
from lib.runtime.leases import (
    list_locks,
    print_lock_table,
)
from lib.runtime import checkpoints as ckpt
from lib.tasks import board
from lib.tasks import store


def cmd_status(args) -> int:
    config = load_config()
    tasks = store.load_tasks()
    if getattr(args, "board", False) and not getattr(args, "json", False):
        print(board.render_board(tasks, list_locks(ensure=False), str(config.get("mode"))))
        return 0
    active = [task for task in tasks if task["_folder"] == "active"]
    locks = list_locks()
    artifacts = read_json(MANIFEST_PATH) or []
    markers = ckpt.list_handoff_markers()
    checkpoints = [
        {"task": path.split(os.sep)[-1][:-3], "age_minutes": ckpt.checkpoint_age_minutes(path.split(os.sep)[-1][:-3])}
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


ORDER = 30


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    status = sub.add_parser("status", help="show tasks, locks, checkpoints, handoffs and artifacts")
    status.add_argument("--json", action="store_true")
    status.add_argument(
        "--board",
        action="store_true",
        help="read-only board: dependency order, checkpoint age, leases and refusals",
    )
    status.set_defaults(func=cmd_status)
