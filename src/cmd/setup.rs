//! `ai setup`: the chief's questionnaire about process.

use std::io::IsTerminal;

use crate::config::preferences::{self, PreferenceStatus};
use crate::config::settings::max_lock_ttl;
use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::git::flow as gitflow;

use crate::SetupArgs;

fn value_text(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Bool(true) => "yes".to_string(),
        serde_json::Value::Bool(false) => "no".to_string(),
        serde_json::Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

fn report(result: &PreferenceStatus) {
    let shown: Vec<String> = result
        .questions
        .iter()
        .filter(|row| row.answered)
        .map(|row| format!("{}={}", row.key, value_text(&row.current)))
        .collect();
    println!("Saved to config/workspace.json: {}", shown.join(", "));
    if !result.checks.is_empty() {
        println!("project checks: {}", result.checks.join(", "));
    }
    if result.confirmed {
        println!(
            "Preferences confirmed. Next: record the facts (`ai blueprint propose`), have the chief author the design (`ai blueprint propose --from <analysis.json>`), ask the user to approve or change it, then plan the work (`ai plan example`, then `ai plan apply plan.json --role chief`)."
        );
    } else {
        let missing: Vec<&str> = result
            .questions
            .iter()
            .filter(|row| preferences::REQUIRED_KEYS.contains(&row.key.as_str()) && !row.answered)
            .map(|row| row.key.as_str())
            .collect();
        println!("Still to ask the user: {}", missing.join(", "));
    }
}

pub fn run(ws: &Workspace, args: &SetupArgs) -> Result<i32> {
    if args.defaults && !args.yes {
        eprintln!(
            "`--defaults` accepts every recommended answer without asking the user, so an agent could fake the chief's required approval. \
             Ask the user first (`ai setup`, then `ai setup --set ...`); a human who wants the recommendations runs `ai setup --defaults --yes` in a terminal."
        );
        return Ok(1);
    }
    if args.defaults && !std::io::stdin().is_terminal() {
        eprintln!(
            "`--defaults --yes` needs an interactive terminal: the human confirms by running it, not an agent on a pipe. \
             Store explicit answers with `ai setup --set ...`."
        );
        return Ok(1);
    }
    if args.defaults
        || !args.set.is_empty()
        || !args.checks.is_empty()
        || !args.check_timeout.is_empty()
    {
        let mut answers = if args.defaults {
            preferences::defaults()
        } else {
            Vec::new()
        };
        for item in &args.set {
            match item.split_once('=') {
                Some((key, value)) => answers.push((key.trim().to_string(), value.to_string())),
                None => {
                    eprintln!("--set expects KEY=VALUE, got '{item}'");
                    return Ok(1);
                }
            }
        }
        let result = match preferences::apply(
            ws,
            &answers,
            &args.checks,
            &args.check_timeout,
            args.agent.as_deref(),
        ) {
            Ok(result) => result,
            Err(error) => {
                eprintln!("Cannot store the answers: {error}");
                return Ok(1);
            }
        };
        if args.json {
            println!("{}", serde_json::to_string_pretty(&result.to_json())?);
            return Ok(0);
        }
        report(&result);
        if !result.checks.is_empty() {
            let ceiling = max_lock_ttl(ws).saturating_sub(600);
            let budget = gitflow::checks_seconds_budget(ws);
            if budget >= ceiling {
                eprintln!(
                    "NOTE  the checks may take up to {budget}s, which is the ceiling `ai git finish` can hold the index guard (maxTtlSeconds {}s). \
                     Lower a check's timeoutSeconds, or raise locks.maxTtlSeconds.",
                    max_lock_ttl(ws)
                );
            }
        }
        return Ok(0);
    }
    let result = preferences::status(ws)?;
    if args.json {
        println!("{}", serde_json::to_string_pretty(&result.to_json())?);
        return Ok(0);
    }
    println!("Ask the user these questions (in their language), then store the answers.");
    for row in &result.questions {
        let mark = if row.answered { "answered" } else { "ASK" };
        println!(
            "  [{mark:<8}] {:<9} now={:<5} recommended={}",
            row.key,
            value_text(&row.current),
            value_text(&row.recommended)
        );
        if let Some(by) = &row.answered_by {
            if by != "unrecorded" {
                println!(
                    "             stored by {by}{}",
                    row.answered_at
                        .as_ref()
                        .map(|at| format!(" at {at}"))
                        .unwrap_or_default()
                );
            }
        }
        println!("             {}", row.ask);
    }
    if !result.checks.is_empty() {
        println!("  project checks: {}", result.checks.join(", "));
    }
    if result.confirmed {
        println!(
            "Preferences are confirmed. Next: plan the work with `ai plan apply <plan.json>` (see AGENTS.md, chief flow)."
        );
    } else {
        println!(
            "Store answers: ai setup --set review=yes checks=yes git=yes tests=yes continue=no workers=2 mode=lite playbook=pair \
             --check \"tests=<your test command>\"   (or `ai setup --defaults`)"
        );
    }
    Ok(0)
}
