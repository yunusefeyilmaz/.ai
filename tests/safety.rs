//! Regressions for the safety fixes from the audit: state that must not survive
//! a reset, archived tasks that must not change, and leases that must be freed.

mod support;

use std::time::Duration;

use support::Ws;

#[cfg(windows)]
fn slow_command() -> &'static str {
    "ping -n 6 127.0.0.1 >nul"
}
#[cfg(not(windows))]
fn slow_command() -> &'static str {
    "sleep 5"
}

fn stamp(minutes_ago: i64) -> String {
    (chrono::Utc::now() - chrono::Duration::minutes(minutes_ago))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

#[test]
fn a_done_task_is_immutable_until_reopened() {
    let ws = Ws::new("ai-safety-done-immutable-");
    ws.new_task("Archived").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    ws.ok(&["task", "release", "0001", "--agent", "alice"]);
    ws.ok(&["task", "done", "0001", "--agent", "bob"]);

    let link = ws.fails(&["task", "link", "0001", "--issue", "https://example.com/1"]);
    assert!(link.all().contains("archived in done/"), "{}", link.all());
    let block = ws.fails(&["task", "block", "0001", "--agent", "bob", "--reason", "no"]);
    assert!(block.all().contains("archived in done/"), "{}", block.all());
    let spec = ws.fails(&["spec", "check", "0001", "1"]);
    assert!(spec.all().contains("archived in done/"), "{}", spec.all());

    let reopened = ws.fails(&[
        "task", "reopen", "0001", "--agent", "bob", "--status", "nonsense",
    ]);
    assert!(reopened.all().contains("use one of"), "{}", reopened.all());

    ws.ok(&["task", "reopen", "0001", "--agent", "bob"]);
    assert!(ws.glob("tasks/active", "0001-").len() == 1);
    // Now the same commands are allowed again.
    ws.ok(&["task", "link", "0001", "--issue", "https://example.com/1"]);
}

#[test]
fn verify_refuses_an_empty_index_instead_of_reporting_green() {
    let ws = Ws::new("ai-safety-verify-empty-");
    ws.git_init();
    ws.new_task("Nothing staged yet").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    let out = ws.fails(&["git", "verify", "--strict", "--task", "0001"]);
    assert!(
        out.all().contains("Nothing is staged"),
        "verify must fail like commit does: {}",
        out.all()
    );
}

#[test]
fn blocking_a_task_frees_its_file_leases() {
    let ws = Ws::new("ai-safety-block-locks-");
    ws.new_task("Blocked with lease").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&[
        "lock", "acquire", "src/a.rs", "--agent", "alice", "--task", "0001",
    ]);

    ws.ok(&[
        "task", "block", "0001", "--agent", "alice", "--reason", "waiting",
    ]);

    let status = ws.ok(&["lock", "status", "--json"]).json();
    let locks = status.as_array().cloned().unwrap_or_default();
    assert!(
        !locks.iter().any(|lock| lock["resource"] == "src/a.rs"),
        "the file lease must be released: {locks:?}"
    );
    // Another agent can now take the path.
    ws.ok(&["lock", "acquire", "src/a.rs", "--agent", "bob"]);
}

#[test]
fn a_stale_review_claim_stays_in_the_review_queue() {
    let ws = Ws::new("ai-safety-stale-review-");
    ws.new_task("Review me").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);

    // A reviewer claims it, then dies; its lease ages past the stale window.
    ws.ok(&["task", "claim", "0001", "--agent", "carol"]);
    let lock = ws
        .glob("runtime/locks", "task-0001")
        .into_iter()
        .next()
        .expect("task lock");
    let text = std::fs::read_to_string(&lock).expect("read lock");
    let mut value: serde_json::Value = serde_json::from_str(&text).expect("lock json");
    value["updated_at"] = serde_json::json!(stamp(120));
    value["expires_at"] = serde_json::json!(stamp(120));
    std::fs::write(&lock, serde_json::to_string(&value).unwrap()).expect("write lock");

    let out = ws.ok(&["now", "--json", "--agent", "bob"]).json();
    let queue = out["review_queue"].as_array().expect("review queue");
    assert!(
        queue.iter().any(|task| task["id"] == "0001"),
        "a stale review claim must not hide the task: {out}"
    );
    // And a different reviewer can pick it up.
    ws.ok(&["task", "next", "--review", "--agent", "bob"]);
}

#[test]
fn reset_clears_evidence_so_new_ids_cannot_inherit_green() {
    let ws = Ws::new("ai-safety-reset-evidence-");
    ws.new_task("Old proof").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "alice",
        "--allow-empty",
    ]);
    assert!(ws.path("runtime/state/evidence/0001.jsonl").is_file());

    // `ai reset --hard` is interactive-only, so the reset target selection is
    // exercised through the library's target list instead of a pipe.
    let workspace = ai::core::workspace::Workspace::at(&ws.root);
    let targets = ai::cmd::reset::targets(&workspace);
    assert!(
        targets
            .iter()
            .any(|path| path.ends_with("runtime/state/evidence/0001.jsonl")),
        "evidence must be a reset target: {targets:?}"
    );
    assert!(
        targets.iter().any(|path| path.ends_with("events.jsonl")),
        "the event ledger must be a reset target: {targets:?}"
    );
}

#[test]
fn verify_uses_the_callers_worktree() {
    let ws = Ws::new("ai-safety-verify-worktree-");
    ws.git_init();
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=no",
        "git=yes",
        "tests=no",
        "workers=2",
    ]);
    ws.ok(&["task", "new", "Verify me", "--allow", "src/**"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let root = std::path::PathBuf::from(ws.ok(&["worktree", "path", "0001"]).stdout.trim());

    // A staged, lockless path inside the worktree must be reported even without
    // `--task`, because the caller stands in the worktree.
    std::fs::create_dir_all(root.join("other")).expect("other");
    std::fs::write(root.join("other").join("y.rs"), "y\n").expect("y");
    ws.git_in(&root, &["add", "other/y.rs"]).ok("git add");

    let out = support::discover_in(&root, &["git", "verify", "--strict"]);
    assert!(
        out.all().contains("other/y.rs"),
        "verify must see the worktree's staged path: {}",
        out.all()
    );
    assert!(
        out.all().contains("task 0001"),
        "verify must resolve the caller's task: {}",
        out.all()
    );
}

#[test]
fn a_spec_argument_must_point_at_a_file() {
    let ws = Ws::new("ai-safety-spec-path-");
    ws.chief_ready();
    let refused = ws.fails(&["task", "new", "Typo spec", "--spec", "specs/active/nope.md"]);
    assert!(
        refused.all().contains("does not exist"),
        "{}",
        refused.all()
    );
    assert!(ws.glob("tasks/active", "0001-").is_empty());

    ws.write(
        "specs/active/real.md",
        "# Real\n\n## Acceptance criteria\n\n- [ ] It works\n",
    );
    ws.ok(&["task", "new", "Real spec", "--spec", "specs/active/real.md"]);
}

#[test]
fn status_creates_no_state_in_a_fresh_checkout() {
    let ws = Ws::new("ai-safety-status-readonly-");
    // Remove the runtime dir the fixture created.
    let _ = std::fs::remove_dir_all(ws.path("runtime"));
    let _ = std::fs::remove_dir_all(ws.path("tasks"));

    let _ = ws.run(&["status"]);
    assert!(
        !ws.path("runtime").exists(),
        "`ai status` must not create runtime state"
    );
    assert!(
        !ws.path("tasks").exists(),
        "`ai status` must not create the task folders"
    );
}

#[test]
fn a_hanging_check_cannot_hold_a_review() {
    let ws = Ws::new("ai-safety-check-timeout-");
    ws.set_config(|config| {
        config["mode"] = serde_json::json!("strict");
        config["workflow"]["requireCheck"] = serde_json::json!(true);
        config["checks"] = serde_json::json!([{
            "name": "slow",
            "command": slow_command(),
            "timeoutSeconds": 1
        }]);
    });

    let started = std::time::Instant::now();
    let out = ws.fails(&["check"]);
    assert!(out.all().contains("timed out after 1s"), "{}", out.all());
    assert!(
        started.elapsed() < Duration::from_secs(5),
        "the check must be killed, not waited on"
    );
}
