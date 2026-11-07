//! `ai now`, `ai context` and `ai status`: where am I and what is next.

use serde_json::Value;

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::runtime::checkpoints;
use crate::runtime::overview;

use crate::ContextArgs;

pub fn context(ws: &Workspace, args: &ContextArgs) -> Result<i32> {
    let data = overview::build(ws, args.agent.as_deref(), args.limit, None);
    if args.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&overview::compact(&data))?
        );
        return Ok(0);
    }
    let mut out = vec!["# Project context".to_string()];
    let active = data
        .get("active")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let done_total = data.get("done_total").and_then(Value::as_u64).unwrap_or(0);
    out.push(format!(
        "mode {} | {} active | {done_total} done",
        data.get("mode").and_then(Value::as_str).unwrap_or("-"),
        active.len()
    ));
    out.push(String::new());
    out.push("## Open work".to_string());
    if active.is_empty() {
        out.push("(none)".to_string());
    }
    for task in &active {
        let task_id = task.get("id").and_then(Value::as_str).unwrap_or("-");
        out.push(format!(
            "- {task_id} {} owner={} [{}] {}",
            task.get("status").and_then(Value::as_str).unwrap_or("-"),
            task.get("owner").and_then(Value::as_str).unwrap_or("-"),
            task.get("priority").and_then(Value::as_str).unwrap_or("-"),
            task.get("title").and_then(Value::as_str).unwrap_or("")
        ));
        let sections = checkpoints::checkpoint_sections(ws, task_id);
        if let Some(next) = sections.get("next").and_then(Value::as_str) {
            if let Some(first) = next.lines().next() {
                if !first.trim().is_empty() {
                    out.push(format!("    next: {}", &first[..first.len().min(140)]));
                }
            }
        } else if let Some(spec) = task.get("spec").and_then(Value::as_str) {
            out.push(format!("    spec: {spec}"));
        }
        if let Some(depends) = task.get("depends_on").and_then(Value::as_str) {
            if !depends.is_empty() {
                out.push(format!("    depends_on: {depends}"));
            }
        }
    }
    let done = data
        .get("done")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    out.push(String::new());
    out.push(format!("## Done (last {} of {done_total})", done.len()));
    if done.is_empty() {
        out.push("(nothing shipped yet)".to_string());
    }
    for task in &done {
        out.push(format!(
            "- {} {} ({}, by {})",
            task.get("id").and_then(Value::as_str).unwrap_or("-"),
            task.get("title").and_then(Value::as_str).unwrap_or(""),
            task.get("updated")
                .and_then(Value::as_str)
                .map(|value| &value[..value.len().min(10)])
                .unwrap_or(""),
            task.get("reviewed_by")
                .or_else(|| task.get("owner"))
                .and_then(Value::as_str)
                .unwrap_or("?")
        ));
    }
    if let Some(decisions) = data.get("decisions").and_then(Value::as_array) {
        if !decisions.is_empty() {
            out.push(String::new());
            out.push("## Decisions (ADR)".to_string());
            for item in decisions
                .iter()
                .rev()
                .take(args.limit)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
            {
                let file = item.get("file").and_then(Value::as_str).unwrap_or("");
                let title = item.get("title").and_then(Value::as_str).unwrap_or("");
                let status = item.get("status").and_then(Value::as_str);
                out.push(format!(
                    "- {}: {}{}",
                    file.trim_end_matches(".md"),
                    title,
                    status
                        .map(|value| format!(" [{value}]"))
                        .unwrap_or_default()
                ));
            }
        }
    }
    if let Some(handoffs) = data.get("handoffs").and_then(Value::as_array) {
        if !handoffs.is_empty() {
            out.push(String::new());
            out.push("## Pending handoffs".to_string());
            for handoff in handoffs {
                out.push(format!(
                    "- task {} from {}: {} -> ai resume {}",
                    handoff.get("task").and_then(Value::as_str).unwrap_or("-"),
                    handoff.get("agent").and_then(Value::as_str).unwrap_or("-"),
                    handoff.get("reason").and_then(Value::as_str).unwrap_or("-"),
                    handoff.get("task").and_then(Value::as_str).unwrap_or("-")
                ));
            }
        }
    }
    if let Some(events) = data.get("events").and_then(Value::as_array) {
        if !events.is_empty() {
            out.push(String::new());
            out.push("## Recent activity".to_string());
            let start = events.len().saturating_sub(args.limit);
            for event in &events[start..] {
                out.push(format!(
                    "- {} {} task={} agent={}",
                    event
                        .get("timestamp")
                        .and_then(Value::as_str)
                        .map(|value| &value[..value.len().min(16)])
                        .unwrap_or(""),
                    event.get("event").and_then(Value::as_str).unwrap_or("-"),
                    event.get("task").and_then(Value::as_str).unwrap_or("-"),
                    event.get("agent").and_then(Value::as_str).unwrap_or("-")
                ));
            }
        }
    }
    println!("{}", out.join("\n"));
    Ok(0)
}
