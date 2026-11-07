//! `ai plan`: the chief creates many linked tasks from one JSON document.

use std::io::Read;

use serde_json::Value;

use crate::config::preferences;
use crate::config::roles;
use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::tasks::gates;
use crate::tasks::plan;

use crate::{PlanAction, PlanArgs};

pub fn run(ws: &Workspace, args: &PlanArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai plan apply <plan.json> | ai plan example");
            return Ok(1);
        }
    };
    match action {
        PlanAction::Example => {
            println!("{}", serde_json::to_string_pretty(&plan::example())?);
            Ok(0)
        }
        PlanAction::Apply {
            file,
            role,
            agent,
            dry_run,
            json,
        } => {
            let raw = if file == "-" {
                let mut buffer = String::new();
                std::io::stdin().read_to_string(&mut buffer)?;
                buffer
            } else {
                match std::fs::read_to_string(file) {
                    Ok(text) => text,
                    Err(error) => {
                        eprintln!("Cannot read the plan: {error}");
                        return Ok(1);
                    }
                }
            };
            let document: Value = match serde_json::from_str(&raw) {
                Ok(value) => value,
                Err(error) => {
                    eprintln!("Cannot read the plan: {error}");
                    return Ok(1);
                }
            };
            let (errors, warnings) = plan::validate(&document);
            if !errors.is_empty() {
                eprintln!("Plan rejected; nothing was created:");
                for item in &errors {
                    eprintln!("  - {item}");
                }
                return Ok(1);
            }
            if !dry_run {
                if let Some(blocked) = gates::creation_gate(ws, role.as_deref()) {
                    eprintln!("{blocked}");
                    return Ok(1);
                }
            }
            if let Err(denied) = roles::authorize(ws, agent.as_deref(), "task.new") {
                eprintln!("{denied}");
                return Ok(1);
            }
            for item in &warnings {
                eprintln!("WARN  {item}");
            }
            if *dry_run {
                let count = document
                    .get("tasks")
                    .and_then(Value::as_array)
                    .map(Vec::len)
                    .unwrap_or(0);
                println!("Plan is valid: {count} task(s). Dry run, nothing created.");
                return Ok(0);
            }
            if !preferences::status(ws)
                .map(|state| state.confirmed)
                .unwrap_or(false)
            {
                eprintln!("NOTE  workflow preferences are not confirmed yet: run `ai setup` and ask the user.");
            }
            let created = plan::apply(ws, &document, agent.as_deref())?;
            if *json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&serde_json::json!({
                        "created": created,
                        "warnings": warnings,
                    }))?
                );
                return Ok(0);
            }
            println!("Created {} task(s):", created.len());
            for task in &created {
                let depends = task
                    .get("depends_on")
                    .and_then(Value::as_array)
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(Value::as_str)
                            .collect::<Vec<_>>()
                            .join(", ")
                    })
                    .unwrap_or_default();
                println!(
                    "  {}  {:<14} {}{}",
                    task.get("id").and_then(Value::as_str).unwrap_or("-"),
                    task.get("key").and_then(Value::as_str).unwrap_or("-"),
                    task.get("title").and_then(Value::as_str).unwrap_or(""),
                    if depends.is_empty() {
                        String::new()
                    } else {
                        format!(" after {depends}")
                    }
                );
            }
            println!(
                "Workers now: `ai now --agent <n>` (they claim ready tasks themselves). Fill specs/ for each task first."
            );
            Ok(0)
        }
    }
}
