"""Specs ekranı — spec dosya listesi ve içerik görüntüleyici."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Label, ListItem, ListView, Static

from .base import DataScreen


class SpecContentPanel(ScrollableContainer):
    """Seçili spec dosyasının içeriği."""

    DEFAULT_CSS = """
    SpecContentPanel {
        width: 70%;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._spec = None
        self._body = Static(id="spec-body")

    def compose(self) -> ComposeResult:
        yield self._body

    def on_mount(self) -> None:
        self._render_body()

    def set_spec(self, spec: dict | None) -> None:
        self._spec = spec
        self._render_body()

    def _render_body(self) -> None:
        if not self._spec:
            self._body.update("[dim]Select a spec file to view its contents…[/dim]")
            return

        name = self._spec.get("name", "spec")
        path = self._spec.get("path", "")
        size = self._spec.get("size", 0)
        content = self._spec.get("content", "") or ""
        header = (
            f"[bold #58a6ff]━━ {name} ━━[/bold #58a6ff]\n"
            f"[dim]{path} · {size} bytes[/dim]\n\n"
        )
        self._body.update(header + content.replace("[", r"\["))


class SpecsScreen(DataScreen):
    """Spec dosya listesi ve içerik ekranı."""

    refresh_interval = 20

    DEFAULT_CSS = """
    SpecsScreen {
        layout: horizontal;
        height: 1fr;
    }
    #spec-list-panel {
        width: 30%;
        border-right: solid #30363d;
        layout: vertical;
    }
    #spec-list-view {
        height: 1fr;
    }
    .spec-section-header {
        color: #58a6ff;
        text-style: bold;
        padding: 1 1 0 1;
        height: 2;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._specs: dict = {"active": [], "done": []}
        self._spec_map: dict = {}

    def fetch_data(self):
        return {"specs": self.provider.get_specs()}

    def apply_data(self, data) -> None:
        specs = data.get("specs", {}) if isinstance(data, dict) else {}
        self._specs = {
            "active": list(specs.get("active", [])),
            "done": list(specs.get("done", [])),
        }

    def compose(self) -> ComposeResult:
        active = self._specs.get("active", [])
        done = self._specs.get("done", [])
        self._spec_map = {}

        with Vertical(id="spec-list-panel"):
            yield Static("[bold #58a6ff]Spec Files[/bold #58a6ff]", classes="spec-section-header")
            with ListView(id="spec-list-view"):
                if not self._loaded:
                    yield ListItem(Label(self.loading_text()), id="loading")
                elif self._error:
                    yield ListItem(Label(self.error_text()), id="error")
                elif not active and not done:
                    yield ListItem(Label("[dim]No spec files found[/dim]"), id="empty")
                else:
                    if active:
                        yield ListItem(Label("[yellow]── Active ──[/yellow]"), id="hdr-active")
                        for index, spec in enumerate(active):
                            item_id = f"spec-active-{index}"
                            self._spec_map[item_id] = spec
                            yield ListItem(
                                Label(f"  [cyan]{spec.get('name', '?')}[/cyan]"),
                                id=item_id,
                            )
                    if done:
                        yield ListItem(Label("[dim]── Done ──[/dim]"), id="hdr-done")
                        for index, spec in enumerate(done):
                            item_id = f"spec-done-{index}"
                            self._spec_map[item_id] = spec
                            yield ListItem(
                                Label(f"  [dim]{spec.get('name', '?')}[/dim]"),
                                id=item_id,
                            )

        yield SpecContentPanel(id="spec-content-panel")

    def _show_spec(self, item_id: str) -> None:
        spec = self._spec_map.get(item_id or "")
        self.query_one("#spec-content-panel", SpecContentPanel).set_spec(spec)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None:
            self._show_spec(event.item.id or "")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._show_spec(event.item.id or "")
