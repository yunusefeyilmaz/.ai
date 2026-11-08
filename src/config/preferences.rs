//! The questions the chief asks the user, and where the answers go.
//!
//! `ai setup` prints them and stores the answers in `config/workspace.json`, so
//! every worker and reviewer follows the same rules.

use std::collections::BTreeSet;

use serde_json::{json, Map, Value};

use crate::config::settings::{get_dotted, load, save, set_dotted};
use crate::core::error::{fail, Result};
use crate::core::time::iso;
use crate::core::workspace::Workspace;

#[derive(Clone, Debug)]
pub struct Question {
    pub key: &'static str,
    pub dotted: &'static str,
    pub kind: &'static str,
    pub recommended: Value,
    pub ask: &'static str,
    /// Allowed values for `kind == "enum"`.
    pub values: &'static [&'static str],
}

pub const REQUIRED_KEYS: &[&str] = &["review", "checks", "git", "tests"];

pub fn questions() -> Vec<Question> {
    const NO_VALUES: &[&str] = &[];
    vec![
        Question {
            key: "review",
            dotted: "workflow.requireReview",
            kind: "bool",
            recommended: Value::Bool(true),
            ask: "Should finished work be reviewed before it ships? (in solo playbook you review your own work)",
            values: NO_VALUES,
        },
        Question {
            key: "checks",
            dotted: "workflow.requireCheck",
            kind: "bool",
            recommended: Value::Bool(true),
            ask: "Must the project's checks (tests, lint, build) pass before work goes to review? If yes, which commands? (add them with --check NAME=COMMAND)",
            values: NO_VALUES,
        },
        Question {
            key: "git",
            dotted: "git.enabled",
            kind: "bool",
            recommended: Value::Bool(true),
            ask: "Use Git: a branch per task, standard commits, and merging into develop?",
            values: NO_VALUES,
        },
        Question {
            key: "tests",
            dotted: "testing.writeTests",
            kind: "bool",
            recommended: Value::Bool(true),
            ask: "Should workers write tests for the behavior they add?",
            values: NO_VALUES,
        },
        Question {
            key: "continue",
            dotted: "workflow.autoContinue",
            kind: "bool",
            recommended: Value::Bool(false),
            ask: "After delivering a task, may a worker start the next one without asking you?",
            values: NO_VALUES,
        },
        Question {
            key: "workers",
            dotted: "orchestration.maxParallel",
            kind: "int",
            recommended: json!(1),
            ask: "How many workers may run at the same time? (more than 1 gives every task its own Git worktree)",
            values: NO_VALUES,
        },
        Question {
            key: "mode",
            dotted: "mode",
            kind: "enum",
            recommended: json!("lite"),
            ask: "How much process: lite (fast, fewer approvals) or strict (plan/spec/ship gates, and the user approves the plan)?",
            values: crate::config::blueprint::MODES,
        },
        Question {
            key: "plan",
            dotted: "workflow.requirePlanApproval",
            kind: "bool",
            recommended: Value::Bool(false),
            ask: "Must the user approve the plan (`ai plan apply ... --approved-by <user>`) before tasks are created?",
            values: NO_VALUES,
        },
        Question {
            key: "playbook",
            dotted: "workflow.playbook",
            kind: "enum",
            recommended: json!("pair"),
            ask: "Who does the work: solo (one agent designs, implements and reviews), pair (one implements, another reviews) or team (chief plans, workers implement, reviewers approve)?",
            values: crate::config::blueprint::PLAYBOOKS,
        },
    ]
}

#[derive(Clone, Debug)]
pub struct QuestionStatus {
    pub key: String,
    pub ask: String,
    pub kind: String,
    pub recommended: Value,
    pub current: Value,
    pub answered: bool,
    pub answered_by: Option<String>,
    pub answered_at: Option<String>,
}

#[derive(Clone, Debug)]
pub struct PreferenceStatus {
    pub confirmed: bool,
    pub questions: Vec<QuestionStatus>,
    pub checks: Vec<String>,
}

impl PreferenceStatus {
    pub fn to_json(&self) -> Value {
        json!({
            "confirmed": self.confirmed,
            "questions": self.questions.iter().map(|row| json!({
                "key": row.key,
                "ask": row.ask,
                "type": row.kind,
                "recommended": row.recommended,
                "current": row.current,
                "answered": row.answered,
                "answeredBy": row.answered_by,
                "answeredAt": row.answered_at,
            })).collect::<Vec<_>>(),
            "checks": self.checks,
        })
    }
}

pub fn status(ws: &Workspace) -> Result<PreferenceStatus> {
    let config = load(ws)?;
    status_of(&config)
}

pub fn status_of(config: &Value) -> Result<PreferenceStatus> {
    let prefs = config.get("preferences").cloned().unwrap_or(json!({}));
    let answered: BTreeSet<String> = prefs
        .get("answered")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default();
    let provenance = prefs.get("answers").cloned().unwrap_or(json!({}));
    let mut rows = Vec::new();
    for question in questions() {
        let mut current = get_dotted(config, question.dotted)
            .cloned()
            .unwrap_or(Value::Null);
        if question.key == "checks" && current == Value::String("strict".into()) {
            current = Value::Null;
        }
        let answered_by = provenance
            .get(question.key)
            .and_then(|p| p.get("by"))
            .and_then(Value::as_str)
            .map(ToString::to_string);
        let answered_at = provenance
            .get(question.key)
            .and_then(|p| p.get("at"))
            .and_then(Value::as_str)
            .map(ToString::to_string);
        rows.push(QuestionStatus {
            key: question.key.to_string(),
            ask: question.ask.to_string(),
            kind: question.kind.to_string(),
            recommended: question.recommended,
            current,
            answered: answered.contains(question.key),
            answered_by,
            answered_at,
        });
    }
    let confirmed = REQUIRED_KEYS.iter().all(|key| answered.contains(*key));
    let checks = config
        .get("checks")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(|check| {
                    check
                        .get("name")
                        .or_else(|| check.get("command"))
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string()
                })
                .collect()
        })
        .unwrap_or_default();
    Ok(PreferenceStatus {
        confirmed,
        questions: rows,
        checks,
    })
}

pub fn parse_value(kind: &str, raw: &str, values: &[&str]) -> Result<Value> {
    let text = raw.trim();
    if kind == "bool" {
        let lowered = text.to_lowercase();
        if ["yes", "y", "true", "1", "on"].contains(&lowered.as_str()) {
            return Ok(Value::Bool(true));
        }
        if ["no", "n", "false", "0", "off"].contains(&lowered.as_str()) {
            return Ok(Value::Bool(false));
        }
        return fail(format!("expected yes/no, got '{raw}'"));
    }
    if kind == "enum" {
        let lowered = text.to_lowercase();
        if let Some(canonical) = values.iter().find(|value| **value == lowered.as_str()) {
            return Ok(Value::String((*canonical).to_string()));
        }
        return fail(format!(
            "expected one of {}; got '{raw}'",
            values.join(", ")
        ));
    }
    let number: i64 = text
        .parse()
        .map_err(|_| crate::core::error::AiError::msg(format!("expected a number, got '{raw}'")))?;
    if !(1..=32).contains(&number) {
        return fail("expected a number between 1 and 32");
    }
    Ok(json!(number))
}

/// Validate and store answers (`key -> raw text`) and optional check commands.
pub fn apply(
    ws: &Workspace,
    answers: &[(String, String)],
    checks: &[String],
    check_timeouts: &[String],
    agent: Option<&str>,
) -> Result<PreferenceStatus> {
    let mut config = load(ws)?;
    let known: Map<String, Value> = questions()
        .into_iter()
        .map(|q| (q.key.to_string(), json!([q.dotted, q.kind, q.values])))
        .collect();
    let mut unknown: Vec<String> = Vec::new();
    for (key, _) in answers {
        if !known.contains_key(key) {
            unknown.push(key.clone());
        }
    }
    if !unknown.is_empty() {
        let names: Vec<String> = known.keys().cloned().collect();
        return fail(format!(
            "unknown setting(s): {}; use {}",
            unknown.join(", "),
            names.join(", ")
        ));
    }
    let who = agent
        .map(ToString::to_string)
        .or_else(|| std::env::var("AI_AGENT").ok())
        .unwrap_or_else(|| "unrecorded".to_string());
    let mut answered: BTreeSet<String> = config
        .get("preferences")
        .and_then(|p| p.get("answered"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default();
    for (key, raw) in answers {
        let (dotted, kind, values) = {
            let entry = known.get(key).expect("checked above");
            (
                entry[0].as_str().unwrap_or("").to_string(),
                entry[1].as_str().unwrap_or("bool").to_string(),
                entry[2]
                    .as_array()
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(Value::as_str)
                            .map(ToString::to_string)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default(),
            )
        };
        let allowed: Vec<&str> = values.iter().map(String::as_str).collect();
        let value = parse_value(&kind, raw, &allowed)?;
        set_dotted(&mut config, &dotted, value);
        answered.insert(key.clone());
        let prefs = config
            .as_object_mut()
            .expect("config object")
            .entry("preferences".to_string())
            .or_insert_with(|| json!({}));
        let prefs_object = prefs.as_object_mut().expect("preferences object");
        let provenance = prefs_object
            .entry("answers".to_string())
            .or_insert_with(|| json!({}));
        if let Some(answers_map) = provenance.as_object_mut() {
            answers_map.insert(key.clone(), json!({"by": who, "at": iso(None)}));
        }
    }
    if let Some((_, workers)) = answers.iter().find(|(key, _)| key == "workers") {
        let count = parse_value("int", workers, &[])?.as_i64().unwrap_or(1);
        set_dotted(
            &mut config,
            "git.isolation",
            Value::String(if count > 1 { "worktree" } else { "branch" }.to_string()),
        );
    }
    for item in checks {
        let (name, command) = match item.split_once('=') {
            Some((name, command)) if !name.trim().is_empty() && !command.trim().is_empty() => {
                (name.trim(), command.trim())
            }
            _ => return fail(format!("--check expects NAME=COMMAND, got '{item}'")),
        };
        let mut entries: Vec<Value> = config
            .get("checks")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        entries.retain(|entry| entry.get("name").and_then(Value::as_str) != Some(name));
        entries.push(json!({
            "name": name,
            "command": command,
            "addedBy": who,
            "addedAt": iso(None),
        }));
        set_dotted(&mut config, "checks", Value::Array(entries));
    }
    for item in check_timeouts {
        let (name, seconds) = match item.split_once('=') {
            Some((name, seconds)) if !name.trim().is_empty() => {
                let seconds: u64 = seconds.trim().parse().map_err(|_| {
                    crate::core::error::AiError::msg(format!(
                        "--check-timeout expects NAME=SECONDS with a positive number, got '{item}'"
                    ))
                })?;
                if seconds == 0 {
                    return fail("--check-timeout expects a positive number of seconds");
                }
                (name.trim().to_string(), seconds)
            }
            _ => {
                return fail(format!(
                    "--check-timeout expects NAME=SECONDS, got '{item}'"
                ))
            }
        };
        let mut entries: Vec<Value> = config
            .get("checks")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let found = entries
            .iter_mut()
            .find(|entry| entry.get("name").and_then(Value::as_str) == Some(name.as_str()));
        match found {
            Some(entry) => {
                entry["timeoutSeconds"] = json!(seconds);
            }
            None => {
                return fail(format!(
                    "--check-timeout: no configured check named '{name}'; add it first with --check {name}=<command>"
                ));
            }
        }
        set_dotted(&mut config, "checks", Value::Array(entries));
    }
    {
        let prefs = config
            .as_object_mut()
            .expect("config object")
            .entry("preferences".to_string())
            .or_insert_with(|| json!({}));
        let prefs_object = prefs.as_object_mut().expect("preferences object");
        prefs_object.insert(
            "answered".to_string(),
            Value::Array(answered.iter().map(|k| Value::String(k.clone())).collect()),
        );
        prefs_object.insert(
            "confirmed".to_string(),
            Value::Bool(REQUIRED_KEYS.iter().all(|key| answered.contains(*key))),
        );
        prefs_object.insert("at".to_string(), Value::String(iso(None)));
    }
    save(ws, &config)?;
    status_of(&config)
}

pub fn defaults() -> Vec<(String, String)> {
    questions()
        .into_iter()
        .map(|q| {
            let value = match q.recommended {
                Value::Bool(true) => "yes".to_string(),
                Value::Bool(false) => "no".to_string(),
                other => other.to_string().trim_matches('"').to_string(),
            };
            (q.key.to_string(), value)
        })
        .collect()
}
