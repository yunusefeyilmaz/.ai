//! `ai recover`: detect or repair inconsistent workspace state.

use std::fs;
use std::path::PathBuf;

use serde_json::{json, Value};

use crate::config::settings as config;
use crate::core::error::{fail, Result};
use crate::core::fsio::lock_path;
use crate::core::time::iso;
use crate::core::workspace::Workspace;
use crate::runtime::checkpoints;
use crate::runtime::leases::{list_locks, lock_is_stale};
use crate::runtime::mutex::workspace_state_guard;
use crate::tasks::store;

use crate::RecoverArgs;

enum Fix {
    MoveToDone(PathBuf),
    SetDone(PathBuf),
    ClearOwner(PathBuf),
    RestoreOwner(PathBuf, String, String),
    RemoveLock(String),
    RebuildSidecar(String),
    RemoveHandoff(PathBuf),
}

fn apply_fix(ws: &Workspace, fix: &Fix) -> Result<()> {
    match fix {
        Fix::MoveToDone(path) => {
            let name = path
                .file_name()
                .map(|name| name.to_os_string())
                .unwrap_or_default();
            fs::rename(path, ws.done_dir().join(name))?;
        }
        Fix::SetDone(path) => {
            let (mut meta, body, _) = store::parse_task(path)?;
            meta.insert("status".into(), json!("done"));
            meta.insert("updated".into(), json!(iso(None)));
            store::write_task(path, &meta, &body)?;
        }
        Fix::ClearOwner(path) => {
            let (mut meta, body, _) = store::parse_task(path)?;
            meta.insert("owner".into(), Value::Null);
            meta.insert("lock".into(), Value::Null);
            if meta.get("status").and_then(Value::as_str) == Some("in_progress") {
                meta.insert("status".into(), json!("todo"));
            }
            meta.insert("updated".into(), json!(iso(None)));
            store::write_task(path, &meta, &body)?;
        }
        Fix::RestoreOwner(path, agent, resource) => {
            let (mut meta, body, _) = store::parse_task(path)?;
            meta.insert("owner".into(), json!(agent));
            meta.insert("lock".into(), json!(resource));
            meta.insert("updated".into(), json!(iso(None)));
            store::write_task(path, &meta, &body)?;
        }
        Fix::RemoveLock(resource) => {
            let path = lock_path(&ws.locks_dir(), resource);
            match fs::remove_file(path) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => {
                    return fail(format!(
                        "could not remove the stale lock for '{resource}': {error}"
                    ))
                }
            }
        }
        Fix::RebuildSidecar(task_id) => {
            let _ = checkpoints::rebuild_sidecar(ws, task_id)?;
        }
        Fix::RemoveHandoff(path) => {
            let _ = fs::remove_file(path);
        }
    }
    Ok(())
}

pub fn run(ws: &Workspace, args: &RecoverArgs) -> Result<i32> {
    if args.apply {
        let _guard = match workspace_state_guard(ws) {
            Ok(guard) => guard,
            Err(error) => {
                eprintln!("Cannot apply recovery while {error}.");
                return Ok(1);
            }
        };
        return inner(ws, args);
    }
    inner(ws, args)
}

fn inner(ws: &Workspace, args: &RecoverArgs) -> Result<i32> {
    let mut actions: Vec<(String, String, Fix)> = Vec::new();
    let mut handled_locks: std::collections::HashSet<String> = std::collections::HashSet::new();

    let tasks = store::load_tasks(ws);
    let (_, stale_after) = config::lock_settings(ws);
    let locks: std::collections::HashMap<String, Value> = list_locks(ws, true)
        .into_iter()
        .filter(|lock| !lock_is_stale(Some(lock), stale_after))
        .filter_map(|lock| {
            lock.get("resource")
                .and_then(Value::as_str)
                .map(|resource| (resource.to_string(), lock.clone()))
        })
        .collect();

    for task in &tasks {
        let task_id = task.id();
        let path = task.path.clone();
        let status = task.status();
        let owner = task.owner();
        let resource = format!("task-{task_id}");
        let lock = locks.get(&resource);
        if task.folder == "active" && status == "done" {
            actions.push((
                format!("move task {task_id} active -> done"),
                "status is done but file is in active/".to_string(),
                Fix::MoveToDone(path.clone()),
            ));
            if lock.is_some() {
                handled_locks.insert(resource.clone());
                actions.push((
                    format!("release lock {resource}"),
                    "task is done".to_string(),
                    Fix::RemoveLock(resource.clone()),
                ));
            }
        }
        if task.folder == "done" && status != "done" {
            actions.push((
                format!("set task {task_id} status done"),
                "file is in done/".to_string(),
                Fix::SetDone(path.clone()),
            ));
        }
        if task.folder == "active" && owner.is_some() && lock.is_none() {
            actions.push((
                format!("clear stale owner on {task_id}"),
                format!("owner '{}' has no lock", owner.clone().unwrap_or_default()),
                Fix::ClearOwner(path.clone()),
            ));
        }
        if task.folder == "active" && lock.is_some() && owner.is_none() {
            let agent = lock
                .and_then(|lock| lock.get("agent"))
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .to_string();
            actions.push((
                format!("restore owner on {task_id}"),
                format!("lock held by {agent}"),
                Fix::RestoreOwner(path.clone(), agent.clone(), resource.clone()),
            ));
        }
        if task.folder == "done" && lock.is_some() && !handled_locks.contains(&resource) {
            actions.push((
                format!("release lock {resource}"),
                "task is done".to_string(),
                Fix::RemoveLock(resource.clone()),
            ));
            handled_locks.insert(resource.clone());
        }
        if let Some(problem) = checkpoints::sidecar_mismatch(ws, &task_id) {
            actions.push((
                format!("rebuild checkpoint sidecar {task_id}"),
                problem,
                Fix::RebuildSidecar(task_id.clone()),
            ));
        }
    }

    let known: std::collections::HashSet<String> = tasks.iter().map(|task| task.id()).collect();
    for resource in locks.keys() {
        if let Some(rest) = resource.strip_prefix("task-") {
            if !known.contains(rest) {
                actions.push((
                    format!("remove orphan lock {resource}"),
                    "no task file".to_string(),
                    Fix::RemoveLock(resource.clone()),
                ));
                handled_locks.insert(resource.clone());
            }
        }
    }

    for lock in list_locks(ws, false) {
        let resource = lock
            .get("resource")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if resource.is_empty() || handled_locks.contains(&resource) {
            continue;
        }
        if lock_is_stale(Some(&lock), stale_after) {
            actions.push((
                format!("remove stale lock {resource}"),
                format!(
                    "held by {}",
                    lock.get("agent").and_then(Value::as_str).unwrap_or("-")
                ),
                Fix::RemoveLock(resource.clone()),
            ));
            handled_locks.insert(resource.clone());
        }
    }

    for marker in checkpoints::list_handoff_markers(ws, true) {
        let task_id = marker
            .get("task")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let path = store::find_task(ws, &task_id);
        let gone_or_done = match &path {
            None => true,
            Some(path) => path.starts_with(ws.done_dir()),
        };
        if gone_or_done {
            let file = marker
                .get("_file")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            actions.push((
                format!("remove orphan handoff marker for {task_id}"),
                "task is gone or done".to_string(),
                Fix::RemoveHandoff(ws.handoff_dir().join(file)),
            ));
        }
    }

    if args.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "actions": actions.iter().map(|(action, _, _)| action).collect::<Vec<_>>(),
                "applied": args.apply,
            }))?
        );
        if !args.apply {
            return Ok(0);
        }
    }
    if actions.is_empty() {
        println!("No inconsistencies found.");
        return Ok(0);
    }
    for (action, reason, _) in &actions {
        println!(
            "{}  {action}  ({reason})",
            if args.apply { "FIX" } else { "FIND" }
        );
    }
    if !args.apply {
        println!("\nRun `ai recover --apply` to repair these.");
        return Ok(0);
    }
    for (_, _, fix) in &actions {
        if let Err(error) = apply_fix(ws, fix) {
            eprintln!("WARN  could not apply repair: {error}");
        }
    }
    if !args.json {
        println!("\nRecovery applied. Run `ai check`.");
    }
    Ok(0)
}
