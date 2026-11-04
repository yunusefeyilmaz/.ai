"""ui.style: palettes, glyph sets, and the small drawing toolkit every screen uses.

A `Style` turns semantic color names ("ok", "warn", "accent") into escape codes
for the terminal's real color depth, so one screen definition renders in
truecolor, 256 colors, 16 colors or plain text (NO_COLOR).
"""

from __future__ import annotations

from lib.ui.term import clip, pad, visible_len

THEMES: dict[str, dict[str, tuple[int, int, int]]] = {
    # name: semantic token -> RGB
    "aurora": {
        "fg": (214, 222, 235), "dim": (118, 128, 150), "faint": (72, 80, 100), "border": (58, 68, 92),
        "accent": (122, 162, 247), "accent2": (187, 154, 247), "hot": (247, 118, 142),
        "ok": (115, 218, 160), "warn": (255, 199, 119), "err": (247, 118, 142), "info": (125, 207, 255),
        "todo": (130, 140, 165), "progress": (122, 162, 247), "review": (187, 154, 247),
        "changes": (255, 158, 100), "blocked": (247, 118, 142), "done": (115, 218, 160),
        "sel_bg": (41, 50, 77),
    },
    "ember": {
        "fg": (240, 225, 205), "dim": (150, 125, 105), "faint": (95, 78, 66), "border": (92, 66, 52),
        "accent": (255, 160, 80), "accent2": (255, 107, 107), "hot": (255, 90, 90),
        "ok": (170, 220, 110), "warn": (255, 205, 90), "err": (255, 100, 100), "info": (255, 190, 130),
        "todo": (160, 135, 115), "progress": (255, 160, 80), "review": (255, 120, 150),
        "changes": (255, 130, 70), "blocked": (255, 90, 90), "done": (170, 220, 110),
        "sel_bg": (70, 46, 34),
    },
    "matrix": {
        "fg": (190, 255, 200), "dim": (80, 160, 100), "faint": (40, 90, 55), "border": (30, 100, 55),
        "accent": (60, 255, 120), "accent2": (140, 255, 190), "hot": (255, 255, 120),
        "ok": (60, 255, 120), "warn": (230, 255, 80), "err": (255, 90, 90), "info": (120, 255, 220),
        "todo": (90, 150, 105), "progress": (60, 255, 120), "review": (140, 255, 190),
        "changes": (230, 255, 80), "blocked": (255, 90, 90), "done": (60, 255, 120),
        "sel_bg": (14, 56, 30),
    },
    "paper": {
        "fg": (40, 44, 52), "dim": (110, 118, 132), "faint": (170, 176, 188), "border": (150, 158, 175),
        "accent": (37, 99, 235), "accent2": (124, 58, 237), "hot": (220, 38, 38),
        "ok": (22, 163, 74), "warn": (202, 138, 4), "err": (220, 38, 38), "info": (2, 132, 199),
        "todo": (110, 118, 132), "progress": (37, 99, 235), "review": (124, 58, 237),
        "changes": (234, 88, 12), "blocked": (220, 38, 38), "done": (22, 163, 74),
        "sel_bg": (219, 229, 252),
    },
}

STATUS_TOKEN = {
    "todo": "todo", "in_progress": "progress", "review": "review",
    "changes_requested": "changes", "blocked": "blocked", "done": "done",
}
STATUS_LABEL = {
    "todo": "TODO", "in_progress": "IN PROGRESS", "review": "REVIEW",
    "changes_requested": "CHANGES", "blocked": "BLOCKED", "done": "DONE",
}
PRIORITY_TOKEN = {"high": "hot", "medium": "warn", "low": "dim"}


class Glyphs:
    """Unicode drawing set with a plain-ASCII fallback (`--ascii`, legacy consoles)."""

    def __init__(self, unicode: bool = True) -> None:
        self.unicode = unicode
        if unicode:
            self.tl, self.tr, self.bl, self.br = "╭", "╮", "╰", "╯"
            self.h, self.v = "─", "│"
            self.full, self.empty = "█", "░"
            self.eighths = " ▏▎▍▌▋▊▉█"
            self.spark = "▁▂▃▄▅▆▇█"
            self.dot, self.ring, self.tick, self.cross = "●", "○", "✔", "✘"
            self.arrow, self.bullet, self.warn = "▸", "•", "▲"
            self.shade = " ░▒▓█"
            self.spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            self.check_on, self.check_off = "▣", "□"
        else:
            self.tl = self.tr = self.bl = self.br = "+"
            self.h, self.v = "-", "|"
            self.full, self.empty = "#", "."
            self.eighths = " #########"
            self.spark = "_.-~=+*#"
            self.dot, self.ring, self.tick, self.cross = "*", "o", "v", "x"
            self.arrow, self.bullet, self.warn = ">", "-", "!"
            self.shade = " .:*#"
            self.spinner = "|/-\\"
            self.check_on, self.check_off = "[x]", "[ ]"


def _to_256(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    if abs(r - g) < 10 and abs(g - b) < 10:
        gray = (r + g + b) // 3
        if gray < 8:
            return 16
        if gray > 248:
            return 231
        return 232 + (gray - 8) * 24 // 247
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


_BASIC = [
    (0, (0, 0, 0)), (1, (205, 49, 49)), (2, (13, 188, 121)), (3, (229, 229, 16)),
    (4, (36, 114, 200)), (5, (188, 63, 188)), (6, (17, 168, 205)), (7, (229, 229, 229)),
]


def _to_16(rgb: tuple[int, int, int]) -> int:
    best = min(_BASIC, key=lambda item: sum((a - b) ** 2 for a, b in zip(item[1], rgb)))
    return best[0]


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


class Style:
    def __init__(self, mode: str = "truecolor", theme: str = "aurora", unicode: bool = True) -> None:
        self.mode = mode
        self.theme_name = theme if theme in THEMES else "aurora"
        self.palette = THEMES[self.theme_name]
        self.g = Glyphs(unicode)

    # --- color -------------------------------------------------------------
    def rgb(self, token) -> tuple[int, int, int]:
        return token if isinstance(token, tuple) else self.palette.get(token, self.palette["fg"])

    def _fg(self, rgb: tuple[int, int, int]) -> str:
        if self.mode == "truecolor":
            return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        if self.mode == "256":
            return f"\x1b[38;5;{_to_256(rgb)}m"
        if self.mode == "16":
            return f"\x1b[{30 + _to_16(rgb)}m"
        return ""

    def _bg(self, rgb: tuple[int, int, int]) -> str:
        if self.mode == "truecolor":
            return f"\x1b[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        if self.mode == "256":
            return f"\x1b[48;5;{_to_256(rgb)}m"
        if self.mode == "16":
            return f"\x1b[{40 + _to_16(rgb)}m"
        return ""

    def c(self, token, text: str, bold: bool = False, dim: bool = False, bg=None, underline: bool = False) -> str:
        """Color `text`. `token` is a palette name or an RGB tuple."""
        if self.mode == "none":
            return text
        codes = self._fg(self.rgb(token))
        if bg is not None:
            codes += self._bg(self.rgb(bg))
        if bold:
            codes += "\x1b[1m"
        if dim:
            codes += "\x1b[2m"
        if underline:
            codes += "\x1b[4m"
        return f"{codes}{text}\x1b[0m"

    def reverse(self, text: str, token="accent") -> str:
        """Selected-row look: filled chip in the accent color."""
        if self.mode == "none":
            return f"[{text}]"
        return f"{self._bg(self.rgb(token))}\x1b[30m\x1b[1m{text}\x1b[0m"

    def selected(self, text: str) -> str:
        """Highlight a whole row (keeps the row's own foreground codes readable)."""
        if self.mode == "none":
            return text
        return f"{self._bg(self.rgb('sel_bg'))}{text.replace(chr(27) + '[0m', chr(27) + '[0m' + self._bg(self.rgb('sel_bg')))}\x1b[0m"

    def gradient(self, text: str, start, end, bold: bool = False) -> str:
        if self.mode == "none" or not text:
            return text
        a, b = self.rgb(start), self.rgb(end)
        n = max(1, len(text) - 1)
        out = []
        for index, ch in enumerate(text):
            if ch == " ":
                out.append(ch)
            else:
                out.append(self.c(lerp(a, b, index / n), ch, bold=bold))
        return "".join(out)

    def status(self, status: str, text: str | None = None, bold: bool = False) -> str:
        return self.c(STATUS_TOKEN.get(status, "dim"), text if text is not None else status, bold=bold)

    # --- widgets -----------------------------------------------------------
    def bar(self, ratio: float, width: int, token="accent", back="faint", shimmer: int | None = None) -> str:
        """Smooth horizontal bar (eighth blocks). `shimmer` is a frame counter for a moving highlight."""
        width = max(1, width)
        ratio = max(0.0, min(1.0, ratio))
        total = ratio * width
        full = int(total)
        frac = int((total - full) * 8)
        g = self.g
        base = self.rgb(token)
        cells = []
        for index in range(width):
            if index < full:
                color = base
                if shimmer is not None and full > 0:
                    pos = (shimmer % (full + 6)) - 3
                    color = lerp(base, (255, 255, 255), max(0.0, 1 - abs(index - pos) / 3) * 0.55)
                cells.append(self.c(color, g.full))
            elif index == full and frac and ratio < 1.0:
                cells.append(self.c(base, g.eighths[frac]))
            else:
                cells.append(self.c(back, g.empty if not g.unicode else "░", dim=True))
        return "".join(cells)

    def spark(self, values: list[float], width: int | None = None, token="accent") -> str:
        glyphs = self.g.spark
        if not values:
            return ""
        if width and len(values) > width:
            values = values[-width:]
        top = max(values) or 1
        out = []
        for value in values:
            level = int(round((value / top) * (len(glyphs) - 1))) if value > 0 else 0
            ch = glyphs[level] if value > 0 else (glyphs[0] if self.g.unicode else "_")
            out.append(self.c(token if value > 0 else "faint", ch))
        return "".join(out)

    def stacked(self, parts: list[tuple[str, float]], width: int) -> str:
        """One-line stacked bar: [(token, value), ...] scaled to `width`."""
        total = sum(value for _, value in parts) or 1
        cells: list[str] = []
        used = 0
        for index, (token, value) in enumerate(parts):
            n = width - used if index == len(parts) - 1 else int(round(value / total * width))
            n = max(0, min(n, width - used))
            if value > 0 and n == 0 and used < width:
                n = 1
            cells.append(self.c(token, self.g.full * n))
            used += n
        if used < width:
            cells.append(self.c("faint", self.g.empty * (width - used), dim=True))
        return "".join(cells)

    def rule(self, width: int, token="border", label: str = "") -> str:
        if label:
            body = f" {label} "
            left = self.g.h * 2
            rest = max(0, width - 2 - visible_len(body))
            return self.c(token, left) + body + self.c(token, self.g.h * rest)
        return self.c(token, self.g.h * width)

    def box(self, title: str, body: list[str], w: int, h: int, focused: bool = False,
            right: str = "", token=None) -> list[str]:
        """Rounded panel exactly `w` x `h`. Body lines are clipped/padded; missing rows are blank."""
        w, h = max(4, w), max(3, h)
        border = token or ("accent" if focused else "border")
        g = self.g
        label = f" {title} " if title else ""
        head_text = self.c("fg" if not focused else border, label, bold=True) if label else ""
        tail = f" {right} " if right else ""
        fill = w - 4 - visible_len(label) - visible_len(tail)
        if fill < 0:
            label, tail, fill = clip(label, w - 4), "", 0
            head_text = self.c(border, label, bold=True)
        top = (
            self.c(border, g.tl + g.h) + head_text + self.c(border, g.h * max(0, fill))
            + (self.c("dim", tail) if tail else "") + self.c(border, g.h + g.tr)
        )
        inner = w - 4
        rows = [top]
        for index in range(h - 2):
            line = body[index] if index < len(body) else ""
            rows.append(self.c(border, g.v) + " " + pad(line, inner) + " " + self.c(border, g.v))
        rows.append(self.c(border, g.bl + g.h * (w - 2) + g.br))
        return rows


def hstack(blocks: list[list[str]], widths: list[int], gap: int = 1) -> list[str]:
    """Join equal-height-ish blocks side by side; shorter blocks are padded with blanks."""
    height = max((len(block) for block in blocks), default=0)
    out = []
    for row in range(height):
        parts = []
        for block, width in zip(blocks, widths):
            line = block[row] if row < len(block) else ""
            parts.append(pad(line, width))
        out.append((" " * gap).join(parts))
    return out


def split_width(total: int, weights: list[int], gap: int = 1) -> list[int]:
    """Divide `total` columns by `weights`, leaving `gap` between neighbours."""
    usable = total - gap * (len(weights) - 1)
    weight_sum = sum(weights)
    sizes = [max(1, usable * weight // weight_sum) for weight in weights]
    sizes[-1] += usable - sum(sizes)
    return sizes


def wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap (plain text only)."""
    out: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        words, line = paragraph.split(" "), ""
        for word in words:
            if line and visible_len(line) + 1 + visible_len(word) > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip() if line else word
        out.append(line)
    return out


def humanize(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600}h"
