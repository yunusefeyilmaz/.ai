"""tasks.links: split out of the former monolithic ai.py."""

from __future__ import annotations

import re

from lib.core.timeutil import iso
from lib.tasks import store


def link_task_github(
    path: str,
    issue: str | None = None,
    pr: str | None = None,
    agent: str | None = None,
) -> tuple[dict, str]:
    """Helper to link a GitHub issue and pull request from a task record without external tokens."""
    meta, body = store.parse_task(path)
    links = []
    if issue:
        meta["github_issue"] = str(issue).strip()
        links.append(f"issue: {issue}")
    if pr:
        meta["github_pr"] = str(pr).strip()
        links.append(f"pr: {pr}")
    if not links:
        return meta, body

    if issue and pr:
        note_line = f"GitHub: {issue} / {pr}"
    elif issue:
        note_line = f"GitHub issue: {issue}"
    else:
        note_line = f"GitHub PR: {pr}"

    notes_match = re.search(r"(## Notes\s*\n)", body)
    if notes_match:
        idx = notes_match.end()
        body = body[:idx] + f"- {note_line}\n" + body[idx:]
    else:
        body = body.rstrip() + f"\n\n## Notes\n\n- {note_line}\n"

    meta["updated"] = iso()
    log_entry = f"- {iso()} linked GitHub {', '.join(links)}"
    if agent:
        log_entry += f" by {agent}"
    body = body.rstrip() + f"\n{log_entry}\n"
    store.write_task(path, meta, body)
    return meta, body
