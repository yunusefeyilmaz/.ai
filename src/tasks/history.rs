//! A structured, append-only transition log inside each task file.
//!
//! Every state change writes one line under `## Log`:
//!
//! ```text
//! - <iso time> | <actor> | <from> -> <to> | <reason> | <evidence>
//! ```

use regex::Regex;

use crate::core::time::iso;

fn clean(text: Option<&str>) -> String {
    text.unwrap_or("")
        .replace('|', "/")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn line(
    actor: Option<&str>,
    from: Option<&str>,
    to: &str,
    reason: &str,
    evidence: &str,
) -> String {
    let mut parts = vec![
        iso(None),
        {
            let value = clean(actor);
            if value.is_empty() {
                "-".to_string()
            } else {
                value
            }
        },
        format!("{} -> {to}", from.unwrap_or("-")),
        {
            let value = clean(Some(reason));
            if value.is_empty() {
                "-".to_string()
            } else {
                value
            }
        },
    ];
    if !evidence.is_empty() {
        parts.push(clean(Some(evidence)));
    }
    format!("- {}", parts.join(" | "))
}

pub fn append(
    body: &str,
    actor: Option<&str>,
    from: Option<&str>,
    to: &str,
    reason: &str,
    evidence: &str,
) -> String {
    format!(
        "{}\n{}\n",
        body.trim_end_matches('\n'),
        line(actor, from, to, reason, evidence)
    )
}

#[derive(Clone, Debug)]
pub struct LogEntry {
    pub kind: String,
    pub at: Option<String>,
    pub actor: Option<String>,
    pub from: Option<String>,
    pub to: Option<String>,
    pub reason: String,
    pub evidence: String,
    pub text: String,
}

impl LogEntry {
    pub fn to_json(&self) -> serde_json::Value {
        if self.kind == "note" {
            serde_json::json!({"kind": "note", "text": self.text})
        } else {
            serde_json::json!({
                "kind": "transition",
                "at": self.at,
                "actor": self.actor,
                "from": self.from,
                "to": self.to,
                "reason": self.reason,
                "evidence": self.evidence,
            })
        }
    }
}

pub fn parse(body: &str) -> Vec<LogEntry> {
    let pattern = Regex::new(
        r"^- (?P<at>\d{4}-\d\d-\d\dT[\w:.+-]+) \| (?P<actor>[^|]*?) \| (?P<frm>\S+) -> (?P<to>\S+) \| (?P<reason>[^|]*?)(?: \| (?P<evidence>.*))?$",
    )
    .expect("static regex");
    let mut entries = Vec::new();
    let mut in_log = false;
    for raw in body.lines() {
        if raw.starts_with("## ") {
            in_log = raw.trim().eq_ignore_ascii_case("## log");
            continue;
        }
        if !in_log || !raw.starts_with("- ") {
            continue;
        }
        match pattern.captures(raw) {
            Some(caps) => {
                let frm = caps.name("frm").map(|m| m.as_str()).unwrap_or("-");
                let reason = caps.name("reason").map(|m| m.as_str()).unwrap_or("");
                entries.push(LogEntry {
                    kind: "transition".into(),
                    at: caps.name("at").map(|m| m.as_str().to_string()),
                    actor: caps.name("actor").map(|m| m.as_str().to_string()),
                    from: if frm == "-" {
                        None
                    } else {
                        Some(frm.to_string())
                    },
                    to: caps.name("to").map(|m| m.as_str().to_string()),
                    reason: if reason == "-" {
                        String::new()
                    } else {
                        reason.to_string()
                    },
                    evidence: caps
                        .name("evidence")
                        .map(|m| m.as_str().to_string())
                        .unwrap_or_default(),
                    text: String::new(),
                });
            }
            None => entries.push(LogEntry {
                kind: "note".into(),
                at: None,
                actor: None,
                from: None,
                to: None,
                reason: String::new(),
                evidence: String::new(),
                text: raw[2..].trim().to_string(),
            }),
        }
    }
    entries
}
