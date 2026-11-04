"""asciimatics intro animasyonu — ".ai" ASCII art splash.

Splash tamamen isteğe bağlıdır:
  * `ai ui --no-splash` ile atlanır,
  * asciimatics yoksa ANSI fallback kullanılır,
  * gerçek bir terminal (TTY) yoksa hiçbir şey basılmaz.
"""
from __future__ import annotations

import sys
import time

# pyfiglet "slant" fontu ile ".ai" (fallback ve figlet yoksa kullanılır)
_AI_LOGO = r"""
           _
    ____ _(_)
   / __ `/ /
 _/ /_/ / /
(_)__,_/_/
"""


def _is_tty() -> bool:
    try:
        return bool(sys.stdout.isatty() and sys.stdin.isatty())
    except Exception:
        return False


def run_splash() -> None:
    """FigletText + Stars animasyonu. Herhangi bir tuşa basınca geçilir."""
    if not _is_tty():
        return

    try:
        from asciimatics.effects import Print, Stars
        from asciimatics.exceptions import ResizeScreenError, StopApplication
        from asciimatics.renderers import FigletText, SpeechBubble
        from asciimatics.scene import Scene
        from asciimatics.screen import Screen
    except ImportError:
        _print_fallback_splash()
        return

    def _handle_input(event):
        raise StopApplication("key pressed")

    def _run(screen):
        title = FigletText(".ai", font="slant")
        subtitle = FigletText("workspace", font="small")

        title_x = max(0, (screen.width - title.max_width) // 2)
        subtitle_x = max(0, (screen.width - subtitle.max_width) // 2)

        effects = [
            Stars(screen, count=150),
            Print(
                screen,
                title,
                y=max(0, screen.height // 2 - 5),
                x=title_x,
                colour=Screen.COLOUR_CYAN,
                attr=Screen.A_BOLD,
            ),
            Print(
                screen,
                subtitle,
                y=max(0, screen.height // 2 + 1),
                x=subtitle_x,
                colour=Screen.COLOUR_BLUE,
                attr=Screen.A_NORMAL,
            ),
            Print(
                screen,
                SpeechBubble("  Press any key to enter the dashboard…  "),
                y=max(0, screen.height // 2 + 5),
                x=max(0, (screen.width - 46) // 2),
                colour=Screen.COLOUR_WHITE,
                attr=Screen.A_NORMAL,
            ),
        ]

        try:
            screen.play(
                [Scene(effects, duration=-1)],
                stop_on_resize=True,
                unhandled_input=_handle_input,
            )
        except (ResizeScreenError, StopApplication):
            pass

    try:
        Screen.wrapper(_run)
    except (ResizeScreenError, StopApplication):
        pass
    except Exception:
        # asciimatics terminalden hoşlanmadıysa sessizce devam et
        pass


def _print_fallback_splash() -> None:
    """Terminal ANSI renkleriyle basit fallback splash."""
    if not _is_tty():
        return

    CYAN = "\033[96m"
    BLUE = "\033[94m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    print(CYAN + BOLD + _AI_LOGO + RESET)
    print(BLUE + "        ai workspace · vibe · ship" + RESET)
    print(DIM + "        Starting dashboard…" + RESET)
    time.sleep(0.6)
