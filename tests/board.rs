//! Ported from `lib/tests/test_board.py`.
//!
//! The read-only board view: dependency order, lease reasons and refusals.

mod support;

use support::Ws;

const HEADER: &str =
    "  ID     STATUS       OWNER        PRIORITY  CHECKPOINT   WAITING ON   TITLE\n";

#[allow(clippy::too_many_arguments)]
fn write_task(
    ws: &Ws,
    id: &str,
    title: &str,
    folder: &str,
    status: &str,
    owner: Option<&str>,
    priority: &str,
    depends_on: Option<&str>,
) {
    let text = format!(
        "---\nid: {id}\ntitle: \"{title}\"\nstatus: {status}\nowner: {}\npriority: {priority}\nspec: null\ncreated: 2026-10-29T00:00:00Z\nupdated: 2026-10-29T00:00:00Z\nlock: null\ndepends_on: {}\n---\n\n# {id} - {title}\n\n## Log\n\n",
        owner.unwrap_or("null"),
        depends_on.unwrap_or("null")
    );
    let slug = title.to_lowercase().replace(' ', "-");
    ws.write(&format!("tasks/{folder}/{id}-{slug}.md"), &text);
}

fn write_checkpoint(ws: &Ws, id: &str, minutes_ago: i64) {
    let created = (chrono::Utc::now() - chrono::Duration::minutes(minutes_ago))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string();
    ws.write(
        &format!("runtime/state/checkpoints/{id}.md"),
        &format!("---\ntask: {id}\nagent: alice\ncreated: {created}\n---\n"),
    );
}

#[test]
fn empty_board() {
    let ws = Ws::new("ai-board-empty-");
    let out = ws.ok(&["status", "--board"]).stdout;
    assert_eq!(
        out,
        "Task board\n\
         mode: lite | active: 0 | leases: 0 | checkpoints: 0\n\
         \n\
         Tasks\n\
         \x20 (no active tasks)\n\
         \n\
         Leases\n\
         \x20 (no leases)\n\
         \n\
         Refusals\n\
         \x20 (none)\n"
    );
}

#[test]
fn single_task_shows_owner_status_and_checkpoint_age() {
    let ws = Ws::new("ai-board-one-");
    write_task(
        &ws,
        "0001",
        "Board probe",
        "active",
        "in_progress",
        Some("alice"),
        "medium",
        None,
    );
    write_checkpoint(&ws, "0001", 5);

    let out = ws.ok(&["status", "--board"]).stdout;
    assert_eq!(
        out,
        format!(
            "Task board\n\
             mode: lite | active: 1 | leases: 0 | checkpoints: 1\n\
             \n\
             Tasks\n{HEADER}\
             \x20 0001   in_progress  alice        medium    5m ago       -            Board probe\n\
             \n\
             Leases\n\
             \x20 (no leases)\n\
             \n\
             Refusals\n\
             \x20 (none)\n"
        )
    );
}

#[test]
fn blocked_work_lists_dependencies_and_blocked_state() {
    let ws = Ws::new("ai-board-blocked-");
    write_task(&ws, "0001", "Done work", "done", "done", None, "low", None);
    write_task(
        &ws,
        "0002",
        "Ready work",
        "active",
        "todo",
        None,
        "low",
        Some("0001"),
    );
    write_task(
        &ws,
        "0003",
        "Waiting work",
        "active",
        "todo",
        None,
        "low",
        Some("0002"),
    );
    write_task(
        &ws,
        "0004",
        "Blocked work",
        "active",
        "blocked",
        None,
        "low",
        Some("0002"),
    );

    let out = ws.ok(&["status", "--board"]).stdout;
    assert_eq!(
        out,
        format!(
            "Task board\n\
             mode: lite | active: 3 | leases: 0 | checkpoints: 0\n\
             \n\
             Tasks\n{HEADER}\
             \x20 0002   todo         -            low       none         -            Ready work\n\
             \x20 0003   todo         -            low       none         0002         Waiting work\n\
             \x20 0004   blocked      -            low       none         blocked 0002 Blocked work\n\
             \n\
             Leases\n\
             \x20 (no leases)\n\
             \n\
             Refusals\n\
             \x20 (none)\n"
        )
    );
}

#[test]
fn dependency_order_wins_over_priority() {
    let ws = Ws::new("ai-board-order-");
    write_task(
        &ws,
        "0001",
        "Foundation",
        "active",
        "todo",
        None,
        "low",
        None,
    );
    write_task(
        &ws,
        "0002",
        "Dependent",
        "active",
        "todo",
        None,
        "high",
        Some("0001"),
    );

    let out = ws.ok(&["status", "--board"]).stdout;
    let block = out.split("Tasks\n").nth(1).expect("tasks block");
    let block = block.split("\nLeases").next().expect("before leases");
    let rows: Vec<&str> = block
        .lines()
        .filter(|line| !line.trim().is_empty())
        .skip(1)
        .collect();
    let ids: Vec<&str> = rows
        .iter()
        .map(|row| row.split_whitespace().next().unwrap_or(""))
        .collect();
    assert_eq!(ids, vec!["0001", "0002"], "{out}");
}

#[test]
fn leases_show_ttl_and_remaining_time() {
    let ws = Ws::new("ai-board-lease-");
    write_task(
        &ws,
        "0001",
        "Board probe",
        "active",
        "in_progress",
        Some("alice"),
        "low",
        None,
    );
    ws.ok(&[
        "lock",
        "acquire",
        "src/billing",
        "--agent",
        "alice",
        "--task",
        "0001",
    ]);

    let out = ws.ok(&["status", "--board"]).stdout;
    let rows: Vec<&str> = out
        .lines()
        .filter(|line| line.contains("src/billing"))
        .collect();
    assert_eq!(rows.len(), 1, "{out}");
    let fields: Vec<&str> = rows[0].split_whitespace().collect();
    assert_eq!(fields[0], "src/billing");
    assert_eq!(fields[1], "alice");
    assert_eq!(fields[2], "0001");
    assert_eq!(fields[3], "1800s");
    assert!(fields[4].ends_with('s'), "{}", rows[0]);
    assert_eq!(fields[5], "held");
}

#[test]
fn refusal_names_the_conflicting_resource() {
    let ws = Ws::new("ai-board-refusal-");
    ws.ok(&[
        "lock",
        "acquire",
        "src/billing",
        "--agent",
        "alice",
        "--task",
        "0001",
    ]);
    ws.fails(&[
        "lock",
        "acquire",
        "src/billing/writer.py",
        "--agent",
        "bob",
        "--task",
        "0002",
    ]);

    let out = ws.ok(&["status", "--board"]).stdout;
    let refusals = out.split("Refusals\n").nth(1).expect("refusals section");
    assert!(
        refusals.contains("bob -> src/billing/writer.py (conflict: src/billing held by alice)"),
        "{refusals}"
    );
    assert!(
        refusals.contains("T") && refusals.contains("Z "),
        "expected an ISO timestamp: {refusals}"
    );
}

#[test]
fn lock_status_json_details_refusals() {
    let ws = Ws::new("ai-board-refusal-json-");
    ws.ok(&[
        "lock",
        "acquire",
        "src/billing",
        "--agent",
        "alice",
        "--task",
        "0001",
    ]);
    ws.fails(&[
        "lock",
        "acquire",
        "src/billing/writer.py",
        "--agent",
        "bob",
        "--task",
        "0002",
    ]);

    let payload = ws.ok(&["lock", "status", "--json"]).json();
    let lease = payload
        .as_array()
        .expect("locks array")
        .iter()
        .find(|item| item["resource"] == "src/billing")
        .expect("billing lease");
    assert_eq!(lease["state"], "held");
    assert!(lease["remaining_seconds"].is_number(), "{lease}");
    let refusals = lease["refusals"].as_array().expect("refusals");
    assert_eq!(refusals.len(), 1, "{refusals:?}");
    assert_eq!(refusals[0]["agent"], "bob");
    assert_eq!(refusals[0]["resource"], "src/billing/writer.py");
    assert_eq!(refusals[0]["holder"], "alice");
    assert_eq!(refusals[0]["reason"], "conflict: src/billing held by alice");
}

#[test]
fn refusal_without_recorded_conflict_degrades() {
    let ws = Ws::new("ai-board-refusal-degraded-");
    ws.write(
        "runtime/state/events.jsonl",
        "{\"timestamp\":\"2026-10-29T00:00:00Z\",\"event\":\"lock_refused\",\"resource\":\"src/legacy\",\"agent\":\"bob\"}\n",
    );
    let out = ws.ok(&["status", "--board"]).stdout;
    assert!(
        out.contains("2026-10-29T00:00:00Z  bob -> src/legacy (conflict unknown)"),
        "{out}"
    );
}

#[test]
fn board_is_plain_text() {
    let ws = Ws::new("ai-board-plain-");
    write_task(
        &ws,
        "0001",
        "Board probe",
        "active",
        "in_progress",
        Some("alice"),
        "low",
        None,
    );
    ws.ok(&[
        "lock", "acquire", "src/a", "--agent", "alice", "--task", "0001",
    ]);
    let out = ws.ok(&["status", "--board"]).stdout;
    assert!(!out.contains('\u{1b}'), "{out}");
    assert!(!out.contains('\u{2500}'), "{out}");
    assert!(!out.contains('\u{2502}'), "{out}");
}

#[test]
fn board_creates_no_state() {
    let ws = Ws::new("ai-board-nostate-");
    write_task(
        &ws,
        "0001",
        "Board probe",
        "active",
        "todo",
        None,
        "low",
        None,
    );
    let before = ws.files();
    ws.ok(&["status", "--board"]);
    let after = ws.files();
    assert_eq!(before, after);
}

#[test]
fn plain_status_output_is_unchanged() {
    let ws = Ws::new("ai-board-plain-status-");
    write_task(
        &ws,
        "0001",
        "Board probe",
        "active",
        "in_progress",
        Some("alice"),
        "low",
        None,
    );

    let before = ws.ok(&["status"]).stdout;
    assert!(before.contains("Workspace  :"), "{before}");
    assert!(before.contains("Mode       : lite"), "{before}");
    assert!(before.contains("Active     : 1 task(s)"), "{before}");
    assert!(!before.contains("Task board"), "{before}");

    let payload = ws.ok(&["status", "--json"]).json();
    let mut keys: Vec<&str> = payload
        .as_object()
        .expect("object")
        .keys()
        .map(String::as_str)
        .collect();
    keys.sort();
    assert_eq!(
        keys,
        vec![
            "active",
            "artifacts",
            "checkpoints",
            "handoffs",
            "locks",
            "mode",
            "project",
            "workspace"
        ]
    );
}
