"""ui.app: state, key handling, live refresh and the render loop of `ai ui`."""

from __future__ import annotations

import collections
import threading
import time

from lib.ui import art, data, view_main, view_ops
from lib.ui.demo import DemoWorld
from lib.ui.style import THEMES, Style, humanize
from lib.ui.term import Terminal, clip, color_mode, pad, supports_unicode, terminal_size, visible_len, write_frame
from lib.ui.widgets import chip, event_icon

SCREENS = [
    ("dashboard", "Dashboard", "Dash"), ("tasks", "Tasks", "Task"), ("board", "Board", "Brd"), ("specs", "Specs", "Spec"),
    ("agents", "Agents", "Agnt"), ("locks", "Locks", "Lock"), ("activity", "Activity", "Act"), ("health", "Health", "Hlth"),
    ("metrics", "Metrics", "Metr"), ("project", "Project", "Proj"),
]
SCREEN_KEYS = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6, "8": 7, "9": 8, "0": 9}
RENDERERS = {
    "dashboard": view_main.render_dashboard, "tasks": view_main.render_tasks, "board": view_main.render_board,
    "specs": view_main.render_specs, "agents": view_ops.render_agents, "locks": view_ops.render_locks,
    "activity": view_ops.render_activity, "health": view_ops.render_health, "metrics": view_ops.render_metrics,
    "project": view_ops.render_project,
}
HINTS = {
    "dashboard": "n next-as  v art  r refresh  p pause",
    "tasks": "↑↓ select  Enter detail  PgUp/PgDn scroll  f filter  / search  s spec",
    "board": "←→ column  ↑↓ card  Enter open",
    "specs": "↑↓ select  PgUp/PgDn scroll",
    "agents": "↑↓ select", "locks": "↑↓ select", "activity": "↑↓ scroll  f type  / search",
    "health": "↑↓ scroll", "metrics": "", "project": "↑↓ scroll",
}
TASK_FILTERS = [None, "active", "todo", "in_progress", "changes_requested", "review", "blocked", "done"]
SCROLL_ONLY = {"health", "project"}
ROLES = [None, "chief", "implementer", "reviewer"]
MIN_W, MIN_H = 80, 20


class Loader(threading.Thread):
    """Reads the workspace off the UI thread so animation never stutters."""

    def __init__(self, app: "App", interval: float, demo: DemoWorld | None) -> None:
        super().__init__(daemon=True)
        self.app, self.interval, self.demo = app, interval, demo
        self.stop_event = threading.Event()
        self.kick = threading.Event()
        self.lock = threading.Lock()
        self.latest: dict | None = None
        self.loops = 0

    def run(self) -> None:
        while not self.stop_event.is_set():
            if not self.app.paused or self.loops == 0 or self.kick.is_set():
                self.kick.clear()
                try:
                    if self.demo is not None:
                        self.demo.tick(time.time())
                        snap = self.demo.snapshot(self.app.role)
                    else:
                        snap = data.load_snapshot(role=self.app.role, agent=self.app.agent, deep=self.loops % 8 == 0)
                except Exception as exc:  # noqa: BLE001 - keep the UI alive, show the reason
                    snap = {"errors": [f"refresh failed: {exc}"]}
                with self.lock:
                    self.latest = snap
                self.loops += 1
            self.kick.wait(self.interval)

    def take(self) -> dict | None:
        with self.lock:
            snap, self.latest = self.latest, None
        return snap

    def stop(self) -> None:
        self.stop_event.set()
        self.kick.set()


class App:
    def __init__(self, theme: str = "aurora", anim: bool = True, no_color: bool = False, ascii_only: bool = False,
                 role: str | None = None, agent: str | None = None) -> None:
        self.mode = color_mode(no_color)
        self.unicode = supports_unicode() and not ascii_only
        self.theme = theme if theme in THEMES else "aurora"
        self.st = Style(self.mode, self.theme, self.unicode)
        self.snap: dict = {}
        self.t = 0
        self.screen = 0
        self.sel: dict = collections.defaultdict(int)
        self.scroll: dict = collections.defaultdict(int)
        self.filter_status: str | None = None
        self.event_filter: str | None = None
        self.search = ""
        self.search_mode = False
        self.focus = "list"
        self.anim = anim
        self.paused = False
        self.role = role
        self.agent = agent
        self.hero = art.Hero()
        self.show_help = False
        self.toasts: list[tuple[str, float]] = []
        self.confetti: art.Confetti | None = None
        self.board_cols: list[list[str]] = []
        self.loader: Loader | None = None
        self.last_refresh = time.time()

    # --- state helpers ------------------------------------------------------
    @property
    def name(self) -> str:
        return SCREENS[self.screen][0]

    def clamp(self, key: str, count: int) -> None:
        self.sel[key] = max(0, min(self.sel[key], count - 1)) if count else 0

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.st = Style(self.mode, theme, self.unicode)

    def toast(self, text: str, seconds: float = 6.0) -> None:
        self.toasts.append((text, time.time() + seconds))
        self.toasts = self.toasts[-3:]

    def apply_snapshot(self, new: dict) -> None:
        old = self.snap
        if old and "tasks" in new:
            before = old.get("events", {}).get("total", 0)
            after = new.get("events", {}).get("total", 0)
            if after > before:
                for event in new["events"]["recent"][-min(3, after - before):]:
                    if event.get("event") != "probe":
                        glyph = event_icon(self.st, str(event.get("event")))
                        detail = " ".join(str(event[k]) for k in ("task", "agent") if event.get(k))
                        self.toast(f"{glyph} {str(event.get('event')).replace('task_', '')} {detail}")
            if new.get("counts", {}).get("done", 0) > old.get("counts", {}).get("done", 0) and self.anim:
                w, h = terminal_size()
                self.confetti = art.Confetti(w, h, seed=self.t)
        if "findings" not in new and "findings" in old:
            new["findings"] = old["findings"]
        if "tasks" not in new and old:
            new = {**old, "errors": new.get("errors", [])}
        self.snap = new
        self.last_refresh = time.time()

    # --- keys ---------------------------------------------------------------
    def handle_key(self, key: str) -> bool:
        """Returns False when the user asked to quit."""
        if self.show_help:
            self.show_help = False
            return True
        if self.search_mode:
            if key == "enter":
                self.search_mode = False
            elif key == "esc":
                self.search_mode, self.search = False, ""
            elif key == "backspace":
                self.search = self.search[:-1]
            elif len(key) == 1 and key.isprintable():
                self.search += key
            self.sel["tasks"] = 0
            self.sel["activity"] = 0
            return True
        if key in ("q", "ctrl-c", "eof"):
            return False
        if key == "?":
            self.show_help = True
        elif key in SCREEN_KEYS:
            self.goto(SCREEN_KEYS[key])
        elif key == "tab":
            self.goto((self.screen + 1) % len(SCREENS))
        elif key == "backtab":
            self.goto((self.screen - 1) % len(SCREENS))
        elif key == "r" and self.loader:
            self.loader.kick.set()
            self.toast("refreshing…", 1.5)
        elif key == "p":
            self.paused = not self.paused
            self.toast("live refresh paused" if self.paused else "live refresh resumed", 2)
        elif key == "t":
            names = list(THEMES)
            self.set_theme(names[(names.index(self.theme) + 1) % len(names)])
            self.toast(f"theme: {self.theme}", 2)
        elif key == "a":
            self.anim = not self.anim
            self.toast("animations " + ("on" if self.anim else "off"), 2)
        elif key == "v":
            self.toast(f"art: {self.hero.cycle()}", 2)
        elif key == "n":
            self.role = ROLES[(ROLES.index(self.role) + 1) % len(ROLES)]
            if self.loader:
                self.loader.kick.set()
        elif key == "/" and self.name in ("tasks", "activity"):
            self.search_mode = True
        elif key == "f":
            self.cycle_filter()
        elif key == "esc":
            if self.focus == "detail":
                self.focus = "list"
            else:
                self.search, self.filter_status, self.event_filter = "", None, None
        else:
            self.navigate(key)
        return True

    def goto(self, index: int) -> None:
        self.screen = index
        self.focus = "list"

    def cycle_filter(self) -> None:
        if self.name == "tasks":
            self.filter_status = TASK_FILTERS[(TASK_FILTERS.index(self.filter_status) + 1) % len(TASK_FILTERS)]
            self.sel["tasks"] = 0
        elif self.name == "activity":
            kinds = [None] + view_ops.event_kinds(self)
            current = kinds.index(self.event_filter) if self.event_filter in kinds else 0
            self.event_filter = kinds[(current + 1) % len(kinds)]
            self.sel["activity"] = 0

    def navigate(self, key: str) -> None:
        name = self.name
        step = {"up": -1, "k": -1, "down": 1, "j": 1}.get(key, 0)
        page = {"pgup": -10, "pgdn": 10}.get(key, 0)
        if name in SCROLL_ONLY:
            self.scroll[name] = max(0, self.scroll[name] + step + page)
            return
        if name == "board":
            self.navigate_board(key, step)
            return
        if name == "tasks" and self.focus == "detail" and step:
            self.scroll["tasks"] = max(0, self.scroll["tasks"] + step)
            return
        if step and name in ("tasks", "specs", "agents", "locks", "activity"):
            self.sel[name] += step
            self.scroll[name] = 0
        if page and name in ("tasks", "specs"):
            self.scroll[name] = max(0, self.scroll[name] + page)
        if key == "g" and name in ("tasks", "specs", "agents", "locks", "activity"):
            self.sel[name] = 0
        if key == "G" and name in ("tasks", "specs", "agents", "locks", "activity"):
            self.sel[name] = 10 ** 6
        if key == "enter" and name == "tasks":
            self.focus = "detail" if self.focus == "list" else "list"
        if key == "s" and name == "tasks":
            self.jump_to_spec()

    def navigate_board(self, key: str, step: int) -> None:
        if key in ("left", "h"):
            self.sel["board_col"] = max(0, self.sel["board_col"] - 1)
            self.sel["board_row"] = 0
        elif key in ("right", "l"):
            self.sel["board_col"] = min(len(self.board_cols) - 1, self.sel["board_col"] + 1)
            self.sel["board_row"] = 0
        elif step:
            self.sel["board_row"] = max(0, self.sel["board_row"] + step)
        elif key == "enter" and self.board_cols:
            col = self.board_cols[min(self.sel["board_col"], len(self.board_cols) - 1)]
            if col:
                task_id = col[min(self.sel["board_row"], len(col) - 1)]
                self.filter_status, self.search = None, ""
                ids = [t["id"] for t in view_main.visible_tasks(self)]
                self.sel["tasks"] = ids.index(task_id) if task_id in ids else 0
                self.goto(1)
                self.focus = "detail"

    def jump_to_spec(self) -> None:
        tasks = view_main.visible_tasks(self)
        if not tasks:
            return
        task_id = tasks[min(self.sel["tasks"], len(tasks) - 1)]["id"]
        for index, spec in enumerate(self.snap.get("specs", [])):
            if spec["task"] == task_id:
                self.sel["specs"] = index
                self.goto(3)
                return
        self.toast(f"task {task_id} has no spec", 2)

    # --- drawing ------------------------------------------------------------
    def header(self, w: int) -> str:
        st, snap = self.st, self.snap
        proj = snap.get("project", {})
        left = st.gradient(".ai", "accent", "accent2", bold=True) + " " + st.c("fg", proj.get("name", "workspace"), bold=True) \
            + st.c("faint", f"  v{proj.get('version', '')} ") + chip(st, str(proj.get("mode", "lite")).upper(), "accent2")
        if snap.get("demo"):
            left += " " + chip(st, "DEMO", "warn")
        git = snap.get("git", {})
        right_parts = []
        if git.get("repo"):
            dirty = len(git.get("dirty", []))
            right_parts.append(st.c("info", "⎇ " if self.unicode else "git:") + st.c("fg", str(git.get("branch"))) + (st.c("warn", f" +{dirty}") if dirty else ""))
        if self.paused:
            right_parts.append(st.c("warn", "paused"))
        else:
            right_parts.append((art.spinner(st, self.t, "ok") if self.anim else st.c("ok", st.g.dot)) + st.c("dim", " live"))
        right_parts.append(st.c("dim", time.strftime("%H:%M:%S")))
        right = "  ".join(right_parts)
        gap = w - visible_len(left) - visible_len(right)
        return left + " " * max(1, gap) + right

    def tabs(self, w: int) -> str:
        st, snap = self.st, self.snap
        counts = snap.get("counts", {})
        active = sum(v for k, v in counts.items() if k != "done")
        badges = {
            "tasks": str(active) if active else "", "locks": str(len(snap.get("locks", []))) if snap.get("locks") else "",
            "agents": str(len(snap.get("agents", []))) if snap.get("agents") else "",
            "health": str(len(snap.get("findings", []))) if snap.get("findings") else "",
            "specs": str(len(snap.get("specs", []))) if snap.get("specs") else "",
        }
        for mode in (1, 2, 3):
            parts = []
            for index, (key, label, short) in enumerate(SCREENS):
                num = "0" if index == 9 else str(index + 1)
                text = label if mode == 1 else (short if mode == 2 else "")
                badge = badges.get(key, "")
                body = f" {num} {text}".rstrip() + (f" {badge}" if badge and mode < 3 else "") + " "
                parts.append((index, num, text, badge, body))
            if sum(len(p[4]) for p in parts) + len(parts) <= w or mode == 3:
                break
        out = []
        for index, num, text, badge, body in parts:
            if index == self.screen:
                out.append(st.reverse(body, "accent"))
            else:
                label = st.c("accent2", num) + st.c("dim", (" " + text) if text else "")
                if badge:
                    token = "warn" if SCREENS[index][0] == "health" else "faint"
                    label += " " + st.c(token, badge)
                out.append(" " + label + " ")
        return " ".join(out)

    def footer(self, w: int) -> str:
        st = self.st
        if self.search_mode:
            return st.c("accent", " /") + st.c("fg", self.search) + st.c("accent", "▌" if self.t // 5 % 2 else " ") + st.c("faint", "   Enter keep  Esc clear")
        left = st.c("faint", " ") + st.c("accent2", "?") + st.c("dim", " help  ") + st.c("accent2", "q") + st.c("dim", " quit  ") + st.c("dim", HINTS.get(self.name, ""))
        age = time.time() - self.last_refresh
        right = st.c("faint", f"{self.snap.get('load_ms', 0)}ms · {humanize(age)} ago · {self.theme}")
        if self.filter_status or self.event_filter or self.search:
            right = st.c("warn", "filtered ") + right
        gap = w - visible_len(left) - visible_len(right)
        return left + " " * max(1, gap) + right

    def compose(self, w: int, h: int) -> list[str]:
        st = self.st
        if w < MIN_W or h < MIN_H:
            lines = [""] * h
            msg = f"terminal too small: {w}x{h} (need {MIN_W}x{MIN_H})"
            lines[h // 2] = pad(st.c("warn", msg), w, "center")
            return lines
        body_h = h - 4
        renderer = RENDERERS[self.name]
        body = renderer(self, w, body_h)
        if self.toasts:
            self.toasts = [(text, until) for text, until in self.toasts if until > time.time()]
            body = self.overlay_toasts(body, w)
        if self.confetti:
            if self.confetti.alive:
                self.confetti.step()
                body = self.confetti.overlay(st, body)
            else:
                self.confetti = None
        rule = art.heartbeat(st, w, self.t) if self.anim else st.rule(w)
        lines = [self.header(w), self.tabs(w), rule] + body[:body_h] + [self.footer(w)]
        if self.show_help:
            lines = lines[:3] + view_ops.overlay(self, lines[3:3 + body_h], w, body_h) + lines[3 + body_h:]
        return [clip(line, w, "") for line in lines][:h]

    def overlay_toasts(self, body: list[str], w: int) -> list[str]:
        st = self.st
        out = list(body)
        width = 38
        for index, (text, _) in enumerate(reversed(self.toasts)):
            row = 1 + index * 3
            if row + 2 >= len(out):
                break
            box = st.box("", [text], width, 3, token="accent2")
            for k, line in enumerate(box):
                out[row + k] = pad(clip(out[row + k], w - width - 1, ""), w - width - 1) + " " + line
        return out


# --- entry points -----------------------------------------------------------

def build_app(args) -> tuple[App, DemoWorld | None]:
    app = App(theme=args.theme, anim=not args.no_anim, no_color=args.no_color, ascii_only=args.ascii,
              role=args.role, agent=args.agent)
    if args.screen:
        names = [s[0] for s in SCREENS]
        app.screen = names.index(args.screen)
    return app, (DemoWorld() if args.demo else None)


def render_once(args, width: int | None, height: int | None) -> str:
    app, demo = build_app(args)
    if demo is not None:
        demo.tick(time.time() + 100)
        app.snap = demo.snapshot(app.role)
    else:
        app.snap = data.load_snapshot(role=app.role, agent=app.agent)
    app.t = args.frame
    w, h = terminal_size()
    lines = app.compose(width or w, height or h)
    return "\n".join(lines)


def run(args) -> int:
    app, demo = build_app(args)
    loader = Loader(app, args.refresh, demo)
    app.loader = loader
    loader.start()
    frame_period = 1 / 12
    try:
        with Terminal() as term:
            w, h = terminal_size()
            if not args.no_splash and app.anim:
                rain = art.Rain(w, h, seed=5)
                total = 26
                for frame in range(total):
                    w, h = terminal_size()
                    write_frame(art.splash_frame(app.st, rain, w, h, frame, total), None, w)
                    if term.read_key(1 / 20) is not None:
                        break
                while loader.latest is None:
                    time.sleep(0.02)
            previous: list[str] | None = None
            size = (0, 0)
            while True:
                snap = loader.take()
                if snap is not None:
                    app.apply_snapshot(snap)
                w, h = terminal_size()
                if (w, h) != size:
                    size, previous = (w, h), None
                    import sys
                    sys.stdout.write("\x1b[2J")
                app.t += 1
                lines = app.compose(w, h)
                write_frame(lines, previous, w)
                previous = lines
                key = term.read_key(frame_period if app.anim or app.toasts else 0.25)
                while key is not None:
                    if not app.handle_key(key):
                        return 0
                    key = term.read_key(0)
    except KeyboardInterrupt:
        return 130
    finally:
        loader.stop()
