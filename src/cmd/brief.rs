//! `ai brief`: a paste-ready package for an external chat assistant.

use std::fs;

use serde_json::{json, Map, Value};

use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::time::iso;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo as git;
use crate::runtime::checkpoints;
use crate::specs::spec;
use crate::tasks::store;

use crate::BriefArgs;

pub fn run(ws: &Workspace, args: &BriefArgs) -> Result<i32> {
    let config = config::load_or_default(ws);
    let tasks = store::load_tasks(ws);
    let active: Vec<&store::Task> = tasks.iter().filter(|task| task.is_active()).collect();
    let task_id = store::resolve_task_id(ws, args.task_id.as_deref());
    let mut meta: Option<Map<String, Value>> = None;
    let mut body: Option<String> = None;
    let mut task_path = None;
    if let Some(task_id) = &task_id {
        if let Some(path) = store::find_task(ws, task_id) {
            let (parsed, parsed_body, _) = store::parse_task(&path)?;
            meta = Some(parsed);
            body = Some(parsed_body);
            task_path = Some(path);
        }
    }
    let spec_path = meta
        .as_ref()
        .and_then(|meta| spec::resolve_spec_path(ws, meta));
    let checkpoint = task_id
        .as_deref()
        .and_then(|task_id| checkpoints::read_checkpoint(ws, task_id));
    let state = git::state(ws);
    let cli = "ai";
    let mut lines: Vec<String> = vec![
        "=== .ai WORKSPACE BRIEF ===".to_string(),
        format!("Generated: {}", iso(None)),
        format!(
            "Project:   {}",
            ws.project
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("workspace")
        ),
        format!("Workspace: {}", if ws.ws_prefix().is_empty() { "./" } else { ws.ws_prefix() }),
        format!("Mode:      {}", config.get("mode").and_then(Value::as_str).unwrap_or("-")),
        String::new(),
        "You are an external assistant. You may not have filesystem or shell access.".to_string(),
        "Never claim that you ran a command, test or check. Ask the human to run the".to_string(),
        "commands below and paste the output back. Keep every AI-generated note, spec".to_string(),
        "or scratch file inside the .ai workspace; the rest of the repository is".to_string(),
        "product code.".to_string(),
        String::new(),
        "--- Operating rules ---".to_string(),
        "1. One task per session. Claim it before editing anything.".to_string(),
        "2. Lease the files or subsystem you will touch; a live lease is a refusal.".to_string(),
        "3. A behavior change needs a spec with testable acceptance criteria.".to_string(),
        "4. The producer never reviews its own work.".to_string(),
        "5. Work is done only when `ai check` is green and its output is recorded.".to_string(),
        "6. Checkpoint at milestones and before the context window fills.".to_string(),
        format!(
            "7. Record lasting decisions as an ADR under {}docs/decisions/.",
            ws.ws_prefix()
        ),
        "8. Every file-changing task must use Gitflow unless the user explicitly says not to use Git. Run `ai git setup`; it initializes Git and asks before an initial commit.".to_string(),
        "9. After claim, run `ai git start` before editing; stop if setup or branch creation fails. Commit with `ai git commit`; a different reviewer must merge with `ai git finish` before done. Read-only work needs no branch.".to_string(),
        String::new(),
    ];
    if let Some(meta) = &meta {
        lines.extend([
            "--- Current task ---".to_string(),
            format!("ID:         {}", text(meta.get("id"))),
            format!("Title:      {}", text(meta.get("title"))),
            format!("Status:     {}", text(meta.get("status"))),
            format!("Owner:      {}", text(meta.get("owner"))),
            format!("Priority:   {}", text(meta.get("priority"))),
            format!(
                "Spec:       {}",
                spec_path
                    .as_ref()
                    .map(|path| relative_to(&ws.project, path))
                    .or_else(|| meta
                        .get("spec")
                        .and_then(Value::as_str)
                        .map(ToString::to_string))
                    .unwrap_or_else(|| "none".to_string())
            ),
            format!("Depends on: {}", text(meta.get("depends_on"))),
            format!(
                "File:       {}",
                task_path
                    .as_ref()
                    .map(|path| relative_to(&ws.project, path))
                    .unwrap_or_else(|| "-".to_string())
            ),
            String::new(),
            body.clone()
                .map(|body| body.trim().to_string())
                .filter(|body| !body.is_empty())
                .unwrap_or_else(|| "(task body is empty)".to_string()),
            String::new(),
        ]);
    } else {
        lines.push("--- Current task ---".to_string());
        lines.push(if active.is_empty() {
            "No active task selected.".to_string()
        } else {
            "No task id was given. Active tasks:".to_string()
        });
        for task in &active {
            lines.push(format!(
                "- {} [{}] {} (owner: {})",
                task.id(),
                task.status(),
                task.title(),
                task.owner().unwrap_or_else(|| "-".to_string())
            ));
        }
        lines.push(String::new());
    }
    lines.push("--- Spec ---".to_string());
    if let Some(spec_path) = &spec_path {
        lines.push(format!("File: {}", relative_to(&ws.project, spec_path)));
        lines.push(String::new());
        lines.push(
            fs::read_to_string(spec_path)
                .unwrap_or_default()
                .trim()
                .to_string(),
        );
        lines.push(String::new());
    } else {
        lines.push("No spec is linked to this task.".to_string());
        lines.push(String::new());
    }
    lines.push("--- Last checkpoint ---".to_string());
    if let Some((checkpoint_meta, checkpoint_body, _)) = &checkpoint {
        lines.extend([
            format!("Created: {}", text(checkpoint_meta.get("created"))),
            format!("Reason:  {}", text(checkpoint_meta.get("reason"))),
            format!("Next:    {}", text(checkpoint_meta.get("next"))),
            String::new(),
            checkpoint_body.trim().to_string(),
            String::new(),
        ]);
    } else {
        lines.push("No checkpoint exists.".to_string());
        lines.push(String::new());
    }
    lines.push("--- Repository state ---".to_string());
    lines.push(format!(
        "Branch: {}",
        state.get("branch").and_then(Value::as_str).unwrap_or("-")
    ));
    lines.push(format!(
        "HEAD:   {}",
        state.get("head").and_then(Value::as_str).unwrap_or("-")
    ));
    let dirty = state
        .get("dirty")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if dirty.is_empty() {
        lines.push("Working tree is clean.".to_string());
    } else {
        lines.push("Uncommitted paths:".to_string());
        for path in dirty.iter().take(20).filter_map(Value::as_str) {
            lines.push(format!("- {path}"));
        }
        if dirty.len() > 20 {
            lines.push(format!("- ... {} more", dirty.len() - 20));
        }
    }
    lines.extend([
        String::new(),
        "--- How to answer ---".to_string(),
        "- If the human asks for implementation: give a short plan first, then minimal".to_string(),
        "  patches or diffs and exact commands. Do not invent file contents.".to_string(),
        "- Tie every change to an acceptance criterion. Flag ambiguity before coding.".to_string(),
        "- Mark anything you could not verify as unverified.".to_string(),
        String::new(),
        "--- Commands available to the human ---".to_string(),
        format!("{cli} now --agent <n>"),
        format!("{cli} doctor"),
        format!("{cli} status"),
        format!("{cli} task show <id>"),
        format!("{cli} task claim <id> --agent <name>"),
        format!("{cli} lock acquire <path> --agent <name> --task <id>"),
        format!("{cli} checkpoint <id> --agent <name> --next \"...\""),
        format!("{cli} check --strict"),
        format!("{cli} task done <id> --agent <name>"),
        String::new(),
        "=== END BRIEF ===".to_string(),
    ]);
    let mut text = lines.join("\n");
    if args.max_chars > 0 && text.chars().count() > args.max_chars {
        let truncated: String = text.chars().take(args.max_chars).collect();
        text = format!(
            "{}\n\n[truncated by ai brief]\n=== END BRIEF ===",
            truncated.trim_end()
        );
    }
    if args.json {
        let spec_body = spec_path
            .as_ref()
            .and_then(|path| fs::read_to_string(path).ok());
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "project": ws.project.file_name().and_then(|name| name.to_str()).unwrap_or("workspace"),
                "workspace": if ws.ws_prefix().is_empty() { "./" } else { ws.ws_prefix() },
                "mode": config.get("mode"),
                "task": meta,
                "task_body": body,
                "spec_path": spec_path.as_ref().map(|path| relative_to(&ws.project, path)),
                "spec_body": spec_body,
                "checkpoint": checkpoint.as_ref().map(|entry| entry.0.clone()),
                "checkpoint_body": checkpoint.as_ref().map(|entry| entry.1.clone()),
                "git": state,
                "brief": text,
            }))?
        );
        return Ok(0);
    }
    println!("{text}");
    Ok(0)
}

fn text(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) if !text.is_empty() => text.clone(),
        Some(Value::Bool(true)) => "yes".to_string(),
        Some(Value::Bool(false)) => "no".to_string(),
        Some(Value::Null) | None => "-".to_string(),
        Some(other) => other.to_string(),
    }
}
