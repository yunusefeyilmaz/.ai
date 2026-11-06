"""cmd.capabilities: the machine-readable CLI contract.

The command list and every option string are read from the argparse parser the
CLI actually builds (`ai.py::build_parser`), so the contract cannot drift from
the code. Prose descriptions stay here, keyed by top-level command; a command
the parser defines but this file does not describe still ships, with a pointer
to `--help`, and `lib/tests/test_capabilities.py` fails when a parser flag is
not published.

    ai capabilities            # always JSON
"""

from __future__ import annotations

import argparse
import json
import sys

from lib.config.roles import DEFAULT_ROLES
from lib.core.paths import (
    TASK_STATUSES,
    VERSION,
)
from lib.git import repo
from lib.git.repo import COMMIT_TYPES

CAPABILITIES = {
    "name": "ai",
    "version": VERSION,
    "workspace": ".ai",
    "exit_codes": {"0": "success", "1": "check failed or operation refused", "127": "python 3 not found"},
    # One machine-readable source for the vocabularies the docs used to restate
    # in four slightly different spellings.
    "task_states": sorted(TASK_STATUSES),
    "roles": sorted(DEFAULT_ROLES),
    "commit_types": list(COMMIT_TYPES),
    "state": {
        "tasks": "tasks/active, tasks/done",
        "locks": "runtime/locks/*.lock (advisory, TTL leases)",
        "checkpoints": "runtime/state/checkpoints",
        "events": "runtime/state/events.jsonl and date-rotated local archives",
        "handoffs": "runtime/state/handoff",
        "artifacts": "runtime/artifacts",
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

# Prose for the top-level commands. The keys are not the contract: the parser
# is. A command missing here still appears in the output with a --help pointer.
DESCRIPTIONS = {
    "init": "create the workspace state in a fresh checkout; --wire adds the root adapters",
    "setup": "chief: the questions for the user and where answers are stored; --set k=v, --check NAME=CMD, --check-timeout NAME=SECONDS, --defaults (+ --yes), --json",
    "plan": "chief: apply <plan.json> creates linked tasks; example prints a skeleton; --dry-run, --role chief",
    "version": "print the workspace version",
    "now": "10-line state + the single next required command; --agent, --json",
    "context": "project memory: open/shipped work, ADRs, recent activity; --limit, --json",
    "decision": "new | list architecture decision records",
    "worktree": "list | path <task> | prune [--force]: per-task Git worktrees (git.isolation=worktree)",
    "history": "<id> [--evidence] [--json]: transition log (who, when, from -> to, why, proof) and verification evidence",
    "review": "<id> [--stat] [--max-lines N] [--json]: read-only review package: task, spec + criteria, branch diff, check evidence, history, checklist",
    "start": "one-command first run: prepare, detect Git, create or claim a task; --agent, --json, --no-demo",
    "adopt": "wire root adapters for every AI tool; --check also reports the .gitignore ledger policy",
    "doctor": "workspace health with a repair hint per finding; --fix, --strict, --json",
    "check": "single verification contract; --fast, --strict, --json, --task, --agent, --no-commands",
    "status": "tasks, locks, checkpoints, handoffs; --json, --board",
    "ui": "live terminal dashboard (read-only): tasks, specs, agents, locks, activity, health; --demo, --once, --theme",
    "metrics": "summarize local workflow events; --since, --json",
    "reset": "--hard: interactively clear task/spec/decision/runtime state; preserves framework files",
    "task": "new | list | show | link | ready | next [--review] | claim | release | review | request-changes | done | reopen | discard | block | unblock",
    "spec": "show | check <task-id> <n>: each criterion with its box and done/total, or tick criterion n",
    "lock": "acquire | release | heartbeat | status",
    "checkpoint": "save resumable context",
    "resume": "print a compact resume brief with drift",
    "brief": "print a paste-ready brief for an external chat AI",
    "handoff": "write a marker and checkpoint for another agent",
    "recover": "detect or repair inconsistent state; --apply, --json",
    "git": "setup | start | commit | finish | begin | end | verify",
    "artifact": "put | list | clean",
    "clean": "remove stale locks and logs",
    "capabilities": "this contract, derived from the parser",
}


def _build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    """The real CLI parser, without importing `ai.py` twice.

    Under `python ai.py` the entry point is `__main__`, so reuse its
    `build_parser`; importing the file by name would execute it a second time
    and could produce two module copies of every command.
    """
    entry = sys.modules.get("__main__")
    build = getattr(entry, "build_parser", None)
    if not callable(build):
        from ai import build_parser  # noqa: WPS433 - deliberate late import

        build = build_parser
    return build([])


def _option_strings(parser: argparse.ArgumentParser) -> list[str]:
    flags: set[str] = set()
    for action in parser._actions:  # argparse exposes no public equivalent
        flags.update(action.option_strings)
    return sorted(flags)


def _walk(name: str, parser: argparse.ArgumentParser, out: dict[str, list[str]]) -> None:
    out[name] = _option_strings(parser)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub_name, sub_parser in action.choices.items():
                _walk(f"{name} {sub_name}".strip(), sub_parser, out)


def parser_contract() -> dict[str, list[str]]:
    """Every command path the CLI defines, mapped to its option strings."""
    parser = _build_parser()
    out: dict[str, list[str]] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                _walk(name, sub, out)
    return out


def command_descriptions(contract: dict[str, list[str]]) -> dict[str, str]:
    return {
        name: DESCRIPTIONS.get(name) or f"see `ai {name} --help`"
        for name in sorted(contract)
        if " " not in name
    }


def cmd_capabilities(args) -> int:
    contract = parser_contract()
    payload: dict[str, object] = dict(CAPABILITIES)
    payload["commands"] = command_descriptions(contract)
    # Subcommand paths ("task new") carry their own flags; consumers that only
    # know top-level names can still read `commands`.
    payload["flags"] = {path: flags for path, flags in sorted(contract.items())}
    try:
        payload["branch_types"] = list(repo.git_config()["branchTypes"])
        payload["merge_strategy"] = repo.git_config().get("merge", "no-ff")
    except (OSError, ValueError):
        payload["branch_types"] = []
        payload["merge_strategy"] = None
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
    capabilities.add_argument("--json", action="store_true", help="accepted for symmetry; the output is always JSON")
    capabilities.set_defaults(func=cmd_capabilities)
