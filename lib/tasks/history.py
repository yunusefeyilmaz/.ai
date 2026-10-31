"""tasks.history: a structured, append-only transition log inside each task file.

Every state change writes one line under `## Log`:

    - <iso time> | <actor> | <from> -> <to> | <reason> | <evidence>

so "who moved it, when, from what to what, why, and on which proof" survives
agent changes and needs no conversation history. `ai history <id>` reads it.
Older free-form bullets (`- <time> claimed by x`) are still shown, unparsed.
"""

from __future__ import annotations

import re

from lib.core.timeutil import iso

_LINE = re.compile(
    r"^- (?P<at>\d{4}-\d\d-\d\dT[\w:.+-]+) \| (?P<actor>[^|]*?) \| (?P<frm>\S+) -> (?P<to>\S+)"
    r" \| (?P<reason>[^|]*?)(?: \| (?P<evidence>.*))?$"
)


def _clean(text: str | None) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def line(actor: str | None, frm: str | None, to: str, reason: str = "", evidence: str = "") -> str:
    parts = [iso(), _clean(actor) or "-", f"{frm or '-'} -> {to}", _clean(reason) or "-"]
    if evidence:
        parts.append(_clean(evidence))
    return "- " + " | ".join(parts)


def append(body: str, actor: str | None, frm: str | None, to: str, reason: str = "", evidence: str = "") -> str:
    return body.rstrip("\n") + "\n" + line(actor, frm, to, reason, evidence) + "\n"


def parse(body: str) -> list[dict]:
    """Return log entries oldest-first. Unstructured bullets get kind='note'."""
    entries: list[dict] = []
    in_log = False
    for raw in body.splitlines():
        if raw.startswith("## "):
            in_log = raw.strip().lower() == "## log"
            continue
        if not in_log or not raw.startswith("- "):
            continue
        match = _LINE.match(raw)
        if match:
            entries.append({
                "kind": "transition", "at": match["at"], "actor": match["actor"],
                "from": None if match["frm"] == "-" else match["frm"], "to": match["to"],
                "reason": "" if match["reason"] == "-" else match["reason"],
                "evidence": match["evidence"] or "",
            })
        else:
            entries.append({"kind": "note", "text": raw[2:].strip()})
    return entries
