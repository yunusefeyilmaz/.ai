//! Ported from `lib/tests/test_checkpoint_gate.py`.
//!
//! Delivery needs a checkpoint when a claim is old; `done` leaves a clean tree
//! by committing the archived task, shipped spec and board.

mod support;

use support::Ws;

fn claimed(ws: &Ws, agent: &str) {
    ws.new_task("Checkpoint gate").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", agent]);
}

fn commit_all(ws: &Ws, message: &str) {
    ws.git(&["add", "-A"]).ok("git add");
    ws.git(&["commit", "-qm", message]).ok("git commit");
}

fn old_claim_workspace() -> Ws {
    let ws = Ws::new("ai-checkpoint-gate-old-");
    ws.git_init();
    claimed(&ws, "alice");

    // Backdate the claim itself instead of lowering the warning threshold to
    // zero: claim and review can land in the same whole second, and a zero
    // threshold then makes the gate depend on timing rather than claim age.
    let lock = ws.one("runtime/locks", "task-0001");
    let mut holder: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&lock).expect("read claim lock"))
            .expect("claim lock json");
    holder["started_at"] = serde_json::json!("2000-01-01T00:00:00Z");
    std::fs::write(
        &lock,
        serde_json::to_string_pretty(&holder).expect("serialise claim lock"),
    )
    .expect("write claim lock");

    commit_all(&ws, "feat: work");
    ws
}

#[test]
fn old_claim_is_refused_until_a_checkpoint_exists() {
    let ws = old_claim_workspace();
    let refused = ws.fails(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        refused.stderr.contains("without a checkpoint"),
        "{}",
        refused.stderr
    );
    assert!(
        refused.stderr.contains("ai checkpoint 0001"),
        "{}",
        refused.stderr
    );
    assert!(refused.stderr.contains("--next"), "{}", refused.stderr);

    ws.ok(&[
        "checkpoint",
        "0001",
        "--agent",
        "alice",
        "--next",
        "deliver",
    ]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
}

#[test]
fn fresh_claim_delivers_without_a_checkpoint() {
    let ws = Ws::new("ai-checkpoint-gate-fresh-");
    ws.git_init();
    claimed(&ws, "alice");
    commit_all(&ws, "feat: work");

    let reviewed = ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        !reviewed.stderr.contains("without a checkpoint"),
        "{}",
        reviewed.stderr
    );
}

#[test]
fn checkpoint_records_status_branch_head_and_next_step() {
    let ws = Ws::new("ai-checkpoint-gate-content-");
    ws.git_init();
    claimed(&ws, "alice");

    ws.ok(&["checkpoint", "0001", "--agent", "alice"]);
    let text = ws.read("runtime/state/checkpoints/0001.md");
    let head = ws
        .git(&["rev-parse", "--short=8", "HEAD"])
        .stdout
        .trim()
        .to_string();

    assert!(!text.contains("<!--"), "unresolved placeholders:\n{text}");
    assert!(text.contains("in_progress"), "{text}");
    assert!(text.contains("branch feature/0001-"), "{text}");
    assert!(text.contains(&head), "HEAD {head} missing from:\n{text}");
    assert!(text.contains("## Next steps"), "{text}");
    assert!(text.contains("Continue task 0001"), "{text}");
}

#[test]
fn done_commits_the_archived_task_spec_and_board() {
    let ws = Ws::new("ai-checkpoint-gate-done-");
    ws.git_init();
    claimed(&ws, "alice");
    std::fs::write(ws.path("sample.txt"), "work\n").expect("write sample");
    commit_all(&ws, "feat: work");

    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    commit_all(&ws, "chore: record review");
    ws.ok(&["git", "finish", "--task", "0001", "--agent", "bob"]);
    ws.ok(&["task", "done", "0001", "--agent", "bob"]);

    let status = ws.git(&["status", "--porcelain"]).stdout.trim().to_string();
    assert_eq!(
        status, "",
        "working tree must be clean after done: {status}"
    );

    let subject = ws
        .git(&["log", "-1", "--pretty=%s"])
        .stdout
        .trim()
        .to_string();
    assert_eq!(subject, "chore(task): record done 0001");

    let committed = ws
        .git(&["show", "--name-only", "--pretty=format:", "HEAD"])
        .stdout;
    assert!(committed.contains("tasks/done/0001-"), "{committed}");
    assert!(committed.contains("specs/done/0001-"), "{committed}");
    assert!(committed.contains("tasks/BOARD.md"), "{committed}");
    assert!(ws.glob("tasks/active", "0001-").is_empty());
}
