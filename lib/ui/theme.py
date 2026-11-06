"""Renk paleti ve CSS."""

COLORS = {
    "todo": "#8b949e",
    "in_progress": "#d29922",
    "review": "#fb8500",
    "blocked": "#f85149",
    "changes_requested": "#ff7b72",
    "done": "#3fb950",
    "header": "#58a6ff",
    "border": "#30363d",
    "bg": "#0d1117",
    "surface": "#161b22",
    "accent": "#1f6feb",
}

STATUS_COLORS = {
    "todo": "dim",
    "in_progress": "yellow",
    "review": "orange1",
    "blocked": "red",
    "changes_requested": "red1",
    "done": "green",
}

STATUS_ICONS = {
    "todo": "○",
    "in_progress": "●",
    "review": "★",
    "blocked": "✕",
    "changes_requested": "↺",
    "done": "✓",
}

EVENT_COLORS = {
    "task_claimed": "cyan",
    "task_reviewed": "yellow",
    "task_merged": "green",
    "task_done": "bright_green",
    "task_blocked": "red",
    "lock_acquired": "blue",
    "lock_released": "dim",
    "checkpoint": "magenta",
}

CSS = """
Screen {
    background: #0d1117;
}

Header {
    background: #161b22;
    color: #58a6ff;
    height: 3;
}

Footer {
    background: #161b22;
    color: #8b949e;
}

.panel {
    border: solid #30363d;
    padding: 0 1;
    margin: 0 1 1 0;
}

.panel-title {
    color: #58a6ff;
    text-style: bold;
}

.status-todo { color: #8b949e; }
.status-in_progress { color: #d29922; }
.status-review { color: #fb8500; }
.status-blocked { color: #f85149; }
.status-done { color: #3fb950; }

.metric-box {
    border: solid #30363d;
    padding: 1 2;
    margin: 0 1 1 0;
    width: 1fr;
    height: 7;
    content-align: center middle;
}

.metric-value {
    text-style: bold;
    color: #58a6ff;
}

.nav-tab {
    background: #0d1117;
    color: #8b949e;
    padding: 0 2;
}

.nav-tab.-active {
    background: #1f6feb;
    color: white;
}

#sidebar {
    width: 30%;
    border-right: solid #30363d;
}

#main-content {
    width: 70%;
}

.event-row {
    height: 1;
    padding: 0 1;
}

.next-cmd {
    background: #1f6feb22;
    border: solid #1f6feb;
    padding: 0 2;
    color: #58a6ff;
}

#task-list-panel {
    width: 35%;
    border-right: solid #30363d;
}

#task-detail-panel {
    width: 65%;
    padding: 1 2;
}

#spec-list-panel {
    width: 30%;
    border-right: solid #30363d;
}

#spec-content-panel {
    width: 70%;
    padding: 1 2;
}

.detail-label {
    color: #8b949e;
}

.detail-value {
    color: #e6edf3;
}

.section-header {
    color: #58a6ff;
    text-style: bold;
    padding: 1 0 0 0;
}

.agent-card {
    border: solid #30363d;
    padding: 1 2;
    margin: 0 1 1 0;
    height: auto;
}

.agent-name {
    color: #58a6ff;
    text-style: bold;
}

.bar-label {
    color: #8b949e;
    width: 20;
}

.bar-value {
    color: #58a6ff;
}

LogsScreen {
    padding: 0;
}

#log-scroll {
    height: 1fr;
}
"""
