//! One small error type for the whole CLI.
//!
//! Commands return `Result<()>`; `main` prints `AiError::Msg` as `error: ...`
//! and lets the process exit with 1, matching the Python CLI's contract.

use std::fmt;
use std::io;

pub type Result<T> = std::result::Result<T, AiError>;

#[derive(Debug)]
pub enum AiError {
    /// A user-facing refusal or environment problem.
    Msg(String),
    Io(io::Error),
    Json(serde_json::Error),
}

impl AiError {
    pub fn msg(message: impl Into<String>) -> Self {
        AiError::Msg(message.into())
    }
}

impl fmt::Display for AiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AiError::Msg(m) => write!(f, "{m}"),
            AiError::Io(e) => write!(f, "{e}"),
            AiError::Json(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for AiError {}

impl From<io::Error> for AiError {
    fn from(value: io::Error) -> Self {
        AiError::Io(value)
    }
}

impl From<serde_json::Error> for AiError {
    fn from(value: serde_json::Error) -> Self {
        AiError::Json(value)
    }
}

/// `Err(AiError::Msg(...))` without the boilerplate.
pub fn fail<T>(message: impl Into<String>) -> Result<T> {
    Err(AiError::msg(message))
}
