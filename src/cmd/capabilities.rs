//! The machine-readable CLI contract, derived from the real clap parser.

use std::collections::BTreeMap;

use clap::CommandFactory;
use serde_json::{json, Map, Value};

use crate::config::roles::default_roles;
use crate::core::error::Result;
use crate::core::workspace::{Workspace, VERSION};
use crate::git::repo as git;
use crate::tasks::store::PRIORITY_ORDER;

pub const COMMIT_TYPES: &[&str] = &[
    "feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert",
];

pub const TASK_STATUSES: &[&str] = &[
    "todo",
    "in_progress",
    "review",
    "changes_requested",
    "blocked",
    "done",
];

fn descriptions() -> BTreeMap<String, &'static str> {
    let mut out = BTreeMap::new();
    for (name, text) in [
        ("init", "create the workspace state in a fresh checkout; --wire adds the root adapters"),
        ("setup", "chief: the questions for the user and where answers are stored"),
        ("blueprint", "propose | show | revise --set KEY=VALUE | approve --agent <name>: the user-approved architecture and conventions"),
        ("plan", "chief: apply <plan.json> creates linked tasks; example prints a skeleton"),
        ("version", "print the workspace version"),
        ("now", "10-line state + the single next required command"),
        ("context", "project memory: open/shipped work, ADRs, recent activity"),
        ("decision", "new | list architecture decision records"),
        ("worktree", "list | path <task> | prune [--force]: per-task Git worktrees"),
        ("history", "<id> [--evidence] [--json]: transition log and verification evidence"),
        ("review", "<id> [--stat] [--max-lines N] [--json]: read-only review package"),
        ("start", "one-command first run: prepare, detect Git, create or claim a task"),
        ("adopt", "wire root adapters for every AI tool"),
        ("doctor", "workspace health with a repair hint per finding"),
        ("check", "single verification contract"),
        ("status", "tasks, locks, checkpoints, handoffs"),
        ("ui", "live terminal dashboard (read-only)"),
        ("metrics", "summarize local workflow events"),
        ("reset", "--hard: interactively clear task/spec/decision/runtime state"),
        ("task", "new | list | show | link | ready | next [--review] | claim | release | review | request-changes | done | reopen | discard | block | unblock"),
        ("spec", "show | check <task-id> <n> | approve <task-id> --agent <user>"),
        ("lock", "acquire <resource...> [--wait SECONDS] | release | heartbeat | status"),
        ("checkpoint", "save resumable context"),
        ("resume", "print a compact resume brief with drift"),
        ("brief", "print a paste-ready brief for an external chat AI"),
        ("handoff", "write a marker and checkpoint for another agent"),
        ("recover", "detect or repair inconsistent state"),
        ("git", "setup | start | commit | finish | begin | end | verify"),
        ("artifact", "put | list | clean"),
        ("clean", "remove stale locks and logs"),
        ("capabilities", "this contract, derived from the parser"),
    ] {
        out.insert(name.to_string(), text);
    }
    out
}

fn walk(prefix: &str, command: &clap::Command, out: &mut BTreeMap<String, Vec<String>>) {
    let mut flags: Vec<String> = Vec::new();
    for argument in command.get_arguments() {
        if let Some(name) = argument.get_long() {
            flags.push(format!("--{name}"));
        }
        if let Some(name) = argument.get_short() {
            flags.push(format!("-{name}"));
        }
    }
    flags.sort();
    flags.dedup();
    out.insert(prefix.to_string(), flags);
    for sub in command.get_subcommands() {
        let name = sub.get_name().to_string();
        let path = if prefix.is_empty() {
            name
        } else {
            format!("{prefix} {name}")
        };
        walk(&path, sub, out);
    }
}

pub fn build(ws: &Workspace) -> Value {
    let mut contract = BTreeMap::new();
    let cli = crate::Cli::command();
    for command in cli.get_subcommands() {
        walk(command.get_name(), command, &mut contract);
    }
    let known = descriptions();
    let commands: BTreeMap<String, String> = contract
        .keys()
        .filter(|name| !name.contains(' '))
        .map(|name| {
            let text = known
                .get(name)
                .map(|text| text.to_string())
                .unwrap_or_else(|| format!("see `ai {name} --help`"));
            (name.clone(), text)
        })
        .collect();
    let git_config = git::config(ws);
    let mut payload = Map::new();
    payload.insert("name".into(), json!("ai"));
    payload.insert("version".into(), json!(VERSION));
    payload.insert("workspace".into(), json!(".ai"));
    payload.insert(
        "exit_codes".into(),
        json!({"0": "success", "1": "check failed or operation refused", "127": "binary not found"}),
    );
    payload.insert("task_states".into(), json!(TASK_STATUSES));
    payload.insert(
        "roles".into(),
        json!(default_roles().keys().cloned().collect::<Vec<_>>()),
    );
    payload.insert("commit_types".into(), json!(COMMIT_TYPES));
    payload.insert(
        "playbooks".into(),
        json!(crate::config::blueprint::PLAYBOOKS),
    );
    payload.insert("modes".into(), json!(crate::config::blueprint::MODES));
    payload.insert(
        "blueprint".into(),
        json!({
            "path": crate::config::blueprint::FILE,
            "statuses": ["missing", "pending", "approved"],
            "naming_keys": ["default", "files", "functions", "types", "constants", "json", "branches", "commits", "env"],
        }),
    );
    payload.insert(
        "state".into(),
        json!({
            "tasks": "tasks/active, tasks/done",
            "locks": "runtime/locks/*.lock (advisory, TTL leases)",
            "checkpoints": "runtime/state/checkpoints",
            "events": "runtime/state/events.jsonl and date-rotated local archives",
            "handoffs": "runtime/state/handoff",
            "artifacts": "runtime/artifacts",
        }),
    );
    payload.insert(
        "rules".into(),
        json!([
            "one task per agent session",
            "claim before editing",
            "live lock is a refusal",
            "producer never verifies its own work (except the solo playbook)",
            "checkpoint before the context window fills",
            "done requires ai check",
            "done requires review by a different agent than the producer unless workflow.playbook is solo",
            "chief proposes the architecture blueprint and the user approves it before planning",
            "strict mode (or workflow.requirePlanApproval) needs the user's --approved-by on ai plan apply",
        ]),
    );
    payload.insert("commands".into(), json!(commands));
    payload.insert("flags".into(), json!(contract));
    payload.insert("branch_types".into(), json!(git_config.branch_types));
    payload.insert("merge_strategy".into(), json!(git_config.merge));
    payload.insert(
        "adapter_contract".into(),
        json!({
            "schema_version": "0.1.0",
            "schema_path": "adapters/contract.schema.json",
            "adapter_dir": "adapters/",
            "state_paths": ["runtime/state/", "tasks/", "specs/"],
        }),
    );
    payload.insert(
        "priorities".into(),
        json!(PRIORITY_ORDER
            .iter()
            .map(|(name, _)| *name)
            .collect::<Vec<_>>()),
    );
    Value::Object(payload)
}

pub fn run(ws: &Workspace, _args: &crate::CapabilitiesArgs) -> Result<i32> {
    println!("{ }", serde_json::to_string_pretty(&build(ws))?);
    Ok(0)
}
