//! `ai adopt` must hide the whole `.ai/` folder from the host repository.
//!
//! The workspace is private tooling that lives inside the project, so nothing
//! under `.ai/` may be committed by the host: not the ledger, not runtime state
//! and not a cloned template `.git`.

mod support;

use support::{discover_in, Ws};

fn ignore_lines(ws: &Ws) -> Vec<String> {
    std::fs::read_to_string(ws.host().join(".gitignore"))
        .expect("read host .gitignore")
        .lines()
        .map(|line| line.trim().to_string())
        .collect()
}

fn is_workspace_rule(line: &str) -> bool {
    matches!(line, ".ai" | ".ai/")
}

fn host_with_legacy_rules() -> Ws {
    let ws = Ws::subfolder("ai-adopt-hide-");
    std::fs::write(
        ws.host().join(".gitignore"),
        "# existing\n.ai/runtime/\n.ai/worktrees/\nnode_modules/\n",
    )
    .expect("seed gitignore");
    ws
}

#[test]
fn adopt_hides_the_whole_workspace_folder() {
    let ws = host_with_legacy_rules();
    ws.ok(&["adopt"]);

    let lines = ignore_lines(&ws);
    assert!(
        lines.iter().any(|line| is_workspace_rule(line)),
        "the workspace folder must be ignored: {lines:?}"
    );
    assert_eq!(
        lines.iter().filter(|line| is_workspace_rule(line)).count(),
        1,
        "exactly one workspace rule: {lines:?}"
    );
    assert!(
        !lines.contains(&".ai/runtime/".to_string()),
        "the superseded runtime rule must be dropped: {lines:?}"
    );
    assert!(
        !lines.contains(&".ai/worktrees/".to_string()),
        "the superseded worktree rule must be dropped: {lines:?}"
    );
    assert!(
        lines.contains(&"node_modules/".to_string()),
        "unrelated ignore rules must survive: {lines:?}"
    );
}

#[test]
fn check_accepts_the_migrated_file_and_a_second_run_is_idempotent() {
    let ws = host_with_legacy_rules();
    ws.ok(&["adopt"]);
    let first = std::fs::read_to_string(ws.host().join(".gitignore")).expect("read");

    ws.ok(&["adopt", "--check"]);
    ws.ok(&["adopt"]);
    let second = std::fs::read_to_string(ws.host().join(".gitignore")).expect("read");
    assert_eq!(first, second, "a second adopt must be a no-op");
}

#[test]
fn adopt_ignore_entries_are_the_documented_ones() {
    assert!(
        ai::config::adopt::ADOPT_IGNORE_ENTRIES.contains(&".ai/"),
        "the whole workspace folder must be ignored"
    );
    assert!(ai::config::adopt::ADOPT_IGNORE_ENTRIES.contains(&".github/workflows/ai-check.yml"));
    assert!(
        !ai::config::adopt::ADOPT_IGNORE_ENTRIES.contains(&".ai/runtime/"),
        "the blanket rule replaces the narrow runtime entry"
    );
    assert!(
        !ai::config::adopt::ADOPT_IGNORE_ENTRIES.contains(&".ai/worktrees/"),
        "the blanket rule replaces the narrow worktree entry"
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
fn a_cloned_template_git_stays_untouched_and_ignored() {
    let ws = Ws::subfolder("ai-adopt-nested-git-");
    std::fs::create_dir_all(ws.path(".git")).expect("nested git dir");
    std::fs::write(ws.path(".git/HEAD"), "ref: refs/heads/main\n").expect("nested HEAD");

    ws.ok(&["adopt"]);

    // The clone's metadata is never moved or deleted: ignoring `.ai/` makes it
    // invisible to the host repository without risking the user's checkout.
    assert!(
        ws.exists(".git/HEAD"),
        "nested .ai/.git must be left in place"
    );
    assert!(
        !ws.exists("runtime/state/template-git/git"),
        "adopt must not relocate the clone metadata"
    );
    let lines = ignore_lines(&ws);
    assert!(
        lines.iter().any(|line| is_workspace_rule(line)),
        "{lines:?}"
    );
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
    assert!(ignore_lines(&ws).iter().any(|line| is_workspace_rule(line)));
    assert!(ws.exists(".git/HEAD"), "nested .ai/.git must be left alone");
}
