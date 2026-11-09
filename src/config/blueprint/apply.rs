//! Applying an approved proposal to `config/workspace.json`.
//!
//! Two layers, on purpose:
//!
//! * **Operational fields** the CLI enforces (`mode`, `workflow.playbook`,
//!   `workflow.workers`, the workflow booleans, `git`, `checks`, `naming`,
//!   `architecture`, `layout`, `languages`, `testing`, `guidelines`) are copied
//!   where the rest of the program reads them.
//! * **The whole proposal** is stored under `config.blueprint.approved`, so any
//!   key this version does not interpret is still available to agents, `ai
//!   brief` and future versions. Nothing the AI or the user wrote is dropped.

use serde_json::{json, Map, Value};

use crate::config::settings::{load_for_update, save};
use crate::core::error::Result;
use crate::core::workspace::Workspace;

/// Copy any key from the proposal into `config` unchanged.
const PASSTHROUGH: &[&str] = &[
    "languages",
    "architecture",
    "layout",
    "naming",
    "testing",
    "guidelines",
    "conventions",
    "standards",
];

pub fn to_config(ws: &Workspace, proposal: &Value) -> Result<Vec<String>> {
    let mut config = match load_for_update(ws)? {
        Some(config) => config,
        None => crate::config::settings::default_config(ws),
    };
    let mut applied = Vec::new();
    let object = config
        .as_object_mut()
        .ok_or_else(|| crate::core::error::AiError::msg("config root must be an object"))?;

    for key in PASSTHROUGH {
        if let Some(value) = proposal.get(*key) {
            object.insert((*key).to_string(), value.clone());
            applied.push((*key).to_string());
        }
    }

    if let Some(workflow) = proposal.get("workflow").and_then(Value::as_object) {
        apply_workflow(object, workflow, &mut applied);
    }
    if let Some(git) = proposal.get("git").and_then(Value::as_object) {
        let target = object.entry("git".to_string()).or_insert_with(|| json!({}));
        if let Some(target) = target.as_object_mut() {
            for (key, value) in git {
                target.insert(key.clone(), value.clone());
            }
            applied.push("git".into());
        }
    }
    if let Some(checks) = proposal.get("checks").and_then(Value::as_array) {
        apply_checks(object, checks, &mut applied);
    }

    // Preserve everything, including keys this version does not interpret.
    let entry = object
        .entry("blueprint".to_string())
        .or_insert_with(|| json!({}));
    if let Some(entry) = entry.as_object_mut() {
        entry.insert("status".into(), json!("approved"));
        // `checks` is operational state copied to the top level; storing a
        // second copy here would let the two drift and leave "which check is
        // real?" undefined. Other keys are preserved verbatim.
        let mut approved = proposal.clone();
        if let Some(object) = approved.as_object_mut() {
            object.remove("checks");
        }
        entry.insert("approved".into(), approved);
    }
    save(ws, &config)?;
    Ok(applied)
}

fn apply_workflow(
    object: &mut Map<String, Value>,
    workflow: &Map<String, Value>,
    applied: &mut Vec<String>,
) {
    if let Some(mode) = workflow.get("mode").and_then(Value::as_str) {
        object.insert("mode".into(), json!(mode));
        applied.push(format!("mode={mode}"));
    }
    if let Some(workers) = workflow.get("workers").and_then(Value::as_u64) {
        let orchestration = object
            .entry("orchestration".to_string())
            .or_insert_with(|| json!({}));
        if let Some(orchestration) = orchestration.as_object_mut() {
            orchestration.insert("maxParallel".into(), json!(workers));
        }
        let isolation = if workers > 1 { "worktree" } else { "branch" };
        let git = object.entry("git".to_string()).or_insert_with(|| json!({}));
        if let Some(git) = git.as_object_mut() {
            if git.get("isolation").is_none() {
                git.insert("isolation".into(), json!(isolation));
            }
        }
        applied.push(format!("orchestration.maxParallel={workers}"));
    }
    let flow = object
        .entry("workflow".to_string())
        .or_insert_with(|| json!({}));
    if let Some(flow) = flow.as_object_mut() {
        for (key, value) in workflow {
            if matches!(key.as_str(), "mode" | "workers") {
                continue;
            }
            flow.insert(key.clone(), value.clone());
            applied.push(format!("workflow.{key}"));
        }
    }
}

fn apply_checks(object: &mut Map<String, Value>, checks: &[Value], applied: &mut Vec<String>) {
    let empty = object
        .get("checks")
        .and_then(Value::as_array)
        .map(Vec::is_empty)
        .unwrap_or(true);
    if !empty || checks.is_empty() {
        return;
    }
    let entries: Vec<Value> = checks
        .iter()
        .filter(|check| {
            check
                .get("command")
                .and_then(Value::as_str)
                .map(|command| !command.trim().is_empty())
                .unwrap_or(false)
        })
        .cloned()
        .collect();
    if entries.is_empty() {
        return;
    }
    object.insert("checks".into(), Value::Array(entries.clone()));
    applied.push(format!("checks={}", entries.len()));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_keys_are_preserved_in_the_approved_record() {
        let base = std::env::temp_dir().join(format!(
            "ai-blueprint-apply-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|value| value.as_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(base.join("config")).unwrap();
        std::fs::write(
            base.join("config").join("workspace.json"),
            crate::config::settings::default_config(&Workspace::at(&base)).to_string(),
        )
        .unwrap();
        let ws = Workspace::at(&base);
        let proposal = json!({
            "languages": ["Zig"],
            "architecture": "actor-per-domain",
            "conventions": {"release": "trunk"},
            "workflow": {"mode": "strict", "playbook": "solo", "workers": 2},
            "checks": [{"name": "zig", "command": "zig build test"}],
        });
        to_config(&ws, &proposal).unwrap();
        let config: Value = serde_json::from_str(
            &std::fs::read_to_string(base.join("config/workspace.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(config["mode"], json!("strict"));
        assert_eq!(config["workflow"]["playbook"], json!("solo"));
        assert_eq!(config["orchestration"]["maxParallel"], json!(2));
        assert_eq!(config["conventions"]["release"], json!("trunk"));
        assert_eq!(
            config["blueprint"]["approved"]["languages"][0],
            json!("Zig")
        );
        assert_eq!(config["checks"][0]["name"], json!("zig"));
        // Operational checks live in one place; the approved block must not
        // become a second, drifting copy.
        assert!(
            config["blueprint"]["approved"].get("checks").is_none(),
            "{}",
            config["blueprint"]["approved"]
        );
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn configured_checks_are_not_overwritten() {
        let base = std::env::temp_dir().join(format!(
            "ai-blueprint-apply-checks-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|value| value.as_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(base.join("config")).unwrap();
        let ws = Workspace::at(&base);
        let mut config = crate::config::settings::default_config(&ws);
        config["checks"] = json!([{"name": "keep", "command": "true"}]);
        crate::config::settings::save(&ws, &config).unwrap();
        to_config(
            &ws,
            &json!({"checks": [{"name": "new", "command": "false"}]}),
        )
        .unwrap();
        let saved: Value = serde_json::from_str(
            &std::fs::read_to_string(base.join("config/workspace.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(saved["checks"][0]["name"], json!("keep"));
        let _ = std::fs::remove_dir_all(&base);
    }
}
