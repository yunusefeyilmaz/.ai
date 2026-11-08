//! Ported from `lib/tests/test_acceptance_criteria.py`.
//!
//! Acceptance criteria are tickable state, not decoration: the parser keeps
//! `[ ]` vs `[x]`, `ai spec check` ticks, `ai spec show` counts, `task review`
//! refuses while a real criterion is unticked, `ai review` renders the boxes,
//! and the archived spec says `shipped`.

mod support;

use ai::specs::spec;
use support::Ws;

const SPEC: &str = "---
status: draft
task: 0001
approved_by: null
approved_on: null
---

# Acceptance criteria scenario

## Intent

Prove the boxes are real.

## Acceptance criteria

- [ ] the first criterion holds
- [x] the second criterion holds

## Out of scope

Nothing.
";

fn write_spec(ws: &Ws) -> std::path::PathBuf {
    let path = ws.one("specs/active", "0001");
    std::fs::write(&path, SPEC).expect("write spec");
    path
}

fn task_body(ws: &Ws) -> String {
    std::fs::read_to_string(ws.one("tasks/active", "0001")).expect("read task")
}

fn prepared() -> Ws {
    let ws = Ws::new("ai-criteria-");
    ws.new_task("Criteria scenario").ok("task new");
    write_spec(&ws);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    ws
}

fn gated() -> Ws {
    let ws = Ws::new("ai-criteria-gate-");
    ws.new_task("Criteria gate").ok("task new");
    write_spec(&ws);
    ws.set_config(|config| config["workflow"]["requireSpec"] = serde_json::json!(true));
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    ws
}

// --- parser -----------------------------------------------------------------

#[test]
fn the_parser_preserves_the_ticked_state() {
    assert_eq!(
        spec::acceptance_criteria(SPEC),
        vec![
            (false, "the first criterion holds".to_string()),
            (true, "the second criterion holds".to_string()),
        ]
    );
}

#[test]
fn placeholders_are_not_real_criteria() {
    let text = SPEC.replace(
        "the first criterion holds",
        "Criterion one, observable and independently testable",
    );
    assert!(spec::unticked_criteria(&text).is_empty());
}

#[test]
fn unticked_criteria_keep_their_command_number() {
    let text = SPEC.replace("- [x] the second", "- [ ] the second");
    assert_eq!(
        spec::unticked_criteria(&text),
        vec![
            (1, "the first criterion holds".to_string()),
            (2, "the second criterion holds".to_string()),
        ]
    );
}

#[test]
fn ticking_is_idempotent_and_rejects_out_of_range() {
    let (updated, changed) = spec::tick_criterion(SPEC, 1).expect("tick");
    assert!(changed);
    assert!(updated.contains("- [x] the first criterion holds"));

    let (again, changed_again) = spec::tick_criterion(&updated, 1).expect("tick again");
    assert!(!changed_again);
    assert_eq!(again, updated);

    assert!(spec::tick_criterion(SPEC, 9).is_err());
}

#[test]
fn mark_status_rewrites_only_the_frontmatter() {
    let shipped = spec::mark_status(SPEC, "shipped");
    assert!(shipped.contains("status: shipped"));
    assert!(!shipped.contains("status: draft"));
    assert!(shipped.contains("## Out of scope"));
}

// --- spec command -----------------------------------------------------------

#[test]
fn show_prints_each_box_and_the_progress() {
    let ws = prepared();
    let shown = ws.ok(&["spec", "show", "0001"]);
    assert!(
        shown.stdout.contains("[ ] the first criterion holds"),
        "{}",
        shown.stdout
    );
    assert!(
        shown.stdout.contains("[x] the second criterion holds"),
        "{}",
        shown.stdout
    );
    assert!(shown.stdout.contains("1/2 done"), "{}", shown.stdout);
}

#[test]
fn check_ticks_one_criterion_and_is_idempotent() {
    let ws = prepared();
    let ticked = ws.ok(&["spec", "check", "0001", "1"]);
    assert!(ticked.stdout.contains("Ticked 1:"), "{}", ticked.stdout);
    assert!(ticked.stdout.contains("2/2 done"), "{}", ticked.stdout);

    let shown = ws.ok(&["spec", "show", "0001"]);
    assert!(shown.stdout.contains("[x] the first criterion holds"));

    let again = ws.ok(&["spec", "check", "0001", "1"]);
    assert!(again.stdout.contains("already ticked"), "{}", again.stdout);
}

#[test]
fn an_out_of_range_number_is_a_clean_error() {
    let ws = prepared();
    let refused = ws.fails(&["spec", "check", "0001", "9"]);
    assert!(
        refused.stderr.contains("out of range"),
        "{}",
        refused.stderr
    );
    assert!(!refused.stderr.contains("panicked"), "{}", refused.stderr);
}

#[test]
fn a_task_without_a_spec_is_refused_with_the_reason() {
    let ws = Ws::new("ai-criteria-nospec-");
    ws.chief_ready();
    ws.ok(&["task", "new", "No spec", "--no-spec"]);
    let refused = ws.fails(&["spec", "show", "0001"]);
    assert!(refused.stderr.contains("--no-spec"), "{}", refused.stderr);
}

// --- review gate ------------------------------------------------------------

#[test]
fn review_refuses_and_names_the_unticked_criteria() {
    let ws = gated();
    let refused = ws.fails(&["task", "review", "0001", "--agent", "w1"]);
    assert!(refused.all().contains("unticked"), "{}", refused.all());
    assert!(
        refused.all().contains("the first criterion holds"),
        "{}",
        refused.all()
    );
    assert!(
        refused.all().contains("ai spec check 0001"),
        "{}",
        refused.all()
    );
}

#[test]
fn review_passes_once_every_real_criterion_is_ticked() {
    let ws = gated();
    ws.ok(&["spec", "check", "0001", "1"]);
    let reviewed = ws.ok(&["task", "review", "0001", "--agent", "w1"]);
    assert!(
        reviewed.stdout.contains("delivered for independent review"),
        "{}",
        reviewed.stdout
    );
}

// --- archive ----------------------------------------------------------------

#[test]
fn done_marks_the_archived_spec_shipped() {
    let ws = Ws::new("ai-criteria-archive-");
    ws.new_task("Ship it").ok("task new");
    write_spec(&ws);
    ws.ok(&["task", "claim", "0001", "--agent", "w1"]);
    ws.ok(&["spec", "check", "0001", "1"]);
    ws.ok(&["task", "review", "0001", "--agent", "w1"]);

    ws.ok(&["task", "done", "0001", "--agent", "reviewer"]);
    let archived: Vec<std::path::PathBuf> = ws.glob("specs/done", "0001-");
    assert_eq!(archived.len(), 1, "{archived:?}");
    let text = std::fs::read_to_string(&archived[0]).expect("read archived spec");
    assert!(text.contains("status: shipped"), "{text}");
}

// --- single source of truth -------------------------------------------------

#[test]
fn the_task_body_points_at_the_spec_instead_of_duplicating_it() {
    let ws = Ws::new("ai-criteria-pointer-");
    ws.new_task("Pointer task").ok("task new");
    let body = task_body(&ws);
    assert!(!body.contains("- [ ] Criterion one"), "{body}");
    assert!(body.contains("Criteria live in the spec"), "{body}");

    let shown = ws.ok(&["task", "show", "0001"]);
    assert!(
        shown
            .stdout
            .contains("Criterion one, observable and independently testable"),
        "{}",
        shown.stdout
    );
}

// --- review package ---------------------------------------------------------

fn package() -> Ws {
    let ws = Ws::new("ai-criteria-package-");
    ws.new_task("Package").ok("task new");
    write_spec(&ws);
    ws
}

#[test]
fn the_package_renders_boxes_and_progress() {
    let ws = package();
    let out = ws.ok(&["review", "0001"]).stdout;
    assert!(out.contains("[ ] the first criterion holds"), "{out}");
    assert!(out.contains("[x] the second criterion holds"), "{out}");
    assert!(out.contains("1/2 ticked"), "{out}");
    assert!(
        out.contains("[ ] every acceptance criterion is met"),
        "{out}"
    );
}

#[test]
fn the_checklist_box_reflects_the_spec() {
    let ws = package();
    ws.ok(&["spec", "check", "0001", "1"]);
    let out = ws.ok(&["review", "0001"]).stdout;
    assert!(
        out.contains("[x] every acceptance criterion is met"),
        "{out}"
    );
}

#[test]
fn json_keeps_the_text_list_and_publishes_the_state() {
    let ws = package();
    let payload = ws.ok(&["review", "0001", "--json"]).json();
    let criteria = payload["spec"]["criteria"].as_array().expect("criteria");
    assert!(criteria
        .iter()
        .any(|item| item == "the first criterion holds"));
    let states = payload["spec"]["criteria_state"].as_array().expect("state");
    assert!(
        states.iter().any(|item| item[0] == serde_json::json!(false)
            && item[1] == serde_json::json!("the first criterion holds")),
        "{states:?}"
    );
    assert_eq!(payload["spec"]["done"], serde_json::json!(1));
    assert_eq!(payload["spec"]["total"], serde_json::json!(2));
}

// --- parser helpers ---------------------------------------------------------

#[test]
fn criterion_texts_is_the_thin_wrapper_for_text_only_callers() {
    let texts: Vec<String> = spec::acceptance_criteria(SPEC)
        .into_iter()
        .map(|(_, text)| text)
        .collect();
    assert_eq!(
        texts,
        vec![
            "the first criterion holds".to_string(),
            "the second criterion holds".to_string()
        ]
    );
}

#[test]
fn progress_counts_only_real_criteria() {
    let template = ai::specs::spec::FALLBACK_SPEC.replace("{task_id}", "0001");
    let criteria = spec::acceptance_criteria(&template);
    assert_eq!(spec::criteria_progress(&criteria), (0, 0));
}

#[test]
fn resolve_spec_path_ignores_a_missing_reference() {
    let ws = Ws::new("ai-criteria-resolve-");
    let workspace = ai::core::workspace::Workspace::at(&ws.root);
    let mut meta = serde_json::Map::new();
    meta.insert("spec".into(), serde_json::json!("specs/active/nope.md"));
    assert!(spec::resolve_spec_path(&workspace, &meta).is_none());
}
