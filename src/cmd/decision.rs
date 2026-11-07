//! `ai decision`: record and list lasting decisions (ADRs).

use serde_json::Value;

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::decisions::adr as decisions;

use crate::{DecisionAction, DecisionArgs};

pub fn run(ws: &Workspace, args: &DecisionArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai decision <new|list>");
            return Ok(1);
        }
    };
    match action {
        DecisionAction::New { title, agent, task } => {
            let path = decisions::create_decision(
                ws,
                title,
                agent.as_deref().unwrap_or("-"),
                task.as_deref().unwrap_or("-"),
            )?;
            println!("Created {}", decisions::relative(ws, &path));
            println!("Fill Context/Decision/Consequences; set Status to accepted when agreed.");
            Ok(0)
        }
        DecisionAction::List { json } => {
            let items = decisions::list_decisions(ws);
            if *json {
                println!("{}", serde_json::to_string_pretty(&items)?);
                return Ok(0);
            }
            if items.is_empty() {
                println!("No decisions recorded.");
            }
            for item in &items {
                let status = item.get("status").and_then(Value::as_str).unwrap_or("-");
                let title = item.get("title").and_then(Value::as_str).unwrap_or("");
                let short: String = item
                    .get("file")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .chars()
                    .take(4)
                    .collect();
                println!("{short}  {status:<11} {title}");
            }
            Ok(0)
        }
    }
}
