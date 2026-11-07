//! Append-only JSONL event ledger, rotated by UTC date.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

use regex::Regex;
use serde_json::{json, Map, Value};

use crate::core::error::Result;
use crate::core::time::iso;
use crate::core::workspace::Workspace;
use crate::runtime::mutex::registry_mutex;

fn write_event(ws: &Workspace, record: &Value) -> Result<()> {
    let _guard = registry_mutex(ws)?;
    let events_file = ws.events_file();
    if events_file.is_file() {
        let mut last: Option<Value> = None;
        if let Ok(text) = fs::read_to_string(&events_file) {
            for line in text.lines() {
                if line.trim().is_empty() {
                    continue;
                }
                if let Ok(value) = serde_json::from_str::<Value>(line) {
                    last = Some(value);
                }
            }
        }
        let previous_date = last
            .as_ref()
            .and_then(|value| value.get("timestamp"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .chars()
            .take(10)
            .collect::<String>();
        let event_date = record
            .get("timestamp")
            .and_then(Value::as_str)
            .unwrap_or("")
            .chars()
            .take(10)
            .collect::<String>();
        if !previous_date.is_empty() && previous_date != event_date {
            let archive = ws.state_dir().join(format!("events-{previous_date}.jsonl"));
            if archive.exists() {
                if let Ok(source) = fs::read(&events_file) {
                    let mut target = OpenOptions::new()
                        .create(true)
                        .append(true)
                        .open(&archive)?;
                    target.write_all(&source)?;
                }
                let _ = fs::remove_file(&events_file);
            } else if let Some(parent) = archive.parent() {
                fs::create_dir_all(parent)?;
                fs::rename(&events_file, &archive)?;
            }
        }
    }
    let mut handle = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&events_file)?;
    let line = serde_json::to_string(record)?;
    handle.write_all(format!("{line}\n").as_bytes())?;
    Ok(())
}

/// Append one local event. Logging is best-effort: a broken ledger must never
/// crash the command that was trying to record progress.
pub fn append_event(ws: &Workspace, event: &str, fields: &[(&str, Value)]) {
    let mut map = Map::new();
    map.insert("timestamp".into(), Value::String(iso(None)));
    map.insert("event".into(), Value::String(event.to_string()));
    for (key, value) in fields {
        if !value.is_null() {
            map.insert((*key).to_string(), value.clone());
        }
    }
    let record = Value::Object(map);
    let mut last_error = String::new();
    for attempt in 0..2 {
        match write_event(ws, &record) {
            Ok(()) => return,
            Err(error) => {
                last_error = error.to_string();
                if attempt == 0 {
                    std::thread::sleep(std::time::Duration::from_millis(50));
                }
            }
        }
    }
    let mut fallback = record.clone();
    if let Some(object) = fallback.as_object_mut() {
        object.insert("_fallback".into(), Value::Bool(true));
        object.insert("_error".into(), Value::String(last_error.clone()));
    }
    if let Err(error) = write_event(ws, &fallback) {
        eprintln!(
            "WARN  could not record metrics event '{event}': {last_error}; fallback also failed: {error}"
        );
    }
}

/// Read the active and rotated event ledgers without creating state.
pub fn read_events(ws: &Workspace) -> Vec<Value> {
    let state_dir = ws.state_dir();
    let entries = match fs::read_dir(&state_dir) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };
    let rotated = Regex::new(r"^events-\d{4}-\d{2}-\d{2}\.jsonl$").expect("static regex");
    let mut paths: Vec<_> = entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| {
            let name = path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or_default();
            name == "events.jsonl" || rotated.is_match(name)
        })
        .collect();
    paths.sort();
    let mut events = Vec::new();
    for path in paths {
        if let Ok(text) = fs::read_to_string(&path) {
            for line in text.lines() {
                if let Ok(value) = serde_json::from_str::<Value>(line) {
                    if value.get("event").and_then(Value::as_str).is_some()
                        && value.get("timestamp").and_then(Value::as_str).is_some()
                    {
                        events.push(value);
                    }
                }
            }
        }
    }
    events.sort_by(|a, b| {
        a.get("timestamp")
            .and_then(Value::as_str)
            .unwrap_or("")
            .cmp(b.get("timestamp").and_then(Value::as_str).unwrap_or(""))
    });
    events
}

pub fn event_name(value: &Value) -> &str {
    value.get("event").and_then(Value::as_str).unwrap_or("")
}

pub fn event_field<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(Value::as_str)
}

/// Convenience for callers that only have a path.
pub fn path_name(path: &Path) -> String {
    path.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default()
        .to_string()
}

pub fn summarize(events: &[Value], limit: usize) -> Value {
    json!(events.iter().rev().take(limit).collect::<Vec<_>>())
}
