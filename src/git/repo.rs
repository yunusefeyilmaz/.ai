//! Git state, config and the ancestry checks the ledger relies on.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value};
use sha1::{Digest, Sha1};

use crate::config::settings::load;
use crate::core::fsio::normalize_id;
use crate::core::workspace::Workspace;
use crate::tasks::store::Task;

pub struct GitOutput {
    pub code: i32,
    pub stdout: String,
    pub stderr: String,
}

pub fn run_git(cwd: &Path, args: &[&str]) -> GitOutput {
    match Command::new("git").args(args).current_dir(cwd).output() {
        Ok(output) => GitOutput {
            code: output.status.code().unwrap_or(1),
            stdout: String::from_utf8_lossy(&output.stdout).trim().to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_string(),
        },
        Err(_) => GitOutput {
            code: 127,
            stdout: String::new(),
            stderr: "git is not available".to_string(),
        },
    }
}

/// Raw stdout for parsers: `--porcelain -z` entries start with a status column
/// that may be a space, so trimming would corrupt the first entry.
pub fn run_git_raw(cwd: &Path, args: &[&str]) -> String {
    match Command::new("git").args(args).current_dir(cwd).output() {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).to_string()
        }
        _ => String::new(),
    }
}

/// Parse `git status --porcelain -z` into (status, path) records.
pub fn parse_porcelain_z(output: &str) -> Vec<(String, String)> {
    let tokens: Vec<&str> = output.split('\0').collect();
    let mut entries = Vec::new();
    let mut index = 0;
    while index < tokens.len() {
        let entry = tokens[index];
        index += 1;
        if entry.len() < 3 {
            continue;
        }
        let status = entry[..2].to_string();
        let path = entry[3..].to_string();
        if path.is_empty() {
            continue;
        }
        if status.contains('R') || status.contains('C') {
            index += 1; // the old path belongs to this record
        }
        entries.push((status, path));
    }
    entries
}

pub fn state(ws: &Workspace) -> Value {
    state_at(&ws.project)
}

pub fn state_at(cwd: &Path) -> Value {
    let top = run_git(cwd, &["rev-parse", "--show-toplevel"]);
    if top.code != 0 || top.stdout.is_empty() {
        return json!({
            "repo": false,
            "branch": null,
            "head": null,
            "dirty": [],
            "staged": [],
            "error": if top.stderr.is_empty() { Value::Null } else { json!(top.stderr) },
        });
    }
    let mut branch = run_git(cwd, &["symbolic-ref", "--short", "HEAD"]);
    if branch.code != 0 || branch.stdout.is_empty() {
        branch = run_git(cwd, &["rev-parse", "--abbrev-ref", "HEAD"]);
    }
    let branch = if branch.stdout.is_empty() || branch.stdout == "HEAD" {
        "detached".to_string()
    } else {
        branch.stdout
    };
    let head = run_git(cwd, &["rev-parse", "--verify", "--quiet", "HEAD^{commit}"]);
    let head = if head.code == 0
        && head.stdout.len() >= 40
        && head.stdout.chars().all(|ch| ch.is_ascii_hexdigit())
    {
        Some(head.stdout)
    } else {
        None
    };
    let mut dirty = Vec::new();
    let mut staged = Vec::new();
    for (status, path) in parse_porcelain_z(&run_git_raw(cwd, &["status", "--porcelain", "-z"])) {
        dirty.push(path.clone());
        let first = status.chars().next().unwrap_or(' ');
        if first != ' ' && first != '?' {
            staged.push(path);
        }
    }
    json!({
        "repo": true,
        "branch": branch,
        "head": head,
        "dirty": dirty,
        "staged": staged,
        "error": null,
    })
}

#[derive(Clone, Debug)]
pub struct GitConfig {
    pub integration: String,
    pub production: String,
    pub branch_types: Vec<String>,
    pub template: String,
    pub merge: String,
    pub isolation: String,
    pub delete_after_merge: bool,
    pub enabled: bool,
}

pub fn config(ws: &Workspace) -> GitConfig {
    let config = load(ws).unwrap_or_else(|_| crate::config::settings::default_config(ws));
    let git = config.get("git").cloned().unwrap_or(json!({}));
    GitConfig {
        integration: git
            .get("integrationBranch")
            .and_then(Value::as_str)
            .unwrap_or("develop")
            .to_string(),
        production: git
            .get("productionBranch")
            .and_then(Value::as_str)
            .unwrap_or("master")
            .to_string(),
        branch_types: git
            .get("branchTypes")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(ToString::to_string)
                    .collect()
            })
            .unwrap_or_else(|| {
                ["feature", "fix", "chore", "docs", "refactor", "hotfix"]
                    .iter()
                    .map(|s| s.to_string())
                    .collect()
            }),
        template: git
            .get("commitTemplate")
            .and_then(Value::as_str)
            .unwrap_or("templates/git/commit-template.txt")
            .to_string(),
        merge: git
            .get("merge")
            .and_then(Value::as_str)
            .unwrap_or("no-ff")
            .to_string(),
        isolation: if git.get("isolation").and_then(Value::as_str) == Some("worktree") {
            "worktree".to_string()
        } else {
            "branch".to_string()
        },
        delete_after_merge: git
            .get("deleteAfterMerge")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        enabled: crate::config::settings::git_enabled(ws),
    }
}

pub fn branch_exists(cwd: &Path, name: &str) -> bool {
    let revision = format!("refs/heads/{name}^{{commit}}");
    run_git(cwd, &["rev-parse", "--verify", "--quiet", &revision]).code == 0
}

pub fn branch_merged(cwd: &Path, branch: &str, target: &str) -> bool {
    if !branch_exists(cwd, branch) || !branch_exists(cwd, target) {
        return false;
    }
    run_git(cwd, &["merge-base", "--is-ancestor", branch, target]).code == 0
}

pub fn commits_ahead(cwd: &Path, base: &str) -> Option<i64> {
    let output = run_git(cwd, &["rev-list", "--count", &format!("{base}..HEAD")]);
    if output.code == 0 {
        output.stdout.parse().ok()
    } else {
        None
    }
}

/// Absolute path of a task's worktree when it has one and it exists.
pub fn task_root(ws: &Workspace, task: &Task) -> Option<PathBuf> {
    let rel = task.get_str("worktree")?;
    let absolute = ws.root.join(rel);
    if absolute.is_dir() {
        Some(absolute)
    } else {
        None
    }
}

/// The checkout a task's product files, checks and evidence belong to.
pub fn task_checkout(ws: &Workspace, task: &Task) -> PathBuf {
    task_root(ws, task).unwrap_or_else(|| ws.project.clone())
}

pub fn is_workspace_ledger_path(ws: &Workspace, path: &str) -> bool {
    let absolute = if Path::new(path).is_absolute() {
        PathBuf::from(path)
    } else {
        ws.project.join(path)
    };
    // A moved file no longer exists, so canonicalising the file itself fails.
    // Canonicalise its parent instead: that keeps the comparison consistent on
    // Windows, where `canonicalize` returns a `\\?\`-prefixed path.
    let absolute = match std::fs::canonicalize(&absolute) {
        Ok(path) => path,
        Err(_) => match (absolute.parent(), absolute.file_name()) {
            (Some(parent), Some(name)) => match std::fs::canonicalize(parent) {
                Ok(parent) => parent.join(name),
                Err(_) => absolute.clone(),
            },
            _ => absolute.clone(),
        },
    };
    for folder in [
        ws.tasks_dir(),
        ws.specs_dir(),
        ws.config_dir(),
        ws.decisions_dir(),
    ] {
        let root = std::fs::canonicalize(&folder).unwrap_or(folder);
        if absolute.starts_with(&root) {
            return true;
        }
    }
    false
}

pub fn task_branch_name(task: &Task, branch_type: &str) -> String {
    let full = crate::core::fsio::slugify(&task.title());
    let full = full.trim_matches('-');
    let slug = if full.len() > 40 {
        let cut = &full[..40];
        // Cut on a word boundary when there is one near the end; append a short
        // digest of the full title so two tasks with the same prefix stay
        // distinguishable to humans as well as to Git.
        let base = match cut.rfind('-') {
            Some(index) if index >= 24 => &cut[..index],
            _ => cut,
        };
        let mut hasher = Sha1::new();
        hasher.update(full.as_bytes());
        let digest = format!("{:x}", hasher.finalize());
        format!("{}-{}", base.trim_matches('-'), &digest[..6])
    } else {
        full.to_string()
    };
    format!(
        "{branch_type}/{}-{}",
        normalize_id(&task.id()).unwrap_or_else(|_| "0000".to_string()),
        if slug.is_empty() {
            "task"
        } else {
            slug.as_str()
        }
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn task(id: &str, title: &str) -> Task {
        let mut meta = serde_json::Map::new();
        meta.insert("id".into(), json!(id));
        meta.insert("title".into(), json!(title));
        Task {
            meta,
            body: String::new(),
            path: PathBuf::from("tasks/active/0001-x.md"),
            folder: "active".into(),
        }
    }

    #[test]
    fn short_titles_keep_a_readable_branch() {
        assert_eq!(
            task_branch_name(&task("0007", "CSV export"), "feature"),
            "feature/0007-csv-export"
        );
    }

    #[test]
    fn long_titles_cut_on_a_word_boundary_and_stay_unique() {
        let first = task_branch_name(
            &task(
                "0001",
                "Monorepo foundation for backend and frontend scaffolding",
            ),
            "feature",
        );
        let second = task_branch_name(
            &task(
                "0002",
                "Monorepo foundation for backend and frontend services",
            ),
            "feature",
        );
        assert!(
            first.starts_with("feature/0001-monorepo-foundation"),
            "{first}"
        );
        assert!(!first.ends_with('-'), "{first}");
        assert_ne!(first, second);
        // No trailing partial word: the digest follows a dash-separated base.
        let rest = first.split("feature/0001-").nth(1).unwrap_or("");
        let (base, digest) = rest.rsplit_once('-').expect("digest suffix");
        assert!(!base.ends_with('-'), "{base}");
        assert_eq!(digest.len(), 6);
        assert!(digest.chars().all(|ch| ch.is_ascii_hexdigit()));
    }
}
