//! Atomic file IO, ids, slugs and path normalisation.
//!
//! Every state write goes through this module so a crash cannot leave a
//! half-written JSON/Markdown file behind: content is flushed and fsynced
//! before the atomic rename, and the rename is retried briefly on Windows
//! where antivirus and indexers hold destination files open.

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::thread::sleep;
use std::time::Duration;

use regex::Regex;
use sha1::{Digest, Sha1};

use crate::core::error::{fail, AiError, Result};

#[derive(Clone, Debug)]
pub struct CorruptState {
    pub path: PathBuf,
    pub detail: String,
}

impl std::fmt::Display for CorruptState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.path.display(), self.detail)
    }
}

/// Read UTF-8 text, converting IO errors into the shared error type.
///
/// Line endings are normalised to `\n` the way Python's text mode does, so a
/// CRLF task file parses and round-trips back to LF.
pub fn read_text(path: &Path) -> Result<String> {
    let text = fs::read_to_string(path).map_err(AiError::from)?;
    if text.contains('\r') {
        return Ok(text.replace("\r\n", "\n").replace('\r', "\n"));
    }
    Ok(text)
}

/// Read JSON. `Ok(None)` when missing; `Err` when present but unparseable.
pub fn read_json(path: &Path) -> Result<Option<serde_json::Value>> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(AiError::from(error)),
    };
    match serde_json::from_str(&text) {
        Ok(value) => Ok(Some(value)),
        Err(error) => fail(format!("{}: {error}", path.display())),
    }
}

pub fn write_text_atomic(path: &Path, text: &str) -> Result<()> {
    let directory = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(directory)?;
    let tmp = directory.join(format!(
        ".tmp-{}-{}.part",
        std::process::id(),
        unique_suffix()
    ));
    {
        let mut handle = File::create(&tmp)?;
        handle.write_all(text.as_bytes())?;
        handle.flush()?;
        handle.sync_all()?;
    }
    replace_with_retry(&tmp, path, 10)?;
    sync_directory(directory);
    Ok(())
}

pub fn write_json_atomic(path: &Path, payload: &serde_json::Value) -> Result<()> {
    let mut text = serde_json::to_string_pretty(payload)?;
    text.push('\n');
    write_text_atomic(path, &text)
}

fn unique_suffix() -> u128 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0)
}

fn replace_with_retry(source: &Path, target: &Path, attempts: usize) -> Result<()> {
    let mut last: Option<std::io::Error> = None;
    for attempt in 0..attempts {
        match fs::rename(source, target) {
            Ok(()) => return Ok(()),
            Err(error) => {
                last = Some(error);
                if attempt + 1 < attempts {
                    sleep(Duration::from_millis(50 * (attempt as u64 + 1)));
                }
            }
        }
    }
    // Windows cannot rename over an existing file in every situation; try a
    // direct copy as the last resort, then remove the temp file.
    if let Some(error) = last {
        if fs::copy(source, target).is_ok() {
            let _ = fs::remove_file(source);
            return Ok(());
        }
        return Err(AiError::from(error));
    }
    Ok(())
}

#[cfg(not(windows))]
fn sync_directory(directory: &Path) {
    if let Ok(handle) = File::open(directory) {
        let _ = handle.sync_all();
    }
}

#[cfg(windows)]
fn sync_directory(_directory: &Path) {}

pub fn create_new_json(path: &Path, payload: &serde_json::Value) -> Result<bool> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut text = serde_json::to_string_pretty(payload)?;
    text.push('\n');
    match OpenOptions::new().write(true).create_new(true).open(path) {
        Ok(mut handle) => {
            handle.write_all(text.as_bytes())?;
            handle.sync_all()?;
            Ok(true)
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(false),
        Err(error) => Err(AiError::from(error)),
    }
}

pub fn read_bytes(path: &Path) -> Result<Vec<u8>> {
    let mut file = File::open(path)?;
    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer)?;
    Ok(buffer)
}

/// `src/a/b` -> `src-a-b-<sha1 prefix>.lock`
pub fn lock_path(locks_dir: &Path, resource: &str) -> PathBuf {
    let mut hasher = Sha1::new();
    hasher.update(resource.as_bytes());
    let digest = format!("{:x}", hasher.finalize());
    locks_dir.join(format!("{}-{}.lock", safe_name(resource), &digest[..8]))
}

pub fn safe_name(name: &str) -> String {
    let re = Regex::new(r"[^A-Za-z0-9_.-]+").expect("static regex");
    let value = re.replace_all(name, "-");
    let trimmed = value.trim_matches('-');
    if trimmed.is_empty() {
        "resource".to_string()
    } else {
        trimmed.to_string()
    }
}

pub fn slugify(title: &str) -> String {
    let re = Regex::new(r"[^a-z0-9]+").expect("static regex");
    let lower = title.to_lowercase();
    let slug = re.replace_all(&lower, "-");
    let slug = slug.trim_matches('-');
    let slug = if slug.len() > 60 { &slug[..60] } else { slug };
    let slug = slug.trim_matches('-');
    if slug.is_empty() {
        "task".to_string()
    } else {
        slug.to_string()
    }
}

/// Lexically normalize a repo-relative path (`/` separated, no `.`/`..`).
pub fn normalize_rel_path(path: &str) -> String {
    let raw = path.replace('\\', "/");
    let raw = raw.trim();
    let absolute = raw.starts_with('/')
        || Regex::new(r"^[A-Za-z]:/")
            .expect("static regex")
            .is_match(raw);
    let mut parts: Vec<&str> = Vec::new();
    for part in raw.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            if parts.last().is_some_and(|last| *last != "..") {
                parts.pop();
            } else if !absolute {
                parts.push("..");
            }
            continue;
        }
        parts.push(part);
    }
    let result = if parts.is_empty() {
        ".".to_string()
    } else {
        parts.join("/")
    };
    if absolute {
        format!("/{result}")
    } else {
        result
    }
}

pub const MAX_TASK_ID_DIGITS: usize = 9;

/// Canonical task id (at least four digits); rejects anything not numeric.
pub fn normalize_id(task_id: &str) -> Result<String> {
    let re = Regex::new(r"(?i)^(?:T-|task-)?([0-9]+)$").expect("static regex");
    let text = task_id.trim();
    let caps = match re.captures(text) {
        Some(caps) => caps,
        None => return fail(format!("invalid task id: {task_id:?}")),
    };
    let digits = caps[1].trim_start_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    if digits.len() > MAX_TASK_ID_DIGITS {
        return fail(format!(
            "invalid task id: {task_id:?} — id exceeds {MAX_TASK_ID_DIGITS} digits"
        ));
    }
    let value: u64 = digits
        .parse()
        .map_err(|_| AiError::msg(format!("invalid task id: {task_id:?}")))?;
    Ok(format!("{value:04}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_are_canonical() {
        assert_eq!(normalize_id("7").unwrap(), "0007");
        assert_eq!(normalize_id("task-12").unwrap(), "0012");
        assert_eq!(normalize_id("T-0003").unwrap(), "0003");
        assert!(normalize_id("../etc/passwd").is_err());
        assert!(normalize_id("12a").is_err());
    }

    #[test]
    fn paths_do_not_escape() {
        assert_eq!(normalize_rel_path("./src//a/../b"), "src/b");
        assert_eq!(normalize_rel_path("../secret"), "../secret");
        assert_eq!(normalize_rel_path("C:\\x\\y"), "/C:/x/y");
    }

    #[test]
    fn slugs_are_safe() {
        assert_eq!(slugify("Fix: The Login!!"), "fix-the-login");
        assert_eq!(slugify("***"), "task");
    }
}
