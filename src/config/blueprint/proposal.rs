//! Reading, validating and editing the chief's proposal.
//!
//! The proposal is open-ended JSON on purpose: `languages`, `architecture`,
//! `naming`, `layout`, `testing`, `checks`, `guidelines`, `workflow`, `git` are
//! the keys the CLI understands today, and any other key is accepted and
//! preserved. Only structural mistakes (wrong types, an unknown mode, a check
//! without a command) and the closed product enums are rejected.

use serde_json::{Map, Value};

use crate::config::blueprint::{MODES, PLAYBOOKS};
use crate::core::error::{fail, AiError, Result};

/// Keys whose presence means the chief actually authored the proposal.
const AUTHORED_KEYS: &[&str] = &[
    "languages",
    "architecture",
    "naming",
    "layout",
    "testing",
    "checks",
    "guidelines",
    "conventions",
    "standards",
];

pub fn questions() -> Value {
    serde_json::json!([
        "Which languages/toolchains should the project use? (facts.tooling lists what is installed; any language is allowed)",
        "Which architecture and folder layout fit the request?",
        "Which naming and formatting rules should every worker follow?",
        "Which checks prove the work (tests, lint, build)? Each needs a command.",
        "Which mode (lite/strict) and playbook (solo/pair/team) does the user want?",
        "Which rules should workers never break (for example: no new dependency without approval)?"
    ])
}

/// Accept either `{"proposal": {...}, ...}` or a bare proposal object.
pub fn extract(mut input: Value) -> Result<Value> {
    if let Some(proposal) = input.get_mut("proposal") {
        return match proposal.take() {
            Value::Object(map) => Ok(Value::Object(map)),
            _ => fail("blueprint `proposal` must be a JSON object"),
        };
    }
    match input {
        Value::Object(map) => Ok(Value::Object(map)),
        _ => fail("the blueprint input must be a JSON object"),
    }
}

pub fn authored(proposal: &Value) -> bool {
    let object = match proposal.as_object() {
        Some(object) => object,
        None => return false,
    };
    AUTHORED_KEYS.iter().any(|key| {
        object
            .get(*key)
            .map(|value| match value {
                Value::Null => false,
                Value::String(text) => !text.trim().is_empty(),
                Value::Array(items) => !items.is_empty(),
                Value::Object(map) => !map.is_empty(),
                _ => true,
            })
            .unwrap_or(false)
    })
}

pub fn validate(proposal: &Value) -> Result<()> {
    let object = proposal
        .as_object()
        .ok_or_else(|| AiError::msg("blueprint `proposal` must be a JSON object"))?;
    for key in ["languages", "layout", "guidelines", "checks"] {
        if let Some(value) = object.get(key) {
            if !value.is_array() {
                return fail(format!("blueprint `{key}` must be an array"));
            }
        }
    }
    if let Some(languages) = object.get("languages").and_then(Value::as_array) {
        for (index, language) in languages.iter().enumerate() {
            let named = language.is_string()
                || language
                    .as_object()
                    .and_then(|entry| entry.get("name"))
                    .and_then(Value::as_str)
                    .map(|name| !name.trim().is_empty())
                    .unwrap_or(false);
            if !named {
                return fail(format!(
                    "blueprint `languages[{index}]` must be a name or an object with a non-empty `name`"
                ));
            }
        }
    }
    for key in ["naming", "testing", "workflow", "git", "conventions"] {
        if let Some(value) = object.get(key) {
            if !value.is_object() {
                return fail(format!("blueprint `{key}` must be a JSON object"));
            }
        }
    }
    if let Some(workflow) = object.get("workflow").and_then(Value::as_object) {
        if let Some(mode) = workflow.get("mode").and_then(Value::as_str) {
            if !MODES.contains(&mode) {
                return fail(format!(
                    "blueprint workflow.mode must be one of: {}",
                    MODES.join(", ")
                ));
            }
        }
        if let Some(playbook) = workflow.get("playbook").and_then(Value::as_str) {
            if !PLAYBOOKS.contains(&playbook) {
                return fail(format!(
                    "blueprint workflow.playbook must be one of: {}",
                    PLAYBOOKS.join(", ")
                ));
            }
        }
        if let Some(workers) = workflow.get("workers") {
            match workers.as_u64() {
                Some(count) if (1..=32).contains(&count) => {}
                _ => return fail("blueprint workflow.workers must be a number between 1 and 32"),
            }
        }
    }
    if let Some(checks) = object.get("checks").and_then(Value::as_array) {
        for (index, check) in checks.iter().enumerate() {
            let command = check.get("command").and_then(Value::as_str);
            if command
                .map(|command| command.trim().is_empty())
                .unwrap_or(true)
            {
                return fail(format!(
                    "blueprint `checks[{index}]` needs a non-empty `command`"
                ));
            }
        }
    }
    Ok(())
}

/// A skeleton: enough to show the user what is missing, not a guess.
pub fn draft(facts: &Value, config: &Value) -> Value {
    let workflow = config.get("workflow").cloned().unwrap_or(Value::Null);
    let git = config.get("git").cloned().unwrap_or(Value::Null);
    serde_json::json!({
        "languages": [],
        "architecture": null,
        "layout": [],
        "naming": {},
        "testing": {},
        "checks": [],
        "guidelines": [],
        "workflow": {
            "mode": config.get("mode").and_then(Value::as_str).unwrap_or("lite"),
            "playbook": workflow
                .get("playbook")
                .and_then(Value::as_str)
                .unwrap_or("pair"),
            "workers": config
                .get("orchestration")
                .and_then(|value| value.get("maxParallel"))
                .and_then(Value::as_u64)
                .unwrap_or(1),
            "requireReview": workflow.get("requireReview").cloned().unwrap_or(Value::Bool(true)),
            "requireCheck": workflow.get("requireCheck").cloned().unwrap_or(Value::Bool(true)),
            "autoContinue": workflow.get("autoContinue").cloned().unwrap_or(Value::Bool(false)),
        },
        "git": {
            "integrationBranch": git.get("integrationBranch").cloned().unwrap_or(serde_json::json!("develop")),
            "productionBranch": git.get("productionBranch").cloned().unwrap_or(serde_json::json!("master")),
            "isolation": git.get("isolation").cloned().unwrap_or(serde_json::json!("branch")),
            "merge": git.get("merge").cloned().unwrap_or(serde_json::json!("no-ff")),
        },
        "note": format!(
            "Chief: replace this skeleton with your analysis of facts ({} top-level entries, {} files tracked). Any language or convention is allowed.",
            facts
                .get("topLevel")
                .and_then(Value::as_array)
                .map(Vec::len)
                .unwrap_or(0),
            facts
                .get("git")
                .and_then(|git| git.get("tracked"))
                .and_then(|tracked| tracked.get("count"))
                .and_then(Value::as_u64)
                .unwrap_or(0)
        ),
    })
}

/// Apply `a.b.0.c=value` edits to `document.proposal`.
pub fn apply_sets(document: &mut Value, sets: &[String]) -> Result<()> {
    for item in sets {
        let (path, raw) = item
            .split_once('=')
            .ok_or_else(|| AiError::msg(format!("--set expects PATH=VALUE, got '{item}'")))?;
        let path = path.trim();
        let path = path.strip_prefix("proposal.").unwrap_or(path);
        if path.is_empty() {
            return fail("--set needs a path, e.g. naming.files=PascalCase");
        }
        let value = parse_literal(raw.trim());
        set_path(document, path, value)?;
    }
    let proposal = document.get("proposal").cloned().unwrap_or(Value::Null);
    validate(&proposal)?;
    if let Some(object) = document.as_object_mut() {
        object.insert("authored".into(), serde_json::json!(authored(&proposal)));
    }
    Ok(())
}

fn parse_literal(raw: &str) -> Value {
    if raw.is_empty() {
        return Value::String(String::new());
    }
    let first = raw.chars().next().unwrap_or(' ');
    if matches!(first, '{' | '[') || matches!(raw, "true" | "false" | "null") {
        if let Ok(value) = serde_json::from_str(raw) {
            return value;
        }
    }
    if let Ok(number) = raw.parse::<i64>() {
        return serde_json::json!(number);
    }
    Value::String(raw.to_string())
}

fn set_path(document: &mut Value, path: &str, value: Value) -> Result<()> {
    let segments: Vec<&str> = path.split('.').filter(|part| !part.is_empty()).collect();
    if segments.is_empty() {
        return fail("--set needs a non-empty path");
    }
    let mut node = document
        .as_object_mut()
        .ok_or_else(|| AiError::msg("blueprint root must be an object"))?
        .entry("proposal".to_string())
        .or_insert_with(|| Value::Object(Map::new()));
    for (index, segment) in segments.iter().enumerate() {
        let last = index + 1 == segments.len();
        if let Ok(position) = segment.parse::<usize>() {
            let array = node
                .as_array_mut()
                .ok_or_else(|| AiError::msg(format!("'{segment}' needs an array above it")))?;
            if last {
                if position >= array.len() {
                    return fail(format!(
                        "index {position} is out of range for '{}' (length {})",
                        segments[..index].join("."),
                        array.len()
                    ));
                }
                array[position] = value;
                return Ok(());
            }
            node = array
                .get_mut(position)
                .ok_or_else(|| AiError::msg(format!("index {position} is out of range")))?;
        } else {
            let object = node
                .as_object_mut()
                .ok_or_else(|| AiError::msg(format!("'{segment}' needs an object above it")))?;
            if last {
                object.insert(segment.to_string(), value);
                return Ok(());
            }
            node = object
                .entry(segment.to_string())
                .or_insert_with(|| Value::Object(Map::new()));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn document() -> Value {
        serde_json::json!({"proposal": {"languages": [], "naming": {"files": "snake_case"}}})
    }

    #[test]
    fn arbitrary_languages_and_keys_are_accepted() {
        let proposal = serde_json::json!({
            "languages": ["Zig", {"name": "Gleam", "why": "erlang VM"}],
            "architecture": "actor-per-domain",
            "conventions": {"release": "trunk", "comments": "explain why"},
            "checks": [{"name": "zig", "command": "zig build test"}]
        });
        validate(&proposal).expect("any language is valid");
        assert!(authored(&proposal));
    }

    #[test]
    fn structural_mistakes_are_rejected() {
        assert!(validate(&serde_json::json!({"languages": "Rust"})).is_err());
        assert!(validate(&serde_json::json!({"workflow": {"mode": "turbo"}})).is_err());
        assert!(validate(&serde_json::json!({"checks": [{"name": "no command"}]})).is_err());
        assert!(validate(&serde_json::json!({"languages": [{"why": "no name"}]})).is_err());
    }

    #[test]
    fn sets_write_any_path_and_parse_literals() {
        let mut doc = document();
        apply_sets(
            &mut doc,
            &[
                "languages=[\"Rust\",\"Python\"]".into(),
                "naming.files=PascalCase".into(),
                "conventions.release=trunk".into(),
                "workflow.workers=4".into(),
            ],
        )
        .unwrap();
        assert_eq!(doc["proposal"]["languages"][1], serde_json::json!("Python"));
        assert_eq!(
            doc["proposal"]["naming"]["files"],
            serde_json::json!("PascalCase")
        );
        assert_eq!(
            doc["proposal"]["conventions"]["release"],
            serde_json::json!("trunk")
        );
        assert_eq!(doc["proposal"]["workflow"]["workers"], serde_json::json!(4));
        assert_eq!(doc["authored"], serde_json::json!(true));
    }

    #[test]
    fn an_empty_draft_is_not_authored() {
        let draft = draft(&serde_json::json!({"topLevel": []}), &serde_json::json!({}));
        assert!(!authored(&draft));
    }
}
