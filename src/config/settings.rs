//! `config/workspace.json`: load, defaults and dotted preferences.

use std::path::Path;

use serde_json::{json, Map, Value};

use crate::core::error::{fail, Result};
use crate::core::fsio::{read_json, write_json_atomic};
use crate::core::workspace::Workspace;

pub fn load(ws: &Workspace) -> Result<Value> {
    match read_json(&ws.config_path()) {
        Ok(Some(value @ Value::Object(_))) => Ok(value),
        Ok(Some(_)) => fail("config/workspace.json is unreadable: it must be a JSON object"),
        Ok(None) => fail(
            "config/workspace.json is missing; run `ai doctor --fix` (or `ai setup`) to recreate it.",
        ),
        Err(error) => fail(format!("config/workspace.json is unreadable: {error}")),
    }
}

pub fn load_or_default(ws: &Workspace) -> Value {
    load(ws).unwrap_or_else(|_| default_config(ws))
}

pub fn lock_settings(ws: &Workspace) -> (u64, u64) {
    let config = load(ws).unwrap_or_else(|_| default_config(ws));
    let locks = config.get("locks");
    (
        locks
            .and_then(|l| l.get("defaultTtlSeconds"))
            .and_then(Value::as_u64)
            .unwrap_or(1800),
        locks
            .and_then(|l| l.get("staleAfterSeconds"))
            .and_then(Value::as_u64)
            .unwrap_or(3600),
    )
}

pub fn max_lock_ttl(ws: &Workspace) -> u64 {
    load(ws)
        .ok()
        .and_then(|config| {
            config
                .get("locks")
                .and_then(|l| l.get("maxTtlSeconds"))
                .and_then(Value::as_u64)
        })
        .unwrap_or(7200)
}

pub fn default_config(ws: &Workspace) -> Value {
    let name = ws
        .project
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("workspace");
    json!({
        "version": 1,
        "name": name,
        "mode": "lite",
        "language": {"documents": "en", "interviews": "en"},
        "agents": ["orchestrator", "planner", "implementer", "reviewer", "qa"],
        "workflow": {
            "requireReview": true,
            "requireCheck": "strict",
            "autoContinue": false,
            "chiefOnlyTasks": true,
            "requireSpec": true
        },
        "team": {},
        "orchestration": {"maxParallel": 3},
        "git": {
            "enabled": true,
            "integrationBranch": "develop",
            "productionBranch": "master",
            "branchTypes": ["feature", "fix", "chore", "docs", "refactor", "hotfix"],
            "commitTemplate": "templates/git/commit-template.txt",
            "merge": "no-ff",
            "deleteAfterMerge": true,
            "isolation": "branch"
        },
        "testing": {"writeTests": true},
        "preferences": {"confirmed": false, "answered": []},
        "policy": {"unknownAgent": "allow"},
        "locks": {
            "defaultTtlSeconds": 1800,
            "staleAfterSeconds": 3600,
            "maxTtlSeconds": 7200
        },
        "handoff": {"checkpointEveryMinutes": 20, "warnAfterMinutes": 30},
        "budget": {"contextTokens": 200000, "warnAtPercent": 70, "checkpointAtPercent": 85},
        "artifacts": {
            "quarantine": "runtime/artifacts",
            "watch": ["tmp", "temp", "scratch", ".cache", "ai-notes", "notes-ai"]
        },
        "security": {"warnTrackedSecrets": true},
        "checks": []
    })
}

pub fn save(ws: &Workspace, config: &Value) -> Result<()> {
    write_json_atomic(&ws.config_path(), config)
}

/// Read a dotted config value, e.g. `preference(ws, "git.enabled")`.
pub fn preference(ws: &Workspace, path: &str, default: Value) -> Value {
    let config = match load(ws) {
        Ok(config) => config,
        Err(_) => return default,
    };
    let mut node = &config;
    for part in path.split('.') {
        match node.get(part) {
            Some(next) => node = next,
            None => return default,
        }
    }
    node.clone()
}

pub fn bool_preference(ws: &Workspace, path: &str, default: bool) -> bool {
    match preference(ws, path, Value::Bool(default)) {
        Value::Bool(flag) => flag,
        Value::String(text) => text.eq_ignore_ascii_case("true"),
        Value::Number(number) => number.as_i64().unwrap_or(0) != 0,
        _ => default,
    }
}

pub fn git_enabled(ws: &Workspace) -> bool {
    bool_preference(ws, "git.enabled", true)
}

pub fn configured_checks(ws: &Workspace) -> Vec<Value> {
    match load(ws) {
        Ok(config) => config
            .get("checks")
            .and_then(Value::as_array)
            .map(|checks| {
                checks
                    .iter()
                    .filter(|check| {
                        check
                            .get("command")
                            .and_then(Value::as_str)
                            .map(|c| !c.trim().is_empty())
                            .unwrap_or(false)
                    })
                    .cloned()
                    .collect()
            })
            .unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

/// Set a dotted key, creating intermediate objects as needed.
pub fn set_dotted(config: &mut Value, dotted: &str, value: Value) {
    let parts: Vec<&str> = dotted.split('.').collect();
    let mut node = config;
    for part in &parts[..parts.len() - 1] {
        let object = node.as_object_mut().expect("config root must be an object");
        let entry = object
            .entry(part.to_string())
            .or_insert_with(|| Value::Object(Map::new()));
        if !entry.is_object() {
            *entry = Value::Object(Map::new());
        }
        node = entry;
    }
    let object = node.as_object_mut().expect("config node must be an object");
    object.insert(parts[parts.len() - 1].to_string(), value);
}

pub fn get_dotted<'a>(config: &'a Value, dotted: &str) -> Option<&'a Value> {
    let mut node = config;
    for part in dotted.split('.') {
        node = node.get(part)?;
    }
    Some(node)
}

/// Recreate the config when it is absent; never overwrite a corrupt file.
pub fn ensure_config(ws: &Workspace) -> Result<bool> {
    if ws.config_path().exists() {
        return Ok(false);
    }
    let config = default_config(ws);
    save(ws, &config)?;
    Ok(true)
}

/// Write a default config only when the path is missing.
pub fn init_at(path: &Path, ws: &Workspace) -> Result<bool> {
    if path.exists() {
        return Ok(false);
    }
    let config = default_config(ws);
    write_json_atomic(path, &config)?;
    Ok(true)
}
