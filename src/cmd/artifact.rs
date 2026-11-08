//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::fsio::{read_json, safe_name, write_json_atomic};
use crate::core::time::{compact_stamp, iso, now};
use crate::core::workspace::{relative_to, Workspace};
use crate::runtime::dirs;
use crate::runtime::mutex::workspace_state_guard;

use crate::{ArtifactAction, ArtifactArgs};
fn manifest(ws: &Workspace) -> Result<Vec<Value>> {
    match read_json(&ws.manifest_path())? {
        Some(Value::Array(items)) => Ok(items),
        Some(_) | None => Ok(Vec::new()),
    }
}

pub fn run(ws: &Workspace, args: &ArtifactArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai artifact <put|list|clean>");
            return Ok(1);
        }
    };
    match action {
        ArtifactAction::Put {
            path,
            reason,
            agent,
        } => {
            let _guard = workspace_state_guard(ws)?;
            dirs::ensure_dirs(ws)?;
            let mut items = manifest(ws)?;
            let source = absolute(Path::new(path));
            if !source.exists() {
                eprintln!("No such path: {path}");
                return Ok(1);
            }
            let workspace_abs = absolute(&ws.root);
            let inside_workspace = source.starts_with(&workspace_abs);
            let inside_project = source.starts_with(absolute(ws.project.as_path()));
            if inside_workspace {
                eprintln!("Path is already inside the workspace.");
                return Ok(1);
            }
            if !inside_project {
                eprintln!("Refusing to move paths outside the project.");
                return Ok(1);
            }
            let stamp = compact_stamp(now());
            let base = source
                .file_name()
                .and_then(|name| name.to_str())
                .filter(|name| !name.is_empty())
                .unwrap_or("artifact");
            let target = ws
                .artifacts_dir()
                .join(format!("{stamp}-{}", safe_name(base)));
            fs::create_dir_all(ws.artifacts_dir())?;
            if let Err(error) = fs::rename(&source, &target) {
                // A rename across filesystems (or a locked file on Windows)
                // fails; fall back to copy + remove so `put` works everywhere.
                if source.is_dir() {
                    return Err(error.into());
                }
                fs::copy(&source, &target)?;
                fs::remove_file(&source)?;
            }
            items.push(json!({
                "original": relative_to(&ws.project, &source),
                "stored": relative_to(&ws.root, &target),
                "reason": reason,
                "moved_at": iso(None),
                "agent": agent,
            }));
            write_json_atomic(&ws.manifest_path(), &json!(items))?;
            println!(
                "Quarantined {} -> {}",
                relative_to(&ws.project, &source),
                relative_to(&ws.project, &target)
            );
            Ok(0)
        }
        ArtifactAction::Clean { all } => {
            if !all {
                eprintln!("Pass --all to delete quarantined artifacts.");
                return Ok(1);
            }
            let _guard = workspace_state_guard(ws)?;
            dirs::ensure_dirs(ws)?;
            let items = manifest(ws)?;
            for item in &items {
                let stored = item.get("stored").and_then(Value::as_str).unwrap_or("");
                if stored.is_empty() {
                    continue;
                }
                let target = ws
                    .root
                    .join(stored.replace('/', std::path::MAIN_SEPARATOR_STR));
                if target.is_dir() {
                    let _ = fs::remove_dir_all(&target);
                } else if target.exists() {
                    let _ = fs::remove_file(&target);
                }
            }
            write_json_atomic(&ws.manifest_path(), &json!([]))?;
            println!("Quarantined artifacts removed.");
            Ok(0)
        }
        ArtifactAction::List { json } => {
            dirs::ensure_dirs(ws)?;
            let items = manifest(ws)?;
            if *json {
                println!("{}", serde_json::to_string_pretty(&items)?);
                return Ok(0);
            }
            if items.is_empty() {
                println!("No quarantined artifacts.");
                return Ok(0);
            }
            println!("{:<22} {:<40} REASON", "MOVED AT", "ORIGINAL");
            for item in &items {
                let moved_at = item.get("moved_at").and_then(Value::as_str).unwrap_or("-");
                let original = item.get("original").and_then(Value::as_str).unwrap_or("-");
                let original: String = original.chars().take(40).collect();
                let reason = item.get("reason").and_then(Value::as_str).unwrap_or("-");
                println!("{moved_at:<22} {original:<40} {reason}");
            }
            Ok(0)
        }
    }
}

fn absolute(path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(path))
            .unwrap_or_else(|_| path.to_path_buf())
    }
}
