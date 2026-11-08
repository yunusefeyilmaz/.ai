//! Ported from `lib/tests/test_claim_rollback.py`.
//!
//! A claim is atomic: a failed task branch releases the task and its locks.

mod support;

use support::Ws;

fn create_task(ws: &Ws) {
    ws.chief_ready();
    ws.ok(&[
        "task",
        "new",
        "Rollback scenario",
        "--no-spec",
        "--allow",
        "src/app.py",
    ]);
}

#[test]
fn dirty_product_tree_rolls_the_claim_back() {
    let ws = Ws::new("ai-claim-rollback-");
    ws.git_init();
    create_task(&ws);
    std::fs::write(ws.path("scratch.txt"), "uncommitted work\n").expect("write scratch");

    let claimed = ws.fails(&["task", "claim", "0001", "--agent", "alice"]);
    assert!(claimed.stderr.contains("rolled back"), "{}", claimed.stderr);
    assert!(
        claimed.stderr.contains("ai task claim 0001 --agent alice"),
        "{}",
        claimed.stderr
    );
    assert!(!claimed.stderr.contains("panicked"), "{}", claimed.stderr);

    let shown = ws.ok(&["task", "show", "0001"]).stdout;
    assert!(shown.contains("status: todo"), "{shown}");
    assert!(shown.contains("owner: None"), "{shown}");
    assert!(shown.contains("lock: None"), "{shown}");

    assert!(ws.ok(&["lock", "status"]).stdout.contains("No locks held."));

    let history = ws.ok(&["history", "0001"]).stdout;
    assert!(history.contains("claim rolled back"), "{history}");
    assert!(
        history.contains("the task branch could not start"),
        "{history}"
    );

    let events = ws.read("runtime/state/events.jsonl");
    assert!(events.contains("claim_rolled_back"), "{events}");
}

#[test]
fn missing_integration_branch_keeps_the_claim_for_setup() {
    let ws = Ws::new("ai-claim-rollback-nobase-");
    ws.git_init();
    // Remove the integration branch so only `ai git setup` can create it.
    ws.git(&["checkout", "-q", "main"]).ok("checkout main");
    ws.git(&["branch", "-D", "develop"]).ok("delete develop");
    create_task(&ws);

    let claimed = ws.run(&["task", "claim", "0001", "--agent", "alice"]);
    assert_eq!(claimed.code, 0, "{}", claimed.all());
    assert!(
        claimed
            .stdout
            .contains("integration branch 'develop' is missing"),
        "{}",
        claimed.stdout
    );
    assert!(ws
        .ok(&["task", "show", "0001"])
        .stdout
        .contains("status: in_progress"));
}

#[test]
fn successful_claim_starts_the_branch_and_prints_once() {
    let ws = Ws::new("ai-claim-branch-");
    ws.git_init();
    create_task(&ws);

    let claimed = ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    assert_eq!(
        claimed.stdout.matches("Claimed 0001 for alice.").count(),
        1,
        "{}",
        claimed.stdout
    );

    let shown = ws.ok(&["task", "show", "0001"]).stdout;
    assert!(shown.contains("status: in_progress"), "{shown}");
    assert!(shown.contains("owner: alice"), "{shown}");
    let branch = ws
        .git(&["branch", "--show-current"])
        .stdout
        .trim()
        .to_string();
    assert!(branch.starts_with("feature/0001-"), "{branch}");
}
