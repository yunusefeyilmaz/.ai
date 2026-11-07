//! Ported from `lib/tests/test_capabilities.py`.
//!
//! `ai capabilities` is derived from the parser, so the contract cannot drift.
//! The tests build the same clap parser the CLI builds and compare it with the
//! published JSON.

mod support;

use std::collections::BTreeMap;

use clap::CommandFactory;
use serde_json::Value;
use support::Ws;

/// Every command path the CLI defines, mapped to its option strings.
fn parser_contract() -> BTreeMap<String, Vec<String>> {
    fn walk(prefix: &str, command: &clap::Command, out: &mut BTreeMap<String, Vec<String>>) {
        let mut flags: Vec<String> = Vec::new();
        for argument in command.get_arguments() {
            if let Some(long) = argument.get_long() {
                flags.push(format!("--{long}"));
            }
            if let Some(short) = argument.get_short() {
                flags.push(format!("-{short}"));
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

    let cli = ai::cli::Cli::command();
    let mut contract = BTreeMap::new();
    for command in cli.get_subcommands() {
        walk(command.get_name(), command, &mut contract);
    }
    contract
}

fn published(ws: &Ws) -> Value {
    ws.ok(&["capabilities", "--json"]).json()
}

#[test]
fn every_parser_command_is_published() {
    let ws = Ws::new("ai-capabilities-commands-");
    let payload = published(&ws);
    let commands = payload["commands"].as_object().expect("commands map");
    let contract = parser_contract();
    let missing: Vec<&str> = contract
        .keys()
        .filter(|path| !path.contains(' '))
        .map(String::as_str)
        .filter(|path| !commands.contains_key(*path))
        .collect::<Vec<_>>();
    assert!(missing.is_empty(), "missing from capabilities: {missing:?}");
}

#[test]
fn every_parser_flag_is_published_for_its_command() {
    let ws = Ws::new("ai-capabilities-flags-");
    let payload = published(&ws);
    let flags = payload["flags"].as_object().expect("flags map");
    let mut problems: Vec<String> = Vec::new();
    for (path, expected) in parser_contract() {
        let listed: Vec<&str> = flags
            .get(&path)
            .and_then(Value::as_array)
            .map(|items| items.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        let missing: Vec<&String> = expected
            .iter()
            .filter(|flag| !listed.contains(&flag.as_str()))
            .collect();
        if !missing.is_empty() {
            problems.push(format!("{path}: missing {missing:?}"));
        }
    }
    assert!(problems.is_empty(), "{problems:#?}");
}

#[test]
fn the_flags_that_drifted_are_published() {
    let ws = Ws::new("ai-capabilities-drift-");
    let payload = published(&ws);
    let check: Vec<&str> = payload["flags"]["check"]
        .as_array()
        .expect("check flags")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    for flag in ["--task", "--agent", "--no-commands"] {
        assert!(check.contains(&flag), "check is missing {flag}: {check:?}");
    }
    let task_next: Vec<&str> = payload["flags"]["task next"]
        .as_array()
        .expect("task next flags")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    assert!(task_next.contains(&"--review"), "{task_next:?}");
}

#[test]
fn every_published_command_has_a_real_description() {
    let ws = Ws::new("ai-capabilities-descriptions-");
    let payload = published(&ws);
    let commands = payload["commands"].as_object().expect("commands");
    let unpublished: Vec<&str> = commands
        .iter()
        .filter(|(_, text)| text.as_str().unwrap_or("").contains("--help"))
        .map(|(name, _)| name.as_str())
        .collect();
    assert!(
        unpublished.is_empty(),
        "add these to the descriptions table: {unpublished:?}"
    );
}

#[test]
fn a_subcommand_path_carries_its_own_flags() {
    let ws = Ws::new("ai-capabilities-sub-");
    let payload = published(&ws);
    let setup: Vec<&str> = payload["flags"]["setup"]
        .as_array()
        .expect("setup flags")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    assert!(setup.contains(&"--set"), "{setup:?}");

    let changes: Vec<&str> = payload["flags"]["task request-changes"]
        .as_array()
        .expect("request-changes flags")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    assert!(changes.contains(&"--reason"), "{changes:?}");
}

#[test]
fn the_payload_keeps_the_stable_vocabularies() {
    let ws = Ws::new("ai-capabilities-vocab-");
    let payload = published(&ws);
    assert_eq!(payload["name"], "ai");
    assert_eq!(payload["version"], ai::core::workspace::VERSION);
    for state in ["todo", "in_progress", "review", "blocked", "done"] {
        assert!(
            payload["task_states"]
                .as_array()
                .expect("states")
                .iter()
                .any(|item| item == state),
            "missing state {state}"
        );
    }
    for kind in ["feat", "fix", "docs", "refactor"] {
        assert!(
            payload["commit_types"]
                .as_array()
                .expect("commit types")
                .iter()
                .any(|item| item == kind),
            "missing commit type {kind}"
        );
    }
    assert!(payload["adapter_contract"].is_object(), "{payload}");
}
