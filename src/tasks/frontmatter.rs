//! Task/checkpoint front matter.
//!
//! The Python parser was deliberately strict: it reports structural problems
//! instead of silently guessing. The Rust port keeps the same rules so a task
//! file written by either implementation reads the same way in the other.
//!
//! Values are kept in insertion-ordered JSON maps; the canonical field order is
//! written back through `FRONTMATTER_ORDER`.

use regex::Regex;
use serde_json::{Map, Value};

pub const FRONTMATTER_ORDER: &[&str] = &[
    "id",
    "title",
    "status",
    "owner",
    "priority",
    "spec",
    "depends_on",
    "scope_allowed",
    "scope_forbidden",
    "locks",
    "branch",
    "worktree",
    "created",
    "updated",
    "lock",
];

pub const VALID_STATUSES: &[&str] = &[
    "todo",
    "in_progress",
    "review",
    "changes_requested",
    "blocked",
    "done",
];

#[derive(Clone, Debug, Default)]
pub struct Document {
    pub meta: Map<String, Value>,
    pub body: String,
    pub problems: Vec<String>,
}

/// Turn a YAML-style flow list into the canonical comma-separated value.
pub fn parse_flow_list(raw: &str) -> Result<Option<String>, String> {
    let text = raw.trim();
    let mut items: Vec<String> = Vec::new();
    let mut token = String::new();
    let mut quote: Option<char> = None;
    let mut closed = false;
    for (index, ch) in text.chars().enumerate() {
        if let Some(active) = quote {
            if ch == active {
                quote = None;
            } else if ch == '\\' && active == '"' {
                token.push(ch);
                continue;
            }
            token.push(ch);
            continue;
        }
        match ch {
            '\'' | '"' => {
                quote = Some(ch);
                token.push(ch);
            }
            '[' => {
                if index != 0 {
                    return Err(format!("nested flow list is not supported: {text:?}"));
                }
            }
            ']' => {
                let trailing: String = text.chars().skip(index + 1).collect();
                let trailing = trailing.trim();
                if !trailing.is_empty() {
                    return Err(format!("unexpected text after flow list: {trailing:?}"));
                }
                items.push(token.clone());
                token.clear();
                closed = true;
                break;
            }
            ',' => {
                items.push(token.clone());
                token.clear();
            }
            _ => token.push(ch),
        }
    }
    if !closed {
        return Err(format!("unterminated flow list: {text:?}"));
    }
    if quote.is_some() {
        return Err(format!("unterminated quote in flow list: {text:?}"));
    }
    let mut normalized: Vec<String> = Vec::new();
    for item in items {
        let mut item = item.trim().to_string();
        if item.is_empty() {
            continue;
        }
        let first = item.chars().next().unwrap_or(' ');
        if first == '\'' || first == '"' {
            if item.len() < 2 || !item.ends_with(first) {
                return Err(format!("unterminated quote in flow list item: {item:?}"));
            }
            item = item[1..item.len() - 1].trim().to_string();
        }
        if item.contains(',') {
            return Err(format!("flow-list item contains a comma: {item:?}"));
        }
        normalized.push(item);
    }
    if normalized.is_empty() {
        Ok(None)
    } else {
        Ok(Some(normalized.join(", ")))
    }
}

pub fn parse_value(raw: &str) -> Result<Value, String> {
    let value = raw.trim();
    if value.starts_with('[') {
        return Ok(match parse_flow_list(value)? {
            Some(text) => Value::String(text),
            None => Value::Null,
        });
    }
    if value.is_empty() || matches!(value, "null" | "~" | "None") {
        return Ok(Value::Null);
    }
    match value.to_lowercase().as_str() {
        "true" => return Ok(Value::Bool(true)),
        "false" => return Ok(Value::Bool(false)),
        _ => {}
    }
    if value.starts_with('"') {
        return match serde_json::from_str::<Value>(value) {
            Ok(Value::String(text)) => Ok(Value::String(text)),
            Ok(other) => Ok(other),
            Err(_) => Ok(Value::String(value.trim_matches('"').to_string())),
        };
    }
    // A single-quoted scalar is likewise a string.
    if value.starts_with('\'') && value.ends_with('\'') && value.len() >= 2 {
        return Ok(Value::String(value[1..value.len() - 1].to_string()));
    }
    Ok(Value::String(value.to_string()))
}

pub fn format_value(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(flag) => {
            if *flag {
                "true".to_string()
            } else {
                "false".to_string()
            }
        }
        Value::Number(number) => number.to_string(),
        Value::Array(items) => {
            let joined = items
                .iter()
                .map(format_scalar)
                .collect::<Vec<_>>()
                .join(", ");
            if joined.is_empty() {
                "null".to_string()
            } else {
                joined
            }
        }
        Value::Object(_) => serde_json::to_string(value).unwrap_or_else(|_| "null".to_string()),
        Value::String(text) => {
            if text.is_empty() {
                return "null".to_string();
            }
            let plain = Regex::new(r"^[A-Za-z0-9_./:-]+$").expect("static regex");
            if plain.is_match(text) && !text.starts_with('-') {
                text.clone()
            } else {
                serde_json::to_string(text).unwrap_or_else(|_| "\"\"".to_string())
            }
        }
    }
}

fn format_scalar(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        other => format_value(other),
    }
}

/// Parse `---` front matter without silently guessing.
pub fn parse_document(text: &str) -> Document {
    let mut problems: Vec<String> = Vec::new();
    if !text.starts_with("---") {
        return Document {
            meta: Map::new(),
            body: text.to_string(),
            problems: vec!["missing front matter".to_string()],
        };
    }
    let rest = &text[3..];
    let end = match rest.find("\n---") {
        Some(index) => index,
        None => {
            return Document {
                meta: Map::new(),
                body: text.to_string(),
                problems: vec!["unterminated front matter (no closing ---)".to_string()],
            }
        }
    };
    let head = rest[..end].trim_matches('\n');
    let body = rest[end + 4..].trim_start_matches('\n').to_string();
    let mut meta: Map<String, Value> = Map::new();
    let mut block_key: Option<String> = None;
    let mut block_lines: Vec<String> = Vec::new();
    let mut block_separator = " ";

    fn flush_block(
        key: &mut Option<String>,
        lines: &mut Vec<String>,
        separator: &str,
        meta: &mut Map<String, Value>,
    ) {
        if let Some(name) = key.take() {
            meta.insert(name, Value::String(lines.join(separator)));
            lines.clear();
        }
    }

    for line in head.lines() {
        let stripped = line.trim();
        if stripped.is_empty() || stripped.starts_with('#') {
            continue;
        }
        if line.starts_with(' ') || line.starts_with('\t') {
            if block_key.is_some() {
                block_lines.push(stripped.to_string());
            } else {
                problems.push(format!("stray indented line: {stripped:?}"));
            }
            continue;
        }
        let (key, raw) = match line.split_once(':') {
            Some((key, value)) => (key.trim().to_string(), value.trim().to_string()),
            None => {
                problems.push(format!("line without a colon: {stripped:?}"));
                continue;
            }
        };
        flush_block(&mut block_key, &mut block_lines, block_separator, &mut meta);
        let duplicate = meta.contains_key(&key);
        if duplicate {
            problems.push(format!("duplicate key: {key}"));
        }
        if matches!(raw.as_str(), "|" | "|-" | ">" | ">-") {
            block_separator = if raw.starts_with('|') { "\n" } else { " " };
            block_key = Some(key.clone());
            meta.entry(key).or_insert(Value::Null);
            continue;
        }
        match parse_value(&raw) {
            Ok(value) => {
                meta.insert(key, value);
            }
            Err(message) => {
                problems.push(format!("{key}: {message}"));
                meta.insert(key, Value::Null);
            }
        }
    }
    flush_block(&mut block_key, &mut block_lines, block_separator, &mut meta);
    Document {
        meta,
        body,
        problems,
    }
}

/// Validate required task fields; an empty list means the file is valid.
pub fn validate_task_meta(meta: &Map<String, Value>) -> Vec<String> {
    let mut errors = Vec::new();
    if meta
        .get("id")
        .and_then(Value::as_str)
        .map(str::trim)
        .unwrap_or("")
        .is_empty()
    {
        errors.push("missing required field: id".to_string());
    }
    if meta
        .get("title")
        .and_then(Value::as_str)
        .map(str::trim)
        .unwrap_or("")
        .is_empty()
    {
        errors.push("missing required field: title".to_string());
    }
    let status = meta.get("status").and_then(Value::as_str).unwrap_or("");
    if !VALID_STATUSES.contains(&status) {
        errors.push(format!(
            "missing or invalid status: {:?}",
            meta.get("status")
        ));
    }
    errors
}

/// Render a task/checkpoint file with the canonical field order.
pub fn render(meta: &Map<String, Value>, body: &str) -> String {
    let mut keys: Vec<&String> = Vec::new();
    for key in FRONTMATTER_ORDER {
        if meta.contains_key(*key) {
            if let Some(found) = meta.get_key_value(*key) {
                keys.push(found.0);
            }
        }
    }
    for key in meta.keys() {
        if !FRONTMATTER_ORDER.contains(&key.as_str()) {
            keys.push(key);
        }
    }
    let mut lines = vec!["---".to_string()];
    for key in keys {
        if let Some(value) = meta.get(key) {
            lines.push(format!("{key}: {}", format_value(value)));
        }
    }
    lines.push("---".to_string());
    format!(
        "{}\n\n{}\n",
        lines.join("\n"),
        body.trim_start_matches('\n').trim_end_matches('\n')
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_renders() {
        let text = "---\nid: 0001\ntitle: Test task\nstatus: todo\nlocks: [src/a, tests/**]\n---\n\n# Body\n";
        let doc = parse_document(text);
        assert!(doc.problems.is_empty(), "{:?}", doc.problems);
        assert_eq!(doc.meta["id"], "0001");
        assert_eq!(doc.meta["locks"], "src/a, tests/**");
        let rendered = render(&doc.meta, &doc.body);
        assert!(rendered.contains("id: 0001"));
        assert!(rendered.contains("locks: \"src/a, tests/**\""));
    }

    #[test]
    fn rejects_placeholders_like_python() {
        let doc = parse_document("---\nid: [a, b\n---\nbody");
        assert!(!doc.problems.is_empty());
    }
}
