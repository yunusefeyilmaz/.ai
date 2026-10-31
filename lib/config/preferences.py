"""config.preferences: the questions the chief asks the user, and where answers go.

The chief (orchestrator) must not silently decide how much process a project
gets. It asks the user once, in the user's language, then stores the answers in
`config/workspace.json` so every worker and reviewer follows the same rules.

    ai setup                         # questions + current answers
    ai setup --set review=yes git=no # store answers
    ai setup --defaults              # accept the recommended answers
"""

from __future__ import annotations

from lib.config.settings import config_path, load_config
from lib.core.fsio import write_json_atomic
from lib.core.timeutil import iso

# key -> (dotted config path, type, recommended, question)
QUESTIONS = [
    ("review", "workflow.requireReview", "bool", True,
     "Should finished work be reviewed by a second agent, who approves and merges it?"),
    ("checks", "workflow.requireCheck", "bool", True,
     "Must the project's checks (tests, lint, build) pass before work goes to review? "
     "If yes, which commands? (add them with --check NAME=COMMAND)"),
    ("git", "git.enabled", "bool", True,
     "Use Git: a branch per task, standard commits, and merging into develop?"),
    ("tests", "testing.writeTests", "bool", True,
     "Should workers write tests for the behavior they add?"),
    ("continue", "workflow.autoContinue", "bool", False,
     "After delivering a task, may a worker start the next one without asking you?"),
    ("workers", "orchestration.maxParallel", "int", 1,
     "How many workers may run at the same time?"),
]
REQUIRED_KEYS = ("review", "checks", "git", "tests")
_TRUE, _FALSE = {"yes", "y", "true", "1", "on"}, {"no", "n", "false", "0", "off"}


def _get(config: dict, dotted: str):
    node = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set(config: dict, dotted: str, value) -> None:
    node = config
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def parse_value(kind: str, raw: str):
    text = str(raw).strip().lower()
    if kind == "bool":
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"expected yes/no, got '{raw}'")
    number = int(text)
    if number < 1 or number > 32:
        raise ValueError("expected a number between 1 and 32")
    return number


def status(config: dict | None = None) -> dict:
    config = config if config is not None else load_config()
    prefs = config.get("preferences") or {}
    answered = set(prefs.get("answered") or [])
    rows = []
    for key, dotted, kind, recommended, ask in QUESTIONS:
        value = _get(config, dotted)
        if key == "checks" and value == "strict":
            value = None
        rows.append({
            "key": key, "ask": ask, "type": kind, "recommended": recommended,
            "current": value, "answered": key in answered,
        })
    confirmed = all(key in answered for key in REQUIRED_KEYS)
    return {"confirmed": confirmed, "questions": rows,
            "checks": [c.get("name") or c.get("command") for c in (config.get("checks") or [])]}


def apply(answers: dict[str, str], checks: list[str] | None = None) -> dict:
    """Validate and store answers (key -> raw text) and optional check commands."""
    config = load_config()
    known = {key: (dotted, kind) for key, dotted, kind, _, _ in QUESTIONS}
    unknown = [key for key in answers if key not in known]
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}; use {', '.join(known)}")
    prefs = config.setdefault("preferences", {})
    answered = set(prefs.get("answered") or [])
    for key, raw in answers.items():
        dotted, kind = known[key]
        _set(config, dotted, parse_value(kind, raw))
        answered.add(key)
    for item in checks or []:
        name, sep, command = item.partition("=")
        if not sep or not name.strip() or not command.strip():
            raise ValueError(f"--check expects NAME=COMMAND, got '{item}'")
        entries = [c for c in (config.get("checks") or []) if c.get("name") != name.strip()]
        entries.append({"name": name.strip(), "command": command.strip()})
        config["checks"] = entries
    prefs["answered"] = sorted(answered)
    prefs["confirmed"] = all(key in answered for key in REQUIRED_KEYS)
    prefs["at"] = iso()
    write_json_atomic(config_path(), config)
    return status(config)


def defaults() -> dict[str, str]:
    return {key: ("yes" if rec is True else "no" if rec is False else str(rec)) for key, _, _, rec, _ in QUESTIONS}
