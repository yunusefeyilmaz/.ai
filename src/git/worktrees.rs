//! One isolated Git checkout per task, managed by the workspace.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use crate::config::settings::load;
use crate::core::fsio::write_text_atomic;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo as git;
use crate::tasks::store::Task;

pub const BRIEFING_FILES: &[&str] = &["AGENTS.md", "CLAUDE.md"];

pub fn worktree_name(branch: &str) -> String {
    branch.replace(['/', '\\'], "-")
}

pub fn relative(ws: &Workspace, path: &Path) -> String {
    relative_to(&ws.root, path)
}

/// Absolute command a worker inside a worktree uses to reach the main workspace.
pub fn cli_command(_ws: &Workspace) -> String {
    let exe = std::env::current_exe()
        .map(|path| path.to_string_lossy().to_string())
        .unwrap_or_else(|_| "ai".to_string());
    format!("\"{exe}\"")
}

pub fn ensure_excluded(ws: &Workspace, root: &Path) {
    let output = git::run_git(root, &["rev-parse", "--git-path", "info/exclude"]);
    if output.code != 0 || output.stdout.is_empty() {
        return;
    }
    let exclude = if Path::new(&output.stdout).is_absolute() {
        PathBuf::from(&output.stdout)
    } else {
        root.join(&output.stdout)
    };
    let mut wanted: Vec<String> = Vec::new();
    let prefix = relative_to(&ws.project, &ws.worktrees_dir());
    if !prefix.starts_with("..") {
        wanted.push(format!("/{prefix}/"));
    }
    for name in BRIEFING_FILES {
        wanted.push(format!("/{name}"));
    }
    let existing = fs::read_to_string(&exclude).unwrap_or_default();
    let missing: Vec<&String> = wanted
        .iter()
        .filter(|line| !existing.lines().any(|value| value == line.as_str()))
        .collect();
    if missing.is_empty() {
        return;
    }
    if let Some(parent) = exclude.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let mut text = existing.clone();
    if !text.is_empty() && !text.ends_with('\n') {
        text.push('\n');
    }
    text.push_str("# ai workspace: task worktrees are local\n");
    for line in missing {
        text.push_str(line);
        text.push('\n');
    }
    let _ = write_text_atomic(&exclude, &text);
}

fn briefing(ws: &Workspace, meta: &Map<String, Value>, branch: &str) -> String {
    let cli = cli_command(ws);
    let id = meta
        .get("task")
        .or_else(|| meta.get("id"))
        .and_then(Value::as_str)
        .unwrap_or("-");
    let title = meta.get("title").and_then(Value::as_str).unwrap_or("");
    format!(
        "# Task worktree (managed by the .ai workspace)\n\nYou are inside an isolated checkout for task {id} ({title}),\nbranch `{branch}`. Edit product files **only here**; never touch the main checkout.\n\nThe coordination state (tasks, locks, runtime, config) lives in the main\nworkspace. This directory is a Git worktree, so the CLI resolves it back to that\nshared workspace even though a copy of the ledger may exist here. Run the shared\nCLI by absolute path from this directory:\n\n    {cli} now --agent <name>\n    {cli} task show {id}\n    {cli} git commit --task {id} --agent <name> --type feat --message \"<subject>\"\n    {cli} task review {id} --agent <name>\n\nRead the workspace rules in `{}`.\n",
        ws.root.join("AGENTS.md").to_string_lossy().replace('\\', "/")
    )
}

/// Create (or reuse) the task's worktree. Returns `(ok, path, message)`.
pub fn create(
    ws: &Workspace,
    meta: &Map<String, Value>,
    branch: &str,
    base: &str,
) -> (bool, PathBuf, String) {
    let path = ws.worktrees_dir().join(worktree_name(branch));
    if path.is_dir() {
        let output = git::run_git(&path, &["rev-parse", "--abbrev-ref", "HEAD"]);
        if output.code == 0 && output.stdout == branch {
            return (true, path, "reused".to_string());
        }
        let found = if output.stdout.is_empty() {
            "not a git worktree".to_string()
        } else {
            output.stdout
        };
        let message = format!(
            "{} already exists but is on '{found}', not '{branch}'. Remove it (or pick a different branch) before claiming this task.",
            path.display()
        );
        return (false, path, message);
    }
    let _ = fs::create_dir_all(ws.worktrees_dir());
    ensure_excluded(ws, &ws.project);
    let path_text = path.to_string_lossy().to_string();
    let output = if git::branch_exists(&ws.project, branch) {
        git::run_git(&ws.project, &["worktree", "add", &path_text, branch])
    } else {
        git::run_git(
            &ws.project,
            &["worktree", "add", "-b", branch, &path_text, base],
        )
    };
    if output.code != 0 {
        let message = if output.stderr.is_empty() {
            "git worktree add failed".to_string()
        } else {
            output.stderr
        };
        return (false, path, message);
    }
    for name in BRIEFING_FILES {
        let target = path.join(name);
        if !target.exists() {
            let _ = write_text_atomic(&target, &briefing(ws, meta, branch));
        }
    }
    (true, path, "created".to_string())
}

fn is_registered(ws: &Workspace, path: &Path) -> bool {
    let wanted = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    git::run_git(&ws.project, &["worktree", "list", "--porcelain"])
        .stdout
        .lines()
        .filter_map(|line| line.strip_prefix("worktree "))
        .any(|registered| {
            let registered = PathBuf::from(registered);
            fs::canonicalize(&registered).unwrap_or(registered) == wanted
        })
}

fn is_dirty(path: &Path) -> bool {
    git::run_git(path, &["status", "--porcelain"])
        .stdout
        .lines()
        .filter(|line| !line.trim().is_empty())
        .any(|line| {
            let changed = line.get(3..).unwrap_or("").trim();
            !BRIEFING_FILES.contains(&changed) && !changed.starts_with(".ai/")
        })
}

pub fn remove(ws: &Workspace, path: &Path, force: bool) -> (bool, String) {
    // A directory that git no longer knows about (for example after a failed
    // removal or a manual delete) is still ours to clean up, but never with
    // uncommitted work unless the caller asked to discard it.
    if !is_registered(ws, path) {
        if !path.is_dir() {
            let _ = git::run_git(&ws.project, &["worktree", "prune"]);
            return (true, String::new());
        }
        if !force && is_dirty(path) {
            return (
                false,
                "it is not a registered git worktree and has uncommitted changes".to_string(),
            );
        }
        if fs::remove_dir_all(path).is_err() {
            let _ = git::run_git(&ws.project, &["worktree", "prune"]);
            return (false, "could not delete the worktree directory".to_string());
        }
        let _ = git::run_git(&ws.project, &["worktree", "prune"]);
        return (
            true,
            "removed an unregistered worktree directory".to_string(),
        );
    }
    let path_text = path.to_string_lossy().to_string();
    let mut args: Vec<&str> = vec!["worktree", "remove"];
    if force {
        args.push("--force");
    }
    args.push(&path_text);
    let output = git::run_git(&ws.project, &args);
    if output.code != 0 {
        if !path.is_dir() {
            let _ = git::run_git(&ws.project, &["worktree", "prune"]);
            return (true, String::new());
        }
        if !force {
            return (
                false,
                if output.stderr.is_empty() {
                    "git worktree remove failed".to_string()
                } else {
                    output.stderr
                },
            );
        }
        // Windows cannot delete a directory that is a process's current
        // directory. Leave the task worktree first so the cleanup can finish.
        if std::env::current_dir()
            .map(|cwd| cwd.starts_with(path))
            .unwrap_or(false)
        {
            let _ = std::env::set_current_dir(&ws.project);
        }
        if fs::remove_dir_all(path).is_err() {
            let _ = git::run_git(&ws.project, &["worktree", "prune"]);
            return (
                false,
                "could not delete the worktree directory (leave it first, then run `ai worktree prune`)".to_string(),
            );
        }
        let _ = git::run_git(&ws.project, &["worktree", "prune"]);
        return (
            true,
            "removed from disk (git worktree remove failed)".to_string(),
        );
    }
    let _ = git::run_git(&ws.project, &["worktree", "prune"]);
    (true, String::new())
}

#[derive(Clone, Debug)]
pub struct Row {
    pub path: String,
    pub name: String,
    pub branch: Option<String>,
    pub task: Option<String>,
    pub status: Option<String>,
    pub owner: Option<String>,
    pub dirty: usize,
    pub orphan: bool,
}

impl Row {
    pub fn to_json(&self) -> Value {
        json!({
            "path": self.path,
            "name": self.name,
            "branch": self.branch,
            "task": self.task,
            "status": self.status,
            "owner": self.owner,
            "dirty": self.dirty,
            "orphan": self.orphan,
        })
    }
}

pub fn listing(ws: &Workspace, tasks: &[Task]) -> Vec<Row> {
    let mut rows = Vec::new();
    let entries = match fs::read_dir(ws.worktrees_dir()) {
        Ok(entries) => entries,
        Err(_) => return rows,
    };
    let by_path: std::collections::HashMap<String, &Task> = tasks
        .iter()
        .filter_map(|task| task.get_str("worktree").map(|worktree| (worktree, task)))
        .collect();
    let mut names: Vec<String> = entries
        .flatten()
        .map(|entry| entry.file_name().to_string_lossy().to_string())
        .collect();
    names.sort();
    for name in names {
        let full = ws.worktrees_dir().join(&name);
        if !full.is_dir() {
            continue;
        }
        let rel = relative(ws, &full);
        let task = by_path.get(&rel).copied();
        let branch = git::run_git(&full, &["rev-parse", "--abbrev-ref", "HEAD"]).stdout;
        // Briefing files and ledger copies are workspace-owned, not unfinished
        // product work. Counting them made a clean, merged worktree look dirty.
        let dirty = git::run_git(&full, &["status", "--porcelain"])
            .stdout
            .lines()
            .filter(|line| !line.trim().is_empty())
            .filter(|line| {
                let changed = line.get(3..).unwrap_or("").trim();
                !BRIEFING_FILES.contains(&changed) && !changed.starts_with(".ai/")
            })
            .count();
        rows.push(Row {
            path: full.to_string_lossy().to_string(),
            name,
            branch: if branch.is_empty() {
                None
            } else {
                Some(branch)
            },
            task: task.map(Task::id),
            status: task.map(|task| {
                if task.is_active() {
                    task.status()
                } else {
                    "done".to_string()
                }
            }),
            owner: task.and_then(Task::owner),
            dirty,
            // A merged task no longer needs its checkout even while it is still
            // in review waiting for `ai task done`.
            orphan: task
                .map(|task| !task.is_active() || task.get_str("merged_at").is_some())
                .unwrap_or(true),
        });
    }
    rows
}

pub fn configured_isolation(ws: &Workspace) -> String {
    let config = load(ws).unwrap_or_else(|_| crate::config::settings::default_config(ws));
    if config
        .get("git")
        .and_then(|git| git.get("isolation"))
        .and_then(Value::as_str)
        == Some("worktree")
    {
        "worktree".to_string()
    } else {
        "branch".to_string()
    }
}
