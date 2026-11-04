"""Tasks ekranı — filtrelenebilir task listesi ve detay paneli."""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView, Static

from ..theme import COLORS, STATUS_ICONS
from .base import DataScreen


def _status_color(status: str) -> str:
    return COLORS.get(status, "#8b949e")


class TaskDetailPanel(Static):
    """Seçili task detayı."""

    def __init__(self, task=None, **kwargs):
        super().__init__(**kwargs)
        # NOT: `_task` Textual'ın Widget sınıfında message-pump task'ı için
        # kullanılıyor; çakışmamak için veriyi ayrı bir isimde tutuyoruz.
        self._task_data = task

    def set_task(self, task):
        self._task_data = task
        self.refresh()

    def render(self) -> str:
        if not self._task_data:
            return "[dim]Select a task to view details…[/dim]"

        t = self._task_data
        status = t.get("status", "todo")
        color = _status_color(status)
        icon = STATUS_ICONS.get(status, "?")

        lines = [
            "[bold #58a6ff]━━ Task Detail ━━[/bold #58a6ff]\n",
            f"[dim]ID:[/dim]       [bold white]{t.get('id', 'N/A')}[/bold white]",
            f"[dim]Title:[/dim]    [bold white]{t.get('title', 'N/A')}[/bold white]",
            f"[dim]Status:[/dim]   [{color}]{icon} {status}[/{color}]",
            f"[dim]Owner:[/dim]    [cyan]{t.get('owner', t.get('agent', 'unassigned')) or 'unassigned'}[/cyan]",
            f"[dim]Priority:[/dim] [yellow]{t.get('priority', 'normal')}[/yellow]",
        ]

        if t.get("spec"):
            lines.append(f"[dim]Spec:[/dim]     [dim]{t.get('spec')}[/dim]")

        if t.get("depends_on"):
            deps = t["depends_on"]
            deps = ", ".join(deps) if isinstance(deps, list) else str(deps)
            lines.append(f"[dim]Depends:[/dim]  [dim]{deps}[/dim]")

        locks = t.get("locks", [])
        if locks:
            lines.append("\n[bold #58a6ff]Locks:[/bold #58a6ff]")
            for lock in (locks if isinstance(locks, list) else [locks]):
                lines.append(f"  [dim]·[/dim] {lock}")

        desc = t.get("description", t.get("desc", ""))
        if desc:
            lines.append("\n[bold #58a6ff]Description:[/bold #58a6ff]")
            lines.append(f"[dim]{str(desc)[:300]}[/dim]")

        for field in ("created_at", "updated_at", "claimed_at"):
            if t.get(field):
                lines.append(
                    f"[dim]{field.replace('_', ' ').title()}:[/dim] "
                    f"[dim]{str(t[field])[:16]}[/dim]"
                )

        return "\n".join(lines)


FILTER_STATES = ["all", "in_progress", "review", "todo", "blocked", "done"]


class TasksScreen(DataScreen):
    """Task listesi ve detay ekranı."""

    refresh_interval = 15

    BINDINGS = [
        Binding("f", "cycle_filter", "Filter", show=True),
    ]

    DEFAULT_CSS = """
    TasksScreen {
        layout: horizontal;
        height: 1fr;
    }
    #task-list-panel {
        width: 38%;
        border-right: solid #30363d;
        layout: vertical;
    }
    #filter-bar {
        height: 3;
        background: #161b22;
        padding: 0 1;
        border-bottom: solid #30363d;
        color: #58a6ff;
    }
    #task-list-view {
        height: 1fr;
    }
    #task-detail-panel {
        width: 62%;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tasks: list = []
        self._filtered: list = []
        self._filter_idx: int = 0
        self._task_map: dict = {}

    # ── veri ──────────────────────────────────────────────────
    def fetch_data(self):
        return {"tasks": self.provider.get_tasks()}

    def apply_data(self, data) -> None:
        self._tasks = data.get("tasks", []) if isinstance(data, dict) else []
        self._apply_filter()

    def _apply_filter(self) -> None:
        state = FILTER_STATES[self._filter_idx]
        if state == "all":
            self._filtered = list(self._tasks)
        else:
            self._filtered = [t for t in self._tasks if t.get("status") == state]

    # ── UI ────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        state = FILTER_STATES[self._filter_idx]
        state_color = "yellow" if state != "all" else "dim"
        self._task_map = {}

        with Vertical(id="task-list-panel"):
            yield Static(
                f"[bold #58a6ff]Tasks[/bold #58a6ff] [dim]Filter: "
                f"[{state_color}]{state}[/] · Press [bold]F[/bold] to cycle[/dim]",
                id="filter-bar",
            )
            with ListView(id="task-list-view"):
                if not self._loaded:
                    yield ListItem(Label(self.loading_text()), id="loading")
                elif self._error:
                    yield ListItem(Label(self.error_text()), id="error")
                elif not self._filtered:
                    yield ListItem(Label("[dim]No tasks for this filter[/dim]"), id="empty")
                else:
                    for index, task in enumerate(self._filtered):
                        item_id = f"task-{index}"
                        self._task_map[item_id] = task
                        status = task.get("status", "todo")
                        icon = STATUS_ICONS.get(status, "?")
                        color = _status_color(status)
                        tid = str(task.get("id", ""))[:8]
                        title = str(task.get("title", "Untitled"))[:30]
                        owner = task.get("owner", task.get("agent", ""))
                        owner_str = f" [dim]@{owner}[/dim]" if owner else ""
                        yield ListItem(
                            Label(f"[{color}]{icon}[/{color}] [dim]{tid}[/dim] {title}{owner_str}"),
                            id=item_id,
                        )

        yield TaskDetailPanel(None, id="task-detail-panel")

    def action_cycle_filter(self) -> None:
        self._filter_idx = (self._filter_idx + 1) % len(FILTER_STATES)
        self._apply_filter()
        self.refresh(recompose=True)

    def _show_task(self, item_id: str) -> None:
        task = self._task_map.get(item_id or "")
        if task:
            self.query_one("#task-detail-panel", TaskDetailPanel).set_task(task)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None:
            self._show_task(event.item.id or "")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._show_task(event.item.id or "")
