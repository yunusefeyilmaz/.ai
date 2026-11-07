//! Architecture Decision Records stored under `docs/decisions/`.

use std::fs;
use std::path::{Path, PathBuf};

use regex::Regex;
use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::fsio::{slugify, write_text_atomic};
use crate::core::workspace::Workspace;

pub const TEMPLATE: &str = r#"# {number} - {title}

- Status: proposed
- Date: {date}
- Deciders: {deciders}
- Task: {task}

## Context

<!-- What forces are at play? What breaks if we do nothing? -->

## Decision

<!-- The choice, in the active voice. -->

## Consequences

<!-- What becomes easier, what harder, what is now forbidden. -->

## Alternatives

<!-- What else was considered and why it lost. -->
"#;

pub fn list_decisions(ws: &Workspace) -> Vec<Value> {
    let mut items = Vec::new();
    let entries = match fs::read_dir(ws.decisions_dir()) {
        Ok(entries) => entries,
        Err(_) => return items,
    };
    let name_re = Regex::new(r"^\d{4}-.*\.md$").expect("static regex");
    let title_re = Regex::new(r"^\d{4}\s*-\s*").expect("static regex");
    let status_re = Regex::new(r"(?i)^[-*\s]*status\**:?\**\s*(\w+)").expect("static regex");
    let mut names: Vec<String> = entries
        .flatten()
        .map(|entry| entry.file_name().to_string_lossy().to_string())
        .filter(|name| name_re.is_match(name))
        .collect();
    names.sort();
    for name in names {
        let mut title = name[..name.len() - 3].to_string();
        let mut status: Option<String> = None;
        if let Ok(text) = fs::read_to_string(ws.decisions_dir().join(&name)) {
            for line in text.lines() {
                if line.starts_with("# ") && title == name[..name.len() - 3] {
                    let raw = line[2..].trim();
                    title = title_re.replace(raw, "").to_string();
                }
                if status.is_none() {
                    if let Some(caps) = status_re.captures(line) {
                        let value = caps[1].to_lowercase();
                        if !value.is_empty() {
                            status = Some(value);
                        }
                    }
                }
            }
        }
        items.push(json!({"file": name, "title": title, "status": status}));
    }
    items
}

fn next_number(ws: &Workspace) -> u32 {
    let mut numbers: Vec<u32> = list_decisions(ws)
        .iter()
        .filter_map(|item| item.get("file").and_then(Value::as_str))
        .filter_map(|name| name.get(..4))
        .filter_map(|digits| digits.parse().ok())
        .collect();
    if let Ok(entries) = fs::read_dir(ws.decisions_dir()) {
        let reserved = Regex::new(r"^\.(\d{4})\.reserved$").expect("static regex");
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if let Some(caps) = reserved.captures(&name) {
                if let Ok(value) = caps[1].parse() {
                    numbers.push(value);
                }
            }
        }
    }
    numbers.into_iter().max().unwrap_or(0) + 1
}

fn reserve_number(ws: &Workspace) -> Result<u32> {
    fs::create_dir_all(ws.decisions_dir())?;
    let mut number = next_number(ws);
    loop {
        let marker = ws.decisions_dir().join(format!(".{number:04}.reserved"));
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&marker)
        {
            Ok(_) => return Ok(number),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => number += 1,
            Err(error) => return Err(error.into()),
        }
    }
}

pub fn create_decision(ws: &Workspace, title: &str, deciders: &str, task: &str) -> Result<PathBuf> {
    let number = reserve_number(ws)?;
    let path = ws
        .decisions_dir()
        .join(format!("{number:04}-{}.md", slugify(title)));
    let text = TEMPLATE
        .replace("{number}", &format!("{number:04}"))
        .replace("{title}", title.trim())
        .replace("{deciders}", deciders)
        .replace("{task}", task)
        .replace("{date}", &crate::core::time::iso(None)[..10]);
    write_text_atomic(&path, &text)?;
    let _ = fs::remove_file(ws.decisions_dir().join(format!(".{number:04}.reserved")));
    Ok(path)
}

pub fn relative(ws: &Workspace, path: &Path) -> String {
    crate::core::workspace::relative_to(&ws.project, path)
}
