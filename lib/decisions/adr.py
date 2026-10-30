"""decisions.adr: Architecture Decision Records stored next to this module."""

from __future__ import annotations

import datetime as dt
import os
import re

from lib.core.fsio import slugify, write_text_atomic
from lib.core.paths import DECISIONS_DIR

TEMPLATE = """# {number} - {title}

- Status: proposed
- Date: {date}
- Deciders: {deciders}
- Task: {task}

## Context

<!-- What forces are at play? What breaks if we do nothing? -->

## Decision

<!-- The choice, in the active voice. -->

## Consequences

<!-- What becomes easier, what harder, what is now forbidden. -->

## Alternatives

<!-- What else was considered and why it lost. -->
"""


def list_decisions() -> list[dict]:
    items: list[dict] = []
    if not os.path.isdir(DECISIONS_DIR):
        return items
    for name in sorted(os.listdir(DECISIONS_DIR)):
        if not re.match(r"\d{4}-.*\.md$", name):
            continue
        title, status = name[:-3], None
        try:
            with open(os.path.join(DECISIONS_DIR, name), encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("# ") and title == name[:-3]:
                        title = re.sub(r"^\d{4}\s*-\s*", "", line[2:].strip())
                    match = re.match(r"(?i)[-*\s]*status\**:?\**\s*(\w+)", line)
                    if match and not status:
                        status = match.group(1).lower()
        except OSError:
            pass
        items.append({"file": name, "title": title, "status": status})
    return items


def next_number() -> str:
    numbers = [int(item["file"][:4]) for item in list_decisions()]
    return f"{(max(numbers) if numbers else 0) + 1:04d}"


def create_decision(title: str, deciders: str = "-", task: str = "-") -> str:
    number = next_number()
    path = os.path.join(DECISIONS_DIR, f"{number}-{slugify(title)}.md")
    text = TEMPLATE.format(
        number=number, title=title.strip(), deciders=deciders, task=task,
        date=dt.date.today().isoformat(),
    )
    write_text_atomic(path, text)
    return path
