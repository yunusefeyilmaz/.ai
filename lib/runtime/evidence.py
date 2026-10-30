"""runtime.evidence: the last `ai check` result, kept as proof for the gates.

"Done means `ai check` is green" is only enforceable if the result is stored
somewhere a later command can read. `ai check` records it here; the review gate
(lib/tasks/gates.py) reads it.
"""

from __future__ import annotations

from lib.core.fsio import read_json, write_json_atomic
from lib.core.paths import LAST_CHECK_PATH
from lib.core.timeutil import iso, parse_iso


def record_check(ok: bool, *, strict: bool, ran_commands: bool, fast: bool, head: str | None) -> None:
    write_json_atomic(
        LAST_CHECK_PATH,
        {"at": iso(), "ok": ok, "strict": strict, "ran_commands": ran_commands,
         "fast": fast, "head": head},
    )


def last_check() -> dict | None:
    data = read_json(LAST_CHECK_PATH)
    return data if isinstance(data, dict) else None


def green_since(since_iso: str | None, *, need_commands: bool = True) -> tuple[bool, str]:
    """Is there a green check at/after `since_iso`? Returns (ok, reason)."""
    data = last_check()
    if not data:
        return False, "no `ai check` result is recorded yet"
    if not data.get("ok"):
        return False, f"the last `ai check` ({data.get('at')}) failed"
    if need_commands and not data.get("ran_commands"):
        return False, "the last `ai check` skipped the configured commands (--no-commands)"
    if need_commands and data.get("fast"):
        return False, "the last `ai check` was --fast; run the full `ai check`"
    if since_iso:
        try:
            if parse_iso(str(data.get("at"))) < parse_iso(since_iso):
                return False, f"the last green `ai check` ({data.get('at')}) is older than the claim ({since_iso})"
        except (TypeError, ValueError):
            pass
    return True, str(data.get("at"))
