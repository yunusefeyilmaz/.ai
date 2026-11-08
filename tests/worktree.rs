//! Ported from `lib/tests/test_worktree.py`.
//!
//! Per-task Git worktrees: parallel workers in isolated checkouts, one shared
//! workspace.

mod support;

use std::path::PathBuf;

use support::Ws;

fn parallel_workspace(ws: &Ws, titles: &[&str]) {
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=no",
        "git=yes",
        "tests=no",
        "workers=2",
    ]);
    for title in titles {
        ws.ok(&[
            "task",
            "new",
            title,
            "--allow",
            &format!("src/{}/**", title.to_lowercase()),
        ]);
    }
}

fn worktree_of(ws: &Ws, task: &str) -> PathBuf {
    let out = ws.ok(&["worktree", "path", task]);
    PathBuf::from(out.stdout.trim())
}

fn commit_file(ws: &Ws, task: &str, agent: &str, relative: &str) {
    let root = worktree_of(ws, task);
    let target = root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent).expect("create parent");
    }
    std::fs::write(&target, "x\n").expect("write file");
    ws.git_in(&root, &["add", relative]).ok("git add");
    ws.ok(&[
        "lock", "acquire", relative, "--agent", agent, "--task", task,
    ]);
    ws.ok(&[
        "git",
        "commit",
        "--task",
        task,
        "--agent",
        agent,
        "--type",
        "feat",
        "--message",
        &format!("add {relative}"),
    ]);
}

#[test]
fn setup_with_several_workers_switches_to_worktrees() {
    let ws = Ws::new("ai-worktree-isolation-");
    ws.ok(&["setup", "--set", "workers=3"]);
    assert_eq!(
        ws.config()["git"]["isolation"],
        serde_json::json!("worktree")
    );
    ws.ok(&["setup", "--set", "workers=1"]);
    assert_eq!(ws.config()["git"]["isolation"], serde_json::json!("branch"));
}

#[test]
fn claim_creates_an_isolated_checkout_and_keeps_main_clean() {
    let ws = Ws::new("ai-worktree-claim-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);

    let claimed = ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    assert!(claimed.stdout.contains("worktree:"), "{}", claimed.stdout);

    let root = worktree_of(&ws, "0001");
    assert!(root.is_dir());
    assert_eq!(
        root.parent()
            .and_then(|p| p.file_name())
            .and_then(|n| n.to_str()),
        Some("worktrees")
    );
    let branch = ws.git_in(&root, &["branch", "--show-current"]).stdout;
    assert!(branch.trim().starts_with("feature/0001"), "{branch}");

    let main_branch = ws.git(&["branch", "--show-current"]).stdout;
    assert!(
        ["master", "main", "develop"].contains(&main_branch.trim()),
        "{main_branch}"
    );
    let status = ws.git(&["status", "--porcelain"]).stdout;
    assert!(!status.contains("worktrees"), "{status}");

    let briefing = std::fs::read_to_string(root.join("AGENTS.md")).expect("briefing");
    assert!(briefing.contains("ai"), "{briefing}");
    assert_eq!(
        ws.git_in(&root, &["status", "--porcelain"]).stdout.trim(),
        ""
    );
    assert!(ws.ok(&["now", "--agent", "w1"]).stdout.contains("cd "));
}

#[test]
fn two_workers_commit_to_their_own_branches_at_the_same_time() {
    let ws = Ws::new("ai-worktree-two-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha", "Beta"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    ws.ok(&["task", "claim", "0002", "--agent", "w2"]);

    assert_ne!(worktree_of(&ws, "0001"), worktree_of(&ws, "0002"));
    commit_file(&ws, "0001", "w1", "src/alpha/a.py");
    commit_file(&ws, "0002", "w2", "src/beta/b.py");

    let b1 = ws
        .git(&[
            "branch",
            "--list",
            "--format=%(refname:short)",
            "feature/0001*",
        ])
        .stdout;
    let b2 = ws
        .git(&[
            "branch",
            "--list",
            "--format=%(refname:short)",
            "feature/0002*",
        ])
        .stdout;
    let subject1 = ws.git(&["log", "-1", "--format=%s", b1.trim()]).stdout;
    let subject2 = ws.git(&["log", "-1", "--format=%s", b2.trim()]).stdout;
    assert!(subject1.contains("add src/alpha/a.py"), "{subject1}");
    assert!(subject2.contains("add src/beta/b.py"), "{subject2}");

    let tree = ws.git(&["ls-tree", "-r", "--name-only", b1.trim()]).stdout;
    assert_eq!(tree.matches("src/beta").count(), 0, "{tree}");

    let listing = ws.ok(&["worktree", "list"]).stdout;
    assert!(listing.contains("task 0001"), "{listing}");
    assert!(listing.contains("task 0002"), "{listing}");
}

#[test]
fn scope_is_enforced_inside_the_worktree() {
    let ws = Ws::new("ai-worktree-scope-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);

    let root = worktree_of(&ws, "0001");
    let other = root.join("src").join("other");
    std::fs::create_dir_all(&other).expect("create other");
    std::fs::write(other.join("x.py"), "x\n").expect("write other");
    ws.git_in(&root, &["add", "src/other/x.py"])
        .ok("git add other");

    let verified = ws.fails(&["git", "verify", "--task", "0001"]);
    assert!(
        verified.all().contains("outside allowed scope")
            || verified.all().contains("outside the scope"),
        "{}",
        verified.all()
    );
}

#[test]
fn finish_merges_then_cleans_up_the_worktree() {
    let ws = Ws::new("ai-worktree-delivery-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    commit_file(&ws, "0001", "w1", "src/alpha/MARKER");
    assert!(!ws.path("src/alpha/MARKER").exists());

    ws.ok(&["task", "review", "0001", "--agent", "w1"]);
    ws.ok(&["task", "release", "0001", "--agent", "w1"]);

    let root = worktree_of(&ws, "0001");
    ws.ok(&["git", "finish", "--task", "0001", "--agent", "r1"]);
    assert!(
        !root.exists(),
        "the worktree must be removed after the merge"
    );
    assert_eq!(
        ws.git(&["branch", "--show-current"]).stdout.trim(),
        "develop"
    );
    assert!(ws.path("src/alpha/MARKER").exists());
    assert!(ws
        .git(&["branch", "--list", "feature/0001*"])
        .stdout
        .trim()
        .is_empty());

    ws.ok(&["task", "done", "0001", "--agent", "r1"]);
    assert!(ws
        .ok(&["worktree", "list"])
        .stdout
        .contains("No task worktrees"));
}

#[test]
fn finish_refuses_uncommitted_work_in_the_worktree() {
    let ws = Ws::new("ai-worktree-dirty-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let root = worktree_of(&ws, "0001");
    ws.ok(&["task", "review", "0001", "--agent", "w1"]);

    std::fs::write(root.join("unfinished.txt"), "wip\n").expect("write wip");
    let refused = ws.fails(&["git", "finish", "--task", "0001", "--agent", "r1"]);
    assert!(
        refused.stderr.contains("uncommitted changes"),
        "{}",
        refused.stderr
    );
    assert!(root.exists());
}

#[test]
fn worktree_resolves_to_the_shared_workspace() {
    let ws = Ws::new("ai-worktree-discovery-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let root = worktree_of(&ws, "0001");

    // The fixture commits the whole workspace, so the worktree is a full copy of
    // the ledger too. Discovery must still point at the shared one.
    let now = support::discover_in(&root, &["now", "--agent", "w1"]);
    assert_eq!(now.code, 0, "{}", now.all());
    assert!(now.stdout.contains("1 active"), "{}", now.stdout);
    assert!(now.stdout.contains("0001"), "{}", now.stdout);

    let doctor = support::discover_in(&root, &["doctor"]);
    assert!(
        !doctor.all().contains("missing required path: runtime"),
        "{}",
        doctor.all()
    );

    // Evidence recorded from inside the worktree is visible to the main workspace.
    let check = support::discover_in(
        &root,
        &["check", "--task", "0001", "--agent", "w1", "--allow-empty"],
    );
    assert_eq!(check.code, 0, "{}", check.all());
    assert!(ws.path("runtime/state/evidence/0001.jsonl").is_file());
}

#[test]
fn checks_and_evidence_follow_the_worktree_checkout() {
    let ws = Ws::new("ai-worktree-evidence-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.set_config(|config| {
        config["mode"] = serde_json::json!("strict");
        config["workflow"]["requireCheck"] = serde_json::json!(true);
        config["checks"] = serde_json::json!([{ "name": "ok", "command": "echo ok" }]);
    });
    let claimed = ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let root = worktree_of(&ws, "0001");
    assert!(claimed.stdout.contains("worktree:"), "{}", claimed.stdout);

    commit_file(&ws, "0001", "w1", "src/alpha/MARKER");

    // `ai check` runs in the task checkout and records that checkout's HEAD.
    let checked = ws.ok(&["check", "--task", "0001", "--agent", "w1"]);
    assert!(
        checked.all().contains("Evidence recorded"),
        "{}",
        checked.all()
    );
    let worktree_head = ws.git_in(&root, &["rev-parse", "HEAD"]).stdout;
    let main_head = ws.git(&["rev-parse", "HEAD"]).stdout;
    assert_ne!(worktree_head.trim(), main_head.trim());
    let evidence = std::fs::read_to_string(ws.path("runtime/state/evidence/0001.jsonl"))
        .expect("evidence file");
    assert!(evidence.contains(worktree_head.trim()), "{evidence}");

    ws.ok(&["task", "review", "0001", "--agent", "w1"]);
    ws.ok(&["task", "release", "0001", "--agent", "w1"]);
    ws.ok(&["git", "finish", "--task", "0001", "--agent", "r1"]);
    assert!(ws.path("src/alpha/MARKER").exists());
}

#[test]
fn finish_merges_the_worktree_branch_not_the_integration_tree() {
    let ws = Ws::new("ai-worktree-gate-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.set_config(|config| {
        config["mode"] = serde_json::json!("strict");
        config["workflow"]["requireCheck"] = serde_json::json!(true);
        // The check only passes where HEAD contains the task's marker file, so a
        // gate that ran on develop (before the merge) would fail.
        config["checks"] = serde_json::json!([{ "name": "marker", "command": "git cat-file -e HEAD:src/alpha/MARKER" }]);
    });
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    commit_file(&ws, "0001", "w1", "src/alpha/MARKER");
    ws.ok(&["task", "review", "0001", "--agent", "w1"]);
    ws.ok(&["task", "release", "0001", "--agent", "w1"]);

    ws.ok(&["git", "finish", "--task", "0001", "--agent", "r1"]);
    assert!(ws.path("src/alpha/MARKER").exists());
}

#[test]
fn orphan_worktrees_are_reported_and_pruned() {
    let ws = Ws::new("ai-worktree-prune-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let root = worktree_of(&ws, "0001");

    ws.ok(&["task", "done", "0001", "--agent", "boss", "--force"]);
    assert!(
        ws.ok(&["doctor"]).stdout.contains("has no active task"),
        "doctor must flag the orphan worktree"
    );

    ws.ok(&["worktree", "prune"]);
    assert!(!root.exists());
    assert!(!ws.ok(&["doctor"]).stdout.contains("has no active task"));
}

#[test]
fn prune_keeps_worktrees_with_uncommitted_changes() {
    let ws = Ws::new("ai-worktree-prune-dirty-");
    ws.git_init();
    parallel_workspace(&ws, &["Alpha"]);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let root = worktree_of(&ws, "0001");

    std::fs::write(root.join("precious.txt"), "keep me\n").expect("write precious");
    ws.ok(&["task", "done", "0001", "--agent", "boss", "--force"]);

    let kept = ws.ok(&["worktree", "prune"]);
    assert!(
        kept.stderr.contains("uncommitted changes"),
        "{}",
        kept.stderr
    );
    assert!(root.join("precious.txt").exists());
}
