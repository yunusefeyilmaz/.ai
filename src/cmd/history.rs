//! `ai history`: who moved a task, when, why and on which proof.

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo as git;
use crate::runtime::evidence;
use crate::tasks::history;
use crate::tasks::store;

use crate::HistoryArgs;

pub fn run(ws: &Workspace, args: &HistoryArgs) -> Result<i32> {
    let path = match store::find_task(ws, &args.task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {}.", args.task_id);
            return Ok(1);
        }
    };
    let (meta, body, _) = store::parse_task(&path)?;
    let task_id = meta
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or(&args.task_id)
        .to_string();
    let entries = history::parse(&body);
    let records = evidence::task_records(ws, &task_id);
    let head = git::state(ws)
        .get("head")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    if args.json {
        let status = evidence::task_status(ws, &task_id, head.as_deref(), None);
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "task": task_id,
                "status": meta.get("status"),
                "transitions": entries.iter().map(history::LogEntry::to_json).collect::<Vec<_>>(),
                "evidence": records,
                "evidence_state": status.get("state"),
            }))?
        );
        return Ok(0);
    }
    println!(
        "{task_id} {}  [{}]  {}",
        meta.get("title").and_then(Value::as_str).unwrap_or(""),
        meta.get("status").and_then(Value::as_str).unwrap_or("-"),
        relative_to(&ws.project, &path)
    );
    for entry in &entries {
        if entry.kind == "note" {
            println!("  note  {}", entry.text);
            continue;
        }
        let mut line = format!(
            "  {}  {:<12} {} -> {}",
            entry
                .at
                .as_deref()
                .map(|at| &at[..at.len().min(19)])
                .unwrap_or("-"),
            entry.actor.as_deref().unwrap_or("-"),
            entry.from.as_deref().unwrap_or("-"),
            entry.to.as_deref().unwrap_or("-")
        );
        if !entry.reason.is_empty() {
            line.push_str(&format!("  | {}", entry.reason));
        }
        if !entry.evidence.is_empty() {
            line.push_str(&format!("  | proof: {}", entry.evidence));
        }
        println!("{line}");
    }
    if args.evidence {
        println!("Evidence:");
        if records.is_empty() {
            println!("  (none)");
        }
        for record in &records {
            println!(
                "  {}  {}",
                record
                    .get("at")
                    .and_then(Value::as_str)
                    .map(|at| &at[..at.len().min(19)])
                    .unwrap_or("-"),
                evidence::summary(record)
            );
        }
    } else if !records.is_empty() {
        let verdict = evidence::task_status(ws, &task_id, head.as_deref(), None);
        let mut detail = verdict
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("none")
            .to_string();
        if detail != "green" {
            detail.push_str(&format!(
                " - {}",
                verdict.get("reason").and_then(Value::as_str).unwrap_or("")
            ));
        }
        println!(
            "Evidence: {} record(s), latest {detail} (use --evidence for details)",
            records.len()
        );
    }
    Ok(0)
}
