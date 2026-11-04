"""ui.art: the animated ASCII pieces of the dashboard.

Inspired by the pieces in the ASCII Magic library (digital rain, starfield warp,
spinning torus, pulse rules, spinners, status mascots, confetti). They are
re-implemented here in pure Python so the CLI keeps its "stdlib only" rule: each
piece is a function from a frame counter to a list of text lines.

Every piece takes the `Style`, so it follows the active theme and degrades to
plain ASCII when the terminal cannot draw Unicode.
"""

from __future__ import annotations

import math
import random

from lib.ui.style import Style, lerp
from lib.ui.term import visible_len

# pyfiglet "slant" rendering of ".ai"; plain ASCII, so it is also the no-Unicode fallback.
LOGO = [
    "           _",
    "    ____ _(_)",
    "   / __ `/ /",
    " _/ /_/ / /",
    "(_)__,_/_/",
]
LOGO_ASCII = LOGO
TAGLINE = "tasks · specs · agents · one workspace"


def logo_lines(style: Style) -> list[str]:
    return LOGO if style.g.unicode else LOGO_ASCII


def logo_width(style: Style) -> int:
    return max(visible_len(line) for line in logo_lines(style))


def render_logo(style: Style, t: int = 0, reveal: float = 1.0) -> list[str]:
    """The `.ai` banner with a diagonal gradient; `reveal` < 1 scrambles unsettled cells (decode effect)."""
    rows = logo_lines(style)
    rng = random.Random(t // 2)
    width = logo_width(style)
    noise = "01<>/\\|+*#"
    out = []
    for y, row in enumerate(rows):
        cells = []
        for x, ch in enumerate(row.ljust(width)):
            if ch == " ":
                cells.append(" ")
                continue
            settled = (x / max(1, width)) <= reveal
            shown = ch if settled else rng.choice(noise)
            color = lerp(style.rgb("accent"), style.rgb("accent2"), (x + y * 2) / (width + 10))
            cells.append(style.c(color if settled else "dim", shown, bold=True))
        out.append("".join(cells))
    return out


# --- digital rain -----------------------------------------------------------

class Rain:
    """Falling glyph columns. Stateful: call `step()` once per frame, then `render()`."""

    GLYPHS = "01abcdef:.+*<>=/|"

    def __init__(self, width: int, height: int, seed: int = 7, density: float = 0.55) -> None:
        self.rng = random.Random(seed)
        self.width, self.height = width, height
        self.cols = [self._new_column(initial=True) if self.rng.random() < density else None for _ in range(width)]
        self.density = density

    def _new_column(self, initial: bool = False) -> dict:
        r = self.rng
        return {
            "y": r.uniform(-self.height, self.height if initial else 0),
            "speed": r.uniform(0.35, 1.1),
            "length": r.randint(4, max(5, self.height // 2)),
            "seed": r.random(),
        }

    def resize(self, width: int, height: int) -> None:
        if (width, height) != (self.width, self.height):
            self.__init__(width, height, density=self.density)  # type: ignore[misc]

    def step(self) -> None:
        for index, col in enumerate(self.cols):
            if col is None:
                if self.rng.random() < 0.01:
                    self.cols[index] = self._new_column()
                continue
            col["y"] += col["speed"]
            if col["y"] - col["length"] > self.height:
                self.cols[index] = self._new_column() if self.rng.random() < self.density else None

    def render(self, style: Style, t: int, dim_factor: float = 1.0) -> list[list[str]]:
        grid = [[" "] * self.width for _ in range(self.height)]
        head = style.rgb("accent2")
        tail = style.rgb("accent")
        for x, col in enumerate(self.cols):
            if col is None:
                continue
            for k in range(col["length"]):
                y = int(col["y"]) - k
                if 0 <= y < self.height:
                    fade = 1 - k / col["length"]
                    glyph = self.GLYPHS[(int(col["seed"] * 997) + y * 7 + t // 3 * (k % 3)) % len(self.GLYPHS)]
                    if k == 0:
                        grid[y][x] = style.c((235, 255, 245), glyph, bold=True)
                    else:
                        color = lerp(style.rgb("faint"), lerp(tail, head, 0.25), fade * dim_factor)
                        grid[y][x] = style.c(color, glyph)
        return grid


# --- starfield, torus, wave -------------------------------------------------

class Starfield:
    def __init__(self, count: int = 70, seed: int = 3) -> None:
        self.rng = random.Random(seed)
        self.stars = [self._star(random_z=True) for _ in range(count)]

    def _star(self, random_z: bool = False) -> list[float]:
        r = self.rng
        return [r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0.1, 1.0) if random_z else 1.0]

    def step(self, speed: float = 0.025) -> None:
        for index, star in enumerate(self.stars):
            star[2] -= speed
            if star[2] <= 0.05:
                self.stars[index] = self._star()

    def render(self, style: Style, w: int, h: int) -> list[str]:
        grid = [[" "] * w for _ in range(h)]
        for x, y, z in self.stars:
            sx = int(w / 2 + x / z * w / 4)
            sy = int(h / 2 + y / z * h / 3)
            if 0 <= sx < w and 0 <= sy < h:
                near = 1 - z
                glyph = "." if near < 0.45 else ("+" if near < 0.75 else "*")
                grid[sy][sx] = style.c(lerp(style.rgb("faint"), (255, 255, 255), near), glyph)
        return ["".join(row) for row in grid]


def torus(style: Style, w: int, h: int, t: int) -> list[str]:
    """Spinning donut, shaded with a luminance ramp (the classic)."""
    a, b = t * 0.07, t * 0.035
    ramp = ".,-~:;=!*#$@" if style.g.unicode else ".:-=+*#%@"
    out = [[" "] * w for _ in range(h)]
    zbuf = [[0.0] * w for _ in range(h)]
    sa, ca, sb, cb = math.sin(a), math.cos(a), math.sin(b), math.cos(b)
    theta = 0.0
    while theta < 6.28:
        ct, st = math.cos(theta), math.sin(theta)
        phi = 0.0
        while phi < 6.28:
            sp, cp = math.sin(phi), math.cos(phi)
            circle_x, circle_y = 2 + ct, st
            x = circle_x * (cb * cp + sa * sb * sp) - circle_y * ca * sb
            y = circle_x * (sb * cp - sa * cb * sp) + circle_y * ca * cb
            z = 5 + ca * circle_x * sp + circle_y * sa
            inv = 1 / z
            px = int(w / 2 + w * 0.42 * inv * x * 1.9)
            py = int(h / 2 - h * 0.95 * inv * y * 0.9)
            lum = cp * ct * sb - ca * ct * sp - sa * st + cb * (ca * st - ct * sa * sp)
            if 0 <= px < w and 0 <= py < h and inv > zbuf[py][px]:
                zbuf[py][px] = inv
                idx = max(0, min(len(ramp) - 1, int(lum * 8)))
                out[py][px] = (idx, ramp[idx])
            phi += 0.05
        theta += 0.1
    lines = []
    for row in out:
        cells = []
        for cell in row:
            if cell == " ":
                cells.append(" ")
            else:
                idx, ch = cell
                cells.append(style.c(lerp(style.rgb("faint"), lerp(style.rgb("accent"), style.rgb("accent2"), idx / 11), 0.4 + idx / 18), ch))
        lines.append("".join(cells))
    return lines


def plasma(style: Style, w: int, h: int, t: int) -> list[str]:
    """Sine plasma on a shade ramp."""
    shades = style.g.shade
    lines = []
    for y in range(h):
        cells = []
        for x in range(w):
            v = (math.sin(x / 5.0 + t / 9) + math.sin(y / 2.5 - t / 11) + math.sin((x + y) / 7.0 + t / 14)
                 + math.sin(math.hypot(x - w / 2, (y - h / 2) * 2) / 4 - t / 8))
            n = (v + 4) / 8
            cells.append(style.c(lerp(style.rgb("faint"), lerp(style.rgb("accent"), style.rgb("accent2"), n), n), shades[min(len(shades) - 1, int(n * len(shades)))]))
        lines.append("".join(cells))
    return lines


HERO_KINDS = ("torus", "rain", "stars", "plasma")


class Hero:
    """Switchable animated panel for the dashboard."""

    def __init__(self) -> None:
        self.kind = "torus"
        self.rain: Rain | None = None
        self.stars = Starfield()

    def cycle(self) -> str:
        self.kind = HERO_KINDS[(HERO_KINDS.index(self.kind) + 1) % len(HERO_KINDS)]
        return self.kind

    def render(self, style: Style, w: int, h: int, t: int) -> list[str]:
        w, h = max(4, w), max(2, h)
        if self.kind == "rain":
            if self.rain is None:
                self.rain = Rain(w, h, density=0.7)
            self.rain.resize(w, h)
            self.rain.step()
            return ["".join(row) for row in self.rain.render(style, t)]
        if self.kind == "stars":
            self.stars.step()
            return self.stars.render(style, w, h)
        if self.kind == "plasma":
            return plasma(style, w, h, t)
        return torus(style, w, h, t)


# --- small status pieces ----------------------------------------------------

def spinner(style: Style, t: int, token="accent") -> str:
    frames = style.g.spinner
    return style.c(token, frames[(t // 2) % len(frames)])


def heartbeat(style: Style, width: int, t: int, token="accent") -> str:
    """A flat rule with a pulse sweeping across it (the ASCII Magic 'pulse line')."""
    g = style.g
    pulse = "╱╲╱" if g.unicode else "/\\/"
    pos = (t // 2) % (width + 12) - 6
    cells = []
    for x in range(width):
        d = x - pos
        if 0 <= d < len(pulse):
            cells.append(style.c("hot", pulse[d], bold=True))
        elif -4 <= d < 0:
            cells.append(style.c(lerp(style.rgb("border"), style.rgb(token), (4 + d) / 4), g.h))
        else:
            cells.append(style.c("border", g.h))
    return "".join(cells)


def marquee(style: Style, width: int, t: int, token="progress") -> str:
    """Moving chevrons used on in-progress work ('job queue workers')."""
    chars = "▸▹" if style.g.unicode else ">."
    return "".join(style.c(token, chars[0] if (x + t // 2) % 4 == 0 else chars[1], dim=(x + t // 2) % 4 != 0) for x in range(width))


def big_number(text: str, style: Style, token="accent") -> list[str]:
    """3-row seven-segment-style digits, ASCII-safe."""
    font = {
        "0": (" _ ", "| |", "|_|"), "1": ("   ", "  |", "  |"), "2": (" _ ", " _|", "|_ "),
        "3": (" _ ", " _|", " _|"), "4": ("   ", "|_|", "  |"), "5": (" _ ", "|_ ", " _|"),
        "6": (" _ ", "|_ ", "|_|"), "7": (" _ ", "  |", "  |"), "8": (" _ ", "|_|", "|_|"),
        "9": (" _ ", "|_|", " _|"), "%": ("o /", " / ", "/ o"), "-": ("   ", " _ ", "   "),
        " ": ("   ", "   ", "   "),
    }
    rows = ["", "", ""]
    for ch in text:
        glyph = font.get(ch, font[" "])
        for i in range(3):
            rows[i] += glyph[i] + " "
    return [style.c(token, row, bold=True) for row in rows]


def donut(style: Style, parts: list[tuple[str, float]], rows: int, center: str = "") -> list[str]:
    """Ring chart sampled per character cell (cells are ~2x taller than wide)."""
    width = rows * 2 + 1
    total = sum(value for _, value in parts) or 1
    cx, cy = (width - 1) / 2, (rows - 1) / 2
    lines = []
    for y in range(rows):
        cells = []
        for x in range(width):
            dx = (x - cx) / (width / 2)
            dy = (y - cy) / (rows / 2)
            r = math.hypot(dx, dy)
            if 0.52 <= r <= 1.02:
                angle = (math.atan2(dx, -dy) + 2 * math.pi) % (2 * math.pi) / (2 * math.pi)
                acc, token = 0.0, "faint"
                for part_token, value in parts:
                    acc += value / total
                    if angle <= acc:
                        token = part_token
                        break
                glyph = style.g.full if style.g.unicode else "#"
                if r > 0.96 or r < 0.58:
                    glyph = "▒" if style.g.unicode else "+"
                cells.append(style.c(token, glyph))
            else:
                cells.append(" ")
        lines.append("".join(cells))
    if center:
        mid = rows // 2
        plain = visible_len(center)
        start = max(0, (width - plain) // 2)
        lines[mid] = " " * start + center + " " * max(0, width - start - plain)
    return lines


def heatmap(style: Style, values: list[float], per_row: int, token="accent") -> list[str]:
    """Contribution-style grid: one glyph per value, intensity by magnitude."""
    shades = style.g.shade[1:] if style.g.unicode else ".:*#"
    top = max(values) if values and max(values) > 0 else 1
    rows = []
    for start in range(0, len(values), per_row):
        cells = []
        for value in values[start:start + per_row]:
            if value <= 0:
                cells.append(style.c("faint", "·" if style.g.unicode else "."))
            else:
                level = min(len(shades) - 1, int(value / top * (len(shades) - 1) + 0.5))
                cells.append(style.c(lerp(style.rgb("border"), style.rgb(token), 0.35 + 0.65 * level / (len(shades) - 1)), shades[level] * 1))
        rows.append(" ".join(cells))
    return rows


# --- mascot -----------------------------------------------------------------

def mascot(style: Style, mood: str, t: int) -> list[str]:
    """Friendly robot for empty states. Moods: idle | sleep | done | alert."""
    blink = (t // 6) % 14 == 0
    wave = (t // 5) % 2 == 0
    if style.g.unicode:
        eyes = "─ ─" if blink or mood == "sleep" else ("◉ ◉" if mood != "alert" else "◉ ◉")
        mouth = {"idle": "‿", "sleep": "ᴗ", "done": "▽", "alert": "△"}.get(mood, "‿")
        antenna = {"idle": "●", "sleep": "○", "done": "★", "alert": "▲"}.get(mood, "●")
        rows = [
            f"    {antenna}",
            "    │",
            "  ┌─┴─┐",
            f"  │{eyes}│",
            f"  │ {mouth} │",
            "  └─┬─┘",
            "  ╱ ┴ ╲",
        ]
        if mood in ("idle", "done"):
            rows[5] = ("╲ " if wave else "─ ") + "└─┬─┘"
        if mood == "sleep":
            rows[0] = "    " + ("z" if (t // 8) % 2 else "Z")
    else:
        rows = ["   o", "   |", " [---]", " |o o|", " | - |", " [---]", "  / \\"]
    token = {"idle": "accent", "sleep": "dim", "done": "ok", "alert": "warn"}.get(mood, "accent")
    return [style.c(token, row) for row in rows]


# --- confetti ---------------------------------------------------------------

class Confetti:
    """A short celebratory burst, played when a task reaches done."""

    COLORS = ("accent", "accent2", "ok", "warn", "hot", "info")

    def __init__(self, width: int, height: int, seed: int | None = None) -> None:
        rng = random.Random(seed)
        self.width, self.height = width, height
        self.parts = [
            {"x": rng.uniform(0, width), "y": rng.uniform(-height / 2, 0), "vy": rng.uniform(0.3, 0.9),
             "vx": rng.uniform(-0.3, 0.3), "ch": rng.choice("*+x~o"), "c": rng.choice(self.COLORS)}
            for _ in range(max(12, width // 2))
        ]
        self.age = 0

    @property
    def alive(self) -> bool:
        return self.age < self.height * 2 + 10

    def step(self) -> None:
        self.age += 1
        for p in self.parts:
            p["y"] += p["vy"]
            p["x"] += p["vx"]

    def overlay(self, style: Style, lines: list[str]) -> list[str]:
        """Draw particles over complete lines at the particle cell (plain rows only, wide-safe)."""
        out = list(lines)
        for p in self.parts:
            y, x = int(p["y"]), int(p["x"])
            if 0 <= y < len(out) and 0 <= x < self.width:
                row = out[y]
                if visible_len(row) == 0:
                    out[y] = " " * x + style.c(p["c"], p["ch"], bold=True)
        return out


# --- splash -----------------------------------------------------------------

SPLASH_STEPS = ("reading tasks", "reading specs", "checking locks", "replaying events", "asking git", "ready")


def splash_frame(style: Style, rain: Rain, w: int, h: int, frame: int, total: int) -> list[str]:
    """Startup screen: digital rain, the logo decoding out of noise, a loading bar."""
    rain.resize(w, h)
    rain.step()
    grid = rain.render(style, frame, dim_factor=0.8)
    lines = [list(row) for row in grid]
    logo = render_logo(style, frame, reveal=min(1.0, frame / max(1, total * 0.6)))
    box_w = max(logo_width(style), len(TAGLINE)) + 8
    box_h = len(logo) + 6
    top = max(0, (h - box_h) // 2)
    left = max(0, (w - box_w) // 2)
    progress = min(1.0, frame / max(1, total - 2))
    step = SPLASH_STEPS[min(len(SPLASH_STEPS) - 1, int(progress * len(SPLASH_STEPS)))]
    tagline = TAGLINE[: int(len(TAGLINE) * min(1.0, frame / max(1, total * 0.7)))]
    bar_w = box_w - 8
    content: list[str] = [""] + [" " * ((box_w - logo_width(style)) // 2) + row for row in logo] + [
        "",
        " " * ((box_w - len(TAGLINE)) // 2) + style.c("dim", tagline),
        " " * 4 + style.bar(progress, bar_w, "accent") + "  ",
        " " * 4 + style.c("faint", f"{step}…".ljust(bar_w)),
    ]
    for row in range(box_h):
        y = top + row
        if y >= h:
            break
        text = content[row] if row < len(content) else ""
        cells = [" "] * box_w
        lines[y][left:left + box_w] = cells
        lines[y][left] = text if text else " "
        for x in range(1, box_w):
            lines[y][left + x] = ""
    return ["".join(row) for row in lines]
