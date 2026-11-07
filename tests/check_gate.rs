//! Ported from `lib/tests/test_check_gate.py`.
//!
//! No silent green: an empty check gate is refused, not recorded as proof.

mod support;

use support::Ws;

#[test]
fn no_configured_checks_is_refused() {
    let ws = Ws::new("ai-check-gate-");
    let out = ws.fails(&["check"]);
    let text = out.all();
    assert!(text.contains("no project checks are configured"), "{text}");
    assert!(text.contains("config/workspace.json"), "{text}");
    assert!(text.contains("--allow-empty"), "{text}");
}

#[test]
fn allow_empty_is_an_explicit_printed_opt_out() {
    let ws = Ws::new("ai-check-gate-allow-");
    let out = ws.ok(&["check", "--allow-empty"]);
    let text = out.all();
    assert!(text.contains("ALLOW-EMPTY"), "{text}");
    assert!(text.contains("no project checks are configured"), "{text}");
    assert!(text.contains("--allow-empty"), "{text}");
}

#[test]
fn allow_empty_is_machine_readable_in_json_mode() {
    let ws = Ws::new("ai-check-gate-json-");
    let out = ws.ok(&["check", "--allow-empty", "--json"]);
    let payload = out.json();
    assert_eq!(payload["allow_empty"], serde_json::json!(true));
    assert_eq!(payload["results"], serde_json::json!([]));
    assert!(out.stderr.contains("ALLOW-EMPTY"), "{}", out.stderr);
    assert!(
        out.stderr.contains("no project checks are configured"),
        "{}",
        out.stderr
    );
}

#[test]
fn checks_disabled_in_config_is_a_printed_opt_out() {
    let ws = Ws::new("ai-check-gate-disabled-");
    ws.set_config(|config| config["workflow"]["requireCheck"] = serde_json::json!(false));
    let out = ws.ok(&["check"]);
    let text = out.all();
    assert!(text.contains("ALLOW-EMPTY"), "{text}");
    assert!(text.contains("requireCheck"), "{text}");
}

#[test]
fn empty_check_records_no_green_evidence() {
    let ws = Ws::new("ai-check-gate-evidence-");
    ws.new_task("No proof").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    let checked = ws.run(&["check", "--task", "0001", "--agent", "alice"]);
    assert_eq!(checked.code, 1, "{}", checked.all());
    assert!(
        checked.stderr.contains("Evidence recorded"),
        "{}",
        checked.stderr
    );

    let resume = ws.ok(&["resume", "0001"]).stdout;
    assert!(!resume.contains("still valid"), "{resume}");
}

#[test]
fn strict_review_cannot_pass_on_empty_verification() {
    let ws = Ws::with_mode("ai-check-gate-strict-", "strict");
    ws.new_task("Strict").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    let reviewed = ws.fails(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        reviewed.stderr.contains("no project checks"),
        "{}",
        reviewed.stderr
    );
}
