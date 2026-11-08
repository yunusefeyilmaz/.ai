//! Ported from `lib/tests/test_evidence_state.py`.
//!
//! One evidence state machine: resume, review and status must never disagree.

mod support;

use serde_json::{json, Value};
use support::Ws;

const HEAD: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const OTHER: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const GOOD: &str = "{\"ok\":true,\"result\":\"passed\",\"head\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"ran_commands\":true,\"fast\":false,\"checks\":[]}";

fn workspace() -> ai::core::workspace::Workspace {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    // A throwaway directory is enough: the evidence reader only needs the path.
    let root = std::env::temp_dir().join(format!(
        "ai-evidence-state-{}-{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    std::fs::create_dir_all(root.join("runtime").join("state").join("evidence"))
        .expect("create evidence dir");
    ai::core::workspace::Workspace::at(root)
}

fn write_records(ws: &ai::core::workspace::Workspace, records: &[String]) {
    let path = ws.evidence_dir().join("0001.jsonl");
    let mut text = String::new();
    for record in records {
        let mut value: Value = serde_json::from_str(record).expect("record json");
        value["task"] = json!("0001");
        value["agent"] = json!("alice");
        value["at"] = json!("2026-01-01T00:00:00Z");
        text.push_str(&serde_json::to_string(&value).expect("serialise"));
        text.push('\n');
    }
    std::fs::write(path, text).expect("write evidence");
}

#[test]
fn none_is_reported_when_nothing_was_recorded() {
    let ws = workspace();
    write_records(&ws, &[]);
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None);
    assert_eq!(result.state, "none");
    assert!(result.record.is_none(), "{:?}", result.record);
    assert!(
        result
            .reason
            .contains("no verification evidence is recorded for task 0001"),
        "{}",
        result.reason
    );
    let status = ai::runtime::evidence::task_status(&ws, "0001", Some(HEAD), None);
    assert_eq!(status["state"], "none");
    assert!(
        !ai::runtime::evidence::task_green(&ws, "0001", Some(HEAD), None).0,
        "missing evidence can never be green"
    );
}

#[test]
fn green_needs_full_evidence_on_this_head() {
    let ws = workspace();
    write_records(&ws, &[GOOD.to_string()]);
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None);
    assert_eq!(result.state, "green", "{}", result.reason);
    let (ok, text) = ai::runtime::evidence::task_green(&ws, "0001", Some(HEAD), None);
    assert!(ok, "{text}");
    assert!(text.contains("check passed"), "{text}");
}

#[test]
fn partial_is_never_green() {
    let ws = workspace();
    let partial_fast = GOOD
        .replace("\"fast\":false", "\"fast\":true")
        .replace("\"ran_commands\":true", "\"ran_commands\":false");
    write_records(&ws, &[partial_fast]);
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None);
    assert_eq!(result.state, "partial", "{}", result.reason);
    assert!(result.reason.contains("--fast"), "{}", result.reason);

    let partial_no_commands = GOOD.replace("\"ran_commands\":true", "\"ran_commands\":false");
    write_records(&ws, &[partial_no_commands]);
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None);
    assert_eq!(result.state, "partial", "{}", result.reason);
}

#[test]
fn failed_check_is_failed() {
    let ws = workspace();
    let failed = GOOD
        .replace("\"ok\":true", "\"ok\":false")
        .replace("\"result\":\"passed\"", "\"result\":\"failed\"");
    write_records(&ws, &[failed]);
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None);
    assert_eq!(result.state, "failed", "{}", result.reason);
}

#[test]
fn evidence_from_another_head_is_stale() {
    let ws = workspace();
    write_records(&ws, &[GOOD.to_string()]);
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(OTHER), None);
    assert_eq!(result.state, "stale", "{}", result.reason);
    assert!(result.reason.contains(&HEAD[..8]), "{}", result.reason);
    assert!(result.reason.contains(&OTHER[..8]), "{}", result.reason);
}

#[test]
fn proof_older_than_the_claim_is_stale() {
    let ws = workspace();
    write_records(&ws, &[GOOD.to_string()]);
    let result =
        ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), Some("2027-01-01T00:00:00Z"));
    assert_eq!(result.state, "stale", "{}", result.reason);
    assert!(
        result.reason.contains("older than the claim"),
        "{}",
        result.reason
    );
}

#[test]
fn invalidated_evidence_must_be_re_earned() {
    let ws = workspace();
    write_records(
        &ws,
        &[
            GOOD.to_string(),
            "{\"invalidated\":true,\"reason\":\"changes requested\"}".to_string(),
        ],
    );
    let result = ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None);
    assert_eq!(result.state, "invalidated", "{}", result.reason);
    assert!(
        result.reason.contains("changes requested"),
        "{}",
        result.reason
    );
    assert!(result.summary.contains("invalidated"), "{}", result.summary);
}

#[test]
fn the_newest_record_wins() {
    let ws = workspace();
    let failed = GOOD.replace("\"ok\":true", "\"ok\":false");
    write_records(&ws, &[failed.clone(), GOOD.to_string()]);
    assert_eq!(
        ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None).state,
        "green"
    );

    write_records(&ws, &[GOOD.to_string(), failed]);
    assert_eq!(
        ai::runtime::evidence::evaluate(&ws, "0001", Some(HEAD), None).state,
        "failed"
    );
}

// --- the readers agree ------------------------------------------------------

#[test]
fn resume_calls_a_partial_check_insufficient_for_review() {
    let ws = Ws::new("ai-evidence-resume-");
    ws.set_config(|config| {
        config["mode"] = json!("strict");
        config["checks"] = json!([{ "name": "unit", "command": "cmd /C echo ok" }]);
    });
    ws.new_task("Partial proof").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["checkpoint", "0001", "--agent", "alice", "--next", "go"]);
    ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "alice",
        "--no-commands",
    ]);

    let resume = ws.ok(&["resume", "0001"]).stdout;
    assert!(resume.contains("verification: PARTIAL"), "{resume}");
    assert!(resume.contains("not enough for review"), "{resume}");
    assert!(!resume.contains("still valid"), "{resume}");

    let history = ws.ok(&["history", "0001"]).stdout;
    assert!(history.contains("latest partial"), "{history}");
}

#[test]
fn resume_still_says_valid_after_a_full_check() {
    let ws = Ws::new("ai-evidence-full-");
    ws.set_config(|config| {
        config["mode"] = json!("strict");
        config["checks"] = json!([{ "name": "unit", "command": "cmd /C echo ok" }]);
    });
    ws.new_task("Full proof").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["checkpoint", "0001", "--agent", "alice", "--next", "go"]);
    ws.ok(&["check", "--task", "0001", "--agent", "alice"]);

    let resume = ws.ok(&["resume", "0001"]).stdout;
    assert!(resume.contains("verification: still valid"), "{resume}");
}
