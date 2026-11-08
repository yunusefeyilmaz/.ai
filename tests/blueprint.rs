//! The blueprint is AI-authored and open-ended: the CLI proves facts, the chief
//! proposes any stack, the user approves. No language allowlist anywhere.

mod support;

use support::Ws;

fn project(ws: &Ws) {
    ws.set_config(|config| {
        config["preferences"]["confirmed"] = serde_json::json!(true);
        config["preferences"]["answered"] = serde_json::json!(["review", "checks", "git", "tests"]);
        config["workflow"]["chiefOnlyTasks"] = serde_json::json!(true);
        config["git"]["enabled"] = serde_json::json!(false);
    });
    ws.write("Cargo.toml", "[package]\nname = \"demo\"\n");
    ws.write("src/main.rs", "fn main() {}\n");
    ws.write(
        "plan.json",
        r#"{"tasks":[{"key":"api","title":"Build the API","priority":"high","acceptance":["It responds"]}]}"#,
    );
}

fn analysis(ws: &Ws) -> &'static str {
    ws.write(
        "analysis.json",
        r#"{
          "languages": ["Zig", {"name": "Gleam", "why": "worker services"}],
          "architecture": "hexagonal: domain inside, adapters outside",
          "layout": ["src/domain/", "src/adapters/", "tests/"],
          "naming": {"files": "snake_case", "functions": "snake_case", "types": "PascalCase"},
          "testing": {"framework": "zig build test"},
          "checks": [{"name": "unit", "command": "zig build test"}],
          "guidelines": ["one behavior per task", "no new dependency without approval"],
          "conventions": {"release": "trunk", "comments": "explain why"},
          "workflow": {"mode": "strict", "playbook": "solo", "workers": 2},
          "git": {"integrationBranch": "main", "productionBranch": "release", "isolation": "worktree"}
        }"#,
    );
    "analysis.json"
}

#[test]
fn a_bare_propose_is_only_mechanical_facts() {
    let ws = Ws::new("ai-blueprint-facts-");
    project(&ws);

    let draft = ws.ok(&["blueprint", "propose", "--json"]).json();
    assert_eq!(draft["status"], serde_json::json!("pending"));
    assert_eq!(draft["authored"], serde_json::json!(false));
    // Facts, not a language guess.
    assert_eq!(
        draft["detected"]["os"],
        serde_json::json!(std::env::consts::OS)
    );
    assert!(draft["detected"]["topLevel"]
        .as_array()
        .expect("top level")
        .iter()
        .any(|item| item == "Cargo.toml"));
    assert_eq!(draft["proposal"]["languages"], serde_json::json!([]));

    // An empty draft cannot be approved, so the AI has to do the analysis.
    let refused = ws.fails(&["blueprint", "approve", "--agent", "user"]);
    assert!(
        refused.all().contains("still an empty draft"),
        "{}",
        refused.all()
    );

    let planned = ws.fails(&["plan", "apply", "plan.json", "--role", "chief"]);
    assert!(
        planned.all().contains("architecture proposal is waiting"),
        "{}",
        planned.all()
    );
}

#[test]
fn the_chief_may_propose_any_stack_and_extra_conventions() {
    let ws = Ws::new("ai-blueprint-author-");
    project(&ws);
    let file = analysis(&ws);

    let proposed = ws
        .ok(&[
            "blueprint",
            "propose",
            "--from",
            file,
            "--agent",
            "chief",
            "--json",
        ])
        .json();
    assert_eq!(proposed["status"], serde_json::json!("pending"));
    assert_eq!(proposed["authored"], serde_json::json!(true));
    assert_eq!(
        proposed["proposal"]["languages"][1]["name"],
        serde_json::json!("Gleam")
    );
    assert_eq!(
        proposed["proposal"]["conventions"]["release"],
        serde_json::json!("trunk")
    );

    let approved = ws
        .ok(&["blueprint", "approve", "--agent", "user", "--json"])
        .json();
    assert_eq!(approved["status"], serde_json::json!("approved"));

    let config = ws.config();
    assert_eq!(config["mode"], serde_json::json!("strict"));
    assert_eq!(config["workflow"]["playbook"], serde_json::json!("solo"));
    assert_eq!(config["orchestration"]["maxParallel"], serde_json::json!(2));
    assert_eq!(
        config["git"]["integrationBranch"],
        serde_json::json!("main")
    );
    assert_eq!(config["languages"][0], serde_json::json!("Zig"));
    assert_eq!(config["conventions"]["release"], serde_json::json!("trunk"));
    assert_eq!(config["checks"][0]["name"], serde_json::json!("unit"));
    // The whole proposal is preserved for agents and later versions.
    assert_eq!(
        config["blueprint"]["approved"]["architecture"],
        serde_json::json!("hexagonal: domain inside, adapters outside")
    );

    let brief = ws.ok(&["brief"]).stdout;
    assert!(brief.contains("Zig"), "{brief}");
    assert!(brief.contains("trunk"), "{brief}");
    assert!(brief.contains("Playbook:  solo"), "{brief}");
}

#[test]
fn revise_accepts_any_path_and_rejects_broken_structure() {
    let ws = Ws::new("ai-blueprint-revise-");
    project(&ws);
    let file = analysis(&ws);
    ws.ok(&["blueprint", "propose", "--from", file]);

    ws.ok(&[
        "blueprint",
        "revise",
        "--set",
        "naming.files=PascalCase",
        "conventions.release=gitflow",
        "languages=[\"Zig\",\"Odin\"]",
    ]);
    let document = ws.ok(&["blueprint", "show", "--json"]).json();
    assert_eq!(document["status"], serde_json::json!("pending"));
    assert_eq!(
        document["proposal"]["naming"]["files"],
        serde_json::json!("PascalCase")
    );
    assert_eq!(
        document["proposal"]["conventions"]["release"],
        serde_json::json!("gitflow")
    );
    assert_eq!(
        document["proposal"]["languages"][1],
        serde_json::json!("Odin")
    );
    // Not applied until approval.
    assert_eq!(ws.config()["mode"], serde_json::json!("lite"));

    let invalid = ws.fails(&["blueprint", "revise", "--set", "workflow.mode=turbo"]);
    assert!(invalid.all().contains("lite, strict"), "{}", invalid.all());
    let broken = ws.fails(&["blueprint", "revise", "--set", "languages=Zig"]);
    assert!(
        broken.all().contains("must be an array"),
        "{}",
        broken.all()
    );
}

#[test]
fn a_malformed_analysis_is_rejected_before_it_is_stored() {
    let ws = Ws::new("ai-blueprint-invalid-");
    project(&ws);
    ws.write("bad.json", r#"{"checks": [{"name": "no command"}]}"#);
    let refused = ws.fails(&["blueprint", "propose", "--from", "bad.json"]);
    assert!(
        refused.all().contains("needs a non-empty `command`"),
        "{}",
        refused.all()
    );
    assert!(!ws.path("config/blueprint.json").exists());

    ws.write("not-json.json", "{ nope");
    let refused = ws.fails(&["blueprint", "propose", "--from", "not-json.json"]);
    assert!(
        refused.all().contains("not valid JSON"),
        "{}",
        refused.all()
    );
}

#[test]
fn propose_refuses_to_overwrite_an_approved_blueprint() {
    let ws = Ws::new("ai-blueprint-once-");
    project(&ws);
    let file = analysis(&ws);
    ws.ok(&["blueprint", "propose", "--from", file]);
    ws.ok(&["blueprint", "approve", "--agent", "user"]);

    let refused = ws.fails(&["blueprint", "propose", "--from", file]);
    assert!(
        refused.all().contains("already approved"),
        "{}",
        refused.all()
    );
}

#[test]
fn editing_after_approval_updates_config_on_the_next_approval() {
    let ws = Ws::new("ai-blueprint-reapprove-");
    project(&ws);
    let file = analysis(&ws);
    ws.ok(&["blueprint", "propose", "--from", file]);
    ws.ok(&["blueprint", "approve", "--agent", "user"]);

    ws.ok(&["blueprint", "revise", "--set", "workflow.playbook=team"]);
    assert_eq!(
        ws.config()["workflow"]["playbook"],
        serde_json::json!("solo")
    );
    ws.ok(&["blueprint", "approve", "--agent", "user"]);
    assert_eq!(
        ws.config()["workflow"]["playbook"],
        serde_json::json!("team")
    );
}

#[test]
fn doctor_reports_a_pending_proposal() {
    let ws = Ws::new("ai-blueprint-doctor-");
    project(&ws);
    let file = analysis(&ws);
    ws.ok(&["blueprint", "propose", "--from", file]);

    let payload = ws.run(&["doctor", "--json"]).json();
    let findings = payload["check"]["findings"].as_array().expect("findings");
    assert!(
        findings.iter().any(|finding| finding["message"]
            .as_str()
            .unwrap_or("")
            .contains("waiting for the user")),
        "{payload}"
    );
}
