//! Summarize the local workflow event ledger.

use chrono::{DateTime, TimeZone, Utc};
use serde_json::{json, Map, Value};

use crate::core::error::{fail, Result};
use crate::core::time::parse_iso;
use crate::core::workspace::Workspace;
use crate::runtime::events::read_events;

pub fn metrics_since(value: Option<&str>) -> Result<Option<DateTime<Utc>>> {
    let value = match value {
        Some(value) if !value.trim().is_empty() => value.trim(),
        _ => return Ok(None),
    };
    if value.len() == 10
        && value.as_bytes().get(4) == Some(&b'-')
        && value.as_bytes().get(7) == Some(&b'-')
    {
        if let Ok(date) = chrono::NaiveDate::parse_from_str(value, "%Y-%m-%d") {
            let midnight = date.and_hms_opt(0, 0, 0).expect("midnight always exists");
            return Ok(Some(Utc.from_utc_datetime(&midnight)));
        }
    }
    match parse_iso(value) {
        Some(stamp) => Ok(Some(stamp)),
        None => fail("--since must be an ISO date or timestamp"),
    }
}

fn event_datetime(event: &Value) -> Option<DateTime<Utc>> {
    parse_iso(event.get("timestamp").and_then(Value::as_str).unwrap_or(""))
}

fn median(values: &mut [f64]) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let middle = values.len() / 2;
    if values.len() % 2 == 0 {
        Some((values[middle - 1] + values[middle]) / 2.0)
    } else {
        Some(values[middle])
    }
}

fn duration_median(events: &[Value], starts: &[Value], end_type: &str) -> Option<f64> {
    use std::collections::HashMap;
    let mut start_map: HashMap<String, Vec<DateTime<Utc>>> = HashMap::new();
    for event in starts {
        let task = event.get("task").and_then(Value::as_str).unwrap_or("");
        if let (true, Some(stamp)) = (!task.is_empty(), event_datetime(event)) {
            start_map.entry(task.to_string()).or_default().push(stamp);
        }
    }
    let mut durations = Vec::new();
    for event in events {
        if event.get("event").and_then(Value::as_str) != Some(end_type) {
            continue;
        }
        let task = event.get("task").and_then(Value::as_str).unwrap_or("");
        let end = match event_datetime(event) {
            Some(end) => end,
            None => continue,
        };
        if let Some(stamps) = start_map.get(task) {
            if let Some(earliest) = stamps.iter().filter(|stamp| **stamp <= end).max() {
                durations.push((end - *earliest).num_milliseconds() as f64 / 1000.0);
            }
        }
    }
    median(&mut durations)
}

pub fn collect_metrics(ws: &Workspace, since: Option<DateTime<Utc>>) -> Value {
    let events = read_events(ws);
    let timed: Vec<(&Value, Option<DateTime<Utc>>)> = events
        .iter()
        .map(|event| (event, event_datetime(event)))
        .collect();
    let period: Vec<&Value> = timed
        .iter()
        .filter(|(_, stamp)| {
            stamp
                .map(|stamp| since.map(|since| stamp >= since).unwrap_or(true))
                .unwrap_or(false)
        })
        .map(|(event, _)| *event)
        .collect();
    let mut completed: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    for event in &period {
        if event.get("event").and_then(Value::as_str) == Some("task_done") {
            if let Some(task) = event.get("task").and_then(Value::as_str) {
                completed.insert(task.to_string());
            }
        }
    }
    let mut claims: std::collections::HashMap<String, Vec<&Value>> =
        std::collections::HashMap::new();
    for event in &events {
        if event.get("event").and_then(Value::as_str) == Some("task_claimed") {
            if let Some(task) = event.get("task").and_then(Value::as_str) {
                claims.entry(task.to_string()).or_default().push(event);
            }
        }
    }
    let mut retries = 0usize;
    for attempts in claims.values() {
        for attempt in attempts.iter().skip(1) {
            if let Some(stamp) = event_datetime(attempt) {
                if since.map(|since| stamp >= since).unwrap_or(true) {
                    retries += 1;
                }
            }
        }
    }
    let created: Vec<Value> = events
        .iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("task_created"))
        .cloned()
        .collect();
    let reviewed: Vec<Value> = events
        .iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("task_reviewed"))
        .cloned()
        .collect();
    let merged: Vec<Value> = period
        .iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("task_merged"))
        .map(|event| (*event).clone())
        .collect();
    let done: Vec<Value> = period
        .iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("task_done"))
        .map(|event| (*event).clone())
        .collect();
    let mut agents: std::collections::BTreeMap<String, u64> = std::collections::BTreeMap::new();
    for event in &period {
        if let Some(agent) = event.get("agent").and_then(Value::as_str) {
            *agents.entry(agent.to_string()).or_insert(0) += 1;
        }
    }
    let lock_refusals = period
        .iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("lock_refused"))
        .count();
    let resumes = period
        .iter()
        .filter(|event| event.get("event").and_then(Value::as_str) == Some("resume"))
        .count();
    let since_text = since
        .map(|stamp| stamp.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
        .unwrap_or_default();
    let mut payload = Map::new();
    payload.insert(
        "since".into(),
        if since.is_some() {
            json!(since_text)
        } else {
            Value::Null
        },
    );
    payload.insert("events_recorded".into(), json!(period.len()));
    payload.insert("tasks_completed".into(), json!(completed.len()));
    payload.insert(
        "median_creation_to_done_seconds".into(),
        json!(duration_median(&done, &created, "task_done")),
    );
    payload.insert(
        "median_review_to_merge_seconds".into(),
        json!(duration_median(&merged, &reviewed, "task_merged")),
    );
    payload.insert("lock_refusals".into(), json!(lock_refusals));
    payload.insert("retries".into(), json!(retries));
    payload.insert("resumes".into(), json!(resumes));
    payload.insert("per_agent".into(), json!(agents));
    Value::Object(payload)
}
