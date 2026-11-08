//! Wire a subfolder workspace into the host project's AI tool configuration.

use std::fs;
use std::path::{Path, PathBuf};

use crate::core::error::Result;
use crate::core::fsio::{read_text, write_text_atomic};
use crate::core::workspace::{relative_to, Workspace};

pub const ROOT_BLOCK: &str = r#"<!-- ai-workspace:start -->
## AI workspace

This project uses the `.ai` engineering workspace. Task state, specs, locks,
checkpoints, logs and scratch artifacts live under `.ai/` and nowhere else.

Start every session with `.ai/ai now --agent <name>`: it prints the state and
the single next required command. `.ai/ai context` gives the project memory
(open work, shipped work, decisions) when you are new here.

Who you are decides what you may do. If the user gave you a job and there are no
tasks yet, you are the **chief**: do not write code and do not create tasks
yourself first. Run `.ai/ai now --agent <name> --role chief`, ask the user the
setup questions, then plan. Only the chief creates tasks; implementers claim
existing ones and reviewers review.

Checkpoint before the context window fills. Verify with
`.ai/ai check`; "done" requires its output.

Never create task notes, scratch files or generated logs outside `.ai/`.
<!-- ai-workspace:end -->
"#;

/// The workspace is private tooling that lives inside the host project, so the
/// whole `.ai/` folder stays out of the host repository. That also keeps a
/// cloned template `.git` from turning `.ai/` into an embedded repository.
pub const ADOPT_IGNORE_ENTRIES: &[&str] = &[
    ".ai/",
    "/AGENTS.md",
    "/CLAUDE.md",
    ".cursor/rules/ai-workspace.mdc",
    ".github/copilot-instructions.md",
    ".github/workflows/ai-check.yml",
];

/// Narrow rules written by older releases; `.ai/` now covers all of them, so a
/// rerun removes them instead of leaving a redundant list behind.
const SUPERSEDED_IGNORE_ENTRIES: &[&str] = &[".ai/runtime", ".ai/worktrees"];

pub const CI_WORKFLOW: &str = r#"name: ai-workspace

on:
  push:
  pull_request:

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Rust
        uses: dtolnay/rust-toolchain@stable

      - name: Build the workspace CLI
        run: cargo build --release --manifest-path .ai/Cargo.toml

      - name: Workspace health
        run: ./.ai/target/release/ai doctor --strict

      - name: Verification contract
        run: ./.ai/target/release/ai check --strict
"#;

fn upsert_managed(path: &Path, block: &str, force: bool) -> Result<String> {
    let start_marker = "<!-- ai-workspace:start -->";
    let end_marker = "<!-- ai-workspace:end -->";
    let existing = if path.exists() {
        read_text(path).unwrap_or_default()
    } else {
        String::new()
    };
    if existing.contains(start_marker) && existing.contains(end_marker) {
        if !force {
            return Ok("unchanged".to_string());
        }
        let start = existing.find(start_marker).unwrap_or(0);
        let end = existing.find(end_marker).unwrap_or(existing.len()) + end_marker.len();
        let updated = format!(
            "{}\n{}\n{}",
            existing[..start].trim_end_matches('\n'),
            block.trim(),
            existing[end..].trim_start_matches('\n')
        );
        write_text_atomic(path, &updated)?;
        return Ok("updated".to_string());
    }
    let separator = if existing.trim().is_empty() {
        ""
    } else {
        "\n\n"
    };
    let updated = format!(
        "{}{}{}\n",
        existing.trim_end_matches('\n'),
        separator,
        block.trim()
    );
    write_text_atomic(path, &updated)?;
    Ok("written".to_string())
}

pub fn adopt_root(ws: &Workspace, force: bool, check: bool) -> Result<Vec<(String, String)>> {
    let mut results = Vec::new();
    let targets: Vec<PathBuf> = vec![
        ws.project.join("AGENTS.md"),
        ws.project.join("CLAUDE.md"),
        ws.project
            .join(".cursor")
            .join("rules")
            .join("ai-workspace.mdc"),
        ws.project.join(".github").join("copilot-instructions.md"),
    ];
    for path in targets {
        let rel = relative_to(&ws.project, &path);
        if check {
            let existing = if path.exists() {
                read_text(&path).unwrap_or_default()
            } else {
                String::new()
            };
            let state = if existing.contains("<!-- ai-workspace:start -->") {
                "ok"
            } else {
                "missing"
            };
            results.push((rel, state.to_string()));
            continue;
        }
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        if path.extension().and_then(|ext| ext.to_str()) == Some("mdc") && !path.exists() {
            let text = format!(
                "---\ndescription: AI workspace entry rules\nalwaysApply: true\n---\n\n{}\n",
                ROOT_BLOCK.trim()
            );
            write_text_atomic(&path, &text)?;
            results.push((rel, "written".to_string()));
            continue;
        }
        results.push((rel, upsert_managed(&path, ROOT_BLOCK, force)?));
    }
    Ok(results)
}

fn normalized_ignore_entry(line: &str) -> Option<String> {
    let mut value = line.trim();
    if value.is_empty() || value.starts_with('#') || value.starts_with('!') {
        return None;
    }
    while let Some(rest) = value.strip_prefix('/') {
        value = rest;
    }
    let mut value = value.replace('\\', "/");
    if value.ends_with('/') {
        value.pop();
    }
    Some(value)
}

pub fn adopt_gitattributes(ws: &Workspace, check: bool) -> Result<(String, bool)> {
    let path = ws.project.join(".gitattributes");
    if path.exists() {
        return Ok(("ok".to_string(), false));
    }
    if check {
        return Ok(("missing".to_string(), true));
    }
    write_text_atomic(&path, "* text=auto eol=lf\n")?;
    Ok(("created".to_string(), true))
}

pub fn adopt_gitignore(ws: &Workspace, check: bool) -> Result<(String, Vec<String>)> {
    let path = ws.project.join(".gitignore");
    let existing = if path.exists() {
        fs::read_to_string(&path).unwrap_or_default()
    } else {
        String::new()
    };
    let lines: Vec<&str> = existing.lines().collect();
    let present: std::collections::HashSet<String> = lines
        .iter()
        .filter_map(|line| normalized_ignore_entry(line))
        .collect();
    let missing: Vec<String> = ADOPT_IGNORE_ENTRIES
        .iter()
        .filter(|entry| {
            normalized_ignore_entry(entry)
                .map(|value| !present.contains(&value))
                .unwrap_or(false)
        })
        .map(|entry| (*entry).to_string())
        .collect();
    let stale = |line: &&str| {
        normalized_ignore_entry(line)
            .map(|value| SUPERSEDED_IGNORE_ENTRIES.contains(&value.as_str()))
            .unwrap_or(false)
    };
    let has_stale = lines.iter().any(stale);
    if check {
        let state = if missing.is_empty() && !has_stale {
            "ok"
        } else {
            "missing"
        };
        return Ok((state.to_string(), missing));
    }
    if missing.is_empty() && !has_stale {
        return Ok(("unchanged".to_string(), Vec::new()));
    }
    let newline = if existing.contains("\r\n") {
        "\r\n"
    } else {
        "\n"
    };
    let has_header = lines.iter().any(|line| line.contains("Added by ai adopt"));
    let kept: String = lines
        .iter()
        .filter(|line| !stale(line))
        .map(|line| format!("{line}{newline}"))
        .collect();
    let mut addition = String::new();
    if !has_header {
        addition
            .push_str("# Added by ai adopt: the workspace stays local and out of version control.");
        addition.push_str(newline);
    }
    for entry in &missing {
        addition.push_str(entry);
        addition.push_str(newline);
    }
    write_text_atomic(&path, &format!("{kept}{addition}"))?;
    Ok((
        if existing.is_empty() {
            "created"
        } else {
            "updated"
        }
        .to_string(),
        missing,
    ))
}

pub fn write_ci(ws: &Workspace) -> Result<Option<String>> {
    let path = ws
        .project
        .join(".github")
        .join("workflows")
        .join("ai-check.yml");
    if path.exists() {
        return Ok(None);
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    write_text_atomic(&path, CI_WORKFLOW)?;
    Ok(Some(relative_to(&ws.project, &path)))
}
