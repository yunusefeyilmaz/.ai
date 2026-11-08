//! Ported from `lib/tests/test_workflow.py` and `test_request_changes.py`.
//!
//! Required transitions (gates), `ai now`, `ai context`, ADRs.

mod support;

use support::Ws;

fn new_claimed(ws: &Ws, agent: &str) {
    ws.new_task("Gate work").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", agent]);
}

#[test]
fn done_requires_review_first() {
    let ws = Ws::new("ai-flow-review-first-");
    new_claimed(&ws, "alice");
    let refused = ws.fails(&["task", "done", "0001", "--agent", "alice"]);
    assert!(refused.all().contains("not in review"), "{}", refused.all());
}

#[test]
fn producer_cannot_approve_own_work() {
    let ws = Ws::new("ai-flow-producer-");
    new_claimed(&ws, "alice");
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    let refused = ws.fails(&["task", "done", "0001", "--agent", "alice"]);
    assert!(
        refused.all().contains("producer never approves"),
        "{}",
        refused.all()
    );
}

#[test]
fn other_agent_completes_after_review() {
    let ws = Ws::new("ai-flow-other-");
    new_claimed(&ws, "alice");
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
    ws.ok(&["task", "release", "0001", "--agent", "alice"]);
    ws.ok(&["task", "done", "0001", "--agent", "bob"]);

    let archived = std::fs::read_to_string(ws.one("tasks/done", "0001")).expect("read archived");
    assert!(archived.contains("submitted_by: alice"), "{archived}");
    assert!(archived.contains("reviewed_by: bob"), "{archived}");
}

#[test]
fn review_can_be_disabled_in_config() {
    let ws = Ws::new("ai-flow-noreview-");
    ws.set_config(|config| config["workflow"]["requireReview"] = serde_json::json!(false));
    new_claimed(&ws, "alice");
    ws.ok(&["task", "done", "0001", "--agent", "alice"]);
}

#[test]
fn strict_mode_review_needs_a_green_check() {
    let ws = Ws::with_mode("ai-flow-strict-", "strict");
    new_claimed(&ws, "alice");

    let refused = ws.fails(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        refused.all().contains("no project checks are configured"),
        "{}",
        refused.all()
    );

    ws.ok(&["setup", "--check", "unit=cmd /C echo 1"]);
    let accepted = ws.run(&["task", "review", "0001", "--agent", "alice"]);
    assert_eq!(accepted.code, 0, "{}", accepted.all());
    assert!(
        accepted.all().contains("Running the project checks"),
        "{}",
        accepted.all()
    );
    assert!(
        accepted.stdout.contains("STOP: report what you delivered"),
        "{}",
        accepted.stdout
    );
}

#[test]
fn empty_workspace_says_run_setup() {
    let ws = Ws::new("ai-flow-empty-");
    ws.set_config(|config| config["preferences"]["confirmed"] = serde_json::json!(false));
    let out = ws.ok(&["now"]);
    assert!(out.stdout.contains("NEXT  ai setup"), "{}", out.stdout);
    assert!(out.stdout.lines().count() <= 12, "{}", out.stdout);
}

#[test]
fn ready_task_recommends_next() {
    let ws = Ws::new("ai-flow-ready-");
    ws.set_config(|config| config["preferences"]["confirmed"] = serde_json::json!(true));
    ws.new_task("First thing").ok("task new");
    let out = ws.ok(&["now", "--agent", "alice"]).stdout;
    assert!(out.contains("ai task next --agent alice"), "{out}");
    assert!(out.contains("READY"), "{out}");
}

#[test]
fn a_fresh_claim_points_at_the_work_before_the_checks() {
    let ws = Ws::with_mode("ai-flow-fresh-claim-", "strict");
    ws.git_init();
    ws.set_config(|config| {
        config["checks"] = serde_json::json!([{ "name": "ok", "command": "echo ok" }]);
    });
    new_claimed(&ws, "alice");

    let out = ws.ok(&["now", "--agent", "alice"]).stdout;
    assert!(out.contains("NEXT  ai task show 0001"), "{out}");
    assert!(!out.contains("ai check --task"), "{out}");
}

#[test]
fn plan_apply_commits_the_task_ledger() {
    let ws = Ws::new("ai-flow-plan-commit-");
    ws.git_init();
    ws.chief_ready();
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=no",
        "git=yes",
        "tests=no",
    ]);
    ws.write(
        "plan.json",
        r#"{"tasks":[{"key":"api","title":"Build the API","priority":"high","acceptance":["It responds"]}]}"#,
    );
    ws.blueprint();

    ws.ok(&["plan", "apply", "plan.json", "--role", "chief"]);

    let tracked = ws.git(&["ls-files", "tasks/active"]).stdout;
    assert!(
        tracked.contains("0001-"),
        "the task must be committed: {tracked}"
    );
    let specs = ws.git(&["ls-files", "specs/active"]).stdout;
    assert!(
        specs.contains("0001-"),
        "the spec must be committed: {specs}"
    );
    let status = ws.git(&["status", "--porcelain"]).stdout;
    assert!(
        !status.contains("tasks/") && !status.contains("specs/"),
        "the ledger must start clean: {status}"
    );
}

#[test]
fn strict_mode_requires_the_users_plan_approval() {
    let ws = Ws::with_mode("ai-flow-plan-approval-", "strict");
    ws.git_init();
    ws.chief_ready();
    ws.write(
        "plan.json",
        r#"{"tasks":[{"key":"api","title":"Build the API","priority":"high","acceptance":["It responds"]}]}"#,
    );
    ws.blueprint();

    let refused = ws.fails(&["plan", "apply", "plan.json", "--role", "chief"]);
    assert!(refused.all().contains("--approved-by"), "{}", refused.all());
    assert!(ws.glob("tasks/active", "0001-").is_empty());

    ws.ok(&[
        "plan",
        "apply",
        "plan.json",
        "--role",
        "chief",
        "--approved-by",
        "user",
    ]);
    assert!(ws.path("runtime/state/plan-approval.json").is_file());
}

#[test]
fn context_lists_open_and_decisions() {
    let ws = Ws::new("ai-flow-context-");
    ws.new_task("Open work").ok("task new");
    ws.ok(&[
        "decision",
        "new",
        "Use files not a database",
        "--agent",
        "alice",
    ]);

    let listing = ws.ok(&["decision", "list"]);
    assert!(
        listing.stdout.contains("Use files not a database"),
        "{}",
        listing.stdout
    );

    let out = ws.ok(&["context"]).stdout;
    assert!(out.contains("Open work"), "{out}");
    assert!(out.contains("0001-use-files-not-a-database"), "{out}");
}

#[test]
fn checkpoint_next_step_shows_in_context() {
    let ws = Ws::new("ai-flow-context-ckpt-");
    ws.new_task("Resumable").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&[
        "checkpoint",
        "0001",
        "--agent",
        "alice",
        "--next",
        "wire the parser",
    ]);
    let out = ws.ok(&["context"]).stdout;
    assert!(out.contains("next: wire the parser"), "{out}");
}

#[test]
fn every_command_appears_in_help() {
    let help = support::help();
    for name in ["now", "context", "decision", "task", "git", "lock"] {
        assert!(help.stdout.contains(name), "missing {name} in help");
    }
}

/// Hand a task over to review with no reviewer claim yet.
fn delivered(ws: &Ws, agent: &str) {
    ws.new_task("Rework").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", agent]);
    ws.ok(&["task", "review", "0001", "--agent", agent]);
    ws.ok(&["task", "release", "0001", "--agent", agent]);
}

#[test]
fn unclaimed_review_is_refused_with_the_claiming_command() {
    let ws = Ws::new("ai-changes-unclaimed-");
    delivered(&ws, "alice");
    let refused = ws.fails(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "bob",
        "--reason",
        "x",
    ]);
    assert!(
        refused.stderr.contains("without a reviewer claim"),
        "{}",
        refused.stderr
    );
    assert!(
        refused.stderr.contains("ai task next --review --agent bob"),
        "{}",
        refused.stderr
    );
    assert!(ws.ok(&["task", "show", "0001"]).stdout.contains("review"));
}

#[test]
fn reviewer_who_claimed_can_request_changes() {
    let ws = Ws::new("ai-changes-claimed-");
    delivered(&ws, "alice");
    ws.ok(&["task", "next", "--review", "--agent", "bob"]);

    ws.ok(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "bob",
        "--reason",
        "missing tests",
    ]);

    let listing = ws.ok(&["task", "list", "--json"]).stdout;
    assert!(listing.contains("changes_requested"), "{listing}");

    let text = std::fs::read_to_string(ws.one("tasks/active", "0001")).expect("read task");
    assert!(text.contains("changes_requested_by: bob"), "{text}");
    assert!(text.contains("missing tests"), "{text}");

    // the reviewer's claim is gone, so the producer can pick the task up again
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
}

#[test]
fn a_plain_claim_on_a_review_task_is_enough() {
    let ws = Ws::new("ai-changes-plainclaim-");
    delivered(&ws, "alice");
    ws.ok(&["task", "claim", "0001", "--agent", "bob"]);
    ws.ok(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "bob",
        "--reason",
        "x",
    ]);
}

#[test]
fn another_reviewers_claim_is_refused() {
    let ws = Ws::new("ai-changes-other-");
    delivered(&ws, "alice");
    ws.ok(&["task", "next", "--review", "--agent", "bob"]);

    let refused = ws.fails(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "carol",
        "--reason",
        "x",
    ]);
    assert!(
        refused.stderr.contains("claimed for review by bob"),
        "{}",
        refused.stderr
    );
    assert!(
        refused.stderr.contains("ai task release 0001 --agent bob"),
        "{}",
        refused.stderr
    );

    // the claim survives the refused attempt
    ws.fails(&["task", "next", "--review", "--agent", "carol"]);
    ws.ok(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "bob",
        "--reason",
        "y",
    ]);
}

#[test]
fn submitter_is_refused_before_the_claim_check() {
    let ws = Ws::new("ai-changes-submitter-");
    delivered(&ws, "alice");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    let refused = ws.fails(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "alice",
        "--reason",
        "x",
    ]);
    assert!(refused.stderr.contains("independent"), "{}", refused.stderr);
}

#[test]
fn a_task_outside_review_keeps_its_refusal() {
    let ws = Ws::new("ai-changes-early-");
    ws.new_task("Early").ok("task new");
    let refused = ws.fails(&[
        "task",
        "request-changes",
        "0001",
        "--agent",
        "bob",
        "--reason",
        "x",
    ]);
    assert!(refused.stderr.contains("in review"), "{}", refused.stderr);
}
