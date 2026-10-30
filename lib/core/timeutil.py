"""core.timeutil: split out of the former monolithic ai.py."""

from __future__ import annotations

import datetime as dt


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_minutes(value) -> float | None:
    if not value:
        return None
    try:
        return (now() - parse_iso(str(value))).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None
