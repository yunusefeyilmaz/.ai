"""core.findings: split out of the former monolithic ai.py."""

from __future__ import annotations

from typing import NamedTuple


class Finding(NamedTuple):
    """One diagnostic and, when one exists, the next safe action."""

    level: str
    message: str
    hint: str | None = None
