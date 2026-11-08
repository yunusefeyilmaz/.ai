//! The workspace-wide state registry lock.
//!
//! An OS advisory lock on a file, not a directory whose age is guessed:
//! a crashed process releases it automatically, and a slow-but-alive holder
//! cannot be "stolen" after a fixed age. Re-entrant on the same thread because
//! a single CLI call may nest writers (state guard -> lease acquisition).

use std::cell::Cell;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::thread::sleep;
use std::time::{Duration, Instant};

use fs2::FileExt;

use crate::core::error::{fail, Result};
use crate::core::fsio::lock_path;
use crate::core::workspace::Workspace;

thread_local! {
    static HOLDING: Cell<bool> = const { Cell::new(false) };
}

pub struct RegistryGuard {
    file: Option<File>,
}

impl Drop for RegistryGuard {
    fn drop(&mut self) {
        if let Some(file) = self.file.take() {
            let _ = FileExt::unlock(&file);
            HOLDING.with(|holding| holding.set(false));
        }
    }
}

pub fn registry_mutex(ws: &Workspace) -> Result<RegistryGuard> {
    if HOLDING.with(Cell::get) {
        return Ok(RegistryGuard { file: None });
    }
    fs::create_dir_all(ws.locks_dir())?;
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(ws.registry_mutex())?;
    if file.metadata().map(|m| m.len()).unwrap_or(0) == 0 {
        let _ = file.write_all(b"ai");
        let _ = file.sync_all();
    }
    let started = Instant::now();
    let timeout = Duration::from_secs(10);
    loop {
        match file.try_lock_exclusive() {
            Ok(()) => break,
            Err(_) => {
                if started.elapsed() > timeout {
                    return fail("lock registry is busy");
                }
                sleep(Duration::from_millis(20));
            }
        }
    }
    HOLDING.with(|holding| holding.set(true));
    Ok(RegistryGuard { file: Some(file) })
}

/// Serialize state writes against `ai reset --hard`.
pub struct StateGuard {
    _registry: RegistryGuard,
}

pub fn workspace_state_guard(ws: &Workspace) -> Result<StateGuard> {
    let registry = registry_mutex(ws)?;
    let reset_lock = lock_path(&ws.locks_dir(), "project");
    if reset_lock.exists() {
        return fail("workspace reset is in progress");
    }
    Ok(StateGuard {
        _registry: registry,
    })
}
