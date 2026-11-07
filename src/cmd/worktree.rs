//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use std::path::{Path, PathBuf};

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::git::repo as git;
use crate::git::worktrees;
use crate::tasks::store;

use crate::{WorktreeAction, WorktreeArgs};
pub fn run(ws: &Workspace, args: &WorktreeArgs) -> Result<i32> {
    let tasks = store::load_tasks(ws);
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai worktree <list|path|prune>");
            return Ok(1);
        }
    };
    match action {
        WorktreeAction::Path { task_id } => {
            let path = store::find_task(ws, task_id);
            let meta = match path {
                Some(path) => store::parse_task(&path)?.0,
                None => serde_json::Map::new(),
            };
            let task = store::Task {
                meta,
                body: String::new(),
                path: PathBuf::new(),
                folder: "active".into(),
            };
            match git::task_root(ws, &task) {
                Some(root) => {
                    println!("{}", root.display());
                    Ok(0)
                }
                None => {
                    eprintln!("Task {task_id} has no worktree.");
                    Ok(1)
                }
            }
        }
        WorktreeAction::List { json } => {
            let rows = worktrees::listing(ws, &tasks);
            if *json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(
                        &rows.iter().map(worktrees::Row::to_json).collect::<Vec<_>>()
                    )?
                );
                return Ok(0);
            }
            if rows.is_empty() {
                println!("No task worktrees.");
            }
            for row in &rows {
                let owner = match &row.task {
                    Some(task) => format!(
                        "task {task} ({}, {})",
                        row.status.clone().unwrap_or_default(),
                        row.owner.clone().unwrap_or_else(|| "unowned".to_string())
                    ),
                    None => "NO TASK".to_string(),
                };
                let flag = if row.orphan { " ORPHAN" } else { "" };
                let dirty = if row.dirty > 0 {
                    format!("  dirty:{}", row.dirty)
                } else {
                    String::new()
                };
                println!(
                    "{:<34} {:<28} {owner}{flag}{dirty}",
                    row.name,
                    row.branch.clone().unwrap_or_else(|| "?".to_string())
                );
            }
            Ok(0)
        }
        WorktreeAction::Prune { force } => {
            let rows = worktrees::listing(ws, &tasks);
            let mut removed = 0;
            for row in &rows {
                if !row.orphan {
                    continue;
                }
                if row.dirty > 0 && !force {
                    eprintln!(
                        "Kept {}: uncommitted changes (use --force to discard them).",
                        row.name
                    );
                    continue;
                }
                let discard = *force || (row.branch.is_none() && row.dirty == 0);
                let (ok, note) = worktrees::remove(ws, Path::new(&row.path), discard);
                if ok {
                    println!("Removed {}", row.name);
                    removed += 1;
                } else {
                    println!("Could not remove {}: {note}", row.name);
                }
            }
            let _ = git::run_git(&ws.project, &["worktree", "prune"]);
            println!("{removed} worktree(s) removed.");
            Ok(0)
        }
    }
}
