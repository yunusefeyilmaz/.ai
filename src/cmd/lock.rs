//! `ai lock`: advisory resource leases.

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::runtime::events::append_event;
use crate::runtime::leases::{
    self, acquire_lock, heartbeat_lock, list_locks, lock_status_payload, print_lock_table,
    release_lock, resource_has_glob,
};
use crate::tasks::scope as task_scope;
use crate::tasks::store;

use crate::{LockAction, LockArgs};

fn widen_scope(
    ws: &Workspace,
    task_id: Option<&str>,
    resource: &str,
    agent: &str,
) -> Option<String> {
    let task_id = task_id?;
    if resource_has_glob(resource) || resource.starts_with('@') {
        return None;
    }
    let path = store::find_task(ws, task_id)?;
    let (mut meta, body, _) = store::parse_task(&path).ok()?;
    let owner = meta.get("owner").and_then(Value::as_str).unwrap_or("");
    if !owner.is_empty() && owner != agent {
        return None;
    }
    let allowed = task_scope::split_globs(meta.get("scope_allowed"));
    if allowed.is_empty()
        || allowed
            .iter()
            .any(|glob| task_scope::matches(glob, resource))
    {
        return None;
    }
    let mut widened = allowed.clone();
    widened.push(resource.to_string());
    meta.insert(
        "scope_allowed".into(),
        json!(task_scope::join_globs(Some(&widened)).unwrap_or_default()),
    );
    let _ = store::write_task(&path, &meta, &body);
    Some(resource.to_string())
}

pub fn run(ws: &Workspace, args: &LockArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai lock <acquire|release|heartbeat|status>");
            return Ok(1);
        }
    };
    match action {
        LockAction::Acquire {
            resource,
            agent,
            task,
            ttl,
            force,
        } => {
            let result = acquire_lock(ws, resource, Some(agent), task.as_deref(), *ttl, *force)?;
            if result.ok {
                if let Some(covered) = &result.covered_by {
                    println!("'{resource}' is already covered by {agent}'s lock '{covered}'.");
                } else {
                    println!("Acquired '{resource}' for {agent}.");
                }
                if let Some(widened) = widen_scope(ws, task.as_deref(), resource, agent) {
                    println!(
                        "Added '{widened}' to task {}'s scope_allowed (so the commit gate accepts it).",
                        task.as_deref().unwrap_or("-")
                    );
                }
                return Ok(0);
            }
            if let Some(error) = &result.error {
                eprintln!("Cannot acquire '{resource}': {error}");
                return Ok(1);
            }
            let holder = result.holder.clone().unwrap_or(json!({}));
            eprintln!(
                "'{resource}' is held by {} (task {}, since {}).",
                holder
                    .get("agent")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                holder.get("task").and_then(Value::as_str).unwrap_or("-"),
                holder
                    .get("started_at")
                    .and_then(Value::as_str)
                    .unwrap_or("-")
            );
            append_event(
                ws,
                "lock_refused",
                &[
                    ("resource", json!(resource)),
                    ("agent", json!(agent)),
                    ("task", json!(task)),
                    (
                        "conflict",
                        holder.get("resource").cloned().unwrap_or(Value::Null),
                    ),
                    (
                        "conflict_agent",
                        holder.get("agent").cloned().unwrap_or(Value::Null),
                    ),
                ],
            );
            Ok(1)
        }
        LockAction::Release {
            resource,
            agent,
            force,
        } => {
            release_lock(ws, resource, agent.as_deref(), *force, false)?;
            Ok(0)
        }
        LockAction::Heartbeat { resource, agent } => {
            heartbeat_lock(ws, resource, agent.as_deref(), false)?;
            Ok(0)
        }
        LockAction::Status { json } => {
            let locks = list_locks(ws, true);
            if *json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&lock_status_payload(ws, &locks))?
                );
                return Ok(0);
            }
            print_lock_table(ws, &locks);
            Ok(0)
        }
    }
}

#[allow(dead_code)]
fn _unused(_: &leases::LockResult) {}
