//! Ported from `lib/tests/test_lock_ownership.py`.
//!
//! Lock ownership: TTL-only staleness, idempotent re-claim, release guard.
//! A task claim outlives the CLI process that created it, so ownership - not
//! PID liveness - decides whether a lease is stale.

mod support;

use serde_json::Value;
use support::Ws;

fn stamp(seconds_ago: i64) -> String {
    (chrono::Utc::now() - chrono::Duration::seconds(seconds_ago))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

fn task_workspace() -> Ws {
    let ws = Ws::new("ai-lock-owner-");
    ws.new_task("Lock ownership").ok("task new");
    ws
}

fn lock_file(ws: &Ws, resource: &str) -> std::path::PathBuf {
    let files: Vec<std::path::PathBuf> = std::fs::read_dir(ws.path("runtime/locks"))
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| {
                    path.file_name()
                        .map(|name| {
                            let name = name.to_string_lossy();
                            name.contains(resource) && name.ends_with(".lock")
                        })
                        .unwrap_or(false)
                })
                .collect()
        })
        .unwrap_or_default();
    assert_eq!(
        files.len(),
        1,
        "expected one lease for {resource}: {files:?}"
    );
    files.into_iter().next().expect("one")
}

fn lock_files(ws: &Ws, resource: &str) -> Vec<std::path::PathBuf> {
    let files: Vec<std::path::PathBuf> = std::fs::read_dir(ws.path("runtime/locks"))
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| {
                    path.file_name()
                        .map(|name| {
                            let name = name.to_string_lossy();
                            name.contains(resource) && name.ends_with(".lock")
                        })
                        .unwrap_or(false)
                })
                .collect()
        })
        .unwrap_or_default();
    files
}

fn read_lock(path: &std::path::Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).expect("read lock")).expect("lock json")
}

fn age_lock(path: &std::path::Path, seconds: i64) {
    let mut payload = read_lock(path);
    payload["started_at"] = Value::String(stamp(seconds));
    payload["updated_at"] = Value::String(stamp(seconds));
    std::fs::write(path, serde_json::to_string(&payload).expect("serialise")).expect("write lock");
}

fn task_text(ws: &Ws) -> String {
    std::fs::read_to_string(ws.one("tasks/active", "0001")).expect("read task")
}

fn events(ws: &Ws) -> String {
    std::fs::read_to_string(ws.path("runtime/state/events.jsonl")).unwrap_or_default()
}

#[test]
fn a_live_task_claim_survives_the_old_pid_window() {
    let ws = task_workspace();
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    age_lock(&lock_file(&ws, "task-0001"), 90);
    let before = task_text(&ws);

    let stolen = ws.fails(&["task", "claim", "0001", "--agent", "bob"]);
    assert!(stolen.all().contains("alice"), "{}", stolen.all());
    assert_eq!(
        task_text(&ws),
        before,
        "a refused claim must not touch the task"
    );
    assert!(before.contains("owner: alice"), "{before}");
    assert!(!before.contains("branch:"), "{before}");
    assert_eq!(read_lock(&lock_file(&ws, "task-0001"))["agent"], "alice");
}

#[test]
fn doctor_does_not_report_a_live_claim_as_stale() {
    let ws = task_workspace();
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    age_lock(&lock_file(&ws, "task-0001"), 90);

    let payload = ws.ok(&["doctor", "--json"]).json();
    let findings = payload["check"]["findings"]
        .as_array()
        .expect("findings array");
    let stale: Vec<&str> = findings
        .iter()
        .filter_map(|finding| finding["message"].as_str())
        .filter(|message| message.starts_with("stale lock"))
        .collect();
    assert!(stale.is_empty(), "{stale:?}");
}

#[test]
fn recover_proposes_nothing_for_a_live_claim() {
    let ws = task_workspace();
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    age_lock(&lock_file(&ws, "task-0001"), 90);

    let payload = ws.ok(&["recover", "--json"]).json();
    let actions = payload["actions"].as_array().expect("actions");
    assert!(
        !actions
            .iter()
            .filter_map(Value::as_str)
            .any(|action| action.contains("stale lock")),
        "{actions:?}"
    );
    assert!(
        !actions
            .iter()
            .filter_map(Value::as_str)
            .any(|action| action.contains("stale owner")),
        "{actions:?}"
    );
}

#[test]
fn reclaiming_your_own_task_renews_the_lease_in_place() {
    let ws = task_workspace();
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    let lock = lock_file(&ws, "task-0001");
    age_lock(&lock, 90);
    let aged = read_lock(&lock);

    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    assert_eq!(
        lock_files(&ws, "task-0001").len(),
        1,
        "a renewal must not duplicate the lease"
    );
    let renewed = read_lock(&lock);
    assert!(
        renewed["updated_at"].as_str() > aged["updated_at"].as_str(),
        "{} vs {}",
        renewed["updated_at"],
        aged["updated_at"]
    );
    assert_eq!(
        renewed["started_at"], aged["started_at"],
        "the original claim time is history"
    );
    assert!(renewed["expires_at"].as_str() > renewed["updated_at"].as_str());
    assert!(!events(&ws).contains("lock_replaced_stale"));
    assert!(task_text(&ws).contains("owner: alice"));
}

#[test]
fn acquire_takes_several_paths_in_one_call() {
    let ws = Ws::new("ai-locks-multi-");
    ws.ok(&[
        "lock", "acquire", "src/a.rs", "src/b.rs", "src/c.rs", "--agent", "alice",
    ]);
    let status = ws.ok(&["lock", "status", "--json"]).json();
    let resources: Vec<&str> = status
        .as_array()
        .expect("locks")
        .iter()
        .filter_map(|lock| lock["resource"].as_str())
        .collect();
    for path in ["src/a.rs", "src/b.rs", "src/c.rs"] {
        assert!(resources.contains(&path), "{path} missing: {resources:?}");
    }
}

#[test]
fn a_failed_batch_releases_the_paths_it_already_took() {
    let ws = Ws::new("ai-locks-multi-rollback-");
    ws.ok(&["lock", "acquire", "src/b.rs", "--agent", "bob"]);
    ws.fails(&[
        "lock", "acquire", "src/a.rs", "src/b.rs", "--agent", "alice",
    ]);
    // alice's first path was rolled back; bob still owns src/b.rs.
    let status = ws.ok(&["lock", "status", "--json"]).json();
    let locks = status.as_array().cloned().unwrap_or_default();
    assert!(
        !locks
            .iter()
            .any(|lock| lock["resource"] == "src/a.rs" && lock["agent"] == "alice"),
        "partial batch must not leak: {locks:?}"
    );
    assert!(locks
        .iter()
        .any(|lock| lock["resource"] == "src/b.rs" && lock["agent"] == "bob"));
}

#[test]
fn release_without_agent_names_the_owner_and_refuses() {
    let ws = task_workspace();
    ws.ok(&[
        "lock",
        "acquire",
        "task-0001",
        "--agent",
        "alice",
        "--task",
        "0001",
    ]);

    let anonymous = ws.fails(&["lock", "release", "task-0001"]);
    assert!(anonymous.all().contains("alice"), "{}", anonymous.all());
    assert!(lock_file(&ws, "task-0001").is_file());
}

#[test]
fn release_by_another_agent_refuses_and_the_owner_succeeds() {
    let ws = task_workspace();
    ws.ok(&[
        "lock",
        "acquire",
        "task-0001",
        "--agent",
        "alice",
        "--task",
        "0001",
    ]);

    let wrong = ws.fails(&["lock", "release", "task-0001", "--agent", "bob"]);
    assert!(wrong.all().contains("alice"), "{}", wrong.all());
    assert!(lock_file(&ws, "task-0001").is_file());

    ws.ok(&["lock", "release", "task-0001", "--agent", "alice"]);
    assert!(lock_files(&ws, "task-0001").is_empty());
}

#[test]
fn force_release_still_works_without_an_agent() {
    let ws = task_workspace();
    ws.ok(&[
        "lock",
        "acquire",
        "task-0001",
        "--agent",
        "alice",
        "--task",
        "0001",
    ]);

    ws.ok(&["lock", "release", "task-0001", "--force"]);
    assert!(lock_files(&ws, "task-0001").is_empty());
}
