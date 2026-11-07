//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use crate::core::error::Result;
use crate::core::workspace::VERSION;

pub fn run() -> Result<i32> {
    println!("ai workspace {VERSION}");
    Ok(0)
}
