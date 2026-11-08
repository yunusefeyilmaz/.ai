//! `ai git`: Gitflow branches, guarded commits and merges.

use std::path::PathBuf;

use serde_json::{json, Map, Value};

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::git::flow as gitflow;
use crate::git::repo as git;
use crate::runtime::leases::{acquire_lock, release_lock};
use crate::tasks::scope;
use crate::tasks::store;

use crate::{GitAction, GitArgs};

/// The checkout a `git verify` run should inspect, plus the task metadata that
/// defines its scope: an explicit `--task`, the task whose worktree contains the
/// current directory, the active task on the current branch, or the main
/// checkout.
fn verify_checkout(
    ws: &Workspace,
    task: Option<&str>,
) -> Option<(PathBuf, Map<String, Value>, bool)> {
    if let Some(task_id) = task {
        let task = store::task_of(ws, task_id)?;
        let root = git::task_checkout(ws, &task);
        return Some((root, task.meta, true));
    }
    // Inside a task worktree the workspace resolves to the main checkout, so the
    // checkout comes from the current directory.
    if let Ok(cwd) = std::env::current_dir() {
        if cwd.starts_with(ws.worktrees_dir()) {
            if let Some(task) = store::load_tasks(ws).into_iter().find(|task| {
                git::task_root(ws, task)
                    .map(|root| cwd.starts_with(&root))
                    .unwrap_or(false)
            }) {
                return Some((cwd, task.meta, true));
            }
        }
    }
    let branch = git::state(ws)
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if let Some(task) = store::load_tasks(ws)
        .into_iter()
        .find(|task| task.is_active() && task.get_str("branch").as_deref() == Some(branch.as_str()))
    {
        if let Some(root) = git::task_root(ws, &task) {
            return Some((root, task.meta, true));
        }
    }
    Some((ws.project.clone(), Map::new(), false))
}

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
            let (checkout, meta, scoped) = match verify_checkout(ws, task.as_deref()) {
                Some(found) => found,
                None => {
                    eprintln!("No task with id {}.", task.as_deref().unwrap_or("-"));
                    return Ok(1);
                }
            };
            let state = git::state_at(&checkout);
            let (uncovered, locks) = gitflow::uncovered_staged(ws, &state);
            let mut out_of_scope = Vec::new();
            if scoped {
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
                let label = meta
                    .get("id")
                    .and_then(Value::as_str)
                    .map(ToString::to_string)
                    .or_else(|| task.clone())
                    .unwrap_or_else(|| "-".to_string());
                if !out_of_scope.is_empty() {
                    println!("Staged paths outside the scope of task {label}:");
                    for item in &out_of_scope {
                        println!("  {item}");
                    }
                } else if scoped {
                    println!("All staged paths are inside the scope of task {label}.");
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
