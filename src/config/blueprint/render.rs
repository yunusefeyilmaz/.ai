//! Rendering the proposal for humans and for an external model.
//!
//! Both views are generic over the JSON shape: they walk whatever the chief
//! wrote, so adding `languages`, `conventions`, `standards` or a key nobody has
//! invented yet needs no change here.

use serde_json::Value;

use crate::config::blueprint::approved_proposal;
use crate::core::workspace::Workspace;

/// One-line JSON preview, bounded so a nested section cannot flood a token
/// budget. The full form stays available through `--json`.
fn preview(value: &Value, limit: usize) -> String {
    let text = match value {
        Value::String(text) => text.clone(),
        Value::Null => "-".to_string(),
        other => other.to_string(),
    };
    let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if text.chars().count() > limit {
        format!("{}…", text.chars().take(limit).collect::<String>())
    } else {
        text
    }
}

fn scalar_text(node: &Value, key: &str) -> String {
    node.get(key)
        .map(|value| preview(value, 40))
        .unwrap_or_else(|| "-".to_string())
}

fn list_text(node: &Value, key: &str, take: usize) -> String {
    node.get(key)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .take(take)
                .collect::<Vec<_>>()
                .join(", ")
        })
        .filter(|text| !text.is_empty())
        .unwrap_or_else(|| "-".to_string())
}

fn render_section(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut parts: Vec<String> = map
                .iter()
                .map(|(name, value)| format!("{name}={}", preview(value, 28)))
                .collect();
            parts.sort();
            parts.join(", ")
        }
        Value::Array(items) => items
            .iter()
            .map(|item| preview(item, 40))
            .collect::<Vec<_>>()
            .join("; "),
        other => preview(other, 160),
    }
}

fn sections(proposal: &Value) -> Vec<(String, String)> {
    let Some(object) = proposal.as_object() else {
        return Vec::new();
    };
    let mut keys: Vec<&String> = object.keys().collect();
    keys.sort();
    keys.into_iter()
        .filter_map(|key| {
            if key == "note" {
                return None;
            }
            let rendered = render_section(&object[key]);
            if rendered.is_empty() {
                None
            } else {
                Some((key.clone(), rendered))
            }
        })
        .collect()
}

/// Human summary of a blueprint document (pending or approved).
pub fn summary(document: &Value) -> String {
    let proposal = document.get("proposal").cloned().unwrap_or(Value::Null);
    let detected = document.get("detected").cloned().unwrap_or(Value::Null);
    let status = document
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("pending");
    let authored = document
        .get("authored")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let git = detected.get("git").cloned().unwrap_or(Value::Null);
    let tracked = git
        .get("tracked")
        .and_then(|tracked| tracked.get("count"))
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let mut lines = vec![
        format!(
            "Blueprint [{status}{}] {}",
            if authored { "" } else { ", draft" },
            document
                .get("project")
                .and_then(Value::as_str)
                .unwrap_or("-")
        ),
        format!(
            "  os:         {} ({}) · shell {}",
            scalar_text(&detected, "os"),
            scalar_text(&detected, "arch"),
            scalar_text(&detected, "shell"),
        ),
        format!(
            "  git:        {} · {tracked} file(s) tracked",
            if git
                .get("repository")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                "repository"
            } else {
                "no repository"
            }
        ),
        format!("  top level:  {}", list_text(&detected, "topLevel", 12)),
        format!(
            "  tooling:    {}",
            detected
                .get("tooling")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| item.get("binary").and_then(Value::as_str))
                        .take(14)
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .filter(|text| !text.is_empty())
                .unwrap_or_else(|| "nothing answered --version".to_string())
        ),
    ];
    for (key, rendered) in sections(&proposal) {
        lines.push(format!("  {key:<11} {rendered}"));
    }
    if let Some(note) = proposal.get("note").and_then(Value::as_str) {
        lines.push(format!("  note:       {note}"));
    }
    if !authored {
        lines.push(
            "  next:       ai blueprint propose --from <analysis.json>   # chief: fill the draft"
                .to_string(),
        );
    }
    lines.push("  approve:    ai blueprint approve --agent <name>".to_string());
    lines.push(
        "  change:     ai blueprint revise --set path.to.key=value   (any path, e.g. naming.files=PascalCase)"
            .to_string(),
    );
    lines.push(format!("  edit:       {}", crate::config::blueprint::FILE));
    lines.join("\n")
}

/// Compact conventions block for `ai brief` and agents, from the approved
/// proposal (config first, then an approved blueprint file).
pub fn conventions_block(ws: &Workspace) -> String {
    let Some(proposal) = approved_proposal(ws) else {
        return "No approved blueprint yet: the chief runs `ai blueprint propose --from <analysis.json>` and the user approves it."
            .to_string();
    };
    let sections = sections(&proposal);
    if sections.is_empty() {
        return "The approved blueprint is empty.".to_string();
    }
    sections
        .into_iter()
        .map(|(key, rendered)| format!("{key}: {rendered}"))
        .collect::<Vec<_>>()
        .join("\n")
}
