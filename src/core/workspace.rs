//! Every filesystem location the workspace knows about.
//!
//! The Python implementation derived these paths from the location of
//! `lib/core/paths.py`. A compiled binary cannot do that, so the workspace is
//! discovered instead:
//!
//! 1. `AI_WORKSPACE` (explicit override, used by tests and wrappers),
//! 2. the nearest ancestor (or child `.ai/`) that looks like a workspace,
//! 3. the directory holding the binary, walking upward,
//! 4. the current directory.
//!
//! Layout (root is the `.ai` folder):
//!
//! ```text
//! ai[.exe]             launcher / binary
//! tasks/ specs/ runtime/ config/ templates/ docs/decisions/ skills/
//! ```
//!
//! The port keeps the exact same on-disk layout and file formats as the Python
//! implementation, so both versions can operate on the same workspace.

use std::env;
use std::path::{Path, PathBuf};

use crate::core::error::{fail, Result};

pub const VERSION: &str = "1.1.0";

#[derive(Clone, Debug)]
pub struct Workspace {
    /// The `.ai` (or `.ai-rust`) directory that owns config/, tasks/, runtime/.
    pub root: PathBuf,
    /// The host project: `root` itself, or its parent for a subfolder install.
    pub project: PathBuf,
    /// Stable lower-case short host name, used only as lease diagnostics.
    pub host: String,
}

impl Workspace {
    pub fn at(root: impl Into<PathBuf>) -> Self {
        let root = absolute(root.into());
        let project = project_root_for(&root);
        Workspace {
            root,
            project,
            host: host_name(),
        }
    }

    /// Discover the workspace from the environment / current directory.
    pub fn discover() -> Result<Self> {
        if let Ok(explicit) = env::var("AI_WORKSPACE") {
            let path = PathBuf::from(explicit);
            if !path.exists() {
                return fail(format!(
                    "AI_WORKSPACE points at {} but it does not exist",
                    path.display()
                ));
            }
            return Ok(Workspace::at(path));
        }
        let cwd = env::current_dir()?;
        if let Some(found) = find_workspace(&cwd) {
            return Ok(Workspace::at(found));
        }
        if let Ok(exe) = env::current_exe() {
            if let Some(dir) = exe.parent() {
                if let Some(found) = find_workspace(dir) {
                    return Ok(Workspace::at(found));
                }
            }
        }
        Ok(Workspace::at(cwd))
    }

    // --- data owned by each domain ---------------------------------------
    pub fn config_dir(&self) -> PathBuf {
        self.root.join("config")
    }
    pub fn config_path(&self) -> PathBuf {
        self.config_dir().join("workspace.json")
    }
    pub fn tasks_dir(&self) -> PathBuf {
        self.root.join("tasks")
    }
    pub fn active_dir(&self) -> PathBuf {
        self.tasks_dir().join("active")
    }
    pub fn done_dir(&self) -> PathBuf {
        self.tasks_dir().join("done")
    }
    pub fn board_path(&self) -> PathBuf {
        self.tasks_dir().join("BOARD.md")
    }
    pub fn specs_dir(&self) -> PathBuf {
        self.root.join("specs")
    }
    pub fn specs_active_dir(&self) -> PathBuf {
        self.specs_dir().join("active")
    }
    pub fn specs_done_dir(&self) -> PathBuf {
        self.specs_dir().join("done")
    }
    pub fn specs_template(&self) -> PathBuf {
        self.specs_dir().join("TEMPLATE.md")
    }
    pub fn decisions_dir(&self) -> PathBuf {
        self.root.join("docs").join("decisions")
    }
    pub fn worktrees_dir(&self) -> PathBuf {
        self.root.join("worktrees")
    }
    pub fn git_templates_dir(&self) -> PathBuf {
        self.root.join("templates").join("git")
    }
    pub fn skills_dir(&self) -> PathBuf {
        self.root.join("skills")
    }
    pub fn runtime_dir(&self) -> PathBuf {
        self.root.join("runtime")
    }
    pub fn locks_dir(&self) -> PathBuf {
        self.runtime_dir().join("locks")
    }
    pub fn state_dir(&self) -> PathBuf {
        self.runtime_dir().join("state")
    }
    pub fn checkpoint_dir(&self) -> PathBuf {
        self.state_dir().join("checkpoints")
    }
    pub fn checkpoint_archive(&self) -> PathBuf {
        self.checkpoint_dir().join("archive")
    }
    pub fn handoff_dir(&self) -> PathBuf {
        self.state_dir().join("handoff")
    }
    pub fn events_file(&self) -> PathBuf {
        self.state_dir().join("events.jsonl")
    }
    pub fn artifacts_dir(&self) -> PathBuf {
        self.runtime_dir().join("artifacts")
    }
    pub fn logs_dir(&self) -> PathBuf {
        self.runtime_dir().join("logs")
    }
    pub fn counter_path(&self) -> PathBuf {
        self.state_dir().join("task-counter.json")
    }
    pub fn manifest_path(&self) -> PathBuf {
        self.artifacts_dir().join("MANIFEST.json")
    }
    pub fn evidence_dir(&self) -> PathBuf {
        self.state_dir().join("evidence")
    }
    pub fn registry_mutex(&self) -> PathBuf {
        self.locks_dir().join(".registry.mutex")
    }

    /// `""` when the workspace is the project root, else `".ai/"`.
    pub fn ws_prefix(&self) -> &'static str {
        if same_path(&self.root, &self.project) {
            ""
        } else {
            ".ai/"
        }
    }

    pub fn ws_rel(&self, path: &Path) -> String {
        relative_to(&self.project, path)
    }

    pub fn workspace_shape(&self) -> &'static str {
        if self.root.file_name().and_then(|n| n.to_str()) == Some(".ai")
            && !same_path(&self.root, &self.project)
        {
            "subfolder"
        } else {
            "root"
        }
    }

    pub fn setup_questions_answered(&self) -> bool {
        crate::config::preferences::status(self)
            .map(|s| s.confirmed)
            .unwrap_or(false)
    }
}

fn host_name() -> String {
    if let Ok(value) = env::var("AI_HOST") {
        let trimmed = value.trim().to_lowercase();
        if !trimmed.is_empty() {
            return trimmed;
        }
    }
    let raw = env::var("COMPUTERNAME")
        .or_else(|_| env::var("HOSTNAME"))
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(platform_host_name)
        .unwrap_or_else(|| "localhost".to_string());
    raw.split('.')
        .next()
        .unwrap_or("localhost")
        .trim()
        .to_lowercase()
}

/// POSIX shells often do not export HOSTNAME; ask the OS instead.
#[cfg(not(windows))]
fn platform_host_name() -> Option<String> {
    for path in ["/proc/sys/kernel/hostname", "/etc/hostname"] {
        if let Ok(text) = std::fs::read_to_string(path) {
            let text = text.trim();
            if !text.is_empty() {
                return Some(text.to_string());
            }
        }
    }
    None
}

#[cfg(windows)]
fn platform_host_name() -> Option<String> {
    None
}

fn absolute(path: PathBuf) -> PathBuf {
    if path.is_absolute() {
        path
    } else {
        env::current_dir()
            .map(|cwd| cwd.join(&path))
            .unwrap_or(path)
    }
}

/// A directory is a workspace when it owns `config/workspace.json`, or when it
/// is a `.ai` folder with the contract files but its config is still missing
/// (a fresh checkout). This keeps `ai init` / `ai doctor --fix` reachable.
fn looks_like_workspace(dir: &Path) -> bool {
    if dir.join("config").join("workspace.json").is_file() {
        return true;
    }
    if dir.file_name().and_then(|n| n.to_str()) == Some(".ai")
        && dir.join("AGENTS.md").is_file()
        && dir.join("tasks").is_dir()
    {
        return true;
    }
    // The Rust port's own checkout is called `.ai-rust` during development.
    if dir.file_name().and_then(|n| n.to_str()) == Some(".ai-rust")
        && dir.join("Cargo.toml").is_file()
        && dir.join("tasks").is_dir()
    {
        return true;
    }
    false
}

fn find_workspace(start: &Path) -> Option<PathBuf> {
    let start = absolute(start.to_path_buf());
    // A project root that contains an installed `.ai/` child.
    for ancestor in start.ancestors() {
        let child = ancestor.join(".ai");
        if child.is_dir() && looks_like_workspace(&child) {
            return Some(child);
        }
        if looks_like_workspace(ancestor) {
            return Some(ancestor.to_path_buf());
        }
    }
    None
}

fn project_root_for(root: &Path) -> PathBuf {
    let is_ai = root.file_name().and_then(|n| n.to_str()) == Some(".ai");
    if !is_ai {
        return root.to_path_buf();
    }
    let parent = root
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| root.to_path_buf());
    if parent.join(".git").exists() {
        return parent;
    }
    const HOST_MARKERS: &[&str] = &[
        ".gitignore",
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "composer.json",
        "Gemfile",
        "requirements.txt",
        "src",
        "app",
        "index.html",
    ];
    if HOST_MARKERS.iter().any(|name| parent.join(name).exists()) {
        return parent;
    }
    if root.join(".git").exists() {
        return root.to_path_buf();
    }
    parent
}

pub fn same_path(a: &Path, b: &Path) -> bool {
    if a == b {
        return true;
    }
    match (std::fs::canonicalize(a), std::fs::canonicalize(b)) {
        (Ok(a), Ok(b)) => a == b,
        _ => false,
    }
}

/// Repo-relative path with `/` separators (never escapes the project).
pub fn relative_to(base: &Path, target: &Path) -> String {
    let target = absolute(target.to_path_buf());
    let base = absolute(base.to_path_buf());
    match target.strip_prefix(&base) {
        Ok(rest) => normalize_slashes(&rest.to_string_lossy()),
        Err(_) => normalize_slashes(&target.to_string_lossy()),
    }
}

pub fn normalize_slashes(text: &str) -> String {
    text.replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_root_when_workspace_is_dot_ai() {
        let base = std::env::temp_dir().join(format!("ai-ws-{}", std::process::id()));
        let ws = base.join(".ai");
        std::fs::create_dir_all(&ws).unwrap();
        std::fs::write(base.join("Cargo.toml"), "").unwrap();
        let workspace = Workspace::at(&ws);
        assert_eq!(workspace.project, base);
        assert_eq!(workspace.ws_prefix(), ".ai/");
    }
}
