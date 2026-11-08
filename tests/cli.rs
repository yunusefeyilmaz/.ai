//! End-to-end smoke: a fresh workspace can be initialised, inspected and driven
//! through the basic task lifecycle.

mod support;

use support::Ws;

#[test]
fn a_fresh_workspace_is_healthy() {
    let ws = Ws::new("ai-cli-healthy-");
    let doctor = ws.ok(&["doctor", "--json"]);
    let payload = doctor.json();
    assert_eq!(payload["check"]["ok"], serde_json::json!(true), "{payload}");
    assert!(
        payload["check"]["errors"]
            .as_array()
            .map(Vec::is_empty)
            .unwrap_or(false),
        "{payload}"
    );
}

#[test]
fn init_is_idempotent_and_reports_the_workspace() {
    let ws = Ws::new("ai-cli-init-");
    let first = ws.ok(&["init"]);
    assert!(first.stdout.contains("Workspace ready"), "{}", first.stdout);
    let second = ws.ok(&["init"]);
    assert!(
        second.stdout.contains("Workspace ready"),
        "{}",
        second.stdout
    );
}

#[test]
fn task_spec_lock_and_metrics_round_trip() {
    let ws = Ws::new("ai-cli-roundtrip-");
    ws.new_task("Ship the port").ok("task new");

    let listing = ws.ok(&["task", "list", "--json"]).json();
    assert_eq!(listing["active"].as_array().map(Vec::len), Some(1));
    assert_eq!(listing["active"][0]["title"], "Ship the port");

    ws.ok(&["spec", "check", "0001", "1"]);
    ws.ok(&[
        "lock",
        "acquire",
        "src/main.rs",
        "--agent",
        "tester",
        "--task",
        "0001",
    ]);
    let locks = ws.ok(&["lock", "status", "--json"]).json();
    assert!(locks.as_array().map(Vec::len).unwrap_or(0) >= 1);
    ws.ok(&["lock", "release", "src/main.rs", "--agent", "tester"]);

    let metrics = ws.ok(&["metrics", "--json"]).json();
    assert!(
        metrics["events_recorded"].as_u64().unwrap_or(0) >= 1,
        "{metrics}"
    );

    ws.ok(&["decision", "new", "Use Rust", "--agent", "tester"]);
    assert!(ws
        .ok(&["decision", "list", "--json"])
        .stdout
        .contains("Use Rust"));
}

#[test]
fn recover_reports_nothing_on_a_fresh_workspace() {
    let ws = Ws::new("ai-cli-recover-");
    let payload = ws.ok(&["recover", "--json"]).json();
    assert_eq!(payload["actions"], serde_json::json!([]));
    assert_eq!(payload["applied"], serde_json::json!(false));
}

#[test]
fn a_missing_task_is_a_clean_error() {
    let ws = Ws::new("ai-cli-missing-");
    let out = ws.fails(&["task", "show", "999999"]);
    assert!(out.all().contains("999999"), "{}", out.all());
    assert!(!out.all().contains("panicked"), "{}", out.all());
}

#[test]
fn unknown_flags_are_arg_errors() {
    let ws = Ws::new("ai-cli-args-");
    let out = ws.run(&["task", "list", "--not-a-flag"]);
    assert_ne!(out.code, 0);
}

#[test]
fn version_matches_the_workspace_constant() {
    let ws = Ws::new("ai-cli-version-");
    let out = ws.ok(&["version"]).stdout;
    assert!(
        out.contains(ai::core::workspace::VERSION),
        "{out} (expected {})",
        ai::core::workspace::VERSION
    );
}
