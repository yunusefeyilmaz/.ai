"""runtime.events: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys

from lib.core.paths import (
    EVENTS_FILE,
    STATE_DIR,
)
from lib.core.timeutil import iso
from lib.runtime.dirs import ensure_dirs
from lib.runtime.mutex import registry_mutex


def append_event(event: str, **fields) -> None:
    """Append one local JSONL event, rotating the active file by UTC date."""
    record = {"timestamp": iso(), "event": event}
    record.update({key: value for key, value in fields.items() if value is not None})
    try:
        ensure_dirs()
        with registry_mutex():
            if os.path.isfile(EVENTS_FILE):
                last = None
                try:
                    with open(EVENTS_FILE, encoding="utf-8") as handle:
                        for line in handle:
                            if line.strip():
                                try:
                                    last = json.loads(line)
                                except ValueError:
                                    continue
                except OSError:
                    last = None
                previous_date = str((last or {}).get("timestamp") or "")[:10]
                event_date = record["timestamp"][:10]
                if previous_date and previous_date != event_date:
                    archive = os.path.join(STATE_DIR, f"events-{previous_date}.jsonl")
                    if os.path.exists(archive):
                        with open(EVENTS_FILE, "rb") as source, open(archive, "ab") as target:
                            shutil.copyfileobj(source, target)
                        os.remove(EVENTS_FILE)
                    else:
                        os.replace(EVENTS_FILE, archive)
            descriptor = os.open(EVENTS_FILE, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            try:
                line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                os.write(descriptor, line.encode("utf-8"))
            finally:
                os.close(descriptor)
    except (OSError, TimeoutError) as exc:
        print(f"WARN  could not record metrics event '{event}': {exc}", file=sys.stderr)


def read_events() -> list[dict]:
    """Read the active and rotated event ledgers without creating state."""
    if not os.path.isdir(STATE_DIR):
        return []
    paths = [
        os.path.join(STATE_DIR, name)
        for name in os.listdir(STATE_DIR)
        if name == "events.jsonl" or re.fullmatch(r"events-\d{4}-\d{2}-\d{2}\.jsonl", name)
    ]
    events = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("event") and event.get("timestamp"):
                        events.append(event)
        except OSError:
            continue
    events.sort(key=lambda item: str(item.get("timestamp") or ""))
    return events
