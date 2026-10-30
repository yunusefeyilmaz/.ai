"""cmd.init: split out of the former monolithic ai.py."""

from __future__ import annotations

import os

from lib.core.paths import (
    PROJECT,
    WORKSPACE,
)
from lib.config.settings import (
    config_path,
    default_config,
)
from lib.core.fsio import write_json_atomic
from lib.runtime.dirs import (
    ensure_dirs,
    ensure_placeholders,
)
from lib.config import adopt as config_adopt


def cmd_init(args) -> int:
    ensure_dirs()
    if not os.path.exists(config_path()):
        write_json_atomic(config_path(), default_config())
    ensure_placeholders()
    print(f"Workspace ready: {WORKSPACE}")
    print(f"Project root:    {PROJECT}")
    if args.wire:
        if os.path.basename(WORKSPACE) != ".ai":
            print("Template install detected: the workspace is the project root; no wiring needed.")
        else:
            for path, state in config_adopt.adopt_root():
                print(f"{state.upper():<10} {path}")
            state, _ = config_adopt.adopt_gitignore()
            print(f"{state.upper():<10} .gitignore")
            print("Local adapters are in place. Each clone runs `ai adopt` to create its own copies.")
    print("Next: run `ai doctor`.")
    return 0


ORDER = 0


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    init = sub.add_parser("init", help="prepare runtime directories and config")
    init.add_argument("--wire", action="store_true", help="also wire the root adapters (same as `ai adopt`)")
    init.set_defaults(func=cmd_init)
