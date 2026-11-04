"""Metrics ekranı — istatistikler ve ASCII bar chart'lar."""
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ..theme import COLORS, STATUS_ICONS
from .base import DataScreen


def _make_bar(value: int, max_val: int, width: int = 20, color: str = "#58a6ff") -> str:
    """ASCII bar chart çubuğu."""
    filled = 0 if max_val <= 0 else int((value / max_val) * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{color}]{bar}[/{color}] [bold]{value}[/bold]"


class AgentBarChart(Static):
    """Per-agent task sayıları bar chart."""

    def __init__(self, metrics: dict, tasks: list, **kwargs):
        super().__init__(**kwargs)
        self._metrics = metrics or {}
        self._chart_tasks = tasks or []

    def render(self) -> str:
        lines = ["[bold #58a6ff]━━ Tasks per Agent ━━[/bold #58a6ff]\n"]

        per_agent = self._metrics.get("per_agent", {})
        if not isinstance(per_agent, dict):
            per_agent = {}

        if not per_agent:
            per_agent = {}
            for task in self._chart_tasks:
                agent = task.get("owner", task.get("agent", "unknown")) or "unknown"
                entry = per_agent.setdefault(agent, {"tasks_completed": 0})
                if task.get("status") == "done":
                    entry["tasks_completed"] += 1

        if not per_agent:
            return "\n".join(lines + ["[dim]No agent metrics available[/dim]"])

        values = []
        for data in per_agent.values():
            value = data.get("tasks_completed", 0) if isinstance(data, dict) else data
            values.append(int(value or 0))
        max_val = max(values + [1])

        for agent, data in per_agent.items():
            value = data.get("tasks_completed", 0) if isinstance(data, dict) else data
            value = int(value or 0)
            lines.append(f"[dim]{str(agent)[:15]:<15}[/dim] {_make_bar(value, max_val, 25)}")

        return "\n".join(lines)


class StatusBarChart(Static):
    """Status dağılımı bar chart."""

    def __init__(self, tasks: list, **kwargs):
        super().__init__(**kwargs)
        self._chart_tasks = tasks or []

    def render(self) -> str:
        lines = ["[bold #58a6ff]━━ Status Distribution ━━[/bold #58a6ff]\n"]

        status_counts: dict = {}
        for task in self._chart_tasks:
            status = task.get("status", "todo")
            status_counts[status] = status_counts.get(status, 0) + 1

        if not status_counts:
            return "\n".join(lines + ["[dim]No tasks found[/dim]"])

        max_val = max(status_counts.values(), default=1)
        order = ["in_progress", "review", "blocked", "changes_requested", "todo", "done"]

        for status in order:
            count = status_counts.get(status, 0)
            color = COLORS.get(status, "#8b949e")
            icon = STATUS_ICONS.get(status, "?")
            label = f"{icon} {status[:18]:<18}"
            lines.append(f"[{color}]{label}[/{color}] {_make_bar(count, max_val, 20, color)}")

        return "\n".join(lines)


class NumericMetrics(Static):
    """Sayısal metrikler paneli."""

    def __init__(self, metrics: dict, **kwargs):
        super().__init__(**kwargs)
        self._metrics = metrics or {}

    def render(self) -> str:
        metrics = self._metrics
        lines = ["[bold #58a6ff]━━ Numeric Metrics ━━[/bold #58a6ff]\n"]

        fields = [
            ("tasks_completed", "Tasks Completed", "green"),
            ("tasks_created", "Tasks Created", "cyan"),
            ("tasks_in_progress", "In Progress", "yellow"),
            ("retries", "Retries", "red"),
            ("resumes", "Resumes", "magenta"),
            ("lock_refusals", "Lock Refusals", "red1"),
            ("median_creation_to_done_seconds", "Median Time to Done (s)", "dim"),
        ]

        found_any = False
        for key, label, color in fields:
            value = metrics.get(key)
            if value is not None:
                found_any = True
                lines.append(f"[dim]{label:<30}[/dim] [{color}]{value}[/{color}]")

        if not found_any:
            lines.append("[dim]No metrics data available yet.[/dim]")

        return "\n".join(lines)


class MetricsScreen(DataScreen):
    """Metrics ekranı."""

    refresh_interval = 30

    DEFAULT_CSS = """
    MetricsScreen {
        layout: vertical;
        height: 1fr;
        padding: 1;
        overflow-y: auto;
    }
    #charts-row {
        layout: horizontal;
        height: auto;
        margin: 0 0 1 0;
    }
    #agent-chart {
        width: 1fr;
        border: solid #30363d;
        padding: 1;
        margin: 0 1 0 0;
    }
    #status-chart {
        width: 1fr;
        border: solid #30363d;
        padding: 1;
    }
    #numeric-metrics {
        border: solid #30363d;
        padding: 1;
        height: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._metrics: dict = {}
        self._chart_tasks: list = []

    def fetch_data(self):
        provider = self.provider
        return {"metrics": provider.get_metrics() or {}, "tasks": provider.get_tasks() or []}

    def apply_data(self, data) -> None:
        self._metrics = data.get("metrics", {})
        self._chart_tasks = data.get("tasks", [])

    def compose(self) -> ComposeResult:
        if not self._loaded:
            yield Static(self.loading_text())
            return
        if self._error:
            yield Static(self.error_text())
            return

        with Horizontal(id="charts-row"):
            yield AgentBarChart(self._metrics, self._chart_tasks, id="agent-chart")
            yield StatusBarChart(self._chart_tasks, id="status-chart")

        yield NumericMetrics(self._metrics, id="numeric-metrics")
