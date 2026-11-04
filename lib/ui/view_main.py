"""ui.view_main: Dashboard, Tasks, Board and Specs screens.

Every `render_*` takes the running `App` (state + snapshot + style) and the
body size, and returns exactly `h` lines of at most `w` columns.
"""

from __future__ import annotations

from lib.ui import art
from lib.ui.data import STATUS_ORDER
from lib.ui.style import STATUS_LABEL, STATUS_TOKEN, hstack, humanize, split_width, wrap
from lib.ui.term import clip, pad
from lib.ui.widgets import (
    chip,
    event_icon,
    fit,
    hhmm,
    kv,
    labelled_bar,
    priority_mark,
    scroll_view,
    scrollbar,
    status_chip,
    when,
    window,
)

PIPELINE = ["todo", "in_progress", "review", "done"]


# --- shared task helpers ----------------------------------------------------

def visible_tasks(app) -> list[dict]:
    """Tasks after the status filter and the search text (shared by the key handler)."""
    tasks = app.snap.get("tasks", [])
    mode = app.filter_status
    if mode == "active":
        tasks = [t for t in tasks if t["folder"] == "active"]
    elif mode:
        tasks = [t for t in tasks if t["status"] == mode]
    if app.search:
        needle = app.search.lower()
        tasks = [t for t in tasks if needle in (t["id"] + " " + t["title"] + " " + str(t["owner"] or "")).lower()]
    return tasks


def pipeline_line(app, task: dict, width: int) -> str:
    """todo ── progress ── review ── done, with the current stage lit (and animated when in progress)."""
    st = app.st
    status = task["status"]
    here = {"changes_requested": "in_progress", "blocked": "todo"}.get(status, status)
    index = PIPELINE.index(here) if here in PIPELINE else 0
    labels = {"todo": "todo", "in_progress": "doing", "review": "review", "done": "done"}
    seg = max(2, (width - 34) // 3)
    parts = []
    for i, name in enumerate(PIPELINE):
        lit = i <= index
        token = STATUS_TOKEN.get(status if i == index else name, "dim") if lit else "faint"
        parts.append(st.c(token, (st.g.dot if i == index else (st.g.tick if lit and st.g.unicode else st.g.ring)) + " " + labels[name], bold=(i == index)))
        if i < len(PIPELINE) - 1:
            if i == index and status == "in_progress":
                parts.append(" " + art.marquee(st, seg, app.t, "progress") + " ")
            else:
                parts.append(" " + st.c("accent" if i < index else "faint", st.g.h * seg) + " ")
    return "".join(parts)


def mini_pipeline(app, task: dict) -> str:
    st = app.st
    status = task["status"]
    here = {"changes_requested": "in_progress", "blocked": "todo"}.get(status, status)
    index = PIPELINE.index(here) if here in PIPELINE else 0
    cells = []
    for i in range(4):
        if i <= index:
            cells.append(st.c(STATUS_TOKEN.get(status, "dim"), "■" if st.g.unicode else "#"))
        else:
            cells.append(st.c("faint", "□" if st.g.unicode else "."))
    return "".join(cells)


def crit_bar(app, task: dict, width: int) -> str:
    st = app.st
    total = task["criteria_total"]
    if not total:
        return st.c("faint", "no criteria")
    ratio = task["criteria_done"] / total
    return st.bar(ratio, max(3, width - 6), "ok" if ratio >= 1 else "accent") + " " + st.c("dim", f"{task['criteria_done']}/{total}")


# --- dashboard --------------------------------------------------------------

def render_dashboard(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    wide = w >= 112
    top_h = 12 if h >= 34 else (10 if h >= 26 else 8)
    rec = (snap.get("now") or {}).get("recommended") or {}
    need = 1 + len(wrap(rec.get("why") or "", w - 6)) + len(rec.get("extra") or [])
    next_h = max(4, min(8 if h >= 34 else 6, need + 2))
    bottom_h = max(7, h - top_h - next_h)

    # --- top row: progress | pipeline | hero --------------------------------
    counts = snap.get("counts", {})
    total = snap.get("total_tasks", 0)
    done = counts.get("done", 0)
    pct = int(round(snap.get("progress", 0) * 100))
    parts = [(STATUS_TOKEN[s], counts.get(s, 0)) for s in STATUS_ORDER if counts.get(s, 0)]
    donut_rows = max(5, top_h - 4)
    ring = art.donut(st, parts or [("faint", 1)], donut_rows)
    big = art.big_number(f"{pct}%", st, "accent")
    prog_body: list[str] = []
    ring_w = donut_rows * 2 + 1
    side = [""] * max(0, (donut_rows - 4) // 2) + big + ["", st.c("dim", f"{done}/{total} tasks done"),
                                                        st.c("dim", f"weighted {int(snap.get('progress_weighted', 0) * 100)}%")]
    for i in range(donut_rows):
        prog_body.append(pad(ring[i], ring_w) + "  " + (side[i] if i < len(side) else ""))
    if total == 0:
        prog_body = art.mascot(st, "sleep" if not snap.get("events", {}).get("total") else "idle", app.t) + [
            "", st.c("dim", "no tasks yet")]
    progress_w = ring_w + 2 + 20 if wide else max(34, w // 3)
    hero_w = 30 if wide else 0
    pipe_w = w - progress_w - hero_w - (2 if wide else 1)
    box_progress = st.box("Progress", prog_body, progress_w, top_h)

    pipe_inner = pipe_w - 4
    pipe: list[str] = []
    stack_parts = [(STATUS_TOKEN[s], counts.get(s, 0)) for s in STATUS_ORDER]
    pipe.append(st.stacked(stack_parts, pipe_inner) if total else st.c("faint", st.g.empty * pipe_inner))
    legend = []
    for s in STATUS_ORDER:
        legend.append(st.c(STATUS_TOKEN[s], st.g.dot) + " " + st.c("dim", STATUS_LABEL[s].lower()) + " " + st.c("fg", str(counts.get(s, 0)), bold=True))
    pipe.append("  ".join(legend[:3]))
    pipe.append("  ".join(legend[3:]))
    crit = snap.get("criteria", {"done": 0, "total": 0})
    ratio = crit["done"] / crit["total"] if crit["total"] else 0
    pipe.append("")
    pipe.append(labelled_bar(st, "criteria", ratio, pipe_inner, "ok", f"{crit['done']}/{crit['total']}", 9, app.t // 2 if app.anim else None))
    pipe.append(labelled_bar(st, "weighted", snap.get("progress_weighted", 0), pipe_inner, "accent", f"{int(snap.get('progress_weighted', 0) * 100)}%", 9, app.t // 2 if app.anim else None))
    days = snap.get("events", {}).get("per_day", [])
    spark_w = max(8, min(28, pipe_inner - 24))
    pipe.append("")
    pipe.append(st.c("dim", pad("activity 28d", 12)) + st.spark(days[-spark_w:], spark_w, "accent2") + " " + st.c("dim", f"{sum(days)} events"))
    box_pipe = st.box("Pipeline", pipe, pipe_w, top_h)
    blocks = [box_progress, box_pipe]
    widths = [progress_w, pipe_w]
    if wide:
        hero_inner_w, hero_inner_h = hero_w - 4, top_h - 2
        hero = app.hero.render(st, hero_inner_w, hero_inner_h, app.t) if app.anim or app.t < 2 else app.hero.render(st, hero_inner_w, hero_inner_h, 20)
        blocks.append(st.box(f"{app.hero.kind}", hero, hero_w, top_h, right="v"))
        widths.append(hero_w)
    rows = hstack(blocks, widths, 1)

    # --- NEXT ----------------------------------------------------------------
    rows += render_next_box(app, w, next_h)

    # --- bottom: active work | (activity over locks & agents) ----------------
    if w >= 100:
        cw = split_width(w, [3, 2])
        feed_h = max(5, (bottom_h * 11) // 20)
        right_col = render_feed_box(app, cw[1], feed_h) + render_side_box(app, cw[1], bottom_h - feed_h)
        rows += hstack([render_active_work(app, cw[0], bottom_h), right_col], cw, 1)
    elif w >= 84:
        cw = split_width(w, [5, 4])
        rows += hstack([render_active_work(app, cw[0], bottom_h), render_feed_box(app, cw[1], bottom_h)], cw, 1)
    else:
        rows += render_active_work(app, w, bottom_h)
    return fit(rows, h)


def render_next_box(app, w: int, h: int) -> list[str]:
    st = app.st
    rec = (app.snap.get("now") or {}).get("recommended") or {}
    cmd = rec.get("cmd")
    role = app.role or "any role"
    body: list[str] = []
    if cmd:
        body.append(st.c("accent", st.g.arrow, bold=True) + " " + st.c("fg", cmd, bold=True))
    elif rec.get("needs_human") or rec.get("question"):
        body.append(st.c("warn", st.g.warn + " waiting for a human decision", bold=True))
    else:
        body.append(st.c("ok", st.g.tick + " nothing to run right now", bold=True))
    why = rec.get("why") or rec.get("blocker") or ""
    for line in wrap(why, w - 6)[: max(1, h - 4)]:
        body.append(st.c("dim", line))
    for extra in (rec.get("extra") or [])[: max(0, h - 2 - len(body))]:
        body.append(st.c("faint", "  " + extra))
    return st.box("Next command", body, w, h, right=f"view as: {role}  (n)", token="accent2")


def render_active_work(app, w: int, h: int) -> list[str]:
    st = app.st
    inner = w - 4
    tasks = [t for t in app.snap.get("tasks", []) if t["folder"] == "active"]
    body: list[str] = []
    if not tasks:
        body = art.mascot(st, "done" if app.snap.get("total_tasks") else "idle", app.t)
        body += ["", st.c("dim", "no active work."), st.c("faint", "chief: ai now --role chief")]
        return st.box("Active work", body, w, h)
    title_w = max(8, inner - 5 - 2 - 5 - 12 - 12)
    for task in tasks[: h - 2]:
        owner = task["owner"] or "-"
        line = (
            st.c("dim", pad(task["id"], 5)) + priority_mark(st, task["priority"]) + " "
            + mini_pipeline(app, task) + " "
            + st.status(task["status"], pad(STATUS_LABEL.get(task["status"], task["status"]).lower(), 12))
            + pad(task["title"], title_w) + st.c("accent2", pad(owner, 12, "right"))
        )
        body.append(line)
    return st.box("Active work", body, w, h, right=f"{len(tasks)}")


def render_feed_box(app, w: int, h: int) -> list[str]:
    st = app.st
    events = [e for e in app.snap.get("events", {}).get("recent", []) if e.get("event") != "probe"]
    body = []
    for event in reversed(events[-(h - 2):]):
        name = str(event.get("event"))
        detail = " ".join(f"{k}:{event[k]}" for k in ("task", "agent") if event.get(k))
        body.append(f"{st.c('faint', hhmm(event.get('timestamp')))} {event_icon(st, name)} {st.c('fg', name.replace('task_', ''))} {st.c('dim', detail)}")
    if not body:
        body = [st.c("faint", "no events recorded yet"), "", art.spinner(st, app.t) + " " + st.c("dim", "listening…")]
    return st.box("Live activity", body, w, h, right=art.spinner(st, app.t, "ok") if app.anim else "")


def render_side_box(app, w: int, h: int) -> list[str]:
    st, snap = app.st, app.snap
    body: list[str] = []
    locks = snap.get("locks", [])
    body.append(st.c("accent", "leases", bold=True) + st.c("dim", f"  {len(locks)} held"))
    for lock in locks[:3]:
        token = {"held": "ok", "stale": "warn", "corrupt": "err"}.get(lock.get("state"), "dim")
        body.append(st.c(token, st.g.dot) + " " + st.c("fg", str(lock.get("resource")), bold=False) + " " + st.c("dim", str(lock.get("agent"))))
    if not locks:
        body.append(st.c("faint", "  none"))
    body.append("")
    agents = snap.get("agents", [])
    body.append(st.c("accent", "agents", bold=True) + st.c("dim", f"  {len(agents)}"))
    for agent in agents[:4]:
        busy = bool(agent["tasks"])
        body.append(st.c("ok" if busy else "faint", st.g.dot) + " " + st.c("fg", pad(agent["name"], 14)) + st.c("dim", ",".join(agent["tasks"]) or "idle"))
    if not agents:
        body.append(st.c("faint", "  none seen yet"))
    handoffs = snap.get("handoffs", [])
    if handoffs:
        body.append("")
        body.append(st.c("warn", f"{st.g.warn} {len(handoffs)} handoff(s) pending", bold=True))
    return st.box("Locks & agents", body, w, h)


# --- tasks ------------------------------------------------------------------

def render_tasks(app, w: int, h: int) -> list[str]:
    st = app.st
    tasks = visible_tasks(app)
    app.clamp("tasks", len(tasks))
    sel = app.sel["tasks"]
    list_w = max(34, int(w * 0.42)) if w >= 90 else w
    detail_w = w - list_w - 1
    inner_h = h - 2
    title = "Tasks"
    flags = []
    if app.filter_status:
        flags.append(f"filter:{app.filter_status}")
    if app.search:
        flags.append(f"/{app.search}")
    right = " ".join(flags + [f"{len(tasks)}/{len(app.snap.get('tasks', []))}"])
    body: list[str] = []
    start, end = window(len(tasks), sel, inner_h)
    inner = list_w - 4
    for index in range(start, end):
        t = tasks[index]
        title_w = max(6, inner - 5 - 2 - 4 - 1)
        line = (st.c("dim", pad(t["id"], 5)) + priority_mark(st, t["priority"]) + " " + mini_pipeline(app, t) + " "
                + st.status(t["status"], pad(t["title"], title_w)))
        if t["status"] == "done":
            line = st.c("faint", clip(f"{t['id']:<5}  ✔  {t['title']}" if st.g.unicode else f"{t['id']:<5}  v  {t['title']}", inner))
        body.append(st.selected(pad(line, inner)) if index == sel else line)
    if not tasks:
        body = art.mascot(st, "sleep", app.t) + ["", st.c("dim", "no tasks match." if app.snap.get("tasks") else "no tasks yet.")]
    box_list = st.box(title, body, list_w, h, focused=app.focus != "detail", right=right)
    if list_w == w:
        return box_list
    detail = render_task_detail(app, tasks[sel] if tasks else None, detail_w, h)
    return hstack([box_list, detail], [list_w, detail_w], 1)


def render_task_detail(app, task: dict | None, w: int, h: int) -> list[str]:
    st = app.st
    inner = w - 6
    if not task:
        return st.box("Detail", [st.c("faint", "select a task")], w, h, focused=app.focus == "detail")
    lines: list[str] = []
    lines.append(st.c("fg", task["title"], bold=True))
    lines.append(status_chip(st, task["status"]) + "  " + st.c("dim", "priority ") + priority_mark(st, task["priority"])
                 + "  " + st.c("dim", "owner ") + st.c("accent2", task["owner"] or "-"))
    lines.append("")
    lines.append(pipeline_line(app, task, inner))
    lines.append("")
    if task["criteria"]:
        lines.append(st.c("accent", "Acceptance criteria", bold=True) + "  " + crit_bar(app, task, 22))
        for done, text in task["criteria"]:
            box = st.c("ok", st.g.check_on) if done else st.c("dim", st.g.check_off)
            wrapped = wrap(text, inner - 4) or [""]
            lines.append(f" {box} " + st.c("fg" if not done else "dim", wrapped[0]))
            lines += ["     " + st.c("dim", extra) for extra in wrapped[1:]]
        lines.append("")
    meta = [
        ("spec", task["spec_ref"] or "-"), ("branch", task["branch"] or "-"),
        ("depends on", ", ".join(task["depends_on"]) or "-"), ("waiting on", task["waiting_on"]),
        ("locks", ", ".join(task["locks"]) or "-"), ("allowed", ", ".join(task["scope_allowed"]) or "-"),
        ("forbidden", ", ".join(task["scope_forbidden"]) or "-"),
        ("submitted by", task["submitted_by"] or "-"), ("reviewed by", task["reviewed_by"] or "-"),
        ("created", when(task["created"])), ("updated", when(task["updated"])),
    ]
    lines.append(st.c("accent", "Details", bold=True))
    for key, value in meta:
        lines.append(kv(st, key, st.c("fg", clip(str(value), max(4, inner - 14))), 13))
    ev = task["evidence"]
    ev_token = {"green": "ok", "failed": "err", "stale": "warn", "partial": "warn", "invalidated": "err", "none": "dim"}.get(ev, "dim")
    lines.append(kv(st, "evidence", st.c(ev_token, str(ev)) + " " + st.c("faint", clip(task["evidence_summary"] or "", max(4, inner - 24))), 13))
    mins = task["checkpoint_minutes"]
    lines.append(kv(st, "checkpoint", st.c("dim", "none") if mins is None else st.c("warn" if mins > 30 else "ok", humanize(mins * 60) + " ago"), 13))
    if task["intent"]:
        lines += ["", st.c("accent", "Intent", bold=True)] + [st.c("dim", line) for line in wrap(task["intent"], inner)[:6]]
    if task["plan"]:
        lines += ["", st.c("accent", "Plan", bold=True)] + [st.c("dim", line) for line in wrap(task["plan"], inner)[:8]]
    if task["log"]:
        lines += ["", st.c("accent", "History", bold=True)]
        for entry in task["log"][-8:]:
            if entry["kind"] == "transition":
                arrow = f"{entry['from'] or '-'} {st.g.arrow} {entry['to']}"
                lines.append(st.c("faint", entry["at"][5:16].replace("T", " ")) + " " + st.c("accent2", pad(entry["actor"], 10))
                             + " " + st.status(entry["to"], arrow) + " " + st.c("dim", clip(entry["reason"], max(4, inner - 44))))
            else:
                lines.append(st.c("dim", clip(entry["text"], inner)))
    view, offset, more = scroll_view(lines, app.scroll["tasks"], h - 2)
    app.scroll["tasks"] = offset
    bar = scrollbar(st, h - 2, len(lines), offset)
    body = [pad(line, inner) + " " + bar[i] if i < len(bar) else line for i, line in enumerate(view)]
    return st.box(f"#{task['id']}", body, w, h, focused=app.focus == "detail", right="PgDn ▾" if more else "")


# --- board ------------------------------------------------------------------

def board_columns(app, w: int) -> list[tuple[str, list[str]]]:
    if w >= 108:
        return [("TODO", ["todo"]), ("IN PROGRESS", ["in_progress"]), ("CHANGES", ["changes_requested"]),
                ("REVIEW", ["review"]), ("BLOCKED", ["blocked"]), ("DONE", ["done"])]
    return [("TODO", ["todo", "blocked"]), ("DOING", ["in_progress", "changes_requested"]),
            ("REVIEW", ["review"]), ("DONE", ["done"])]


def board_cards(app, statuses: list[str]) -> list[dict]:
    return [t for t in app.snap.get("tasks", []) if t["status"] in statuses]


def render_board(app, w: int, h: int) -> list[str]:
    st = app.st
    cols = board_columns(app, w)
    app.board_cols = [[t["id"] for t in board_cards(app, statuses)] for _, statuses in cols]
    app.sel["board_col"] = max(0, min(app.sel["board_col"], len(cols) - 1))
    widths = split_width(w, [1] * len(cols), 1)
    blocks = []
    for ci, ((name, statuses), cw) in enumerate(zip(cols, widths)):
        cards = board_cards(app, statuses)
        focused = ci == app.sel["board_col"]
        row = max(0, min(app.sel["board_row"], len(cards) - 1)) if focused else -1
        if focused:
            app.sel["board_row"] = max(0, row)
        inner = cw - 4
        token = STATUS_TOKEN[statuses[0]]
        body: list[str] = []
        for index, task in enumerate(cards):
            sel = focused and index == row
            card = [st.c("dim", task["id"]) + " " + priority_mark(st, task["priority"]) + " " + st.c(token, pad("", 0))]
            card[0] += mini_pipeline(app, task)
            for tl in wrap(task["title"], inner)[:2]:
                card.append(st.c("fg", tl, bold=sel))
            owner = task["owner"] or "unassigned"
            card.append(st.c("accent2", clip(owner, inner)))
            if task["status"] == "in_progress":
                card.append(art.marquee(st, min(inner, 12), app.t + index * 3, "progress"))
            elif task["criteria_total"]:
                card.append(crit_bar(app, task, inner))
            if task["status"] == "blocked":
                card.append(st.c("err", clip("waiting: " + str(task["waiting_on"]), inner)))
            card.append(st.c("faint", st.g.h * inner))
            body += [st.selected(pad(line, inner)) if sel else line for line in card]
        if not cards:
            body = [st.c("faint", "empty")]
        _, offset, _ = scroll_view(body, 0, h - 2)
        start = 0
        if focused and cards:
            per = max(1, len(body) // len(cards))
            start = max(0, min(row * per - (h - 2) // 3, max(0, len(body) - (h - 2))))
        body = body[start:]
        blocks.append(st.box(f"{name} {len(cards)}", body, cw, h, focused=focused, token=token if focused else None))
    return hstack(blocks, widths, 1)


# --- specs ------------------------------------------------------------------

SPEC_TOKEN = {"draft": "warn", "approved": "info", "in progress": "progress", "shipped": "ok", "done": "ok"}


def render_specs(app, w: int, h: int) -> list[str]:
    st = app.st
    specs = app.snap.get("specs", [])
    app.clamp("specs", len(specs))
    sel = app.sel["specs"]
    list_w = max(36, int(w * 0.40)) if w >= 90 else w
    inner = list_w - 4
    body: list[str] = []
    start, end = window(len(specs), sel, h - 2)
    for index in range(start, end):
        spec = specs[index]
        token = "warn" if spec["template"] else SPEC_TOKEN.get(spec["status"], "dim")
        ratio = spec["criteria_done"] / spec["criteria_total"] if spec["criteria_total"] else 0
        line = (st.c(token, st.g.dot) + " " + st.c("dim", pad(spec["task"] or "--", 5))
                + st.c("fg", pad(spec["title"], max(8, inner - 22))) + " "
                + st.bar(ratio, 8, "ok" if ratio >= 1 else "accent") + " " + st.c("dim", pad(f"{spec['criteria_done']}/{spec['criteria_total']}", 4)))
        body.append(st.selected(pad(line, inner)) if index == sel else line)
    if not specs:
        body = art.mascot(st, "idle", app.t) + ["", st.c("dim", "no specs yet."), st.c("faint", "ai task new creates one per task")]
    box_list = st.box("Specs", body, list_w, h, focused=True, right=f"{len(specs)}")
    if list_w == w:
        return box_list
    dw = w - list_w - 1
    di = dw - 6
    lines: list[str] = []
    if specs:
        spec = specs[sel]
        token = "warn" if spec["template"] else SPEC_TOKEN.get(spec["status"], "dim")
        lines.append(st.c("fg", spec["title"], bold=True))
        lines.append(chip(st, spec["status"].upper(), token) + "  " + st.c("dim", "task ") + st.c("accent2", spec["task"] or "-")
                     + "  " + st.c("dim", "approved by ") + st.c("fg", str(spec["approved_by"] or "-")))
        lines.append(st.c("faint", spec["ref"]))
        if spec["template"]:
            lines += ["", st.c("warn", f"{st.g.warn} still the template: no real acceptance criteria yet")]
        lines += ["", st.c("accent", "Intent", bold=True)] + [st.c("dim", x) for x in (wrap(spec["intent"], di) if spec["intent"] else ["-"])]
        lines += ["", st.c("accent", "Acceptance criteria", bold=True) + "  "
                  + st.bar(spec["criteria_done"] / spec["criteria_total"] if spec["criteria_total"] else 0, 14, "ok") + " "
                  + st.c("dim", f"{spec['criteria_done']}/{spec['criteria_total']}")]
        for done, text in spec["criteria"]:
            mark = st.c("ok", st.g.check_on) if done else st.c("dim", st.g.check_off)
            wrapped = wrap(text, di - 4) or [""]
            lines.append(f" {mark} " + st.c("dim" if done else "fg", wrapped[0]))
            lines += ["     " + st.c("dim", extra) for extra in wrapped[1:]]
        if spec["changed"]:
            lines += ["", st.c("accent", "Behavior", bold=True)] + [st.c("dim", x) for x in spec["changed"].splitlines()[:12]]
        if spec["out_of_scope"]:
            lines += ["", st.c("accent", "Out of scope", bold=True)] + [st.c("dim", x) for x in wrap(spec["out_of_scope"], di)[:6]]
    view, offset, more = scroll_view(lines, app.scroll["specs"], h - 2)
    app.scroll["specs"] = offset
    bar = scrollbar(st, h - 2, len(lines), offset)
    detail = [pad(line, di) + " " + bar[i] if i < len(bar) else line for i, line in enumerate(view)]
    box_detail = st.box("Spec", detail, dw, h, right="PgDn ▾" if more else "")
    return hstack([box_list, box_detail], [list_w, dw], 1)
