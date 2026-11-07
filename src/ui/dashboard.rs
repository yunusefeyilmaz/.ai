//! The read-only dashboard frame used by `ai ui --once` and non-TTY output.

use serde_json::{json, Value};

use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::runtime::checkpoints;
use crate::runtime::leases::list_locks;
use crate::tasks::store;
use crate::UiArgs;

pub fn render(ws: &Workspace, args: &UiArgs) -> Result<i32> {
    let config = config::load_or_default(ws);
    let tasks = store::load_tasks(ws);
    let locks = list_locks(ws, true);
    let active: Vec<&store::Task> = tasks.iter().filter(|task| task.is_active()).collect();
    let done = tasks.len().saturating_sub(active.len());
    let handoffs = checkpoints::list_handoff_markers(ws, true);
    let payload = json!({
        "workspace": ws.root.to_string_lossy(),
        "mode": config.get("mode"),
        "tasks": {
            "active": active.iter().map(|task| task.slim_json()).collect::<Vec<_>>(),
            "done": done,
        },
        "locks": locks,
        "handoffs": handoffs,
        "demo": args.demo,
        "theme": args.theme,
    });
    if args.json {
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }
    println!("=== .ai dashboard (read-only) ===");
    println!(
        "workspace {} | mode {}",
        ws.root.display(),
        config.get("mode").and_then(Value::as_str).unwrap_or("-")
    );
    println!(
        "{} active task(s), {done} done, {} lock(s)",
        active.len(),
        locks.len()
    );
    println!();
    for task in &active {
        println!(
            "{:<6} {:<18} {:<12} {}",
            task.id(),
            task.status(),
            task.owner().unwrap_or_else(|| "-".to_string()),
            task.title()
        );
        let sections = checkpoints::checkpoint_sections(ws, &task.id());
        if let Some(next) = sections.get("next").and_then(Value::as_str) {
            if let Some(first) = next.lines().next().filter(|line| !line.trim().is_empty()) {
                let shown: String = first.chars().take(120).collect();
                println!("       next: {shown}");
            }
        }
    }
    if !handoffs.is_empty() {
        println!();
        for marker in &handoffs {
            println!(
                "HANDOFF task {} from {}: {}",
                marker.get("task").and_then(Value::as_str).unwrap_or("-"),
                marker.get("agent").and_then(Value::as_str).unwrap_or("-"),
                marker.get("reason").and_then(Value::as_str).unwrap_or("-")
            );
        }
    }
    println!();
    println!("(single frame; the live TUI is not part of this port yet)");
    Ok(0)
}
