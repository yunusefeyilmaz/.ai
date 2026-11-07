//! `ai git`: Gitflow branches, guarded commits and merges.

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::git::flow as gitflow;
use crate::git::repo as git;
use crate::runtime::leases::{acquire_lock, release_lock};
use crate::tasks::scope;
use crate::tasks::store;

use crate::{GitAction, GitArgs};

pub fn run(ws: &Workspace, args: &GitArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai git <setup|start|commit|finish|begin|end|verify>");
            return Ok(1);
        }
    };
    match action {
        GitAction::Setup { json, yes } => gitflow::setup(ws, *yes, *json),
        GitAction::Start {
            task,
            agent,
            branch_type,
            base,
            force,
            carry,
            json,
        } => {
            if *json {
                // Branch start has no separate JSON payload; keep the human line.
            }
            gitflow::start_branch(
                ws,
                task,
                agent,
                branch_type,
                base.as_deref(),
                *force,
                *carry,
            )
        }
        GitAction::Commit {
            task,
            agent,
            commit_type,
            scope,
            message,
            body,
            allow_empty,
            verify,
            no_verify,
            force,
            json,
            ci,
        } => gitflow::commit_flow(
            ws,
            task,
            agent,
            commit_type,
            scope.as_deref(),
            message,
            body,
            *allow_empty,
            *verify,
            *no_verify,
            *force,
            ci.as_deref(),
            *json,
        ),
        GitAction::Finish {
            task,
            agent,
            force,
            json,
        } => gitflow::finish_flow(ws, task, agent, *force, *json),
        GitAction::Begin { agent, task, ttl } => {
            let result = acquire_lock(
                ws,
                "@git/index",
                Some(agent),
                task.as_deref(),
                Some(*ttl),
                false,
            )?;
            if !result.ok {
                let holder = result.holder.clone().unwrap_or(json!({}));
                eprintln!(
                    "git index is locked by {} (task {}).",
                    holder
                        .get("agent")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown"),
                    holder.get("task").and_then(Value::as_str).unwrap_or("-")
                );
                return Ok(1);
            }
            println!(
                "Acquired @git/index. Stage and commit only what you own, then run `ai git end`."
            );
            Ok(0)
        }
        GitAction::End { agent, force } => {
            release_lock(ws, "@git/index", agent.as_deref(), *force, false)?;
            Ok(0)
        }
        GitAction::Verify { strict, task, json } => {
            let state = git::state(ws);
            if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
                println!("Not a git repository; nothing to verify.");
                return Ok(0);
            }
            let mut meta = serde_json::Map::new();
            let mut state = state;
            if let Some(task_id) = task {
                let path = match store::find_task(ws, task_id) {
                    Some(path) => path,
                    None => {
                        eprintln!("No task with id {task_id}.");
                        return Ok(1);
                    }
                };
                let (parsed, _, _) = store::parse_task(&path)?;
                let task_struct = store::Task {
                    meta: parsed.clone(),
                    body: String::new(),
                    path: path.clone(),
                    folder: "active".into(),
                };
                if let Some(root) = git::task_root(ws, &task_struct) {
                    state = git::state_at(&root);
                }
                meta = parsed;
            }
            let (uncovered, locks) = gitflow::uncovered_staged(ws, &state);
            let mut out_of_scope = Vec::new();
            if task.is_some() {
                let staged: Vec<String> = state
                    .get("staged")
                    .and_then(Value::as_array)
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(Value::as_str)
                            .map(crate::core::fsio::normalize_rel_path)
                            .collect()
                    })
                    .unwrap_or_default();
                out_of_scope = scope::violations(&meta, &staged);
            }
            if *json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&json!({
                        "staged": state.get("staged").cloned().unwrap_or(json!([])),
                        "uncovered": uncovered,
                        "out_of_scope": out_of_scope,
                        "locks": locks,
                    }))?
                );
            } else {
                if uncovered.is_empty() {
                    println!("All staged paths are covered by a held lock.");
                } else {
                    println!("Staged paths with no held file lock:");
                    for path in &uncovered {
                        println!("  {path}");
                    }
                }
                if !out_of_scope.is_empty() {
                    println!(
                        "Staged paths outside the scope of task {}:",
                        task.as_deref().unwrap_or("-")
                    );
                    for item in &out_of_scope {
                        println!("  {item}");
                    }
                } else if task.is_some() {
                    println!(
                        "All staged paths are inside the scope of task {}.",
                        task.as_deref().unwrap_or("-")
                    );
                }
            }
            Ok(
                if (*strict && !uncovered.is_empty()) || !out_of_scope.is_empty() {
                    1
                } else {
                    0
                },
            )
        }
    }
}
