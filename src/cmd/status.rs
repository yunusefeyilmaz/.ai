//! `ai now`, `ai context` and `ai status`: where am I and what is next.

use std::fs;

use serde_json::{json, Value};

use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::fsio::read_json;
use crate::core::workspace::{relative_to, Workspace};
use crate::runtime::checkpoints;
use crate::runtime::leases::{list_locks, print_lock_table};
use crate::tasks::board;
use crate::tasks::store;

use crate::StatusArgs;

pub fn status(ws: &Workspace, args: &StatusArgs) -> Result<i32> {
    let config = config::load_or_default(ws);
    let tasks = store::load_tasks(ws);
    let locks = list_locks(ws, false);
    if args.board && !args.json {
        println!(
            "{}",
            board::render_board(
                ws,
                &tasks,
                &locks,
                config.get("mode").and_then(Value::as_str).unwrap_or("lite")
            )
        );
        return Ok(0);
    }
    let active: Vec<&crate::tasks::store::Task> =
        tasks.iter().filter(|task| task.is_active()).collect();
    let artifacts = read_json(&ws.manifest_path())
        .ok()
        .flatten()
        .unwrap_or_else(|| json!([]));
    let handoffs = checkpoints::list_handoff_markers(ws, false);
    let mut checkpoints = Vec::new();
    if let Ok(entries) = fs::read_dir(ws.checkpoint_dir()) {
        let mut names: Vec<String> = entries
            .flatten()
            .map(|entry| entry.file_name().to_string_lossy().to_string())
            .filter(|name| name.ends_with(".md"))
            .collect();
        names.sort();
        for name in names {
            let task_id = name.trim_end_matches(".md").to_string();
            let age = checkpoints::checkpoint_age_minutes(ws, &task_id);
            checkpoints.push(json!({"task": task_id, "age_minutes": age}));
        }
    }
    if args.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "workspace": ws.root.to_string_lossy(),
                "project": ws.project.to_string_lossy(),
                "mode": config.get("mode"),
                "active": active.iter().map(|task| task.slim_json()).collect::<Vec<_>>(),
                "locks": locks,
                "handoffs": handoffs,
                "checkpoints": checkpoints,
                "artifacts": artifacts,
            }))?
        );
        return Ok(0);
    }
    println!("Workspace  : {}", ws.root.display());
    println!(
        "Mode       : {}",
        config.get("mode").and_then(Value::as_str).unwrap_or("-")
    );
    println!("Active     : {} task(s)", active.len());
    println!("Locks      : {} held", locks.len());
    println!("Checkpoints: {}", checkpoints.len());
    println!("Handoffs   : {} pending", handoffs.len());
    println!(
        "Artifacts  : {} quarantined",
        artifacts.as_array().map(Vec::len).unwrap_or(0)
    );
    println!();
    if !active.is_empty() {
        let rows: Vec<Vec<String>> = active
            .iter()
            .map(|task| {
                vec![
                    task.id(),
                    task.status(),
                    task.owner().unwrap_or_default(),
                    task.title(),
                ]
            })
            .collect();
        for line in store::text_table(
            &[("ID", 6), ("STATUS", 12), ("OWNER", 18), ("TITLE", 0)],
            &rows,
        ) {
            println!("{line}");
        }
        println!();
    }
    for marker in &handoffs {
        println!(
            "HANDOFF    task {} requested by {} ({})",
            marker.get("task").and_then(Value::as_str).unwrap_or("-"),
            marker.get("agent").and_then(Value::as_str).unwrap_or("-"),
            marker.get("reason").and_then(Value::as_str).unwrap_or("-")
        );
    }
    print_lock_table(ws, &locks);
    let _ = relative_to(&ws.project, &ws.root);
    Ok(0)
}
