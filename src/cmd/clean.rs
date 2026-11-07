//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use std::fs;

use serde_json::Value;

use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::runtime::leases::{list_locks, lock_is_stale};
use crate::runtime::mutex::workspace_state_guard;

use crate::CleanArgs;
pub fn run(ws: &Workspace, args: &CleanArgs) -> Result<i32> {
    if !(args.stale_locks || args.logs) {
        eprintln!("Nothing to clean: pass --stale-locks and/or --logs.");
        return Ok(1);
    }
    let mut removed = 0;
    let _guard = workspace_state_guard(ws)?;
    if args.stale_locks {
        let (_, stale_after) = config::lock_settings(ws);
        for lock in list_locks(ws, true) {
            if lock_is_stale(Some(&lock), stale_after) {
                if let Some(file) = lock.get("_file").and_then(Value::as_str) {
                    if fs::remove_file(ws.locks_dir().join(file)).is_ok() {
                        removed += 1;
                        println!(
                            "Removed stale lock: {}",
                            lock.get("resource").and_then(Value::as_str).unwrap_or("-")
                        );
                    }
                }
            }
        }
    }
    if args.logs {
        if let Ok(entries) = fs::read_dir(ws.logs_dir()) {
            for entry in entries.flatten() {
                let path = entry.path();
                let name = entry.file_name().to_string_lossy().to_string();
                if path.is_file() && name != ".gitkeep" && fs::remove_file(&path).is_ok() {
                    removed += 1;
                }
            }
        }
    }
    println!("Cleaned {removed} item(s).");
    Ok(0)
}
