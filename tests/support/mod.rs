//! Shared fixture for the CLI tests.
//!
//! Ported from `lib/tests/_workspace.py`: every test gets a private, writable
//! workspace copied from this checkout's templates, normalised so a developer's
//! `ai setup` answers cannot change what a test gates on.

#![allow(dead_code)]

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

/// Minimal config used when the checkout has none (mirrors `default_config`).
pub const DEFAULT_CONFIG: &str = r#"{
  "version": 1,
  "name": "ai-workspace",
  "mode": "lite",
  "language": { "documents": "en", "interviews": "en" },
  "agents": ["orchestrator", "planner", "implementer", "reviewer", "qa"],
  "orchestration": { "maxParallel": 1 },
  "workflow": {
    "requireReview": true,
    "requireCheck": "strict",
    "autoContinue": false,
    "chiefOnlyTasks": false,
    "requireSpec": false,
    "playbook": "pair"
  },
  "blueprint": { "status": "missing", "path": "config/blueprint.json", "required": false },
  "team": {},
  "policy": { "unknownAgent": "allow" },
  "git": {
    "enabled": true,
    "integrationBranch": "develop",
    "productionBranch": "master",
    "branchTypes": ["feature", "fix", "chore", "docs", "refactor", "hotfix"],
    "commitTemplate": "templates/git/commit-template.txt",
    "merge": "no-ff",
    "deleteAfterMerge": true,
    "isolation": "branch"
  },
  "locks": {
    "defaultTtlSeconds": 1800,
    "staleAfterSeconds": 3600,
    "maxTtlSeconds": 7200
  },
  "handoff": { "checkpointEveryMinutes": 20, "warnAfterMinutes": 30 },
  "budget": { "contextTokens": 200000, "warnAtPercent": 70, "checkpointAtPercent": 85 },
  "artifacts": { "quarantine": "runtime/artifacts", "watch": ["tmp", "temp", "scratch"] },
  "security": { "warnTrackedSecrets": true },
  "testing": { "writeTests": false },
  "preferences": { "confirmed": false, "answered": [] },
  "checks": []
}"#;

/// Directories copied from the repo into each throwaway workspace.
const ASSET_DIRS: &[&str] = &[
    "adapters",
    "agents",
    "config",
    "docs",
    "prompts",
    "skills",
    "specs",
    "tasks",
    "templates",
];

const ASSET_FILES: &[&str] = &[
    "AGENTS.md",
    "README.md",
    "GUIDE.md",
    "LICENSE",
    "CHANGELOG.md",
    "VERSION",
];

/// Never copied: build output, the test harness itself and transient state.
const SKIP: &[&str] = &["target", ".git", "runtime", "worktrees", "src", "tests"];

pub struct Out {
    pub code: i32,
    pub stdout: String,
    pub stderr: String,
}

impl Out {
    /// Exactly what Python's assertions usually need: both streams together.
    pub fn all(&self) -> String {
        format!("{}{}", self.stderr, self.stdout)
    }

    pub fn ok(self, what: &str) -> Self {
        assert_eq!(self.code, 0, "{what} failed:\n{}", self.all());
        self
    }

    pub fn fails(self, what: &str) -> Self {
        assert_ne!(
            self.code,
            0,
            "{what} unexpectedly succeeded:\n{}",
            self.all()
        );
        self
    }

    pub fn has(&self, needle: &str) -> bool {
        self.stdout.contains(needle) || self.stderr.contains(needle)
    }

    pub fn json(&self) -> Value {
        serde_json::from_str(&self.stdout)
            .unwrap_or_else(|error| panic!("not JSON ({error}):\n{}", self.stdout))
    }
}

pub struct Ws {
    pub root: PathBuf,
    owned: bool,
    /// Directory removed on drop (the temp parent, not necessarily `root`).
    cleanup: PathBuf,
}

impl Ws {
    /// A normalised workspace: no tasks, empty checks, preferences unset,
    /// `chiefOnlyTasks`/`requireSpec` off (the gates have their own tests).
    pub fn new(prefix: &str) -> Self {
        Self::with(prefix, None, None)
    }

    /// A subfolder install: the workspace lives in `<host>/.ai`, the host
    /// project one level up. Used by `adopt` and `artifact` tests.
    pub fn subfolder(prefix: &str) -> Self {
        let host = unique_dir(prefix);
        let _ = fs::remove_dir_all(&host);
        fs::create_dir_all(&host).expect("create host");
        fs::write(host.join(".gitignore"), "").expect("host gitignore");
        let root = host.join(".ai");
        fs::create_dir_all(&root).expect("create workspace");
        copy_assets(&root);
        normalise(&root, None, None);
        Ws {
            root,
            owned: true,
            cleanup: host,
        }
    }

    pub fn with_mode(prefix: &str, mode: &str) -> Self {
        Self::with(prefix, Some(mode), None)
    }

    pub fn with(prefix: &str, mode: Option<&str>, configure: Option<&dyn Fn(&mut Value)>) -> Self {
        let root = unique_dir(prefix);
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create workspace root");
        copy_assets(&root);
        normalise(&root, mode, configure);
        Ws {
            root: root.clone(),
            owned: true,
            cleanup: root,
        }
    }

    /// Wrap an existing directory (already a workspace) without copying.
    pub fn adopt(root: impl Into<PathBuf>) -> Self {
        let root = root.into();
        Ws {
            cleanup: root.clone(),
            root,
            owned: false,
        }
    }

    /// The host project directory of a subfolder install.
    pub fn host(&self) -> PathBuf {
        self.root
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| self.root.clone())
    }

    pub fn path(&self, relative: &str) -> PathBuf {
        self.root
            .join(relative.replace('/', std::path::MAIN_SEPARATOR_STR))
    }

    pub fn read(&self, relative: &str) -> String {
        fs::read_to_string(self.path(relative))
            .unwrap_or_else(|error| panic!("cannot read {relative}: {error}"))
    }

    pub fn exists(&self, relative: &str) -> bool {
        self.path(relative).exists()
    }

    pub fn write(&self, relative: &str, text: &str) {
        let path = self.path(relative);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create parent");
        }
        fs::write(path, text).expect("write file");
    }

    pub fn remove(&self, relative: &str) {
        let _ = fs::remove_file(self.path(relative));
    }

    /// Relative paths of every file, sorted (for "must not create state" tests).
    pub fn files(&self) -> Vec<String> {
        let mut out = Vec::new();
        walk(&self.root, &self.root, &mut out);
        out.sort();
        out
    }

    pub fn glob(&self, dir: &str, prefix: &str) -> Vec<PathBuf> {
        let mut found: Vec<PathBuf> = fs::read_dir(self.path(dir))
            .map(|entries| {
                entries
                    .flatten()
                    .map(|entry| entry.path())
                    .filter(|path| {
                        path.file_name()
                            .map(|name| name.to_string_lossy().starts_with(prefix))
                            .unwrap_or(false)
                    })
                    .collect()
            })
            .unwrap_or_default();
        found.sort();
        found
    }

    /// The only `0001-*.md` in a folder, asserting there is exactly one.
    pub fn one(&self, dir: &str, id: &str) -> PathBuf {
        let found = self.glob(dir, &format!("{id}-"));
        assert_eq!(found.len(), 1, "expected one {id} file in {dir}: {found:?}");
        found.into_iter().next().expect("one")
    }

    pub fn config(&self) -> Value {
        serde_json::from_str(&self.read("config/workspace.json")).expect("config json")
    }

    pub fn set_config(&self, configure: impl Fn(&mut Value)) {
        let mut config = self.config();
        configure(&mut config);
        self.write(
            "config/workspace.json",
            &(serde_json::to_string_pretty(&config).expect("serialise") + "\n"),
        );
    }

    /// Run the binary in this workspace.
    pub fn run(&self, args: &[&str]) -> Out {
        run_in(&self.root, args)
    }

    pub fn ok(&self, args: &[&str]) -> Out {
        self.run(args).ok(&args.join(" "))
    }

    pub fn fails(&self, args: &[&str]) -> Out {
        self.run(args).fails(&args.join(" "))
    }

    /// Boilerplate every task test needs: a chief-approved path to `task new`.
    pub fn chief_ready(&self) {
        self.set_config(|config| {
            config["preferences"]["confirmed"] = serde_json::json!(true);
            config["workflow"]["chiefOnlyTasks"] = serde_json::json!(false);
        });
    }

    /// `task new` with the usual prerequisites applied.
    pub fn new_task(&self, title: &str) -> Out {
        self.chief_ready();
        self.run(&["task", "new", title])
    }

    /// A minimal chief-authored blueprint, approved by the user. Tests that only
    /// need the planning gate open use this; the blueprint's own behaviour lives
    /// in `tests/blueprint.rs`.
    pub fn blueprint(&self) {
        let analysis = serde_json::json!({
            "languages": ["Rust"],
            "architecture": "layered: domain -> application -> adapters",
            "layout": ["src/", "tests/"],
            "naming": {
                "files": "snake_case",
                "functions": "snake_case",
                "types": "PascalCase",
                "json": "snake_case"
            },
            "testing": {"framework": "cargo test"},
            "checks": [],
            "guidelines": ["one behavior per task with testable criteria"],
            "workflow": {"workers": 1},
            "git": {
                "integrationBranch": "develop",
                "productionBranch": "master",
                "merge": "no-ff",
                "isolation": "branch"
            }
        });
        self.write(
            "blueprint-analysis.json",
            &serde_json::to_string_pretty(&analysis).expect("analysis json"),
        );
        self.ok(&["blueprint", "propose", "--from", "blueprint-analysis.json"]);
        self.ok(&["blueprint", "approve", "--agent", "user"]);
    }

    pub fn git(&self, args: &[&str]) -> Out {
        self.git_in(&self.root, args)
    }

    /// Run git in an arbitrary directory (a task worktree, a host project).
    pub fn git_in(&self, cwd: &std::path::Path, args: &[&str]) -> Out {
        let mut command = Command::new("git");
        command.args(args).current_dir(cwd);
        let output = command.output().expect("run git");
        Out {
            code: output.status.code().unwrap_or(-1),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        }
    }

    /// A repository with one baseline commit on `main`, plus `develop` and
    /// `master` so Gitflow commands have something to start from.
    pub fn git_init(&self) {
        self.git(&["init", "-q", "--initial-branch=main"])
            .ok("git init");
        self.git(&["config", "user.name", "Test Runner"])
            .ok("git config name");
        self.git(&["config", "user.email", "test@example.com"])
            .ok("git config email");
        self.git(&["config", "commit.gpgsign", "false"])
            .ok("git config gpgsign");
        self.git(&["add", "-A"]).ok("git add");
        self.git(&["commit", "-qm", "test baseline"])
            .ok("git commit baseline");
        for branch in ["master", "develop"] {
            self.git(&["branch", branch]).ok("git branch");
        }
        self.git(&["checkout", "-q", "develop"])
            .ok("git checkout develop");
    }
}

impl Drop for Ws {
    fn drop(&mut self) {
        if self.owned {
            let _ = fs::remove_dir_all(&self.cleanup);
        }
    }
}

pub fn run_in(root: &Path, args: &[&str]) -> Out {
    let output = Command::new(env!("CARGO_BIN_EXE_ai"))
        .args(args)
        .current_dir(root)
        .env("AI_WORKSPACE", root)
        .env("AI_HOST", "test-host")
        .output()
        .expect("run ai");
    Out {
        code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    }
}

/// Run the binary in `cwd` without `AI_WORKSPACE`, exercising path discovery.
pub fn discover_in(cwd: &Path, args: &[&str]) -> Out {
    let output = Command::new(env!("CARGO_BIN_EXE_ai"))
        .args(args)
        .current_dir(cwd)
        .env_remove("AI_WORKSPACE")
        .env("AI_HOST", "test-host")
        .output()
        .expect("run ai");
    Out {
        code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    }
}

/// `--help` of the binary itself, from any directory.
pub fn help() -> Out {
    let output = Command::new(env!("CARGO_BIN_EXE_ai"))
        .arg("--help")
        .output()
        .expect("run ai --help");
    Out {
        code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    }
}

fn nanos() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0)
}

/// A directory name unique across threads: the clock alone can repeat when
/// tests start in parallel, and two tests sharing a workspace is a false
/// failure waiting to happen.
fn unique_dir(prefix: &str) -> PathBuf {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    std::env::temp_dir().join(format!(
        "{prefix}{}-{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst),
        nanos()
    ))
}

fn copy_assets(destination: &Path) {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for name in ASSET_FILES {
        let source = repo.join(name);
        if source.is_file() {
            let _ = fs::copy(&source, destination.join(name));
        }
    }
    // `runtime/` itself is transient state, but its `.gitignore` is what keeps
    // that state out of the commit; without it every fixture looks dirty.
    let runtime_ignore = repo.join("runtime").join(".gitignore");
    if runtime_ignore.is_file() {
        let _ = fs::create_dir_all(destination.join("runtime"));
        let _ = fs::copy(
            &runtime_ignore,
            destination.join("runtime").join(".gitignore"),
        );
    }
    for name in ASSET_DIRS {
        let source = repo.join(name);
        if source.is_dir() {
            copy_tree(&source, &destination.join(name));
        }
    }
}

fn copy_tree(source: &Path, destination: &Path) {
    fs::create_dir_all(destination).expect("create asset dir");
    let entries = match fs::read_dir(source) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if SKIP.contains(&name.as_str()) {
            continue;
        }
        let from = entry.path();
        let to = destination.join(&name);
        if from.is_dir() {
            copy_tree(&from, &to);
        } else if fs::copy(&from, &to).is_err() {
            // A concurrently-locked file is not worth failing a fixture over.
        }
    }
}

fn normalise(root: &Path, mode: Option<&str>, configure: Option<&dyn Fn(&mut Value)>) {
    for folder in ["tasks/active", "tasks/done", "specs/active", "specs/done"] {
        let path = root.join(folder.replace('/', std::path::MAIN_SEPARATOR_STR));
        let _ = fs::remove_dir_all(&path);
        let _ = fs::create_dir_all(&path);
    }
    for folder in [
        "runtime/locks",
        "runtime/state",
        "runtime/artifacts",
        "runtime/logs",
    ] {
        let _ = fs::remove_dir_all(root.join(folder.replace('/', std::path::MAIN_SEPARATOR_STR)));
        // The workspace ships an empty runtime tree; recreate it so `doctor`
        // does not report a missing required path.
        let path = root.join(folder.replace('/', std::path::MAIN_SEPARATOR_STR));
        let _ = fs::create_dir_all(&path);
        let _ = fs::write(path.join(".gitkeep"), "");
    }
    let _ = fs::write(root.join("tasks").join("BOARD.md"), "# Task board\n");

    let config_path = root.join("config").join("workspace.json");
    let text = match fs::read_to_string(&config_path) {
        Ok(text) => text,
        Err(_) => DEFAULT_CONFIG.to_string(),
    };
    let mut config: Value = serde_json::from_str(&text).expect("config json");
    if let Some(mode) = mode {
        config["mode"] = Value::String(mode.to_string());
    }
    config["checks"] = serde_json::json!([]);
    // Pin the mode-driven gate: a developer's `ai setup --set checks=yes` must
    // not make every fixture demand checks it does not have.
    config["workflow"]["requireCheck"] = Value::String("strict".to_string());
    config["preferences"]["confirmed"] = Value::Bool(false);
    config["preferences"]["answered"] = serde_json::json!([]);
    config["workflow"]["chiefOnlyTasks"] = Value::Bool(false);
    config["workflow"]["requireSpec"] = Value::Bool(false);
    if let Some(configure) = configure {
        configure(&mut config);
    }
    let _ = mode;
    fs::create_dir_all(root.join("config")).expect("config dir");
    fs::write(
        &config_path,
        serde_json::to_string_pretty(&config).expect("serialise") + "\n",
    )
    .expect("write config");
}

fn walk(base: &Path, current: &Path, out: &mut Vec<String>) {
    let entries = match fs::read_dir(current) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            walk(base, &path, out);
        } else if let Ok(relative) = path.strip_prefix(base) {
            out.push(relative.to_string_lossy().replace('\\', "/"));
        }
    }
}
