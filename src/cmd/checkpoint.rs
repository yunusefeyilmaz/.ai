//! `ai checkpoint`, `ai handoff` and `ai resume`.

use serde_json::{json, Map, Value};

use crate::core::error::Result;
use crate::core::fsio::write_json_atomic;
use crate::core::time::iso;
use crate::core::workspace::{relative_to, Workspace};
use crate::runtime::checkpoints::{self, CheckpointFields};
use crate::runtime::events::append_event;
use crate::runtime::mutex::workspace_state_guard;
use crate::tasks::store;

use crate::{CheckpointArgs, ResumeArgs};

fn merged_fields(
    ws: &Workspace,
    task_id: &str,
    title: Option<&str>,
    status_line: Option<&str>,
    args: &CheckpointArgs,
) -> CheckpointFields {
    let sections = checkpoints::checkpoint_sections(ws, task_id);
    let sidecar = checkpoints::read_checkpoint(ws, task_id)
        .map(|(_, _, sidecar)| sidecar)
        .unwrap_or(Value::Null);
    let keep = |value: &Option<String>, key: &str| -> Option<String> {
        value.clone().or_else(|| {
            sections
                .get(key)
                .and_then(Value::as_str)
                .filter(|text| !text.trim().is_empty())
                .map(ToString::to_string)
        })
    };
    let files: Vec<String> = match &args.files {
        Some(files) => files
            .split(',')
            .map(str::trim)
            .filter(|item| !item.is_empty())
            .map(ToString::to_string)
            .collect(),
        None => sidecar
            .get("files")
            .and_then(Value::as_object)
            .map(|files| files.keys().cloned().collect())
            .unwrap_or_default(),
    };
    CheckpointFields {
        title: title.map(ToString::to_string),
        objective: keep(&args.objective, "objective"),
        status: keep(&args.status, "status"),
        done: keep(&args.done, "done"),
        in_progress: keep(&args.in_progress, "in_progress"),
        next: keep(&args.next, "next"),
        decisions: keep(&args.decisions, "decisions"),
        do_not: keep(&args.do_not, "do_not"),
        questions: keep(&args.questions, "questions"),
        files,
        files_text: args.files_text.clone().or_else(|| {
            sections
                .get("files_text")
                .and_then(Value::as_str)
                .filter(|text| !text.trim().is_empty())
                .map(ToString::to_string)
        }),
        verification: keep(&args.verification, "verification"),
        status_line: status_line.map(ToString::to_string),
    }
}

fn existing_percent(ws: &Workspace, task_id: &str, args: &CheckpointArgs) -> Option<i64> {
    if args.percent.is_some() {
        return args.percent;
    }
    checkpoints::read_checkpoint(ws, task_id)
        .and_then(|(meta, _, _)| meta.get("percent").and_then(Value::as_i64))
}

pub fn checkpoint(ws: &Workspace, args: &CheckpointArgs) -> Result<i32> {
    let task_id = match store::resolve_task_id(ws, args.task_id.as_deref()) {
        Some(task_id) => task_id,
        None => {
            eprintln!("No task to checkpoint. Create or claim a task first.");
            return Ok(1);
        }
    };
    let checkpoint_path;
    {
        let _guard = workspace_state_guard(ws)?;
        let path = match store::find_task(ws, &task_id) {
            Some(path) => path,
            None => {
                eprintln!("No task with id {task_id}.");
                return Ok(1);
            }
        };
        let (mut meta, body, _) = store::parse_task(&path)?;
        let owner = meta.get("owner").and_then(Value::as_str).unwrap_or("");
        if !owner.is_empty() && owner != args.agent && !args.force {
            eprintln!("Task {task_id} is owned by {owner}. Use --force to checkpoint anyway.");
            return Ok(1);
        }
        let fields = merged_fields(
            ws,
            &task_id,
            meta.get("title").and_then(Value::as_str),
            meta.get("status").and_then(Value::as_str),
            args,
        );
        let percent = existing_percent(ws, &task_id, args);
        checkpoint_path = checkpoints::write_checkpoint(
            ws,
            &task_id,
            &args.agent,
            &args.reason,
            percent,
            &fields,
        )?;
        meta.insert("updated".into(), json!(iso(None)));
        let body = format!(
            "{}\n- {} checkpoint by {} ({}, {}%)\n",
            body.trim_end_matches('\n'),
            iso(None),
            args.agent,
            args.reason,
            percent
                .map(|value| value.to_string())
                .unwrap_or_else(|| "?".to_string())
        );
        store::write_task(&path, &meta, &body)?;
    }
    append_event(
        ws,
        "checkpoint",
        &[("task", json!(task_id)), ("agent", json!(args.agent))],
    );
    println!("Checkpoint: {}", relative_to(&ws.root, &checkpoint_path));
    if let Some(next) = &args.next {
        println!("Next: {next}");
    }
    println!("Resume later with: ai resume {task_id}");
    Ok(0)
}

pub fn handoff(ws: &Workspace, args: &CheckpointArgs) -> Result<i32> {
    let task_id = match store::resolve_task_id(ws, args.task_id.as_deref()) {
        Some(task_id) => task_id,
        None => {
            eprintln!("No task to hand off.");
            return Ok(1);
        }
    };
    let checkpoint_path;
    {
        let _guard = workspace_state_guard(ws)?;
        let path = match store::find_task(ws, &task_id) {
            Some(path) => path,
            None => {
                eprintln!("No task with id {task_id}.");
                return Ok(1);
            }
        };
        let (mut meta, body, _) = store::parse_task(&path)?;
        let owner = meta.get("owner").and_then(Value::as_str).unwrap_or("");
        if !owner.is_empty() && owner != args.agent {
            eprintln!("Task {task_id} is owned by {owner}.");
            return Ok(1);
        }
        let fields = merged_fields(
            ws,
            &task_id,
            meta.get("title").and_then(Value::as_str),
            meta.get("status").and_then(Value::as_str),
            args,
        );
        let percent = existing_percent(ws, &task_id, args);
        checkpoint_path =
            checkpoints::write_checkpoint(ws, &task_id, &args.agent, "handoff", percent, &fields)?;
        write_json_atomic(
            &checkpoints::handoff_marker(ws, &task_id),
            &json!({
                "task": task_id,
                "agent": args.agent,
                "reason": args.reason,
                "created": iso(None),
                "checkpoint": relative_to(&ws.root, &checkpoint_path),
            }),
        )?;
        meta.insert("updated".into(), json!(iso(None)));
        let body = format!(
            "{}\n- {} handoff requested by {}: {}\n",
            body.trim_end_matches('\n'),
            iso(None),
            args.agent,
            args.reason
        );
        store::write_task(&path, &meta, &body)?;
    }
    println!(
        "Handoff marker: {}",
        relative_to(&ws.root, &checkpoints::handoff_marker(ws, &task_id))
    );
    println!(
        "Checkpoint:     {}",
        relative_to(&ws.root, &checkpoint_path)
    );
    println!("\nPaste this into the next agent:\n");
    println!("{}", checkpoints::resume_prompt(ws, &task_id));
    Ok(0)
}

pub fn resume(ws: &Workspace, args: &ResumeArgs) -> Result<i32> {
    let task_id = match store::resolve_task_id(ws, args.task_id.as_deref()) {
        Some(task_id) => task_id,
        None => {
            eprintln!("No task to resume.");
            return Ok(1);
        }
    };
    let path = match store::find_task(ws, &task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task file for {task_id}; it may have been archived.");
            return Ok(1);
        }
    };
    let (meta, body, _) = store::parse_task(&path)?;
    let data = checkpoints::read_checkpoint(ws, &task_id);
    let drift = checkpoints::current_drift(ws, &task_id);
    let markers: Vec<Value> = checkpoints::list_handoff_markers(ws, true)
        .into_iter()
        .filter(|marker| marker.get("task").and_then(Value::as_str) == Some(task_id.as_str()))
        .collect();
    append_event(
        ws,
        "resume",
        &[
            ("task", json!(task_id)),
            ("agent", meta.get("owner").cloned().unwrap_or(Value::Null)),
        ],
    );
    let prompt = checkpoints::resume_prompt(ws, &task_id);
    if args.json {
        let payload = json!({
            "task": meta,
            "checkpoint": data.as_ref().map(|entry| entry.0.clone()),
            "checkpoint_body": data.as_ref().map(|entry| entry.1.clone()),
            "drift": drift,
            "handoff": markers,
            "prompt": prompt,
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }
    println!(
        "Task      : {task_id} - {}",
        meta.get("title").and_then(Value::as_str).unwrap_or("")
    );
    println!(
        "Status    : {} (owner {})",
        meta.get("status").and_then(Value::as_str).unwrap_or("-"),
        meta.get("owner").and_then(Value::as_str).unwrap_or("-")
    );
    println!(
        "Spec      : {}",
        meta.get("spec").and_then(Value::as_str).unwrap_or("-")
    );
    println!("File      : {}", relative_to(&ws.root, &path));
    println!(
        "Checkpoint: {}",
        data.as_ref()
            .map(|_| relative_to(&ws.root, &checkpoints::checkpoint_path(ws, &task_id)))
            .unwrap_or_else(|| "none".to_string())
    );
    if let Some(marker) = markers.first() {
        println!(
            "Handoff   : requested by {} ({})",
            marker.get("agent").and_then(Value::as_str).unwrap_or("-"),
            marker.get("reason").and_then(Value::as_str).unwrap_or("-")
        );
    }
    println!();
    if let Some((checkpoint_meta, checkpoint_body, _)) = &data {
        println!(
            "Checkpoint age: {} min ({})",
            checkpoints::checkpoint_age_minutes(ws, &task_id).unwrap_or(0.0) as i64,
            checkpoint_meta
                .get("reason")
                .and_then(Value::as_str)
                .unwrap_or("-")
        );
        println!(
            "Next (saved)  : {}",
            checkpoint_meta
                .get("next")
                .and_then(Value::as_str)
                .unwrap_or("-")
        );
        println!();
        println!("{}", checkpoint_body.trim());
        println!();
    } else {
        println!("No checkpoint yet. The task body is the only saved context.");
        println!();
        println!("{}", body.trim());
        println!();
    }
    if drift
        .get("checkpoint")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let changed: Vec<&str> = drift
            .get("files")
            .and_then(Value::as_object)
            .map(|files| {
                files
                    .iter()
                    .filter(|(_, status)| status.as_str() != Some("verified"))
                    .map(|(path, _)| path.as_str())
                    .collect()
            })
            .unwrap_or_default();
        println!("Drift:");
        println!(
            "  branch: {} | head: {}",
            drift.get("branch").and_then(Value::as_str).unwrap_or("-"),
            drift
                .get("head")
                .and_then(Value::as_str)
                .map(|head| &head[..head.len().min(8)])
                .unwrap_or("-")
        );
        if let Some(commits) = drift.get("commits_since").and_then(Value::as_i64) {
            println!("  commits since checkpoint: {commits}");
        }
        println!(
            "  files needing attention: {}",
            if changed.is_empty() {
                "none".to_string()
            } else {
                changed.join(", ")
            }
        );
        let proof = drift.get("evidence").cloned().unwrap_or(json!({}));
        let state = proof.get("state").and_then(Value::as_str).unwrap_or("none");
        match state {
            "none" => println!(
                "  verification: none recorded; run `ai check --task <id> --agent <n>` before review"
            ),
            "green" => println!(
                "  verification: still valid for this HEAD ({})",
                proof.get("summary").and_then(Value::as_str).unwrap_or("-")
            ),
            "partial" => println!(
                "  verification: PARTIAL, not enough for review ({})",
                proof
                    .get("reason")
                    .or_else(|| proof.get("summary"))
                    .and_then(Value::as_str)
                    .unwrap_or("-")
            ),
            other => println!(
                "  verification: {}, do not trust it ({})",
                other.to_uppercase(),
                proof
                    .get("reason")
                    .or_else(|| proof.get("summary"))
                    .and_then(Value::as_str)
                    .unwrap_or("-")
            ),
        }
        println!();
    }
    println!("Resume prompt:");
    println!("{}", "-".repeat(60));
    println!("{}", prompt.trim());
    println!("{}", "-".repeat(60));
    let _ = Map::<String, Value>::new();
    Ok(0)
}
