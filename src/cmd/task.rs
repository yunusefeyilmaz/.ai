//! `ai task ...`: the task ledger state machine.

use std::io::{IsTerminal, Write};
use std::path::Path;

use serde_json::{json, Map, Value};

use crate::cmd::common::{apply_transition, rel, text, text_or};
use crate::config::roles;
use crate::config::settings as config;
use crate::core::error::{fail, Result};
use crate::core::fsio::{normalize_id, read_text};
use crate::core::time::iso;
use crate::core::workspace::Workspace;
use crate::git::flow as gitflow;
use crate::git::repo as git;
use crate::runtime::checkpoints;
use crate::runtime::events::append_event;
use crate::runtime::evidence;
use crate::runtime::leases::{self, acquire_lock, effective_holder, list_locks, release_lock};
use crate::runtime::mutex::workspace_state_guard;
use crate::specs::spec;
use crate::tasks::board;
use crate::tasks::gates;
use crate::tasks::history;
use crate::tasks::lifecycle::{self, NewTask};
use crate::tasks::scope;
use crate::tasks::store::{self, Task};

use crate::{TaskAction, TaskArgs};

pub fn run(ws: &Workspace, args: &TaskArgs) -> Result<i32> {
    let action = match &args.action {
        Some(action) => action,
        None => {
            eprintln!("Usage: ai task <new|list|show|link|ready|next|claim|release|review|request-changes|done|reopen|discard|block|unblock>");
            return Ok(1);
        }
    };
    match action {
        TaskAction::New {
            title,
            priority,
            spec,
            no_spec,
            depends_on,
            allow,
            forbid,
            lock,
            agent,
            role,
        } => task_new(
            ws,
            title,
            priority,
            spec.clone(),
            *no_spec,
            depends_on.clone(),
            allow.as_slice(),
            forbid.as_slice(),
            lock.as_slice(),
            agent.as_deref(),
            role.as_deref(),
        ),
        TaskAction::List { all, json } => task_list(ws, *all, *json),
        TaskAction::Show { task_id, json } => task_show(ws, task_id, *json),
        TaskAction::Link {
            task_id,
            issue,
            pr,
            agent,
            json,
        } => task_link(
            ws,
            task_id,
            issue.as_deref(),
            pr.as_deref(),
            agent.as_deref(),
            *json,
        ),
        TaskAction::Ready { json } => task_ready(ws, *json),
        TaskAction::Next {
            agent,
            review,
            json,
        } => task_next(ws, agent, *review, *json),
        TaskAction::Claim {
            task_id,
            agent,
            force,
        } => task_claim(ws, task_id, agent, *force),
        TaskAction::Release {
            task_id,
            agent,
            force,
        } => task_release(ws, task_id, agent, *force),
        TaskAction::Review { task_id, agent } => task_review(ws, task_id, agent),
        TaskAction::RequestChanges {
            task_id,
            agent,
            reason,
        } => task_request_changes(ws, task_id, agent, reason),
        TaskAction::Done {
            task_id,
            agent,
            force,
        } => task_done(ws, task_id, agent, *force),
        TaskAction::Reopen {
            task_id,
            agent,
            reason,
            status,
        } => task_reopen(ws, task_id, agent, reason.as_deref(), status.as_deref()),
        TaskAction::Discard { task_id } => task_discard(ws, task_id),
        TaskAction::Block {
            task_id,
            agent,
            reason,
        } => task_block(ws, task_id, agent, reason),
        TaskAction::Unblock { task_id, agent } => task_unblock(ws, task_id, agent),
    }
}

#[allow(clippy::too_many_arguments)]
fn task_new(
    ws: &Workspace,
    title: &str,
    priority: &str,
    spec_ref: Option<String>,
    no_spec: bool,
    depends_on: Option<String>,
    allow: &[String],
    forbid: &[String],
    lock: &[String],
    agent: Option<&str>,
    role: Option<&str>,
) -> Result<i32> {
    if let Some(blocked) = gates::creation_gate(ws, role) {
        eprintln!("{blocked}");
        return Ok(1);
    }
    if let Err(denied) = roles::authorize(ws, agent, "task.new") {
        eprintln!("{denied}");
        return Ok(1);
    }
    let new = NewTask {
        title: title.to_string(),
        priority: priority.to_string(),
        spec: spec_ref,
        depends_on,
        make_spec: !no_spec,
        scope_allowed: scope::join_globs(Some(allow)),
        scope_forbidden: scope::join_globs(Some(forbid)),
        actor: agent.map(ToString::to_string),
        locks: scope::join_globs(Some(lock)),
        intent: None,
        acceptance: None,
        demo: false,
    };
    let created = lifecycle::create_task(ws, new)?;
    let path = created.get("path").and_then(Value::as_str).unwrap_or("");
    println!("Created {path}");
    if let Some(spec) = created.get("spec").and_then(Value::as_str) {
        println!("Spec: {spec}");
    }
    println!(
        "Claim it: ai task claim {} --agent <name>",
        created.get("id").and_then(Value::as_str).unwrap_or("")
    );
    Ok(0)
}

fn task_list(ws: &Workspace, all: bool, json: bool) -> Result<i32> {
    let tasks = {
        let _guard = workspace_state_guard(ws)?;
        let tasks = store::load_tasks(ws);
        board::write_board(ws, &tasks)?;
        tasks
    };
    let active: Vec<&Task> = tasks.iter().filter(|task| task.is_active()).collect();
    let done: Vec<&Task> = tasks.iter().filter(|task| task.folder == "done").collect();
    if json {
        // List views must stay compact: the Markdown body belongs to `task show`.
        let payload = json!({
            "active": active.iter().map(|task| task.slim_json()).collect::<Vec<_>>(),
            "done": done.iter().map(|task| task.slim_json()).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }
    let mut shown: Vec<&Task> = active.to_vec();
    if all {
        shown.extend(done.iter().copied());
    }
    let rows: Vec<Vec<String>> = shown
        .iter()
        .map(|task| {
            vec![
                task.id(),
                task.folder.clone(),
                task.status(),
                task.owner().unwrap_or_else(|| "-".into()),
                task.title(),
            ]
        })
        .collect();
    for line in store::text_table(
        &[
            ("ID", 6),
            ("FOLDER", 8),
            ("STATUS", 12),
            ("OWNER", 18),
            ("TITLE", 0),
        ],
        &rows,
    ) {
        println!("{line}");
    }
    println!(
        "\nActive: {} | Done: {} | Board: tasks/BOARD.md",
        active.len(),
        done.len()
    );
    Ok(0)
}

fn task_show(ws: &Workspace, task_id: &str, json: bool) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (meta, body, _) = store::parse_task(&path)?;
    let ci_results: Vec<String> = body
        .lines()
        .filter(|line| line.contains("CI:"))
        .map(|line| line.trim().trim_start_matches("- ").to_string())
        .collect();
    if json {
        let mut payload = json!({"meta": meta, "body": body});
        if !ci_results.is_empty() {
            payload["ci_results"] = json!(ci_results);
        }
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }
    println!("File: {}", rel(ws, &path));
    for (key, value) in meta.iter() {
        // Python prints the raw value (`None`, `True`, `123`); keep that shape
        // so scripts and tests read the same lines.
        let rendered = match value {
            Value::Null => "None".to_string(),
            Value::Bool(flag) => {
                if *flag {
                    "True".to_string()
                } else {
                    "False".to_string()
                }
            }
            Value::String(text) => text.clone(),
            other => other.to_string(),
        };
        println!("{key}: {rendered}");
    }
    if !ci_results.is_empty() {
        println!("\nCI results:");
        for item in &ci_results {
            println!("  {item}");
        }
    }
    println!();
    println!("{body}");
    print_held_locks(ws, &text_or(meta.get("id"), task_id));
    print_spec_criteria(ws, &meta);
    Ok(0)
}

fn print_held_locks(ws: &Workspace, task_id: &str) {
    let held: Vec<Value> = list_locks(ws, false)
        .into_iter()
        .filter(|lock| lock.get("task").and_then(Value::as_str) == Some(task_id))
        .collect();
    if held.is_empty() {
        return;
    }
    println!();
    println!("Held leases:");
    for lock in held {
        println!(
            "  {} ({}, ttl {}s)",
            text(lock.get("resource")),
            text(lock.get("agent")),
            text(lock.get("ttl_seconds"))
        );
    }
}

fn print_spec_criteria(ws: &Workspace, meta: &Map<String, Value>) {
    let path = match spec::resolve_spec_path(ws, meta) {
        Some(path) => path,
        None => return,
    };
    let content = match read_text(&path) {
        Ok(content) => content,
        Err(_) => return,
    };
    let criteria = spec::acceptance_criteria(&content);
    if criteria.is_empty() {
        return;
    }
    let (done, total) = spec::criteria_progress(&criteria);
    println!();
    println!(
        "Acceptance criteria (from {}; {done}/{total} done)",
        text_or(meta.get("spec"), "-")
    );
    for (is_done, item) in criteria {
        println!("  [{}] {item}", if is_done { "x" } else { " " });
    }
}

/// A task in `done/` is archived history: only `reopen` may change it.
fn require_active(ws: &Workspace, task_id: &str, path: &Path, action: &str) -> Option<i32> {
    if path.parent() == Some(ws.active_dir().as_path()) {
        return None;
    }
    eprintln!(
        "Task {task_id} is archived in done/ and cannot be changed by `{action}`. Bring it back first with `ai task reopen {task_id} --agent <name>`."
    );
    Some(1)
}

fn task_link(
    ws: &Workspace,
    task_id: &str,
    issue: Option<&str>,
    pr: Option<&str>,
    agent: Option<&str>,
    json: bool,
) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    if issue.is_none() && pr.is_none() {
        eprintln!("Specify at least --issue or --pr.");
        return Ok(1);
    }
    if let Some(code) = require_active(ws, task_id, &path, "task link") {
        return Ok(code);
    }
    let (mut meta, mut body, _) = store::parse_task(&path)?;
    let mut links = Vec::new();
    if let Some(issue) = issue {
        meta.insert("github_issue".into(), json!(issue.trim()));
        links.push(format!("issue: {issue}"));
    }
    if let Some(pr) = pr {
        meta.insert("github_pr".into(), json!(pr.trim()));
        links.push(format!("pr: {pr}"));
    }
    let note = match (issue, pr) {
        (Some(issue), Some(pr)) => format!("GitHub: {issue} / {pr}"),
        (Some(issue), None) => format!("GitHub issue: {issue}"),
        (None, Some(pr)) => format!("GitHub PR: {pr}"),
        _ => String::new(),
    };
    if let Some(index) = body.find("## Notes\n") {
        let index = index + "## Notes\n".len();
        body = format!("{}\n- {note}\n{}", &body[..index], &body[index..]);
    } else {
        body = format!("{}\n\n## Notes\n\n- {note}\n", body.trim_end());
    }
    meta.insert("updated".into(), json!(iso(None)));
    let mut entry = format!("- {} linked GitHub {}", iso(None), links.join(", "));
    if let Some(agent) = agent {
        entry.push_str(&format!(" by {agent}"));
    }
    body = format!("{}\n{entry}\n", body.trim_end());
    store::write_task(&path, &meta, &body)?;
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({"ok": true, "meta": meta, "task": task_id}))?
        );
    } else {
        println!(
            "Linked task {task_id} to GitHub: issue={}, pr={}",
            issue.unwrap_or("-"),
            pr.unwrap_or("-")
        );
    }
    Ok(0)
}

fn task_ready(ws: &Workspace, json: bool) -> Result<i32> {
    let (ready, waiting) = lifecycle::ready_and_waiting(ws);
    if json {
        let payload = json!({
            "ready": ready.iter().map(|task| task.slim_json()).collect::<Vec<_>>(),
            "waiting": waiting.iter().map(|(task, reasons)| json!({
                "task": task.slim_json(),
                "reasons": reasons,
            })).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }
    if ready.is_empty() {
        println!("No ready task.");
    } else {
        let rows: Vec<Vec<String>> = ready
            .iter()
            .map(|task| {
                vec![
                    task.id(),
                    task.priority().unwrap_or_else(|| "-".into()),
                    task.get_str("spec").unwrap_or_else(|| "-".into()),
                    task.title(),
                ]
            })
            .collect();
        for line in store::text_table(
            &[("ID", 6), ("PRIORITY", 10), ("SPEC", 28), ("TITLE", 0)],
            &rows,
        ) {
            println!("{line}");
        }
    }
    if !waiting.is_empty() {
        println!("\nWaiting:");
        for (task, reasons) in waiting {
            println!("  {} {}: {}", task.id(), task.title(), reasons.join("; "));
        }
    }
    Ok(0)
}

fn task_next(ws: &Workspace, agent: &str, review: bool, json: bool) -> Result<i32> {
    if review {
        return next_review(ws, agent, json);
    }
    let (ready, waiting) = lifecycle::ready_and_waiting(ws);
    for task in ready {
        match claim_one(ws, &task.path, agent, false) {
            Ok((true, message)) => {
                let path = match store::find_task(ws, &message) {
                    Some(path) => path,
                    None => {
                        eprintln!("Claimed {message}, but its task file disappeared.");
                        return Ok(1);
                    }
                };
                let (meta, body, _) = store::parse_task(&path)?;
                if json {
                    let mut payload = json!({"meta": meta, "body": body});
                    if let Some(worktree) = meta.get("worktree") {
                        payload["worktree"] = worktree.clone();
                        payload["cli"] = json!(gitflow::cli_command(ws));
                    }
                    println!("{}", serde_json::to_string_pretty(&payload)?);
                    return Ok(0);
                }
                println!("Task: {}", text_or(meta.get("title"), ""));
                if let Some(spec) = meta.get("spec").and_then(Value::as_str) {
                    println!("Spec: {spec}");
                }
                if let Some(worktree) = meta.get("worktree").and_then(Value::as_str) {
                    println!("Worktree: {worktree} (cd there; run the CLI by absolute path)");
                    println!("CLI: {}", gitflow::cli_command(ws));
                }
                println!("Read it: ai task show {message}");
                return Ok(0);
            }
            Ok((false, message)) => {
                eprintln!("Skipped {}: {message}", task.id());
            }
            Err(error) => return Err(error),
        }
    }
    if json {
        let payload = json!({
            "ready": [],
            "waiting": waiting.iter().map(|(task, reasons)| json!({
                "task": task.slim_json(),
                "reasons": reasons,
            })).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(1);
    }
    eprintln!("No ready task. Nothing was claimed.");
    for (task, reasons) in waiting {
        eprintln!("  {} {}: {}", task.id(), task.title(), reasons.join("; "));
    }
    Ok(1)
}

fn next_review(ws: &Workspace, agent: &str, json: bool) -> Result<i32> {
    let mut queue: Vec<Task> = store::load_tasks(ws)
        .into_iter()
        .filter(|task| {
            task.is_active()
                && lifecycle::review_is_claimable(ws, task)
                && task.get_str("submitted_by").as_deref() != Some(agent)
        })
        .collect();
    queue.sort_by_key(|task| task.id());
    for task in queue {
        match claim_one(ws, &task.path, agent, false) {
            Ok((true, message)) => {
                let path = match store::find_task(ws, &message) {
                    Some(path) => path,
                    None => {
                        eprintln!("Claimed {message}, but its task file disappeared.");
                        return Ok(1);
                    }
                };
                let (meta, _, _) = store::parse_task(&path)?;
                if json {
                    println!("{}", serde_json::to_string_pretty(&json!({"meta": meta}))?);
                    return Ok(0);
                }
                println!(
                    "Review: {} (submitted by {})",
                    text_or(meta.get("title"), ""),
                    text_or(meta.get("submitted_by"), "-")
                );
                if let Some(spec) = meta.get("spec").and_then(Value::as_str) {
                    println!("Spec: {spec}");
                }
                println!("History: ai history {message}");
                println!("Approve:  {}", approve_steps(ws, &message, agent));
                println!(
                    "Reject:   ai task request-changes {message} --agent {agent} --reason \"...\""
                );
                return Ok(0);
            }
            Ok((false, message)) => eprintln!("Skipped {}: {message}", task.id()),
            Err(error) => return Err(error),
        }
    }
    eprintln!("Nothing is waiting for review.");
    Ok(1)
}

fn task_claim(ws: &Workspace, task_id: &str, agent: &str, force: bool) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (ok, message) = claim_one(ws, &path, agent, force)?;
    if !ok {
        eprintln!("{message}");
        return Ok(1);
    }
    println!("Release without delivering: ai task release {message} --agent {agent}");
    Ok(0)
}

/// Claim a task and do the standard set-up: file locks, claim, task branch.
pub fn claim_one(ws: &Workspace, path: &Path, agent: &str, force: bool) -> Result<(bool, String)> {
    let (meta, _, _) = store::parse_task(path)?;
    let previous = meta
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("todo")
        .to_string();
    if previous != "review" {
        let task = Task {
            meta: meta.clone(),
            body: String::new(),
            path: path.to_path_buf(),
            folder: "active".into(),
        };
        let (ok, message) = lifecycle::acquire_task_locks(ws, &task, agent)?;
        if !ok {
            return Ok((false, message));
        }
    }
    let (ok, message) = lifecycle::claim_task(ws, path, agent, force)?;
    if !ok {
        if previous != "review" {
            lifecycle::release_task_locks(ws, &meta, Some(agent))?;
        }
        return Ok((false, message));
    }
    if previous != "review" && config::git_enabled(ws) {
        let state = git::state(ws);
        let cfg = git::config(ws);
        let repo = state.get("repo").and_then(Value::as_bool).unwrap_or(false);
        let head = state.get("head").and_then(Value::as_str).unwrap_or("");
        if !repo || head.is_empty() {
            println!(
                "  git: not initialized; run `ai git setup` once (or `ai setup --set git=no`)."
            );
        } else if !git::branch_exists(&ws.project, &cfg.integration) {
            println!(
                "  git: integration branch '{}' is missing; run `ai git setup` once, then `ai git start` for this task.",
                cfg.integration
            );
        } else {
            let started =
                gitflow::start_branch(ws, &message, agent, "feature", None, force, false)?;
            if started != 0 {
                let rolled = lifecycle::rollback_claim(
                    ws,
                    path,
                    agent,
                    Some(&previous),
                    "the task branch could not start",
                )?;
                if rolled.is_none() {
                    return Ok((
                        false,
                        format!(
                            "Task {message} changed while its branch was starting; inspect it with `ai task show {message}`."
                        ),
                    ));
                }
                return Ok((
                    false,
                    format!(
                        "Claim of {message} was rolled back: the task branch could not start. Fix the Git problem, then reclaim with `ai task claim {message} --agent {agent}`."
                    ),
                ));
            }
        }
    }
    println!("Claimed {message} for {agent}.");
    Ok((true, message))
}

fn task_release(ws: &Workspace, task_id: &str, agent: &str, force: bool) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (meta, _, _) = store::parse_task(&path)?;
    let id = text_or(meta.get("id"), task_id);
    let resource = format!("task-{id}");
    lifecycle::release_task_locks(ws, &meta, if force { None } else { Some(agent) })?;
    {
        let _guard = workspace_state_guard(ws)?;
        let current = match store::find_task(ws, &id) {
            Some(current) => current,
            None => {
                eprintln!("Task {id} changed before release.");
                return Ok(1);
            }
        };
        if current != path {
            eprintln!("Task {id} changed before release.");
            return Ok(1);
        }
        let (mut meta, body, _) = store::parse_task(&current)?;
        if meta.get("owner").and_then(Value::as_str).is_none()
            && meta.get("status").and_then(Value::as_str) == Some("review")
            && meta.get("submitted_by").and_then(Value::as_str) == Some(agent)
        {
            println!("Task {id} was already handed over by `ai task review`; nothing to release.");
            return Ok(0);
        }
        if let Some(owner) = meta.get("owner").and_then(Value::as_str) {
            if owner != agent && !force {
                eprintln!("Task {id} is owned by {owner}. Use --force to override.");
                return Ok(1);
            }
        }
        meta.insert("owner".into(), Value::Null);
        meta.insert("lock".into(), Value::Null);
        let previous = meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("todo")
            .to_string();
        if previous == "in_progress" {
            meta.insert("status".into(), json!("todo"));
        }
        meta.insert("updated".into(), json!(iso(None)));
        let new_status = meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("todo")
            .to_string();
        let body = history::append(
            &body,
            Some(agent),
            Some(&previous),
            &new_status,
            "released",
            "",
        );
        store::write_task(&current, &meta, &body)?;
        board::write_board(ws, &store::load_tasks(ws))?;
    }
    release_lock(ws, &resource, Some(agent), force, false)?;
    append_event(
        ws,
        "task_released",
        &[("task", json!(id)), ("agent", json!(agent))],
    );
    Ok(0)
}

fn auto_verify(ws: &Workspace, path: &Path, agent: &str) -> Result<Option<String>> {
    if !gates::check_required(ws) || config::configured_checks(ws).is_empty() {
        return Ok(None);
    }
    let (meta, _, _) = store::parse_task(path)?;
    if meta.get("owner").and_then(Value::as_str) != Some(agent)
        || meta.get("status").and_then(Value::as_str) != Some("in_progress")
    {
        return Ok(None);
    }
    let task_id = text_or(meta.get("id"), "");
    let task = match store::task_of(ws, &task_id) {
        Some(task) => task,
        None => return Ok(None),
    };
    let checkout = git::task_checkout(ws, &task);
    let head = git::state_at(&checkout)
        .get("head")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    let started = gates::claim_started(ws, &task_id);
    if evidence::task_green(ws, &task_id, head.as_deref(), started.as_deref()).0 {
        return Ok(None);
    }
    println!("Running the project checks for task {task_id} before review...");
    let mut results: Vec<Value> = Vec::new();
    let problems = crate::runtime::health::run_commands(ws, &checkout, false, &mut results, None)?;
    let ok = !problems.iter().any(|finding| finding.level == "error");
    evidence::record_task_check(
        ws,
        &task_id,
        Some(agent),
        ok,
        head.as_deref(),
        &results,
        false,
        true,
        false,
    )?;
    if !ok {
        return Ok(Some(format!(
            "Task {task_id} cannot enter review: the project checks failed. Fix them, then run `ai task review {task_id} --agent {agent}` again."
        )));
    }
    Ok(None)
}

fn approve_steps(ws: &Workspace, task_id: &str, who: &str) -> String {
    if config::git_enabled(ws) {
        format!("ai git finish --task {task_id} --agent {who}, then ai task done {task_id} --agent {who}")
    } else {
        format!("ai task done {task_id} --agent {who}   (Git is off: nothing to merge)")
    }
}

fn task_review(ws: &Workspace, task_id: &str, agent: &str) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) if path.parent() == Some(ws.active_dir().as_path()) => path,
        _ => {
            eprintln!("No active task with id {task_id}.");
            return Ok(1);
        }
    };
    let (current_meta, _, _) = store::parse_task(&path)?;
    let current_task = Task {
        meta: current_meta.clone(),
        body: String::new(),
        path: path.clone(),
        folder: "active".into(),
    };
    if let Some(error) = gates::review_git_gate(ws, &current_task, agent, false) {
        eprintln!("{error}");
        return Ok(1);
    }
    if let Some(error) = auto_verify(ws, &path, agent)? {
        eprintln!("{error}");
        return Ok(1);
    }
    let id = text_or(current_meta.get("id"), task_id);
    let _guard = workspace_state_guard(ws)?;
    let current = match store::find_task(ws, &id) {
        Some(current) => current,
        None => {
            eprintln!("Task {id} changed before it could be updated; retry.");
            return Ok(1);
        }
    };
    if current != path {
        eprintln!("Task {id} changed before it could be updated; retry.");
        return Ok(1);
    }
    let (mut meta, body, _) = store::parse_task(&current)?;
    if meta.get("status").and_then(Value::as_str) != Some("in_progress") {
        eprintln!("Task {id} must be in_progress to enter review.");
        return Ok(1);
    }
    if meta.get("owner").and_then(Value::as_str) != Some(agent) {
        eprintln!("Task {id} is not owned by {agent}.");
        return Ok(1);
    }
    let holder = effective_holder(ws, &format!("task-{id}"));
    if holder.get("agent").and_then(Value::as_str) != Some(agent) {
        eprintln!("Task {id} does not have a live claim for {agent}.");
        return Ok(1);
    }
    let warn_after = config::preference(ws, "handoff.warnAfterMinutes", json!(30))
        .as_i64()
        .unwrap_or(30) as f64;
    if let Some(error) = checkpoints::checkpoint_required(
        ws,
        &id,
        gates::claim_started(ws, &id).as_deref(),
        Some(warn_after),
    ) {
        eprintln!("{error}");
        return Ok(1);
    }
    if let Err(denied) = roles::authorize(ws, Some(agent), "task.review") {
        eprintln!("{denied}");
        return Ok(1);
    }
    if gates::workflow_config(ws).require_spec {
        let unticked = spec::spec_unticked(ws, &meta);
        if !unticked.is_empty() {
            let listed = unticked
                .iter()
                .map(|(number, content)| format!("{number}. {content}"))
                .collect::<Vec<_>>()
                .join("; ");
            eprintln!(
                "Task {id} cannot enter review: {} acceptance criteria are still unticked in {}: {listed}. Tick each one with `ai spec check {id} <n>` once the work makes it true.",
                unticked.len(),
                text_or(meta.get("spec"), "the spec")
            );
            return Ok(1);
        }
    }
    let task = Task {
        meta: meta.clone(),
        body: body.clone(),
        path: current.clone(),
        folder: "active".into(),
    };
    let (gate_error, proof) = gates::review_gate(ws, &task, agent)?;
    if let Some(error) = gate_error {
        eprintln!("{error}");
        return Ok(1);
    }
    if let Some(error) = gates::review_git_gate(ws, &task, agent, true) {
        eprintln!("{error}");
        return Ok(1);
    }
    meta.insert("status".into(), json!("review"));
    meta.insert("submitted_by".into(), json!(agent));
    meta.insert("owner".into(), Value::Null);
    meta.insert("lock".into(), Value::Null);
    meta.insert("updated".into(), json!(iso(None)));
    let new_body = history::append(
        &body,
        Some(agent),
        Some("in_progress"),
        "review",
        "submitted for independent review",
        &proof,
    );
    store::write_task(&current, &meta, &new_body)?;
    board::write_board(ws, &store::load_tasks(ws))?;
    drop(_guard);
    append_event(
        ws,
        "task_reviewed",
        &[("task", json!(id)), ("agent", json!(agent))],
    );
    lifecycle::release_task_locks(ws, &meta, Some(agent))?;
    release_lock(ws, &format!("task-{id}"), Some(agent), false, true)?;
    println!("Task {id} is delivered for independent review and handed over.");
    if gates::allows_self_review(ws) {
        println!(
            "Solo playbook: approve and ship it yourself: {} (re-read the diff first).",
            approve_steps(ws, &id, agent)
        );
    } else {
        println!("Reviewer next: {}", approve_steps(ws, &id, "<reviewer>"));
    }
    if !gates::workflow_config(ws).auto_continue {
        println!(
            "STOP: report what you delivered and wait for the user before starting another task."
        );
    }
    Ok(0)
}

fn task_request_changes(ws: &Workspace, task_id: &str, agent: &str, reason: &str) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) if path.parent() == Some(ws.active_dir().as_path()) => path,
        _ => {
            eprintln!("No active task with id {task_id}.");
            return Ok(1);
        }
    };
    if let Err(denied) = roles::authorize(ws, Some(agent), "task.request_changes") {
        eprintln!("{denied}");
        return Ok(1);
    }
    let meta = apply_transition(ws, task_id, &path, true, |meta, body| {
        let task = Task {
            meta: meta.clone(),
            body: body.to_string(),
            path: path.clone(),
            folder: "active".into(),
        };
        if let Some(error) =
            gates::request_changes_gate(&task, agent, gates::allows_self_review(ws))
        {
            return fail(error);
        }
        meta.insert("status".into(), json!("changes_requested"));
        meta.insert("changes_requested_by".into(), json!(agent));
        meta.insert("owner".into(), Value::Null);
        meta.insert("lock".into(), Value::Null);
        Ok(history::append(
            body,
            Some(agent),
            Some("review"),
            "changes_requested",
            reason,
            "",
        ))
    });
    let meta = match meta {
        Ok(meta) => meta,
        Err(error) => {
            eprintln!("{error}");
            return Ok(1);
        }
    };
    let id = text_or(meta.get("id"), task_id);
    release_lock(ws, &format!("task-{id}"), None, true, true)?;
    evidence::invalidate(ws, &id, &format!("changes requested by {agent}"))?;
    append_event(
        ws,
        "task_changes_requested",
        &[("task", json!(id)), ("agent", json!(agent))],
    );
    println!(
        "Task {id} sent back to its producer ({}): {reason}",
        text_or(meta.get("submitted_by"), "-")
    );
    println!("Producer next: ai task claim {id} --agent <producer>");
    Ok(0)
}

fn task_block(ws: &Workspace, task_id: &str, agent: &str, reason: &str) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (meta, _, _) = store::parse_task(&path)?;
    if let Some(owner) = meta.get("owner").and_then(Value::as_str) {
        if owner != agent {
            eprintln!(
                "Task {task_id} is owned by {owner}; only the owner (or the chief) may block it."
            );
            return Ok(1);
        }
    }
    let id = text_or(meta.get("id"), task_id);
    if meta.get("status").and_then(Value::as_str) == Some("blocked") {
        println!("Task {id} is already blocked.");
        return Ok(0);
    }
    if let Some(code) = require_active(ws, task_id, &path, "task block") {
        return Ok(code);
    }
    let result = apply_transition(ws, task_id, &path, false, |meta, body| {
        let previous = meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("todo")
            .to_string();
        meta.insert("blocked_from".into(), json!(previous));
        meta.insert("status".into(), json!("blocked"));
        if previous == "in_progress" {
            meta.insert("owner".into(), Value::Null);
            meta.insert("lock".into(), Value::Null);
        }
        Ok(history::append(
            body,
            Some(agent),
            Some(&previous),
            "blocked",
            reason,
            "",
        ))
    });
    let meta = match result {
        Ok(meta) => meta,
        Err(error) => {
            eprintln!("{error}");
            return Ok(1);
        }
    };
    if meta.get("blocked_from").and_then(Value::as_str) == Some("in_progress") {
        release_lock(ws, &format!("task-{id}"), None, true, true)?;
        // File leases taken for this task would otherwise linger for the whole
        // stale window and refuse other agents on those paths.
        lifecycle::release_task_locks(ws, &meta, None)?;
    }
    println!("Blocked {}: {reason}", text_or(meta.get("id"), task_id));
    Ok(0)
}

fn task_unblock(ws: &Workspace, task_id: &str, agent: &str) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    if let Some(code) = require_active(ws, task_id, &path, "task unblock") {
        return Ok(code);
    }
    let result = apply_transition(ws, task_id, &path, false, |meta, body| {
        let previous = meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("todo")
            .to_string();
        if previous != "blocked" {
            return fail(format!("Task {task_id} is {previous}, not blocked."));
        }
        let mut restore = text_or(meta.get("blocked_from"), "todo");
        if !matches!(restore.as_str(), "review" | "changes_requested") {
            restore = "todo".to_string();
        }
        meta.insert("status".into(), json!(restore));
        meta.remove("blocked_from");
        if restore == "todo" {
            meta.insert("owner".into(), Value::Null);
            meta.insert("lock".into(), Value::Null);
        }
        Ok(history::append(
            body,
            Some(agent),
            Some("blocked"),
            &restore,
            "unblocked",
            "",
        ))
    });
    match result {
        Ok(meta) => {
            println!(
                "Unblocked {} to {}.",
                text_or(meta.get("id"), task_id),
                text_or(meta.get("status"), "todo")
            );
            Ok(0)
        }
        Err(error) => {
            eprintln!("{error}");
            Ok(1)
        }
    }
}

fn task_done(ws: &Workspace, task_id: &str, agent: &str, force: bool) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    if path.parent() == Some(ws.done_dir().as_path()) {
        println!("Task is already done.");
        return Ok(0);
    }
    let (meta, _, _) = store::parse_task(&path)?;
    let id = text_or(meta.get("id"), task_id);
    let previous_spec = meta.get("spec").and_then(Value::as_str);
    let submitted_by = meta
        .get("submitted_by")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    let solo_self = gates::allows_self_review(ws) && submitted_by.as_deref() == Some(agent);
    if !force && !solo_self {
        if let Err(denied) = roles::authorize(ws, Some(agent), "task.done") {
            eprintln!("{denied}");
            return Ok(1);
        }
    }
    let task = Task {
        meta: meta.clone(),
        body: String::new(),
        path: path.clone(),
        folder: "active".into(),
    };
    if let Some(error) = gates::done_gate(ws, &task, agent, force) {
        eprintln!("{error}");
        return Ok(1);
    }
    if let Some(error) = gates::done_merge_gate(ws, &task, force) {
        eprintln!("{error}");
        return Ok(1);
    }
    let resource = format!("task-{id}");
    let holder = effective_holder(ws, &resource);
    if holder
        .get("corrupt")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        && !force
    {
        append_event(
            ws,
            "lock_refused",
            &[
                ("resource", json!(resource)),
                ("agent", json!(agent)),
                ("task", json!(id)),
            ],
        );
        eprintln!(
            "Task {id} has a corrupt task lock ({resource}), which cannot prove the task is free. Inspect it, then repair it with `ai lock release {resource} --force`."
        );
        return Ok(1);
    }
    if holder.get("agent").and_then(Value::as_str) != Some(agent) {
        let result = acquire_lock(ws, &resource, Some(agent), Some(&id), None, force)?;
        if !result.ok {
            let holder = result.holder.unwrap_or_else(|| json!({}));
            let error = result.error.unwrap_or_default();
            append_event(
                ws,
                "lock_refused",
                &[
                    ("resource", json!(resource)),
                    ("agent", json!(agent)),
                    ("task", json!(id)),
                    (
                        "conflict",
                        holder.get("resource").cloned().unwrap_or(Value::Null),
                    ),
                    (
                        "conflict_agent",
                        holder.get("agent").cloned().unwrap_or(Value::Null),
                    ),
                    ("error", json!(error)),
                ],
            );
            if !error.is_empty() {
                eprintln!("Cannot lock task {id}: {error}");
            } else {
                eprintln!(
                    "Task {id} is locked by {}.",
                    text_or(holder.get("agent"), "unknown")
                );
            }
            return Ok(1);
        }
    }
    let target = ws.done_dir().join(
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("task.md"),
    );
    if target.exists() {
        eprintln!(
            "Cannot archive task {id}: {} already exists. Rename one of the files, then rerun.",
            rel(ws, &target)
        );
        return Ok(1);
    }
    let require_review = gates::workflow_config(ws).require_review;
    let final_meta: Map<String, Value>;
    {
        let _guard = workspace_state_guard(ws)?;
        let current = match store::find_task(ws, &id) {
            Some(current) => current,
            None => {
                eprintln!("Task {id} changed before it could be updated; retry.");
                return Ok(1);
            }
        };
        if current != path {
            eprintln!("Task {id} changed before it could be updated; retry.");
            return Ok(1);
        }
        let (mut current_meta, body, _) = store::parse_task(&current)?;
        let status = current_meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if require_review && !matches!(status.as_str(), "review" | "done") && !force {
            eprintln!("Task {id} is no longer in review; retry.");
            return Ok(1);
        }
        current_meta.insert("status".into(), json!("done"));
        current_meta.insert("reviewed_by".into(), json!(agent));
        current_meta.insert("reviewed_at".into(), json!(iso(None)));
        current_meta.insert("lock".into(), Value::Null);
        let forced = if force
            && matches!(
                current_meta.get("submitted_by").and_then(Value::as_str),
                None | Some(_)
            ) {
            if current_meta.get("submitted_by").and_then(Value::as_str) == Some(agent)
                || current_meta
                    .get("submitted_by")
                    .and_then(Value::as_str)
                    .is_none()
            {
                "forced: review gate bypassed"
            } else {
                "approved"
            }
        } else {
            "approved"
        };
        let records = evidence::task_records(ws, &id);
        let proof = records.last().map(evidence::summary).unwrap_or_default();
        if let Some(archived) = spec::archive_spec(ws, &mut current_meta) {
            current_meta.insert("spec".into(), json!(archived));
        }
        let new_body = history::append(&body, Some(agent), Some(&status), "done", forced, &proof);
        store::write_task(&current, &current_meta, &new_body)?;
        std::fs::rename(&current, &target)?;
        board::write_board(ws, &store::load_tasks(ws))?;
        final_meta = current_meta;
    }
    release_lock(ws, &resource, None, true, true)?;
    lifecycle::release_task_locks(ws, &final_meta, None)?;
    let marker = checkpoints::handoff_marker(ws, &id);
    if marker.exists() {
        let _ = std::fs::remove_file(marker);
    }
    let board_path = ws.board_path();
    let mut ledger_paths: Vec<&Path> = vec![target.as_path(), path.as_path(), board_path.as_path()];
    let archived_spec = final_meta
        .get("spec")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    let mut spec_buf: Vec<std::path::PathBuf> = Vec::new();
    if let Some(spec) = archived_spec.as_deref() {
        if previous_spec != Some(spec) {
            spec_buf.push(
                ws.root
                    .join(spec.replace('/', std::path::MAIN_SEPARATOR_STR)),
            );
        }
    }
    if let Some(previous) = previous_spec {
        spec_buf.push(
            ws.root
                .join(previous.replace('/', std::path::MAIN_SEPARATOR_STR)),
        );
    }
    ledger_paths.extend(spec_buf.iter().map(|path| path.as_path()));
    commit_ledger(ws, &ledger_paths, &format!("chore(task): record done {id}"));
    append_event(
        ws,
        "task_done",
        &[
            ("task", json!(id)),
            ("agent", json!(agent)),
            ("forced", if force { json!(true) } else { Value::Null }),
            (
                "submitted_by",
                final_meta
                    .get("submitted_by")
                    .cloned()
                    .unwrap_or(Value::Null),
            ),
        ],
    );
    let _ = previous_spec;
    println!("Done: {}", rel(ws, &target));
    Ok(0)
}

fn restore_spec(ws: &Workspace, meta: &mut Map<String, Value>) -> Option<String> {
    let reference = meta.get("spec").and_then(Value::as_str)?.to_string();
    let path = ws.root.join(&reference);
    let done = std::fs::canonicalize(ws.specs_done_dir()).unwrap_or_else(|_| ws.specs_done_dir());
    let path = std::fs::canonicalize(&path).unwrap_or(path);
    if path.parent() != Some(done.as_path()) || !path.is_file() {
        return None;
    }
    let target = ws.specs_active_dir().join(path.file_name()?);
    if target.exists() {
        return None;
    }
    std::fs::create_dir_all(ws.specs_active_dir()).ok()?;
    std::fs::rename(&path, &target).ok()?;
    if let Ok(text) = read_text(&target) {
        let _ = crate::core::fsio::write_text_atomic(&target, &spec::mark_status(&text, "draft"));
    }
    Some(
        target
            .strip_prefix(&ws.root)
            .map(|rest| rest.to_string_lossy().replace('\\', "/"))
            .unwrap_or_else(|_| target.to_string_lossy().replace('\\', "/")),
    )
}

fn task_reopen(
    ws: &Workspace,
    task_id: &str,
    agent: &str,
    reason: Option<&str>,
    status: Option<&str>,
) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    if path.parent() != Some(ws.done_dir().as_path()) {
        eprintln!("Task {task_id} is not done; there is nothing to reopen.");
        return Ok(1);
    }
    if let Err(denied) = roles::authorize(ws, Some(agent), "task.reopen") {
        eprintln!("{denied}");
        return Ok(1);
    }
    // A free-form status would make the task disappear from every reader, so the
    // reopened state is a real status from the state machine.
    const REOPEN_STATUSES: &[&str] = &["review", "todo", "in_progress", "changes_requested"];
    let reopen_status = status.unwrap_or("review");
    if !REOPEN_STATUSES.contains(&reopen_status) {
        eprintln!(
            "Cannot reopen into '{reopen_status}'; use one of: {}.",
            REOPEN_STATUSES.join(", ")
        );
        return Ok(1);
    }
    let (mut meta, body, _) = store::parse_task(&path)?;
    let id = text_or(meta.get("id"), task_id);
    let target = ws.active_dir().join(
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("task.md"),
    );
    if target.exists() {
        eprintln!(
            "Cannot reopen task {id}: {} already exists.",
            rel(ws, &target)
        );
        return Ok(1);
    }
    let previous_spec = meta
        .get("spec")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    if let Some(restored) = restore_spec(ws, &mut meta) {
        meta.insert("spec".into(), json!(restored));
    } else if let Some(previous) = previous_spec {
        eprintln!("WARN  could not restore the spec {previous}; the task keeps its reference.");
    }
    meta.insert("status".into(), json!(reopen_status));
    meta.insert("reviewed_by".into(), Value::Null);
    meta.insert("reviewed_at".into(), Value::Null);
    meta.insert("merged_into".into(), Value::Null);
    meta.insert("merged_at".into(), Value::Null);
    meta.insert("updated".into(), json!(iso(None)));
    let new_status = text_or(meta.get("status"), "review");
    let new_body = history::append(
        &body,
        Some(agent),
        Some("done"),
        &new_status,
        "reopened",
        reason.unwrap_or(""),
    );
    {
        let _guard = workspace_state_guard(ws)?;
        store::write_task(&path, &meta, &new_body)?;
        std::fs::rename(&path, &target)?;
        board::write_board(ws, &store::load_tasks(ws))?;
    }
    commit_ledger(
        ws,
        &[target.as_path(), path.as_path(), ws.board_path().as_path()],
        &format!("chore(task): reopen {id}"),
    );
    append_event(
        ws,
        "task_reopened",
        &[
            ("task", json!(id)),
            ("agent", json!(agent)),
            ("reason", reason.map(|r| json!(r)).unwrap_or(Value::Null)),
        ],
    );
    println!("Reopened {id} to {new_status}: {}", rel(ws, &target));
    if let Some(branch) = meta.get("branch").and_then(Value::as_str) {
        println!(
            "Branch {branch} was left as it is; merge it with `ai git finish --task {id} --agent <reviewer>`."
        );
    }
    Ok(0)
}

fn task_discard(ws: &Workspace, task_id: &str) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (meta, _, _) = store::parse_task(&path)?;
    let id = match normalize_id(&text_or(meta.get("id"), task_id)) {
        Ok(id) => id,
        Err(_) => {
            eprintln!("Task file has an invalid id: {task_id}.");
            return Ok(1);
        }
    };
    let spec_path = spec::resolve_spec_path(ws, &meta);
    let mut targets: Vec<std::path::PathBuf> = vec![path.clone()];
    if let Some(spec_path) = spec_path {
        if spec_path.starts_with(ws.specs_dir()) {
            targets.push(spec_path);
        } else {
            eprintln!(
                "Cannot safely discard task: its spec is outside the workspace specs directory."
            );
            return Ok(1);
        }
    }
    targets.push(checkpoints::checkpoint_path(ws, &id));
    targets.push(checkpoints::checkpoint_sidecar(ws, &id));
    targets.push(checkpoints::handoff_marker(ws, &id));
    for lock in list_locks(ws, false) {
        if lock.get("resource").and_then(Value::as_str) == Some(&format!("task-{id}")) {
            let agent = text_or(lock.get("agent"), "unknown");
            if !leases::lock_is_stale(Some(&lock), config::lock_settings(ws).1) {
                eprintln!(
                    "Task {id} still has a lock held by {agent}. Release it first, or ask someone who can."
                );
                return Ok(1);
            }
        }
    }
    if !std::io::stdin().is_terminal() {
        eprintln!("Discard requires an interactive terminal; no files were changed.");
        return Ok(1);
    }
    println!(
        "This permanently discards task {id}: {}",
        text_or(meta.get("title"), "")
    );
    println!("It removes the task, its matching spec, and its continuation files.");
    let expected = format!("discard task {id}");
    print!("Type '{expected}' to continue: ");
    let _ = std::io::stdout().flush();
    let mut confirmation = String::new();
    let _ = std::io::stdin().read_line(&mut confirmation);
    if confirmation.trim() != expected {
        eprintln!("Confirmation did not match; no files were changed.");
        return Ok(1);
    }
    let _guard = workspace_state_guard(ws)?;
    let current = store::find_task(ws, &id);
    if current.as_deref() != Some(path.as_path()) {
        eprintln!("Task {id} changed while awaiting confirmation; retry.");
        return Ok(1);
    }
    let mut removed = 0usize;
    for target in &targets {
        if target.exists() {
            std::fs::remove_file(target)?;
            removed += 1;
        }
    }
    board::write_board(ws, &store::load_tasks(ws))?;
    println!("Discarded task {id}; removed {removed} file(s).");
    Ok(0)
}

/// Stage and commit only coordination paths (tasks, specs, board).
///
/// Delegates to `git::flow::commit_ledger`, which knows how to record a moved or
/// deleted task, so the two callers cannot drift apart.
pub fn commit_ledger(ws: &Workspace, paths: &[&Path], message: &str) {
    let owned: Vec<std::path::PathBuf> = paths.iter().map(|path| path.to_path_buf()).collect();
    let _ = gitflow::commit_ledger(ws, &owned, message);
}
