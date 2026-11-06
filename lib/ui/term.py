"""ui.term: raw terminal access with no third-party dependency.

POSIX uses termios + select; Windows uses msvcrt. Everything the dashboard
needs from a terminal lives here: alternate screen, hidden cursor, size, color
depth, and a non-blocking key reader that returns symbolic key names.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
import time
import unicodedata
from typing import Any, cast


def _detect_windows() -> bool:
    return os.name == "nt"


IS_WINDOWS: bool = _detect_windows()

if IS_WINDOWS:  # pragma: no cover - exercised on Windows only
    import msvcrt

    _msvcrt = cast(Any, msvcrt)
else:
    import select

    termios = importlib.import_module("termios")
    tty = importlib.import_module("tty")

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


# --- text width -------------------------------------------------------------

def char_width(ch: str) -> int:
    if ch == "\t":
        return 4
    if unicodedata.combining(ch) or ch in ("\u200b", "\ufe0f"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible_len(text: str) -> int:
    plain = ANSI.sub("", text)
    if plain.isascii():
        return len(plain)
    return sum(char_width(ch) for ch in plain)


def clip(text: str, width: int, ellipsis: str = "…") -> str:
    """Cut `text` to `width` columns, keeping escape codes intact and closing styles."""
    if width <= 0:
        return ""
    if visible_len(text) <= width:
        return text
    out: list[str] = []
    used = 0
    limit = width - (1 if ellipsis else 0)
    pos = 0
    styled = False
    while pos < len(text):
        match = ANSI.match(text, pos)
        if match:
            out.append(match.group(0))
            styled = True
            pos = match.end()
            continue
        ch = text[pos]
        w = char_width(ch)
        if used + w > limit:
            break
        out.append(ch)
        used += w
        pos += 1
    out.append(ellipsis)
    if styled:
        out.append("\x1b[0m")
    return "".join(out)


def pad(text: str, width: int, align: str = "left") -> str:
    """Clip then pad to exactly `width` columns."""
    text = clip(text, width)
    gap = width - visible_len(text)
    if gap <= 0:
        return text
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


# --- color depth ------------------------------------------------------------

def color_mode(no_color: bool = False) -> str:
    """truecolor | 256 | 16 | none, from the usual environment signals."""
    if no_color or os.environ.get("NO_COLOR") is not None:
        return "none"
    term = os.environ.get("TERM", "")
    if term == "dumb":
        return "none"
    colorterm = os.environ.get("COLORTERM", "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return "truecolor"
    if IS_WINDOWS or os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") in ("iTerm.app", "vscode", "WezTerm"):
        return "truecolor"
    if "256" in term:
        return "256"
    return "16"


def terminal_size(default: tuple[int, int] = (120, 40)) -> tuple[int, int]:
    size = shutil.get_terminal_size(default)
    return size.columns, size.lines


def supports_unicode() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


# --- screen control ---------------------------------------------------------

ENTER_SCREEN = "\x1b[?1049h\x1b[?25l\x1b[2J"
LEAVE_SCREEN = "\x1b[0m\x1b[?25h\x1b[?1049l"


def _enable_windows_vt() -> None:  # pragma: no cover - Windows only
    try:
        import ctypes

        kernel = vars(ctypes)["windll"].kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError):
        pass


class Terminal:
    """Context manager: alternate screen + raw keys, always restored on exit."""

    def __init__(self) -> None:
        self._fd = sys.stdin.fileno() if not IS_WINDOWS else -1
        self._saved: Any = None
        self._pending = ""

    def __enter__(self) -> "Terminal":
        if IS_WINDOWS:  # pragma: no cover
            _enable_windows_vt()
        else:
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        sys.stdout.write(ENTER_SCREEN)
        sys.stdout.flush()
        return self

    def __exit__(self, *exc) -> None:
        sys.stdout.write(LEAVE_SCREEN)
        sys.stdout.flush()
        if not IS_WINDOWS and self._saved is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    # --- keys -----------------------------------------------------------
    _CSI = {
        "A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
        "1~": "home", "4~": "end", "5~": "pgup", "6~": "pgdn", "3~": "delete", "Z": "backtab",
    }

    def read_key(self, timeout: float) -> str | None:
        """Wait up to `timeout` seconds; return a key name, a single char, or None."""
        if IS_WINDOWS:  # pragma: no cover
            return self._read_key_windows(timeout)
        ready, _, _ = select.select([self._fd], [], [], max(0.0, timeout))
        if not ready:
            return None
        data = os.read(self._fd, 32).decode("utf-8", errors="ignore")
        if not data:
            return "eof"
        return self._decode(data)

    def _decode(self, data: str) -> str | None:
        if data == "\x1b":
            return "esc"
        if data.startswith("\x1b[") or data.startswith("\x1bO"):
            body = data[2:]
            for suffix, name in self._CSI.items():
                if body.endswith(suffix):
                    return name
            return None
        if data in ("\r", "\n"):
            return "enter"
        if data == "\t":
            return "tab"
        if data in ("\x7f", "\b"):
            return "backspace"
        if data == "\x03":
            return "ctrl-c"
        return data[0] if data else None

    def _read_key_windows(self, timeout: float) -> str | None:  # pragma: no cover
        end = time.time() + timeout
        while time.time() < end:
            if _msvcrt.kbhit():
                ch = _msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    code = _msvcrt.getwch()
                    return {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home",
                            "O": "end", "I": "pgup", "Q": "pgdn"}.get(code)
                if ch == "\r":
                    return "enter"
                if ch == "\t":
                    return "tab"
                if ch == "\x1b":
                    return "esc"
                if ch == "\x08":
                    return "backspace"
                if ch == "\x03":
                    return "ctrl-c"
                return ch
            time.sleep(0.01)
        return None


def write_frame(lines: list[str], previous: list[str] | None, width: int) -> None:
    """Paint `lines`, rewriting only rows that changed since `previous`."""
    out: list[str] = []
    for row, line in enumerate(lines):
        if previous is not None and row < len(previous) and previous[row] == line:
            continue
        out.append(f"\x1b[{row + 1};1H{line}\x1b[0m\x1b[K")
    if previous is not None and len(previous) > len(lines):
        for row in range(len(lines), len(previous)):
            out.append(f"\x1b[{row + 1};1H\x1b[K")
    if out:
        sys.stdout.write("".join(out))
        sys.stdout.flush()
