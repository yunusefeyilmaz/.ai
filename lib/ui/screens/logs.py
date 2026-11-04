"""Logs ekranı — canlı event log görüntüleyici."""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Static

from ..theme import EVENT_COLORS
from .base import DataScreen


class LogLine(Static):
    """Tek bir log satırı."""

    def __init__(self, event: dict, **kwargs):
        super().__init__(**kwargs)
        self._event = event or {}

    def render(self) -> str:
        event = self._event
        ts = str(event.get("timestamp", event.get("ts", "??")))[:19]
        etype = str(event.get("type", event.get("event_type", "event")))
        task_id = event.get("task_id", event.get("task", ""))
        agent = event.get("agent", event.get("agent_id", ""))
        details = event.get("details", event.get("data", event.get("message", "")))

        color = EVENT_COLORS.get(etype, "white")

        parts = [f"[dim]{ts}[/dim]"]
        parts.append(f"[{color}]{etype:<25}[/{color}]")
        if task_id:
            parts.append(f"[cyan]{str(task_id)[:10]:<10}[/cyan]")
        if agent:
            parts.append(f"[dim]@{str(agent)[:12]:<12}[/dim]")
        if details and isinstance(details, str):
            parts.append(f"[dim]{details[:60]}[/dim]")

        return " ".join(parts)


class LogsScreen(DataScreen):
    """Canlı event log ekranı."""

    refresh_interval = 5

    BINDINGS = [
        Binding("p", "toggle_pause", "Pause", show=True),
    ]

    DEFAULT_CSS = """
    LogsScreen {
        layout: vertical;
        height: 1fr;
    }
    #logs-header {
        height: 3;
        padding: 0 1;
        background: #161b22;
        border-bottom: solid #30363d;
        color: #58a6ff;
    }
    #log-scroll {
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }
    LogLine {
        height: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._events: list = []
        self._paused = False

    def fetch_data(self):
        return {"events": self.provider.get_events(200)}

    def apply_data(self, data) -> None:
        if self._paused:
            return
        self._events = data.get("events", [])

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        count = len(self._events)
        status = "[yellow]PAUSED[/yellow] · " if self._paused else ""
        yield Static(
            f"[bold #58a6ff]━━ Event Log ━━[/bold #58a6ff]  "
            f"[dim]{status}{count} events · auto-refresh every 5s · newest first · "
            f"[bold]P[/bold] pause[/dim]",
            id="logs-header",
        )
        with ScrollableContainer(id="log-scroll"):
            if not self._loaded:
                yield Static(self.loading_text())
            elif self._error:
                yield Static(self.error_text())
            elif not self._events:
                yield Static("[dim]No events found in runtime/state/events.jsonl[/dim]")
            else:
                for event in self._events:
                    yield LogLine(event)
