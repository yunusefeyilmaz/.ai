//! Gitflow: guarded branch creation, commits and merges.

use std::path::{Path, PathBuf};
use std::process::Command;

use regex::Regex;
use serde_json::{json, Map, Value};

use crate::config::roles;
use crate::config::settings::{lock_settings, max_lock_ttl};
use crate::core::error::{fail, Result};
use crate::core::time::iso;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::repo::{self as git, GitConfig};
use crate::git::worktrees;
use crate::runtime::events::append_event;
use crate::runtime::leases::{self, acquire_lock, list_locks, lock_is_stale};
use crate::runtime::mutex::workspace_state_guard;
use crate::tasks::board;
use crate::tasks::gates;
use crate::tasks::scope;
use crate::tasks::store::{self, Task};

pub fn cli_command(_ws: &Workspace) -> String {
    _ws.cli_command()
}

impl Workspace {
    pub fn cli_command(&self) -> String {
        worktrees::cli_command(self)
    }
}

pub fn checks_seconds_budget(ws: &Workspace) -> u64 {
    let config = crate::config::settings::load_or_default(ws);
    let mut total = 0u64;
    if let Some(items) = config.get("checks").and_then(Value::as_array) {
        for item in items {
            total += item
                .get("timeoutSeconds")
                .and_then(Value::as_u64)
                .or_else(|| config.get("checksTimeoutSeconds").and_then(Value::as_u64))
                .unwrap_or(1800);
        }
    }
    let ceiling = max_lock_ttl(ws).saturating_sub(600).max(60);
    (if total == 0 { 1800 } else { total }).min(ceiling)
}

pub fn acquire_git_guard(
    ws: &Workspace,
    agent: &str,
    task_id: &str,
    ttl: u64,
) -> Result<(bool, bool, String)> {
    let (_, stale_after) = lock_settings(ws);
    if let Some(current) = list_locks(ws, false).into_iter().find(|lock| {
        lock.get("resource").and_then(Value::as_str) == Some("@git/index")
            && !lock_is_stale(Some(lock), stale_after)
    }) {
        if current.get("agent").and_then(Value::as_str) != Some(agent) {
            append_event(
                ws,
                "lock_refused",
                &[
                    ("resource", json!("@git/index")),
                    ("agent", json!(agent)),
                    ("task", json!(task_id)),
                    ("conflict", json!("@git/index")),
                    (
                        "conflict_agent",
                        current.get("agent").cloned().unwrap_or(Value::Null),
                    ),
                ],
            );
            return Ok((
                false,
                false,
                format!(
                    "git index is locked by {} (task {}).",
                    current
                        .get("agent")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown"),
                    current.get("task").and_then(Value::as_str).unwrap_or("-")
                ),
            ));
        }
        return Ok((true, false, String::new()));
    }
    let ttl = ttl.clamp(1, max_lock_ttl(ws).max(1));
    let result = acquire_lock(
        ws,
        "@git/index",
        Some(agent),
        Some(task_id),
        Some(ttl),
        false,
    )?;
    if !result.ok {
        let holder = result.holder.clone().unwrap_or(Value::Null);
        let error = result.error.clone().unwrap_or_default();
        append_event(
            ws,
            "lock_refused",
            &[
                ("resource", json!("@git/index")),
                ("agent", json!(agent)),
                ("task", json!(task_id)),
                ("conflict", json!("@git/index")),
                (
                    "conflict_agent",
                    holder.get("agent").cloned().unwrap_or(Value::Null),
                ),
                ("error", json!(error)),
            ],
        );
        if !error.is_empty() {
            return Ok((
                false,
                false,
                format!("Could not take the git index guard: {error}"),
            ));
        }
        return Ok((
            false,
            false,
            format!(
                "git index is locked by {} (task {}).",
                holder
                    .get("agent")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                holder.get("task").and_then(Value::as_str).unwrap_or("-")
            ),
        ));
    }
    Ok((true, true, String::new()))
}

pub fn release_git_guard(ws: &Workspace, owned: bool, agent: &str) {
    if !owned {
        return;
    }
    let _ = leases::release_lock(ws, "@git/index", Some(agent), false, true);
}

pub fn heartbeat_git_guard(ws: &Workspace, agent: &str) -> bool {
    leases::heartbeat_lock(ws, "@git/index", Some(agent), true).is_ok()
}

pub fn git_clean(ws: &Workspace, cwd: &Path, ignore_ledger: bool) -> bool {
    let state = git::state_at(cwd);
    let dirty = state
        .get("dirty")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    !dirty.iter().filter_map(Value::as_str).any(|path| {
        if ignore_ledger {
            !git::is_workspace_ledger_path(ws, path)
        } else {
            true
        }
    })
}

pub fn uncovered_staged(ws: &Workspace, state: &Value) -> (Vec<String>, Vec<Value>) {
    let (_, stale_after) = lock_settings(ws);
    let locks: Vec<Value> = list_locks(ws, false)
        .into_iter()
        .filter(|lock| {
            let resource = lock.get("resource").and_then(Value::as_str).unwrap_or("");
            !lock_is_stale(Some(lock), stale_after)
                && resource != "@git/index"
                && resource != "tasks.index"
                && !resource.starts_with("task-")
        })
        .collect();
    let mut uncovered = Vec::new();
    if let Some(staged) = state.get("staged").and_then(Value::as_array) {
        for path in staged.iter().filter_map(Value::as_str) {
            if git::is_workspace_ledger_path(ws, path) {
                continue;
            }
            let covered = locks.iter().any(|lock| {
                leases::resources_overlap(
                    path,
                    lock.get("resource").and_then(Value::as_str).unwrap_or(""),
                )
                .unwrap_or(false)
            });
            if !covered {
                uncovered.push(path.to_string());
            }
        }
    }
    (uncovered, locks)
}

fn task_from(meta: &Map<String, Value>, body: &str, path: &Path) -> Task {
    let folder = path
        .parent()
        .and_then(|parent| parent.file_name())
        .and_then(|name| name.to_str())
        .unwrap_or("active")
        .to_string();
    Task {
        meta: meta.clone(),
        body: body.to_string(),
        path: path.to_path_buf(),
        folder,
    }
}

pub fn start_branch(
    ws: &Workspace,
    task_id: &str,
    agent: &str,
    branch_type: &str,
    base: Option<&str>,
    force: bool,
    carry: bool,
) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    if path.parent() != Some(ws.active_dir().as_path()) {
        eprintln!("The task is already in done/. Start a branch before finishing it.");
        return Ok(1);
    }
    let (meta, body, _) = store::parse_task(&path)?;
    let task = task_from(&meta, &body, &path);
    let task_id = task.id();
    if let Some(error) = store::task_owner_error(&task, agent, force) {
        eprintln!("{error}");
        return Ok(1);
    }
    let state = git::state(ws);
    if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
        eprintln!("Not a git repository.");
        return Ok(1);
    }
    let config = git::config(ws);
    let isolated = config.isolation == "worktree";
    if !isolated && !carry && !git_clean(ws, &ws.project, true) {
        eprintln!(
            "Working tree has product changes (uncommitted or untracked files outside tasks/specs/config). \
             If they belong to this task, carry them onto the new branch: \
             `ai git start --task {task_id} --agent {agent} --carry`. \
             Otherwise commit or stash them first."
        );
        return Ok(1);
    }
    if !config.branch_types.iter().any(|name| name == branch_type) {
        eprintln!(
            "Unknown branch type '{branch_type}'. Use one of: {}.",
            config.branch_types.join(", ")
        );
        return Ok(1);
    }
    if !git::branch_exists(&ws.project, &config.integration) {
        eprintln!(
            "Integration branch '{}' is missing. Run `ai git setup`.",
            config.integration
        );
        return Ok(1);
    }
    let base = base.map(ToString::to_string).unwrap_or_else(|| {
        if branch_type == "hotfix" {
            config.production.clone()
        } else {
            config.integration.clone()
        }
    });
    if !git::branch_exists(&ws.project, &base) {
        eprintln!("Base branch '{base}' does not exist.");
        return Ok(1);
    }
    let branch = git::task_branch_name(&task, branch_type);
    let (ok, owned, error) = acquire_git_guard(ws, agent, &task_id, 600)?;
    if !ok {
        eprintln!("{error}");
        return Ok(1);
    }
    let mut meta = meta;
    let mut body = body;
    let mut worktree_path: Option<PathBuf> = None;
    let mut action = String::new();
    let result = (|| -> Result<Option<i32>> {
        if isolated {
            let (made, created, note) = worktrees::create(ws, &meta, &branch, &base);
            if !made {
                eprintln!("Could not create the worktree for {branch}: {note}");
                return Ok(Some(1));
            }
            meta.insert("worktree".into(), json!(relative_to(&ws.root, &created)));
            worktree_path = Some(created);
            action = format!("{note} worktree on");
        } else {
            let current = git::state(ws)
                .get("branch")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            if git::branch_exists(&ws.project, &branch) {
                if current.as_deref() != Some(&branch) {
                    let output = git::run_git(&ws.project, &["checkout", &branch]);
                    if output.code != 0 {
                        eprintln!("Could not switch to {branch}: {}", output.stderr);
                        return Ok(Some(1));
                    }
                }
                action = "switched to".to_string();
            } else {
                let output = git::run_git(&ws.project, &["checkout", "-b", &branch, &base]);
                if output.code != 0 {
                    eprintln!("Could not create {branch}: {}", output.stderr);
                    return Ok(Some(1));
                }
                action = "created".to_string();
            }
        }
        Ok(None)
    })();
    release_git_guard(ws, owned, agent);
    if let Some(code) = result? {
        return Ok(code);
    }
    meta.insert("branch".into(), json!(branch));
    meta.insert("updated".into(), json!(iso(None)));
    body = format!(
        "{}\n- {} {action} branch {branch} from {base} by {agent}\n",
        body.trim_end_matches('\n'),
        iso(None)
    );
    {
        let _guard = workspace_state_guard(ws)?;
        store::write_task(&path, &meta, &body)?;
        board::write_board(ws, &store::load_tasks(ws))?;
    }
    if let Some(worktree_path) = &worktree_path {
        println!(
            "{} {branch} from {base}.",
            action
                .chars()
                .enumerate()
                .map(|(index, ch)| if index == 0 {
                    ch.to_ascii_uppercase()
                } else {
                    ch
                })
                .collect::<String>()
        );
        println!("  worktree: {}", worktree_path.display());
        println!(
            "  Edit product files ONLY there (cd into it). Run the workspace CLI by absolute path:"
        );
        println!("  {} now --agent {agent}", cli_command(ws));
    } else {
        println!(
            "{} {branch} from {base}.",
            action
                .chars()
                .enumerate()
                .map(|(index, ch)| if index == 0 {
                    ch.to_ascii_uppercase()
                } else {
                    ch
                })
                .collect::<String>()
        );
        println!("Task {task_id} now points at that branch. Commit only files you own.");
    }
    Ok(0)
}

pub fn setup(ws: &Workspace, yes: bool, json_out: bool) -> Result<i32> {
    let state = git::state(ws);
    if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
        if let Some(error) = state.get("error").and_then(Value::as_str) {
            if error.to_lowercase().contains("dubious ownership") {
                eprintln!(
                    "Git found this repository but refused it because its ownership is untrusted. \
                     Ask the user to approve this exact checkout with `git config --global --add \
                     safe.directory \"{}\"`, then rerun `ai git setup`. Do not use a wildcard safe.directory entry.",
                    ws.project.to_string_lossy().replace('\\', "/")
                );
                return Ok(1);
            }
            if !error.to_lowercase().contains("not a git repository") {
                eprintln!("Could not inspect the project Git repository: {error}");
                return Ok(1);
            }
        }
    }
    let config = git::config(ws);
    let mut initialized = false;
    let mut created_production = false;
    let mut created_integration = false;
    let mut created_baseline = false;
    let mut checked_out_integration = false;
    let mut fast_forwarded_integration = false;

    if !git::state(ws)
        .get("repo")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let mut output = git::run_git(
            &ws.project,
            &["init", &format!("--initial-branch={}", config.production)],
        );
        if output.code != 0 {
            let lowered = output.stderr.to_lowercase();
            if lowered.contains("unknown option")
                || lowered.contains("unrecognized option")
                || lowered.contains("unknown switch")
            {
                output = git::run_git(&ws.project, &["init"]);
            }
        }
        if output.code != 0 {
            eprintln!(
                "Could not initialize Git in {}: {}",
                ws.project.display(),
                output.stderr
            );
            return Ok(1);
        }
        let reference = format!("refs/heads/{}", config.production);
        let symbolic = git::run_git(&ws.project, &["symbolic-ref", "HEAD", &reference]);
        if symbolic.code != 0 {
            eprintln!(
                "Could not select the production branch: {}",
                symbolic.stderr
            );
            return Ok(1);
        }
        initialized = true;
    }
    let template_rel = config.template.trim_start_matches("./");
    let template_rel = if template_rel.starts_with(".ai/") {
        template_rel.trim_start_matches(".ai/")
    } else {
        template_rel
    };
    let template = ws
        .root
        .join(template_rel.replace('/', std::path::MAIN_SEPARATOR_STR));
    if !template.is_file() {
        eprintln!(
            "Commit template not found: {}",
            relative_to(&ws.project, &template)
        );
        return Ok(1);
    }
    let configured = git::run_git(
        &ws.project,
        &["config", "--local", "--get", "commit.template"],
    );
    let current_template = configured.stdout.trim().to_string();
    let same = !current_template.is_empty()
        && crate::core::workspace::same_path(Path::new(&current_template), &template);
    if configured.code != 0 || !same {
        let value = if Path::new(&current_template).is_absolute() {
            template.to_string_lossy().to_string()
        } else {
            relative_to(&ws.project, &template)
        };
        let output = git::run_git(
            &ws.project,
            &["config", "--local", "commit.template", &value],
        );
        if output.code != 0 {
            eprintln!("Could not set commit.template: {}", output.stderr);
            return Ok(1);
        }
    }
    let production_ref = format!("refs/heads/{}", config.production);
    let mut state = git::state(ws);
    if !state.get("head").and_then(Value::as_str).is_some() {
        if git::branch_exists(&ws.project, &config.production) {
            // nothing to do
        } else {
            let symbolic = git::run_git(&ws.project, &["symbolic-ref", "HEAD", &production_ref]);
            if symbolic.code != 0 {
                eprintln!(
                    "Could not select production branch '{}': {}",
                    config.production, symbolic.stderr
                );
                return Ok(1);
            }
            if !confirm_initial_baseline(ws, &config.production, yes, json_out)? {
                return Ok(2);
            }
            created_baseline = true;
            created_production = true;
        }
        state = git::state(ws);
        if !state.get("head").and_then(Value::as_str).is_some() {
            let symbolic = git::run_git(&ws.project, &["symbolic-ref", "HEAD", &production_ref]);
            if symbolic.code != 0 {
                eprintln!(
                    "Could not select production branch '{}': {}",
                    config.production, symbolic.stderr
                );
                return Ok(1);
            }
            state = git::state(ws);
        }
        if !state.get("head").and_then(Value::as_str).is_some() {
            eprintln!("Gitflow setup could not establish a committed production base.");
            return Ok(1);
        }
    } else if !git::branch_exists(&ws.project, &config.production) {
        let head = state
            .get("head")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if head.is_empty() {
            eprintln!("Cannot create the production branch: current HEAD has no commit.");
            return Ok(1);
        }
        let output = git::run_git(&ws.project, &["branch", &config.production, &head]);
        if output.code != 0 {
            eprintln!(
                "Could not create production branch '{}': {}",
                config.production, output.stderr
            );
            return Ok(1);
        }
        created_production = true;
    }
    if !git::branch_exists(&ws.project, &config.integration) {
        let production_commit = commit_id(&ws.project, &production_ref);
        let production_commit = match production_commit {
            Some(commit) => commit,
            None => {
                eprintln!(
                    "Cannot create integration branch '{}': production branch '{}' has no commit.",
                    config.integration, config.production
                );
                return Ok(1);
            }
        };
        let output = git::run_git(
            &ws.project,
            &["branch", &config.integration, &production_commit],
        );
        if output.code != 0 {
            eprintln!(
                "Could not create integration branch '{}': {}",
                config.integration, output.stderr
            );
            return Ok(1);
        }
        created_integration = true;
    }
    let current = git::state(ws)
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if current != config.integration
        && (created_integration || current == config.production || current == "detached")
    {
        let output = git::run_git(&ws.project, &["checkout", &config.integration]);
        if output.code != 0 {
            eprintln!(
                "Could not switch to the integration branch '{}': {}\nRun this yourself, then rerun setup: git checkout {}",
                config.integration, output.stderr, config.integration
            );
            return Ok(1);
        }
        checked_out_integration = true;
    }
    let production_commit = commit_id(&ws.project, &format!("refs/heads/{}", config.production));
    let integration_commit = commit_id(&ws.project, &format!("refs/heads/{}", config.integration));
    if let (Some(production_commit), Some(integration_commit)) =
        (production_commit, integration_commit)
    {
        let contains = git::run_git(
            &ws.project,
            &[
                "merge-base",
                "--is-ancestor",
                &production_commit,
                &integration_commit,
            ],
        );
        if contains.code != 0 {
            let behind = git::run_git(
                &ws.project,
                &[
                    "merge-base",
                    "--is-ancestor",
                    &integration_commit,
                    &production_commit,
                ],
            );
            if behind.code != 0 {
                eprintln!(
                    "Integration branch '{}' and production branch '{}' have diverged; refusing to rewrite either. \
                     Merge them deliberately, then rerun setup:\n  git checkout {}\n  git merge {}",
                    config.integration, config.production, config.integration, config.production
                );
                return Ok(1);
            }
            if git::state(ws).get("branch").and_then(Value::as_str)
                != Some(config.integration.as_str())
            {
                eprintln!(
                    "Integration branch '{}' does not contain production's latest commit. Run this yourself, then rerun setup:\n  git checkout {}\n  git merge --ff-only {}",
                    config.integration, config.integration, config.production
                );
                return Ok(1);
            }
            let output = git::run_git(&ws.project, &["merge", "--ff-only", &config.production]);
            if output.code != 0 {
                eprintln!(
                    "Could not fast-forward '{}' to '{}': {}. Commit or stash the listed files, then rerun setup.\n  git checkout {}\n  git merge --ff-only {}",
                    config.integration, config.production, output.stderr, config.integration, config.production
                );
                return Ok(1);
            }
            fast_forwarded_integration = true;
        }
    }
    if json_out {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "repo": true,
                "commitTemplate": relative_to(&ws.project, &template).replace('\\', "/"),
                "integration": config.integration,
                "production": config.production,
                "initializedRepository": initialized,
                "createdBaseline": created_baseline,
                "createdProduction": created_production,
                "createdIntegration": created_integration,
                "checkedOutIntegration": checked_out_integration,
                "fastForwardedIntegration": fast_forwarded_integration,
                "head": git::state(ws).get("branch"),
            }))?
        );
        return Ok(0);
    }
    println!("commit.template = {}", relative_to(&ws.project, &template));
    if initialized {
        println!("Git repository: initialized");
    }
    if created_baseline {
        println!(
            "production branch: {} (created with the confirmed baseline)",
            config.production
        );
    } else {
        println!(
            "production branch: {}{}",
            config.production,
            if created_production {
                " (created)"
            } else {
                " (exists)"
            }
        );
    }
    println!(
        "integration branch: {}{}",
        config.integration,
        if created_integration {
            " (created)"
        } else {
            " (exists)"
        }
    );
    if fast_forwarded_integration {
        println!(
            "integration branch: fast-forwarded to {}",
            config.production
        );
    }
    println!(
        "HEAD: {}{}",
        git::state(ws)
            .get("branch")
            .and_then(Value::as_str)
            .unwrap_or("-"),
        if checked_out_integration {
            " (checked out)"
        } else {
            ""
        }
    );
    println!("Next: ai task claim <id> --agent <name>, then ai git start ...");
    Ok(0)
}

fn commit_id(cwd: &Path, revision: &str) -> Option<String> {
    let output = git::run_git(
        cwd,
        &[
            "rev-parse",
            "--verify",
            "--quiet",
            &format!("{revision}^{{commit}}"),
        ],
    );
    if output.code == 0 && !output.stdout.is_empty() {
        Some(output.stdout)
    } else {
        None
    }
}

fn sensitive(path: &str) -> bool {
    let re = Regex::new(
        r"(?i)(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx)|id_(rsa|dsa|ecdsa|ed25519)|credentials(\..*)?|secrets?(\..*)?)$",
    )
    .expect("static regex");
    re.is_match(path)
}

fn confirm_initial_baseline(
    ws: &Workspace,
    production: &str,
    assume_yes: bool,
    json_out: bool,
) -> Result<bool> {
    let listed = git::run_git(
        &ws.project,
        &["ls-files", "--cached", "--others", "--exclude-standard"],
    );
    if listed.code != 0 {
        eprintln!(
            "Could not list files for the initial Git baseline: {}",
            listed.stderr
        );
        return Ok(false);
    }
    let files: Vec<&str> = listed
        .stdout
        .lines()
        .filter(|line| !line.is_empty())
        .collect();
    if assume_yes {
        let risky: Vec<&str> = files
            .iter()
            .copied()
            .filter(|path| sensitive(path))
            .collect();
        if !risky.is_empty() {
            eprintln!(
                "Refusing --yes: the baseline would commit files that look like secrets: {}. \
                 Add them to .gitignore (or review in a terminal without --yes).",
                risky.iter().take(8).copied().collect::<Vec<_>>().join(", ")
            );
            return Ok(false);
        }
        println!(
            "Committing the initial baseline ({} file(s), confirmed with --yes):",
            files.len()
        );
        for path in files.iter().take(30) {
            println!("  {path}");
        }
        if files.len() > 30 {
            println!("  ... and {} more", files.len() - 30);
        }
    } else if json_out {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "repo": true,
                "baselineConfirmationRequired": true,
                "production": production,
                "files": files,
            }))?
        );
        return Ok(false);
    } else {
        use std::io::{IsTerminal, Write};
        if !std::io::stdin().is_terminal() {
            eprintln!(
                "Initial Git baseline needs the user's confirmation and no terminal is attached. \
                 If the user already agreed to Git (ai setup), run `ai git setup --yes`; it lists \
                 the files and refuses secrets. Otherwise run `ai git setup` in a terminal."
            );
            return Ok(false);
        }
        println!("Gitflow needs an initial production commit so task branches can start cleanly.");
        println!("The following non-ignored project files will be included:");
        for path in &files {
            println!("  {path}");
        }
        if files.is_empty() {
            println!("  (no files; an empty baseline commit will be created)");
        }
        print!("Type 'commit project baseline' to continue: ");
        let _ = std::io::stdout().flush();
        let mut confirmation = String::new();
        let _ = std::io::stdin().read_line(&mut confirmation);
        if confirmation.trim() != "commit project baseline" {
            eprintln!("Confirmation did not match; no project files were staged or committed.");
            return Ok(false);
        }
    }
    let output = git::run_git(&ws.project, &["add", "-A"]);
    if output.code != 0 {
        eprintln!(
            "Could not stage the initial project baseline: {}",
            output.stderr
        );
        return Ok(false);
    }
    let output = git::run_git(
        &ws.project,
        &[
            "commit",
            "--allow-empty",
            "-m",
            "chore: initialize repository",
        ],
    );
    if output.code != 0 {
        eprintln!(
            "Could not create the initial baseline commit. Configure Git author identity if needed, then rerun setup: {}",
            output.stderr
        );
        return Ok(false);
    }
    Ok(true)
}

/// Commit planning artifacts (task files, specs, board) to the integration
/// branch so every task worktree starts with the current ledger.
///
/// Only coordination paths are staged: a moved (deleted) task is committed as a
/// deletion when Git already tracks it, untracked files are skipped, and a
/// nothing-to-commit run is a silent no-op.
pub fn commit_ledger(ws: &Workspace, paths: &[PathBuf], message: &str) -> Option<String> {
    if !git::config(ws).enabled {
        return None;
    }
    let state = git::state(ws);
    if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
        return None;
    }
    let mut rels: Vec<String> = Vec::new();
    for path in paths {
        let relative = match path.strip_prefix(&ws.project) {
            Ok(rest) => rest.to_string_lossy().replace('\\', "/"),
            Err(_) => continue,
        };
        if !git::is_workspace_ledger_path(ws, &relative) || rels.contains(&relative) {
            continue;
        }
        if !path.exists() {
            let tracked = git::run_git(
                &ws.project,
                &["ls-files", "--error-unmatch", "--", &relative],
            );
            if tracked.code != 0 {
                continue;
            }
        }
        rels.push(relative);
    }
    if rels.is_empty() {
        return None;
    }
    let integration = git::config(ws).integration;
    let current = state.get("branch").and_then(Value::as_str).unwrap_or("");
    if !integration.is_empty()
        && current != integration
        && git::branch_exists(&ws.project, &integration)
        && git_clean(ws, &ws.project, true)
    {
        let output = git::run_git(&ws.project, &["checkout", &integration]);
        if output.code != 0 {
            eprintln!(
                "WARN  the ledger was committed on '{current}', not '{integration}': {}",
                last_line(&output.stderr)
            );
        }
    }
    let mut add = vec!["add", "--"];
    add.extend(rels.iter().map(String::as_str));
    let output = git::run_git(&ws.project, &add);
    if output.code != 0 {
        eprintln!(
            "WARN  the ledger was not staged: {}",
            last_line(&output.stderr)
        );
        return None;
    }
    let mut diff = vec!["diff", "--cached", "--quiet", "--"];
    diff.extend(rels.iter().map(String::as_str));
    if git::run_git(&ws.project, &diff).code == 0 {
        return None;
    }
    let mut commit = vec!["commit", "-m", message, "--"];
    commit.extend(rels.iter().map(String::as_str));
    let output = git::run_git(&ws.project, &commit);
    if output.code != 0 {
        eprintln!(
            "WARN  the task ledger was written but not committed: {}. Commit tasks/, specs/ and tasks/BOARD.md manually.",
            last_line(&output.stderr)
        );
        return None;
    }
    let short = git::run_git(&ws.project, &["rev-parse", "--short", "HEAD"]);
    if short.code == 0 && !short.stdout.is_empty() {
        Some(short.stdout)
    } else {
        None
    }
}

pub fn commit_task_metadata(
    ws: &Workspace,
    cwd: &Path,
    task_path: &Path,
    message: &str,
    amend: bool,
) -> Option<String> {
    let board = ws.board_path();
    let paths = [task_path.to_path_buf(), board];
    let rels: Vec<String> = paths
        .iter()
        .filter(|path| path.exists())
        .map(|path| relative_to(&ws.project, path).replace('\\', "/"))
        .collect();
    if rels.is_empty() {
        return None;
    }
    let mut add = vec!["add", "--"];
    add.extend(rels.iter().map(String::as_str));
    let output = git::run_git(cwd, &add);
    if output.code != 0 {
        eprintln!(
            "WARN  task metadata was not committed (git add): {}",
            last_line(&output.stderr)
        );
        return None;
    }
    let state = git::state_at(cwd);
    let staged: Vec<String> = state
        .get("staged")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(|item| item.replace('\\', "/"))
                .collect()
        })
        .unwrap_or_default();
    let owned: Vec<&str> = rels
        .iter()
        .map(String::as_str)
        .filter(|path| staged.iter().any(|staged_path| staged_path == path))
        .collect();
    if owned.is_empty() {
        return None;
    }
    if amend {
        let unexpected: Vec<&str> = staged
            .iter()
            .map(String::as_str)
            .filter(|path| !rels.iter().any(|rel| rel == path))
            .collect();
        if !unexpected.is_empty() {
            eprintln!(
                "WARN  task metadata was not amended: unrelated staged paths ({}) stay staged and out of the commit.",
                unexpected.iter().take(5).copied().collect::<Vec<_>>().join(", ")
            );
            return None;
        }
        let output = git::run_git(cwd, &["commit", "--amend", "--no-edit"]);
        if output.code != 0 {
            eprintln!(
                "WARN  task metadata was not committed (git commit): {}",
                last_line(&output.stderr)
            );
            return None;
        }
    } else {
        let mut args = vec!["commit", "-m", message, "--"];
        args.extend(owned.iter().copied());
        let output = git::run_git(cwd, &args);
        if output.code != 0 {
            eprintln!(
                "WARN  task metadata was not committed (git commit): {}",
                last_line(&output.stderr)
            );
            return None;
        }
    }
    let short = git::run_git(cwd, &["rev-parse", "--short", "HEAD"]);
    if short.code == 0 && !short.stdout.is_empty() {
        Some(short.stdout)
    } else {
        None
    }
}

fn last_line(text: &str) -> &str {
    text.lines().last().unwrap_or("unknown error")
}

#[allow(clippy::too_many_arguments)]
pub fn commit_flow(
    ws: &Workspace,
    task_id: &str,
    agent: &str,
    commit_type: &str,
    scope_name: Option<&str>,
    message: &str,
    body: &str,
    allow_empty: bool,
    verify: bool,
    no_verify: bool,
    force: bool,
    ci: Option<&str>,
    json_out: bool,
) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    if path.parent() != Some(ws.active_dir().as_path()) {
        eprintln!("The task is already in done/; no commit is needed.");
        return Ok(1);
    }
    let (mut meta, mut body_text, _) = store::parse_task(&path)?;
    let task = task_from(&meta, &body_text, &path);
    let task_id = task.id();
    if let Some(error) = store::task_owner_error(&task, agent, force) {
        eprintln!("{error}");
        return Ok(1);
    }
    let branch = task.get_str("branch").unwrap_or_default();
    if branch.is_empty() {
        eprintln!(
            "Task {task_id} has no branch. Run `ai git start --task {task_id} --agent {agent}`."
        );
        return Ok(1);
    }
    let cwd = git::task_checkout(ws, &task);
    let current = git::state_at(&cwd)
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if current != branch {
        // A harness or a manual step can move the main checkout back to the
        // integration branch between turns. Recover when that is safe instead
        // of stranding the worker with a commit it cannot make.
        if git::task_root(ws, &task).is_none()
            && git::branch_exists(&ws.project, &branch)
            && git_clean(ws, &ws.project, true)
        {
            let output = git::run_git(&ws.project, &["checkout", &branch]);
            if output.code != 0 {
                eprintln!("Could not switch back to {branch}: {}", output.stderr);
                return Ok(1);
            }
            println!("Recovered the task checkout: switched {current} -> {branch}.");
        } else {
            eprintln!("Current branch is {current}, but task {task_id} uses {branch}.");
            return Ok(1);
        }
    }
    if !crate::cmd::capabilities::COMMIT_TYPES.contains(&commit_type) {
        eprintln!(
            "Unknown commit type '{commit_type}'. Use one of: {}.",
            crate::cmd::capabilities::COMMIT_TYPES.join(", ")
        );
        return Ok(1);
    }
    let message = message.split_whitespace().collect::<Vec<_>>().join(" ");
    if message.is_empty() {
        eprintln!("Commit message is empty.");
        return Ok(1);
    }
    let scope_text = scope_name.unwrap_or("").trim().to_string();
    if !scope_text.is_empty()
        && !Regex::new(r"^[a-z0-9_.-]+$")
            .expect("static regex")
            .is_match(&scope_text)
    {
        eprintln!("Scope must be lowercase letters, digits, dot, dash or underscore.");
        return Ok(1);
    }
    let subject = if scope_text.is_empty() {
        format!("{commit_type}: {message}")
    } else {
        format!("{commit_type}({scope_text}): {message}")
    };
    let state = git::state_at(&cwd);
    let staged = state
        .get("staged")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if staged.is_empty() && !allow_empty {
        eprintln!("Nothing is staged. Stage only the files you own, then retry.");
        return Ok(1);
    }
    let staged_paths: Vec<String> = staged
        .iter()
        .filter_map(Value::as_str)
        .map(ToString::to_string)
        .collect();
    let scope_paths: Vec<String> = staged_paths
        .iter()
        .map(|path| crate::core::fsio::normalize_rel_path(path))
        .collect();
    let problems = scope::violations(&meta, &scope_paths);
    if !problems.is_empty() && !force {
        eprintln!("Refusing commit; staged paths leave the scope of task {task_id}:");
        for item in &problems {
            eprintln!("  {item}");
        }
        eprintln!("Unstage them, or widen the task's scope_allowed/scope_forbidden deliberately.");
        return Ok(1);
    }
    let declared = meta
        .get("locks")
        .map(|value| !value.is_null())
        .unwrap_or(false)
        || meta
            .get("scope_allowed")
            .map(|value| !value.is_null())
            .unwrap_or(false);
    let verify = verify || (declared && !no_verify);
    if verify {
        let (uncovered, _) = uncovered_staged(ws, &state);
        if !uncovered.is_empty() {
            eprintln!("Refusing commit; staged paths have no held file lock:");
            for item in &uncovered {
                eprintln!("  {item}");
            }
            eprintln!("Run `ai lock acquire <path>` for each, or pass `--no-verify` deliberately.");
            return Ok(1);
        }
    }
    let (ok, owned, error) = acquire_git_guard(ws, agent, &task_id, 600)?;
    if !ok {
        eprintln!("{error}");
        return Ok(1);
    }
    let trailers = format!("Task: {task_id}\nAgent: {agent}");
    let body_with_trailers = if body.trim().is_empty() {
        trailers
    } else {
        format!("{}\n\n{trailers}", body.trim())
    };
    let mut commit_args = vec!["commit", "-m", &subject, "-m", &body_with_trailers];
    if allow_empty {
        commit_args.push("--allow-empty");
    }
    let output = git::run_git(&cwd, &commit_args);
    if output.code != 0 {
        release_git_guard(ws, owned, agent);
        eprintln!("git commit failed: {}", output.stderr);
        return Ok(1);
    }
    let mut short = git::run_git(&cwd, &["rev-parse", "--short", "HEAD"]).stdout;
    meta.insert("updated".into(), json!(iso(None)));
    body_text = format!(
        "{}\n- {} committed: {subject}\n",
        body_text.trim_end_matches('\n'),
        iso(None)
    );
    if let Some(ci) = ci.filter(|value| !value.is_empty()) {
        body_text.push_str(&format!("- {} CI: {ci}\n", iso(None)));
    }
    {
        let _guard = workspace_state_guard(ws)?;
        store::write_task(&path, &meta, &body_text)?;
        board::write_board(ws, &store::load_tasks(ws))?;
    }
    if let Some(amended) = commit_task_metadata(ws, &cwd, &path, "", true) {
        short = amended;
    }
    release_git_guard(ws, owned, agent);
    if json_out {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "task": task_id,
                "branch": branch,
                "commit": short,
                "subject": subject,
            }))?
        );
    } else {
        println!("{short} {subject}");
    }
    Ok(0)
}

pub fn finish_flow(
    ws: &Workspace,
    task_id: &str,
    agent: &str,
    force: bool,
    json_out: bool,
) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (mut meta, mut body, _) = store::parse_task(&path)?;
    let task_id = meta
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or(task_id)
        .to_string();
    let submitter = meta
        .get("submitted_by")
        .and_then(Value::as_str)
        .unwrap_or("");
    let solo_self = gates::allows_self_review(ws) && !submitter.is_empty() && submitter == agent;
    if !force && !solo_self {
        if let Err(denied) = roles::authorize(ws, Some(agent), "git.finish") {
            eprintln!("{denied}");
            return Ok(1);
        }
    }
    if !force && !gates::allows_self_review(ws) && !submitter.is_empty() && submitter == agent {
        eprintln!(
            "Task {task_id} was submitted by {submitter}; the producer never merges its own work. \
             A different agent must run `ai git finish` (or choose the solo playbook)."
        );
        return Ok(1);
    }
    let branch = meta
        .get("branch")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if branch.is_empty() {
        eprintln!("Task {task_id} has no branch to merge.");
        return Ok(1);
    }
    let status = meta.get("status").and_then(Value::as_str).unwrap_or("");
    if !matches!(status, "review" | "done") && !force {
        eprintln!(
            "Task {task_id} is {}; move it to review after a separate verification, or use --force.",
            if status.is_empty() { "unknown" } else { status }
        );
        return Ok(1);
    }
    if !git_clean(ws, &ws.project, true) {
        eprintln!("Working tree has product changes. Commit or stash before merging.");
        return Ok(1);
    }
    let task = task_from(&meta, &body, &path);
    let cwd = git::task_checkout(ws, &task);
    let leftover: Vec<Value> = git::state_at(&cwd)
        .get("dirty")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter(|path| {
                    path.as_str()
                        .map(|path| !worktrees::BRIEFING_FILES.contains(&path))
                        .unwrap_or(true)
                })
                .cloned()
                .collect()
        })
        .unwrap_or_default();
    if !leftover.is_empty() {
        let listed = leftover
            .iter()
            .take(5)
            .filter_map(Value::as_str)
            .collect::<Vec<_>>()
            .join(", ");
        eprintln!(
            "The task worktree has uncommitted changes ({listed}). The producer must commit them before the merge."
        );
        return Ok(1);
    }
    if !git::branch_exists(&ws.project, &branch) {
        eprintln!("Task branch '{branch}' does not exist.");
        return Ok(1);
    }
    let config = git::config(ws);
    let integration = config.integration.clone();
    if !git::branch_exists(&ws.project, &integration) {
        eprintln!("Integration branch '{integration}' is missing. Run `ai git setup`.");
        return Ok(1);
    }
    let (ok, owned, error) =
        acquire_git_guard(ws, agent, &task_id, 600 + checks_seconds_budget(ws))?;
    if !ok {
        eprintln!("{error}");
        return Ok(1);
    }
    let result = finish_inner(
        ws,
        &mut meta,
        &mut body,
        &path,
        &task_id,
        &branch,
        &integration,
        &config,
        &cwd,
        agent,
        &task,
        json_out,
    );
    release_git_guard(ws, owned, agent);
    result
}

#[allow(clippy::too_many_arguments)]
fn finish_inner(
    ws: &Workspace,
    meta: &mut Map<String, Value>,
    body: &mut String,
    path: &Path,
    task_id: &str,
    branch: &str,
    integration: &str,
    config: &GitConfig,
    cwd: &Path,
    agent: &str,
    task: &Task,
    json_out: bool,
) -> Result<i32> {
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("ai"));
    let mut check = Command::new(exe);
    check
        .arg("check")
        .arg("--strict")
        .arg("--task")
        .arg(task_id);
    if !agent.is_empty() {
        check.arg("--agent").arg(agent);
    }
    if !gates::check_required(ws) {
        check.arg("--allow-empty");
    }
    check.current_dir(cwd);
    if json_out {
        check.stdout(std::process::Stdio::null());
        check.stderr(std::process::Stdio::inherit());
    } else {
        check.stdout(std::process::Stdio::inherit());
        check.stderr(std::process::Stdio::inherit());
    }
    let status = check.status().map_err(crate::core::error::AiError::from)?;
    if !status.success() {
        eprintln!("ai check --strict failed; refusing to merge.");
        return Ok(1);
    }
    if !heartbeat_git_guard(ws, agent) {
        eprintln!(
            "The git index guard expired while the checks ran; nothing was merged. Run `ai git finish` again."
        );
        return Ok(1);
    }
    let worktree = git::task_root(ws, task);
    if cwd != ws.project && worktree.is_some() {
        // already in the task worktree
    } else {
        let state_now = git::state(ws);
        let current = state_now
            .get("branch")
            .and_then(Value::as_str)
            .unwrap_or("");
        if current != branch {
            let output = git::run_git(&ws.project, &["checkout", branch]);
            if output.code != 0 {
                eprintln!("Could not switch to {branch}: {}", output.stderr);
                return Ok(1);
            }
        }
    }
    let output = git::run_git(&ws.project, &["checkout", integration]);
    if output.code != 0 {
        eprintln!("Could not switch to {integration}: {}", output.stderr);
        return Ok(1);
    }
    let merge_message = format!("merge: {branch} ({task_id})");
    let merge_flag = if config.merge == "ff" {
        "--ff"
    } else {
        "--no-ff"
    };
    let output = git::run_git(
        &ws.project,
        &["merge", merge_flag, branch, "-m", &merge_message],
    );
    if output.code != 0 {
        let abort = git::run_git(&ws.project, &["merge", "--abort"]);
        if abort.code == 0 {
            eprintln!("Merge failed and was aborted: {}", output.stderr);
        } else {
            eprintln!(
                "Merge failed and could NOT be aborted ({}); the repository is still mid-merge. \
                 Resolve it manually before retrying: {}",
                if abort.stderr.is_empty() {
                    "git merge --abort failed".to_string()
                } else {
                    abort.stderr.clone()
                },
                if output.stderr.is_empty() {
                    "unknown merge error".to_string()
                } else {
                    output.stderr.clone()
                }
            );
        }
        return Ok(1);
    }
    let merged_head = git::run_git(&ws.project, &["rev-parse", "--short", "HEAD"]).stdout;
    let mut deleted = false;
    if let Some(worktree) = worktree {
        let (freed, note) = worktrees::remove(ws, &worktree, true);
        if !freed {
            eprintln!("WARN  merged, but could not remove the worktree: {note}");
        } else {
            meta.insert("worktree".into(), Value::Null);
        }
    }
    if config.delete_after_merge {
        let output = git::run_git(&ws.project, &["branch", "-d", branch]);
        if output.code == 0 {
            deleted = true;
        } else {
            eprintln!(
                "WARN  merged, but could not delete {branch}: {}",
                output.stderr
            );
        }
        meta.insert("branch".into(), Value::Null);
    }
    meta.insert("merged_into".into(), json!(integration));
    meta.insert("merged_at".into(), json!(iso(None)));
    meta.insert("updated".into(), json!(iso(None)));
    *body = format!(
        "{}\n- {} merged {branch} into {integration} by {agent}\n",
        body.trim_end_matches('\n'),
        iso(None)
    );
    {
        let _guard = workspace_state_guard(ws)?;
        store::write_task(path, meta, body)?;
        board::write_board(ws, &store::load_tasks(ws))?;
    }
    commit_task_metadata(
        ws,
        &ws.project,
        path,
        &format!("chore(task): record merge {task_id}"),
        false,
    );
    append_event(
        ws,
        "task_merged",
        &[
            ("task", json!(task_id)),
            ("agent", json!(agent)),
            ("branch", json!(branch)),
            ("integration", json!(integration)),
        ],
    );
    if json_out {
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "task": task_id,
                "branch": branch,
                "integration": integration,
                "mergeCommit": merged_head,
                "branchDeleted": deleted,
            }))?
        );
    } else {
        println!("Merged {branch} into {integration} ({merged_head}).");
        println!(
            "{}",
            if deleted {
                "Branch deleted."
            } else {
                "Branch kept."
            }
        );
    }
    Ok(0)
}

/// Kept for callers that only need the exit code of a refused start.
pub fn start_error(message: impl Into<String>) -> Result<i32> {
    let _ = fail::<()>(message);
    Ok(1)
}
