//! Ported from `lib/tests/test_platform.py` (the parts without Python-only
//! console encoding) plus Windows launcher coverage.

mod support;

use ai::tasks::store;
use support::Ws;

#[test]
fn crlf_task_file_parses_and_round_trips_to_lf() {
    let ws = Ws::new("ai-platform-crlf-");
    let path = ws.path("0001-windows.md");
    std::fs::write(
        &path,
        b"---\r\nid: 0001\r\ntitle: Windows\r\nstatus: todo\r\n---\r\nbody line\r\n",
    )
    .expect("write crlf task");

    let (meta, body, problems) = store::parse_task(&path).expect("parse crlf");
    assert!(problems.is_empty(), "{problems:?}");
    assert_eq!(meta["id"], "0001");
    assert_eq!(meta["title"], "Windows");
    assert_eq!(body.trim(), "body line");

    store::write_task(&path, &meta, &body).expect("rewrite task");
    let bytes = std::fs::read(&path).expect("read task");
    assert!(
        !bytes.windows(2).any(|window| window == b"\r\n"),
        "the CLI always writes LF"
    );
}

#[test]
fn a_missing_working_directory_reports_git_as_unavailable() {
    let missing = std::env::temp_dir().join("ai-platform-no-such-dir-xyz");
    let _ = std::fs::remove_dir_all(&missing);
    let output = ai::git::repo::run_git(&missing, &["status"]);
    assert_eq!(output.code, 127, "{}", output.stderr);
    assert!(
        output.stderr.contains("git is not available"),
        "{}",
        output.stderr
    );
}

#[test]
fn atomic_writes_leave_no_temp_debris() {
    let ws = Ws::new("ai-platform-atomic-");
    let path = ws.path("state.json");
    std::fs::write(&path, "{\"ok\": true}\n").expect("seed file");

    ai::core::fsio::write_json_atomic(&path, &serde_json::json!({"retried": true}))
        .expect("atomic write");
    let text = std::fs::read_to_string(&path).expect("read");
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&text).expect("json"),
        serde_json::json!({"retried": true})
    );

    let leftovers: Vec<String> = std::fs::read_dir(&ws.root)
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| entry.file_name().to_string_lossy().to_string())
                .filter(|name| name.starts_with(".tmp-"))
                .collect()
        })
        .unwrap_or_default();
    assert!(leftovers.is_empty(), "{leftovers:?}");
}

#[test]
fn task_show_survives_non_ascii_content() {
    let ws = Ws::new("ai-platform-unicode-");
    ws.new_task("Unicode arrow").ok("task new");
    let path = ws.one("tasks/active", "0001");
    let text = std::fs::read_to_string(&path).expect("read task");
    let text = text.replacen("## Intent", "## Intent\n\nThen \u{2192} done.", 1);
    std::fs::write(&path, text).expect("write task");

    let out = ws.ok(&["task", "show", "0001"]);
    assert!(!out.stderr.contains("panicked"), "{}", out.stderr);
    assert!(out.stdout.contains("\u{2192} done"), "{}", out.stdout);
}

#[cfg(windows)]
#[test]
fn windows_launcher_propagates_the_exit_code() {
    let repo = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let launcher = repo.join("ai.cmd");
    if !launcher.is_file() {
        return;
    }
    let failed = std::process::Command::new("cmd")
        .arg("/c")
        .arg(&launcher)
        .arg("task")
        .arg("show")
        .arg("999999")
        .current_dir(&repo)
        .output()
        .expect("run launcher");
    assert_eq!(failed.status.code(), Some(1));

    let ok = std::process::Command::new("cmd")
        .arg("/c")
        .arg(&launcher)
        .arg("version")
        .current_dir(&repo)
        .output()
        .expect("run launcher");
    assert_eq!(ok.status.code(), Some(0));
    let text = String::from_utf8_lossy(&ok.stdout);
    assert!(text.contains("ai workspace"), "{text}");
}
