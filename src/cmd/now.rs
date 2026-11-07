//! `ai now`, `ai context` and `ai status`: where am I and what is next.

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::workspace::{Workspace, VERSION};
use crate::runtime::overview;

use crate::NowArgs;

fn task_line(task: &Value) -> String {
    format!(
        "{} {} ({}) {}",
        task.get("id").and_then(Value::as_str).unwrap_or("-"),
        task.get("status").and_then(Value::as_str).unwrap_or("-"),
        task.get("owner").and_then(Value::as_str).unwrap_or("-"),
        task.get("title").and_then(Value::as_str).unwrap_or("")
    )
}

pub fn now(ws: &Workspace, args: &NowArgs) -> Result<i32> {
    let data = overview::build(ws, args.agent.as_deref(), 5, args.role.as_deref());
    if args.json {
        let mut payload = overview::compact(&data);
        if let Some(object) = payload.as_object_mut() {
            object.insert("schema".into(), json!(2));
            let recommended = data.get("recommended").cloned().unwrap_or(json!({}));
            object.insert(
                "needs_human".into(),
                json!(recommended
                    .get("needs_human")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)),
            );
            object.insert(
                "question".into(),
                recommended.get("question").cloned().unwrap_or(Value::Null),
            );
            object.insert(
                "next_args".into(),
                recommended
                    .get("next_args")
                    .cloned()
                    .unwrap_or_else(|| json!([])),
            );
            object.insert(
                "blocker".into(),
                recommended.get("blocker").cloned().unwrap_or(Value::Null),
            );
        }
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }
    let git = data.get("git").cloned().unwrap_or(json!({}));
    let dirty = git.get("dirty").and_then(Value::as_u64).unwrap_or(0);
    let tree = if dirty > 0 {
        format!("dirty:{dirty}")
    } else {
        "clean".to_string()
    };
    let branch = git.get("branch").and_then(Value::as_str).unwrap_or("");
    let head = git.get("head").and_then(Value::as_str).unwrap_or("");
    let state = if git.get("ready").and_then(Value::as_bool).unwrap_or(false) || !branch.is_empty()
    {
        format!("{branch}@{head} {tree}")
    } else {
        "not initialized".to_string()
    };
    let active = data
        .get("active")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let done_total = data.get("done_total").and_then(Value::as_u64).unwrap_or(0);
    let locks = data
        .get("locks")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let mut lines = vec![format!(
        "ai {VERSION} | mode {} | git {state} | {active} active, {done_total} done, {locks} locks",
        data.get("mode").and_then(Value::as_str).unwrap_or("-")
    )];
    for task in data
        .get("mine")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        lines.push(format!("YOU   {}", task_line(task)));
    }
    let recommended = data.get("recommended").cloned().unwrap_or(json!({}));
    let command = recommended.get("cmd").and_then(Value::as_str).unwrap_or("");
    lines.push(format!(
        "NEXT  {}",
        if command.is_empty() {
            "(nothing to run)"
        } else {
            command
        }
    ));
    lines.push(format!(
        "WHY   {}",
        recommended
            .get("why")
            .and_then(Value::as_str)
            .unwrap_or("-")
    ));
    if let Some(extras) = recommended.get("extra").and_then(Value::as_array) {
        for extra in extras.iter().filter_map(Value::as_str) {
            lines.push(format!("ALSO  {extra}"));
        }
    }
    if command == "ai setup" {
        if let Ok(state) = crate::config::preferences::status(ws) {
            for row in state.questions.iter().filter(|row| !row.answered) {
                lines.push(format!("ASK   {}: {}", row.key, row.ask));
            }
        }
    }
    if let Some(handoff) = data
        .get("handoffs")
        .and_then(Value::as_array)
        .and_then(|items| items.first())
    {
        if !command.starts_with("ai resume") {
            lines.push(format!(
                "HANDOFF task {} from {}: {} -> ai resume {}",
                handoff.get("task").and_then(Value::as_str).unwrap_or("-"),
                handoff.get("agent").and_then(Value::as_str).unwrap_or("-"),
                handoff.get("reason").and_then(Value::as_str).unwrap_or("-"),
                handoff.get("task").and_then(Value::as_str).unwrap_or("-")
            ));
        }
    }
    if let Some(queue) = data.get("review_queue").and_then(Value::as_array) {
        if !queue.is_empty() {
            lines.push(format!(
                "REVIEW {}",
                queue
                    .iter()
                    .take(3)
                    .map(task_line)
                    .collect::<Vec<_>>()
                    .join("; ")
            ));
        }
    }
    if let Some(ready) = data.get("ready").and_then(Value::as_array) {
        if !ready.is_empty() {
            lines.push(format!(
                "READY  {}",
                ready
                    .iter()
                    .take(3)
                    .map(|task| format!(
                        "{} [{}] {}",
                        task.get("id").and_then(Value::as_str).unwrap_or("-"),
                        task.get("priority").and_then(Value::as_str).unwrap_or("-"),
                        task.get("title").and_then(Value::as_str).unwrap_or("")
                    ))
                    .collect::<Vec<_>>()
                    .join("; ")
            ));
        }
    }
    let blocked = data
        .get("blocked")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let waiting = data
        .get("waiting")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if !blocked.is_empty() || !waiting.is_empty() {
        let mut waits: Vec<String> = blocked
            .iter()
            .map(|task| {
                format!(
                    "{} blocked",
                    task.get("id").and_then(Value::as_str).unwrap_or("-")
                )
            })
            .collect();
        for entry in waiting.iter().take(3) {
            let id = entry
                .get("task")
                .and_then(|task| task.get("id"))
                .and_then(Value::as_str)
                .unwrap_or("-");
            let reasons = entry
                .get("reasons")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(Value::as_str)
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .unwrap_or_default();
            waits.push(format!("{id} waits {reasons}"));
        }
        lines.push(format!("WAIT   {}", waits.join("; ")));
    }
    if let Some(others) = data.get("others").and_then(Value::as_array) {
        if !others.is_empty() {
            lines.push(format!(
                "BUSY   {}",
                others
                    .iter()
                    .take(3)
                    .map(task_line)
                    .collect::<Vec<_>>()
                    .join("; ")
            ));
        }
    }
    lines.push("More: ai context (history) | ai task show <id> | ai resume <id>".to_string());
    println!("{}", lines.join("\n"));
    Ok(0)
}
