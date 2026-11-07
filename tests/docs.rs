//! Ported from `lib/tests/test_docs.py` (the checks that apply to this port).
//!
//! Documentation must not drift from the CLI: commands written in a guide are
//! checked against the real parser, and the version is consistent everywhere.

mod support;

use std::path::{Path, PathBuf};

use clap::CommandFactory;

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// Every command path the CLI defines, e.g. `task`, `task new`.
fn parser_tree() -> std::collections::BTreeSet<String> {
    fn walk(prefix: &str, command: &clap::Command, out: &mut std::collections::BTreeSet<String>) {
        for sub in command.get_subcommands() {
            let name = sub.get_name().to_string();
            let path = if prefix.is_empty() {
                name
            } else {
                format!("{prefix} {name}")
            };
            out.insert(path.clone());
            walk(&path, sub, out);
        }
    }
    let cli = ai::cli::Cli::command();
    let mut out = std::collections::BTreeSet::new();
    walk("", &cli, &mut out);
    out
}

fn doc_files() -> Vec<PathBuf> {
    let mut files = Vec::new();
    for name in [
        "README.md",
        "AGENTS.md",
        "GUIDE.md",
        "CHANGELOG.md",
        "PORTING.md",
        "tasks/README.md",
        "specs/README.md",
    ] {
        let path = repo().join(name.replace('/', std::path::MAIN_SEPARATOR_STR));
        if path.is_file() {
            files.push(path);
        }
    }
    for folder in ["docs", "agents", "prompts"] {
        let dir = repo().join(folder);
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().and_then(|ext| ext.to_str()) == Some("md") {
                    files.push(path);
                }
            }
        }
    }
    files
}

/// Backtick snippets and fenced blocks: where `ai <cmd>` examples live.
fn snippets(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut in_fence = false;
    for line in text.lines() {
        if line.trim_start().starts_with("```") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            out.push(line.to_string());
            continue;
        }
        let mut rest = line;
        while let Some(start) = rest.find('`') {
            let after = &rest[start + 1..];
            if let Some(end) = after.find('`') {
                out.push(after[..end].to_string());
                rest = &after[end + 1..];
            } else {
                break;
            }
        }
    }
    out
}

/// The first two words after `ai ` on a command line.
///
/// Mirrors the Python regex `(?:^|[\s`$(;&|])ai ([a-z][a-z-]*)`: the word must
/// start a command, not appear inside `.ai hard` or `.ai workspace`.
fn documented_commands(line: &str) -> Vec<(String, Option<String>)> {
    const PREFIXES: &[char] = &[' ', '\t', '`', '$', '(', ';', '&', '|'];
    let mut found = Vec::new();
    let bytes: Vec<char> = line.chars().collect();
    let mut index = 0;
    while index + 3 < bytes.len() {
        let at_command_start = index == 0 || PREFIXES.contains(&bytes[index - 1]);
        if at_command_start
            && bytes[index] == 'a'
            && bytes[index + 1] == 'i'
            && bytes[index + 2] == ' '
        {
            let mut cursor = index + 3;
            let mut words: Vec<String> = Vec::new();
            while cursor < bytes.len() && words.len() < 2 {
                while cursor < bytes.len() && bytes[cursor].is_whitespace() {
                    cursor += 1;
                }
                let start = cursor;
                while cursor < bytes.len()
                    && (bytes[cursor].is_ascii_lowercase() || bytes[cursor] == '-')
                {
                    cursor += 1;
                }
                if cursor == start {
                    break;
                }
                words.push(bytes[start..cursor].iter().collect());
            }
            if let Some(first) = words.first() {
                found.push((first.clone(), words.get(1).cloned()));
            }
            index = cursor.max(index + 1);
        } else {
            index += 1;
        }
    }
    found
}

#[test]
fn every_documented_ai_command_exists() {
    let tree = parser_tree();
    let mut problems: Vec<String> = Vec::new();
    for path in doc_files() {
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        for snippet in snippets(&text) {
            for line in snippet.lines() {
                for (top, second) in documented_commands(line) {
                    if !tree.contains(&top) {
                        problems.push(format!("{}: unknown command `ai {top}`", path.display()));
                        continue;
                    }
                    if let Some(second) = second {
                        let wanted = format!("{top} {second}");
                        let has_children =
                            tree.iter().any(|item| item.starts_with(&format!("{top} ")));
                        if has_children && !tree.contains(&wanted) {
                            problems.push(format!(
                                "{}: `ai {top}` has no subcommand `{second}`",
                                path.display()
                            ));
                        }
                    }
                }
            }
        }
    }
    problems.sort();
    problems.dedup();
    assert!(problems.is_empty(), "{problems:#?}");
}

#[test]
fn version_is_consistent() {
    let text = std::fs::read_to_string(repo().join("VERSION")).expect("read VERSION");
    assert_eq!(text.trim(), ai::core::workspace::VERSION);

    let changelog = std::fs::read_to_string(repo().join("CHANGELOG.md")).expect("read CHANGELOG");
    assert!(
        changelog.contains(&format!("## [{}]", ai::core::workspace::VERSION)),
        "CHANGELOG is missing an entry for {}",
        ai::core::workspace::VERSION
    );
    let cargo = std::fs::read_to_string(repo().join("Cargo.toml")).expect("read Cargo.toml");
    assert!(
        cargo.contains(&format!("version = \"{}\"", ai::core::workspace::VERSION)),
        "Cargo.toml version must match VERSION"
    );
}

#[test]
fn no_stale_paths_in_the_guides() {
    const STALE: &[&str] = &[
        "scripts/ai",
        "scripts\\ai",
        "lib/runtime/artifacts",
        "lib/tasks/active",
        "lib/specs/active",
    ];
    let mut problems: Vec<String> = Vec::new();
    for path in doc_files() {
        if path.file_name().and_then(|name| name.to_str()) == Some("CHANGELOG.md") {
            continue;
        }
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        for stale in STALE {
            if text.contains(stale) {
                problems.push(format!("{} mentions {stale}", path.display()));
            }
        }
    }
    assert!(problems.is_empty(), "{problems:#?}");
}

#[test]
fn agents_md_states_the_staleness_rule() {
    let path = repo().join("AGENTS.md");
    let text = std::fs::read_to_string(&path).expect("read AGENTS.md");
    assert!(
        text.contains("staleAfterSeconds"),
        "missing staleAfterSeconds"
    );
    assert!(text.contains("updated_at"), "missing updated_at");
    assert!(text.contains("PID"), "missing PID");
}

#[test]
fn porting_notes_describe_the_source_layout() {
    let text = std::fs::read_to_string(repo().join("PORTING.md")).expect("read PORTING.md");
    for needle in [
        "src/core/",
        "src/tasks/",
        "src/runtime/",
        "src/git/",
        "src/cmd/",
    ] {
        assert!(
            text.contains(needle),
            "PORTING.md does not mention {needle}"
        );
    }
    let _ = Path::new(".");
}
