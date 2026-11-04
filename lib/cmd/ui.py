"""cmd.ui: the terminal dashboard (read-only).

    ai ui                 live dashboard: tasks, specs, agents, locks, activity, health
    ai ui --demo          the same screens fed by a self-playing fake workspace
    ai ui --once          print one frame and exit (also what a pipe or CI gets)

It reads state through the same modules as `ai status`, `ai now` and `ai doctor`
and never writes anything: no tasks, no locks, no Git. Stdlib only.
"""

from __future__ import annotations

import sys

from lib.ui import app as ui_app
from lib.ui.style import THEMES

ORDER = 35


def cmd_ui(args) -> int:
    interactive = sys.stdout.isatty() and sys.stdin.isatty() and not args.once
    if not interactive:
        print(ui_app.render_once(args, args.width, args.height))
        return 0
    return ui_app.run(args)


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    ui = sub.add_parser("ui", help="live terminal dashboard: tasks, specs, agents, locks, activity, health (read-only)")
    ui.add_argument("--demo", action="store_true", help="play a fake workspace instead of reading this one")
    ui.add_argument("--theme", default="aurora", choices=sorted(THEMES), help="color theme (press t inside to cycle)")
    ui.add_argument("--screen", default=None, choices=[s[0] for s in ui_app.SCREENS], help="open on this screen")
    ui.add_argument("--refresh", type=float, default=2.0, help="seconds between workspace reads (default 2)")
    ui.add_argument("--agent", default=None, help="highlight this agent's work in the NEXT box")
    ui.add_argument("--role", default=None, choices=["chief", "implementer", "reviewer"], help="view NEXT as this role")
    ui.add_argument("--no-anim", action="store_true", help="turn animations off")
    ui.add_argument("--no-splash", action="store_true", help="skip the startup animation")
    ui.add_argument("--no-color", action="store_true", help="plain text (NO_COLOR is honored too)")
    ui.add_argument("--ascii", action="store_true", help="ASCII-only drawing for legacy terminals")
    ui.add_argument("--once", action="store_true", help="print one frame and exit")
    ui.add_argument("--width", type=int, default=None, help="with --once: frame width")
    ui.add_argument("--height", type=int, default=None, help="with --once: frame height")
    ui.add_argument("--frame", type=int, default=12, help="with --once: animation frame to draw")
    ui.set_defaults(func=cmd_ui)
