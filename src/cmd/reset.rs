//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use std::fs;
use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::fsio::lock_path;
use crate::core::workspace::{relative_to, Workspace};
use crate::runtime::leases::{acquire_lock, release_lock};
use crate::runtime::mutex::registry_mutex;
use crate::tasks::store;

use crate::ResetArgs;
fn reset_lock_files(ws: &Workspace) -> Vec<PathBuf> {
    let mut files: Vec<PathBuf> = fs::read_dir(ws.locks_dir())
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| {
                    path.file_name()
                        .map(|name| name.to_string_lossy().ends_with(".lock"))
                        .unwrap_or(false)
                })
                .collect()
        })
        .unwrap_or_default();
    files.sort();
    files
}

/// The files `ai reset --hard` would remove. Public so tests (and a future
/// `--dry-run`) can prove the scope without driving an interactive prompt.
pub fn targets(ws: &Workspace) -> Vec<PathBuf> {
    reset_targets(ws)
}

fn reset_targets(ws: &Workspace) -> Vec<PathBuf> {
    let mut targets: std::collections::BTreeSet<PathBuf> = std::collections::BTreeSet::new();
    let preserved = [".gitkeep", "TEMPLATE.md", "README.md"];
    for directory in [
        ws.active_dir(),
        ws.done_dir(),
        ws.specs_active_dir(),
        ws.specs_done_dir(),
    ] {
        if let Ok(entries) = fs::read_dir(directory) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                let path = entry.path();
                if !preserved.contains(&name.as_str()) && name.ends_with(".md") && path.is_file() {
                    targets.insert(path);
                }
            }
        }
    }
    let decisions = ws.decisions_dir();
    if decisions.is_dir()
        && fs::symlink_metadata(&decisions)
            .map(|m| !m.file_type().is_symlink())
            .unwrap_or(true)
    {
        if let Ok(entries) = fs::read_dir(&decisions) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                let path = entry.path();
                let is_adr = name.len() > 7
                    && name.as_bytes().get(4) == Some(&b'-')
                    && name.ends_with(".md")
                    && name[..4].chars().all(|ch| ch.is_ascii_digit());
                if is_adr && path.is_file() {
                    targets.insert(path);
                }
            }
        }
    }
    for root in [
        ws.artifacts_dir(),
        ws.logs_dir(),
        // The whole state tree is derived: checkpoints, handoffs, evidence,
        // events, the plan approval and the task counter. Ids restart after a
        // reset, so leaving evidence behind would let an old green record
        // authorise a brand-new task with the same id.
        ws.state_dir(),
    ] {
        collect_files(&root, &mut targets);
    }
    targets.into_iter().collect()
}

fn collect_files(root: &Path, targets: &mut std::collections::BTreeSet<PathBuf>) {
    let entries = match fs::read_dir(root) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(_) => continue,
        };
        if metadata.file_type().is_symlink() {
            targets.insert(path);
            continue;
        }
        if metadata.is_dir() {
            collect_files(&path, targets);
        } else if name != ".gitkeep" {
            targets.insert(path);
        }
    }
}

fn reset_target_error(ws: &Workspace, targets: &[PathBuf]) -> Option<String> {
    let workspace = fs::canonicalize(&ws.root).unwrap_or_else(|_| ws.root.clone());
    let roots = [
        ws.active_dir(),
        ws.done_dir(),
        ws.specs_active_dir(),
        ws.specs_done_dir(),
        ws.decisions_dir(),
        ws.artifacts_dir(),
        ws.logs_dir(),
        ws.state_dir(),
    ];
    for target in targets {
        let resolved = fs::canonicalize(target).unwrap_or_else(|_| target.clone());
        if !resolved.starts_with(&workspace) {
            return Some(format!(
                "Refusing to reset a path outside the approved state folders: {}",
                target.display()
            ));
        }
        let in_scope = roots.iter().any(|root| {
            let root = fs::canonicalize(root).unwrap_or_else(|_| root.clone());
            resolved.starts_with(&root)
        });
        if !in_scope {
            return Some(format!(
                "Refusing to reset a path outside the approved state folders: {}",
                target.display()
            ));
        }
        if !(target.is_file()
            || fs::symlink_metadata(target)
                .map(|m| m.file_type().is_symlink())
                .unwrap_or(false))
        {
            return Some(format!(
                "Refusing to reset a non-file path: {}",
                target.display()
            ));
        }
    }
    None
}

/// Remove one reset target. A directory symlink needs `remove_dir` on Windows
/// because `remove_file` refuses it; on Unix `remove_file` unlinks the symlink.
fn remove_reset_target(target: &Path) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        if target.is_dir() {
            return fs::remove_dir(target);
        }
    }
    fs::remove_file(target)
}

pub fn run(ws: &Workspace, args: &ResetArgs) -> Result<i32> {
    if !args.hard {
        eprintln!("Specify --hard to reset .ai project task, spec, decision and runtime state.");
        return Ok(1);
    }
    if !std::io::stdin().is_terminal() {
        eprintln!("Hard reset requires an interactive terminal; no files were changed.");
        return Ok(1);
    }
    let locks = reset_lock_files(ws);
    if !locks.is_empty() {
        eprintln!("Hard reset requires all locks to be released. Existing lock files:");
        for path in &locks {
            eprintln!("  {}", relative_to(&ws.root, path));
        }
        eprintln!("Resolve stale locks with `ai recover --apply`, then retry.");
        return Ok(1);
    }
    if fs::symlink_metadata(ws.decisions_dir())
        .map(|m| m.file_type().is_symlink())
        .unwrap_or(false)
    {
        eprintln!(
            "Refusing to reset decision records through a symlinked docs/decisions directory."
        );
        return Ok(1);
    }
    let mut targets = reset_targets(ws);
    if let Some(error) = reset_target_error(ws, &targets) {
        eprintln!("{error}");
        return Ok(1);
    }
    println!("Hard reset removes task/spec/decision records, checkpoints, handoffs,");
    println!("artifacts, logs and the task counter. It keeps framework docs and Git history.");
    println!("Files to remove: {}", targets.len());
    print!("Type 'reset .ai hard' to continue: ");
    let _ = std::io::stdout().flush();
    let mut confirmation = String::new();
    let _ = std::io::stdin().read_line(&mut confirmation);
    if confirmation.trim() != "reset .ai hard" {
        eprintln!("Confirmation did not match; no files were changed.");
        return Ok(1);
    }
    let resource = "project";
    let agent = "operator-reset";
    let mut acquired = false;
    let mut code = 1;
    let outcome: Result<()> = {
        let mut run_reset = || -> Result<()> {
            let _registry = registry_mutex(ws)?;
            let result = acquire_lock(ws, resource, Some(agent), None, Some(600), false)?;
            if !result.ok {
                let holder = result.holder.clone().unwrap_or_else(|| json!({}));
                eprintln!(
                    "Could not start reset; '{resource}' overlaps a lock held by {} ({}).",
                    holder
                        .get("agent")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown"),
                    holder
                        .get("resource")
                        .and_then(Value::as_str)
                        .unwrap_or("-")
                );
                return Ok(());
            }
            acquired = true;
            let unexpected: Vec<PathBuf> = reset_lock_files(ws)
                .into_iter()
                .filter(|path| *path != lock_path(&ws.locks_dir(), resource))
                .collect();
            if !unexpected.is_empty() {
                eprintln!("A lock appeared during confirmation; reset cancelled.");
                return Ok(());
            }
            targets = reset_targets(ws);
            if let Some(error) = reset_target_error(ws, &targets) {
                eprintln!("{error}");
                return Ok(());
            }
            let mut removed = 0;
            for target in &targets {
                if let Err(error) = fs::symlink_metadata(target) {
                    eprintln!("WARN  {error}");
                    continue;
                }
                remove_reset_target(target)?;
                removed += 1;
            }
            let _ = crate::tasks::board::write_board(ws, &store::load_tasks(ws));
            println!("Hard reset complete; removed {removed} file(s).");
            code = 0;
            Ok(())
        };
        run_reset()
    };
    if acquired {
        let _ = release_lock(ws, resource, Some(agent), false, true);
    }
    if let Err(error) = outcome {
        eprintln!(
            "Hard reset stopped after a partial cleanup: {error}. Run `ai reset --hard` again."
        );
        return Ok(1);
    }
    Ok(code)
}
