"""cmd.adopt: split out of the former monolithic ai.py."""

from __future__ import annotations

import os
import sys

from lib.core.paths import (
    PROJECT,
    WORKSPACE,
)
from lib.config.settings import (
    config_path,
    default_config,
)
from lib.core.fsio import write_json_atomic
from lib.runtime.dirs import ensure_dirs
from lib.config import adopt as config_adopt


def cmd_adopt(args) -> int:
    if not args.check:
        ensure_dirs()
    if not args.check and not os.path.exists(config_path()):
        write_json_atomic(config_path(), default_config())
    if args.print:
        print(config_adopt.BOOTSTRAP_PROMPT)
        return 0
    if os.path.basename(WORKSPACE) != ".ai" or PROJECT == WORKSPACE:
        print("Template install detected: the workspace is the project root.")
        print("Root AGENTS.md already acts as the signpost; no wiring needed.")
        if not args.check:
            print("Run `ai doctor` to verify the workspace.")
        return 0
    results = config_adopt.adopt_root(force=args.force, check=args.check)
    for path, state in results:
        print(f"{state.upper():<10} {path}")
    try:
        ignore_state, missing_ignore = config_adopt.adopt_gitignore(check=args.check)
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
        config_adopt.write_ci()
    print("\nLocal adapters are in place. Each clone runs `ai adopt` to create its own copies.")
    print("Next: ai doctor")
    return 0


ORDER = 10


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    adopt = sub.add_parser("adopt", help="wire the workspace into root AI tool configs")
    adopt.add_argument("--check", action="store_true", help="only report missing root adapters")
    adopt.add_argument("--print", dest="print", action="store_true", help="print the bootstrap prompt")
    adopt.add_argument("--force", action="store_true", help="rewrite managed blocks")
    adopt.add_argument("--ci", action="store_true", help="also write the CI workflow")
    adopt.set_defaults(func=cmd_adopt)
