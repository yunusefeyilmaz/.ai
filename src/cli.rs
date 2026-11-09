//! The clap surface: every command, argument and flag the binary accepts.
//!
//! Kept separate from `main` so `capabilities` can derive the contract from
//! the real parser and so tests can inspect it without spawning a process.

use clap::{Args, Parser, Subcommand};

#[derive(Parser, Debug)]
#[command(
    name = "ai",
    version = concat!("ai workspace ", env!("CARGO_PKG_VERSION")),
    about = "Local, cross-platform CLI for the .ai engineering workspace."
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Option<Command>,
}

#[derive(Subcommand, Debug)]
pub enum Command {
    /// Compact state plus the single next required command.
    Now(NowArgs),
    /// Project memory: open work, shipped work, decisions, recent activity.
    Context(ContextArgs),
    /// Print a paste-ready brief for an external chat AI.
    Brief(BriefArgs),
    /// One-command first run.
    Start(StartArgs),
    /// Chief: ask the user which workflow features to use.
    Setup(SetupArgs),
    /// Chief: propose or approve the project architecture and conventions.
    Blueprint(BlueprintArgs),
    /// Create the workspace state in a fresh checkout.
    Init(InitArgs),
    /// Check workspace health; --fix repairs safe issues.
    Doctor(DoctorArgs),
    /// Run the single verification contract.
    Check(CheckArgs),
    /// Show tasks, locks, checkpoints, handoffs and artifacts.
    Status(StatusArgs),
    /// Summarize local workflow events.
    Metrics(MetricsArgs),
    /// Print the machine-readable CLI contract.
    Capabilities(CapabilitiesArgs),
    /// Print the workspace version.
    Version,
    /// Chief: many linked tasks from one JSON file.
    Plan(PlanArgs),
    /// Manage local tasks.
    Task(TaskArgs),
    /// Manage advisory resource locks.
    Lock(LockArgs),
    /// Save resumable context for a task.
    Checkpoint(CheckpointArgs),
    /// Checkpoint and mark a task for another agent.
    Handoff(CheckpointArgs),
    /// Print a compact resume brief with drift.
    Resume(ResumeArgs),
    /// Gitflow branches, commits and guarded merges.
    Git(GitArgs),
    /// Who moved a task, when, why and on which proof.
    History(HistoryArgs),
    /// Record and list architecture decisions (ADR).
    Decision(DecisionArgs),
    /// Tick and show a task's acceptance criteria.
    Spec(SpecArgs),
    /// Quarantine AI scratch files.
    Artifact(ArtifactArgs),
    /// Remove stale locks and logs.
    Clean(CleanArgs),
    /// Print the read-only review package for one task.
    Review(ReviewArgs),
    /// Reset .ai operational state (interactive operator action).
    Reset(ResetArgs),
    /// Detect or repair inconsistent workspace state.
    Recover(RecoverArgs),
    /// Wire the workspace into root AI tool configs.
    Adopt(AdoptArgs),
    /// List or prune the per-task Git worktrees.
    Worktree(WorktreeArgs),
    /// Live terminal dashboard (read-only).
    Ui(UiArgs),
}

#[derive(Args, Debug, Clone, Default)]
pub struct NowArgs {
    #[arg(long)]
    pub agent: Option<String>,
    #[arg(long)]
    pub role: Option<String>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct ContextArgs {
    #[arg(long)]
    pub agent: Option<String>,
    #[arg(long, default_value_t = 5)]
    pub limit: usize,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct BriefArgs {
    pub task_id: Option<String>,
    #[arg(long = "max-chars", default_value_t = 0)]
    pub max_chars: usize,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct StartArgs {
    #[arg(long)]
    pub agent: Option<String>,
    #[arg(long)]
    pub json: bool,
    #[arg(long = "no-demo")]
    pub no_demo: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct SetupArgs {
    #[arg(long = "set", num_args = 1.., value_delimiter = ' ')]
    pub set: Vec<String>,
    #[arg(long = "check")]
    pub checks: Vec<String>,
    #[arg(long = "check-timeout")]
    pub check_timeout: Vec<String>,
    #[arg(long)]
    pub defaults: bool,
    #[arg(long)]
    pub yes: bool,
    #[arg(long)]
    pub agent: Option<String>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct BlueprintArgs {
    #[command(subcommand)]
    pub action: Option<BlueprintAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum BlueprintAction {
    /// Scan the machine and record the proposal (the chief may supply one).
    Propose {
        /// Analysis JSON authored by the chief (`-` reads stdin).
        #[arg(long)]
        from: Option<String>,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// Print the proposal (human summary or JSON).
    Show {
        #[arg(long)]
        json: bool,
    },
    /// Change the proposal before approval.
    Revise {
        #[arg(long = "set", num_args = 1.., value_delimiter = ' ')]
        set: Vec<String>,
        #[arg(long)]
        json: bool,
    },
    /// Apply the proposal to config/workspace.json (the user's approval).
    Approve {
        #[arg(long = "set", num_args = 1.., value_delimiter = ' ')]
        set: Vec<String>,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        json: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct InitArgs {
    #[arg(long)]
    pub wire: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct DoctorArgs {
    #[arg(long)]
    pub strict: bool,
    #[arg(long)]
    pub fix: bool,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct CheckArgs {
    #[arg(long)]
    pub fast: bool,
    #[arg(long = "no-commands")]
    pub no_commands: bool,
    #[arg(long = "allow-empty")]
    pub allow_empty: bool,
    #[arg(long)]
    pub strict: bool,
    #[arg(long)]
    pub task: Option<String>,
    #[arg(long)]
    pub agent: Option<String>,
    /// Reuse green evidence recorded on this exact HEAD instead of running the
    /// project checks again (the expensive part of review and finish).
    #[arg(long = "reuse-evidence")]
    pub reuse_evidence: bool,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct StatusArgs {
    #[arg(long)]
    pub json: bool,
    #[arg(long)]
    pub board: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct MetricsArgs {
    #[arg(long)]
    pub since: Option<String>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct CapabilitiesArgs {
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct PlanArgs {
    #[command(subcommand)]
    pub action: Option<PlanAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum PlanAction {
    /// Create the tasks from a JSON plan document.
    Apply {
        #[arg(default_value = "-")]
        file: String,
        #[arg(long)]
        role: Option<String>,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long = "approved-by")]
        approved_by: Option<String>,
        #[arg(long = "dry-run")]
        dry_run: bool,
        #[arg(long)]
        json: bool,
    },
    /// Print a skeleton plan document.
    Example,
}

#[derive(Args, Debug, Clone, Default)]
pub struct TaskArgs {
    #[command(subcommand)]
    pub action: Option<TaskAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum TaskAction {
    New {
        title: String,
        #[arg(long, default_value = "medium")]
        priority: String,
        #[arg(long)]
        spec: Option<String>,
        #[arg(long = "no-spec")]
        no_spec: bool,
        #[arg(long = "depends-on")]
        depends_on: Option<String>,
        #[arg(long = "allow")]
        allow: Vec<String>,
        #[arg(long = "forbid")]
        forbid: Vec<String>,
        #[arg(long = "lock")]
        lock: Vec<String>,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        role: Option<String>,
    },
    List {
        #[arg(long)]
        all: bool,
        #[arg(long)]
        json: bool,
    },
    Show {
        task_id: String,
        #[arg(long)]
        json: bool,
    },
    Link {
        task_id: String,
        #[arg(long)]
        issue: Option<String>,
        #[arg(long)]
        pr: Option<String>,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        json: bool,
    },
    Ready {
        #[arg(long)]
        json: bool,
    },
    Next {
        #[arg(long)]
        agent: String,
        #[arg(long)]
        review: bool,
        #[arg(long)]
        json: bool,
    },
    Claim {
        task_id: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        force: bool,
    },
    Release {
        task_id: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        force: bool,
    },
    Review {
        task_id: String,
        #[arg(long)]
        agent: String,
    },
    #[command(name = "request-changes")]
    RequestChanges {
        task_id: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        reason: String,
    },
    Done {
        task_id: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        force: bool,
    },
    Reopen {
        task_id: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        reason: Option<String>,
        #[arg(long)]
        status: Option<String>,
    },
    Discard {
        task_id: String,
    },
    Block {
        task_id: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        reason: String,
    },
    Unblock {
        task_id: String,
        #[arg(long)]
        agent: String,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct LockArgs {
    #[command(subcommand)]
    pub action: Option<LockAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum LockAction {
    Acquire {
        #[arg(required = true, num_args = 1..)]
        resource: Vec<String>,
        #[arg(long, default_value = "unknown")]
        agent: String,
        #[arg(long)]
        task: Option<String>,
        #[arg(long)]
        ttl: Option<u64>,
        /// Seconds to keep retrying while another agent holds a lock.
        #[arg(long, default_value_t = 0)]
        wait: u64,
        #[arg(long)]
        force: bool,
    },
    Release {
        resource: String,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        force: bool,
    },
    Heartbeat {
        resource: String,
        #[arg(long)]
        agent: Option<String>,
    },
    Status {
        #[arg(long)]
        json: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct CheckpointArgs {
    pub task_id: Option<String>,
    #[arg(long)]
    pub agent: String,
    #[arg(long, default_value = "checkpoint")]
    pub reason: String,
    #[arg(long)]
    pub percent: Option<i64>,
    #[arg(long)]
    pub objective: Option<String>,
    #[arg(long)]
    pub status: Option<String>,
    #[arg(long)]
    pub done: Option<String>,
    #[arg(long = "in-progress")]
    pub in_progress: Option<String>,
    #[arg(long = "next")]
    pub next: Option<String>,
    #[arg(long)]
    pub decisions: Option<String>,
    #[arg(long = "do-not")]
    pub do_not: Option<String>,
    #[arg(long)]
    pub questions: Option<String>,
    #[arg(long)]
    pub files: Option<String>,
    #[arg(long = "files-text")]
    pub files_text: Option<String>,
    #[arg(long)]
    pub verification: Option<String>,
    #[arg(long)]
    pub force: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct ResumeArgs {
    pub task_id: Option<String>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct GitArgs {
    #[command(subcommand)]
    pub action: Option<GitAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum GitAction {
    Setup {
        #[arg(long)]
        json: bool,
        #[arg(long)]
        yes: bool,
    },
    Start {
        #[arg(long)]
        task: String,
        #[arg(long)]
        agent: String,
        #[arg(long = "type", default_value = "feature")]
        branch_type: String,
        #[arg(long)]
        base: Option<String>,
        #[arg(long)]
        force: bool,
        #[arg(long)]
        carry: bool,
        #[arg(long)]
        json: bool,
    },
    Commit {
        #[arg(long)]
        task: String,
        #[arg(long)]
        agent: String,
        #[arg(long = "type", default_value = "feat")]
        commit_type: String,
        #[arg(long)]
        scope: Option<String>,
        #[arg(long)]
        message: String,
        #[arg(long, default_value = "")]
        body: String,
        #[arg(long = "allow-empty")]
        allow_empty: bool,
        #[arg(long)]
        verify: bool,
        #[arg(long = "no-verify")]
        no_verify: bool,
        #[arg(long)]
        force: bool,
        #[arg(long)]
        json: bool,
        #[arg(long)]
        ci: Option<String>,
    },
    Finish {
        #[arg(long)]
        task: String,
        #[arg(long)]
        agent: String,
        #[arg(long)]
        force: bool,
        #[arg(long)]
        json: bool,
    },
    Begin {
        #[arg(long)]
        agent: String,
        #[arg(long)]
        task: Option<String>,
        #[arg(long, default_value_t = 300)]
        ttl: u64,
    },
    End {
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        force: bool,
    },
    Verify {
        #[arg(long)]
        strict: bool,
        #[arg(long)]
        task: Option<String>,
        #[arg(long)]
        json: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct HistoryArgs {
    pub task_id: String,
    #[arg(long)]
    pub json: bool,
    #[arg(long)]
    pub evidence: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct DecisionArgs {
    #[command(subcommand)]
    pub action: Option<DecisionAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum DecisionAction {
    New {
        title: String,
        #[arg(long)]
        agent: Option<String>,
        #[arg(long)]
        task: Option<String>,
    },
    List {
        #[arg(long)]
        json: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct SpecArgs {
    #[command(subcommand)]
    pub action: Option<SpecAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum SpecAction {
    Show {
        task_id: String,
        #[arg(long)]
        json: bool,
    },
    Check {
        task_id: String,
        n: usize,
    },
    /// Record the user's approval of a spec (strict mode requires it).
    Approve {
        task_id: String,
        #[arg(long, default_value = "user")]
        agent: String,
        #[arg(long)]
        json: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct ArtifactArgs {
    #[command(subcommand)]
    pub action: Option<ArtifactAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum ArtifactAction {
    Put {
        path: String,
        #[arg(long)]
        reason: Option<String>,
        #[arg(long, default_value = "unknown")]
        agent: String,
    },
    List {
        #[arg(long)]
        json: bool,
    },
    Clean {
        #[arg(long)]
        all: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct CleanArgs {
    #[arg(long = "stale-locks")]
    pub stale_locks: bool,
    #[arg(long)]
    pub logs: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct ReviewArgs {
    pub task_id: String,
    #[arg(long)]
    pub stat: bool,
    #[arg(long = "max-lines")]
    pub max_lines: Option<usize>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct ResetArgs {
    #[arg(long)]
    pub hard: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct RecoverArgs {
    #[arg(long)]
    pub apply: bool,
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct AdoptArgs {
    #[arg(long)]
    pub check: bool,
    #[arg(long = "print")]
    pub print: bool,
    #[arg(long)]
    pub force: bool,
    #[arg(long)]
    pub ci: bool,
}

#[derive(Args, Debug, Clone, Default)]
pub struct WorktreeArgs {
    #[command(subcommand)]
    pub action: Option<WorktreeAction>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum WorktreeAction {
    List {
        #[arg(long)]
        json: bool,
    },
    Path {
        task_id: String,
    },
    Prune {
        #[arg(long)]
        force: bool,
    },
}

#[derive(Args, Debug, Clone, Default)]
pub struct UiArgs {
    #[arg(long)]
    pub once: bool,
    #[arg(long)]
    pub json: bool,
    #[arg(long)]
    pub demo: bool,
    #[arg(long)]
    pub theme: Option<String>,
}
