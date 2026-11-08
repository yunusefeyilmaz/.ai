//! Ported from `lib/tests/test_done_stale_lock.py`.
//!
//! `ai task done` must inherit a stale task lock, not refuse forever. A crashed
//! reviewer leaves `task-<id>.lock` behind; a live one is still a refusal.

mod support;

use serde_json::Value;
use support::Ws;

fn stamp(minutes_ago: i64) -> String {
    (chrono::Utc::now() - chrono::Duration::minutes(minutes_ago))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

/// A task in review that bob may archive (alice produced it).
fn prepared() -> Ws {
    let ws = Ws::new("ai-done-stale-");
    ws.new_task("Finished work").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    ws.ok(&["task", "release", "0001", "--agent", "alice"]);
    assert_eq!(ws.ok(&["lock", "status"]).stdout.trim(), "No locks held.");
    ws
}

fn lock_file(ws: &Ws) -> std::path::PathBuf {
    let files: Vec<std::path::PathBuf> = std::fs::read_dir(ws.path("runtime/locks"))
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| {
                    let name = path
                        .file_name()
                        .map(|name| name.to_string_lossy().to_string())
                        .unwrap_or_default();
                    name.contains("task-0001") && name.ends_with(".lock")
                })
                .collect()
        })
        .unwrap_or_default();
    assert_eq!(files.len(), 1, "{files:?}");
    files.into_iter().next().expect("one")
}

/// A genuine lease from the CLI, optionally aged past the staleness TTL.
fn take_lock(ws: &Ws, agent: &str, minutes_ago: i64) -> std::path::PathBuf {
    ws.ok(&[
        "lock",
        "acquire",
        "task-0001",
        "--agent",
        agent,
        "--task",
        "0001",
    ]);
    let path = lock_file(ws);
    if minutes_ago > 0 {
        let mut payload: Value =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read lock"))
                .expect("lock json");
        payload["started_at"] = Value::String(stamp(minutes_ago));
        payload["updated_at"] = Value::String(stamp(minutes_ago));
        std::fs::write(&path, serde_json::to_string(&payload).expect("serialise"))
            .expect("write lock");
    }
    path
}

fn events(ws: &Ws) -> String {
    std::fs::read_to_string(ws.path("runtime/state/events.jsonl")).unwrap_or_default()
}

#[test]
fn a_stale_lock_is_inherited_and_the_task_is_archived() {
    let ws = prepared();
    take_lock(&ws, "ghost", 180);

    let done = ws.ok(&["task", "done", "0001", "--agent", "bob"]);
    assert!(!done.stderr.contains("locked by"), "{}", done.stderr);
    assert_eq!(ws.glob("tasks/done", "0001-").len(), 1);
    assert!(ws.glob("tasks/active", "0001-").is_empty());
}

#[test]
fn the_takeover_is_recorded_in_the_event_log() {
    let ws = prepared();
    take_lock(&ws, "ghost", 180);
    ws.ok(&["task", "done", "0001", "--agent", "bob"]);

    let log = events(&ws);
    assert!(log.contains("lock_replaced_stale"), "{log}");
    assert!(log.contains("ghost"), "{log}");
}

#[test]
fn a_live_lock_from_another_agent_is_still_refused() {
    let ws = prepared();
    take_lock(&ws, "ghost", 0);

    let done = ws.fails(&["task", "done", "0001", "--agent", "bob"]);
    assert!(done.stderr.contains("locked by ghost"), "{}", done.stderr);
    assert!(ws
        .ok(&["task", "show", "0001"])
        .stdout
        .contains("status: review"));
    assert!(!events(&ws).contains("lock_replaced_stale"));
}

#[test]
fn a_corrupt_lock_still_fails_closed() {
    let ws = prepared();
    let lock = take_lock(&ws, "ghost", 0);
    std::fs::write(&lock, "{not json").expect("corrupt lock");

    let done = ws.fails(&["task", "done", "0001", "--agent", "bob"]);
    assert!(done.stderr.contains("corrupt task lock"), "{}", done.stderr);
    assert!(
        done.stderr.contains("ai lock release task-0001 --force"),
        "{}",
        done.stderr
    );
    assert!(ws
        .ok(&["task", "show", "0001"])
        .stdout
        .contains("status: review"));
    assert!(
        lock.is_file(),
        "a damaged lease must never be removed silently"
    );
}

#[test]
fn our_own_live_lock_needs_no_takeover() {
    let ws = prepared();
    take_lock(&ws, "bob", 0);

    ws.ok(&["task", "done", "0001", "--agent", "bob"]);
    assert!(!events(&ws).contains("lock_replaced_stale"));
}
