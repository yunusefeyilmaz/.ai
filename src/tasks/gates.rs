//! The required transitions of the task state machine.
//!
//! ```text
//! todo --claim--> in_progress --review--> review --done--> done
//!                      ^  |                 |  ^
//!                      |  +---block-------> blocked --unblock--> todo
//!                      |                    |
//!                      +----claim-------- changes_requested <--request-changes
//! ```
//!
//! Rules enforced here (not left to prose):
//! * `review` needs the owner, a live claim and, when configured, green evidence
//!   recorded for this task on the current HEAD.
//! * `request-changes` is only for a task in review and never by its submitter.
//! * `done` needs `review` and an approver different from the submitter.
//! * `--force` is the operator escape hatch.

use serde_json::Value;

use crate::config::preferences;
use crate::config::settings::{configured_checks, git_enabled, load, preference};
use crate::core::error::Result;
use crate::core::fsio::lock_path;
use crate::core::workspace::Workspace;
use crate::git::repo as git;
use crate::runtime::evidence;
use crate::runtime::leases::read_holder;
use crate::specs::spec;
use crate::tasks::store::Task;

#[derive(Clone, Debug)]
pub struct WorkflowConfig {
    pub mode: String,
    pub require_review: bool,
    pub require_check: Value,
    pub auto_continue: bool,
    pub chief_only_tasks: bool,
    pub require_spec: bool,
}

pub fn workflow_config(ws: &Workspace) -> WorkflowConfig {
    let config = load(ws).unwrap_or_else(|_| crate::config::settings::default_config(ws));
    let flow = config.get("workflow").cloned().unwrap_or(Value::Null);
    WorkflowConfig {
        mode: config
            .get("mode")
            .and_then(Value::as_str)
            .unwrap_or("lite")
            .to_string(),
        require_review: flow
            .get("requireReview")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        require_check: flow
            .get("requireCheck")
            .cloned()
            .unwrap_or(Value::String("strict".into())),
        auto_continue: flow
            .get("autoContinue")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        chief_only_tasks: flow
            .get("chiefOnlyTasks")
            .and_then(Value::as_bool)
            .unwrap_or(true),
        require_spec: flow
            .get("requireSpec")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    }
}

/// Only the chief creates tasks, and only after the user chose the workflow.
pub fn creation_gate(ws: &Workspace, role: Option<&str>) -> Option<String> {
    if !workflow_config(ws).chief_only_tasks {
        return None;
    }
    let role = role
        .map(ToString::to_string)
        .or_else(|| std::env::var("AI_ROLE").ok());
    if !matches!(role.as_deref(), Some("chief" | "orchestrator" | "planner")) {
        return Some(
            "Only the chief creates tasks. If the user asked you to plan or build something and there are no tasks yet, you are the chief: run `ai now --agent <name> --role chief` and follow it. Implementers claim existing tasks (`ai task next`); they never create them."
                .to_string(),
        );
    }
    let confirmed = preferences::status(ws)
        .map(|s| s.confirmed)
        .unwrap_or(false);
    if !confirmed {
        return Some(
            "Ask the user how much process they want before planning: run `ai setup`, ask them the questions (review, checks, git, tests, continue, workers) and store the answers with `ai setup --set ...`."
                .to_string(),
        );
    }
    None
}

/// No spec, no code.
pub fn spec_gate(ws: &Workspace, task: &Task) -> Option<String> {
    if !workflow_config(ws).require_spec {
        return None;
    }
    let problem = spec::spec_problem(ws, &task.meta)?;
    Some(format!(
        "Task {} cannot be claimed: {problem}. The chief fills the spec (intent, behavior, acceptance criteria) before any worker starts. Ask the chief, or write the criteria yourself only if the user told you to.",
        task.id()
    ))
}

pub fn check_required(ws: &Workspace) -> bool {
    let flow = workflow_config(ws);
    match flow.require_check {
        Value::String(text) if text == "strict" => flow.mode == "strict",
        Value::Bool(flag) => flag,
        _ => false,
    }
}

pub fn claim_started(ws: &Workspace, task_id: &str) -> Option<String> {
    let path = lock_path(&ws.locks_dir(), &format!("task-{task_id}"));
    let holder = read_holder(&path)?;
    holder
        .get("started_at")
        .and_then(Value::as_str)
        .map(ToString::to_string)
}

/// Return (error, evidence_text) for a task entering review.
pub fn review_gate(ws: &Workspace, task: &Task, _agent: &str) -> Result<(Option<String>, String)> {
    let task_id = task.id();
    if check_required(ws) && configured_checks(ws).is_empty() {
        return Ok((
            Some(format!(
                "Task {task_id} cannot enter review: verification is required but no project checks are configured. Add them: `ai setup --check \"tests=<command>\"` (or choose `ai setup --set checks=no` if the user declines verification)."
            )),
            String::new(),
        ));
    }
    let head = git::state(ws)
        .get("head")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    let (ok, text) = evidence::task_green(
        ws,
        &task_id,
        head.as_deref(),
        claim_started(ws, &task_id).as_deref(),
    );
    if check_required(ws) && !ok {
        return Ok((
            Some(format!(
                "Task {task_id} cannot enter review: {text}. Run `ai check --task {task_id} --agent {_agent}` and fix what it reports first."
            )),
            String::new(),
        ));
    }
    Ok((None, if ok { text } else { String::new() }))
}

/// Refuse review while the task checkout is not the one that will be merged.
pub fn review_git_gate(
    ws: &Workspace,
    task: &Task,
    agent: &str,
    include_evidence: bool,
) -> Option<String> {
    if !git_enabled(ws) {
        return None;
    }
    let task_id = task.id();
    let branch = task.get_str("branch").unwrap_or_default();
    // A task with an isolated worktree is reviewed inside that checkout: the
    // main checkout is on the integration branch by design.
    let cwd = git::task_root(ws, task);
    let state = match &cwd {
        Some(root) => git::state_at(root),
        None => git::state(ws),
    };
    if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
        return None;
    }
    if branch.is_empty() {
        return Some(format!(
            "Task {task_id} has no branch. Start one with `ai git start --task {task_id} --agent {agent}` before review."
        ));
    }
    let current = state.get("branch").and_then(Value::as_str).unwrap_or("");
    if current != branch {
        return Some(format!(
            "Task {task_id} belongs to branch {branch}, but the checkout is on {current}. Switch back with `git checkout {branch}`, then retry `ai task review {task_id} --agent {agent}`."
        ));
    }
    let head = state.get("head").and_then(Value::as_str).unwrap_or("");
    if head.is_empty() {
        return Some(format!(
            "Task {task_id} has no commit on {branch}. Commit the work with `ai git commit --task {task_id} --agent {agent} ...` before review."
        ));
    }
    let dirty: Vec<String> = state
        .get("dirty")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .filter(|path| !git::is_workspace_ledger_path(ws, path))
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default();
    if !dirty.is_empty() {
        let listed = dirty.iter().take(5).cloned().collect::<Vec<_>>().join(", ");
        let suffix = if dirty.len() > 5 { " ..." } else { "" };
        return Some(format!(
            "Task {task_id} has uncommitted product changes ({listed}{suffix}). Commit them with `ai git commit --task {task_id} --agent {agent} ...` before review."
        ));
    }
    if include_evidence {
        if let Some(latest) = evidence::task_records(ws, &task_id).last() {
            if !latest
                .get("invalidated")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                let recorded = latest.get("head").and_then(Value::as_str).unwrap_or("");
                if !recorded.is_empty() && recorded != head {
                    return Some(format!(
                        "Task {task_id}: verification evidence belongs to {} but HEAD is {}. Re-run `ai check --task {task_id} --agent {agent}` on the current commit before review.",
                        &recorded[..recorded.len().min(8)],
                        &head[..head.len().min(8)]
                    ));
                }
            }
        }
    }
    None
}

pub fn request_changes_gate(task: &Task, agent: &str) -> Option<String> {
    let task_id = task.id();
    if task.status() != "review" {
        return Some(format!(
            "Task {task_id} is '{}'; changes can only be requested while it is in review.",
            task.status()
        ));
    }
    if task.get_str("submitted_by").as_deref() == Some(agent) {
        return Some(format!(
            "Task {task_id} was submitted by {agent}; an independent agent must request changes."
        ));
    }
    match task.owner() {
        Some(owner) if owner != agent => Some(format!(
            "Task {task_id} is claimed for review by {owner}; only the reviewer holding the claim may request changes. {owner} can send it back, or release it first with `ai task release {task_id} --agent {owner}`."
        )),
        None => Some(format!(
            "Task {task_id} is in review without a reviewer claim. Claim it first with `ai task next --review --agent {agent}` (or `ai task claim {task_id} --agent {agent}`), then request changes."
        )),
        _ => None,
    }
}

/// Return an error message when `agent` may not mark the task done.
pub fn done_gate(ws: &Workspace, task: &Task, agent: &str, force: bool) -> Option<String> {
    if force || !workflow_config(ws).require_review {
        return None;
    }
    let task_id = task.id();
    if task.status() != "review" {
        return Some(format!(
            "Task {task_id} is '{}', not in review. Submit it first: `ai task review {task_id} --agent <producer>`; a different agent then merges and marks it done.",
            task.status()
        ));
    }
    if task.get_str("submitted_by").as_deref() == Some(agent) {
        return Some(format!(
            "Task {task_id} was submitted by {agent}; the producer never approves its own work. A different agent must run `ai task done`."
        ));
    }
    None
}

/// Refuse to archive a task whose branch never landed on the integration branch.
pub fn done_merge_gate(ws: &Workspace, task: &Task, force: bool) -> Option<String> {
    if force || !git_enabled(ws) {
        return None;
    }
    let branch = task.get_str("branch").unwrap_or_default();
    if branch.is_empty() {
        return None;
    }
    let integration = preference(ws, "git.integrationBranch", Value::String("develop".into()))
        .as_str()
        .unwrap_or("develop")
        .to_string();
    if !git::branch_exists(&ws.project, &integration) {
        return None;
    }
    let task_id = task.id();
    if git::branch_merged(&ws.project, &branch, &integration) {
        return None;
    }
    if !git::branch_exists(&ws.project, &branch) {
        return Some(format!(
            "Task {task_id}: branch '{branch}' no longer exists and there is no verifiable merge into {integration}. Run `ai git finish --task {task_id} --agent <reviewer>` before marking it done, or --force if it really was merged and deleted by hand."
        ));
    }
    Some(format!(
        "Task {task_id} is not merged into {integration}: branch '{branch}' is not an ancestor of {integration}. Run `ai git finish --task {task_id} --agent <reviewer>` first; the ledger must not say done before the merge."
    ))
}
