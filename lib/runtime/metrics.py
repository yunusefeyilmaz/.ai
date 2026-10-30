"""runtime.metrics: split out of the former monolithic ai.py."""

from __future__ import annotations

import datetime as dt
import re
import statistics

from lib.core.timeutil import parse_iso
from lib.runtime.events import read_events


def metrics_since(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return dt.datetime.combine(dt.date.fromisoformat(value), dt.time.min, dt.timezone.utc)
        parsed = parse_iso(value)
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    except ValueError as exc:
        raise ValueError("--since must be an ISO date or timestamp") from exc


def event_datetime(event: dict) -> dt.datetime | None:
    try:
        parsed = parse_iso(str(event.get("timestamp") or ""))
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def duration_median(events: list[dict], starts: list[dict], end_type: str) -> float | None:
    starts_by_task: dict[str, list[dt.datetime]] = {}
    for event in starts:
        task = str(event.get("task") or "")
        stamp = event_datetime(event)
        if task and stamp:
            starts_by_task.setdefault(task, []).append(stamp)
    durations = []
    for event in events:
        if event.get("event") != end_type:
            continue
        task = str(event.get("task") or "")
        end = event_datetime(event)
        earlier = [stamp for stamp in starts_by_task.get(task, []) if end and stamp <= end]
        if earlier and end:
            durations.append((end - max(earlier)).total_seconds())
    return float(statistics.median(durations)) if durations else None


def collect_metrics(since: dt.datetime | None = None) -> dict:
    events = read_events()
    timed = [(event, event_datetime(event)) for event in events]
    period = [event for event, stamp in timed if stamp and (since is None or stamp >= since)]
    completed = {
        str(event.get("task")) for event in period
        if event.get("event") == "task_done" and event.get("task")
    }
    claims: dict[str, list[dict]] = {}
    for event in events:
        if event.get("event") == "task_claimed" and event.get("task"):
            claims.setdefault(str(event["task"]), []).append(event)
    retries = 0
    for attempts in claims.values():
        for attempt in attempts[1:]:
            stamp = event_datetime(attempt)
            if stamp and (since is None or stamp >= since):
                retries += 1
    created = [event for event in events if event.get("event") == "task_created"]
    reviewed = [event for event in events if event.get("event") == "task_reviewed"]
    merged = [event for event in period if event.get("event") == "task_merged"]
    agents: dict[str, int] = {}
    for event in period:
        agent = event.get("agent")
        if agent:
            agents[str(agent)] = agents.get(str(agent), 0) + 1
    return {
        "since": since.isoformat().replace("+00:00", "Z") if since else None,
        "events_recorded": len(period),
        "tasks_completed": len(completed),
        "median_creation_to_done_seconds": duration_median(
            [event for event in period if event.get("event") == "task_done"], created, "task_done"
        ),
        "median_review_to_merge_seconds": duration_median(merged, reviewed, "task_merged"),
        "lock_refusals": sum(event.get("event") == "lock_refused" for event in period),
        "retries": retries,
        "resumes": sum(event.get("event") == "resume" for event in period),
        "per_agent": dict(sorted(agents.items())),
    }
