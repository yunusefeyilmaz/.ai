//! `ai lock`: advisory resource leases.

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::runtime::events::append_event;
use crate::runtime::leases::{
    self, acquire_lock, heartbeat_lock, list_locks, lock_status_payload, print_lock_table,
    release_lock, resource_has_glob,
};
use crate::runtime::mutex::workspace_state_guard;
use crate::tasks::scope as task_scope;
use crate::tasks::store;

use crate::{LockAction, LockArgs};

fn widen_scope(
    ws: &Workspace,
    task_id: Option<&str>,
    resource: &str,
    agent: &str,
) -> Result<Option<String>> {
    let task_id = match task_id {
        Some(task_id) => task_id,
        None => return Ok(None),
    };
    if resource_has_glob(resource) || resource.starts_with('@') {
        return Ok(None);
    }
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => return Ok(None),
    };
    let _guard = workspace_state_guard(ws)?;
    let (mut meta, mut body, _) = store::parse_task(&path)?;
    let owner = meta.get("owner").and_then(Value::as_str).unwrap_or("");
    if !owner.is_empty() && owner != agent {
        return Ok(None);
    }
    let allowed = task_scope::split_globs(meta.get("scope_allowed"));
    if allowed.is_empty()
        || allowed
            .iter()
            .any(|glob| task_scope::matches(glob, resource))
    {
        return Ok(None);
    }
    let mut widened = allowed.clone();
    widened.push(resource.to_string());
    meta.insert(
        "scope_allowed".into(),
        json!(task_scope::join_globs(Some(&widened)).unwrap_or_default()),
    );
    let stamp = crate::core::time::iso(None);
    meta.insert("updated".into(), json!(stamp));
    // Make the silent scope expansion reviewable: the task log records who
    // widened it and by which path, so a reviewer can see it without diffing
    // the spec against the committed files.
    let entry = format!("- {stamp} scope widened by {agent}: +{resource}\n");
    if body.ends_with('\n') {
        body.push_str(&entry);
    } else {
        body.push('\n');
        body.push_str(&entry);
    }
    store::write_task(&path, &meta, &body)?;
    append_event(
        ws,
        "scope_widened",
        &[
            ("task", json!(task_id)),
            ("agent", json!(agent)),
            ("resource", json!(resource)),
        ],
    );
    Ok(Some(resource.to_string()))
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
            wait,
            force,
        } => {
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(*wait);
            loop {
                // All or nothing: a batch of paths either locks every one of
                // them or releases the ones this call just took.
                let mut acquired: Vec<&str> = Vec::new();
                let mut failure: Option<(String, leases::LockResult)> = None;
                for item in resource {
                    let result =
                        acquire_lock(ws, item, Some(agent), task.as_deref(), *ttl, *force)?;
                    if result.ok {
                        if result.covered_by.is_none() && !result.refreshed {
                            acquired.push(item.as_str());
                        }
                        if let Some(covered) = &result.covered_by {
                            println!("'{item}' is already covered by {agent}'s lock '{covered}'.");
                        } else {
                            println!("Acquired '{item}' for {agent}.");
                        }
                        if let Some(widened) = widen_scope(ws, task.as_deref(), item, agent)? {
                            println!(
                                "Added '{widened}' to task {}'s scope_allowed (so the commit gate accepts it).",
                                task.as_deref().unwrap_or("-")
                            );
                        }
                    } else {
                        failure = Some((item.clone(), result));
                        break;
                    }
                }
                let (resource, result) = match failure {
                    None => return Ok(0),
                    Some(failure) => failure,
                };
                if !*force {
                    for item in acquired {
                        let _ = release_lock(ws, item, Some(agent), false, true);
                    }
                }
                if std::time::Instant::now() < deadline {
                    eprintln!(
                        "'{resource}' is held; waiting {} more second(s).",
                        deadline
                            .saturating_duration_since(std::time::Instant::now())
                            .as_secs()
                    );
                    std::thread::sleep(std::time::Duration::from_secs(1));
                    continue;
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
                return Ok(1);
            }
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
