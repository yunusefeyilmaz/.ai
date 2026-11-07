//! Ported from `lib/tests/test_metadata_commit.py`.
//!
//! `commit_task_metadata` may only amend the ledger paths it owns: the task file
//! and the board. Anything else in the index belongs to the user's work.

mod support;

use support::Ws;

struct Fixture {
    ws: Ws,
    task: std::path::PathBuf,
}

impl Fixture {
    fn new(prefix: &str) -> Self {
        let ws = Ws::new(prefix);
        ws.write("tasks/0001-probe.md", "---\nid: 0001\n---\n\nbody\n");
        ws.write("tasks/BOARD.md", "# board\n");
        ws.git_init();
        let task = ws.path("tasks/0001-probe.md");
        Fixture { ws, task }
    }

    fn update_ledger(&self) {
        self.ws.write(
            "tasks/0001-probe.md",
            "---\nid: 0001\n---\n\nbody, updated\n",
        );
        self.ws.write("tasks/BOARD.md", "# board\n\n- 0001\n");
    }

    fn stage(&self, name: &str) {
        self.ws.write(name, "user work\n");
        self.ws.git(&["add", "--", name]).ok("git add");
    }

    fn record(&self, message: &str, amend: bool) -> Option<String> {
        let workspace = ai::core::workspace::Workspace::at(&self.ws.root);
        ai::git::flow::commit_task_metadata(&workspace, &self.ws.root, &self.task, message, amend)
    }
}

#[test]
fn amend_folds_in_the_ledger_paths_and_nothing_else() {
    let fixture = Fixture::new("ai-metadata-amend-");
    fixture.update_ledger();

    let result = fixture.record("", true);
    assert!(result.is_some(), "the amend should produce a commit");

    assert_eq!(
        fixture
            .ws
            .git(&["rev-list", "--count", "HEAD"])
            .stdout
            .trim(),
        "1",
        "an amend replaces the last commit instead of adding one"
    );
    assert_eq!(
        fixture.ws.git(&["log", "-1", "--pretty=%s"]).stdout.trim(),
        "test baseline"
    );
    let committed = fixture
        .ws
        .git(&["show", "--name-only", "--pretty=format:", "HEAD"])
        .stdout;
    // The fixture stores the board at tasks/BOARD.md, which is the board path.
    assert!(committed.contains("tasks/0001-probe.md"), "{committed}");
    assert!(committed.contains("tasks/BOARD.md"), "{committed}");
    assert_eq!(fixture.ws.git(&["status", "--porcelain"]).stdout.trim(), "");
}

#[test]
fn unrelated_staged_path_skips_the_amend_and_stays_staged() {
    let fixture = Fixture::new("ai-metadata-skip-");
    fixture.stage("scratch.txt");
    fixture.update_ledger();

    let result = fixture.record("", true);
    assert!(result.is_none(), "an amend must not swallow foreign paths");

    assert_eq!(
        fixture
            .ws
            .git(&["rev-list", "--count", "HEAD"])
            .stdout
            .trim(),
        "1"
    );
    let committed = fixture
        .ws
        .git(&["show", "--name-only", "--pretty=format:", "HEAD"])
        .stdout;
    assert!(!committed.contains("scratch.txt"), "{committed}");

    let staged = fixture.ws.git(&["diff", "--cached", "--name-only"]).stdout;
    assert!(staged.contains("scratch.txt"), "{staged}");
    assert!(staged.contains("tasks/0001-probe.md"), "{staged}");
}

#[test]
fn new_commit_keeps_its_message_and_ignores_other_staged_paths() {
    let fixture = Fixture::new("ai-metadata-new-");
    fixture.stage("scratch.txt");
    fixture.update_ledger();

    let result = fixture.record("chore(task): record merge 0001", false);
    assert!(result.is_some(), "the ledger commit should be created");

    assert_eq!(
        fixture
            .ws
            .git(&["rev-list", "--count", "HEAD"])
            .stdout
            .trim(),
        "2"
    );
    assert_eq!(
        fixture.ws.git(&["log", "-1", "--pretty=%s"]).stdout.trim(),
        "chore(task): record merge 0001"
    );
    let committed = fixture
        .ws
        .git(&["show", "--name-only", "--pretty=format:", "HEAD"])
        .stdout;
    assert!(committed.contains("tasks/0001-probe.md"), "{committed}");
    assert!(committed.contains("tasks/BOARD.md"), "{committed}");
    assert!(!committed.contains("scratch.txt"), "{committed}");
    assert!(fixture
        .ws
        .git(&["diff", "--cached", "--name-only"])
        .stdout
        .contains("scratch.txt"));
}

#[test]
fn unexpected_staged_reports_only_foreign_paths() {
    // `uncovered_staged` is the public equivalent of Python's
    // `unexpected_staged`: ledger paths never need a lease.
    let ws = Ws::new("ai-metadata-unexpected-");
    ws.write("tasks/0001-probe.md", "---\nid: 0001\n---\n\nbody\n");
    ws.write("src/app.rs", "fn main() {}\n");
    let workspace = ai::core::workspace::Workspace::at(&ws.root);

    let state = serde_json::json!({
        "staged": ["tasks/0001-probe.md", "specs/active/x.md", "src/app.rs"],
    });
    let (uncovered, _) = ai::git::flow::uncovered_staged(&workspace, &state);
    assert_eq!(uncovered, vec!["src/app.rs".to_string()]);
}
