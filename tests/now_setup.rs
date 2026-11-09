//! Ported from `lib/tests/test_now_json.py` and `test_setup_gate.py`.
//!
//! `ai now --json` tells a harness whether to act or to ask the user; `ai
//! setup --defaults` must not be usable as a fake human approval.

mod support;

use support::Ws;

fn prepare_now(ws: &Ws) {
    ws.set_config(|config| {
        config["preferences"] = serde_json::json!({"confirmed": false, "answered": []});
        config["workflow"]["chiefOnlyTasks"] = serde_json::json!(false);
        config["workflow"]["requireSpec"] = serde_json::json!(false);
        config["workflow"]["requireCheck"] = serde_json::json!(false);
        config["workflow"]["autoContinue"] = serde_json::json!(false);
    });
}

fn now_payload(ws: &Ws, extra: &[&str]) -> serde_json::Value {
    let mut args = vec!["now", "--json"];
    args.extend_from_slice(extra);
    ws.ok(&args).json()
}

// --- now --json -------------------------------------------------------------

#[test]
fn schema_two_publishes_the_four_contract_keys() {
    let ws = Ws::new("ai-now-json-keys-");
    prepare_now(&ws);
    let payload = now_payload(&ws, &["--agent", "alice"]);
    assert_eq!(payload["schema"], serde_json::json!(2));
    for key in ["needs_human", "question", "next_args", "blocker"] {
        assert!(payload.get(key).is_some(), "missing {key}: {payload}");
    }
    assert!(payload["needs_human"].is_boolean(), "{payload}");
    assert!(payload["next_args"].is_array(), "{payload}");
    assert!(payload["recommended"].is_object(), "{payload}");
}

#[test]
fn asking_the_setup_questions_needs_the_human() {
    let ws = Ws::new("ai-now-json-setup-");
    prepare_now(&ws);
    let payload = now_payload(&ws, &["--agent", "alice"]);
    assert_eq!(payload["needs_human"], serde_json::json!(true));

    let question = payload["question"].as_str().unwrap_or("").to_lowercase();
    assert!(
        question.contains("process") || question.contains("workflow"),
        "{question}"
    );
    assert_eq!(payload["next_args"], serde_json::json!(["setup"]));
    assert!(!payload["blocker"].is_null(), "{payload}");
}

#[test]
fn a_ready_task_is_actionable_with_the_callers_agent_name() {
    let ws = Ws::new("ai-now-json-ready-");
    prepare_now(&ws);
    ws.set_config(|config| {
        config["preferences"] =
            serde_json::json!({"confirmed": true, "answered": ["review", "checks", "git", "tests"]});
    });
    ws.chief_ready();
    ws.ok(&["task", "new", "Now json scenario", "--no-spec"]);

    let payload = now_payload(&ws, &["--agent", "alice"]);
    assert_eq!(payload["needs_human"], serde_json::json!(false));
    assert!(payload["question"].is_null(), "{payload}");
    assert!(payload["blocker"].is_null(), "{payload}");
    assert_eq!(
        payload["next_args"],
        serde_json::json!(["task", "next", "--agent", "alice"])
    );
    assert!(!serde_json::to_string(&payload["next_args"])
        .unwrap()
        .contains("<n>"));
}

#[test]
fn next_args_matches_the_printed_next_line() {
    let ws = Ws::new("ai-now-json-match-");
    prepare_now(&ws);
    ws.set_config(|config| config["preferences"]["confirmed"] = serde_json::json!(true));
    ws.new_task("Now json scenario").ok("task new");
    ws.ok(&["task", "claim", "0001", "--agent", "alice"]);

    let payload = now_payload(&ws, &["--agent", "alice"]);
    let next_line = ws
        .ok(&["now", "--agent", "alice"])
        .stdout
        .lines()
        .find(|line| line.starts_with("NEXT"))
        .expect("NEXT line")
        .to_string();
    let printed: Vec<&str> = next_line["NEXT".len()..].split_whitespace().collect();
    assert_eq!(printed.first().copied(), Some("ai"), "{next_line}");
    let expected: Vec<String> = payload["next_args"]
        .as_array()
        .expect("array")
        .iter()
        .map(|item| item.as_str().unwrap_or("").to_string())
        .collect();
    assert_eq!(&printed[1..], expected.as_slice(), "{next_line}");
    assert!(!expected.join(" ").contains("<n>"));
}

#[test]
fn the_text_output_is_unchanged_in_shape() {
    let ws = Ws::new("ai-now-json-text-");
    prepare_now(&ws);
    ws.set_config(|config| config["preferences"]["confirmed"] = serde_json::json!(true));
    ws.new_task("Now json scenario").ok("task new");
    let out = ws.ok(&["now", "--agent", "alice"]).stdout;
    let lines: Vec<&str> = out.trim().lines().collect();
    assert!(lines[0].starts_with("ai "), "{}", lines[0]);
    let labels: Vec<&str> = lines
        .iter()
        .filter_map(|line| line.split_whitespace().next())
        .collect();
    assert!(labels.contains(&"NEXT"), "{out}");
    assert!(labels.contains(&"WHY"), "{out}");
    assert!(!out.contains("schema"), "{out}");
    assert!(lines.last().unwrap().starts_with("More:"), "{out}");
}

// --- setup gate -------------------------------------------------------------

#[test]
fn defaults_without_yes_is_refused() {
    let ws = Ws::new("ai-setup-defaults-");
    let out = ws.fails(&["setup", "--defaults"]);
    assert!(out.stderr.contains("--yes"), "{}", out.stderr);
    assert_eq!(
        ws.config()["preferences"]["confirmed"],
        serde_json::json!(false)
    );
}

#[test]
fn defaults_with_yes_still_needs_a_terminal() {
    let ws = Ws::new("ai-setup-defaults-yes-");
    let out = ws.fails(&["setup", "--defaults", "--yes"]);
    assert!(
        out.stderr.contains("interactive terminal"),
        "{}",
        out.stderr
    );
    assert_eq!(
        ws.config()["preferences"]["confirmed"],
        serde_json::json!(false)
    );
}

#[test]
fn explicit_answers_still_work_without_a_terminal() {
    let ws = Ws::new("ai-setup-explicit-");
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=no",
        "git=no",
        "tests=yes",
    ]);
    assert_eq!(
        ws.config()["preferences"]["confirmed"],
        serde_json::json!(true)
    );
}

#[test]
fn unconfirmed_preferences_block_task_creation() {
    let ws = Ws::new("ai-setup-chief-");
    ws.set_config(|config| {
        config["workflow"]["chiefOnlyTasks"] = serde_json::json!(true);
        config["preferences"]["confirmed"] = serde_json::json!(false);
    });
    let refused = ws.fails(&["task", "new", "Should wait", "--role", "chief"]);
    assert!(
        refused.stderr.contains("Ask the user"),
        "{}",
        refused.stderr
    );
    assert!(ws.glob("tasks/active", "").is_empty());
}

#[test]
fn stored_answers_unblock_creation() {
    let ws = Ws::new("ai-setup-chief-answers-");
    ws.set_config(|config| config["workflow"]["chiefOnlyTasks"] = serde_json::json!(true));
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=no",
        "git=no",
        "tests=yes",
    ]);
    // Creation also needs the user-approved architecture proposal.
    let refused = ws.fails(&["task", "new", "Needs a blueprint", "--role", "chief"]);
    assert!(
        refused.all().contains("architecture proposal exists"),
        "{}",
        refused.all()
    );
    ws.blueprint();
    ws.ok(&["task", "new", "Now allowed", "--role", "chief"]);
}

#[test]
fn adding_a_check_does_not_erase_the_other_answers() {
    let ws = Ws::new("ai-setup-partial-");
    ws.ok(&[
        "setup",
        "--set",
        "review=yes",
        "checks=yes",
        "git=yes",
        "tests=yes",
    ]);
    // A later, partial call only adds a check; it must merge, not rewrite the
    // questionnaire.
    ws.ok(&[
        "setup",
        "--set",
        "checks=yes",
        "--check",
        "typecheck=echo ok",
    ]);

    let config = ws.config();
    assert_eq!(config["testing"]["writeTests"], serde_json::json!(true));
    assert_eq!(config["workflow"]["requireReview"], serde_json::json!(true));
    let answered: Vec<&str> = config["preferences"]["answered"]
        .as_array()
        .expect("answered array")
        .iter()
        .filter_map(serde_json::Value::as_str)
        .collect();
    assert!(answered.contains(&"tests"), "{answered:?}");
    assert_eq!(config["checks"][0]["name"], serde_json::json!("typecheck"));
}

#[test]
fn check_timeout_is_stored_on_the_named_check() {
    let ws = Ws::new("ai-setup-check-timeout-");
    ws.ok(&[
        "setup",
        "--check",
        "unit=echo ok",
        "--check-timeout",
        "unit=300",
    ]);
    assert_eq!(
        ws.config()["checks"][0]["timeoutSeconds"],
        serde_json::json!(300)
    );

    let unknown = ws.fails(&["setup", "--check-timeout", "nope=5"]);
    assert!(
        unknown.all().contains("no configured check named 'nope'"),
        "{}",
        unknown.all()
    );
    let invalid = ws.fails(&["setup", "--check-timeout", "unit=soon"]);
    assert!(
        invalid
            .all()
            .contains("--check-timeout expects NAME=SECONDS"),
        "{}",
        invalid.all()
    );
}
