//! Ported from `lib/tests/test_adopt_ignore.py`.
//!
//! `ai adopt` must keep the ledger committable in a subfolder install: only
//! ephemeral state may stay local.

mod support;

use support::{discover_in, Ws};

fn ignore_lines(ws: &Ws) -> Vec<String> {
    std::fs::read_to_string(ws.host().join(".gitignore"))
        .expect("read host .gitignore")
        .lines()
        .map(|line| line.trim().to_string())
        .collect()
}

fn host_with_blanket_rule() -> Ws {
    let ws = Ws::subfolder("ai-adopt-ledger-");
    std::fs::write(
        ws.host().join(".gitignore"),
        "# existing\n.ai/\nnode_modules/\n",
    )
    .expect("seed gitignore");
    ws
}

#[test]
fn the_ledger_is_not_ignored_and_the_blanket_rule_is_migrated() {
    let ws = host_with_blanket_rule();
    ws.ok(&["adopt"]);

    let lines = ignore_lines(&ws);
    assert!(
        !lines.contains(&".ai".to_string()),
        "blanket .ai rule: {lines:?}"
    );
    assert!(
        !lines.contains(&".ai/".to_string()),
        "blanket .ai/ rule: {lines:?}"
    );
    assert!(lines.contains(&".ai/runtime/".to_string()), "{lines:?}");
    assert!(lines.contains(&".ai/worktrees/".to_string()), "{lines:?}");
    assert!(
        lines.contains(&"node_modules/".to_string()),
        "unrelated ignore rules must survive: {lines:?}"
    );
}

#[test]
fn check_accepts_the_migrated_file_and_a_second_run_is_idempotent() {
    let ws = host_with_blanket_rule();
    ws.ok(&["adopt"]);
    let first = std::fs::read_to_string(ws.host().join(".gitignore")).expect("read");

    ws.ok(&["adopt", "--check"]);
    ws.ok(&["adopt"]);
    let second = std::fs::read_to_string(ws.host().join(".gitignore")).expect("read");
    assert_eq!(first, second, "a second adopt must be a no-op");
}

#[test]
fn adopt_ignore_entries_are_the_documented_ones() {
    for entry in [
        ".ai/runtime/",
        ".ai/worktrees/",
        ".github/workflows/ai-check.yml",
    ] {
        assert!(
            ai::config::adopt::ADOPT_IGNORE_ENTRIES.contains(&entry),
            "missing {entry}"
        );
    }
    assert!(
        !ai::config::adopt::ADOPT_IGNORE_ENTRIES.contains(&".ai"),
        "a blanket .ai entry would hide the ledger"
    );
}

#[test]
fn adopt_creates_the_managed_block_and_reports_template_installs() {
    let ws = Ws::subfolder("ai-adopt-block-");
    ws.ok(&["adopt"]);
    for file in ["AGENTS.md", "CLAUDE.md"] {
        let text = std::fs::read_to_string(ws.host().join(file)).expect("read adapter");
        assert!(
            text.contains("<!-- ai-workspace:start -->"),
            "{file}: {text}"
        );
        assert!(text.contains("<!-- ai-workspace:end -->"), "{file}: {text}");
    }
}

#[test]
fn a_cloned_template_git_is_moved_out_of_a_subfolder_workspace() {
    let ws = Ws::subfolder("ai-adopt-nested-git-");
    std::fs::create_dir_all(ws.path(".git")).expect("nested git dir");
    std::fs::write(ws.path(".git/HEAD"), "ref: refs/heads/main\n").expect("nested HEAD");

    ws.ok(&["adopt"]);

    assert!(!ws.exists(".git"), "nested .ai/.git must be detached");
    assert!(
        ws.exists("runtime/state/template-git/git/HEAD"),
        "the cloned template metadata must be preserved"
    );
    assert!(std::fs::read_to_string(ws.host().join("AGENTS.md"))
        .expect("host AGENTS.md")
        .contains("ai-workspace:start"));
}

#[test]
fn running_from_an_empty_host_treats_a_cloned_ai_folder_as_a_subfolder() {
    let ws = Ws::subfolder("ai-adopt-fresh-host-");
    std::fs::remove_file(ws.host().join(".gitignore")).expect("remove host marker");
    std::fs::create_dir_all(ws.path(".git")).expect("nested git dir");
    std::fs::write(ws.path(".git/HEAD"), "ref: refs/heads/main\n").expect("nested HEAD");

    // No AI_WORKSPACE and the host has no marker of its own: only the clone's
    // nested .git is present, exactly like `git clone <template> .ai` in a new
    // project.
    discover_in(&ws.host(), &["adopt"]).ok("adopt from host root");

    assert!(std::fs::read_to_string(ws.host().join("AGENTS.md"))
        .expect("host AGENTS.md")
        .contains("ai-workspace:start"));
    assert!(std::fs::read_to_string(ws.host().join(".gitignore"))
        .expect("host .gitignore")
        .contains(".ai/runtime/"));
    assert!(!ws.exists(".git"), "nested .ai/.git must be detached");
}
