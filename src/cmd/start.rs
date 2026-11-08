//! `ai start` and `ai init`: prepare the workspace and name the next steps.

use serde_json::{json, Value};

use crate::config::adopt;
use crate::config::blueprint;
use crate::config::preferences;
use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::{Workspace, VERSION};
use crate::git::flow as gitflow;
use crate::git::repo as git;
use crate::runtime::dirs;
use crate::tasks::lifecycle::{self, NewTask};
use crate::tasks::store::{self, Task};

use crate::StartArgs;

/// `ai start` claims through the same pipeline as `ai task claim`, so the two
/// entry points cannot drift (branch creation, rollback, git diagnostics).
fn claim_for_start(ws: &Workspace, path: &std::path::Path, agent: &str) -> Result<(bool, String)> {
    crate::cmd::task::claim_one(ws, path, agent, false)
}

pub fn run(ws: &Workspace, args: &StartArgs) -> Result<i32> {
    dirs::ensure_dirs(ws)?;
    if !ws.config_path().exists() {
        config::save(ws, &config::default_config(ws))?;
    }
    if let Some(path) = adopt::detach_template_git(ws)? {
        println!("Moved nested .ai/.git -> {path}");
    }
    let shape = ws.workspace_shape();
    let mut adapter_report: Vec<(String, String)> = Vec::new();
    let mut ignore_report = json!({"state": "not-needed", "missing": []});
    if shape == "subfolder" {
        match adopt::adopt_root(ws, false, false) {
            Ok(report) => adapter_report = report,
            Err(error) => {
                eprintln!("Could not wire the local adapters: {error}");
                return Ok(1);
            }
        }
        let (state, missing) = adopt::adopt_gitignore(ws, false)?;
        ignore_report = json!({"state": state, "missing": missing});
    }
    let mut git_state = git::state(ws);
    let mut setup_error = String::new();
    let confirmed = preferences::status(ws)
        .map(|state| state.confirmed)
        .unwrap_or(false);
    if confirmed
        && config::git_enabled(ws)
        && git_state
            .get("repo")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        && git_state.get("head").and_then(Value::as_str).is_some()
    {
        if gitflow::setup(ws, true, args.json)? != 0 {
            setup_error = "git setup failed".to_string();
            eprintln!("{setup_error}");
        }
        git_state = git::state(ws);
    }
    let branches = git::config(ws);
    let git_ready = git_state
        .get("repo")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        && git_state.get("head").and_then(Value::as_str).is_some()
        && git::branch_exists(&ws.project, &branches.integration)
        && git::branch_exists(&ws.project, &branches.production);
    let mut created = false;
    let mut active_tasks: Vec<Task> = store::load_tasks(ws)
        .into_iter()
        .filter(Task::is_active)
        .collect();
    let demo_created = active_tasks.is_empty()
        && !args.no_demo
        && lifecycle::create_task(
            ws,
            NewTask {
                title: "Try the workspace".into(),
                priority: "medium".into(),
                spec: None,
                depends_on: None,
                make_spec: true,
                scope_allowed: None,
                scope_forbidden: None,
                actor: None,
                locks: None,
                intent: None,
                acceptance: Some(vec![
                    "`ai doctor` reports 0 errors".to_string(),
                    "`ai task show` prints this task".to_string(),
                ]),
                demo: true,
            },
        )
        .is_ok();
    if demo_created {
        created = true;
        active_tasks = store::load_tasks(ws)
            .into_iter()
            .filter(Task::is_active)
            .collect();
    }
    let mut target = active_tasks.first().cloned();
    let mut claimed = false;
    let mut claim_error: Option<String> = None;
    if let (Some(task), Some(agent)) = (&target, args.agent.as_deref()) {
        if task.owner().is_none() {
            let path = task.path.clone();
            match claim_for_start(ws, &path, agent) {
                Ok((true, message)) => {
                    claimed = true;
                    target = store::load_tasks(ws)
                        .into_iter()
                        .find(|task| task.id() == message)
                        .or_else(|| target.clone());
                }
                Ok((false, message)) => claim_error = Some(message),
                Err(error) => return Err(error),
            }
        }
    }
    let mut next_steps: Vec<String> = Vec::new();
    if config::git_enabled(ws) && !git_ready {
        next_steps.push("ai git setup".to_string());
    }
    if let Some(task) = &target {
        let owner = task
            .owner()
            .or_else(|| if claimed { args.agent.clone() } else { None });
        let current_branch = git_state.get("branch").and_then(Value::as_str);
        let task_branch = task.get_str("branch");
        if owner.is_some() && task_branch.is_some() && task_branch.as_deref() == current_branch {
            // already on the task branch
        } else if let Some(owner) = owner {
            next_steps.push(format!(
                "ai git start --task {} --agent {owner} --type feature",
                task.id()
            ));
        } else {
            next_steps.push(format!("ai task claim {} --agent <name>", task.id()));
        }
    } else if !confirmed {
        next_steps.push(
            "ai setup   # you are the chief: ask the user which workflow features they want"
                .to_string(),
        );
    } else if blueprint::status(ws) == blueprint::State::Missing {
        next_steps.push(
            "ai blueprint propose   # record the facts, then the chief authors it with --from <analysis.json> and the user approves"
                .to_string(),
        );
    } else if blueprint::status(ws) == blueprint::State::Pending {
        next_steps.push(
            "ai blueprint show   # the user approves or changes the proposal before planning"
                .to_string(),
        );
    } else {
        next_steps.push(
            "ai plan apply plan.json --role chief   # split the request into linked tasks (`ai plan example`)"
                .to_string(),
        );
    }
    if let Some(task) = &target {
        let checkout = git::task_checkout(ws, task);
        let ahead = git::commits_ahead(&checkout, &branches.integration).unwrap_or(0);
        if ahead > 0 {
            next_steps.push(format!("ai check --task {} --agent <name>", task.id()));
        } else if task.owner().is_some() {
            next_steps.push(format!(
                "ai task show {}   # read the spec, do the work, then `ai git commit` (checks come at the end)",
                task.id()
            ));
        }
    }
    if let Some(error) = &claim_error {
        eprintln!("{error}");
    }
    if args.json {
        let payload = json!({
            "workspace": ws.root.to_string_lossy(),
            "project": ws.project.to_string_lossy(),
            "version": VERSION,
            "shape": shape,
            "mode": config::load_or_default(ws).get("mode").cloned().unwrap_or(Value::Null),
            "adapters": adapter_report.iter().map(|(path, state)| json!({"path": path, "state": state})).collect::<Vec<_>>(),
            "gitignore": ignore_report,
            "git": {
                "repo": git_state.get("repo").and_then(Value::as_bool).unwrap_or(false),
                "head": git_state.get("head").and_then(Value::as_str).is_some(),
                "branch": git_state.get("branch"),
                "integration": branches.integration,
                "production": branches.production,
                "ready": git_ready,
                "error": if setup_error.is_empty() { Value::Null } else { json!(setup_error) },
            },
            "task": target.as_ref().map(|task| json!({
                "id": task.id(),
                "title": task.title(),
                "owner": task.owner(),
                "spec": task.get("spec"),
            })),
            "claimed": claimed,
            "created": created,
            "next": next_steps,
        });
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(if claim_error.is_some() { 1 } else { 0 });
    }
    println!("Workspace : {}", ws.root.display());
    println!(
        "Shape     : {shape}{}",
        if shape == "subfolder" {
            " install"
        } else {
            " template"
        }
    );
    println!(
        "Mode      : {}",
        config::load_or_default(ws)
            .get("mode")
            .and_then(Value::as_str)
            .unwrap_or("-")
    );
    if shape == "subfolder" {
        let written = adapter_report
            .iter()
            .filter(|(_, state)| state != "unchanged")
            .count();
        println!(
            "Adapters  : {} local file(s), {written} changed",
            adapter_report.len()
        );
    } else {
        println!("Adapters  : not needed (the root AGENTS.md is the entry point)");
    }
    if git_ready {
        println!(
            "Git       : ready (integration {}, production {})",
            branches.integration, branches.production
        );
    } else if git_state
        .get("repo")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        println!("Git       : repository found, Gitflow base missing");
    } else {
        println!("Git       : not initialized");
    }
    if let Some(task) = &target {
        let owner = task
            .owner()
            .map(|owner| format!(" ({owner})"))
            .unwrap_or_default();
        println!("Task      : {} {}{owner}", task.id(), task.title());
        if let Some(spec) = task.get_str("spec") {
            println!("Spec      : {spec}");
        }
    } else {
        println!("Task      : none yet");
    }
    println!("\nNext:");
    for (index, step) in next_steps.iter().enumerate() {
        println!("  {}. {step}", index + 1);
    }
    println!("\nFull loop: GUIDE.md#first-pass-clone-to-verified-change");
    Ok(if claim_error.is_some() { 1 } else { 0 })
}
