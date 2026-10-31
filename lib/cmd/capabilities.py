"""cmd.capabilities: split out of the former monolithic ai.py."""

from __future__ import annotations

from lib.core.paths import (
    VERSION,
)

import json



CAPABILITIES = {
    "name": "ai",
    "version": VERSION,
    "workspace": ".ai",
    "exit_codes": {"0": "success", "1": "check failed or operation refused", "127": "python 3 not found"},
    "state": {
        "tasks": "tasks/active, tasks/done",
        "locks": "runtime/locks/*.lock (advisory, TTL leases)",
        "checkpoints": "runtime/state/checkpoints",
        "events": "runtime/state/events.jsonl and date-rotated local archives",
        "handoffs": "runtime/state/handoff",
        "artifacts": "runtime/artifacts",
    },
    "commands": {
        "now": "10-line state + the single next required command; --agent, --json",
        "context": "project memory: open/shipped work, ADRs, recent activity; --limit, --json",
        "decision": "new | list architecture decision records",
        "worktree": "list | path <task> | prune [--force]: per-task Git worktrees (git.isolation=worktree)",
        "history": "<id> [--evidence] [--json]: transition log (who, when, from -> to, why, proof) and verification evidence",
        "start": "one-command first run: prepare, detect Git, create or claim a task; --agent, --json, --no-demo",
        "adopt": "wire root adapters for every AI tool",
        "doctor": "workspace health with a repair hint per finding; --fix, --strict, --json",
        "check": "single verification contract; --fast, --strict, --json",
        "status": "tasks, locks, checkpoints, handoffs; --json, --board",
        "metrics": "summarize local workflow events; --since, --json",
        "reset": "--hard: interactively clear task/spec/decision/runtime state; preserves framework files",
        "task": "new | list | show | link | ready | next | claim | release | review | done | discard | block | unblock",
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
        "done requires review by a different agent than the producer",
    ],
}


def cmd_capabilities(args) -> int:
    payload = dict(CAPABILITIES)
    payload["adapter_contract"] = {
        "schema_version": "0.1.0",
        "schema_path": "adapters/contract.schema.json",
        "adapter_dir": "adapters/",
        "state_paths": [
            "runtime/state/",
            "tasks/",
            "specs/",
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


ORDER = 120


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    capabilities = sub.add_parser("capabilities", help="print the machine-readable CLI contract")
    capabilities.add_argument("--json", action="store_true")
    capabilities.set_defaults(func=cmd_capabilities)
