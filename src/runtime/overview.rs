//! One compact, token-cheap picture of the whole workspace.

use serde_json::{json, Value};

use crate::config::preferences;
use crate::config::roles;
use crate::config::settings::{self as config, configured_checks, git_enabled, lock_settings};
use crate::core::workspace::Workspace;
use crate::decisions::adr as decisions;
use crate::git::repo as git;
use crate::runtime::checkpoints;
use crate::runtime::events::read_events;
use crate::runtime::evidence;
use crate::runtime::leases::{list_locks, lock_is_stale};
use crate::tasks::gates;
use crate::tasks::lifecycle;
use crate::tasks::store::{self, Task};

pub fn resolve_role(ws: &Workspace, agent: Option<&str>, explicit: Option<&str>) -> Option<String> {
    if let Some(explicit) = explicit {
        return Some(
            match explicit {
                "orchestrator" | "planner" => "chief",
                "qa" => "reviewer",
                other => other,
            }
            .to_string(),
        );
    }
    let agent = agent?;
    let config = config::load_or_default(ws);
    let assigned = roles::roles_of(agent, &config)?;
    for (names, role) in [
        (vec!["orchestrator", "planner"], "chief"),
        (vec!["reviewer", "qa"], "reviewer"),
        (vec!["implementer"], "implementer"),
    ] {
        if names
            .iter()
            .any(|name| assigned.iter().any(|value| value == name))
        {
            return Some(role.to_string());
        }
    }
    None
}

fn line_of(task: &Task) -> String {
    format!(
        "{} [{}] {}",
        task.id(),
        task.priority().unwrap_or_else(|| "-".into()),
        task.title()
    )
}

fn argv(command: Option<&str>) -> Vec<String> {
    let command = match command {
        Some(command) if !command.is_empty() => command,
        _ => return Vec::new(),
    };
    let tokens: Vec<String> = command
        .split_whitespace()
        .map(ToString::to_string)
        .collect();
    if tokens.first().map(String::as_str) == Some("ai") {
        tokens.into_iter().skip(1).collect()
    } else {
        tokens
    }
}

fn human_question(recommended: &Value) -> Option<String> {
    let command = recommended.get("cmd").and_then(Value::as_str).unwrap_or("");
    let why = recommended.get("why").and_then(Value::as_str).unwrap_or("");
    if command == "ai setup" {
        return Some("Before planning: how much process do you want for this project (independent review, checks required, Git, tests, auto-continue, number of workers)?".to_string());
    }
    if command.is_empty() {
        return Some(if why.is_empty() {
            "nothing can proceed without a decision from the user".to_string()
        } else {
            why.to_string()
        });
    }
    None
}

fn contract(recommended: &mut Value) {
    let question = human_question(recommended);
    let command = recommended
        .get("cmd")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    if let Some(object) = recommended.as_object_mut() {
        object.insert("next_args".into(), json!(argv(command.as_deref())));
        object.insert("needs_human".into(), json!(question.is_some()));
        object.insert("question".into(), json!(question));
        object.insert(
            "blocker".into(),
            match &question {
                Some(question) => json!(question),
                None => Value::Null,
            },
        );
    }
}

fn answer_text(value: &Value) -> String {
    match value {
        Value::Bool(true) => "yes".to_string(),
        Value::Bool(false) => "no".to_string(),
        other => other.to_string().trim_matches('"').to_string(),
    }
}

fn setup_extras(state: &preferences::PreferenceStatus) -> Vec<String> {
    let pending: Vec<&preferences::QuestionStatus> =
        state.questions.iter().filter(|row| !row.answered).collect();
    if pending.is_empty() {
        return Vec::new();
    }
    let asks = pending
        .iter()
        .map(|row| format!("{} ({})", row.key, answer_text(&row.recommended)))
        .collect::<Vec<_>>()
        .join(", ");
    let answers = state
        .questions
        .iter()
        .map(|row| format!("{}={}", row.key, answer_text(&row.recommended)))
        .collect::<Vec<_>>()
        .join(" ");
    let mut command = format!("then: ai setup --set {answers}");
    if state.checks.is_empty() {
        command.push_str(" --check \"tests=<command>\"");
    }
    vec![format!("ask the user: {asks}"), command]
}

fn task_state(ws: &Workspace, task: &Task) -> Value {
    match git::task_root(ws, task) {
        Some(root) => {
            let mut state = git::state_at(&root);
            let integration = git::config(ws).integration;
            let ahead = git::commits_ahead(&root, &integration);
            state["ahead"] = json!(ahead);
            state
        }
        None => git::state(ws),
    }
}

/// `{"cmd","why","extra"}` for one task's current state.
pub fn next_action(
    ws: &Workspace,
    task: &Task,
    agent: Option<&str>,
    git_state: &Value,
    git_ready: bool,
    git_on: bool,
) -> Value {
    let task_id = task.id();
    let status = task.status();
    let a = agent.unwrap_or("<n>");
    let mut extra: Vec<String> = Vec::new();
    if status == "done" {
        return json!({"cmd": null, "why": "task is done", "extra": extra});
    }
    if status == "blocked" {
        return json!({"cmd": format!("ai task unblock {task_id} --agent {a}"), "why": "blocked; unblock when the cause is gone", "extra": extra});
    }
    if status == "changes_requested" {
        return json!({
            "cmd": format!("ai task claim {task_id} --agent {a}"),
            "why": format!("{} sent it back: read `ai history {}`, fix, then re-review", task.get_str("changes_requested_by").unwrap_or_else(|| "the reviewer".into()), task_id),
            "extra": extra,
        });
    }
    if status == "todo" {
        let why = match task.owner() {
            Some(owner) => format!("leased by {owner}"),
            None => "claim before touching anything".to_string(),
        };
        return json!({"cmd": format!("ai task claim {task_id} --agent {a}"), "why": why, "extra": extra});
    }
    if status == "review" {
        let submitter = task.get_str("submitted_by");
        if let (Some(agent), Some(submitter)) = (agent, submitter.as_deref()) {
            if agent == submitter {
                return json!({
                    "cmd": null,
                    "why": "you delivered it; a different agent must review. Start a reviewer session (`ai now --agent <reviewer> --role reviewer`), or a solo user can disable the gate with `ai setup --set review=no`. Report to the user and wait",
                    "extra": extra,
                });
            }
        }
        if !git_on {
            return json!({
                "cmd": format!("ai task done {task_id} --agent {a}"),
                "why": format!("independent review (producer: {}); Git is off, so approving is just `done`. Or `ai task request-changes`", submitter.as_deref().unwrap_or("?")),
                "extra": extra,
            });
        }
        return json!({
            "cmd": format!("ai git finish --task {task_id} --agent {a}"),
            "why": format!("independent review (producer: {}): read spec + diff, then merge; afterwards `ai task done {task_id} --agent {a}`", submitter.as_deref().unwrap_or("?")),
            "extra": extra,
        });
    }
    // in_progress
    if git_on && !git_ready {
        return json!({"cmd": "ai git setup", "why": "Gitflow base is missing (skip only if the user said no Git)", "extra": extra});
    }
    let branch = task.get_str("branch");
    if git_on
        && branch
            .as_deref()
            .map(|value| git_state.get("branch").and_then(Value::as_str) != Some(value))
            .unwrap_or(true)
    {
        return json!({
            "cmd": format!("ai git start --task {task_id} --agent {a} --type feature"),
            "why": "work on the task branch, never on develop/master",
            "extra": extra,
        });
    }
    let warn_after = config::preference(ws, "handoff.warnAfterMinutes", json!(30))
        .as_f64()
        .unwrap_or(30.0);
    if let Some(missing) = checkpoints::checkpoint_required(
        ws,
        &task_id,
        gates::claim_started(ws, &task_id).as_deref(),
        Some(warn_after),
    ) {
        let _ = missing;
        extra.push(format!(
            "ai checkpoint {task_id} --agent {a} --next \"<step>\"   # required before review"
        ));
    }
    let dirty: Vec<String> = if !git_on {
        Vec::new()
    } else {
        git_state
            .get("dirty")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .filter(|path| {
                        !git::is_workspace_ledger_path(ws, path) && !path.starts_with(".ai/")
                    })
                    .map(ToString::to_string)
                    .collect()
            })
            .unwrap_or_default()
    };
    if !dirty.is_empty() {
        return json!({
            "cmd": "ai git verify --strict",
            "why": format!("{} uncommitted product path(s); stage your owned paths, verify, then `ai git commit --task {task_id} --agent {a} --type feat --message \"<subject>\"`", dirty.len()),
            "extra": extra,
        });
    }
    if git_on && git_state.get("ahead").and_then(Value::as_i64) == Some(0) {
        return json!({
            "cmd": format!("ai task show {task_id}"),
            "why": "nothing is committed yet: read the spec, do the work, checkpoint, then `ai git commit` (checks come at the end)",
            "extra": extra,
        });
    }
    if gates::check_required(ws) {
        if configured_checks(ws).is_empty() {
            return json!({"cmd": "ai setup --check \"tests=<command>\"", "why": "verification is required but no project checks are configured", "extra": extra});
        }
        let head = git_state.get("head").and_then(Value::as_str);
        let (ok, reason) = evidence::task_green(ws, &task_id, head, None);
        if !ok {
            return json!({
                "cmd": format!("ai check --task {task_id} --agent {a}"),
                "why": format!("review needs fresh evidence ({reason})"),
                "extra": extra,
            });
        }
    }
    json!({
        "cmd": format!("ai task review {task_id} --agent {a}"),
        "why": "work is committed and checked; submit for independent review",
        "extra": extra,
    })
}

pub fn build(ws: &Workspace, agent: Option<&str>, history: usize, role_arg: Option<&str>) -> Value {
    let config = config::load_or_default(ws);
    let tasks = store::load_tasks(ws);
    let active: Vec<&Task> = tasks.iter().filter(|task| task.is_active()).collect();
    let done: Vec<&Task> = tasks.iter().filter(|task| task.folder == "done").collect();
    let state = git::state(ws);
    let branches = git::config(ws);
    let integration_exists = git::branch_exists(&ws.project, &branches.integration);
    let production_exists = git::branch_exists(&ws.project, &branches.production);
    let git_ready = state.get("repo").and_then(Value::as_bool).unwrap_or(false)
        && state.get("head").and_then(Value::as_str).is_some()
        && integration_exists
        && production_exists;
    let (_, stale_after) = lock_settings(ws);
    let locks: Vec<Value> = list_locks(ws, false)
        .into_iter()
        .filter(|lock| !lock_is_stale(Some(lock), stale_after))
        .collect();

    let mine: Vec<&Task> = active
        .iter()
        .copied()
        .filter(|task| {
            agent == task.owner().as_deref()
                && matches!(task.status().as_str(), "in_progress" | "review")
        })
        .collect();
    let (ready_all, waiting_all) = lifecycle::ready_and_waiting(ws);
    let review_queue: Vec<&Task> = active
        .iter()
        .copied()
        .filter(|task| {
            task.status() == "review"
                && task.owner().is_none()
                && (agent.is_none() || task.get_str("submitted_by").as_deref() != agent)
        })
        .collect();
    let others: Vec<&Task> = active
        .iter()
        .copied()
        .filter(|task| task.status() == "in_progress" && task.owner().as_deref() != agent)
        .collect();
    let blocked: Vec<&Task> = active
        .iter()
        .copied()
        .filter(|task| task.status() == "blocked")
        .collect();
    let handoffs = checkpoints::list_handoff_markers(ws, false);

    let git_on = git_enabled(ws);
    let role = resolve_role(ws, agent, role_arg);
    let preference_state = preferences::status(ws).ok();
    let confirmed = preference_state
        .as_ref()
        .map(|state| state.confirmed)
        .unwrap_or(false);
    let autocontinue = config
        .get("workflow")
        .and_then(|flow| flow.get("autoContinue"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let delivered: Vec<&Task> = active
        .iter()
        .copied()
        .filter(|task| {
            agent.is_some()
                && task.status() == "review"
                && task.get_str("submitted_by").as_deref() == agent
        })
        .collect();
    let rework: Vec<&Task> = ready_all
        .iter()
        .filter(|task| {
            agent.is_some()
                && task.status() == "changes_requested"
                && task.get_str("submitted_by").as_deref() == agent
        })
        .collect();
    let who = agent.unwrap_or("<n>");
    let nothing = json!({"task": null, "cmd": null, "extra": []});

    let mut recommended = if let Some(task) = mine
        .iter()
        .max_by_key(|task| task.get_str("updated").unwrap_or_default())
    {
        let state_for_task = task_state(ws, task);
        let mut rec = next_action(ws, task, agent, &state_for_task, git_ready, git_on);
        if let Some(object) = rec.as_object_mut() {
            object.insert("task".into(), json!(task.id()));
        }
        if let Some(root) = git::task_root(ws, task) {
            let extras = rec
                .as_object_mut()
                .and_then(|object| object.get_mut("extra"))
                .and_then(Value::as_array_mut);
            if let Some(extras) = extras {
                extras.insert(
                    0,
                    json!(format!(
                        "cd {}   # your isolated worktree; edit files only there",
                        root.to_string_lossy()
                    )),
                );
            }
        }
        rec
    } else if !handoffs.is_empty() && role.as_deref() != Some("chief") {
        let handoff = &handoffs[0];
        json!({
            "task": handoff.get("task"),
            "cmd": format!("ai resume {}", handoff.get("task").and_then(Value::as_str).unwrap_or("-")),
            "why": format!(
                "handoff from {}: {}",
                handoff.get("agent").and_then(Value::as_str).unwrap_or("-"),
                handoff.get("reason").and_then(Value::as_str).unwrap_or("-")
            ),
            "extra": [],
        })
    } else if active.is_empty() && done.is_empty() && !confirmed {
        let mut rec = nothing.clone();
        rec["cmd"] = json!("ai setup");
        rec["extra"] = json!(preference_state
            .as_ref()
            .map(setup_extras)
            .unwrap_or_default());
        rec["why"] = json!("new project: ask the user which workflow features to use (review, checks, git, tests), then store the answers");
        rec
    } else if role.as_deref() == Some("chief")
        || (role.is_none() && active.is_empty() && done.is_empty())
    {
        if !confirmed {
            let mut rec = nothing.clone();
            rec["cmd"] = json!("ai setup");
            rec["extra"] = json!(preference_state
                .as_ref()
                .map(setup_extras)
                .unwrap_or_default());
            rec["why"] =
                json!("ask the user the setup questions first; answers are stored in config");
            rec
        } else if active.is_empty() {
            let mut rec = nothing.clone();
            rec["cmd"] = json!("ai plan apply plan.json");
            rec["why"] = json!("no tasks yet: split the request into linked tasks (see `ai plan example`), then fill each spec");
            rec
        } else {
            let mut rec = nothing.clone();
            rec["cmd"] = json!("ai status --board");
            rec["why"] = json!("the plan is in place; workers claim tasks themselves. Watch progress, unblock, answer questions");
            rec
        }
    } else if role.as_deref() == Some("reviewer") {
        if let Some(task) = review_queue.first() {
            json!({
                "task": task.id(),
                "cmd": format!("ai task next --review --agent {who}"),
                "why": format!("{} task(s) wait for independent review; this claims the oldest", review_queue.len()),
                "extra": [],
            })
        } else {
            let mut rec = nothing.clone();
            rec["why"] = json!("nothing is waiting for review; tell the user and stop");
            rec
        }
    } else if let Some(task) = rework.first() {
        let task_state = task_state(ws, task);
        let mut rec = next_action(ws, task, agent, &task_state, git_ready, git_on);
        if let Some(object) = rec.as_object_mut() {
            object.insert("task".into(), json!(task.id()));
        }
        rec
    } else if !delivered.is_empty() && !autocontinue {
        let ids = delivered
            .iter()
            .map(|task| task.id())
            .collect::<Vec<_>>()
            .join(", ");
        let mut rec = nothing.clone();
        rec["why"] = json!(format!(
            "you delivered {ids}; report it and wait for the user's go-ahead (then: ai task next --agent {who})"
        ));
        rec
    } else if let Some(task) = ready_all.first() {
        json!({
            "task": task.id(),
            "cmd": format!("ai task next --agent {who}"),
            "why": format!("claims the highest-priority ready task ({}) and sets everything up", line_of(task)),
            "extra": [],
        })
    } else if role.is_none() && !review_queue.is_empty() && agent.is_some() {
        json!({
            "task": review_queue[0].id(),
            "cmd": format!("ai task next --review --agent {who}"),
            "why": "no ready work; a task waits for independent review",
            "extra": [],
        })
    } else {
        let mut rec = nothing.clone();
        rec["why"] = json!("nothing is ready; tell the user and stop (the chief plans new work)");
        rec
    };
    contract(&mut recommended);

    let mut last_done: Vec<&Task> = done.clone();
    last_done.sort_by(|a, b| {
        b.get_str("updated")
            .unwrap_or_default()
            .cmp(&a.get_str("updated").unwrap_or_default())
    });
    last_done.truncate(history);
    let events: Vec<Value> = read_events(ws)
        .into_iter()
        .filter(|event| {
            event
                .get("event")
                .and_then(Value::as_str)
                .map(|name| {
                    name.starts_with("task_")
                        || name.starts_with("checkpoint")
                        || name.starts_with("resume")
                })
                .unwrap_or(false)
        })
        .rev()
        .take(history * 2)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();

    json!({
        "mode": config.get("mode"),
        "git": {
            "ready": git_ready,
            "branch": state.get("branch"),
            "head": state.get("head").and_then(Value::as_str).map(|head| head[..head.len().min(8)].to_string()),
            "dirty": state.get("dirty").and_then(Value::as_array).map(Vec::len).unwrap_or(0),
            "integration": branches.integration,
        },
        "agent": agent,
        "role": role,
        "mine": mine.iter().map(|task| task.to_json()).collect::<Vec<_>>(),
        "recommended": recommended,
        "ready": ready_all.iter().map(Task::to_json).collect::<Vec<_>>(),
        "waiting": waiting_all.iter().map(|(task, reasons)| json!({"task": task.to_json(), "reasons": reasons})).collect::<Vec<_>>(),
        "review_queue": review_queue.iter().map(|task| task.to_json()).collect::<Vec<_>>(),
        "others": others.iter().map(|task| task.to_json()).collect::<Vec<_>>(),
        "blocked": blocked.iter().map(|task| task.to_json()).collect::<Vec<_>>(),
        "handoffs": handoffs,
        "locks": locks,
        "active": active.iter().map(|task| task.to_json()).collect::<Vec<_>>(),
        "done": last_done.iter().map(|task| task.to_json()).collect::<Vec<_>>(),
        "done_total": done.len(),
        "events": events,
        "decisions": decisions::list_decisions(ws),
    })
}

pub fn compact(data: &Value) -> Value {
    let mut out = data.clone();
    if let Some(object) = out.as_object_mut() {
        for key in [
            "mine",
            "ready",
            "review_queue",
            "others",
            "blocked",
            "active",
            "done",
        ] {
            if let Some(items) = object.get(key).and_then(Value::as_array) {
                let slim: Vec<Value> = items
                    .iter()
                    .map(|task| {
                        crate::tasks::store::Task {
                            meta: task.as_object().cloned().unwrap_or_default(),
                            ..Default::default()
                        }
                        .slim_json()
                    })
                    .collect();
                object.insert(key.to_string(), Value::Array(slim));
            }
        }
        if let Some(waiting) = object.get("waiting").and_then(Value::as_array) {
            let slim: Vec<Value> = waiting
                .iter()
                .map(|entry| {
                    json!({
                        "task": entry.get("task").map(|task| crate::tasks::store::Task {
                            meta: task.as_object().cloned().unwrap_or_default(),
                            ..Default::default()
                        }.slim_json()),
                        "reasons": entry.get("reasons"),
                    })
                })
                .collect();
            object.insert("waiting".to_string(), Value::Array(slim));
        }
    }
    out
}
