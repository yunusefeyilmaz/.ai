//! Advisory resource leases: TTL-based ownership for tasks, files and the index.
//!
//! Staleness is TTL-based on purpose. A task claim outlives the CLI process
//! that created it, so PID liveness would mark every held task lock stale. The
//! PID and host are kept as diagnostics only.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use crate::config::settings::{lock_settings, max_lock_ttl};
use crate::core::error::{fail, Result};
use crate::core::fsio::{
    create_new_json, lock_path, normalize_rel_path, read_json, write_json_atomic,
};
use crate::core::time::{iso, parse_iso};
use crate::core::workspace::Workspace;
use crate::runtime::dirs::ensure_dirs;
use crate::runtime::events::append_event;
use crate::runtime::mutex::registry_mutex;
use crate::tasks::scope::{fnmatch, matches};

pub fn path_covers(pattern: &str, resource: &str) -> bool {
    matches(pattern, resource)
        || resource.starts_with(&(pattern.trim_end_matches('/').to_string() + "/"))
}

pub fn lock_is_stale(payload: Option<&Value>, stale_after: u64) -> bool {
    let payload = match payload {
        Some(Value::Object(map)) => map,
        _ => return true,
    };
    let stamp = payload
        .get("updated_at")
        .or_else(|| payload.get("started_at"))
        .and_then(Value::as_str)
        .unwrap_or("");
    let updated = match parse_iso(stamp) {
        Some(updated) => updated,
        None => return true,
    };
    let age = (crate::core::time::now() - updated).num_seconds();
    age > stale_after as i64
}

fn expiry(updated_at: &str, ttl: u64) -> String {
    match parse_iso(updated_at) {
        Some(updated) => iso(Some(updated + chrono::Duration::seconds(ttl as i64))),
        None => iso(None),
    }
}

pub fn normalize_resource(resource: &str) -> Result<String> {
    let raw = normalize_rel_path(resource);
    if raw.is_empty() {
        return fail("lock resource is empty");
    }
    let absolute = raw.starts_with('/')
        || regex::Regex::new(r"^[A-Za-z]:/")
            .expect("static regex")
            .is_match(&raw);
    if absolute {
        return fail("lock resources must be repo-relative, not absolute");
    }
    if raw == ".." || raw.starts_with("../") {
        return fail("lock resources must stay inside the repository");
    }
    let trimmed = raw.trim_end_matches('/');
    Ok(if trimmed.is_empty() {
        ".".to_string()
    } else {
        trimmed.to_string()
    })
}

pub fn resource_has_glob(resource: &str) -> bool {
    resource.chars().any(|ch| matches!(ch, '*' | '?' | '['))
}

pub fn resources_overlap(first: &str, second: &str) -> Result<bool> {
    let first = normalize_resource(first)?;
    let second = normalize_resource(second)?;
    if first == second {
        return Ok(true);
    }
    if first == "." || second == "." || first == "project" || second == "project" {
        return Ok(true);
    }
    if resource_has_glob(&first) || resource_has_glob(&second) {
        if fnmatch(&first, &second) || fnmatch(&second, &first) {
            return Ok(true);
        }
        let first_prefix = first
            .split(['*', '?', '['])
            .next()
            .unwrap_or("")
            .trim_end_matches('/');
        let second_prefix = second
            .split(['*', '?', '['])
            .next()
            .unwrap_or("")
            .trim_end_matches('/');
        if !first_prefix.is_empty()
            && (second == first_prefix || second.starts_with(&(first_prefix.to_string() + "/")))
        {
            return Ok(true);
        }
        if !second_prefix.is_empty()
            && (first == second_prefix || first.starts_with(&(second_prefix.to_string() + "/")))
        {
            return Ok(true);
        }
        return Ok(false);
    }
    Ok(first.starts_with(&(second.clone() + "/")) || second.starts_with(&(first + "/")))
}

fn corrupt_payload(path: &Path, error: &str) -> Value {
    json!({
        "resource": null,
        "agent": "unknown",
        "corrupt": true,
        "error": format!("{} is not valid JSON: {error}", path.file_name().and_then(|n| n.to_str()).unwrap_or("lock")),
    })
}

/// Read a lock payload; a corrupt file becomes a conflict, never "free".
pub fn read_holder(path: &Path) -> Option<Value> {
    match read_json(path) {
        Ok(Some(value @ Value::Object(_))) => Some(value),
        Ok(Some(other)) => Some(other),
        Ok(None) => None,
        Err(error) => Some(corrupt_payload(path, &error.to_string())),
    }
}

/// The live holder of `resource`, or `{}` when it is free or stale.
pub fn effective_holder(ws: &Workspace, resource: &str) -> Value {
    let normalized = match normalize_resource(resource) {
        Ok(normalized) => normalized,
        Err(error) => {
            return json!({"corrupt": true, "agent": "unknown", "error": error.to_string()})
        }
    };
    let holder = match read_holder(&lock_path(&ws.locks_dir(), &normalized)) {
        Some(holder) => holder,
        None => return json!({}),
    };
    if holder
        .get("corrupt")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return holder;
    }
    let (_, stale_after) = lock_settings(ws);
    if lock_is_stale(Some(&holder), stale_after) {
        json!({})
    } else {
        holder
    }
}

#[derive(Clone, Debug, Default)]
pub struct LockResult {
    pub ok: bool,
    pub lock: Option<Value>,
    pub path: Option<PathBuf>,
    pub holder: Option<Value>,
    pub error: Option<String>,
    pub covered_by: Option<String>,
    pub refreshed: bool,
}

impl LockResult {
    fn refused(holder: Option<Value>, path: Option<PathBuf>) -> Self {
        LockResult {
            ok: false,
            holder,
            path,
            ..Default::default()
        }
    }
}

pub fn acquire_lock(
    ws: &Workspace,
    resource: &str,
    agent: Option<&str>,
    task: Option<&str>,
    ttl: Option<u64>,
    force: bool,
) -> Result<LockResult> {
    ensure_dirs(ws)?;
    let resource = match normalize_resource(resource) {
        Ok(resource) => resource,
        Err(error) => {
            return Ok(LockResult {
                error: Some(error.to_string()),
                ..Default::default()
            })
        }
    };
    let (default_ttl, stale_after) = lock_settings(ws);
    let ttl = ttl.unwrap_or(default_ttl);
    let max_ttl = max_lock_ttl(ws);
    if ttl > max_ttl {
        return Ok(LockResult {
            error: Some(format!("ttl must be <= {max_ttl} seconds")),
            ..Default::default()
        });
    }
    let path = lock_path(&ws.locks_dir(), &resource);
    let stamp = iso(None);
    let empty_task = Value::Null;
    let task_value = task
        .map(|t| Value::String(t.to_string()))
        .unwrap_or(empty_task);
    let mut payload = Map::new();
    payload.insert("resource".into(), json!(resource));
    payload.insert("agent".into(), json!(agent.unwrap_or("unknown")));
    payload.insert("task".into(), task_value.clone());
    payload.insert("host".into(), json!(ws.host));
    payload.insert("pid".into(), json!(std::process::id()));
    payload.insert("started_at".into(), json!(stamp));
    payload.insert("updated_at".into(), json!(stamp));
    payload.insert("expires_at".into(), json!(expiry(&stamp, ttl)));
    payload.insert("ttl_seconds".into(), json!(ttl));
    let payload = Value::Object(payload);
    let mut forced: Vec<(String, Map<String, Value>)> = Vec::new();

    let outcome = (|| -> Result<LockResult> {
        let _guard = registry_mutex(ws)?;
        if path.exists() {
            let holder = read_holder(&path);
            if let Some(holder) = holder {
                let holder_resource = holder.get("resource").and_then(Value::as_str);
                let same_resource =
                    holder_resource.is_none() || holder_resource == Some(resource.as_str());
                if !same_resource {
                    return Ok(LockResult::refused(Some(holder), Some(path)));
                }
                let corrupt = holder
                    .get("corrupt")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                if corrupt {
                    if !force {
                        return Ok(LockResult::refused(Some(holder), Some(path)));
                    }
                    let _ = fs::remove_file(&path);
                    let mut fields = Map::new();
                    fields.insert("resource".into(), json!(resource));
                    fields.insert("agent".into(), json!(agent));
                    fields.insert("task".into(), task_value.clone());
                    fields.insert("previous_agent".into(), json!("corrupt"));
                    fields.insert(
                        "previous_resource".into(),
                        holder.get("resource").cloned().unwrap_or(json!(resource)),
                    );
                    forced.push(("lock_forced".into(), fields));
                } else if force {
                    let _ = fs::remove_file(&path);
                    let mut fields = Map::new();
                    fields.insert("resource".into(), json!(resource));
                    fields.insert("agent".into(), json!(agent));
                    fields.insert("task".into(), task_value.clone());
                    fields.insert(
                        "previous_agent".into(),
                        holder.get("agent").cloned().unwrap_or(Value::Null),
                    );
                    fields.insert(
                        "previous_task".into(),
                        holder.get("task").cloned().unwrap_or(Value::Null),
                    );
                    fields.insert(
                        "previous_resource".into(),
                        holder.get("resource").cloned().unwrap_or(json!(resource)),
                    );
                    forced.push(("lock_forced".into(), fields));
                } else if agent.is_some()
                    && holder.get("agent").and_then(Value::as_str) == agent
                    && holder.get("task").and_then(Value::as_str).unwrap_or("")
                        == task.unwrap_or("")
                {
                    let mut refreshed = holder.as_object().cloned().unwrap_or_default();
                    let updated = iso(None);
                    refreshed.insert("updated_at".into(), json!(updated));
                    refreshed.insert("expires_at".into(), json!(expiry(&updated, ttl)));
                    refreshed.insert("ttl_seconds".into(), json!(ttl));
                    refreshed.insert("pid".into(), json!(std::process::id()));
                    refreshed.insert("host".into(), json!(ws.host));
                    if let Some(task) = task {
                        refreshed.insert("task".into(), json!(task));
                    }
                    let refreshed = Value::Object(refreshed);
                    write_json_atomic(&path, &refreshed)?;
                    return Ok(LockResult {
                        ok: true,
                        lock: Some(refreshed),
                        path: Some(path),
                        refreshed: true,
                        ..Default::default()
                    });
                } else if lock_is_stale(Some(&holder), stale_after) {
                    let _ = fs::remove_file(&path);
                    let mut fields = Map::new();
                    fields.insert("resource".into(), json!(resource));
                    fields.insert("agent".into(), json!(agent));
                    fields.insert("task".into(), task_value.clone());
                    fields.insert(
                        "previous_agent".into(),
                        holder.get("agent").cloned().unwrap_or(Value::Null),
                    );
                    fields.insert(
                        "previous_task".into(),
                        holder.get("task").cloned().unwrap_or(Value::Null),
                    );
                    forced.push(("lock_replaced_stale".into(), fields));
                } else {
                    return Ok(LockResult::refused(Some(holder), Some(path)));
                }
            }
        }
        let entries = fs::read_dir(ws.locks_dir())?;
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if !name.ends_with(".lock")
                || name
                    == path
                        .file_name()
                        .map(|n| n.to_string_lossy())
                        .unwrap_or_default()
            {
                continue;
            }
            let other_path = entry.path();
            let other = match read_holder(&other_path) {
                Some(other) => other,
                None => continue,
            };
            let other_resource = other
                .get("resource")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            if other
                .get("corrupt")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                if force {
                    let _ = fs::remove_file(&other_path);
                    let mut fields = Map::new();
                    fields.insert("resource".into(), json!(resource));
                    fields.insert("agent".into(), json!(agent));
                    fields.insert("task".into(), task_value.clone());
                    fields.insert("previous_agent".into(), json!("corrupt"));
                    fields.insert("previous_resource".into(), json!(name));
                    forced.push(("lock_forced".into(), fields));
                    continue;
                }
                return Ok(LockResult::refused(Some(other), Some(other_path)));
            }
            if resource.starts_with("task-") || other_resource.starts_with("task-") {
                continue;
            }
            if lock_is_stale(Some(&other), stale_after) {
                if force {
                    let _ = fs::remove_file(&other_path);
                }
                continue;
            }
            let overlaps = resources_overlap(&resource, &other_resource).unwrap_or(false);
            if !overlaps {
                continue;
            }
            let same_owner = other.get("agent").and_then(Value::as_str) == agent
                && other.get("task").and_then(Value::as_str).unwrap_or("") == task.unwrap_or("");
            if same_owner && path_covers(&other_resource, &resource) {
                return Ok(LockResult {
                    ok: true,
                    lock: Some(other),
                    path: Some(other_path),
                    covered_by: Some(other_resource),
                    ..Default::default()
                });
            }
            if force {
                let _ = fs::remove_file(&other_path);
                let mut fields = Map::new();
                fields.insert("resource".into(), json!(resource));
                fields.insert("agent".into(), json!(agent));
                fields.insert("task".into(), task_value.clone());
                fields.insert(
                    "previous_agent".into(),
                    other.get("agent").cloned().unwrap_or(Value::Null),
                );
                fields.insert(
                    "previous_task".into(),
                    other.get("task").cloned().unwrap_or(Value::Null),
                );
                fields.insert("previous_resource".into(), json!(other_resource));
                forced.push(("lock_forced".into(), fields));
                continue;
            }
            return Ok(LockResult::refused(Some(other), Some(other_path)));
        }
        if !create_new_json(&path, &payload)? {
            return Ok(LockResult::refused(read_holder(&path), Some(path)));
        }
        let written = read_holder(&path);
        let valid = written
            .as_ref()
            .map(|value| {
                !value
                    .get("corrupt")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                    && value.get("resource").and_then(Value::as_str) == Some(resource.as_str())
            })
            .unwrap_or(false);
        if !valid {
            let _ = fs::remove_file(&path);
            return Ok(LockResult {
                error: Some("could not write a valid lock file".into()),
                holder: written,
                ..Default::default()
            });
        }
        Ok(LockResult {
            ok: true,
            lock: Some(payload),
            path: Some(path),
            ..Default::default()
        })
    })();

    for (event, mut fields) in forced {
        let pairs: Vec<(&str, Value)> = fields
            .iter_mut()
            .map(|(key, value)| (key.as_str(), value.take()))
            .collect();
        append_event(ws, &event, &pairs);
    }
    outcome
}

pub fn release_lock(
    ws: &Workspace,
    resource: &str,
    agent: Option<&str>,
    force: bool,
    quiet: bool,
) -> Result<()> {
    let resource = normalize_resource(resource)?;
    let path = lock_path(&ws.locks_dir(), &resource);
    let _guard = registry_mutex(ws)?;
    let mut holder = read_holder(&path);
    if let Some(value) = &holder {
        let same = value
            .get("resource")
            .and_then(Value::as_str)
            .map(|name| name == resource)
            .unwrap_or(true);
        if !same {
            holder = None;
        }
    }
    let holder = match holder {
        Some(holder) => holder,
        None => {
            if !quiet {
                println!("No lock held for '{resource}'.");
            }
            return Ok(());
        }
    };
    if holder
        .get("corrupt")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        if !force {
            return fail(format!(
                "Refusing to release '{resource}': {}. Use --force to remove it.",
                holder
                    .get("error")
                    .and_then(Value::as_str)
                    .unwrap_or("corrupt lock")
            ));
        }
    } else if !force {
        let owner = holder
            .get("agent")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let task = holder.get("task").and_then(Value::as_str).unwrap_or("-");
        match agent {
            None => {
                return fail(format!(
                    "Refusing to release '{resource}': held by {owner} (task {task}). Pass --agent {owner} or use --force to override."
                ))
            }
            Some(agent) if agent != owner => {
                return fail(format!(
                    "Refusing to release '{resource}': held by {owner} (task {task}). Use --force to override."
                ))
            }
            _ => {}
        }
    }
    match fs::remove_file(&path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return fail(format!(
                "Could not remove the lock file for '{resource}' ({}): {error}. The lease is still live; fix permissions or the read-only attribute and retry.",
                path.display()
            ))
        }
    }
    if !quiet {
        println!("Released '{resource}'.");
    }
    Ok(())
}

pub fn heartbeat_lock(
    ws: &Workspace,
    resource: &str,
    agent: Option<&str>,
    quiet: bool,
) -> Result<()> {
    let resource = normalize_resource(resource)?;
    let path = lock_path(&ws.locks_dir(), &resource);
    let _guard = registry_mutex(ws)?;
    let mut holder = read_holder(&path);
    if let Some(value) = &holder {
        let same = value
            .get("resource")
            .and_then(Value::as_str)
            .map(|name| name == resource)
            .unwrap_or(true);
        if !same {
            holder = None;
        }
    }
    let mut holder = match holder {
        Some(holder) => holder,
        None => return fail(format!("No lock held for '{resource}'.")),
    };
    if holder
        .get("corrupt")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return fail(format!(
            "Lock '{resource}' is corrupt: {}",
            holder
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("unreadable")
        ));
    }
    if let Some(agent) = agent {
        if holder.get("agent").and_then(Value::as_str) != Some(agent) {
            return fail(format!(
                "Lock '{resource}' is held by {}.",
                holder
                    .get("agent")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
            ));
        }
    }
    if let Some(object) = holder.as_object_mut() {
        let updated = iso(None);
        object.insert("updated_at".into(), json!(updated));
        if let Some(ttl) = object.get("ttl_seconds").and_then(Value::as_u64) {
            object.insert("expires_at".into(), json!(expiry(&updated, ttl)));
        }
    }
    write_json_atomic(&path, &holder)?;
    if !quiet {
        println!(
            "Heartbeat '{resource}' at {}.",
            holder
                .get("updated_at")
                .and_then(Value::as_str)
                .unwrap_or("-")
        );
    }
    Ok(())
}

pub fn list_locks(ws: &Workspace, ensure: bool) -> Vec<Value> {
    if ensure {
        let _ = ensure_dirs(ws);
    }
    let entries = match fs::read_dir(ws.locks_dir()) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    let mut names: Vec<String> = entries
        .flatten()
        .map(|entry| entry.file_name().to_string_lossy().to_string())
        .filter(|name| name.ends_with(".lock"))
        .collect();
    names.sort();
    let mut items = Vec::new();
    for name in names {
        let path = ws.locks_dir().join(&name);
        let mut payload = read_holder(&path).unwrap_or_else(|| json!({}));
        if let Some(object) = payload.as_object_mut() {
            object.insert("_file".into(), json!(name));
        }
        items.push(payload);
    }
    items
}

pub fn lock_remaining_seconds(lock: &Value) -> Option<u64> {
    let ttl = lock.get("ttl_seconds").and_then(Value::as_u64)?;
    let stamp = lock
        .get("updated_at")
        .or_else(|| lock.get("started_at"))
        .and_then(Value::as_str)?;
    let updated = parse_iso(stamp)?;
    let age = (crate::core::time::now() - updated).num_seconds();
    Some((ttl as i64 - age).max(0) as u64)
}

pub fn recent_refusals(ws: &Workspace, limit: usize) -> Vec<Value> {
    let mut events: Vec<Value> = crate::runtime::events::read_events(ws)
        .into_iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("lock_refused"))
        .collect();
    if events.len() > limit {
        events = events.split_off(events.len() - limit);
    }
    events
}

pub fn refusal_detail(event: &Value) -> String {
    if let Some(error) = event.get("error").and_then(Value::as_str) {
        return format!("error: {error}");
    }
    let conflict = match event.get("conflict").and_then(Value::as_str) {
        Some(conflict) => conflict,
        None => return "conflict unknown".to_string(),
    };
    match event.get("conflict_agent").and_then(Value::as_str) {
        Some(agent) => format!("conflict: {conflict} held by {agent}"),
        None => format!("conflict: {conflict}"),
    }
}

pub fn lock_status_payload(ws: &Workspace, locks: &[Value]) -> Value {
    let (_, stale_after) = lock_settings(ws);
    let refusals: Vec<Value> = crate::runtime::events::read_events(ws)
        .into_iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("lock_refused"))
        .collect();
    let mut payload = Vec::new();
    for lock in locks {
        let resource = lock.get("resource").and_then(Value::as_str).unwrap_or("");
        let mut item = lock.clone();
        if let Some(object) = item.as_object_mut() {
            let state = if lock
                .get("corrupt")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                "corrupt"
            } else if lock_is_stale(Some(lock), stale_after) {
                "stale"
            } else {
                "held"
            };
            object.insert("state".into(), json!(state));
            object.insert(
                "remaining_seconds".into(),
                json!(lock_remaining_seconds(lock)),
            );
            let matches: Vec<Value> = refusals
                .iter()
                .filter(|event| {
                    !resource.is_empty()
                        && event.get("conflict").and_then(Value::as_str) == Some(resource)
                })
                .map(|event| {
                    json!({
                        "timestamp": event.get("timestamp"),
                        "agent": event.get("agent"),
                        "task": event.get("task"),
                        "resource": event.get("resource"),
                        "conflict": event.get("conflict"),
                        "holder": event.get("conflict_agent"),
                        "reason": refusal_detail(event),
                    })
                })
                .collect();
            object.insert("refusals".into(), Value::Array(matches));
        }
        payload.push(item);
    }
    Value::Array(payload)
}

pub fn print_lock_table(ws: &Workspace, locks: &[Value]) {
    let (_, stale_after) = lock_settings(ws);
    if locks.is_empty() {
        println!("No locks held.");
        return;
    }
    println!(
        "{:<28} {:<18} {:<8} {:>7}  STATE",
        "RESOURCE", "AGENT", "TASK", "AGE"
    );
    for lock in locks {
        let resource = lock.get("resource").and_then(Value::as_str).unwrap_or("?");
        let agent = lock.get("agent").and_then(Value::as_str).unwrap_or("?");
        let task = lock.get("task").and_then(Value::as_str).unwrap_or("-");
        let (age, state) = if lock
            .get("corrupt")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            ("?".to_string(), "corrupt")
        } else {
            let stamp = lock
                .get("updated_at")
                .or_else(|| lock.get("started_at"))
                .and_then(Value::as_str)
                .unwrap_or("");
            match parse_iso(stamp) {
                Some(updated) => {
                    let seconds = (crate::core::time::now() - updated).num_seconds();
                    let state = if lock_is_stale(Some(lock), stale_after) {
                        "stale"
                    } else {
                        "held"
                    };
                    (format!("{seconds}s"), state)
                }
                None => ("?".to_string(), "stale"),
            }
        };
        println!(
            "{:<28} {:<18} {:<8} {:>7}  {state}",
            truncate(resource, 28),
            truncate(agent, 18),
            task,
            age
        );
    }
}

fn truncate(value: &str, width: usize) -> String {
    value.chars().take(width).collect()
}

pub fn task_lock_resource(task_id: &str) -> String {
    format!("task-{task_id}")
}
