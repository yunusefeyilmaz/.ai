//! Mechanical facts about the machine and the project.
//!
//! No language, framework or folder layout is inferred here: that judgement
//! belongs to the chief (the AI) and the user. This module only reports what it
//! can observe, so the proposal can be written against reality instead of a
//! hardcoded stack table.

use std::path::Path;

use serde_json::{json, Value};

use crate::config::settings::load_or_default;
use crate::core::process::run;
use crate::core::workspace::Workspace;

/// Hints, not support: binaries worth asking for a version. A project may use
/// anything else, and `blueprint.probes` in config extends this list.
const DEFAULT_PROBES: &[&str] = &[
    "cargo",
    "rustc",
    "node",
    "npm",
    "pnpm",
    "yarn",
    "bun",
    "deno",
    "python",
    "python3",
    "pip",
    "poetry",
    "uv",
    "go",
    "java",
    "mvn",
    "gradle",
    "dotnet",
    "php",
    "composer",
    "ruby",
    "bundle",
    "elixir",
    "mix",
    "dart",
    "swift",
    "clang",
    "gcc",
    "cmake",
    "make",
    "just",
    "bazel",
    "zig",
    "terraform",
    "docker",
    "git",
];

/// Probe binaries are allowed a short answer; a broken tool must not stall the
/// scan.
const PROBE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3);

fn probes(ws: &Workspace) -> Vec<String> {
    let config = load_or_default(ws);
    let configured: Vec<String> = config
        .get("blueprint")
        .and_then(|blueprint| blueprint.get("probes"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default();
    let mut seen = std::collections::BTreeSet::new();
    configured
        .into_iter()
        .chain(DEFAULT_PROBES.iter().map(|name| (*name).to_string()))
        .filter(|name| !name.trim().is_empty() && seen.insert(name.clone()))
        .collect()
}

fn version_of(binary: &str, cwd: &Path) -> Option<String> {
    let outcome = run(&format!("{binary} --version"), cwd, Some(PROBE_TIMEOUT));
    if outcome.timed_out || outcome.code != 0 {
        return None;
    }
    outcome
        .stdout
        .lines()
        .chain(outcome.stderr.lines())
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(|line| line.chars().take(120).collect())
}

fn top_level(project: &Path) -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(project)
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if entry.path().is_dir() {
                        format!("{name}/")
                    } else {
                        name
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    names.sort();
    names.truncate(200);
    names
}

fn tracked(ws: &Workspace) -> Value {
    let output = run("git ls-files", &ws.project, Some(PROBE_TIMEOUT));
    if output.code != 0 {
        return json!({"count": 0, "samples": []});
    }
    let paths: Vec<&str> = output
        .stdout
        .lines()
        .filter(|line| !line.is_empty())
        .collect();
    let samples: Vec<&str> = paths.iter().copied().take(120).collect();
    json!({"count": paths.len(), "samples": samples})
}

pub fn facts(ws: &Workspace) -> Value {
    let project = &ws.project;
    let tooling: Vec<Value> = probes(ws)
        .into_iter()
        .filter_map(|binary| {
            version_of(&binary, project)
                .map(|version| json!({"binary": binary, "version": version}))
        })
        .collect();
    let git = crate::git::repo::state(ws);
    json!({
        "os": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
        "shell": if cfg!(windows) { "cmd" } else { "sh" },
        "pathSeparator": std::path::MAIN_SEPARATOR.to_string(),
        "shape": ws.workspace_shape(),
        "git": {
            "repository": git.get("repo").and_then(Value::as_bool).unwrap_or(false),
            "branch": git.get("branch").cloned().unwrap_or(Value::Null),
            "tracked": tracked(ws),
        },
        "topLevel": top_level(project),
        "tooling": tooling,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn facts_carry_the_machine_and_the_tree() {
        let base = std::env::temp_dir().join(format!(
            "ai-blueprint-facts-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|value| value.as_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(base.join("src")).unwrap();
        std::fs::write(base.join("Cargo.toml"), "").unwrap();
        let ws = Workspace::at(&base);
        let facts = facts(&ws);
        assert_eq!(facts["os"], json!(std::env::consts::OS));
        let top: Vec<&str> = facts["topLevel"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .collect();
        assert!(top.contains(&"src/"), "{top:?}");
        assert!(top.contains(&"Cargo.toml"), "{top:?}");
        assert!(facts["tooling"].is_array());
        let _ = std::fs::remove_dir_all(&base);
    }
}
