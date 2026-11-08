//! `ai` - local, cross-platform CLI for the .ai engineering workspace.
//!
//! Rust port of the Python entry point. The on-disk contract (task/spec
//! front matter, JSON leases, event ledger, Markdown board) is unchanged, so
//! both implementations can operate on the same workspace.

use clap::Parser;

use ai::cli::{Cli, Command};
use ai::cmd;
use ai::core::workspace::Workspace;

fn main() {
    let cli = Cli::parse();
    let command = match cli.command {
        Some(command) => command,
        None => {
            use clap::CommandFactory;
            let mut cmd = Cli::command();
            let _ = cmd.print_help();
            return;
        }
    };

    let ws = match Workspace::discover() {
        Ok(ws) => ws,
        Err(error) => {
            eprintln!("error: {error}");
            std::process::exit(1);
        }
    };

    let code = match run(&ws, command) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    };
    std::process::exit(code);
}

fn run(ws: &Workspace, command: Command) -> ai::core::error::Result<i32> {
    match command {
        Command::Now(args) => cmd::now::now(ws, &args),
        Command::Context(args) => cmd::context::context(ws, &args),
        Command::Brief(args) => cmd::brief::run(ws, &args),
        Command::Start(args) => cmd::start::run(ws, &args),
        Command::Setup(args) => cmd::setup::run(ws, &args),
        Command::Blueprint(args) => cmd::blueprint::run(ws, &args),
        Command::Init(args) => cmd::init::run(ws, &args),
        Command::Doctor(args) => cmd::doctor::doctor(ws, &args),
        Command::Check(args) => cmd::doctor::check(ws, &args),
        Command::Status(args) => cmd::status::status(ws, &args),
        Command::Metrics(args) => cmd::metrics::run(ws, &args),
        Command::Capabilities(args) => cmd::capabilities::run(ws, &args),
        Command::Version => cmd::version::run(),
        Command::Plan(args) => cmd::plan::run(ws, &args),
        Command::Task(args) => cmd::task::run(ws, &args),
        Command::Lock(args) => cmd::lock::run(ws, &args),
        Command::Checkpoint(args) => cmd::checkpoint::checkpoint(ws, &args),
        Command::Handoff(args) => cmd::checkpoint::handoff(ws, &args),
        Command::Resume(args) => cmd::checkpoint::resume(ws, &args),
        Command::Git(args) => cmd::git::run(ws, &args),
        Command::History(args) => cmd::history::run(ws, &args),
        Command::Decision(args) => cmd::decision::run(ws, &args),
        Command::Spec(args) => cmd::spec::run(ws, &args),
        Command::Artifact(args) => cmd::artifact::run(ws, &args),
        Command::Clean(args) => cmd::clean::run(ws, &args),
        Command::Review(args) => cmd::review::run(ws, &args),
        Command::Reset(args) => cmd::reset::run(ws, &args),
        Command::Recover(args) => cmd::recover::run(ws, &args),
        Command::Adopt(args) => cmd::adopt::run(ws, &args),
        Command::Worktree(args) => cmd::worktree::run(ws, &args),
        Command::Ui(args) => cmd::ui::run(ws, &args),
    }
}
