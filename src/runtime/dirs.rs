//! Runtime directory shapes: create what is regenerable, never data.

use std::fs;
use std::path::Path;

use crate::core::error::Result;
use crate::core::fsio::write_text_atomic;
use crate::core::workspace::Workspace;

pub fn workspace_dirs(ws: &Workspace) -> Vec<std::path::PathBuf> {
    vec![
        ws.config_dir(),
        ws.decisions_dir(),
        ws.root.join("agents"),
        ws.active_dir(),
        ws.done_dir(),
        ws.specs_active_dir(),
        ws.specs_done_dir(),
        ws.locks_dir(),
        ws.state_dir(),
        ws.checkpoint_dir(),
        ws.checkpoint_archive(),
        ws.handoff_dir(),
        ws.artifacts_dir(),
        ws.logs_dir(),
    ]
}

pub fn ensure_dirs(ws: &Workspace) -> Result<()> {
    for path in workspace_dirs(ws) {
        fs::create_dir_all(path)?;
    }
    Ok(())
}

/// Create runtime keep files and return the ones that were missing.
pub fn ensure_placeholders(ws: &Workspace) -> Result<Vec<String>> {
    let mut created = Vec::new();
    let root_ignore = ws.runtime_dir().join(".gitignore");
    if !root_ignore.exists() {
        write_text_atomic(
            &root_ignore,
            "# Keep the shape, ignore transient state.\n*\n!.gitignore\n!**/\n!**/.gitkeep\n",
        )?;
        created.push("runtime/.gitignore".to_string());
    }
    for folder in [
        ws.locks_dir(),
        ws.state_dir(),
        ws.checkpoint_dir(),
        ws.handoff_dir(),
        ws.artifacts_dir(),
        ws.logs_dir(),
    ] {
        let keep = folder.join(".gitkeep");
        if !keep.exists() {
            write_text_atomic(&keep, "")?;
            created.push(relative(ws, &keep));
        }
    }
    Ok(created)
}

fn relative(ws: &Workspace, path: &Path) -> String {
    path.strip_prefix(&ws.root)
        .map(|rest| rest.to_string_lossy().replace('\\', "/"))
        .unwrap_or_else(|_| path.to_string_lossy().replace('\\', "/"))
}
