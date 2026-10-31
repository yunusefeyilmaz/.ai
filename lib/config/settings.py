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
        "workflow": {"requireReview": True, "requireCheck": "strict"},
        "team": {},
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
