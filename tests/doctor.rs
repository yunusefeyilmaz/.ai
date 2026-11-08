//! Ported from `lib/tests/test_doctor.py` (non-interactive cases).
//!
//! Diagnostics: every finding names a safe repair, and `--fix` stays narrow.

mod support;

use serde_json::Value;
use support::Ws;

fn finding_with<'a>(payload: &'a Value, needle: &str) -> &'a Value {
    payload["check"]["findings"]
        .as_array()
        .expect("findings")
        .iter()
        .find(|finding| {
            finding["message"]
                .as_str()
                .map(|message| message.contains(needle))
                .unwrap_or(false)
        })
        .unwrap_or_else(|| panic!("no finding containing {needle:?} in {payload}"))
}

#[test]
fn missing_runtime_is_reported_and_repaired() {
    let ws = Ws::new("ai-doctor-runtime-");
    std::fs::remove_dir_all(ws.path("runtime")).expect("remove runtime");

    let before = ws.run(&["doctor", "--json"]);
    assert_eq!(before.code, 1, "{}", before.all());
    let payload = before.json();
    let finding = finding_with(&payload, "missing required path: runtime");
    assert_eq!(finding["level"], "error", "{finding}");
    assert!(
        finding["hint"]
            .as_str()
            .unwrap_or("")
            .contains("ai doctor --fix"),
        "{finding}"
    );
    assert!(
        !ws.path("runtime").exists(),
        "plain doctor must not create runtime state"
    );

    let fixed = ws.ok(&["doctor", "--fix", "--json"]).json();
    assert!(
        fixed["fixes"]
            .as_array()
            .expect("fixes")
            .iter()
            .any(|item| item.as_str().unwrap_or("").starts_with("created runtime")),
        "{fixed}"
    );
    assert_eq!(fixed["check"]["findings"], serde_json::json!([]));
    assert!(ws.path("runtime/locks").is_dir());
    assert!(ws.path("runtime/.gitignore").is_file());

    let again = ws.ok(&["doctor", "--fix", "--json"]).json();
    assert_eq!(again["fixes"], serde_json::json!([]));
}

#[test]
fn missing_config_is_repaired_without_touching_tasks() {
    let ws = Ws::new("ai-doctor-config-");
    ws.chief_ready();
    ws.ok(&["task", "new", "Keep me", "--no-spec"]);
    let task = ws.one("tasks/active", "0001");
    let bytes = std::fs::read(&task).expect("read task");

    std::fs::remove_file(ws.path("config/workspace.json")).expect("remove config");
    let before = ws.run(&["doctor", "--json"]);
    assert_eq!(before.code, 1, "{}", before.all());
    let payload = before.json();
    let matches: Vec<&Value> = payload["check"]["findings"]
        .as_array()
        .expect("findings")
        .iter()
        .filter(|finding| {
            finding["message"]
                .as_str()
                .map(|message| message.contains("config/workspace.json"))
                .unwrap_or(false)
        })
        .collect();
    assert_eq!(matches.len(), 1, "{matches:?}");
    assert_eq!(matches[0]["hint"], "ai doctor --fix");

    let fixed = ws.ok(&["doctor", "--fix", "--json"]).json();
    let fixes: Vec<&str> = fixed["fixes"]
        .as_array()
        .expect("fixes")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    assert!(
        fixes.contains(&"created config/workspace.json"),
        "{fixes:?}"
    );
    assert_eq!(fixed["check"]["findings"], serde_json::json!([]));
    assert_eq!(std::fs::read(&task).expect("read task"), bytes);
}

#[test]
fn corrupt_config_is_never_overwritten() {
    let ws = Ws::new("ai-doctor-corrupt-");
    ws.write("config/workspace.json", "{ not json\n");

    let result = ws.run(&["doctor", "--fix", "--json"]);
    assert_eq!(result.code, 1, "{}", result.all());
    assert_eq!(ws.read("config/workspace.json"), "{ not json\n");
    let payload = result.json();
    let finding = finding_with(&payload, "config/workspace.json is unreadable");
    assert!(
        !finding["hint"].as_str().unwrap_or("").is_empty(),
        "{finding}"
    );
}

#[test]
fn orphan_lock_is_reported_but_never_removed() {
    let ws = Ws::new("ai-doctor-orphan-");
    let stamp = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string();
    ws.write(
        "runtime/locks/task-9999.lock",
        &serde_json::json!({
            "resource": "task-9999",
            "agent": "ghost",
            "task": "9999",
            "started_at": stamp,
            "updated_at": stamp,
            "expires_at": stamp,
            "pid": 1,
            "host": "test",
        })
        .to_string(),
    );

    let result = ws.run(&["doctor", "--fix", "--json"]);
    assert_eq!(result.code, 1, "{}", result.all());
    assert!(
        ws.path("runtime/locks/task-9999.lock").is_file(),
        "safe repair must never delete a lock"
    );
    let payload = result.json();
    let finding = finding_with(&payload, "orphan task lock");
    assert!(
        finding["hint"]
            .as_str()
            .unwrap_or("")
            .contains("ai recover --apply"),
        "{finding}"
    );
    let fixes: Vec<&str> = payload["fixes"]
        .as_array()
        .expect("fixes")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    assert!(
        !fixes.iter().any(|item| item.contains("task-9999")),
        "{fixes:?}"
    );
}

#[test]
fn human_output_prints_the_hint() {
    let ws = Ws::new("ai-doctor-human-");
    std::fs::remove_file(ws.path("config/workspace.json")).expect("remove config");

    let result = ws.run(&["doctor"]);
    assert_eq!(result.code, 1, "{}", result.all());
    assert!(result.stdout.contains("missing"), "{}", result.stdout);
    assert!(
        result.stdout.contains("fix: ai doctor --fix"),
        "{}",
        result.stdout
    );
}

#[test]
fn doctor_flags_production_head_and_untracked_planning() {
    let ws = Ws::new("ai-doctor-invariants-");
    ws.git_init();
    ws.git(&["checkout", "-q", "master"]).ok("checkout master");
    ws.new_task("Uncommitted plan").ok("task new");

    let payload = ws.run(&["doctor", "--json"]).json();
    let production = finding_with(&payload, "production branch 'master'");
    assert!(
        production["hint"]
            .as_str()
            .unwrap_or("")
            .contains("git checkout develop"),
        "{production}"
    );
    let ledger = finding_with(
        &payload,
        "planning file(s) under tasks/specs/config are untracked",
    );
    assert!(
        ledger["hint"].as_str().unwrap_or("").contains("plan apply"),
        "{ledger}"
    );
}

#[test]
fn missing_adapters_in_a_subfolder_install_are_wired_by_fix() {
    let ws = Ws::subfolder("ai-doctor-subfolder-");
    std::fs::write(ws.host().join("package.json"), "{}\n").expect("host package.json");

    let payload = ws.run(&["doctor", "--json"]).json();
    let finding = finding_with(&payload, "missing adapter pointer");
    assert!(
        finding["hint"]
            .as_str()
            .unwrap_or("")
            .contains("ai doctor --fix"),
        "{finding}"
    );
    assert!(!ws.host().join("AGENTS.md").exists());

    let fixed = ws.ok(&["doctor", "--fix", "--json"]).json();
    assert_eq!(fixed["check"]["findings"], serde_json::json!([]));
    assert!(ws.host().join(".gitignore").is_file());
    let agents = std::fs::read_to_string(ws.host().join("AGENTS.md")).expect("agents");
    assert!(agents.contains("ai-workspace:start"), "{agents}");
    assert!(
        fixed["fixes"]
            .as_array()
            .expect("fixes")
            .iter()
            .any(|item| item.as_str().unwrap_or("").starts_with("wired AGENTS.md")),
        "{fixed}"
    );
}

#[test]
fn missing_framework_file_hints_at_the_workspace_copy() {
    let ws = Ws::subfolder("ai-doctor-framework-");
    std::fs::remove_file(ws.path("docs/architecture.md")).expect("remove doc");

    let result = ws.run(&["doctor", "--json"]);
    assert_eq!(result.code, 1, "{}", result.all());
    let payload = result.json();
    let finding = finding_with(&payload, "missing required path: docs/architecture.md");
    let hint = finding["hint"].as_str().unwrap_or("");
    assert!(hint.contains("workspace"), "{hint}");
    assert!(!hint.contains("git checkout"), "{hint}");
}
