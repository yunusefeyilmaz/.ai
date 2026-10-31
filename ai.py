#!/usr/bin/env python3
"""Entry point of the .ai engineering workspace CLI.

Intentionally thin: it only builds the parser from `lib/cmd/*` (and future
`skills/*`) and dispatches. All behavior lives under `lib/`.

Stdlib only. Invoked through `ai` (POSIX) or `ai.cmd` (Windows), which
auto-detect a Python 3 interpreter. The file protocol is the contract; this
CLI is the fast, race-safe path through it.
"""

from __future__ import annotations

import argparse
import os
import sys

# Keep bytecode out of the managed tree (a workspace tool must not leave clutter
# behind) but still cache it: recompiling every module costs ~60 ms per call.
import tempfile  # noqa: E402

sys.pycache_prefix = os.path.join(
    tempfile.gettempdir(), "ai-pycache-%s" % (getattr(os, "getuid", lambda: "u")(),)
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.cmd import discover  # noqa: E402
from lib.core.paths import VERSION  # noqa: E402


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai",
        description="Local, cross-platform CLI for the .ai engineering workspace.",
    )
    parser.add_argument("--version", action="version", version=f"ai workspace {VERSION}")
    sub = parser.add_subparsers(dest="command")
    command = (argv if argv is not None else sys.argv[1:])[:1]
    for module in discover(command[0] if command else None):
        module.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # e.g. `ai ... | head`
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
