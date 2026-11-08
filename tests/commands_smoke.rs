//! Ported from `lib/tests/test_commands_smoke.py`.
//!
//! Smoke coverage for block/unblock, link, discard, brief, artifact, clean,
//! git begin/end and decision numbering.

mod support;

use support::Ws;

#[test]
fn block_then_unblock() {
    let ws = Ws::new("ai-smoke-block-");
    ws.new_task("Blocked").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);

    ws.ok(&[
        "task",
        "block",
        "0001",
        "--agent",
        "w1",
        "--reason",
        "needs an API key",
    ]);
    assert!(
        ws.ok(&["task", "show", "0001"]).stdout.contains("blocked"),
        "blocked status missing"
    );
    assert!(
        ws.ok(&["history", "0001"])
            .stdout
            .contains("needs an API key"),
        "reason missing from history"
    );

    ws.ok(&["task", "unblock", "0001", "--agent", "w1"]);
    assert!(ws.ok(&["task", "show", "0001"]).stdout.contains("todo"));
}

#[test]
fn link_records_issue_and_pr() {
    let ws = Ws::new("ai-smoke-link-");
    ws.new_task("Linked").ok("task new");
    ws.ok(&[
        "task",
        "link",
        "0001",
        "--issue",
        "https://github.com/o/r/issues/12",
        "--pr",
        "https://github.com/o/r/pull/34",
    ]);
    let shown = ws.ok(&["task", "show", "0001"]).stdout;
    assert!(shown.contains("issues/12"), "{shown}");
    assert!(shown.contains("pull/34"), "{shown}");
}

#[test]
fn discard_is_destructive_so_it_needs_a_terminal() {
    let ws = Ws::new("ai-smoke-discard-");
    ws.new_task("Throwaway").ok("task new");
    let refused = ws.fails(&["task", "discard", "0001"]);
    assert!(
        refused.all().contains("interactive terminal"),
        "{}",
        refused.all()
    );
    let active = ws.ok(&["task", "list", "--json"]).json();
    assert_eq!(active["active"].as_array().map(Vec::len), Some(1));
}

#[test]
fn discard_refuses_a_task_that_someone_holds() {
    let ws = Ws::new("ai-smoke-discard-held-");
    ws.new_task("Held").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    let refused = ws.fails(&["task", "discard", "0001"]);
    assert!(
        refused.stderr.contains("lock held by w1"),
        "{}",
        refused.stderr
    );
    assert!(!refused.stderr.contains("panicked"), "{}", refused.stderr);
    let active = ws.ok(&["task", "list", "--json"]).json();
    assert_eq!(active["active"].as_array().map(Vec::len), Some(1));
}

#[test]
fn brief_contains_the_task_and_the_rules() {
    let ws = Ws::new("ai-smoke-brief-");
    ws.new_task("Brief me").ok("task new");
    let brief = ws.ok(&["brief", "0001"]);
    assert!(brief.stdout.contains("Brief me"), "{}", brief.stdout);
    let payload = ws.ok(&["brief", "0001", "--json"]).json();
    assert!(!payload.is_null(), "{payload}");
}

#[test]
fn a_truncated_brief_keeps_the_rules_and_commands() {
    let ws = Ws::new("ai-smoke-brief-truncate-");
    ws.new_task("Brief me").ok("task new");
    let full = ws.ok(&["brief", "0001"]).stdout;
    let budget = 1200.min(full.chars().count() - 1).max(400);
    let cut = ws
        .ok(&["brief", "0001", "--max-chars", &budget.to_string()])
        .stdout;
    assert!(
        cut.chars().count() <= budget + 120,
        "{}",
        cut.chars().count()
    );
    assert!(
        cut.contains("--- Commands available to the human ---"),
        "{cut}"
    );
    assert!(cut.contains("=== END BRIEF ==="), "{cut}");
    assert!(cut.contains("Operating rules"), "{cut}");
}

#[test]
fn artifact_put_list_clean() {
    let host = Ws::subfolder("ai-smoke-artifact-");
    let scratch = host.host().join("scratch.txt");
    std::fs::write(&scratch, "notes\n").expect("write scratch");

    ws_artifact_put(&host, &scratch);
    assert!(!scratch.exists(), "the artifact must be moved out");
    assert!(
        host.ok(&["artifact", "list"])
            .stdout
            .contains("scratch.txt"),
        "artifact missing from list"
    );
    host.fails(&["artifact", "clean"]);
    host.ok(&["artifact", "clean", "--all"]);
    assert!(host
        .ok(&["artifact", "list"])
        .stdout
        .contains("No quarantined artifacts"));
}

fn ws_artifact_put(ws: &Ws, path: &std::path::Path) {
    ws.ok(&[
        "artifact",
        "put",
        &path.to_string_lossy(),
        "--reason",
        "test",
        "--agent",
        "w1",
    ]);
}

#[test]
fn artifact_put_refuses_paths_outside_the_project() {
    let ws = Ws::new("ai-smoke-artifact-outside-");
    let outside = ws
        .root
        .parent()
        .unwrap_or(&ws.root)
        .join(format!("outside-{}.txt", std::process::id()));
    std::fs::write(&outside, "x\n").expect("write outside");
    let refused = ws.fails(&["artifact", "put", &outside.to_string_lossy()]);
    assert!(
        refused.all().contains("outside the project"),
        "{}",
        refused.all()
    );
    assert!(outside.exists(), "the outside file must survive");
    let _ = std::fs::remove_file(&outside);
}

#[test]
fn clean_needs_a_flag_and_removes_stale_locks() {
    let ws = Ws::new("ai-smoke-clean-");
    let bare = ws.fails(&["clean"]);
    assert!(bare.stderr.contains("--stale-locks"), "{}", bare.stderr);
    ws.ok(&["clean", "--stale-locks", "--logs"]);
}

#[test]
fn begin_and_end_hold_and_free_the_index() {
    let ws = Ws::new("ai-smoke-git-index-");
    ws.ok(&["git", "begin", "--agent", "w1"]);
    assert!(ws.ok(&["lock", "status"]).stdout.contains("@git/index"));
    ws.fails(&["git", "begin", "--agent", "w2"]);
    ws.ok(&["git", "end", "--agent", "w1"]);
    ws.ok(&["git", "begin", "--agent", "w2"]);
}

#[test]
fn decision_numbers_increase_and_never_repeat() {
    let ws = Ws::new("ai-smoke-decisions-");
    for title in ["One", "Two", "Three"] {
        ws.ok(&["decision", "new", title]);
    }
    let listing = ws.ok(&["decision", "list"]).stdout;
    for number in ["0001", "0002", "0003"] {
        assert!(listing.contains(number), "{listing}");
    }
    let reserved: Vec<_> = std::fs::read_dir(ws.path("docs/decisions"))
        .map(|entries| {
            entries
                .flatten()
                .filter(|entry| {
                    let name = entry.file_name().to_string_lossy().to_string();
                    name.starts_with('.') && name.ends_with(".reserved")
                })
                .collect()
        })
        .unwrap_or_default();
    assert!(reserved.is_empty(), "{reserved:?}");
}

#[test]
fn json_payloads_are_compact_and_versioned() {
    let ws = Ws::new("ai-smoke-compact-");
    ws.new_task("Compact").ok("task new");

    let payload = ws.ok(&["now", "--json"]).json();
    assert_eq!(payload["schema"], serde_json::json!(2));
    for task in payload["active"].as_array().expect("active") {
        assert!(task.get("_body").is_none(), "{task}");
        assert!(task.get("_path").is_none(), "{task}");
    }

    let context = ws.ok(&["context", "--json"]).json();
    for task in context["active"].as_array().expect("context active") {
        assert!(task.get("_body").is_none(), "{task}");
    }
}
