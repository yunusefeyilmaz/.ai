"""ui.view_ops: Agents, Locks, Activity, Health, Metrics, Project screens and the help overlay."""

from __future__ import annotations

from lib.config.roles import DEFAULT_ROLES
from lib.runtime.leases import resources_overlap
from lib.ui import art
from lib.ui.style import hstack, humanize, split_width, wrap
from lib.ui.term import clip, pad
from lib.ui.widgets import (
    chip,
    day_hhmm,
    event_icon,
    fit,
    kv,
    labelled_bar,
    scroll_view,
    scrollbar,
    table,
    window,
)

ROLE_BLURB = {
    "orchestrator": "plans the work, splits it into linked tasks, owns the setup interview",
    "planner": "turns a request into tasks with specs and acceptance criteria",
    "implementer": "claims one task, edits under file locks, checks and delivers for review",
    "reviewer": "independent review: merges and approves, or requests changes",
    "qa": "verification-focused reviewer; can request changes or approve",
}


def _scrolled(app, key: str, lines: list[str], w: int, h: int, title: str, right: str = "", focused: bool = True) -> list[str]:
    st = app.st
    view, offset, more = scroll_view(lines, app.scroll[key], h - 2)
    app.scroll[key] = offset
    bar = scrollbar(st, h - 2, len(lines), offset)
    body = [pad(line, w - 6) + " " + bar[i] if i < len(bar) else line for i, line in enumerate(view)]
    return st.box(title, body, w, h, focused=focused, right=right or ("PgDn ▾" if more else ""))


# --- agents -----------------------------------------------------------------

def render_agents(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    config = snap.get("config", {})
    agents = snap.get("agents", [])
    team = config.get("team") or {}
    roles_top = 9 if h >= 28 else 7
    # roles row
    names = [r for r in (config.get("agents") or list(DEFAULT_ROLES)) if r in DEFAULT_ROLES][:5]
    cards = []
    widths = split_width(w, [1] * len(names), 1) if names else [w]
    holders: dict[str, list[str]] = {}
    for agent, entry in team.items():
        for role in (entry or {}).get("roles", []):
            holders.setdefault(role, []).append(agent)
    for name, cw in zip(names, widths):
        body = [st.c("dim", line) for line in wrap(ROLE_BLURB.get(name, ""), cw - 4)[: roles_top - 5]]
        who = ", ".join(holders.get(name, [])) or ("anyone" if not team else "-")
        body.append(st.c("accent2", clip(who, cw - 4)))
        caps = ",".join(DEFAULT_ROLES.get(name, []))
        body.append(st.c("faint", clip(caps, cw - 4)))
        cards.append(st.box(name, body, cw, roles_top, token="accent2" if name in ("orchestrator", "planner") else None))
    rows = hstack(cards, widths, 1) if cards else []
    # agents table
    max_parallel = int((config.get("orchestration") or {}).get("maxParallel", 1) or 1)
    active = snap.get("counts", {}).get("in_progress", 0)
    table_h = h - roles_top - (8 if h >= 34 else 6)
    rows_data = []
    for agent in agents:
        idle = agent.get("idle_seconds")
        token = "ok" if agent["tasks"] else ("warn" if idle is not None and idle < 600 else "faint")
        rows_data.append([
            st.c(token, st.g.dot) + " " + st.c("fg", agent["name"], bold=True),
            st.c("accent2", ",".join(agent["roles"]) if agent["roles"] else "-"),
            st.c("fg", ",".join(agent["tasks"]) or "-"), st.c("dim", ",".join(agent["reviews"]) or "-"),
            st.c("fg", str(agent["locks"])), st.c("dim", str(agent["events"])),
            st.c("dim", humanize(idle) + " ago" if idle is not None else "-"),
            st.c("faint", agent.get("last_event") or "-"),
        ])
    cols = [("AGENT", 20, "left"), ("ROLES", 18, "left"), ("TASKS", 10, "left"), ("REVIEWS", 10, "left"),
            ("LOCKS", 6, "left"), ("EVENTS", 7, "left"), ("LAST SEEN", 11, "left"), ("LAST EVENT", 0, "left")]
    body = table(st, cols, rows_data, app.sel["agents"] if rows_data else None, table_h - 2, w - 4) if rows_data else [
        st.c("faint", "no agent has touched this workspace yet.")] + [""] + art.mascot(st, "sleep", app.t)
    rows += st.box("Agents", body, w, table_h, focused=True, right=f"workers {active}/{max_parallel}")
    # adapters
    adapters = snap.get("adapters", [])
    ad_h = h - roles_top - table_h
    adapter_lines = []
    for ad in adapters:
        mark = st.c("ok", st.g.tick) if ad["wired"] else st.c("faint", st.g.ring)
        adapter_lines.append(f"{mark} {st.c('fg', pad(ad['tool'], 16))} {st.c('dim', pad(ad['entry'], 40))} {st.c('faint', ' '.join(ad['supports']))}")
    half = split_width(w, [3, 2], 1)
    gauge = [labelled_bar(st, "worker slots", min(1.0, active / max_parallel), half[1] - 4, "progress", f"{active}/{max_parallel}", 13),
             "", st.c("dim", f"mode {snap.get('project', {}).get('mode')}  |  review {'on' if (config.get('workflow') or {}).get('requireReview') else 'off'}"),
             st.c("dim", f"checks {(config.get('workflow') or {}).get('requireCheck')}  |  spec {'required' if (config.get('workflow') or {}).get('requireSpec') else 'optional'}")]
    rows += hstack([st.box("Tool adapters", adapter_lines, half[0], ad_h), st.box("Capacity", gauge, half[1], ad_h)], half, 1)
    return fit(rows, h)


# --- locks ------------------------------------------------------------------

def render_locks(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    locks = snap.get("locks", [])
    top_h = max(6, int(h * 0.5))
    rows_data = []
    for lock in locks:
        ttl = lock.get("ttl_seconds") or 1
        remaining = lock.get("remaining_seconds")
        ratio = (remaining or 0) / ttl if isinstance(ttl, int) else 0
        state = lock.get("state", "held")
        token = {"held": "ok", "stale": "warn", "corrupt": "err"}.get(state, "dim")
        rows_data.append([
            st.c("fg", str(lock.get("resource"))), st.c("accent2", str(lock.get("agent"))), st.c("dim", str(lock.get("task") or "-")),
            st.bar(ratio, 14, token if ratio > 0.25 else "warn") + " " + st.c("dim", humanize(remaining)),
            st.c(token, state), st.c("faint", str(lock.get("host") or "")),
        ])
    cols = [("RESOURCE", 30, "left"), ("AGENT", 16, "left"), ("TASK", 7, "left"), ("TTL REMAINING", 24, "left"), ("STATE", 8, "left"), ("HOST", 0, "left")]
    body = table(st, cols, rows_data, app.sel["locks"], top_h - 2, w - 4) if rows_data else [
        st.c("ok", st.g.tick + " no leases held: every resource is free")]
    rows = st.box("Leases", body, w, top_h, focused=True, right=f"{len(locks)} held")
    bottom_h = h - top_h
    half = split_width(w, [1, 1], 1)
    refusals = snap.get("refusals", [])
    ref_lines = []
    for ev in reversed(refusals):
        ref_lines.append(f"{st.c('faint', day_hhmm(ev.get('timestamp')))} {st.c('err', st.g.cross)} {st.c('accent2', str(ev.get('agent')))} "
                         f"{st.c('dim', st.g.arrow)} {st.c('fg', str(ev.get('resource')))} {st.c('dim', 'held by ' + str(ev.get('conflict_agent') or '?'))}")
    if not ref_lines:
        ref_lines = [st.c("ok", st.g.tick + " no refusals recorded")]
    # declared locks per active task (spot overlaps before they bite)
    declared = []
    active = [t for t in snap.get("tasks", []) if t["folder"] == "active" and t["locks"]]
    clashes = set()
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if any(resources_overlap(x, y) for x in a["locks"] for y in b["locks"]):
                clashes.update((a["id"], b["id"]))
    for t in active:
        flag = st.c("warn", st.g.warn + " overlap ") if t["id"] in clashes else "  "
        declared.append(f"{flag}{st.c('dim', pad(t['id'], 5))}{st.c('fg', clip(', '.join(t['locks']), half[1] - 18))}")
    if not declared:
        declared = [st.c("faint", "no active task declares file locks")]
    rows += hstack([st.box("Recent refusals", ref_lines, half[0], bottom_h), st.box("Declared locks (active tasks)", declared, half[1], bottom_h)], half, 1)
    return fit(rows, h)


# --- activity ---------------------------------------------------------------

def event_kinds(app) -> list[str]:
    return sorted({str(e.get("event")) for e in app.snap.get("events", {}).get("recent", []) if e.get("event") != "probe"})


def filtered_events(app) -> list[dict]:
    events = [e for e in app.snap.get("events", {}).get("recent", []) if e.get("event") != "probe"]
    if app.event_filter:
        events = [e for e in events if str(e.get("event")) == app.event_filter]
    if app.search:
        needle = app.search.lower()
        events = [e for e in events if needle in " ".join(str(v) for v in e.values()).lower()]
    return list(reversed(events))


def render_activity(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    side_w = 34 if w >= 100 else 0
    main_w = w - side_w - (1 if side_w else 0)
    events = filtered_events(app)
    app.clamp("activity", len(events))
    inner_h = h - 2
    start, end = window(len(events), app.sel["activity"], inner_h)
    body = []
    for index in range(start, end):
        ev = events[index]
        name = str(ev.get("event"))
        extras = " ".join(f"{k}={v}" for k, v in ev.items() if k not in ("timestamp", "event", "agent", "task") and not str(k).startswith("_"))
        line = (st.c("faint", day_hhmm(ev.get("timestamp"))) + " " + event_icon(st, name) + " " + st.c("fg", pad(name, 22))
                + st.c("accent2", pad(str(ev.get("agent") or "-"), 14)) + st.c("dim", pad(str(ev.get("task") or "-"), 6)) + st.c("faint", extras))
        body.append(st.selected(pad(line, main_w - 4)) if index == app.sel["activity"] else line)
    if not body:
        body = art.mascot(st, "sleep", app.t) + ["", st.c("dim", "no events recorded yet.")]
    flags = " ".join(x for x in (f"filter:{app.event_filter}" if app.event_filter else "", f"/{app.search}" if app.search else "") if x)
    rows = st.box("Activity", body, main_w, h, focused=True, right=(flags + " " if flags else "") + f"{len(events)} events (f)")
    if not side_w:
        return rows
    days = snap.get("events", {}).get("per_day", [0] * 28)
    side: list[str] = [st.c("accent", "last 28 days", bold=True)]
    side += art.heatmap(st, days, 7)
    side += ["", st.c("dim", "trend  ") + st.spark(days, 20, "accent2"), "", st.c("accent", "by agent", bold=True)]
    per_agent = sorted(snap.get("events", {}).get("per_agent", {}).items(), key=lambda x: -x[1])
    top = per_agent[0][1] if per_agent else 1
    for name, count in per_agent[:6]:
        side.append(st.c("fg", pad(name, 12)) + st.bar(count / top, 12, "accent") + " " + st.c("dim", str(count)))
    if not per_agent:
        side.append(st.c("faint", "no agent activity"))
    side += ["", st.c("accent", "by type", bold=True)]
    kinds = sorted(snap.get("events", {}).get("kinds", {}).items(), key=lambda x: -x[1])
    for name, count in [k for k in kinds if k[0] != "probe"][:5]:
        side.append(event_icon(st, name) + " " + st.c("dim", pad(name.replace("task_", ""), 14)) + st.c("fg", str(count)))
    return hstack([rows, st.box("Pulse", side, side_w, h)], [main_w, side_w], 1)


# --- health -----------------------------------------------------------------

def render_health(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    findings = snap.get("findings", [])
    errors = [f for f in findings if f["level"] == "error"]
    warns = [f for f in findings if f["level"] != "error"]
    head_token = "err" if errors else ("warn" if warns else "ok")
    label = "ERRORS" if errors else ("WARNINGS" if warns else "HEALTHY")
    left_w = int(w * 0.55) if w >= 100 else w
    lines = [chip(st, label, head_token) + "  " + st.c("dim", f"{len(errors)} error(s), {len(warns)} warning(s)   (ai doctor)"), ""]
    for f in errors + warns:
        token = "err" if f["level"] == "error" else "warn"
        lines.append(st.c(token, st.g.cross if f["level"] == "error" else st.g.warn, bold=True) + " " + st.c("fg", f["message"]))
        if f.get("hint"):
            lines.append("    " + st.c("accent", st.g.arrow) + " " + st.c("dim", f["hint"]))
    if not findings:
        lines += art.mascot(st, "done", app.t) + ["", st.c("ok", "workspace is consistent. nothing to repair.")]
    for warning in snap.get("warnings", []):
        lines.append(st.c("warn", st.g.warn) + " " + st.c("dim", warning))
    for err in snap.get("errors", []):
        lines.append(st.c("err", st.g.cross) + " " + st.c("dim", "ui: " + err))
    box_find = _scrolled(app, "health", lines, left_w, h, "Doctor", focused=True)
    if left_w == w:
        return box_find
    rw = w - left_w - 1
    right: list[str] = []
    cfg = snap.get("config", {})
    wf = cfg.get("workflow") or {}
    for key, value in (("requireReview", wf.get("requireReview")), ("requireCheck", wf.get("requireCheck")),
                       ("requireSpec", wf.get("requireSpec")), ("chiefOnlyTasks", wf.get("chiefOnlyTasks")),
                       ("autoContinue", wf.get("autoContinue"))):
        on = bool(value) and value != "off"
        right.append((st.c("ok", st.g.tick) if on else st.c("faint", st.g.ring)) + " " + st.c("fg", pad(key, 16)) + st.c("dim", str(value)))
    right += ["", st.c("accent", "Evidence", bold=True)]
    active = [t for t in snap.get("tasks", []) if t["folder"] == "active"]
    for t in active[:8]:
        token = {"green": "ok", "failed": "err", "stale": "warn", "partial": "warn", "invalidated": "err"}.get(t["evidence"], "dim")
        right.append(st.c("dim", pad(t["id"], 5)) + st.c(token, pad(str(t["evidence"]), 12)) + st.c("faint", clip(t["evidence_summary"] or "", rw - 24)))
    if not active:
        right.append(st.c("faint", "no active tasks"))
    right += ["", st.c("accent", "Checkpoints & handoffs", bold=True)]
    warn_after = int((cfg.get("handoff") or {}).get("warnAfterMinutes", 30))
    for c in snap.get("checkpoints", [])[:6]:
        age = c.get("age_minutes")
        ratio = min(1.0, (age or 0) / (warn_after * 2))
        right.append(st.c("dim", pad(c["task"], 5)) + st.bar(ratio, 10, "warn" if (age or 0) > warn_after else "ok") + " " + st.c("dim", humanize((age or 0) * 60)) + " " + st.c("accent2", str(c.get("agent") or "")))
    for hmark in snap.get("handoffs", []):
        right.append(st.c("warn", st.g.warn) + " " + st.c("fg", f"handoff {hmark.get('task')}") + " " + st.c("dim", str(hmark.get("reason") or "")))
    if not snap.get("checkpoints") and not snap.get("handoffs"):
        right.append(st.c("faint", "none"))
    prefs = snap.get("preferences", {})
    right += ["", st.c("accent", "Setup", bold=True),
              (st.c("ok", st.g.tick + " preferences confirmed") if prefs.get("confirmed") else st.c("warn", st.g.warn + " setup interview pending (ai setup)")),
              st.c("dim", "checks: ") + st.c("fg", ", ".join(prefs.get("checks") or []) or "none configured"),
              st.c("dim", f"artifacts quarantined: {snap.get('artifacts', 0)}")]
    return hstack([box_find, st.box("Gates & evidence", right, rw, h)], [left_w, rw], 1)


# --- metrics ----------------------------------------------------------------

def _tile(st, label: str, value: str, sub: str, w: int, token="accent") -> list[str]:
    big = art.big_number(value, st, token) if len(value) <= 5 and all(c in "0123456789%- " for c in value) else [
        "", st.c(token, value, bold=True), ""]
    body = big + [st.c("dim", sub)]
    return st.box(label, body, w, 7)


def render_metrics(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    m = snap.get("metrics") or {}
    ws = split_width(w, [1] * 5, 1)
    med1, med2 = m.get("median_creation_to_done_seconds"), m.get("median_review_to_merge_seconds")
    tiles = [
        _tile(st, "completed", str(m.get("tasks_completed", 0)), "tasks done", ws[0], "ok"),
        _tile(st, "idea → done", humanize(med1) if med1 else "-", "median", ws[1], "accent"),
        _tile(st, "review → merge", humanize(med2) if med2 else "-", "median", ws[2], "accent2"),
        _tile(st, "lock refusals", str(m.get("lock_refusals", 0)), "contention", ws[3], "err" if m.get("lock_refusals") else "dim"),
        _tile(st, "retries", str(m.get("retries", 0)), f"{m.get('resumes', 0)} resumes", ws[4], "warn" if m.get("retries") else "dim"),
    ]
    rows = hstack(tiles, ws, 1)
    rest = h - 7
    half = split_width(w, [1, 1, 1] if w >= 110 else [1, 1], 1)
    counts = snap.get("counts", {})
    total = max(1, snap.get("total_tasks", 0))
    dist = []
    from lib.ui.style import STATUS_LABEL, STATUS_TOKEN
    from lib.ui.data import STATUS_ORDER

    for s in STATUS_ORDER:
        dist.append(labelled_bar(st, STATUS_LABEL[s].lower(), counts.get(s, 0) / total, half[0] - 4, STATUS_TOKEN[s], str(counts.get(s, 0)), 12))
    prio: dict[str, int] = {}
    for t in snap.get("tasks", []):
        prio[t["priority"]] = prio.get(t["priority"], 0) + 1
    dist += ["", st.c("accent", "priority", bold=True)]
    for p, token in (("high", "hot"), ("medium", "warn"), ("low", "dim")):
        dist.append(labelled_bar(st, p, prio.get(p, 0) / total, half[0] - 4, token, str(prio.get(p, 0)), 12))
    per_agent = sorted((m.get("per_agent") or {}).items(), key=lambda x: -x[1])
    top = per_agent[0][1] if per_agent else 1
    agents = [labelled_bar(st, name, count / top, half[1] - 4, "accent2", str(count), 14) for name, count in per_agent[:10]]
    if not agents:
        agents = [st.c("faint", "no per-agent events yet")]
    days = snap.get("events", {}).get("per_day", [0] * 28)
    agents += ["", st.c("accent", "events per day (28d)", bold=True), st.spark(days, half[1] - 6, "accent"), "", *art.heatmap(st, days, 14)]
    boxes = [st.box("Task flow", dist, half[0], rest), st.box("Work by agent", agents, half[1], rest)]
    if len(half) > 2:
        kinds = sorted(snap.get("events", {}).get("kinds", {}).items(), key=lambda x: -x[1])
        ktop = kinds[0][1] if kinds else 1
        klines = [event_icon(st, k) + " " + st.c("dim", pad(k, 22)) + st.bar(v / ktop, max(4, half[2] - 36), "info") + " " + st.c("fg", str(v)) for k, v in kinds[:14] if k != "probe"]
        boxes.append(st.box("Event types", klines or [st.c("faint", "no events")], half[2], rest))
    return fit(rows + hstack(boxes, half, 1), h)


# --- project ----------------------------------------------------------------

def render_project(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    git = snap.get("git", {})
    proj = snap.get("project", {})
    cfg = snap.get("config", {})
    lw = int(w * 0.55) if w >= 100 else w
    g: list[str] = []
    if git.get("repo"):
        dirty = len(git.get("dirty", []))
        g.append(st.c("accent", st.g.dot) + " " + st.c("fg", str(git.get("branch")), bold=True) + st.c("dim", "  @" + str(git.get("head") or "-"))
                 + "  " + (st.c("warn", f"{dirty} dirty") if dirty else st.c("ok", "clean")) + (st.c("dim", f"  {git.get('ahead')} ahead of {git.get('integration')}") if git.get("ahead") is not None else ""))
        g.append(kv(st, "flow", st.c("fg", f"{git.get('production')} ← {git.get('integration')} ← feature branches ({git.get('merge')})"), 12))
        g.append(kv(st, "isolation", st.c("fg", str(git.get("isolation"))), 12))
        g.append("")
        for index, c in enumerate(git.get("commits", [])):
            refs = f" {st.c('warn', '(' + c['refs'] + ')')}" if c.get("refs") else ""
            node = st.c("accent" if index == 0 else "border", "●" if st.g.unicode else "*")
            link = st.c("border", "│" if st.g.unicode else "|")
            g.append(f"{node} {st.c('info', c['hash'])} {st.c('fg', clip(c['subject'], lw - 40))}{refs} {st.c('faint', c['when'])}")
            if index < len(git["commits"]) - 1:
                g.append(link)
    else:
        g = [st.c("warn", "not a git repository (or git is off)"), st.c("dim", "ai git setup")]
    left = _scrolled(app, "project", g, lw, h, "Git", focused=True)
    if lw == w:
        return left
    rw = w - lw - 1
    right: list[str] = [st.c("accent", proj.get("name", ""), bold=True) + st.c("dim", f"   ai {proj.get('version')}   mode {proj.get('mode')}"),
                        st.c("faint", clip(str(proj.get("path")), rw - 4)), ""]
    right.append(st.c("accent", "Decisions (ADR)", bold=True))
    decisions = snap.get("decisions", [])
    for d in decisions[-6:]:
        right.append(st.c("dim", pad(d["file"][:4], 5)) + st.c("fg", clip(d["title"], rw - 18)) + " " + st.c("ok" if d.get("status") == "accepted" else "warn", str(d.get("status") or "")))
    if not decisions:
        right.append(st.c("faint", "none yet (ai decision new)"))
    right += ["", st.c("accent", "Settings", bold=True)]
    for key, value in (
        ("lock ttl", f"{(cfg.get('locks') or {}).get('defaultTtlSeconds')}s (stale after {(cfg.get('locks') or {}).get('staleAfterSeconds')}s)"),
        ("context budget", f"{(cfg.get('budget') or {}).get('contextTokens')} tokens, warn {(cfg.get('budget') or {}).get('warnAtPercent')}%"),
        ("handoff", f"checkpoint every {(cfg.get('handoff') or {}).get('checkpointEveryMinutes')}m"),
        ("workers", str((cfg.get("orchestration") or {}).get("maxParallel"))),
        ("tests", "write tests" if (cfg.get("testing") or {}).get("writeTests") else "optional"),
        ("language", str((cfg.get("language") or {}).get("documents"))),
    ):
        right.append(kv(st, key, st.c("fg", value), 15))
    right += ["", st.c("accent", "Docs", bold=True)]
    for name, note in (("AGENTS.md", "start here"), ("GUIDE.md", "full guide"), ("docs/task-flow.md", "lifecycle"),
                       ("docs/orchestration.md", "multi-agent"), ("docs/recovery.md", "when it breaks")):
        right.append(st.c("accent2", pad(name, 24)) + st.c("dim", note))
    return hstack([left, st.box("Workspace", right, rw, h)], [lw, rw], 1)


# --- help -------------------------------------------------------------------

HELP = [
    ("Screens", [("1-9, 0", "Dashboard, Tasks, Board, Specs, Agents, Locks, Activity, Health, Metrics, Project"),
                 ("Tab / Shift-Tab", "next / previous screen")]),
    ("Move", [("↑ ↓  j k", "select"), ("← →  h l", "board column / switch pane"), ("PgUp PgDn", "scroll the detail pane"),
              ("g  G", "first / last"), ("Enter", "open task from board; focus detail")]),
    ("Find", [("/", "search (Enter keeps it, Esc clears)"), ("f", "cycle filter (status or event type)"),
              ("s", "jump from a task to its spec")]),
    ("Dashboard", [("n", "view NEXT as: any / chief / implementer / reviewer"), ("v", "change the animated panel"),
                   ("r", "refresh now"), ("p", "pause / resume live refresh")]),
    ("Look", [("t", "theme: aurora, ember, matrix, paper"), ("a", "animations on/off"), ("?", "this help"), ("q", "quit")]),
]


def render_help(app, w: int, h: int) -> list[str]:
    st = app.st
    lines: list[str] = []
    for section, items in HELP:
        lines.append(st.c("accent", section, bold=True))
        for key, text in items:
            lines.append("  " + st.c("fg", pad(key, 18), bold=True) + st.c("dim", text))
        lines.append("")
    lines.append(st.c("faint", "The dashboard is read-only: it never changes tasks, locks or Git. Run the commands it shows in a terminal."))
    return lines


def overlay(app, base: list[str], w: int, h: int) -> list[str]:
    """Draw the help panel centred over `base`."""
    st = app.st
    lines = render_help(app, w, h)
    bw = min(w - 4, 84)
    bh = min(h - 2, len(lines) + 2)
    panel = st.box("Help  (any key closes)", lines, bw, bh, focused=True)
    top = max(0, (h - bh) // 2)
    left = max(0, (w - bw) // 2)
    out = list(base)
    for index, row in enumerate(panel):
        if top + index < len(out):
            out[top + index] = pad("", left) + row
    return out
