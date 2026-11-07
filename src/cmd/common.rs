//! Shared helpers for command implementations.

use std::path::Path;

use serde_json::{Map, Value};

use crate::core::error::{fail, Result};
use crate::core::time::iso;
use crate::core::workspace::{relative_to, Workspace};
use crate::runtime::mutex::workspace_state_guard;
use crate::tasks::board;
use crate::tasks::store;

/// Run `mutate(meta, body) -> new_body` under the workspace state guard, then
/// re-find the task, validate, write, refresh the board. A refusal returned by
/// `mutate` leaves the file untouched.
pub fn apply_transition<F>(
    ws: &Workspace,
    task_id: &str,
    path: &Path,
    active_only: bool,
    mutate: F,
) -> Result<Map<String, Value>>
where
    F: FnOnce(&mut Map<String, Value>, &str) -> Result<String>,
{
    let _guard = workspace_state_guard(ws)?;
    let current = match store::find_task(ws, task_id) {
        Some(current) => current,
        None => {
            return fail(format!(
                "Task {task_id} changed before it could be updated; retry."
            ))
        }
    };
    if current != path || (active_only && current.parent() != Some(ws.active_dir().as_path())) {
        return fail(format!(
            "Task {task_id} changed before it could be updated; retry."
        ));
    }
    let (mut meta, body, _) = store::parse_task(&current)?;
    let new_body = mutate(&mut meta, &body)?;
    meta.insert("updated".into(), Value::String(iso(None)));
    store::write_task(&current, &meta, &new_body)?;
    board::write_board(ws, &store::load_tasks(ws))?;
    Ok(meta)
}

pub fn rel(ws: &Workspace, path: &Path) -> String {
    relative_to(&ws.project, path)
}

pub fn text(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Null) | None => "-".to_string(),
        Some(other) => other.to_string(),
    }
}

pub fn text_or(value: Option<&Value>, fallback: &str) -> String {
    match value {
        Some(Value::String(text)) if !text.is_empty() => text.clone(),
        Some(Value::Null) | None => fallback.to_string(),
        Some(other) => other.to_string(),
    }
}

pub fn flag(value: Option<&Value>) -> bool {
    match value {
        Some(Value::Bool(flag)) => *flag,
        Some(Value::String(text)) => text.eq_ignore_ascii_case("true"),
        _ => false,
    }
}

pub fn str_value(meta: &Map<String, Value>, key: &str) -> Option<String> {
    meta.get(key)
        .and_then(Value::as_str)
        .map(ToString::to_string)
}

pub fn set_null(meta: &mut Map<String, Value>, key: &str) {
    meta.insert(key.to_string(), Value::Null);
}
