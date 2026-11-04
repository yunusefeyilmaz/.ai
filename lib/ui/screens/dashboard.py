"""Dashboard ekranı — ana özet görünümü."""
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ..theme import COLORS, EVENT_COLORS, STATUS_ICONS
from .base import DataScreen


class MetricBox(Static):
    """Tek bir metrik kutusu."""

    def __init__(self, title: str, value: str, color: str = "#58a6ff", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._value = value
        self._color = color

    def render(self) -> str:
        return f"[dim]{self._title}[/dim]\n[bold {self._color}]{self._value}[/bold {self._color}]"


class KanbanPanel(Static):
    """Task kanban özeti."""

    def __init__(self, tasks_data, **kwargs):
        super().__init__(**kwargs)
        self._tasks = tasks_data if isinstance(tasks_data, list) else []

    def render(self) -> str:
        if not self._tasks:
            return "[bold #58a6ff]━━ Task Board ━━[/bold #58a6ff]\n\n[dim]No tasks found[/dim]"

        status_counts: dict = {}
        status_tasks: dict = {}
        for task in self._tasks:
            status = task.get("status", "todo")
            status_counts[status] = status_counts.get(status, 0) + 1
            status_tasks.setdefault(status, []).append(task)

        lines = ["[bold #58a6ff]━━ Task Board ━━[/bold #58a6ff]\n"]
        order = ["in_progress", "review", "blocked", "changes_requested", "todo", "done"]

        for status in order:
            count = status_counts.get(status, 0)
            if not count:
                continue
            icon = STATUS_ICONS.get(status, "?")
            color = COLORS.get(status, "#8b949e")
            lines.append(f"[{color}]{icon} {status.upper().replace('_', ' ')} ({count})[/{color}]")
            for task in status_tasks.get(status, [])[:3]:
                title = str(task.get("title", task.get("id", "?")))[:28]
                tid = str(task.get("id", ""))[:6]
                lines.append(f"  [{color}]·[/{color}] [{tid}] {title}")
            lines.append("")

        return "\n".join(lines)


class EventsPanel(Static):
    """Son event'ler."""

    def __init__(self, events, **kwargs):
        super().__init__(**kwargs)
        self._events = (events or [])[:10]

    def render(self) -> str:
        if not self._events:
            return "[bold #58a6ff]━━ Recent Events ━━[/bold #58a6ff]\n\n[dim]No events found[/dim]"

        lines = ["[bold #58a6ff]━━ Recent Events ━━[/bold #58a6ff]\n"]
        for event in self._events:
            ts = str(event.get("timestamp", event.get("ts", "")))[:16]
            etype = str(event.get("type", event.get("event_type", "event")))
            task_id = str(event.get("task_id", event.get("task", "")))[:8]
            agent = event.get("agent", event.get("agent_id", ""))

            color = EVENT_COLORS.get(etype, "white")
            lines.append(
                f"[dim]{ts}[/dim] [{color}]{etype}[/{color}]"
                + (f" [cyan]{task_id}[/cyan]" if task_id else "")
                + (f" [dim]@{agent}[/dim]" if agent else "")
            )

        return "\n".join(lines)


class InfoPanel(Static):
    """Git + workspace config özeti."""

    def __init__(self, now_data, config_data, **kwargs):
        super().__init__(**kwargs)
        self._now = now_data or {}
        self._cfg = config_data or {}

    def render(self) -> str:
        lines = ["[bold #58a6ff]━━ Workspace Info ━━[/bold #58a6ff]\n"]

        mode = self._cfg.get("mode", "N/A")
        git_on = self._cfg.get("git", {}).get("enabled", False)
        agents = self._cfg.get("team", {}).get("agents", [])

        lines.append(f"[dim]Mode:[/dim]   [yellow]{mode}[/yellow]")
        lines.append(f"[dim]Git:[/dim]    [{'green' if git_on else 'red'}]{'on' if git_on else 'off'}[/]")
        lines.append(f"[dim]Agents:[/dim] [cyan]{len(agents)}[/cyan]")

        role = self._now.get("role", "")
        session_state = self._now.get("session_state", "")
        if role or session_state:
            lines.append("\n[bold #58a6ff]━━ Session ━━[/bold #58a6ff]")
            if role:
                lines.append(f"[dim]Role:[/dim]  [magenta]{role}[/magenta]")
            if session_state:
                lines.append(f"[dim]State:[/dim] [yellow]{session_state}[/yellow]")

        return "\n".join(lines)


class NextCmdPanel(Static):
    """NEXT komut kutusu."""

    def __init__(self, now_data, **kwargs):
        super().__init__(**kwargs)
        self._now = now_data or {}

    def render(self) -> str:
        recommended = self._now.get("recommended", {})
        if not recommended:
            return "[dim]No recommended command[/dim]"

        cmd = recommended.get("cmd", "")
        why = recommended.get("why", "")
        lines = [
            "[bold #58a6ff]▶ NEXT COMMAND[/bold #58a6ff]",
            f"[bold white]{cmd}[/bold white]",
        ]
        if why:
            lines.append(f"[dim]{why}[/dim]")
        return "\n".join(lines)


class DashboardScreen(DataScreen):
    """Ana dashboard ekranı."""

    refresh_interval = 10

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
        height: 1fr;
    }
    #metrics-row {
        height: 7;
        layout: horizontal;
    }
    #middle-row {
        height: 1fr;
        layout: horizontal;
    }
    #bottom-row {
        height: 5;
        border: solid #1f6feb;
        background: #1f6feb22;
        padding: 0 2;
        margin: 1 0 0 0;
        overflow-y: auto;
    }
    #kanban-col {
        width: 40%;
        border: solid #30363d;
        padding: 1;
        margin: 0 1 0 0;
        overflow-y: auto;
    }
    #events-col {
        width: 35%;
        border: solid #30363d;
        padding: 1;
        margin: 0 1 0 0;
        overflow-y: auto;
    }
    #info-col {
        width: 25%;
        border: solid #30363d;
        padding: 1;
        overflow-y: auto;
    }
    """

    def fetch_data(self):
        provider = self.provider
        return {
            "now": provider.get_now(),
            "status": provider.get_status(),
            "events": provider.get_events(20),
            "config": provider.get_config(),
            "tasks": provider.get_tasks(),
            "locks": provider.get_locks(),
        }

    def compose(self) -> ComposeResult:
        if not self._loaded:
            yield Static(self.loading_text(), id="dashboard-loading")
            return
        if self._error:
            yield Static(self.error_text(), id="dashboard-error")
            return

        data = self._data or {}
        tasks = data.get("tasks", [])
        tasks = tasks if isinstance(tasks, list) else []

        active_tasks = sum(1 for t in tasks if t.get("status") != "done")
        done_tasks = sum(1 for t in tasks if t.get("status") == "done")

        locks = data.get("locks", [])
        if isinstance(locks, dict):
            locks = locks.get("locks", [])
        lock_count = len(locks) if isinstance(locks, list) else 0

        cfg = data.get("config", {}) or {}
        agent_count = len(cfg.get("team", {}).get("agents", []))

        with Horizontal(id="metrics-row"):
            yield MetricBox("Active Tasks", str(active_tasks), "#d29922", classes="metric-box")
            yield MetricBox("Done Tasks", str(done_tasks), "#3fb950", classes="metric-box")
            yield MetricBox("Locks", str(lock_count), "#f85149", classes="metric-box")
            yield MetricBox("Agents", str(agent_count), "#58a6ff", classes="metric-box")

        with Horizontal(id="middle-row"):
            yield KanbanPanel(tasks, id="kanban-col")
            yield EventsPanel(data.get("events", []), id="events-col")
            yield InfoPanel(data.get("now", {}), cfg, id="info-col")

        yield NextCmdPanel(data.get("now", {}), id="bottom-row")
