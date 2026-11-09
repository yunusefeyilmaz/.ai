//! The project blueprint: facts the machine can prove, the proposal the AI
//! authors, and the user's approval.
//!
//! The CLI deliberately does **not** own a language or framework registry. It
//! reports mechanical facts (OS, shell, Git, the top-level tree, the toolchains
//! that answer `--version`) and then records whatever proposal the chief wrote.
//! Any language, folder layout, architecture or extra convention is accepted, so
//! a project outside the usual stacks, or a user who wants something unusual, is
//! not blocked by this binary.
//!
//! File: `config/blueprint.json`. Flow: `propose --from` -> `show` -> `revise`
//! -> `approve`. Only `approve` copies values into `config/workspace.json`; the
//! full proposal is preserved under `config.blueprint.approved` so later readers
//! (`ai brief`, `ai now`, agents) see every convention, including ones this
//! version of the CLI does not interpret.

mod apply;
mod detect;
mod proposal;
mod render;

use serde_json::Value;

use crate::config::settings::{load, save};
use crate::core::error::{fail, Result};
use crate::core::fsio::write_json_atomic;
use crate::core::time::iso;
use crate::core::workspace::{relative_to, Workspace};

pub use detect::facts;
pub use render::{conventions_block, summary};

pub const FILE: &str = "config/blueprint.json";

/// Process mode: how much ceremony the gates add. Kept an enum on purpose —
/// this is product behaviour, not project technology.
pub const MODES: &[&str] = &["lite", "strict"];

/// Approval playbook: who may approve delivered work. Also product behaviour.
pub const PLAYBOOKS: &[&str] = &["solo", "pair", "team"];

pub struct Approved {
    pub applied: Vec<String>,
    pub document: Value,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum State {
    Missing,
    Pending,
    Approved,
}

impl State {
    pub fn as_str(self) -> &'static str {
        match self {
            State::Missing => "missing",
            State::Pending => "pending",
            State::Approved => "approved",
        }
    }
}

pub fn path_of(ws: &Workspace) -> std::path::PathBuf {
    ws.root
        .join(FILE.replace('/', std::path::MAIN_SEPARATOR_STR))
}

pub fn read(ws: &Workspace) -> Option<Value> {
    let text = std::fs::read_to_string(path_of(ws)).ok()?;
    serde_json::from_str::<Value>(&text).ok()
}

pub fn status(ws: &Workspace) -> State {
    match read(ws) {
        Some(document) => {
            if document.get("status").and_then(Value::as_str) == Some("approved") {
                State::Approved
            } else {
                State::Pending
            }
        }
        None => State::Missing,
    }
}

pub fn write(ws: &Workspace, document: &Value) -> Result<()> {
    write_json_atomic(&path_of(ws), document)?;
    let mut config = match crate::config::settings::load_for_update(ws)? {
        Some(config) => config,
        None => crate::config::settings::default_config(ws),
    };
    let approved = document.get("status").and_then(Value::as_str) == Some("approved");
    if let Some(object) = config.as_object_mut() {
        let entry = object
            .entry("blueprint".to_string())
            .or_insert_with(|| serde_json::json!({}));
        if let Some(entry) = entry.as_object_mut() {
            entry.insert(
                "status".into(),
                document
                    .get("status")
                    .cloned()
                    .unwrap_or(serde_json::json!("pending")),
            );
            entry.insert("path".into(), serde_json::json!(FILE));
            entry.insert(
                "authored".into(),
                serde_json::json!(proposal::authored(
                    &document.get("proposal").cloned().unwrap_or(Value::Null)
                )),
            );
            if approved {
                entry.insert(
                    "approvedBy".into(),
                    document
                        .get("approval")
                        .and_then(|approval| approval.get("by"))
                        .cloned()
                        .unwrap_or(Value::Null),
                );
                entry.insert(
                    "approvedAt".into(),
                    document
                        .get("approval")
                        .and_then(|approval| approval.get("at"))
                        .cloned()
                        .unwrap_or(Value::Null),
                );
            }
        }
    }
    save(ws, &config)
}

/// Build the document to store.
///
/// * `from` is the chief's analysis (a full proposal or `{"proposal": {...}}`);
///   it is validated structurally and kept verbatim, so unknown keys survive.
/// * Without `from`, a draft is written: facts plus a skeleton the AI must fill
///   before the user can approve it.
pub fn propose(ws: &Workspace, actor: Option<&str>, from: Option<Value>) -> Result<Value> {
    let facts = detect::facts(ws);
    let proposal = match from {
        Some(input) => {
            let proposal = proposal::extract(input)?;
            proposal::validate(&proposal)?;
            proposal
        }
        None => proposal::draft(
            &facts,
            &load(ws).unwrap_or_else(|_| crate::config::settings::default_config(ws)),
        ),
    };
    Ok(serde_json::json!({
        "schema": 2,
        "status": "pending",
        "project": ws
            .project
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("project"),
        "workspace": relative_to(&ws.project, &ws.root),
        "created": iso(None),
        "createdBy": actor,
        "detected": facts,
        "proposal": proposal,
        "authored": proposal::authored(&proposal),
        "questions": proposal::questions(),
        "approval": {"required": true, "by": null, "at": null},
    }))
}

/// Change any part of the proposal with `path.to.key=value`. Values are parsed
/// as JSON when they look like it (`true`, `3`, `["a"]`, `{"k":"v"}`), otherwise
/// as a string, so custom keys do not need a schema.
pub fn revise(document: &mut Value, sets: &[String]) -> Result<()> {
    proposal::apply_sets(document, sets)
}

/// Copy the proposal into `config/workspace.json` and mark it approved.
pub fn approve(ws: &Workspace, agent: Option<&str>, sets: &[String]) -> Result<Approved> {
    let mut document = read(ws).ok_or_else(|| {
        crate::core::error::AiError::msg(
            "no architecture proposal yet; run `ai blueprint propose --from <analysis.json>` first",
        )
    })?;
    revise(&mut document, sets)?;
    let proposal = document
        .get("proposal")
        .cloned()
        .ok_or_else(|| crate::core::error::AiError::msg("blueprint has no proposal object"))?;
    if !proposal::authored(&proposal) {
        return fail(
            "the blueprint is still an empty draft: the chief must author it (languages, architecture, naming, layout, guidelines or checks) with `ai blueprint propose --from <file>` or `ai blueprint revise --set ...` before the user approves it",
        );
    }
    proposal::validate(&proposal)?;
    let applied = apply::to_config(ws, &proposal)?;
    if let Some(object) = document.as_object_mut() {
        object.insert("status".into(), serde_json::json!("approved"));
        object.insert("authored".into(), serde_json::json!(true));
        object.insert(
            "approval".into(),
            serde_json::json!({
                "required": true,
                "by": agent.unwrap_or("user"),
                "at": iso(None),
            }),
        );
    }
    write(ws, &document)?;
    Ok(Approved { applied, document })
}

/// The approved proposal, from config first (it survives a deleted work file)
/// and the blueprint file second.
pub fn approved_proposal(ws: &Workspace) -> Option<Value> {
    if let Ok(config) = load(ws) {
        if let Some(proposal) = config
            .get("blueprint")
            .and_then(|blueprint| blueprint.get("approved"))
            .filter(|value| value.is_object())
        {
            let mut proposal = proposal.clone();
            // Top-level `checks` is the single source of truth; re-attach it
            // for readers that display the whole approved proposal.
            if proposal.get("checks").is_none() {
                if let Some(checks) = config.get("checks") {
                    if let Some(object) = proposal.as_object_mut() {
                        object.insert("checks".into(), checks.clone());
                    }
                }
            }
            return Some(proposal);
        }
    }
    let document = read(ws)?;
    if document.get("status").and_then(Value::as_str) != Some("approved") {
        return None;
    }
    document.get("proposal").cloned()
}
