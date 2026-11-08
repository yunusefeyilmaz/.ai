//! `ai blueprint`: the chief's architecture proposal and the user's approval.

use std::io::Read;

use serde_json::Value;

use crate::config::blueprint;
use crate::core::error::Result;
use crate::core::time::iso;
use crate::core::workspace::Workspace;
use crate::git::flow as gitflow;

use crate::{BlueprintAction, BlueprintArgs};

fn read_input(path: &str) -> Result<Value> {
    let text = if path == "-" {
        let mut buffer = String::new();
        std::io::stdin().read_to_string(&mut buffer)?;
        buffer
    } else {
        std::fs::read_to_string(path).map_err(|error| {
            crate::core::error::AiError::msg(format!("cannot read the blueprint analysis: {error}"))
        })?
    };
    serde_json::from_str(&text).map_err(|error| {
        crate::core::error::AiError::msg(format!(
            "the blueprint analysis is not valid JSON: {error}"
        ))
    })
}

fn commit(ws: &Workspace, message: &str) {
    gitflow::commit_ledger(ws, &[blueprint::path_of(ws), ws.config_path()], message);
}

pub fn run(ws: &Workspace, args: &BlueprintArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai blueprint propose [--from file|-] | show | revise --set PATH=VALUE | approve --agent <name>");
            return Ok(1);
        }
    };
    match action {
        BlueprintAction::Propose { from, agent, json } => {
            if blueprint::status(ws) == blueprint::State::Approved {
                eprintln!(
                    "A blueprint is already approved. Change it with `ai blueprint revise --set ...` then `ai blueprint approve`, or delete {} to start over.",
                    blueprint::FILE
                );
                return Ok(1);
            }
            let input = match from.as_deref() {
                Some(path) => match read_input(path) {
                    Ok(value) => Some(value),
                    Err(error) => {
                        eprintln!("{error}");
                        return Ok(1);
                    }
                },
                None => None,
            };
            let authored = input.is_some();
            let document = match blueprint::propose(ws, agent.as_deref(), input) {
                Ok(document) => document,
                Err(error) => {
                    eprintln!("{error}");
                    return Ok(1);
                }
            };
            blueprint::write(ws, &document)?;
            commit(ws, "chore(blueprint): record the architecture proposal");
            if *json {
                println!("{}", serde_json::to_string_pretty(&document)?);
                return Ok(0);
            }
            println!("{}", blueprint::summary(&document));
            if authored {
                println!("Nothing is planned yet: the user approves this first, or changes it.");
            } else {
                println!(
                    "This is a draft built from facts only. Chief: analyze the request, write your proposal JSON, then run `ai blueprint propose --from <file>`; the user approves it after that."
                );
            }
            Ok(0)
        }
        BlueprintAction::Show { json } => {
            let document = match blueprint::read(ws) {
                Some(document) => document,
                None => {
                    eprintln!("No blueprint yet. Run `ai blueprint propose` (you are the chief).");
                    return Ok(1);
                }
            };
            if *json {
                println!("{}", serde_json::to_string_pretty(&document)?);
            } else {
                println!("{}", blueprint::summary(&document));
            }
            Ok(0)
        }
        BlueprintAction::Revise { set, json } => {
            let mut document = match blueprint::read(ws) {
                Some(document) => document,
                None => {
                    eprintln!("No blueprint yet. Run `ai blueprint propose` first.");
                    return Ok(1);
                }
            };
            if let Err(error) = blueprint::revise(&mut document, set) {
                eprintln!("{error}");
                return Ok(1);
            }
            if let Some(object) = document.as_object_mut() {
                object.insert("updated".into(), serde_json::json!(iso(None)));
            }
            blueprint::write(ws, &document)?;
            commit(ws, "chore(blueprint): revise the proposal");
            if *json {
                println!("{}", serde_json::to_string_pretty(&document)?);
            } else {
                println!("{}", blueprint::summary(&document));
            }
            Ok(0)
        }
        BlueprintAction::Approve { set, agent, json } => {
            let approved = match blueprint::approve(ws, agent.as_deref(), set) {
                Ok(approved) => approved,
                Err(error) => {
                    eprintln!("{error}");
                    return Ok(1);
                }
            };
            commit(
                ws,
                "chore(blueprint): record the user's architecture approval",
            );
            if *json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&serde_json::json!({
                        "status": "approved",
                        "applied": approved.applied,
                        "blueprint": approved.document,
                    }))?
                );
                return Ok(0);
            }
            println!(
                "Blueprint approved by {}. Applied: {}.",
                agent.as_deref().unwrap_or("the user"),
                approved.applied.join(", ")
            );
            println!("Next: fill specs, then `ai plan apply plan.json --role chief`.");
            Ok(0)
        }
    }
}
