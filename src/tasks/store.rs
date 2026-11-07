//! Reading, writing, finding and ordering the Markdown task ledger.

use std::fs;
use std::path::{Path, PathBuf};

use regex::Regex;
use serde_json::{json, Map, Value};

use crate::core::error::Result;
use crate::core::fsio::{normalize_id, read_text, write_text_atomic};
use crate::core::workspace::Workspace;
use crate::tasks::frontmatter::{parse_document, render, validate_task_meta};

pub const PRIORITY_ORDER: &[(&str, u8)] = &[("high", 0), ("medium", 1), ("low", 2)];

pub fn priority_rank(priority: Option<&str>) -> u8 {
    PRIORITY_ORDER
        .iter()
        .find(|(name, _)| Some(*name) == priority)
        .map(|(_, rank)| *rank)
        .unwrap_or(1)
}

#[derive(Clone, Debug, Default)]
pub struct Task {
    pub meta: Map<String, Value>,
    pub body: String,
    pub path: PathBuf,
    pub folder: String,
}

impl Task {
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.meta.get(key)
    }

    pub fn get_str(&self, key: &str) -> Option<String> {
        match self.meta.get(key) {
            Some(Value::String(text)) => Some(text.clone()),
            Some(Value::Null) | None => None,
            Some(other) => Some(other.to_string()),
        }
    }

    pub fn id(&self) -> String {
        self.get_str("id").unwrap_or_default()
    }

    pub fn title(&self) -> String {
        self.get_str("title").unwrap_or_default()
    }

    pub fn status(&self) -> String {
        self.get_str("status").unwrap_or_default()
    }

    pub fn owner(&self) -> Option<String> {
        self.get_str("owner")
    }

    pub fn priority(&self) -> Option<String> {
        self.get_str("priority")
    }

    pub fn is_active(&self) -> bool {
        self.folder == "active"
    }

    /// Metadata plus the internal fields the JSON contract exposes.
    pub fn to_json(&self) -> Value {
        let mut map = self.meta.clone();
        map.insert("_path".into(), json!(self.path.to_string_lossy()));
        map.insert("_folder".into(), json!(self.folder));
        map.insert("_body".into(), json!(self.body));
        Value::Object(map)
    }

    pub fn slim_json(&self) -> Value {
        const KEEP: &[&str] = &[
            "id",
            "title",
            "status",
            "owner",
            "priority",
            "spec",
            "depends_on",
            "branch",
            "worktree",
            "submitted_by",
            "reviewed_by",
            "changes_requested_by",
            "updated",
        ];
        let mut map = Map::new();
        for key in KEEP {
            if let Some(value) = self.meta.get(*key) {
                if !value.is_null() {
                    map.insert((*key).to_string(), value.clone());
                }
            }
        }
        Value::Object(map)
    }
}

pub fn parse_task(path: &Path) -> Result<(Map<String, Value>, String, Vec<String>)> {
    let text = read_text(path)?;
    let document = parse_document(&text);
    Ok((document.meta, document.body, document.problems))
}

pub fn validate_meta(meta: &Map<String, Value>) -> Vec<String> {
    validate_task_meta(meta)
}

pub fn write_task(path: &Path, meta: &Map<String, Value>, body: &str) -> Result<()> {
    write_text_atomic(path, &render(meta, body))
}

pub fn task_paths(ws: &Workspace, folder: &str) -> Vec<PathBuf> {
    let directory = ws.tasks_dir().join(folder);
    let entries = match fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    let mut paths: Vec<PathBuf> = entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| {
            path.extension().and_then(|ext| ext.to_str()) == Some("md")
                && !path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .map(|name| name.starts_with("TEMPLATE"))
                    .unwrap_or(false)
        })
        .collect();
    paths.sort();
    paths
}

pub fn find_task(ws: &Workspace, task_id: &str) -> Option<PathBuf> {
    let wanted = normalize_id(task_id).ok()?;
    for folder in ["active", "done"] {
        for path in task_paths(ws, folder) {
            let name = path.file_name()?.to_str()?;
            if name.starts_with(&(wanted.clone() + "-"))
                || name.starts_with(&(wanted.clone() + "."))
            {
                return Some(path);
            }
        }
    }
    None
}

pub fn load_tasks(ws: &Workspace) -> Vec<Task> {
    let mut items = Vec::new();
    for folder in ["active", "done"] {
        for path in task_paths(ws, folder) {
            let (meta, body, problems) = match parse_task(&path) {
                Ok(parsed) => parsed,
                Err(error) => {
                    eprintln!(
                        "WARN  skipping unreadable task file {}: {error}",
                        path.display()
                    );
                    continue;
                }
            };
            let mut errors = validate_meta(&meta);
            errors.extend(problems);
            if !errors.is_empty() {
                eprintln!(
                    "WARN  skipping invalid task file {}: {}",
                    path.display(),
                    errors.join("; ")
                );
                continue;
            }
            items.push(Task {
                meta,
                body,
                path,
                folder: folder.to_string(),
            });
        }
    }
    items
}

pub fn task_owner_error(task: &Task, agent: &str, force: bool) -> Option<String> {
    match task.owner() {
        Some(owner) if owner != agent && !force => {
            Some(format!("Task {} is owned by {owner}.", task.id()))
        }
        _ => None,
    }
}

pub fn board_dependencies(meta: &Map<String, Value>) -> Vec<String> {
    let raw = match meta.get("depends_on") {
        Some(Value::Null) | None => return Vec::new(),
        Some(value) => value,
    };
    let parts: Vec<String> = match raw {
        Value::Array(items) => items
            .iter()
            .filter_map(Value::as_str)
            .map(ToString::to_string)
            .collect(),
        Value::String(text) => {
            if text.trim().is_empty() || text.trim() == "None" {
                return Vec::new();
            }
            Regex::new(r"[,\s]+")
                .expect("static regex")
                .split(text)
                .map(ToString::to_string)
                .collect()
        }
        other => vec![other.to_string()],
    };
    parts
        .into_iter()
        .filter(|part| !part.is_empty() && part.trim() != "null")
        .filter_map(|part| normalize_id(&part).ok())
        .collect()
}

pub fn dependency_blockers(ws: &Workspace, meta: &Map<String, Value>) -> Vec<String> {
    let mut blockers = Vec::new();
    let depends = match meta.get("depends_on") {
        Some(Value::Null) | None => return blockers,
        Some(value) => value,
    };
    let text = match depends {
        Value::String(text) => text.clone(),
        Value::Array(items) => items
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>()
            .join(","),
        other => other.to_string(),
    };
    for dependency in Regex::new(r"[,\s]+").expect("static regex").split(&text) {
        let dependency = dependency.trim();
        if dependency.is_empty() {
            continue;
        }
        match find_task(ws, dependency) {
            None => blockers.push(format!("unknown task {dependency}")),
            Some(path) => {
                let (meta, _, _) = parse_task(&path).unwrap_or_default();
                let status = meta
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                if status != "done" {
                    blockers.push(format!("{dependency} is {status}"));
                }
            }
        }
    }
    blockers
}

pub fn resolve_task_id(ws: &Workspace, task_id: Option<&str>) -> Option<String> {
    if let Some(task_id) = task_id.filter(|value| !value.trim().is_empty()) {
        let path = find_task(ws, task_id)?;
        let (meta, _, _) = parse_task(&path).ok()?;
        return meta
            .get("id")
            .and_then(Value::as_str)
            .map(ToString::to_string);
    }
    let mut active: Vec<Task> = load_tasks(ws).into_iter().filter(Task::is_active).collect();
    active.sort_by(|a, b| {
        b.get_str("updated")
            .unwrap_or_default()
            .cmp(&a.get_str("updated").unwrap_or_default())
    });
    active.first().map(Task::id)
}

pub fn board_task_rows(tasks: &[Task]) -> Vec<(Task, String)> {
    let active: Vec<&Task> = tasks.iter().filter(|task| task.is_active()).collect();
    let done_ids: std::collections::HashSet<String> = tasks
        .iter()
        .filter(|task| task.folder == "done")
        .map(Task::id)
        .collect();
    let by_id: std::collections::HashMap<String, &Task> =
        active.iter().map(|task| (task.id(), *task)).collect();
    let mut ordered: Vec<Task> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();

    fn visit(
        task: &Task,
        stack: &mut std::collections::HashSet<String>,
        seen: &mut std::collections::HashSet<String>,
        by_id: &std::collections::HashMap<String, &Task>,
        ordered: &mut Vec<Task>,
    ) {
        let task_id = task.id();
        if seen.contains(&task_id) || stack.contains(&task_id) {
            return;
        }
        stack.insert(task_id.clone());
        for dependency in board_dependencies(&task.meta) {
            if let Some(next) = by_id.get(&dependency) {
                visit(next, stack, seen, by_id, ordered);
            }
        }
        stack.remove(&task_id);
        if seen.insert(task_id) {
            ordered.push(task.clone());
        }
    }

    let mut ranked: Vec<&Task> = active.clone();
    ranked.sort_by(|a, b| {
        let rank_a = priority_rank(a.priority().as_deref());
        let rank_b = priority_rank(b.priority().as_deref());
        rank_a.cmp(&rank_b).then_with(|| a.id().cmp(&b.id()))
    });
    for task in ranked {
        let mut stack = std::collections::HashSet::new();
        visit(task, &mut stack, &mut seen, &by_id, &mut ordered);
    }

    ordered
        .into_iter()
        .map(|task| {
            let waiting: Vec<String> = board_dependencies(&task.meta)
                .into_iter()
                .filter(|dependency| !done_ids.contains(dependency))
                .collect();
            let reason = if task.status() == "blocked" {
                if waiting.is_empty() {
                    "blocked".to_string()
                } else {
                    format!("blocked {}", waiting.join(", "))
                }
            } else if waiting.is_empty() {
                "-".to_string()
            } else {
                waiting.join(", ")
            };
            (task, reason)
        })
        .collect()
}

pub fn text_table(columns: &[(&str, usize)], rows: &[Vec<String>]) -> Vec<String> {
    fn cell(value: &str, width: usize) -> String {
        let text = if value.is_empty() { "-" } else { value };
        if width == 0 {
            text.to_string()
        } else {
            let truncated: String = text.chars().take(width).collect();
            format!("{truncated:<width$}")
        }
    }
    let mut lines = Vec::new();
    let header = columns
        .iter()
        .map(|(name, width)| cell(name, *width))
        .collect::<Vec<_>>()
        .join(" ");
    lines.push(header.trim_end().to_string());
    for row in rows {
        let line = row
            .iter()
            .zip(columns.iter())
            .map(|(value, (_, width))| cell(value, *width))
            .collect::<Vec<_>>()
            .join(" ");
        lines.push(line.trim_end().to_string());
    }
    lines
}
