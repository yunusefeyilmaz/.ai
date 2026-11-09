//! Workspace health: structure, task-state consistency and the check runner.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use regex::Regex;
use serde_json::{json, Value};

use crate::config::blueprint;
use crate::config::roles;
use crate::config::settings::{self as config, configured_checks, load, lock_settings};
use crate::core::error::Result;
use crate::core::fsio::{normalize_id, read_json};
use crate::core::time::age_minutes;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo as git;
use crate::runtime::checkpoints;
use crate::runtime::dirs;
use crate::runtime::leases::{list_locks, lock_is_stale};
use crate::specs::spec;
use crate::tasks::store::{self, Task};

#[derive(Clone, Debug)]
pub struct Finding {
    pub level: String,
    pub message: String,
    pub hint: String,
}

impl Finding {
    pub fn new(level: &str, message: impl Into<String>, hint: impl Into<String>) -> Self {
        Finding {
            level: level.to_string(),
            message: message.into(),
            hint: hint.into(),
        }
    }
}

const REQUIRED_PATHS: &[&str] = &[
    "AGENTS.md",
    "README.md",
    "GUIDE.md",
    "config/workspace.json",
    "tasks/README.md",
    "tasks/TEMPLATE.md",
    "specs/README.md",
    "specs/TEMPLATE.md",
    "templates/git/commit-template.txt",
    "templates/git/pull-request.md",
    "runtime",
    "docs/architecture.md",
    "docs/git-workflow.md",
    "docs/task-flow.md",
    "docs/multi-agent.md",
    "docs/artifact-hygiene.md",
    "docs/recovery.md",
    "docs/orchestration.md",
    "docs/roadmap.md",
    "docs/conventions.md",
    "agents/README.md",
    "agents/orchestrator.md",
    "agents/planner.md",
    "agents/implementer.md",
    "agents/reviewer.md",
    "agents/qa.md",
];

const SCAN_SKIP: &[&str] = &[
    ".ai",
    ".git",
    ".github",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "out",
    "bin",
    "obj",
    ".venv",
    "venv",
    "__pycache__",
];

fn rel(ws: &Workspace, path: &Path) -> String {
    relative_to(&ws.root, path)
}

pub fn adapters(ws: &Workspace) -> Vec<String> {
    let directory = ws.root.join("adapters");
    let entries = match fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    let mut names: Vec<String> = entries
        .flatten()
        .filter(|entry| entry.path().is_dir())
        .map(|entry| entry.file_name().to_string_lossy().to_string())
        .collect();
    names.sort();
    names
}

pub fn problems_to_dict(problems: &[Finding]) -> Value {
    json!({
        "ok": !problems.iter().any(|finding| finding.level == "error"),
        "errors": problems.iter().filter(|f| f.level == "error").map(|f| f.message.clone()).collect::<Vec<_>>(),
        "warnings": problems.iter().filter(|f| f.level == "warn").map(|f| f.message.clone()).collect::<Vec<_>>(),
        "findings": problems.iter().map(|f| json!({
            "level": f.level,
            "message": f.message,
            "hint": f.hint,
        })).collect::<Vec<_>>(),
    })
}

pub fn report_problems(problems: &[Finding]) -> i32 {
    let errors: Vec<&Finding> = problems.iter().filter(|f| f.level == "error").collect();
    let warnings: Vec<&Finding> = problems.iter().filter(|f| f.level == "warn").collect();
    for (label, group) in [("ERROR", &errors), ("WARN ", &warnings)] {
        for finding in group {
            println!("{label}  {}", finding.message);
            if !finding.hint.is_empty() {
                println!("       fix: {}", finding.hint);
            }
        }
    }
    if problems.is_empty() {
        println!("OK     workspace structure and task state are consistent");
    }
    println!("\n{} error(s), {} warning(s)", errors.len(), warnings.len());
    if errors.is_empty() {
        0
    } else {
        1
    }
}

/// Run the configured project checks in `cwd`; append results to `results` when given.
pub fn run_commands(
    ws: &Workspace,
    cwd: &Path,
    fast_only: bool,
    results: &mut Vec<Value>,
    out: Option<bool>,
) -> Result<Vec<Finding>> {
    let mut problems = Vec::new();
    let config = load(ws).unwrap_or_else(|_| config::default_config(ws));
    let checks = config
        .get("checks")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let stderr_mode = out.unwrap_or(false);
    if checks.is_empty() {
        let note = "NOTE  no project checks configured: add your test/lint commands under \"checks\" in config/workspace.json.";
        if stderr_mode {
            eprintln!("{note}");
        } else {
            println!("{note}");
        }
    }
    for item in &checks {
        if fast_only && !item.get("fast").and_then(Value::as_bool).unwrap_or(false) {
            continue;
        }
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .or_else(|| item.get("command").and_then(Value::as_str))
            .unwrap_or("check")
            .to_string();
        let command = match item.get("command").and_then(Value::as_str) {
            Some(command) if !command.trim().is_empty() => command.to_string(),
            _ => continue,
        };
        let line = format!("\n$ {command}");
        if stderr_mode {
            eprintln!("{line}");
        } else {
            println!("{line}");
        }
        let started = Instant::now();
        let limit = Duration::from_secs(check_timeout(item, &config));
        let outcome = crate::core::process::run(&command, cwd, Some(limit));
        let output = outcome.combined();
        if !output.trim().is_empty() {
            if stderr_mode {
                eprintln!("{output}");
            } else {
                println!("{output}");
            }
        }
        let seconds = started.elapsed().as_secs_f64();
        results.push(json!({
            "name": name,
            "command": command,
            "exit_code": outcome.code,
            "seconds": (seconds * 100.0).round() / 100.0,
            "timed_out": outcome.timed_out,
            "timeout_seconds": limit.as_secs(),
        }));
        if outcome.timed_out {
            problems.push(Finding::new(
                "error",
                format!(
                    "check '{name}' timed out after {}s (exit 124)",
                    limit.as_secs()
                ),
                format!(
                    "raise this check's `timeoutSeconds` (ai setup --check-timeout {name}=<seconds>) or make the command faster: {command}"
                ),
            ));
        } else if outcome.code != 0 {
            problems.push(Finding::new(
                "error",
                format!("check '{name}' failed with exit code {}", outcome.code),
                format!("run the failing command yourself: {command}"),
            ));
        }
    }
    Ok(problems)
}

/// The budget for one check: its own `timeoutSeconds`, then the shared
/// `checksTimeoutSeconds`, then a safe default.
fn check_timeout(item: &Value, config: &Value) -> u64 {
    item.get("timeoutSeconds")
        .and_then(Value::as_u64)
        .or_else(|| config.get("checksTimeoutSeconds").and_then(Value::as_u64))
        .unwrap_or(1800)
}

fn collect_state_files(ws: &Workspace) -> Vec<PathBuf> {
    let mut paths = vec![ws.counter_path(), ws.manifest_path()];
    for root in [ws.state_dir(), ws.locks_dir()] {
        walk_files(&root, &mut paths, &[".json", ".lock"]);
    }
    paths.into_iter().filter(|path| path.is_file()).collect()
}

fn walk_files(root: &Path, out: &mut Vec<PathBuf>, extensions: &[&str]) {
    let entries = match fs::read_dir(root) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        if path.is_dir() {
            if SCAN_SKIP.contains(&name.as_str()) {
                continue;
            }
            walk_files(&path, out, extensions);
        } else if extensions.iter().any(|ext| name.ends_with(ext)) {
            out.push(path);
        }
    }
}

fn tmp_debris(ws: &Workspace) -> Vec<PathBuf> {
    let mut found = Vec::new();
    for root in [
        ws.tasks_dir(),
        ws.specs_dir(),
        ws.runtime_dir(),
        ws.config_dir(),
        ws.decisions_dir(),
    ] {
        walk_tmp(&root, &mut found);
    }
    found
}

fn walk_tmp(root: &Path, out: &mut Vec<PathBuf>) {
    let entries = match fs::read_dir(root) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        if path.is_dir() {
            if SCAN_SKIP.contains(&name.as_str()) {
                continue;
            }
            walk_tmp(&path, out);
        } else if name.starts_with(".tmp-") && name.ends_with(".part") {
            out.push(path);
        }
    }
}

fn is_corrupt_json(path: &Path) -> Option<String> {
    match read_json(path) {
        Ok(_) => None,
        Err(error) => Some(error.to_string()),
    }
}

fn dependency_cycles(tasks: &[Task]) -> Vec<Vec<String>> {
    let mut edges: std::collections::BTreeMap<String, Vec<String>> =
        std::collections::BTreeMap::new();
    for task in tasks {
        if !task.is_active() {
            continue;
        }
        let task_id = match normalize_id(&task.id()) {
            Ok(id) => id,
            Err(_) => continue,
        };
        let deps: Vec<String> = store::board_dependencies(&task.meta)
            .into_iter()
            .filter(|dep| dep != &task_id)
            .collect();
        edges.insert(task_id, deps);
    }
    let mut cycles: Vec<Vec<String>> = Vec::new();
    let mut seen: std::collections::HashSet<Vec<String>> = std::collections::HashSet::new();
    let mut state: std::collections::HashMap<String, u8> = std::collections::HashMap::new();
    let mut stack: Vec<String> = Vec::new();

    fn visit(
        node: &str,
        edges: &std::collections::BTreeMap<String, Vec<String>>,
        state: &mut std::collections::HashMap<String, u8>,
        stack: &mut Vec<String>,
        cycles: &mut Vec<Vec<String>>,
        seen: &mut std::collections::HashSet<Vec<String>>,
    ) {
        state.insert(node.to_string(), 1);
        stack.push(node.to_string());
        for dep in edges.get(node).cloned().unwrap_or_default() {
            if !edges.contains_key(&dep) {
                continue;
            }
            match state.get(&dep).copied().unwrap_or(0) {
                1 => {
                    if let Some(index) = stack.iter().position(|item| item == &dep) {
                        let mut cycle = stack[index..].to_vec();
                        cycle.sort();
                        if seen.insert(cycle.clone()) {
                            cycles.push(stack[index..].to_vec());
                        }
                    }
                }
                2 => {}
                _ => visit(&dep, edges, state, stack, cycles, seen),
            }
        }
        stack.pop();
        state.insert(node.to_string(), 2);
    }

    let nodes: Vec<String> = edges.keys().cloned().collect();
    for node in nodes {
        if state.get(&node).copied().unwrap_or(0) == 0 {
            visit(
                &node,
                &edges,
                &mut state,
                &mut stack,
                &mut cycles,
                &mut seen,
            );
        }
    }
    cycles
}

pub fn collect_checks(ws: &Workspace) -> Vec<Finding> {
    let mut problems: Vec<Finding> = Vec::new();

    for path in REQUIRED_PATHS {
        if *path == "config/workspace.json" {
            continue;
        }
        if !ws.root.join(path).exists() {
            let hint = if path.starts_with("runtime") {
                "ai doctor --fix".to_string()
            } else if ws.workspace_shape() == "subfolder" {
                format!("restore {path} from the .ai workspace copy")
            } else {
                format!("git checkout -- {path}")
            };
            problems.push(Finding::new(
                "error",
                format!("missing required path: {path}"),
                hint,
            ));
        }
    }

    let config = match load(ws) {
        Ok(config) => config,
        Err(error) => {
            problems.push(Finding::new("error", error.to_string(), "ai doctor --fix"));
            json!({})
        }
    };
    if config.is_object() {
        let known_roles: std::collections::BTreeSet<String> =
            roles::role_table(&config).keys().cloned().collect();
        if let Some(team) = config.get("team").and_then(Value::as_object) {
            for (name, entry) in team {
                if let Some(list) = entry.get("roles").and_then(Value::as_array) {
                    for role in list.iter().filter_map(Value::as_str) {
                        if !known_roles.contains(role) {
                            problems.push(Finding::new(
                                "warn",
                                format!("agent '{name}' has unknown role '{role}'"),
                                format!(
                                    "define it under `roles` or use one of: {}",
                                    known_roles.iter().cloned().collect::<Vec<_>>().join(", ")
                                ),
                            ));
                        }
                    }
                }
            }
        }
        if !matches!(
            config.get("mode").and_then(Value::as_str),
            Some("lite" | "strict")
        ) {
            problems.push(Finding::new(
                "error",
                "config mode must be 'lite' or 'strict'",
                "set \"mode\" to \"lite\" or \"strict\" in config/workspace.json",
            ));
        }
        for key in [
            "version",
            "language",
            "locks",
            "handoff",
            "budget",
            "artifacts",
        ] {
            if !config
                .get(key)
                .map(|value| !value.is_null())
                .unwrap_or(false)
            {
                problems.push(Finding::new(
                    "warn",
                    format!("config is missing key: {key}"),
                    format!("add \"{key}\" to config/workspace.json"),
                ));
            }
        }
    }

    let locks = list_locks(ws, false);
    let mut lock_by_task: std::collections::HashMap<String, Value> =
        std::collections::HashMap::new();
    for lock in &locks {
        if let Some(resource) = lock.get("resource").and_then(Value::as_str) {
            if let Some(task_id) = resource.strip_prefix("task-") {
                lock_by_task.insert(task_id.to_string(), lock.clone());
            }
        }
    }

    let git_config = git::config(ws);
    let state = git::state(ws);
    let mut branches_enabled =
        config::git_enabled(ws) && state.get("repo").and_then(Value::as_bool).unwrap_or(false);
    let mut integration: Option<String> = None;
    if branches_enabled {
        integration = Some(git_config.integration.clone());
        branches_enabled = git::branch_exists(&ws.project, &git_config.integration)
            && git::branch_exists(&ws.project, &git_config.production);
    }
    let require_spec = config
        .get("workflow")
        .and_then(|workflow| workflow.get("requireSpec"))
        .and_then(Value::as_bool)
        .unwrap_or(true);

    let tasks = store::load_tasks(ws);
    let mut ids: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    let depends_separator = Regex::new(r"[,\s]+").expect("static regex");
    for task in &tasks {
        let path = rel(ws, &task.path);
        let task_id = task.id();
        if task_id.is_empty() {
            problems.push(Finding::new(
                "error",
                format!("{path}: missing id"),
                format!("add an `id:` field to {path}"),
            ));
        } else {
            if let Some(existing) = ids.get(&task_id) {
                problems.push(Finding::new(
                    "error",
                    format!("duplicate task id {task_id}: {path} and {existing}"),
                    "give one of the tasks a different id, then rerun `ai check`",
                ));
            }
            ids.insert(task_id.clone(), path.clone());
            match normalize_id(&task_id) {
                Err(_) => problems.push(Finding::new(
                    "error",
                    format!("{path}: invalid task id '{task_id}'"),
                    "task ids are numeric; rename the file and fix `id:`",
                )),
                Ok(canonical) => {
                    let name = task
                        .path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("");
                    if task.is_active() && !name.starts_with(&format!("{canonical}-")) {
                        problems.push(Finding::new(
                            "warn",
                            format!("{path}: filename does not start with {task_id}-"),
                            format!("rename {path} to {task_id}-<slug>.md"),
                        ));
                    }
                }
            }
        }
        if task.title().trim().is_empty() {
            problems.push(Finding::new(
                "error",
                format!("{path}: missing title"),
                format!("add a `title:` field to {path}"),
            ));
        }
        let status = task.status();
        if !crate::tasks::frontmatter::VALID_STATUSES.contains(&status.as_str()) {
            problems.push(Finding::new(
                "error",
                format!("{path}: invalid status '{status}'"),
                format!("set `status:` to a valid task status in {path}"),
            ));
        }
        if !task.is_active() && status != "done" {
            problems.push(Finding::new(
                "warn",
                format!("{path}: file in done/ but status is '{status}'"),
                format!("set `status: done` in {path}"),
            ));
        }
        let spec_ref = task.get_str("spec").unwrap_or_default();
        if !task.is_active() && spec_ref.starts_with("specs/active/") {
            problems.push(Finding::new(
                "warn",
                format!("{path}: task is done but its spec is still in specs/active/"),
                format!("move {spec_ref} to specs/done/ and update `spec:` in {path}"),
            ));
        }
        if task.is_active() && status == "done" {
            problems.push(Finding::new(
                "warn",
                format!("{path}: status is done but file is in active/"),
                format!("run `ai task done {task_id} --agent <name>` to archive it"),
            ));
        }
        if !task.is_active() && integration.is_some() {
            if let Some(branch) = task.get_str("branch") {
                if git::branch_exists(&ws.project, &branch)
                    && !git::branch_merged(
                        &ws.project,
                        &branch,
                        integration.as_deref().unwrap_or(""),
                    )
                {
                    problems.push(Finding::new(
                        "warn",
                        format!(
                            "{path}: done but branch '{branch}' was never merged into {}",
                            integration.as_deref().unwrap_or("develop")
                        ),
                        format!("run `ai git finish --task {task_id} --agent <reviewer>` first"),
                    ));
                }
            }
        }
        if let Some(depends) = task.get_str("depends_on") {
            for dependency in depends_separator.split(&depends) {
                let dependency = dependency.trim();
                if dependency.is_empty() {
                    continue;
                }
                let known = normalize_id(dependency)
                    .map(|id| ids.contains_key(&id))
                    .unwrap_or(false)
                    || store::find_task(ws, dependency).is_some();
                if !known {
                    problems.push(Finding::new(
                        "warn",
                        format!("{path}: depends_on unknown task {dependency}"),
                        format!("remove `{dependency}` from depends_on in {path}, or create it"),
                    ));
                }
            }
        }
        if task.is_active() {
            let owner = task.owner();
            let held = lock_by_task.get(&task_id);
            if let Some(owner) = &owner {
                if held.is_none() {
                    problems.push(Finding::new(
                        "warn",
                        format!("{path}: owner '{owner}' has no task lock"),
                        "ai recover --apply",
                    ));
                }
            }
            if let Some(held) = held {
                if owner.is_none() {
                    problems.push(Finding::new(
                        "warn",
                        format!(
                            "{path}: task lock held by {} but owner is empty",
                            held.get("agent").and_then(Value::as_str).unwrap_or("?")
                        ),
                        "ai recover --apply",
                    ));
                }
                if let Some(owner) = &owner {
                    if held.get("agent").and_then(Value::as_str) != Some(owner.as_str()) {
                        problems.push(Finding::new(
                            "warn",
                            format!(
                                "{path}: owner '{owner}' differs from lock holder '{}'",
                                held.get("agent").and_then(Value::as_str).unwrap_or("?")
                            ),
                            "ai recover --apply",
                        ));
                    }
                }
            }
            if matches!(status.as_str(), "in_progress" | "blocked") && owner.is_none() {
                problems.push(Finding::new(
                    "warn",
                    format!("{path}: {status} without an owner"),
                    format!("ai task claim {task_id} --agent <name>, or `ai recover --apply`"),
                ));
            }
            if matches!(status.as_str(), "in_progress" | "review")
                && task.get_str("branch").is_none()
                && branches_enabled
            {
                problems.push(Finding::new(
                    "warn",
                    format!("{path}: {status} without a task branch"),
                    format!(
                        "ai git start --task {task_id} --agent {} --type feature",
                        owner.clone().unwrap_or_else(|| "<name>".into())
                    ),
                ));
            }
            if require_spec {
                if let Some(problem) = spec::spec_problem(ws, &task.meta) {
                    problems.push(Finding::new(
                        "warn",
                        format!("{path}: {problem}"),
                        format!(
                            "fill {} (intent, behavior, acceptance criteria) before any worker claims it",
                            task.get_str("spec").unwrap_or_default()
                        ),
                    ));
                }
            }
            if status == "in_progress" {
                let warn_after = config
                    .get("handoff")
                    .and_then(|handoff| handoff.get("warnAfterMinutes"))
                    .and_then(Value::as_i64)
                    .unwrap_or(30);
                let hint = format!(
                    "ai checkpoint {task_id} --agent {} --next \"<step>\"",
                    owner.clone().unwrap_or_else(|| "agent".into())
                );
                match checkpoints::checkpoint_age_minutes(ws, &task_id) {
                    None => {
                        let updated = task.get_str("updated");
                        let claimed_age = age_minutes(
                            held.and_then(|lock| lock.get("started_at").and_then(Value::as_str))
                                .or(updated.as_deref()),
                        );
                        let grace = config.get("mode").and_then(Value::as_str) == Some("lite")
                            && claimed_age
                                .map(|age| age <= warn_after as f64)
                                .unwrap_or(false);
                        if !grace {
                            problems.push(Finding::new(
                                "warn",
                                format!("{path}: in_progress with no checkpoint"),
                                hint,
                            ));
                        }
                    }
                    Some(age) if age > warn_after as f64 => {
                        problems.push(Finding::new(
                            "warn",
                            format!("{path}: last checkpoint is {} min old", age as i64),
                            hint,
                        ));
                    }
                    _ => {}
                }
            }
        }
        if !task.is_active() && lock_by_task.contains_key(&task_id) {
            problems.push(Finding::new(
                "warn",
                format!("{path}: done task still holds task lock"),
                "ai recover --apply",
            ));
        }
    }

    for cycle in dependency_cycles(&tasks) {
        let mut path = cycle.clone();
        if let Some(first) = cycle.first() {
            path.push(first.clone());
        }
        problems.push(Finding::new(
            "error",
            format!("dependency cycle among active tasks: {}", path.join(" -> ")),
            "remove one edge of the cycle in the task's depends_on",
        ));
    }

    let (_, stale_after) = lock_settings(ws);
    for lock in &locks {
        if lock_is_stale(Some(lock), stale_after) {
            problems.push(Finding::new(
                "warn",
                format!(
                    "stale lock: {} held by {}",
                    lock.get("resource").and_then(Value::as_str).unwrap_or("?"),
                    lock.get("agent").and_then(Value::as_str).unwrap_or("?")
                ),
                "ai clean --stale-locks",
            ));
        }
        if let Some(resource) = lock.get("resource").and_then(Value::as_str) {
            if let Some(task_id) = resource.strip_prefix("task-") {
                if !ids.contains_key(task_id) {
                    problems.push(Finding::new(
                        "warn",
                        format!("orphan task lock: {resource} has no task file"),
                        "ai recover --apply",
                    ));
                }
            }
        }
    }

    for marker in checkpoints::list_handoff_markers(ws, false) {
        let task_id = marker.get("task").and_then(Value::as_str).unwrap_or("");
        let hint = format!(
            "ai checkpoint {task_id} --agent {} --next \"<step>\"",
            marker
                .get("agent")
                .and_then(Value::as_str)
                .unwrap_or("agent")
        );
        match checkpoints::read_checkpoint(ws, task_id) {
            None => problems.push(Finding::new(
                "warn",
                format!("handoff requested for {task_id} but no checkpoint exists"),
                hint,
            )),
            Some((meta, _, _)) => {
                if meta.get("created").and_then(Value::as_str).unwrap_or("")
                    < marker.get("created").and_then(Value::as_str).unwrap_or("")
                {
                    problems.push(Finding::new(
                        "warn",
                        format!("handoff requested for {task_id} but the checkpoint is older"),
                        hint,
                    ));
                }
            }
        }
    }

    if config
        .get("artifacts")
        .and_then(|artifacts| artifacts.get("watch"))
        .and_then(Value::as_array)
        .is_some()
    {
        let watch: Vec<String> = config
            .get("artifacts")
            .and_then(|artifacts| artifacts.get("watch"))
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(ToString::to_string)
                    .collect()
            })
            .unwrap_or_default();
        let top: std::collections::HashSet<String> = fs::read_dir(&ws.project)
            .map(|entries| {
                entries
                    .flatten()
                    .map(|entry| entry.file_name().to_string_lossy().to_string())
                    .collect()
            })
            .unwrap_or_default();
        for name in watch {
            if top.contains(&name) && !SCAN_SKIP.contains(&name.as_str()) {
                problems.push(Finding::new(
                    "error",
                    format!("AI scratch path outside the workspace: {name}/"),
                    format!("ai artifact put {name} --reason \"agent scratch\""),
                ));
            }
        }
    }

    for path in tmp_debris(ws) {
        problems.push(Finding::new(
            "warn",
            format!("leftover temp file: {}", rel(ws, &path)),
            "ai doctor --fix removes stale temp files",
        ));
    }

    for path in collect_state_files(ws) {
        if let Some(error) = is_corrupt_json(&path) {
            let relative = rel(ws, &path);
            let hint = if relative.starts_with("runtime/locks/") {
                "ai lock release <resource> --force, or wait for the lease to expire".to_string()
            } else if path == ws.manifest_path() {
                "move runtime/artifacts/MANIFEST.json aside, then rerun `ai artifact list`"
                    .to_string()
            } else {
                format!("move {relative} aside, then rerun the command that needs it")
            };
            let level = if relative.starts_with("runtime/locks/") {
                "error"
            } else {
                "warn"
            };
            problems.push(Finding::new(
                level,
                format!("corrupt state file: {relative} ({error})"),
                hint,
            ));
        }
    }

    if ws.workspace_shape() == "subfolder" {
        for (path, state) in crate::config::adopt::adopt_root(ws, false, true).unwrap_or_default() {
            if state != "ok" {
                problems.push(Finding::new(
                    "warn",
                    format!("missing adapter pointer: {path}"),
                    "ai doctor --fix",
                ));
            }
        }
        let (_, missing) =
            crate::config::adopt::adopt_gitignore(ws, true).unwrap_or(("ok".into(), Vec::new()));
        if !missing.is_empty() {
            problems.push(Finding::new(
                "warn",
                format!("project .gitignore is missing: {}", missing.join(", ")),
                "ai doctor --fix",
            ));
        }
    }

    for row in crate::git::worktrees::listing(ws, &tasks) {
        if row.orphan {
            problems.push(Finding::new(
                "warn",
                format!(
                    "worktree {} has no active task (or its task is already merged)",
                    row.name
                ),
                if row.dirty > 0 {
                    "remove it with `ai worktree prune` (it has uncommitted changes; check them first)"
                } else {
                    "remove it with `ai worktree prune`"
                },
            ));
        }
    }

    problems
}

/// Health invariants about the checkout itself. Kept out of `ai check` because
/// they describe the workspace, not the diff under review.
pub fn collect_git_invariants(ws: &Workspace) -> Vec<Finding> {
    let mut problems = Vec::new();
    if !config::git_enabled(ws) {
        return problems;
    }
    let state = git::state(ws);
    if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
        return problems;
    }
    let git_config = git::config(ws);
    if !git::branch_exists(&ws.project, &git_config.integration)
        || !git::branch_exists(&ws.project, &git_config.production)
    {
        return problems;
    }
    let current = state
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if !git_config.production.is_empty()
        && current == git_config.production
        && git_config.production != git_config.integration
    {
        problems.push(Finding::new(
            "warn",
            format!(
                "the main checkout is on production branch '{current}', not the integration branch '{}'",
                git_config.integration
            ),
            format!(
                "git checkout {}   # task branches and worktrees start from the integration branch",
                git_config.integration
            ),
        ));
    }
    // Untracked planning artifacts are the failure mode `ai plan apply` must not
    // leave behind: a task worktree or a fresh clone would not contain the plan.
    let untracked = git::parse_porcelain_z(&git::run_git_raw(
        &ws.project,
        &["status", "--porcelain", "-z"],
    ));
    let ledger: Vec<String> = untracked
        .iter()
        .filter(|(status, _)| status == "??")
        .map(|(_, path)| path.clone())
        .filter(|path| git::is_workspace_ledger_path(ws, path))
        .collect();
    if !ledger.is_empty() {
        problems.push(Finding::new(
            "warn",
            format!(
                "{} planning file(s) under tasks/specs/config are untracked",
                ledger.len()
            ),
            "commit the plan once (the chief's `ai plan apply` commits it) so worktrees and other agents see it",
        ));
    }
    problems
}

/// The architecture proposal is the chief's first deliverable; report it while
/// it is missing-by-policy or waiting for the user's decision.
pub fn collect_blueprint_check(ws: &Workspace) -> Vec<Finding> {
    let mut problems = Vec::new();
    match blueprint::status(ws) {
        blueprint::State::Pending => problems.push(Finding::new(
            "warn",
            "the architecture proposal is waiting for the user",
            "ask the user to approve or change it: `ai blueprint show`, then `ai blueprint approve --agent <name>` or `ai blueprint revise --set naming.files=snake_case`",
        )),
        blueprint::State::Missing => {
            let required = config::load(ws)
                .ok()
                .and_then(|config| config.get("blueprint").cloned())
                .and_then(|blueprint| blueprint.get("required").cloned())
                .and_then(|value| value.as_bool())
                .unwrap_or(false);
            if required {
                problems.push(Finding::new(
                    "warn",
                    "no architecture proposal exists",
                    "run `ai blueprint propose` (you are the chief), analyze the facts, then `ai blueprint propose --from <analysis.json>` and ask the user to approve it",
                ));
            }
        }
        blueprint::State::Approved => {}
    }
    problems
}

/// Repair missing, regenerable state. Never overwrites files or touches Git.
pub fn apply_safe_fixes(ws: &Workspace) -> Vec<String> {
    let mut fixes = Vec::new();
    for path in dirs::workspace_dirs(ws) {
        if !path.is_dir() && fs::create_dir_all(&path).is_ok() {
            fixes.push(format!("created {}/", rel(ws, &path)));
        }
    }
    if let Ok(created) = dirs::ensure_placeholders(ws) {
        fixes.extend(created.into_iter().map(|item| format!("created {item}")));
    }
    if !ws.config_path().exists() && config::save(ws, &config::default_config(ws)).is_ok() {
        fixes.push("created config/workspace.json".to_string());
    }
    if ws.workspace_shape() == "subfolder" {
        let missing: Vec<String> = crate::config::adopt::adopt_root(ws, false, true)
            .unwrap_or_default()
            .into_iter()
            .filter(|(_, state)| state != "ok")
            .map(|(path, _)| path)
            .collect();
        if !missing.is_empty() {
            let _ = crate::config::adopt::adopt_root(ws, false, false);
            fixes.extend(missing.into_iter().map(|path| format!("wired {path}")));
        }
        if let Ok((_, missing_ignore)) = crate::config::adopt::adopt_gitignore(ws, true) {
            if !missing_ignore.is_empty() {
                let _ = crate::config::adopt::adopt_gitignore(ws, false);
                fixes.push(format!(
                    "added .gitignore rules: {}",
                    missing_ignore.join(", ")
                ));
            }
        }
    }
    for path in tmp_debris(ws) {
        if let Ok(metadata) = fs::metadata(&path) {
            if let Ok(modified) = metadata.modified() {
                if let Ok(age) = modified.elapsed() {
                    if age.as_secs() < 300 {
                        continue;
                    }
                }
            }
        }
        if fs::remove_file(&path).is_ok() {
            fixes.push(format!("removed stale temp file {}", rel(ws, &path)));
        }
    }
    if is_corrupt_json(&ws.counter_path()).is_some() && fs::remove_file(ws.counter_path()).is_ok() {
        fixes.push(
            "removed corrupt runtime/state/task-counter.json (ids are rebuilt from the tasks)"
                .to_string(),
        );
    }
    let _ = configured_checks(ws);
    fixes
}
