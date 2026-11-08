//! `ai review`: the whole read-only review package for one task.

use std::path::Path;

use serde_json::{json, Map, Value};

use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo as git;
use crate::runtime::evidence;
use crate::specs::spec as spec_lib;
use crate::tasks::history;
use crate::tasks::store;

use crate::ReviewArgs;

const DEFAULT_MAX_DIFF_LINES: usize = 400;

const CHECKLIST: &[&str] = &[
    "every acceptance criterion is met by the diff (cite the criterion, not a summary)",
    "no product change outside the task's scope_allowed / declared locks",
    "tests cover the new behavior; existing behavior the spec lists as preserved still holds",
    "the recorded check evidence is green on this exact HEAD",
    "the working tree is clean and the branch is the task's branch",
];

fn task_payload(ws: &Workspace, meta: &Map<String, Value>, path: &Path) -> Value {
    const KEYS: &[&str] = &[
        "id",
        "title",
        "status",
        "owner",
        "submitted_by",
        "reviewed_by",
        "priority",
        "spec",
        "branch",
        "worktree",
        "depends_on",
        "changes_requested_by",
        "scope_allowed",
        "scope_forbidden",
        "locks",
        "updated",
    ];
    let mut payload = Map::new();
    for key in KEYS {
        if let Some(value) = meta.get(*key) {
            if !value.is_null() {
                payload.insert((*key).to_string(), value.clone());
            }
        }
    }
    payload.insert("file".into(), json!(relative_to(&ws.project, path)));
    Value::Object(payload)
}

struct SpecPayload {
    path: Option<String>,
    criteria: Vec<String>,
    criteria_state: Vec<(bool, String)>,
    done: usize,
    total: usize,
    problem: Option<String>,
    body: Option<String>,
}

fn spec_payload(ws: &Workspace, meta: &Map<String, Value>) -> SpecPayload {
    let path = spec_lib::resolve_spec_path(ws, meta);
    let path = match path {
        Some(path) => path,
        None => {
            return SpecPayload {
                path: None,
                criteria: Vec::new(),
                criteria_state: Vec::new(),
                done: 0,
                total: 0,
                problem: Some("no spec is linked to this task".to_string()),
                body: None,
            }
        }
    };
    let text = match crate::core::fsio::read_text(&path) {
        Ok(text) => text,
        Err(error) => {
            return SpecPayload {
                path: Some(relative_to(&ws.project, &path)),
                criteria: Vec::new(),
                criteria_state: Vec::new(),
                done: 0,
                total: 0,
                problem: Some(format!("the spec cannot be read: {error}")),
                body: None,
            }
        }
    };
    let state = spec_lib::acceptance_criteria(&text);
    let (done, total) = spec_lib::criteria_progress(&state);
    SpecPayload {
        path: Some(relative_to(&ws.project, &path)),
        criteria: state.iter().map(|(_, item)| item.clone()).collect(),
        criteria_state: state,
        done,
        total,
        problem: spec_lib::spec_problem(ws, meta),
        body: Some(text),
    }
}

struct DiffPayload {
    base: Option<String>,
    stat: String,
    patch: String,
    lines: usize,
    truncated: bool,
    total_lines: usize,
    error: Option<String>,
}

fn diff_payload(
    ws: &Workspace,
    cwd: &Path,
    meta: &Map<String, Value>,
    integration: &str,
    max_lines: usize,
    stat_only: bool,
) -> DiffPayload {
    let mut payload = DiffPayload {
        base: None,
        stat: String::new(),
        patch: String::new(),
        lines: 0,
        truncated: false,
        total_lines: 0,
        error: None,
    };
    let branch = meta
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if branch.is_empty() {
        payload.error = Some("the task has no branch".to_string());
        return payload;
    }
    if !config::git_enabled(ws) {
        payload.error = Some("Git is disabled for this workspace".to_string());
        return payload;
    }
    if !git::branch_exists(cwd, &branch) {
        payload.error = Some(format!("branch {branch} does not exist in the checkout"));
        return payload;
    }
    let output = git::run_git(cwd, &["merge-base", integration, &branch]);
    if output.code != 0 || output.stdout.is_empty() {
        payload.error = Some(if output.stderr.is_empty() {
            format!("no merge base between {integration} and {branch}")
        } else {
            output.stderr
        });
        return payload;
    }
    let base = output.stdout.clone();
    payload.base = Some(base.clone());
    payload.stat = git::run_git(cwd, &["diff", "--stat", &format!("{base}..{branch}")]).stdout;
    if stat_only {
        return payload;
    }
    let patch = git::run_git(cwd, &["diff", &format!("{base}..{branch}")]).stdout;
    let mut lines: Vec<&str> = patch.lines().collect();
    payload.total_lines = lines.len();
    if max_lines > 0 && lines.len() > max_lines {
        payload.truncated = true;
        lines.truncate(max_lines);
    }
    payload.lines = lines.len();
    payload.patch = lines.join("\n");
    payload
}

fn evidence_lines(payload: &Value) -> Vec<String> {
    let state = payload
        .get("state")
        .and_then(Value::as_str)
        .unwrap_or("none");
    let mut lines = vec![format!("state: {state}")];
    if let Some(criteria) = payload.get("criteria") {
        let done = criteria.get("done").and_then(Value::as_u64).unwrap_or(0);
        let total = criteria.get("total").and_then(Value::as_u64).unwrap_or(0);
        if total > 0 {
            lines.push(format!("criteria: {done}/{total} ticked"));
            if done < total {
                lines.push(format!(
                    "  PROBLEM: {} acceptance criteria are still unticked",
                    total - done
                ));
            }
        }
    }
    if state == "none" {
        lines.push("  (no check was ever recorded for this task)".to_string());
        return lines;
    }
    if let Some(summary) = payload.get("summary").and_then(Value::as_str) {
        lines.push(format!("  {summary}"));
    }
    if state != "green" {
        if let Some(reason) = payload.get("reason").and_then(Value::as_str) {
            lines.push(format!("  PROBLEM: {reason}"));
        }
    }
    if payload.get("on_this_head").and_then(Value::as_bool) == Some(false) {
        let head = payload
            .get("head")
            .and_then(Value::as_str)
            .unwrap_or("no-git");
        let short = &head[..head.len().min(8)];
        lines.push(format!(
            "  PROBLEM: the evidence belongs to {short}, not to HEAD"
        ));
    }
    if let Some(checks) = payload.get("checks").and_then(Value::as_array) {
        for item in checks {
            let name = item.get("name").and_then(Value::as_str).unwrap_or("check");
            let code = item.get("exit_code").and_then(Value::as_i64);
            let verdict = if code == Some(0) {
                "ok".to_string()
            } else {
                format!("FAILED (exit {})", code.unwrap_or(-1))
            };
            let suffix = item
                .get("seconds")
                .and_then(Value::as_f64)
                .map(|seconds| format!(", {seconds}s"))
                .unwrap_or_default();
            lines.push(format!("  - {name}: {verdict}{suffix}"));
        }
    }
    lines
}

fn history_lines(body: &str) -> Vec<String> {
    let mut lines = Vec::new();
    for entry in history::parse(body) {
        if entry.kind == "note" {
            lines.push(format!("  note  {}", entry.text));
            continue;
        }
        let mut line = format!(
            "  {}  {:<12} {} -> {}",
            entry
                .at
                .as_deref()
                .map(|at| &at[..at.len().min(19)])
                .unwrap_or("-"),
            entry.actor.as_deref().unwrap_or("-"),
            entry.from.as_deref().unwrap_or("-"),
            entry.to.as_deref().unwrap_or("-")
        );
        if !entry.reason.is_empty() {
            line.push_str(&format!("  | {}", entry.reason));
        }
        if !entry.evidence.is_empty() {
            line.push_str(&format!("  | proof: {}", entry.evidence));
        }
        lines.push(line);
    }
    if lines.is_empty() {
        lines.push("  (no transitions recorded)".to_string());
    }
    lines
}

pub fn run(ws: &Workspace, args: &ReviewArgs) -> Result<i32> {
    let path = match store::find_task(ws, &args.task_id) {
        Some(path) => path,
        None => {
            eprintln!(
                "No task with id {}. `ai task list` shows the active ids; `ai task list --all` includes the archived ones.",
                args.task_id
            );
            return Ok(1);
        }
    };
    let (meta, body, _) = store::parse_task(&path)?;
    let task_id = meta
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or(&args.task_id)
        .to_string();
    let cfg = git::config(ws);
    let integration = cfg.integration.clone();
    let max_lines = args.max_lines.unwrap_or(DEFAULT_MAX_DIFF_LINES);

    let task_struct = store::Task {
        meta: meta.clone(),
        body: body.clone(),
        path: path.clone(),
        folder: "active".into(),
    };
    let cwd = git::task_root(ws, &task_struct).unwrap_or_else(|| ws.project.clone());
    let state = git::state_at(&cwd);
    let diff = diff_payload(ws, &cwd, &meta, &integration, max_lines, args.stat);
    let head = state.get("head").and_then(Value::as_str);
    let verdict = evidence::task_status(ws, &task_id, head, None);
    let record = verdict.get("record").cloned().unwrap_or_else(|| json!({}));
    let on_this_head = evidence::recorded_on(ws, &task_id, head);
    let spec = spec_payload(ws, &meta);
    let mut evidence_value = json!({
        "state": verdict.get("state").cloned().unwrap_or(Value::Null),
        "reason": verdict.get("reason").cloned().unwrap_or(Value::Null),
        "summary": verdict.get("summary").cloned().unwrap_or(Value::Null),
        "head": record.get("head").cloned().unwrap_or(Value::Null),
        "on_this_head": on_this_head,
        "at": record.get("at").cloned().unwrap_or(Value::Null),
        "agent": record.get("agent").cloned().unwrap_or(Value::Null),
        "checks": record.get("checks").cloned().unwrap_or_else(|| json!([])),
    });
    evidence_value["criteria"] = json!({"done": spec.done, "total": spec.total});
    let criteria_complete = spec.total > 0 && spec.done >= spec.total;
    let mut checklist: Vec<&str> = CHECKLIST.to_vec();
    checklist.push("claim it before approving: ai task next --review --agent <you>");
    let checklist_boxes: Vec<bool> = std::iter::once(criteria_complete)
        .chain(std::iter::repeat_n(false, checklist.len() - 1))
        .collect();

    let diff_value = json!({
        "base": diff.base,
        "stat": diff.stat,
        "patch": diff.patch,
        "lines": diff.lines,
        "truncated": diff.truncated,
        "total_lines": diff.total_lines,
        "error": diff.error,
    });
    let spec_value = json!({
        "path": spec.path,
        "criteria": spec.criteria,
        "criteria_state": spec.criteria_state.iter().map(|(done, item)| json!([done, item])).collect::<Vec<_>>(),
        "done": spec.done,
        "total": spec.total,
        "problem": spec.problem,
        "body": spec.body,
    });
    let payload = json!({
        "task": task_payload(ws, &meta, &path),
        "git": {
            "branch": state.get("branch").cloned().unwrap_or(Value::Null),
            "head": state.get("head").cloned().unwrap_or(Value::Null),
            "integration": integration,
            "dirty": state.get("dirty").cloned().unwrap_or_else(|| json!([])),
        },
        "spec": spec_value,
        "diff": diff_value,
        "evidence": evidence_value,
        "history": history::parse(&body).iter().map(history::LogEntry::to_json).collect::<Vec<_>>(),
        "checklist": checklist,
    });

    if args.json {
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(0);
    }

    let task = &payload["task"];
    let text = |value: &Value, key: &str| -> String {
        value
            .get(key)
            .and_then(Value::as_str)
            .unwrap_or("-")
            .to_string()
    };
    let mut out = vec![
        format!("=== REVIEW PACKAGE {task_id} ==="),
        format!("Task:     {}", text(task, "title")),
        {
            let mut line = format!("Status:   {}", text(task, "status"));
            if let Some(submitted) = task.get("submitted_by").and_then(Value::as_str) {
                line.push_str(&format!(" (submitted by {submitted})"));
            }
            if let Some(changed) = task.get("changes_requested_by").and_then(Value::as_str) {
                line.push_str(&format!(" (changes requested by {changed})"));
            }
            line
        },
        format!(
            "Owner:    {}",
            task.get("owner").and_then(Value::as_str).unwrap_or("-")
        ),
        format!(
            "Priority: {}",
            task.get("priority").and_then(Value::as_str).unwrap_or("-")
        ),
        {
            let mut line = format!(
                "Branch:   {}",
                task.get("branch").and_then(Value::as_str).unwrap_or("-")
            );
            if let Some(worktree) = task.get("worktree").and_then(Value::as_str) {
                line.push_str(&format!("  (worktree {worktree})"));
            }
            line
        },
        format!(
            "Spec:     {}",
            payload["spec"]
                .get("path")
                .and_then(Value::as_str)
                .unwrap_or("-")
        ),
        String::new(),
        {
            let mut line = "Acceptance criteria".to_string();
            if payload["spec"]
                .get("total")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                > 0
            {
                line.push_str(&format!(
                    "  {}/{} ticked",
                    payload["spec"]
                        .get("done")
                        .and_then(Value::as_u64)
                        .unwrap_or(0),
                    payload["spec"]
                        .get("total")
                        .and_then(Value::as_u64)
                        .unwrap_or(0)
                ));
            }
            line
        },
    ];
    if let Some(problem) = payload["spec"]
        .get("problem")
        .and_then(Value::as_str)
        .filter(|problem| !problem.is_empty())
    {
        out.push(format!("  PROBLEM: {problem}"));
    }
    if let Some(states) = payload["spec"]
        .get("criteria_state")
        .and_then(Value::as_array)
    {
        for entry in states {
            let done = entry.get(0).and_then(Value::as_bool).unwrap_or(false);
            let criterion = entry.get(1).and_then(Value::as_str).unwrap_or("");
            out.push(format!("  [{}] {criterion}", if done { 'x' } else { ' ' }));
        }
    } else if payload["spec"]
        .get("problem")
        .and_then(Value::as_str)
        .is_none()
    {
        out.push("  (the spec lists no criteria)".to_string());
    }
    out.push(String::new());

    out.push(format!(
        "Diff  {} vs {integration}",
        task.get("branch")
            .and_then(Value::as_str)
            .unwrap_or("(no branch)")
    ));
    if let Some(error) = payload["diff"].get("error").and_then(Value::as_str) {
        out.push(format!("  PROBLEM: {error}"));
    } else {
        let base = payload["diff"]
            .get("base")
            .and_then(Value::as_str)
            .unwrap_or("");
        let base = if base.is_empty() {
            "-"
        } else {
            &base[..base.len().min(8)]
        };
        out.push(format!("  base {base}"));
        let stat = payload["diff"]
            .get("stat")
            .and_then(Value::as_str)
            .filter(|stat| !stat.is_empty())
            .unwrap_or("(no changes)");
        for line in stat.lines() {
            out.push(format!("  {line}"));
        }
        if let Some(patch) = payload["diff"]
            .get("patch")
            .and_then(Value::as_str)
            .filter(|patch| !patch.is_empty())
        {
            out.push(String::new());
            for line in patch.lines() {
                out.push(line.to_string());
            }
        }
        if payload["diff"]
            .get("truncated")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            out.push(format!(
                "  [truncated: {} of {} lines; raise it with --max-lines {}]",
                payload["diff"]
                    .get("lines")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
                payload["diff"]
                    .get("total_lines")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
                payload["diff"]
                    .get("total_lines")
                    .and_then(Value::as_u64)
                    .unwrap_or(0)
            ));
        } else if args.stat {
            out.push("  (--stat: run without it for the full patch)".to_string());
        }
    }
    out.push(String::new());

    out.push("Evidence".to_string());
    out.extend(evidence_lines(&evidence_value));
    out.push(String::new());

    out.push("History".to_string());
    out.extend(history_lines(&body));
    out.push(String::new());

    out.push("Checklist".to_string());
    for (case, item) in checklist_boxes.iter().zip(checklist.iter()) {
        out.push(format!("  [{}] {item}", if *case { 'x' } else { ' ' }));
    }
    out.push(String::new());
    out.push("=== END REVIEW PACKAGE ===".to_string());
    println!("{}", out.join("\n"));
    Ok(0)
}
