//! `ai start` and `ai init`: prepare the workspace and name the next steps.

use crate::config::adopt;
use crate::config::settings as config;
use crate::core::error::Result;
use crate::core::workspace::{relative_to, Workspace};
use crate::runtime::dirs;
use crate::tasks::board;
use crate::tasks::store::{self};

use crate::InitArgs;
pub fn run(ws: &Workspace, args: &InitArgs) -> Result<i32> {
    dirs::ensure_dirs(ws)?;
    if !ws.config_path().exists() {
        config::save(ws, &config::default_config(ws))?;
    }
    dirs::ensure_placeholders(ws)?;
    println!("Workspace ready: {}", ws.root.display());
    println!("Project root:    {}", ws.project.display());
    if args.wire {
        if ws.workspace_shape() != "subfolder" {
            println!(
                "Template install detected: the workspace is the project root; no wiring needed."
            );
        } else {
            for (path, state) in adopt::adopt_root(ws, false, false)? {
                println!("{:<10} {path}", state.to_uppercase());
            }
            let (state, _) = adopt::adopt_gitignore(ws, false)?;
            println!("{:<10} .gitignore", state.to_uppercase());
        }
    }
    let _ = board::write_board(ws, &store::load_tasks(ws));
    let _ = relative_to(&ws.project, &ws.root);
    Ok(0)
}
