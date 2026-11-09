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
        checked.all().contains("Evidence recorded"),
        "{}",
        checked.all()
    );

    let resume = ws.ok(&["resume", "0001"]).stdout;
    assert!(!resume.contains("still valid"), "{resume}");
}

#[test]
fn reuse_evidence_skips_a_second_run_on_the_same_head() {
    let ws = Ws::new("ai-check-gate-reuse-");
    ws.set_config(|config| {
        config["mode"] = serde_json::json!("strict");
        config["workflow"]["requireCheck"] = serde_json::json!(true);
        config["checks"] = serde_json::json!([{ "name": "ok", "command": "echo ok" }]);
    });
    ws.new_task("Reuse proof").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["check", "--task", "0001", "--agent", "alice"]);

    // A failing command proves the reuse path did not execute it.
    ws.set_config(|config| {
        config["checks"] = serde_json::json!([{ "name": "ok", "command": "exit 1" }]);
    });
    let reused = ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "alice",
        "--reuse-evidence",
    ]);
    assert!(
        reused.all().contains("Reusing green evidence"),
        "{}",
        reused.all()
    );
}

#[test]
fn a_check_that_hangs_is_killed_and_reported() {
    let ws = Ws::new("ai-check-gate-timeout-");
    #[cfg(windows)]
    let command = "ping -n 6 127.0.0.1 >nul";
    #[cfg(not(windows))]
    let command = "sleep 5";
    ws.set_config(|config| {
        config["mode"] = serde_json::json!("strict");
        config["workflow"]["requireCheck"] = serde_json::json!(true);
        config["checks"] = serde_json::json!([{
            "name": "slow",
            "command": command,
            "timeoutSeconds": 1
        }]);
    });

    let started = std::time::Instant::now();
    let out = ws.fails(&["check", "--allow-empty"]);
    assert!(out.all().contains("timed out after 1s"), "{}", out.all());
    assert!(
        started.elapsed() < std::time::Duration::from_secs(4),
        "the check must be killed"
    );
}

#[test]
fn an_unclaimed_task_never_gains_evidence() {
    let ws = Ws::new("ai-check-gate-unclaimed-");
    ws.new_task("Not mine yet").ok("task new");

    let out = ws.ok(&["check", "--task", "0001", "--allow-empty"]);
    assert!(!out.all().contains("Evidence recorded"), "{}", out.all());
    assert!(
        !ws.path("runtime/state/evidence/0001.jsonl").exists(),
        "a task nobody claimed must not acquire evidence"
    );

    // After claiming, the same command records evidence normally.
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    let claimed = ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "alice",
        "--allow-empty",
    ]);
    assert!(
        claimed.all().contains("Evidence recorded"),
        "{}",
        claimed.all()
    );
}

#[test]
fn another_agent_cannot_write_evidence_for_a_claimed_task() {
    let ws = Ws::new("ai-check-gate-alien-");
    ws.new_task("Owned by alice").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    let out = ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "mallory",
        "--allow-empty",
    ]);
    assert!(!out.all().contains("Evidence recorded"), "{}", out.all());
    assert!(
        !ws.path("runtime/state/evidence/0001.jsonl").exists(),
        "only the claimant may attach evidence"
    );
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
