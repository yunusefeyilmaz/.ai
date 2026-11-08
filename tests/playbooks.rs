//! Playbooks: who implements and who reviews (solo, pair, team).
//!
//! `solo` deliberately lets one agent deliver and approve; `pair` and `team`
//! keep the producer/reviewer separation.

mod support;

use support::Ws;

fn prepared(ws: &Ws, playbook: &str) {
    ws.set_config(|config| {
        config["workflow"]["playbook"] = serde_json::json!(playbook);
        config["workflow"]["requireReview"] = serde_json::json!(true);
        config["workflow"]["requireCheck"] = serde_json::json!(false);
        config["git"]["enabled"] = serde_json::json!(false);
    });
    ws.new_task("Playbook work").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);
}

#[test]
fn setup_stores_the_playbook_and_mode() {
    let ws = Ws::new("ai-playbook-setup-");
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=no",
        "git=no",
        "tests=no",
        "mode=strict",
        "playbook=solo",
    ]);
    let config = ws.config();
    assert_eq!(config["mode"], serde_json::json!("strict"));
    assert_eq!(config["workflow"]["playbook"], serde_json::json!("solo"));

    let refused = ws.fails(&["setup", "--set", "playbook=anarchy"]);
    assert!(
        refused.all().contains("solo, pair, team"),
        "{}",
        refused.all()
    );
}

#[test]
fn solo_lets_one_agent_deliver_and_approve() {
    let ws = Ws::new("ai-playbook-solo-");
    prepared(&ws, "solo");
    ws.ok(&["task", "done", "0001", "--agent", "alice"]);
    let archived = std::fs::read_to_string(ws.one("tasks/done", "0001")).expect("archived");
    assert!(archived.contains("reviewed_by: alice"), "{archived}");
}

#[test]
fn pair_refuses_self_approval_but_accepts_a_reviewer() {
    let ws = Ws::new("ai-playbook-pair-");
    prepared(&ws, "pair");

    let refused = ws.fails(&["task", "done", "0001", "--agent", "alice"]);
    assert!(
        refused.all().contains("producer never approves"),
        "{}",
        refused.all()
    );
    ws.ok(&["task", "done", "0001", "--agent", "bob"]);
    let archived = std::fs::read_to_string(ws.one("tasks/done", "0001")).expect("archived");
    assert!(archived.contains("reviewed_by: bob"), "{archived}");
}

#[test]
fn solo_now_recommends_shipping_its_own_work() {
    let ws = Ws::new("ai-playbook-solo-now-");
    prepared(&ws, "solo");

    let payload = ws.ok(&["now", "--json", "--agent", "alice"]).json();
    assert_eq!(
        payload["recommended"]["cmd"],
        serde_json::json!("ai task done 0001 --agent alice")
    );
    assert!(
        payload["recommended"]["why"]
            .as_str()
            .unwrap_or("")
            .contains("solo playbook"),
        "{payload}"
    );
}

#[test]
fn solo_bypasses_a_team_role_table_for_its_own_delivery() {
    let ws = Ws::new("ai-playbook-solo-roles-");
    ws.set_config(|config| {
        config["workflow"]["playbook"] = serde_json::json!("solo");
        config["workflow"]["requireCheck"] = serde_json::json!(false);
        config["git"]["enabled"] = serde_json::json!(false);
        config["team"] = serde_json::json!({
            "alice": {"roles": ["implementer"]}
        });
        config["policy"]["unknownAgent"] = serde_json::json!("deny");
    });
    ws.new_task("Solo with roles").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);
    ws.ok(&["task", "review", "0001", "--agent", "alice"]);

    // An unlisted agent is still refused by the table.
    let other = ws.fails(&["task", "done", "0001", "--agent", "bob"]);
    assert!(other.all().contains("denied"), "{}", other.all());

    // `task.done` is a reviewer capability, but solo may approve its own work.
    ws.ok(&["task", "done", "0001", "--agent", "alice"]);
}

#[test]
fn now_reports_the_playbook() {
    let ws = Ws::new("ai-playbook-now-");
    ws.set_config(|config| {
        config["workflow"]["playbook"] = serde_json::json!("team");
        config["preferences"]["confirmed"] = serde_json::json!(true);
    });
    let payload = ws.ok(&["now", "--json", "--agent", "alice"]).json();
    assert_eq!(payload["playbook"], serde_json::json!("team"));
}
