//! A light agent -> role -> capability table.
//!
//! Three separate ideas, kept apart on purpose:
//!   agent       the actor doing the work (a name, any vendor)
//!   role        a responsibility (planner, developer, reviewer, ...)
//!   capability  an action the protocol guards (task.done, git.finish, ...)

use std::collections::BTreeMap;

use serde_json::Value;

use crate::config::settings::load;
use crate::core::workspace::Workspace;

pub const ACTIONS: &[&str] = &[
    "task.new",
    "task.claim",
    "task.review",
    "task.request_changes",
    "task.done",
    "git.finish",
];

pub fn default_roles() -> BTreeMap<String, Vec<String>> {
    let mut table = BTreeMap::new();
    table.insert("chief".into(), vec!["*".into()]);
    table.insert("planner".into(), vec!["task.new".into()]);
    table.insert(
        "implementer".into(),
        vec!["task.claim".into(), "task.review".into()],
    );
    table.insert(
        "reviewer".into(),
        vec![
            "task.request_changes".into(),
            "task.done".into(),
            "git.finish".into(),
        ],
    );
    table.insert(
        "qa".into(),
        vec!["task.request_changes".into(), "task.done".into()],
    );
    table.insert("orchestrator".into(), vec!["*".into()]);
    table
}

fn strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default()
}

pub fn role_table(config: &Value) -> BTreeMap<String, Vec<String>> {
    let mut table = default_roles();
    for (name, caps) in config
        .get("roles")
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
    {
        table.insert(name.clone(), strings(Some(caps)));
    }
    table
}

/// Roles assigned to `agent`, or None when the agent is not in the team table.
pub fn roles_of(agent: &str, config: &Value) -> Option<Vec<String>> {
    let team = config.get("team").and_then(Value::as_object)?;
    let entry = team.get(agent).or_else(|| team.get("*"))?;
    Some(strings(entry.get("roles")))
}

pub fn authorize(ws: &Workspace, agent: Option<&str>, action: &str) -> Result<(), String> {
    let config = match load(ws) {
        Ok(config) => config,
        Err(_) => return Ok(()),
    };
    let team_empty = config
        .get("team")
        .and_then(Value::as_object)
        .map(|team| team.is_empty())
        .unwrap_or(true);
    if team_empty {
        return Ok(());
    }
    let agent = match agent {
        Some(agent) if !agent.trim().is_empty() => agent,
        _ => return Ok(()),
    };
    let roles = match roles_of(agent, &config) {
        Some(roles) => roles,
        None => {
            let deny = config
                .get("policy")
                .and_then(|p| p.get("unknownAgent"))
                .and_then(Value::as_str)
                .unwrap_or("allow")
                == "deny";
            if deny {
                return Err(format!(
                    "Agent '{agent}' is not listed under `team` in config/workspace.json; `{action}` is denied."
                ));
            }
            return Ok(());
        }
    };
    let table = role_table(&config);
    for role in &roles {
        if let Some(caps) = table.get(role) {
            if caps.iter().any(|cap| cap == "*" || cap == action) {
                return Ok(());
            }
        }
    }
    let wanted: Vec<&String> = table
        .iter()
        .filter(|(_, caps)| caps.iter().any(|cap| cap == "*" || cap == action))
        .map(|(name, _)| name)
        .collect();
    let wanted = if wanted.is_empty() {
        "none".to_string()
    } else {
        wanted
            .iter()
            .map(|name| name.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    };
    Err(format!(
        "Agent '{agent}' (roles: {}) may not `{action}`. Roles that can: {wanted}.",
        if roles.is_empty() {
            "none".to_string()
        } else {
            roles.join(", ")
        }
    ))
}
