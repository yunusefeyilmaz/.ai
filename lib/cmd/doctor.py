"""cmd.doctor: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import sys

from lib.core.paths import (
    PROJECT,
    VERSION,
    WORKSPACE,
)
from lib.core.findings import Finding
from lib.runtime import evidence
from lib.git import repo
from lib.runtime import health
from lib.tasks import store


def cmd_doctor(args) -> int:
    fixes: list[str] = []
    if getattr(args, "fix", False):
        try:
            fixes = health.apply_safe_fixes()
        except OSError as exc:
            print(f"Could not complete the repair: {exc}", file=sys.stderr)
    problems = health.collect_checks()
    code = 1 if any(finding.level == "error" for finding in problems) else 0
    if args.strict and any(finding.level == "warn" for finding in problems):
        code = 1
    if getattr(args, "fix", False) and problems:
        code = 1
    if not args.json:
        if fixes:
            print("Repaired:")
            for item in fixes:
                print(f"FIXED  {item}")
            print()
        health.report_problems(problems)
    if args.json:
        payload = {
            "workspace": WORKSPACE,
            "project": PROJECT,
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "version": VERSION,
            "adapters": health.adapters(),
            "fixes": fixes,
            "check": health.problems_to_dict(problems),
        }
        print(json.dumps(payload, indent=2))
        return code
    print(f"workspace: {WORKSPACE}")
    print(f"project:   {PROJECT}")
    print(f"platform:  {sys.platform} ({os.name})")
    print(f"python:    {sys.version.split()[0]}")
    print(f"version:   {VERSION}")
    print()
    for adapter in health.adapters():
        print(f"adapter:   {adapter}")
    print()
    return code


def _evidence_task(args) -> str | None:
    """Task the evidence belongs to: --task, or the agent's only in-progress task."""
    if getattr(args, "task", None):
        path = store.find_task(args.task)
        return str(store.parse_task(path)[0].get("id")) if path else None
    agent = getattr(args, "agent", None)
    if not agent:
        return None
    mine = [
        t for t in store.load_tasks()
        if t["_folder"] == "active" and t.get("owner") == agent and t.get("status") == "in_progress"
    ]
    return str(mine[0].get("id")) if len(mine) == 1 else None


def cmd_check(args) -> int:
    problems = health.collect_checks()
    results: list[dict] = []
    task_id = _evidence_task(args)
    if not args.no_commands:
        try:
            problems.extend(health.run_commands(args.fast, results))
        except (OSError, ValueError) as exc:
            problems.append(
                Finding("error", f"could not run configured checks: {exc}", "fix config/workspace.json")
            )
    code = 1 if any(finding.level == "error" for finding in problems) else 0
    if args.strict and any(finding.level == "warn" for finding in problems):
        code = 1
    try:
        evidence.record_check(
            code == 0, strict=bool(args.strict), ran_commands=not args.no_commands,
            fast=bool(args.fast), head=repo.git_state().get("head"),
        )
        if task_id:
            record = evidence.record_task_check(
                task_id, getattr(args, "agent", None), code == 0,
                head=repo.git_state().get("head"), checks=results, strict=bool(args.strict),
                ran_commands=not args.no_commands, fast=bool(args.fast),
            )
            if not args.json:
                print(f"Evidence recorded for task {task_id}: {evidence.summary(record)}", file=sys.stderr)
    except OSError as exc:  # evidence is best-effort; never mask the check result
        print(f"WARN  could not record the check result: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(health.problems_to_dict(problems), indent=2))
        return code
    health.report_problems(problems)
    return code


ORDER = 20


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    doctor = sub.add_parser("doctor", help="check workspace health; --fix repairs safe issues")
    doctor.add_argument("--strict", action="store_true", help="treat warnings as failures")
    doctor.add_argument(
        "--fix", action="store_true",
        help="recreate missing runtime state, config and subfolder adapters",
    )
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    check = sub.add_parser("check", help="run the single verification contract")
    check.add_argument("--fast", action="store_true", help="run only fast checks")
    check.add_argument("--no-commands", action="store_true", help="structure/state checks only")
    check.add_argument("--strict", action="store_true", help="treat warnings as failures")
    check.add_argument("--task", default=None, help="attach the result to this task as verification evidence")
    check.add_argument("--agent", default=None, help="who runs the check (auto-attaches to your only in-progress task)")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)
