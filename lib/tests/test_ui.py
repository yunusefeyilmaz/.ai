"""`ai ui`: the read-only dashboard renders every screen, never writes, and survives odd sizes."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _workspace import copy_project

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.ui import app as ui_app
from lib.ui.demo import DemoWorld
from lib.ui.term import visible_len

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def run(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(workspace / "ai.py"), *args], cwd=str(workspace),
                          capture_output=True, text=True, encoding="utf-8", env=env)


class Args:
    demo = True
    theme = "aurora"
    screen = None
    no_anim = True
    no_splash = True
    no_color = True
    ascii = False
    role = None
    agent = None
    refresh = 2.0
    frame = 3


def make_app(**overrides):
    args = Args()
    for key, value in overrides.items():
        setattr(args, key, value)
    app, demo = ui_app.build_app(args)
    app.snap = demo.snapshot(None)
    return app


class UiTest(unittest.TestCase):
    def test_every_screen_fits_the_terminal(self):
        for size in ((80, 24), (100, 30), (130, 40), (200, 50)):
            for index, (name, _, _) in enumerate(ui_app.SCREENS):
                app = make_app()
                app.screen = index
                lines = app.compose(*size)
                self.assertEqual(len(lines), size[1], f"{name} {size}")
                for line in lines:
                    self.assertLessEqual(visible_len(line), size[0], f"{name} {size}: {line!r}")

    def test_too_small_terminal_says_so(self):
        self.assertIn("too small", "\n".join(make_app().compose(40, 10)))

    def test_ascii_mode_has_no_box_drawing(self):
        app = make_app(ascii=True)
        text = "\n".join(app.compose(120, 36))
        self.assertFalse(re.search(r"[╭╮╰╯│─█]", text))

    def test_color_modes(self):
        app = make_app(no_color=False)
        app.st.mode = "none"
        self.assertFalse(ANSI.search("\n".join(app.compose(110, 30))))

    def test_keys_navigate_without_error(self):
        app = make_app()
        for key in ["2", "down", "j", "enter", "pgdn", "s", "3", "right", "down", "enter", "7", "f", "/", "a", "enter",
                    "9", "?", "x", "t", "v", "0", "tab", "backtab", "g", "G", "esc"]:
            self.assertTrue(app.handle_key(key), key)
            app.compose(120, 36)
        self.assertFalse(app.handle_key("q"))

    def test_demo_world_keeps_moving(self):
        world = DemoWorld()
        before = len(world.events)
        for step in range(1, 40):
            world.tick(step * 5.0)
        self.assertGreater(len(world.events), before)
        snap = world.snapshot("reviewer")
        self.assertEqual(sum(snap["counts"].values()), snap["total_tasks"])

    def test_cli_once_reads_a_real_workspace_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / ".ai"
            copy_project(workspace)
            before = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file())
            result = run(workspace, "ui", "--once", "--no-color", "--width", "110", "--height", "30")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Next command", result.stdout)
            after = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file())
            self.assertEqual([x for x in after if "__pycache__" not in x], [x for x in before if "__pycache__" not in x])


if __name__ == "__main__":
    unittest.main()
