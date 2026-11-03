"""core.timeutil: split out of the former monolithic ai.py."""

from __future__ import annotations

import datetime as dt


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    """Parse an ISO timestamp and always return an offset-aware datetime.

    Hand-edited state (or another tool's output) may omit the timezone. A naive
    value used to crash arithmetic against `now()` with a TypeError, so it is
    interpreted as UTC here instead.
    """
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def age_minutes(value) -> float | None:
    if not value:
        return None
    try:
        return (now() - parse_iso(str(value))).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None
