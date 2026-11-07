//! `ai` - the .ai engineering workspace CLI as a library plus a thin binary.
//!
//! The modules mirror the Python `lib/` package so the two implementations can
//! be read side by side; `main.rs` only parses arguments and dispatches.

#![allow(dead_code)] // ported helpers kept for API parity with the Python modules

pub mod cli;
pub mod cmd;
pub mod config;
pub mod core;
pub mod decisions;
pub mod git;
pub mod runtime;
pub mod specs;
pub mod tasks;
pub mod ui;

pub use cli::*;
