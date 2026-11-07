//! Ported from `lib/tests/test_events_fallback.py` and `test_metrics.py`.
//!
//! The audit-event fallback must never raise or lose the record; metrics are
//! local, append-only and read-only when queried.

mod support;

use support::Ws;

#[test]
fn an_unwritable_ledger_path_does_not_raise() {
    let ws = Ws::new("ai-events-unwritable-");
    // A directory where the ledger file is expected: the append must fail
    // without taking the command down.
    ws.write("runtime/state/events.jsonl/placeholder", "");

    let out = ws.run(&["task", "new", "Probe"]);
    assert_eq!(out.code, 0, "{}", out.all());
    assert!(out.stderr.contains("WARN"), "{}", out.stderr);
    assert!(!out.stderr.contains("panicked"), "{}", out.stderr);
    assert!(!out.stderr.contains("RUST_BACKTRACE"), "{}", out.stderr);
}

#[test]
fn empty_metrics_are_read_only() {
    let ws = Ws::new("ai-metrics-empty-");
    let _ = std::fs::remove_dir_all(ws.path("runtime/state"));

    let payload = ws.ok(&["metrics", "--json"]).json();
    assert!(
        !ws.path("runtime/state").exists(),
        "metrics must not create the runtime state tree"
    );
    assert_eq!(payload["events_recorded"], serde_json::json!(0));
    assert_eq!(payload["tasks_completed"], serde_json::json!(0));
    assert!(payload["median_creation_to_done_seconds"].is_null());
    assert!(payload["median_review_to_merge_seconds"].is_null());
    assert_eq!(payload["per_agent"], serde_json::json!({}));
}

#[test]
fn lifecycle_events_are_recorded_in_order_and_counted() {
    let ws = Ws::new("ai-metrics-life-");
    ws.new_task("Metrics lifecycle").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["task", "release", "0001", "--agent", "alice"]);
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&[
        "checkpoint",
        "0001",
        "--agent",
        "alice",
        "--next",
        "submit for review",
    ]);
    ws.ok(&["resume", "0001", "--json"]);

    ws.ok(&["lock", "acquire", "docs/shared", "--agent", "owner"]);
    ws.fails(&["lock", "acquire", "docs/shared/file", "--agent", "blocked"]);
    ws.ok(&["lock", "release", "docs/shared", "--agent", "owner"]);

    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    ws.ok(&["task", "release", "0001", "--agent", "alice"]);

    let ledger = ws.read("runtime/state/events.jsonl");
    let names: Vec<String> = ledger
        .lines()
        .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
        .filter_map(|event| event["event"].as_str().map(ToString::to_string))
        .collect();
    assert_eq!(
        names,
        vec![
            "task_created",
            "task_claimed",
            "task_released",
            "task_claimed",
            "checkpoint",
            "resume",
            "lock_refused",
            "task_reviewed"
        ],
        "{ledger}"
    );

    let metrics = ws.ok(&["metrics", "--json"]).json();
    assert_eq!(metrics["events_recorded"], serde_json::json!(names.len()));
    assert_eq!(metrics["lock_refusals"], serde_json::json!(1));
    assert_eq!(metrics["retries"], serde_json::json!(1));
    assert_eq!(metrics["resumes"], serde_json::json!(1));
    assert_eq!(metrics["per_agent"]["alice"], serde_json::json!(6));
}

#[test]
fn since_filter_excludes_older_and_future_events() {
    let ws = Ws::new("ai-metrics-since-");
    ws.new_task("Since probe").ok("task new");

    let future = (chrono::Utc::now().date_naive() + chrono::Days::new(1))
        .format("%Y-%m-%d")
        .to_string();
    let payload = ws.ok(&["metrics", "--json", "--since", &future]).json();
    assert_eq!(payload["events_recorded"], serde_json::json!(0));
    assert_eq!(payload["tasks_completed"], serde_json::json!(0));
    assert!(payload["median_creation_to_done_seconds"].is_null());
    assert_eq!(payload["per_agent"], serde_json::json!({}));
}

#[test]
fn daily_rotation_preserves_events_for_metrics() {
    let ws = Ws::new("ai-metrics-rotation-");
    ws.new_task("Rotation probe").ok("task new");

    let mut first: serde_json::Value =
        serde_json::from_str(ws.read("runtime/state/events.jsonl").trim()).expect("event json");
    first["timestamp"] = serde_json::json!("2000-01-01T00:00:00Z");
    ws.write(
        "runtime/state/events.jsonl",
        &(serde_json::to_string(&first).expect("serialise") + "\n"),
    );

    ws.ok(&["lock", "acquire", "docs/shared", "--agent", "owner"]);
    ws.fails(&["lock", "acquire", "docs/shared/file", "--agent", "blocked"]);

    assert!(
        ws.exists("runtime/state/events-2000-01-01.jsonl"),
        "the rotation must archive the old day"
    );
    let metrics = ws.ok(&["metrics", "--json"]).json();
    assert_eq!(metrics["events_recorded"], serde_json::json!(2));
    assert_eq!(metrics["lock_refusals"], serde_json::json!(1));
}
