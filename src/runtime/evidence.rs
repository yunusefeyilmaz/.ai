//! Verification proof, kept apart from what an agent *says*.
//!
//! `ai check --task <id>` appends a record to
//! `runtime/state/evidence/<id>.jsonl`: which commands ran, their exit codes,
//! who ran them and on which commit. A record is only valid for the HEAD it was
//! taken on, so new commits make older evidence stale.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::fsio::safe_name;
use crate::core::time::{iso, parse_iso};
use crate::core::workspace::Workspace;

pub const STATES: &[&str] = &["none", "invalidated", "failed", "partial", "stale", "green"];

fn task_file(ws: &Workspace, task_id: &str) -> PathBuf {
    ws.evidence_dir()
        .join(format!("{}.jsonl", safe_name(task_id)))
}

#[allow(clippy::too_many_arguments)]
pub fn record_task_check(
    ws: &Workspace,
    task_id: &str,
    agent: Option<&str>,
    ok: bool,
    head: Option<&str>,
    checks: &[Value],
    strict: bool,
    ran_commands: bool,
    fast: bool,
) -> Result<Value> {
    let record = json!({
        "task": task_id,
        "agent": agent,
        "at": iso(None),
        "head": head,
        "ok": ok,
        "result": if ok { "passed" } else { "failed" },
        "strict": strict,
        "ran_commands": ran_commands,
        "fast": fast,
        "checks": checks,
    });
    fs::create_dir_all(ws.evidence_dir())?;
    // One writer at a time: two agents checking at once must not interleave
    // partial JSON lines in the ledger every gate reads.
    let _guard = crate::runtime::mutex::workspace_state_guard(ws)?;
    let mut handle = OpenOptions::new()
        .create(true)
        .append(true)
        .open(task_file(ws, task_id))?;
    handle.write_all(format!("{}\n", serde_json::to_string(&record)?).as_bytes())?;
    Ok(record)
}

pub fn invalidate(ws: &Workspace, task_id: &str, reason: &str) -> Result<()> {
    fs::create_dir_all(ws.evidence_dir())?;
    let _guard = crate::runtime::mutex::workspace_state_guard(ws)?;
    let mut handle = OpenOptions::new()
        .create(true)
        .append(true)
        .open(task_file(ws, task_id))?;
    let record = json!({
        "task": task_id,
        "at": iso(None),
        "invalidated": true,
        "reason": reason,
    });
    handle.write_all(format!("{}\n", serde_json::to_string(&record)?).as_bytes())?;
    Ok(())
}

pub fn task_records(ws: &Workspace, task_id: &str) -> Vec<Value> {
    let path = task_file(ws, task_id);
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(_) => return Vec::new(),
    };
    text.lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .filter(Value::is_object)
        .collect()
}

/// True when the newest record (if any) was taken on `head`. One definition, so
/// the review package, the gates and the status views cannot disagree.
pub fn recorded_on(ws: &Workspace, task_id: &str, head: Option<&str>) -> bool {
    let recorded = task_records(ws, task_id)
        .last()
        .and_then(|record| record.get("head"))
        .and_then(Value::as_str)
        .map(ToString::to_string);
    match (recorded, head) {
        (Some(recorded), Some(head)) => recorded == head,
        _ => false,
    }
}

pub fn summary(record: &Value) -> String {
    if record
        .get("invalidated")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return format!(
            "evidence invalidated: {}",
            record.get("reason").and_then(Value::as_str).unwrap_or("")
        );
    }
    let names = record
        .get("checks")
        .and_then(Value::as_array)
        .map(|checks| {
            checks
                .iter()
                .map(|check| {
                    format!(
                        "{} {}",
                        check.get("name").and_then(Value::as_str).unwrap_or("check"),
                        if check.get("exit_code").and_then(Value::as_i64) == Some(0) {
                            "passed".to_string()
                        } else {
                            format!(
                                "FAILED (exit {})",
                                check
                                    .get("exit_code")
                                    .map(|v| v.to_string())
                                    .unwrap_or_else(|| "?".to_string())
                            )
                        }
                    )
                })
                .collect::<Vec<_>>()
                .join(", ")
        })
        .filter(|text| !text.is_empty())
        .unwrap_or_else(|| "no commands".to_string());
    let head = record
        .get("head")
        .and_then(Value::as_str)
        .unwrap_or("no-git");
    format!(
        "check {} @{} by {} ({names})",
        record.get("result").and_then(Value::as_str).unwrap_or("-"),
        &head[..head.len().min(8)],
        record.get("agent").and_then(Value::as_str).unwrap_or("-")
    )
}

#[derive(Clone, Debug)]
pub struct Verdict {
    pub state: String,
    pub record: Option<Value>,
    pub summary: String,
    pub reason: String,
}

fn verdict(state: &str, record: Option<Value>, summary: String, reason: String) -> Verdict {
    Verdict {
        state: state.to_string(),
        record,
        summary,
        reason,
    }
}

/// The single evidence verdict shared by every reader of the ledger.
pub fn evaluate(
    ws: &Workspace,
    task_id: &str,
    head: Option<&str>,
    since_iso: Option<&str>,
) -> Verdict {
    let records = task_records(ws, task_id);
    if records.is_empty() {
        return verdict(
            "none",
            None,
            String::new(),
            format!("no verification evidence is recorded for task {task_id}"),
        );
    }
    let latest = records.last().cloned().unwrap_or(Value::Null);
    let base_summary = summary(&latest);
    if latest
        .get("invalidated")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return verdict(
            "invalidated",
            Some(latest.clone()),
            base_summary,
            format!(
                "the earlier evidence was invalidated ({}); run the checks again",
                latest.get("reason").and_then(Value::as_str).unwrap_or("")
            ),
        );
    }
    if !latest.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        return verdict(
            "failed",
            Some(latest.clone()),
            base_summary,
            format!(
                "the latest check for task {task_id} failed ({})",
                latest.get("at").and_then(Value::as_str).unwrap_or("")
            ),
        );
    }
    if latest.get("fast").and_then(Value::as_bool).unwrap_or(false)
        || !latest
            .get("ran_commands")
            .and_then(Value::as_bool)
            .unwrap_or(false)
    {
        return verdict(
            "partial",
            Some(latest),
            base_summary,
            "the latest check was partial (--fast or --no-commands); run the full check"
                .to_string(),
        );
    }
    let recorded_head = latest.get("head").and_then(Value::as_str);
    if recorded_head != head {
        return verdict(
            "stale",
            Some(latest.clone()),
            base_summary,
            format!(
                "the evidence was taken on {} but HEAD is {}; a merge or a new commit moved HEAD after the check",
                recorded_head.unwrap_or("no-git"),
                head.unwrap_or("no-git")
            ),
        );
    }
    if let Some(since) = since_iso {
        let at = latest.get("at").and_then(Value::as_str).and_then(parse_iso);
        if let (Some(at), Some(since)) = (at, parse_iso(since)) {
            if at < since {
                return verdict(
                    "stale",
                    Some(latest),
                    base_summary,
                    format!(
                        "the latest green check ({}) is older than the claim ({since})",
                        at.to_rfc3339()
                    ),
                );
            }
        }
    }
    verdict("green", Some(latest), base_summary, String::new())
}

pub fn task_status(
    ws: &Workspace,
    task_id: &str,
    head: Option<&str>,
    since_iso: Option<&str>,
) -> Value {
    let result = evaluate(ws, task_id, head, since_iso);
    let mut payload = json!({"state": result.state});
    if let Some(record) = result.record {
        payload["record"] = record;
    }
    if !result.summary.is_empty() {
        payload["summary"] = json!(result.summary);
    }
    if result.state != "green" {
        payload["reason"] = json!(result.reason);
    }
    payload
}

pub fn task_green(
    ws: &Workspace,
    task_id: &str,
    head: Option<&str>,
    since_iso: Option<&str>,
) -> (bool, String) {
    let result = evaluate(ws, task_id, head, since_iso);
    if result.state == "green" {
        (true, result.summary)
    } else {
        (false, result.reason)
    }
}
