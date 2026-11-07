//! Ported from `lib/tests/test_frontmatter_lists.py`.
//!
//! Flow-style front matter lists must survive parsing instead of becoming one
//! string.

mod support;

use serde_json::Value;
use support::Ws;

fn parse(ws: &Ws, frontmatter: &str) -> serde_json::Map<String, Value> {
    ws.write(
        "0001-probe.md",
        &format!("---\n{frontmatter}\n---\n\nbody\n"),
    );
    ai::tasks::store::parse_task(&ws.path("0001-probe.md"))
        .expect("parse task")
        .0
}

fn problems(ws: &Ws, name: &str, text: &str) -> Vec<String> {
    ws.write(name, text);
    ai::tasks::store::parse_task(&ws.path(name))
        .expect("parse task")
        .2
}

#[test]
fn flow_dependencies_become_real_dependencies() {
    let ws = Ws::new("ai-fm-deps-");
    let meta = parse(
        &ws,
        "id: 0001\ntitle: One\nstatus: todo\ndepends_on: [0001, 0002]",
    );
    assert_eq!(meta["depends_on"], "0001, 0002");
    assert_eq!(
        ai::tasks::store::board_dependencies(&meta),
        vec!["0001".to_string(), "0002".to_string()]
    );
}

#[test]
fn quoted_items_spacing_and_single_quotes() {
    let ws = Ws::new("ai-fm-quotes-");
    let meta = parse(
        &ws,
        "id: 0001\ntitle: One\nstatus: todo\nlocks: [ \"lib/a.py\",  'lib/b.py' ,lib/c.py ]",
    );
    assert_eq!(meta["locks"], "lib/a.py, lib/b.py, lib/c.py");
}

#[test]
fn empty_flow_list_means_no_value() {
    let ws = Ws::new("ai-fm-empty-");
    let meta = parse(&ws, "id: 0001\ntitle: One\nstatus: todo\ndepends_on: []");
    assert_eq!(meta["depends_on"], Value::Null);
    assert!(ai::tasks::store::board_dependencies(&meta).is_empty());
}

#[test]
fn unterminated_flow_list_is_reported_not_swallowed() {
    let ws = Ws::new("ai-fm-unterminated-");
    let found = problems(
        &ws,
        "0001-broken.md",
        "---\nid: 0001\ntitle: One\nstatus: todo\ndepends_on: [0001, 0002\n---\n",
    );
    assert!(
        found
            .iter()
            .any(|item| item.contains("unterminated flow list")),
        "{found:?}"
    );
    let meta = ai::tasks::store::parse_task(&ws.path("0001-broken.md"))
        .expect("parse")
        .0;
    assert_eq!(meta["depends_on"], Value::Null);
}

#[test]
fn trailing_text_after_a_flow_list_is_reported() {
    let ws = Ws::new("ai-fm-trailing-");
    let found = problems(
        &ws,
        "0001-trailing.md",
        "---\nid: 0001\ntitle: One\nstatus: todo\ndepends_on: [0001] oops\n---\n",
    );
    assert!(
        found
            .iter()
            .any(|item| item.contains("unexpected text after flow list")),
        "{found:?}"
    );
}

#[test]
fn written_lists_round_trip_as_comma_separated() {
    let ws = Ws::new("ai-fm-round-");
    let mut meta = serde_json::Map::new();
    meta.insert("id".into(), Value::String("0001".into()));
    meta.insert("title".into(), Value::String("One".into()));
    meta.insert("status".into(), Value::String("todo".into()));
    meta.insert("depends_on".into(), serde_json::json!(["0002", "0003"]));
    meta.insert("locks".into(), serde_json::json!(["lib/a.py", "lib/b.py"]));

    let path = ws.path("0001-round.md");
    ai::tasks::store::write_task(&path, &meta, "body\n").expect("write task");
    let text = std::fs::read_to_string(&path).expect("read task");
    assert!(text.contains("depends_on: 0002, 0003"), "{text}");
    assert!(!text.contains('['), "{text}");

    let (parsed, _, _) = ai::tasks::store::parse_task(&path).expect("parse");
    assert_eq!(
        ai::tasks::store::board_dependencies(&parsed),
        vec!["0002".to_string(), "0003".to_string()]
    );
    assert_eq!(parsed["locks"], "lib/a.py, lib/b.py");
}

#[test]
fn scalar_values_keep_their_behavior() {
    let ws = Ws::new("ai-fm-scalars-");
    let meta = parse(
        &ws,
        "id: 0001\ntitle: \"Two, three\"\nstatus: todo\nscope_allowed: src/[ab].py",
    );
    assert_eq!(meta["title"], "Two, three");
    assert_eq!(meta["scope_allowed"], "src/[ab].py");
}
