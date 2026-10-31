"""config.settings: split out of the former monolithic ai.py."""

from __future__ import annotations

from lib.core.paths import (
    CONFIG_PATH,
    PROJECT,
)

import json
import os



def config_path() -> str:
    return CONFIG_PATH


def load_config() -> dict:
    with open(config_path(), encoding="utf-8") as handle:
        return json.load(handle)


def lock_settings() -> tuple[int, int]:
    locks = load_config().get("locks", {})
    return (
        int(locks.get("defaultTtlSeconds", 1800)),
        int(locks.get("staleAfterSeconds", 3600)),
    )


def max_lock_ttl() -> int:
    return int(load_config().get("locks", {}).get("maxTtlSeconds", 7200))


def default_config() -> dict:
    return {
        "version": 1,
        "name": os.path.basename(PROJECT),
        "mode": "lite",
        "language": {"documents": "en", "interviews": "en"},
        "agents": ["orchestrator", "planner", "implementer", "reviewer", "qa"],
        "workflow": {"requireReview": True, "requireCheck": "strict", "autoContinue": False},
        "team": {},
        "orchestration": {"maxParallel": 3},
        "git": {
            "enabled": True,
            "integrationBranch": "develop",
            "productionBranch": "master",
            "branchTypes": ["feature", "fix", "chore", "docs", "refactor", "hotfix"],
            "commitTemplate": "templates/git/commit-template.txt",
            "merge": "no-ff",
            "deleteAfterMerge": True,
            "isolation": "branch",
        },
        "testing": {"writeTests": True},
        "preferences": {"confirmed": False, "answered": []},
        "policy": {"unknownAgent": "allow"},
        "locks": {
            "defaultTtlSeconds": 1800,
            "staleAfterSeconds": 3600,
            "maxTtlSeconds": 7200,
        },
        "handoff": {
            "checkpointEveryMinutes": 20,
            "warnAfterMinutes": 30,
        },
        "budget": {
            "contextTokens": 200000,
            "warnAtPercent": 70,
            "checkpointAtPercent": 85,
        },
        "artifacts": {
            "quarantine": "runtime/artifacts",
            "watch": ["tmp", "temp", "scratch", ".cache", "ai-notes", "notes-ai"],
        },
        "security": {"warnTrackedSecrets": True},
        "checks": [],
    }


def configured_checks() -> list[dict]:
    """Project check commands that actually have a command to run."""
    try:
        checks = load_config().get("checks") or []
    except (OSError, ValueError):
        return []
    return [c for c in checks if isinstance(c, dict) and c.get("command")]


def preference(path: str, default=None):
    """Read a dotted config value, e.g. preference("git.enabled", True)."""
    try:
        node = load_config()
    except (OSError, ValueError):
        return default
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def git_enabled() -> bool:
    return bool(preference("git.enabled", True))
