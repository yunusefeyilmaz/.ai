"""Agents ekranı — ajan kartları ve aktivite özeti."""
from textual.app import ComposeResult
from textual.widgets import Static

from ..theme import COLORS, STATUS_ICONS
from .base import DataScreen


class AgentCard(Static):
    """Bir ajan için kart."""

    def __init__(self, agent_name: str, tasks: list, events: list, metrics_data: dict, **kwargs):
        super().__init__(**kwargs)
        self._agent = agent_name
        self._agent_tasks = tasks
        self._agent_events = events
        self._agent_metrics = metrics_data

    @staticmethod
    def _agent_name(entry) -> str:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return str(entry.get("id") or entry.get("name") or entry)
        return str(entry)

    def render(self) -> str:
        agent = self._agent

        agent_tasks = [
            t for t in self._agent_tasks
            if t.get("owner") == agent or t.get("agent") == agent
        ]
        active = [t for t in agent_tasks if t.get("status") in ("in_progress", "review")]
        done = [t for t in agent_tasks if t.get("status") == "done"]

        per_agent = self._agent_metrics.get("per_agent", {}) if isinstance(self._agent_metrics, dict) else {}
        agent_metrics = per_agent.get(agent, {}) or {}
        completed_count = agent_metrics.get("tasks_completed", len(done))

        agent_events = [
            e for e in self._agent_events
            if e.get("agent") == agent or e.get("agent_id") == agent
        ]
        last_event = agent_events[0] if agent_events else None

        lines = [f"[bold #58a6ff]◉ Agent: {agent}[/bold #58a6ff]"]
        lines.append(
            f"  [dim]Completed:[/dim] [green]{completed_count}[/green]  "
            f"[dim]Active:[/dim] [yellow]{len(active)}[/yellow]  "
            f"[dim]Total:[/dim] [cyan]{len(agent_tasks)}[/cyan]"
        )

        if active:
            lines.append("  [bold]Active Tasks:[/bold]")
            for task in active[:3]:
                status = task.get("status", "")
                icon = STATUS_ICONS.get(status, "●")
                color = COLORS.get(status, "#d29922")
                title = str(task.get("title", task.get("id", "")))[:35]
                lines.append(f"    [{color}]{icon}[/{color}] {title}")

        if last_event:
            ts = str(last_event.get("timestamp", last_event.get("ts", "")))[:16]
            etype = last_event.get("type", last_event.get("event_type", ""))
            lines.append(f"  [dim]Last activity:[/dim] [dim]{ts}[/dim] [cyan]{etype}[/cyan]")

        return "\n".join(lines)


class AgentsScreen(DataScreen):
    """Agents özet ekranı."""

    refresh_interval = 20

    DEFAULT_CSS = """
    AgentsScreen {
        layout: vertical;
        height: 1fr;
        padding: 1;
        overflow-y: auto;
    }
    .agent-card {
        border: solid #30363d;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }
    .agent-card:hover {
        border: solid #58a6ff;
    }
    #agents-header {
        color: #58a6ff;
        text-style: bold;
        height: 2;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._agents: list = []
        self._tasks: list = []
        self._events: list = []
        self._metrics: dict = {}

    def fetch_data(self):
        provider = self.provider
        config = provider.get_config() or {}
        tasks = provider.get_tasks() or []
        team = config.get("team", {}) if isinstance(config, dict) else {}
        raw_agents = team.get("agents", []) if isinstance(team, dict) else []

        names: list = []
        seen: set = set()
        for entry in raw_agents:
            name = AgentCard._agent_name(entry)
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        for task in tasks:
            for key in ("owner", "agent"):
                value = task.get(key)
                if value and value not in seen:
                    seen.add(value)
                    names.append(value)

        return {
            "agents": names,
            "tasks": tasks,
            "events": provider.get_events(100),
            "metrics": provider.get_metrics() or {},
        }

    def apply_data(self, data) -> None:
        self._agents = data.get("agents", [])
        self._tasks = data.get("tasks", [])
        self._events = data.get("events", [])
        self._metrics = data.get("metrics", {})

    def compose(self) -> ComposeResult:
        yield Static("[bold #58a6ff]━━ Agents ━━[/bold #58a6ff]", id="agents-header")

        if not self._loaded:
            yield Static(self.loading_text())
            return
        if self._error:
            yield Static(self.error_text())
            return
        if not self._agents:
            yield Static("[dim]No agents configured. Check config/workspace.json[/dim]")
            return

        for name in self._agents:
            yield AgentCard(
                name,
                self._tasks,
                self._events,
                self._metrics,
                classes="agent-card",
            )
