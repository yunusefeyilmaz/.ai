//! Ported from `lib/tests/test_task_ids.py`.
//!
//! Task ids scale past 9999: one constant drives every check and hint.

mod support;

use ai::core::fsio::{normalize_id, MAX_TASK_ID_DIGITS};
use support::Ws;

#[test]
fn five_and_nine_digit_ids_are_canonical() {
    assert_eq!(normalize_id("10000").unwrap(), "10000");
    assert_eq!(normalize_id("T-10000").unwrap(), "10000");
    assert_eq!(normalize_id("task-123456789").unwrap(), "123456789");
    assert_eq!(normalize_id("7").unwrap(), "0007");
}

#[test]
fn ten_digits_name_the_single_limit() {
    assert_eq!(MAX_TASK_ID_DIGITS, 9);
    let error = normalize_id("1234567890").expect_err("ten digits must be refused");
    assert!(
        error
            .to_string()
            .contains(&format!("{MAX_TASK_ID_DIGITS} digits")),
        "{error}"
    );
}

#[test]
fn leading_zeros_do_not_bypass_the_limit() {
    let padded = format!("{}1234567890", "0".repeat(20));
    assert!(normalize_id(&padded).is_err());
}

#[test]
fn task_lookup_accepts_a_five_digit_id() {
    let ws = Ws::new("ai-ids-lookup-");
    let text = "---\nid: 10000\ntitle: Big ledger\nstatus: todo\n---\nbody\n";
    ws.write("tasks/active/10000-big-ledger.md", text);
    let workspace = ai::core::workspace::Workspace::at(&ws.root);
    let found = ai::tasks::store::find_task(&workspace, "10000").expect("find 10000");
    assert!(
        found.ends_with("10000-big-ledger.md"),
        "{}",
        found.display()
    );
}

#[test]
fn spec_lookup_by_five_digit_id() {
    let ws = Ws::new("ai-ids-spec-");
    ws.write("specs/active/10000-big-ledger.md", "# 10000\n");
    let workspace = ai::core::workspace::Workspace::at(&ws.root);
    let mut meta = serde_json::Map::new();
    meta.insert("spec".into(), serde_json::json!("10000"));
    let resolved = ai::specs::spec::resolve_spec_path(&workspace, &meta).expect("resolve spec");
    assert!(
        resolved.ends_with("10000-big-ledger.md"),
        "{}",
        resolved.display()
    );
}
