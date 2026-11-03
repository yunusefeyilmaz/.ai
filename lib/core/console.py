"""core.console: keep CLI output from crashing on a console codepage.

Task titles, spec bodies and quotes are user/AI text and may contain any
Unicode character. On Windows, a console or pipe using a legacy codepage (e.g.
cp1254, cp850) cannot encode them, so `print()` raised
`UnicodeEncodeError: 'charmap' codec can't encode character ...` and the command
died with a traceback after having printed useful state.

The fix is applied once, at startup:

* a real terminal keeps its codepage and escapes characters it cannot show
  (``\\u2192``), so nothing is lost and nothing crashes;
* redirected output (editor task output, CI, a pipe or a file) is written as
  UTF-8, which every consumer of a redirected stream can decode.
"""

from __future__ import annotations

import sys


def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def configure(streams=None) -> None:
    """Make `streams` (default stdout/stderr) unable to raise on encoding."""
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if _is_tty(stream):
                reconfigure(errors="backslashreplace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # A replaced or detached stream keeps working as-is.
            continue
