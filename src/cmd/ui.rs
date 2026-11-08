//! `ai ui`: the read-only terminal dashboard.

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::UiArgs;

pub fn run(ws: &Workspace, args: &UiArgs) -> Result<i32> {
    crate::ui::dashboard::render(ws, args)
}
