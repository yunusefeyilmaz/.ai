"""ui.widgets: small reusable pieces shared by every screen."""

from __future__ import annotations

from lib.core.timeutil import now, parse_iso
from lib.ui.style import PRIORITY_TOKEN, STATUS_LABEL, STATUS_TOKEN, Style, humanize
from lib.ui.term import pad, visible_len

EVENT_ICON = {
    "task_created": ("+", "info"), "task_claimed": ("▶", "progress"), "task_released": ("◀", "dim"),
    "task_reviewed": ("◆", "review"), "task_merged": ("⇉", "accent"), "task_done": ("✔", "done"),
    "task_changes_requested": ("↩", "changes"), "task_blocked": ("■", "blocked"),
    "checkpoint": ("⚑", "warn"), "resume": ("⟲", "info"), "lock_refused": ("✖", "err"),
    "lock_forced": ("!", "err"), "claim_rolled_back": ("↺", "warn"),
}
EVENT_ASCII = {
    "task_created": "+", "task_claimed": ">", "task_released": "<", "task_reviewed": "*", "task_merged": "M",
    "task_done": "v", "task_changes_requested": "r", "task_blocked": "#", "checkpoint": "c", "resume": "R",
    "lock_refused": "x", "lock_forced": "!", "claim_rolled_back": "u",
}


def event_icon(st: Style, name: str) -> str:
    glyph, token = EVENT_ICON.get(name, ("·", "dim"))
    if not st.g.unicode:
        glyph = EVENT_ASCII.get(name, ".")
    return st.c(token, glyph, bold=True)


def chip(st: Style, text: str, token="accent") -> str:
    """Filled badge: ` TEXT ` on the token color (falls back to [TEXT] without color)."""
    return st.reverse(f" {text} ", token)


def status_chip(st: Style, status: str) -> str:
    return chip(st, STATUS_LABEL.get(status, status.upper()), STATUS_TOKEN.get(status, "dim"))


def priority_mark(st: Style, priority: str) -> str:
    letter = {"high": "H", "medium": "M", "low": "L"}.get(priority, "?")
    return st.c(PRIORITY_TOKEN.get(priority, "dim"), letter, bold=True)


def fit(lines: list[str], height: int) -> list[str]:
    """Exactly `height` rows: crop or pad with blanks."""
    return (lines + [""] * height)[:height]


def window(count: int, selected: int, height: int) -> tuple[int, int]:
    """(start, end) of the slice that keeps `selected` visible, roughly centred."""
    if count <= height:
        return 0, count
    start = max(0, min(selected - height // 2, count - height))
    return start, start + height


def scroll_view(lines: list[str], offset: int, height: int) -> tuple[list[str], int, bool]:
    """Slice `lines` by `offset`; returns (visible, clamped_offset, more_below)."""
    offset = max(0, min(offset, max(0, len(lines) - height)))
    return lines[offset:offset + height], offset, offset + height < len(lines)


def scrollbar(st: Style, rows: int, total: int, offset: int) -> list[str]:
    """One-column scroll indicator."""
    if total <= rows:
        return [" "] * rows
    size = max(1, rows * rows // total)
    top = min(rows - size, offset * rows // total)
    return [st.c("accent" if top <= i < top + size else "faint", "┃" if st.g.unicode else "|") for i in range(rows)]


def when(value) -> str:
    """'3m ago' style age for an ISO timestamp."""
    try:
        seconds = (now() - parse_iso(str(value))).total_seconds()
    except (TypeError, ValueError):
        return "-"
    return humanize(max(0, seconds)) + " ago"


def hhmm(value) -> str:
    try:
        return parse_iso(str(value)).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "--:--:--"


def day_hhmm(value) -> str:
    try:
        return parse_iso(str(value)).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return "--"


def kv(st: Style, key: str, value: str, width: int = 12) -> str:
    return st.c("dim", pad(key, width)) + value


def table(st: Style, columns: list[tuple[str, int, str]], rows: list[list[str]], selected: int | None = None,
          height: int | None = None, width: int = 0) -> list[str]:
    """Header + rows. `columns` is (title, width, align); width 0 = take the remaining space.

    Cells may already contain color. `selected` highlights one row; `height`
    scrolls to keep it visible and reserves one row for the header.
    """
    head = " ".join(st.c("dim", pad(title, width) if width else title, bold=True) for title, width, _ in columns)
    body_rows = rows
    start = 0
    if height is not None:
        room = max(1, height - 1)
        start, end = window(len(rows), selected or 0, room)
        body_rows = rows[start:end]
    out = [head]
    for index, row in enumerate(body_rows):
        cells = [pad(cell, width, align) if width else cell for cell, (_, width, align) in zip(row, columns)]
        line = " ".join(cells)
        out.append(st.selected(pad(line, width or visible_len(line))) if selected is not None and index + start == selected else line)
    return out


def labelled_bar(st: Style, label: str, ratio: float, width: int, token="accent", suffix: str = "",
                 label_width: int = 10, shimmer: int | None = None) -> str:
    bar_width = max(4, width - label_width - visible_len(suffix) - 2)
    return f"{st.c('dim', pad(label, label_width))} {st.bar(ratio, bar_width, token, shimmer=shimmer)} {suffix}"
