"""cmd.version: split out of the former monolithic ai.py."""

from __future__ import annotations

from lib.core.paths import (
    VERSION,
)



def cmd_version(args) -> int:
    print(f"ai workspace {VERSION}")
    return 0


ORDER = 150


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    version = sub.add_parser("version", help="print the workspace version")
    version.set_defaults(func=cmd_version)
