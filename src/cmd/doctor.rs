//! `ai doctor` and `ai check`: workspace health and the verification contract.

use std::path::PathBuf;

use serde_json::{json, Value};

use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::{Workspace, VERSION};
use crate::git::repo as git;
use crate::runtime::evidence;
use crate::runtime::health::{self, Finding};
use crate::tasks::store;

use crate::{CheckArgs, DoctorArgs};

pub fn doctor(ws: &Workspace, args: &DoctorArgs) -> Result<i32> {
    let fixes = if args.fix {
        health::apply_safe_fixes(ws)
    } else {
        Vec::new()
    };
    let mut problems = health::collect_checks(ws);
    problems.extend(health::collect_git_invariants(ws));
    problems.extend(health::collect_blueprint_check(ws));
    let mut code = if problems.iter().any(|finding| finding.level == "error") {
        1
    } else {
        0
    };
    if args.strict && problems.iter().any(|finding| finding.level == "warn") {
        code = 1;
    }
    if args.fix && !problems.is_empty() {
        code = 1;
    }
    if !args.json {
        if !fixes.is_empty() {
            println!("Repaired:");
            for item in &fixes {
                println!("FIXED  {item}");
            }
            println!();
        }
        health::report_problems(&problems);
    }
    if args.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "workspace": ws.root.to_string_lossy(),
                "project": ws.project.to_string_lossy(),
                "platform": std::env::consts::OS,
                "version": VERSION,
                "adapters": health::adapters(ws),
                "fixes": fixes,
                "check": health::problems_to_dict(&problems),
            }))?
        );
        return Ok(code);
    }
    println!("workspace: {}", ws.root.display());
    println!("project:   {}", ws.project.display());
    println!(
        "platform:  {} ({})",
        std::env::consts::OS,
        std::env::consts::ARCH
    );
    println!("version:   {VERSION}");
    println!();
    for adapter in health::adapters(ws) {
        println!("adapter:   {adapter}");
    }
    println!();
    Ok(code)
}

fn evidence_task(ws: &Workspace, args: &CheckArgs) -> Option<String> {
    if let Some(task_id) = &args.task {
        return store::task_of(ws, task_id).map(|task| task.id());
    }
    let agent = args.agent.as_deref()?;
    let mine: Vec<store::Task> = store::load_tasks(ws)
        .into_iter()
        .filter(|task| {
            task.is_active()
                && task.owner().as_deref() == Some(agent)
                && task.status() == "in_progress"
        })
        .collect();
    if mine.len() == 1 {
        Some(mine[0].id())
    } else {
        None
    }
}

/// The checkout whose product files the checks and evidence describe.
fn checkout_for(ws: &Workspace, task_id: Option<&str>) -> PathBuf {
    task_id
        .and_then(|task_id| store::task_of(ws, task_id))
        .map(|task| git::task_checkout(ws, &task))
        .unwrap_or_else(|| ws.project.clone())
}

/// Evidence is proof of the claimant's work, not a lever any agent may pull on
/// somebody else's task. Only a task being worked on (by the caller) or one that
/// is already in review may gain a record.
fn may_record_evidence(ws: &Workspace, task_id: &str, agent: Option<&str>) -> bool {
    let task = match store::task_of(ws, task_id) {
        Some(task) => task,
        None => return false,
    };
    let status = task.status();
    let owner = task.owner();
    match status.as_str() {
        "review" => true,
        "in_progress" => match (owner, agent) {
            (Some(owner), Some(agent)) => owner == agent,
            (Some(owner), None) => {
                eprintln!(
                    "NOTE  task {task_id} is owned by {owner}; pass --agent {owner} to record evidence."
                );
                false
            }
            (None, _) => true,
        },
        other => {
            eprintln!(
                "NOTE  no evidence recorded for task {task_id}: it is '{other}', not claimed by a worker."
            );
            false
        }
    }
}

pub fn check(ws: &Workspace, args: &CheckArgs) -> Result<i32> {
    if let Some(task_id) = &args.task {
        if store::find_task(ws, task_id).is_none() {
            eprintln!("No task with id {task_id}; no evidence was recorded.");
            return Ok(1);
        }
    }
    let task_id = evidence_task(ws, args);
    if args.agent.is_some() && task_id.is_none() && args.task.is_none() {
        eprintln!(
            "WARN  no single in-progress task owned by {}; the check result will not be attached as evidence. Use --task <id>.",
            args.agent.as_deref().unwrap_or("-")
        );
    }
    let attach = task_id
        .as_deref()
        .map(|task_id| may_record_evidence(ws, task_id, args.agent.as_deref()))
        .unwrap_or(false);
    let checkout = checkout_for(ws, task_id.as_deref());
    let mut problems: Vec<Finding> = health::collect_checks(ws);
    let mut results: Vec<Value> = Vec::new();
    let allow_empty = args.allow_empty;
    let config_readable = config::load(ws).is_ok();
    let checks = if config_readable {
        config::configured_checks(ws)
    } else {
        Vec::new()
    };
    let config_opt_out =
        config::preference(ws, "workflow.requireCheck", json!("strict")) == Value::Bool(false);
    if config_readable && !args.no_commands && checks.is_empty() {
        if allow_empty || config_opt_out {
            let reason = if allow_empty {
                "--allow-empty was given"
            } else {
                "workflow.requireCheck is false in config/workspace.json"
            };
            eprintln!("ALLOW-EMPTY  no project checks are configured; passing because {reason}.");
        } else {
            problems.push(Finding::new(
                "error",
                "no project checks are configured; this gate would be empty",
                "add a command under \"checks\" in config/workspace.json (e.g. `ai setup --check \"tests=<command>\"`), or pass --allow-empty if this project intentionally runs no checks",
            ));
        }
    } else if !args.no_commands {
        problems.extend(health::run_commands(
            ws,
            &checkout,
            args.fast,
            &mut results,
            Some(args.json),
        )?);
    }
    let mut code = if problems.iter().any(|finding| finding.level == "error") {
        1
    } else {
        0
    };
    if args.strict && problems.iter().any(|finding| finding.level == "warn") {
        code = 1;
    }
    if let Some(task_id) = &task_id {
        if attach {
            let head = git::state_at(&checkout)
                .get("head")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            match evidence::record_task_check(
                ws,
                task_id,
                args.agent.as_deref(),
                code == 0,
                head.as_deref(),
                &results,
                args.strict,
                !checks.is_empty() && !args.no_commands,
                args.fast,
            ) {
                Ok(record) => {
                    if !args.json {
                        eprintln!(
                            "Evidence recorded for task {task_id}: {}",
                            evidence::summary(&record)
                        );
                    }
                }
                Err(error) => eprintln!("WARN  could not record the check result: {error}"),
            }
        }
    }
    if args.json {
        let mut payload = health::problems_to_dict(&problems);
        if let Some(object) = payload.as_object_mut() {
            object.insert("results".into(), json!(results));
            object.insert("allow_empty".into(), json!(allow_empty));
            if let Some(task_id) = &task_id {
                object.insert("task".into(), json!(task_id));
                object.insert("evidence_attached".into(), json!(attach));
                let head = git::state_at(&checkout)
                    .get("head")
                    .and_then(Value::as_str)
                    .map(ToString::to_string);
                object.insert(
                    "evidence".into(),
                    evidence::task_status(ws, task_id, head.as_deref(), None)
                        .get("state")
                        .cloned()
                        .unwrap_or(Value::Null),
                );
            }
        }
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(code);
    }
    health::report_problems(&problems);
    Ok(code)
}
