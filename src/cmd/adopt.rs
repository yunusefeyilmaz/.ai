//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use serde_json::Value;

use crate::config::adopt;
use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::{relative_to, Workspace};
use crate::git::flow as gitflow;
use crate::git::repo as git;
use crate::runtime::dirs;

use crate::AdoptArgs;
pub fn run(ws: &Workspace, args: &AdoptArgs) -> Result<i32> {
    if !args.check {
        dirs::ensure_dirs(ws)?;
    }
    if !args.check {
        let _ = config::ensure_config(ws)?;
    }
    if args.print {
        println!("{}", adopt::ROOT_BLOCK);
        return Ok(0);
    }
    if !args.check {
        if let Some(path) = adopt::detach_template_git(ws)? {
            println!("MOVED      .ai/.git -> {path}");
        }
    }
    if ws.root.file_name().and_then(|name| name.to_str()) != Some(".ai") || ws.project == ws.root {
        println!("Template install detected: the workspace is the project root.");
        println!("Root AGENTS.md already acts as the signpost; no wiring needed.");
        if !args.check {
            println!("Run `ai doctor` to verify the workspace.");
        }
        return Ok(0);
    }
    // A newly cloned workspace is often the only entry in an empty project.
    // In that case adopt can establish the host repository too, so the first
    // command leaves Gitflow ready instead of asking for a second step. An
    // existing product tree keeps the deliberate `ai git setup` confirmation.
    let bootstrap_git = !args.check && host_has_no_product_files(ws) && config::git_enabled(ws);
    let results = adopt::adopt_root(ws, args.force, args.check)?;
    for (path, state) in &results {
        println!("{:<10} {path}", state.to_uppercase());
    }
    let (ignore_state, missing_ignore) = adopt::adopt_gitignore(ws, args.check)?;
    println!("{:<10} .gitignore", ignore_state.to_uppercase());
    if !missing_ignore.is_empty() {
        println!("Missing ignore rules: {}", missing_ignore.join(", "));
    }
    let (attributes_state, _) = adopt::adopt_gitattributes(ws, args.check)?;
    println!("{:<10} .gitattributes", attributes_state.to_uppercase());
    if args.check {
        let missing = results.iter().any(|(_, state)| state != "ok")
            || !missing_ignore.is_empty()
            || attributes_state != "ok";
        return Ok(if missing { 1 } else { 0 });
    }
    if args.ci {
        let _ = adopt::write_ci(ws)?;
    }
    if bootstrap_git
        && !git::state(ws)
            .get("repo")
            .and_then(Value::as_bool)
            .unwrap_or(false)
    {
        match gitflow::setup(ws, true, false) {
            Ok(0) => {}
            Ok(_) => eprintln!("WARN  Git baseline needs attention; run `ai git setup` after fixing the message above."),
            Err(error) => eprintln!("WARN  Git setup failed: {error}"),
        }
    }
    let baseline = commit_workspace_baseline(ws)?;
    println!("\nLocal adapters are in place. Each clone runs `ai adopt` to create its own copies.");
    println!("Next: ai doctor");
    Ok(baseline)
}

fn host_has_no_product_files(ws: &Workspace) -> bool {
    let Ok(entries) = std::fs::read_dir(&ws.project) else {
        return false;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if matches!(
            name.as_ref(),
            ".ai" | ".gitignore" | ".gitattributes" | ".DS_Store" | "Thumbs.db"
        ) {
            continue;
        }
        return false;
    }
    true
}

fn commit_workspace_baseline(ws: &Workspace) -> Result<i32> {
    let state = git::state(ws);
    if !state.get("repo").and_then(Value::as_bool).unwrap_or(false) {
        println!(
            "Git: no repository yet. `ai git setup` initializes it and commits the baseline (including .ai/ and .gitignore)."
        );
        return Ok(0);
    }
    if state.get("head").and_then(Value::as_str).is_none() {
        println!(
            "Git: the repository has no commit yet. Run `ai git setup`; its initial baseline commit includes .ai/ and .gitignore."
        );
        return Ok(0);
    }
    let cfg = git::config(ws);
    let integration = cfg.integration.clone();
    let mut paths = vec![ws.root.clone()];
    for extra in [
        ws.project.join(".gitignore"),
        ws.project.join(".gitattributes"),
    ] {
        if extra.exists() {
            paths.push(extra);
        }
    }
    if !git::branch_exists(&ws.project, &integration) {
        let base = git::run_git(
            &ws.project,
            &[
                "rev-parse",
                "--verify",
                &format!("refs/heads/{}", cfg.production),
            ],
        )
        .stdout;
        let base = if base.is_empty() {
            state
                .get("head")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string()
        } else {
            base
        };
        let output = git::run_git(&ws.project, &["branch", &integration, &base]);
        if output.code != 0 {
            eprintln!(
                "Could not create the integration branch '{integration}': {}",
                output.stderr
            );
            return Ok(1);
        }
    }
    if git::state(ws).get("branch").and_then(Value::as_str) != Some(integration.as_str()) {
        let output = git::run_git(&ws.project, &["checkout", &integration]);
        if output.code != 0 {
            eprintln!(
                "Could not switch to the integration branch '{integration}': {}",
                output.stderr
            );
            return Ok(1);
        }
    }
    let rels: Vec<String> = paths
        .iter()
        .map(|path| relative_to(&ws.project, path))
        .collect();
    let mut add = vec!["add", "-A", "--"];
    add.extend(rels.iter().map(String::as_str));
    let output = git::run_git(&ws.project, &add);
    if output.code != 0 {
        eprintln!("Could not stage the workspace baseline: {}", output.stderr);
        return Ok(1);
    }
    let mut diff = vec!["diff", "--cached", "--quiet", "--"];
    diff.extend(rels.iter().map(String::as_str));
    if git::run_git(&ws.project, &diff).code == 0 {
        println!("Workspace baseline already committed on {integration}; nothing to commit.");
    } else {
        let mut commit = vec!["commit", "-m", "chore: add ai workspace baseline", "--"];
        commit.extend(rels.iter().map(String::as_str));
        let output = git::run_git(&ws.project, &commit);
        if output.code != 0 {
            let mut reset = vec!["reset", "-q", "--"];
            reset.extend(rels.iter().map(String::as_str));
            let _ = git::run_git(&ws.project, &reset);
            eprintln!("Could not commit the workspace baseline: {}", output.stderr);
            return Ok(1);
        }
        println!("Workspace baseline committed on {integration}: chore: add ai workspace baseline");
    }
    println!("HEAD: {integration}");
    Ok(0)
}
