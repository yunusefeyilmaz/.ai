//! Resumable context snapshots: a Markdown body plus a JSON sidecar.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::core::error::Result;
use crate::core::fsio::{normalize_id, read_json, write_json_atomic};
use crate::core::time::{compact_stamp, iso, now, parse_iso};
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo as git;
use crate::tasks::store;

pub fn checkpoint_path(ws: &Workspace, task_id: &str) -> PathBuf {
    let id = normalize_id(task_id).unwrap_or_else(|_| task_id.to_string());
    ws.checkpoint_dir().join(format!("{id}.md"))
}

pub fn checkpoint_sidecar(ws: &Workspace, task_id: &str) -> PathBuf {
    let id = normalize_id(task_id).unwrap_or_else(|_| task_id.to_string());
    ws.checkpoint_dir().join(format!("{id}.json"))
}

pub fn handoff_marker(ws: &Workspace, task_id: &str) -> PathBuf {
    let id = normalize_id(task_id).unwrap_or_else(|_| task_id.to_string());
    ws.handoff_dir().join(format!("{id}.json"))
}

pub fn list_handoff_markers(ws: &Workspace, ensure: bool) -> Vec<Value> {
    if ensure {
        let _ = crate::runtime::dirs::ensure_dirs(ws);
    }
    let entries = match fs::read_dir(ws.handoff_dir()) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    let mut names: Vec<String> = entries
        .flatten()
        .map(|entry| entry.file_name().to_string_lossy().to_string())
        .filter(|name| name.ends_with(".json"))
        .collect();
    names.sort();
    let mut items = Vec::new();
    for name in names {
        match read_json(&ws.handoff_dir().join(&name)) {
            Ok(Some(mut payload @ Value::Object(_))) => {
                if let Some(object) = payload.as_object_mut() {
                    object.insert("_file".into(), json!(name));
                }
                items.push(payload);
            }
            Ok(_) => {}
            Err(error) => eprintln!("WARN  skipping corrupt handoff file {name}: {error}"),
        }
    }
    items
}

pub fn read_checkpoint(
    ws: &Workspace,
    task_id: &str,
) -> Option<(Map<String, Value>, String, Value)> {
    let path = checkpoint_path(ws, task_id);
    if !path.exists() {
        return None;
    }
    let (meta, body, _) = store::parse_task(&path).ok()?;
    let sidecar = match read_json(&checkpoint_sidecar(ws, task_id)) {
        Ok(Some(value)) => value,
        Ok(None) => json!({}),
        Err(error) => {
            eprintln!("WARN  checkpoint sidecar for task {task_id} is corrupt: {error}");
            json!({})
        }
    };
    Some((meta, body, sidecar))
}

pub fn sidecar_mismatch(ws: &Workspace, task_id: &str) -> Option<String> {
    let path = checkpoint_path(ws, task_id);
    if !path.exists() {
        return None;
    }
    let (meta, _, _) = store::parse_task(&path).ok()?;
    let sidecar = checkpoint_sidecar(ws, task_id);
    if !sidecar.exists() {
        return Some(format!("checkpoint {task_id} has a .md but no sidecar"));
    }
    let payload = match read_json(&sidecar) {
        Ok(Some(value)) => value,
        Ok(None) => json!({}),
        Err(error) => return Some(format!("checkpoint sidecar {task_id} is corrupt: {error}")),
    };
    let created = payload.get("created").and_then(Value::as_str).unwrap_or("");
    let meta_created = meta.get("created").and_then(Value::as_str).unwrap_or("");
    if created != meta_created {
        return Some(format!(
            "checkpoint sidecar {task_id} belongs to a different checkpoint"
        ));
    }
    None
}

pub fn rebuild_sidecar(ws: &Workspace, task_id: &str) -> Result<bool> {
    let path = checkpoint_path(ws, task_id);
    if !path.exists() {
        return Ok(false);
    }
    let (meta, _, _) = store::parse_task(&path)?;
    write_json_atomic(
        &checkpoint_sidecar(ws, task_id),
        &json!({
            "task": task_id,
            "created": meta.get("created"),
            "agent": meta.get("agent"),
            "reason": meta.get("reason"),
            "percent": meta.get("percent"),
            "git": {},
            "files": {},
            "rebuilt": true,
        }),
    )?;
    Ok(true)
}

pub fn checkpoint_age_minutes(ws: &Workspace, task_id: &str) -> Option<f64> {
    let (meta, _, _) = read_checkpoint(ws, task_id)?;
    crate::core::time::age_minutes(meta.get("created").and_then(Value::as_str))
}

pub fn checkpoint_required(
    ws: &Workspace,
    task_id: &str,
    claimed_at: Option<&str>,
    warn_after_minutes: Option<f64>,
) -> Option<String> {
    let claimed_at = claimed_at?;
    let threshold = warn_after_minutes?;
    let started = parse_iso(claimed_at)?;
    let elapsed = (now() - started).num_seconds() as f64 / 60.0;
    if elapsed <= threshold {
        return None;
    }
    if let Some((meta, _, _)) = read_checkpoint(ws, task_id) {
        if let Some(created) = meta
            .get("created")
            .and_then(Value::as_str)
            .and_then(parse_iso)
        {
            if created >= started {
                return None;
            }
        }
    }
    Some(format!(
        "Task {task_id} has been claimed for {} minutes without a checkpoint (the warn threshold is {} minutes). Save recoverable state first: `ai checkpoint {task_id} --agent <name> --next \"<step>\"`, then deliver again.",
        elapsed as i64, threshold as i64
    ))
}

pub fn fingerprint_file(ws: &Workspace, relative: &str) -> Option<Value> {
    let path = ws.project.join(relative.replace('\\', "/"));
    if !path.is_file() {
        return None;
    }
    let metadata = fs::metadata(&path).ok()?;
    if metadata.len() > 5 * 1024 * 1024 {
        let modified = metadata.modified().ok()?;
        let mtime_ns = modified
            .duration_since(std::time::UNIX_EPOCH)
            .ok()
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        return Some(json!({"size": metadata.len(), "mtime_ns": mtime_ns, "large": true}));
    }
    let data = fs::read(&path).ok()?;
    let mut hasher = Sha256::new();
    hasher.update(&data);
    Some(json!({
        "sha256": format!("{:x}", hasher.finalize()),
        "size": metadata.len(),
    }))
}

#[derive(Clone, Debug, Default)]
pub struct CheckpointFields {
    pub title: Option<String>,
    pub objective: Option<String>,
    pub status: Option<String>,
    pub done: Option<String>,
    pub in_progress: Option<String>,
    pub next: Option<String>,
    pub decisions: Option<String>,
    pub do_not: Option<String>,
    pub questions: Option<String>,
    pub files: Vec<String>,
    pub files_text: Option<String>,
    pub verification: Option<String>,
    pub status_line: Option<String>,
}

fn text(value: &Option<String>, fallback: &str) -> String {
    value
        .as_ref()
        .filter(|value| !value.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| fallback.to_string())
}

pub fn write_checkpoint(
    ws: &Workspace,
    task_id: &str,
    agent: &str,
    reason: &str,
    percent: Option<i64>,
    fields: &CheckpointFields,
) -> Result<PathBuf> {
    crate::runtime::dirs::ensure_dirs(ws)?;
    let task_id = normalize_id(task_id)?;
    let state = git::state(ws);
    let previous = checkpoint_path(ws, &task_id);
    if previous.exists() {
        let stamp = compact_stamp(now());
        let archive = ws
            .checkpoint_archive()
            .join(format!("{task_id}-{stamp}.md"));
        let _ = fs::copy(&previous, archive);
    }
    let mut files: Map<String, Value> = Map::new();
    for rel in &fields.files {
        if let Some(fingerprint) = fingerprint_file(ws, rel) {
            files.insert(rel.replace('\\', "/"), fingerprint);
        }
    }
    if let Some(dirty) = state.get("dirty").and_then(Value::as_array) {
        for rel in dirty.iter().filter_map(Value::as_str) {
            if !rel.is_empty() && !files.contains_key(rel) {
                if let Some(fingerprint) = fingerprint_file(ws, rel) {
                    files.insert(rel.to_string(), fingerprint);
                }
            }
        }
    }
    let files_text = if fields
        .files_text
        .as_ref()
        .map(|text| !text.trim().is_empty())
        .unwrap_or(false)
    {
        fields.files_text.clone()
    } else if files.is_empty() {
        None
    } else {
        let mut lines = Vec::new();
        let mut keys: Vec<&String> = files.keys().collect();
        keys.sort();
        for rel in keys {
            let item = &files[rel];
            let detail = if item.get("large").and_then(Value::as_bool).unwrap_or(false) {
                "large file (size/mtime only)".to_string()
            } else {
                item.get("sha256")
                    .and_then(Value::as_str)
                    .map(|hash| hash[..hash.len().min(12)].to_string())
                    .unwrap_or_default()
            };
            lines.push(format!("- `{rel}` {detail}").trim_end().to_string());
        }
        Some(lines.join("\n"))
    };
    let title = fields.title.clone().unwrap_or_else(|| "task".to_string());
    let branch = state
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("no branch");
    let head = state.get("head").and_then(Value::as_str).unwrap_or("");
    let head_short = if head.is_empty() {
        "no commit"
    } else {
        &head[..head.len().min(8)]
    };
    let status_line = fields
        .status_line
        .clone()
        .unwrap_or_else(|| "in progress".to_string());
    let auto_status = format!("{status_line} on branch {branch} at {head_short}.");
    let auto_next = fields.next.clone().unwrap_or_else(|| {
        format!(
            "Continue task {task_id} ({title}) from the current step; re-read the task and its spec before editing."
        )
    });
    let mut meta: Map<String, Value> = Map::new();
    meta.insert("task".into(), json!(task_id));
    meta.insert("agent".into(), json!(agent));
    meta.insert("created".into(), json!(iso(None)));
    meta.insert("reason".into(), json!(reason));
    meta.insert("percent".into(), json!(percent));
    meta.insert(
        "branch".into(),
        state.get("branch").cloned().unwrap_or(Value::Null),
    );
    meta.insert(
        "head".into(),
        state.get("head").cloned().unwrap_or(Value::Null),
    );
    meta.insert("next".into(), json!(auto_next));
    meta.insert("status_line".into(), json!(fields.status_line));
    let body = format!(
        r#"# Checkpoint {task_id} - {title}

## Objective

{objective}

## Status

{status}

## Done

{done}

## In progress

{in_progress}

## Next steps

{auto_next}

## Decisions

{decisions}

## Do not

{do_not}

## Open questions

{questions}

## Files

{files}

## Verification

{verification}
"#,
        objective = text(&fields.objective, &format!("Task {task_id}: {title}")),
        status = text(&fields.status, &auto_status),
        done = text(&fields.done, "Nothing recorded yet."),
        in_progress = text(&fields.in_progress, &auto_status),
        decisions = text(&fields.decisions, "No decisions recorded."),
        do_not = text(&fields.do_not, "No constraints recorded."),
        questions = text(&fields.questions, "None open."),
        files = text(&files_text, "No files recorded."),
        verification = text(&fields.verification, "No verification run yet."),
    );
    store::write_task(&checkpoint_path(ws, &task_id), &meta, &body)?;
    write_json_atomic(
        &checkpoint_sidecar(ws, &task_id),
        &json!({
            "task": task_id,
            "created": meta.get("created"),
            "agent": agent,
            "reason": reason,
            "percent": percent,
            "git": state,
            "files": files,
        }),
    )?;
    let marker = handoff_marker(ws, &task_id);
    if marker.exists() {
        let _ = fs::remove_file(marker);
    }
    Ok(checkpoint_path(ws, &task_id))
}

pub fn format_checkpoint_age(ws: &Workspace, task_id: &str) -> String {
    match checkpoint_age_minutes(ws, task_id) {
        None => "none".to_string(),
        Some(age) => {
            let minutes = age as i64;
            if minutes < 60 {
                format!("{minutes}m ago")
            } else if minutes < 48 * 60 {
                format!("{}h ago", minutes / 60)
            } else {
                format!("{}d ago", minutes / (24 * 60))
            }
        }
    }
}

pub fn checkpoint_sections(ws: &Workspace, task_id: &str) -> Map<String, Value> {
    let mut sections = Map::new();
    let (_, body, _) = match read_checkpoint(ws, task_id) {
        Some(data) => data,
        None => return sections,
    };
    let mut current: Option<String> = None;
    for line in body.lines() {
        if let Some(heading) = line.strip_prefix("## ") {
            current = match heading.trim().to_lowercase().as_str() {
                "objective" => Some("objective".into()),
                "status" => Some("status".into()),
                "done" => Some("done".into()),
                "in progress" => Some("in_progress".into()),
                "next steps" => Some("next".into()),
                "decisions" => Some("decisions".into()),
                "do not" => Some("do_not".into()),
                "open questions" => Some("questions".into()),
                "files" => Some("files_text".into()),
                "verification" => Some("verification".into()),
                _ => None,
            };
            if let Some(key) = &current {
                sections.insert(key.clone(), json!(""));
            }
        } else if let Some(key) = &current {
            let existing = sections
                .get(key)
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            sections.insert(key.clone(), json!(format!("{existing}{line}\n")));
        }
    }
    for (_, value) in sections.iter_mut() {
        let cleaned = value
            .as_str()
            .unwrap_or("")
            .lines()
            .filter(|line| !line.trim_start().starts_with("<!--"))
            .collect::<Vec<_>>()
            .join("\n");
        *value = json!(cleaned.trim().to_string());
    }
    sections
}

pub fn current_drift(ws: &Workspace, task_id: &str) -> Value {
    let (_, _, sidecar) = match read_checkpoint(ws, task_id) {
        Some(data) => data,
        None => return json!({"checkpoint": false}),
    };
    let current = git::state(ws);
    let saved_git = sidecar.get("git").cloned().unwrap_or(json!({}));
    let head = current.get("head").and_then(Value::as_str);
    let mut drift = json!({
        "checkpoint": true,
        "branch": current.get("branch"),
        "head": current.get("head"),
        "dirty": current.get("dirty"),
        "commits_since": Value::Null,
        "files": {},
        "evidence": crate::runtime::evidence::task_status(ws, task_id, head, None),
    });
    let old_head = saved_git.get("head").and_then(Value::as_str);
    if let (Some(old), Some(new)) = (old_head, head) {
        if old != new {
            let output = git::run_git(
                &ws.project,
                &["rev-list", "--count", &format!("{old}..{new}")],
            );
            if output.code == 0 {
                if let Ok(count) = output.stdout.parse::<i64>() {
                    drift["commits_since"] = json!(count);
                }
            }
        }
    }
    let mut changed: Map<String, Value> = Map::new();
    if let Some(saved) = sidecar.get("files").and_then(Value::as_object) {
        for (rel, fingerprint) in saved {
            match fingerprint_file(ws, rel) {
                None => {
                    changed.insert(rel.clone(), json!("gone"));
                }
                Some(now_fp) => {
                    let old_hash = fingerprint.get("sha256").and_then(Value::as_str);
                    let new_hash = now_fp.get("sha256").and_then(Value::as_str);
                    let status = if let (Some(old_hash), Some(new_hash)) = (old_hash, new_hash) {
                        if old_hash == new_hash {
                            "verified"
                        } else {
                            "changed"
                        }
                    } else {
                        let old_mtime = fingerprint.get("mtime_ns").and_then(Value::as_i64);
                        let new_mtime = now_fp.get("mtime_ns").and_then(Value::as_i64);
                        if old_mtime.is_some() && old_mtime == new_mtime {
                            "verified"
                        } else {
                            "changed"
                        }
                    };
                    changed.insert(rel.clone(), json!(status));
                }
            }
        }
    }
    drift["files"] = Value::Object(changed);
    drift
}

pub fn resume_prompt(ws: &Workspace, task_id: &str) -> String {
    let path = store::find_task(ws, task_id);
    let prefix = ws.ws_prefix();
    let rel = path
        .as_ref()
        .map(|path| relative_to(&ws.project, path))
        .unwrap_or_else(|| format!("{prefix}tasks/active/{task_id}-..."));
    let checkpoint = relative_to(&ws.project, &checkpoint_path(ws, task_id));
    let cli = format!("{prefix}ai");
    format!(
        r#"You are resuming task {task_id} in the .ai engineering workspace.

1. Read {prefix}AGENTS.md, then {rel} and {checkpoint}. Open {prefix}GUIDE.md or {prefix}docs/task-flow.md only if you need a command or rule you do not already have; do not re-read them for context.
2. Verify the real repository state before trusting the checkpoint (git status, git log, tests).
3. Claim or refresh ownership: `{cli} task claim {task_id} --agent <name>` (or `{cli} lock heartbeat task-{task_id}`).
4. Continue from the first unchecked item in "Next steps". Do not redo "Done" items.
5. Checkpoint at the next milestone, and always before your context window fills: `{cli} checkpoint {task_id} --agent <name>`.
6. Never call it done without `{cli} check`.
"#
    )
}

pub fn path_is_under(base: &Path, target: &Path) -> bool {
    target.starts_with(base)
}
