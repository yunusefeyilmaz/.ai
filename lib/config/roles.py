"""config.roles: a light agent -> role -> capability table.

Three separate ideas, kept apart on purpose:
  agent       the actor doing the work (a name, any vendor)
  role        a responsibility (planner, developer, reviewer, ...)
  capability  an action the protocol guards (task.done, git.finish, ...)

Configuration (config/workspace.json), all optional:

  "team":   {"claude-1": {"roles": ["implementer"]},
             "codex-1":  {"roles": ["reviewer"]},
             "*":        {"roles": ["implementer", "reviewer"]}},  # fallback
  "roles":  {"implementer": ["task.claim", "task.review"], ...},   # overrides

Role names are the cards in `agents/` (listed under `agents` in the config).
  "policy": {"unknownAgent": "allow"}                            # or "deny"

With no `team` table everything is allowed (solo work needs no ceremony).
This guards the *protocol*, not the machine: `ai.py` cannot stop an agent from
editing files directly, so treat it as accountability, not a sandbox.
"""

from __future__ import annotations

from lib.config.settings import load_config

DEFAULT_ROLES = {
    "planner": ["task.new"],
    "implementer": ["task.claim", "task.review"],
    "reviewer": ["task.request_changes", "task.done", "git.finish"],
    "qa": ["task.request_changes", "task.done"],
    "orchestrator": ["*"],
}

ACTIONS = (
    "task.new", "task.claim", "task.review", "task.request_changes", "task.done", "git.finish",
)


def role_table(config: dict | None = None) -> dict:
    config = config if config is not None else load_config()
    table = {name: list(caps) for name, caps in DEFAULT_ROLES.items()}
    for name, caps in (config.get("roles") or {}).items():
        table[str(name)] = [str(cap) for cap in (caps or [])]
    return table


def roles_of(agent: str, config: dict | None = None) -> list[str] | None:
    """Roles assigned to `agent`, or None when the agent is not in the team table."""
    config = config if config is not None else load_config()
    team = config.get("team") or {}
    entry = team.get(agent) or team.get("*")
    if entry is None:
        return None
    return [str(role) for role in (entry.get("roles") or [])]


def authorize(agent: str | None, action: str, config: dict | None = None) -> str | None:
    """Return an error message when `agent` may not perform `action`, else None."""
    try:
        config = config if config is not None else load_config()
    except (OSError, ValueError):
        return None
    if not (config.get("team") or {}):
        return None
    if not agent:
        return None
    roles = roles_of(agent, config)
    if roles is None:
        if (config.get("policy") or {}).get("unknownAgent", "allow") == "deny":
            return f"Agent '{agent}' is not listed under `team` in config/workspace.json; `{action}` is denied."
        return None
    table = role_table(config)
    for role in roles:
        caps = table.get(role, [])
        if "*" in caps or action in caps:
            return None
    wanted = [name for name, caps in table.items() if action in caps or "*" in caps]
    return (
        f"Agent '{agent}' (roles: {', '.join(roles) or 'none'}) may not `{action}`. "
        f"Roles that can: {', '.join(wanted) or 'none'}."
    )
