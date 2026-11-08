//! Ported from `lib/tests/test_review_gate.py`.
//!
//! Review is a Git gate: correct branch, clean tree, evidence on HEAD.

mod support;

use support::Ws;

fn porcelain(output: &str) -> Vec<(String, String)> {
    ai::git::repo::parse_porcelain_z(output)
}

#[test]
fn rename_consumes_the_old_path() {
    assert_eq!(
        porcelain("R  new/name.txt\0old/name.txt\0"),
        vec![("R ".to_string(), "new/name.txt".to_string())]
    );
}

#[test]
fn copy_consumes_the_old_path() {
    assert_eq!(
        porcelain("C  copy.txt\0source.txt\0"),
        vec![("C ".to_string(), "copy.txt".to_string())]
    );
}

#[test]
fn delete_modify_and_untracked_are_preserved() {
    assert_eq!(
        porcelain(" D gone.txt\0 M changed.txt\0?? new.txt\0"),
        vec![
            (" D".to_string(), "gone.txt".to_string()),
            (" M".to_string(), "changed.txt".to_string()),
            ("??".to_string(), "new.txt".to_string())
        ]
    );
}

fn claimed(ws: &Ws) {
    ws.chief_ready();
    ws.ok(&["task", "new", "Review gate", "--no-spec"]);
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
}

fn commit_all(ws: &Ws, message: &str) {
    ws.git(&["add", "-A"]).ok("git add");
    ws.git(&["commit", "-qm", message]).ok("git commit");
}

#[test]
fn clean_task_branch_passes() {
    let ws = Ws::new("ai-review-clean-");
    ws.git_init();
    claimed(&ws);
    commit_all(&ws, "feat: work");
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
}

#[test]
fn wrong_branch_is_refused() {
    let ws = Ws::new("ai-review-branch-");
    ws.git_init();
    claimed(&ws);
    commit_all(&ws, "feat: work");
    ws.git(&["checkout", "-b", "other"]).ok("checkout other");

    let refused = ws.fails(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        refused.stderr.contains("belongs to branch"),
        "{}",
        refused.stderr
    );
    assert!(
        refused.stderr.contains("git checkout"),
        "{}",
        refused.stderr
    );
}

#[test]
fn dirty_product_tree_is_refused() {
    let ws = Ws::new("ai-review-dirty-");
    ws.git_init();
    claimed(&ws);
    commit_all(&ws, "feat: work");
    std::fs::create_dir_all(ws.path("src")).expect("mkdir src");
    std::fs::write(ws.path("src/dirty.py"), "pass\n").expect("write dirty");

    let refused = ws.fails(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        refused.stderr.contains("uncommitted product changes"),
        "{}",
        refused.stderr
    );
    assert!(refused.stderr.contains("src/"), "{}", refused.stderr);
    assert!(
        refused.stderr.contains("ai git commit"),
        "{}",
        refused.stderr
    );
}

#[test]
fn evidence_from_another_head_is_refused() {
    let ws = Ws::new("ai-review-evidence-");
    ws.git_init();
    claimed(&ws);
    commit_all(&ws, "feat: work");
    ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "alice",
        "--allow-empty",
    ]);

    std::fs::write(ws.path("NOTES.md"), "moved on\n").expect("write notes");
    commit_all(&ws, "fix: move on");

    let refused = ws.fails(&["task", "review", "0001", "--agent", "alice"]);
    assert!(
        refused.stderr.contains("evidence belongs to"),
        "{}",
        refused.stderr
    );
    assert!(
        refused.stderr.contains("ai check --task 0001"),
        "{}",
        refused.stderr
    );

    ws.ok(&[
        "check",
        "--task",
        "0001",
        "--agent",
        "alice",
        "--allow-empty",
    ]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
}

#[test]
fn workspace_without_git_still_reviews() {
    let ws = Ws::new("ai-review-nogit-");
    claimed(&ws);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
}
