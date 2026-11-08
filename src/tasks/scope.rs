//! Which paths a task may touch.
//!
//! Front matter keys (comma-separated globs, `**` crosses directories):
//!
//! ```text
//! scope_allowed:   src/auth/**, tests/auth/**
//! scope_forbidden: src/payment/**
//! ```
//!
//! Ledger files (tasks and specs) are exempt in callers: coordination state is
//! not product code.

use regex::Regex;
use serde_json::Value;

use crate::core::fsio::normalize_rel_path;

pub fn split_globs(raw: Option<&Value>) -> Vec<String> {
    let raw = match raw {
        Some(Value::Null) | None => return Vec::new(),
        Some(Value::Array(items)) => {
            return items
                .iter()
                .filter_map(Value::as_str)
                .flat_map(|item| item.split(',').map(str::to_string).collect::<Vec<_>>())
                .map(|item| normalize_rel_path(item.trim()))
                .filter(|item| !item.is_empty() && item != "null")
                .collect()
        }
        Some(Value::String(text)) => text.clone(),
        Some(other) => other.to_string(),
    };
    raw.split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty() && *item != "null")
        .map(normalize_rel_path)
        .collect()
}

pub fn join_globs(values: Option<&[String]>) -> Option<String> {
    let mut flat: Vec<String> = Vec::new();
    for value in values.unwrap_or(&[]) {
        flat.extend(split_globs(Some(&Value::String(value.clone()))));
    }
    if flat.is_empty() {
        None
    } else {
        Some(flat.join(", "))
    }
}

fn glob_regex(pattern: &str) -> Regex {
    let mut out = String::from("^");
    let chars: Vec<char> = pattern.chars().collect();
    let mut index = 0;
    while index < chars.len() {
        let ch = chars[index];
        if chars[index..].starts_with(&['*', '*', '/']) {
            out.push_str("(?:.*/)?");
            index += 3;
        } else if chars[index..].starts_with(&['*', '*']) {
            out.push_str(".*");
            index += 2;
        } else if ch == '*' {
            out.push_str("[^/]*");
            index += 1;
        } else if ch == '?' {
            out.push_str("[^/]");
            index += 1;
        } else {
            out.push_str(&regex::escape(&ch.to_string()));
            index += 1;
        }
    }
    out.push('$');
    Regex::new(&out).unwrap_or_else(|_| Regex::new("$^").expect("static regex"))
}

/// Does `pattern` (maybe a glob or a directory) cover `path`?
pub fn matches(pattern: &str, path: &str) -> bool {
    let mut pattern = pattern.replace('\\', "/");
    let path = normalize_rel_path(path);
    if path == ".." || path.starts_with("../") {
        return false;
    }
    if pattern.ends_with('/') {
        pattern = pattern.trim_end_matches('/').to_string();
    }
    if !pattern.chars().any(|ch| matches!(ch, '*' | '?' | '[')) {
        let pattern = normalize_rel_path(&pattern);
        return path == pattern || path.starts_with(&(pattern + "/"));
    }
    glob_regex(&normalize_rel_path(&pattern)).is_match(&path)
}

/// Python `fnmatch.fnmatch`-style match used by resource overlap checks.
pub fn fnmatch(value: &str, pattern: &str) -> bool {
    let mut regex = String::from("^");
    let mut chars = pattern.chars().peekable();
    while let Some(ch) = chars.next() {
        match ch {
            '*' => regex.push_str(".*"),
            '?' => regex.push('.'),
            '[' => {
                regex.push('[');
                let mut closed = false;
                for next in chars.by_ref() {
                    if next == ']' {
                        regex.push(']');
                        closed = true;
                        break;
                    }
                    regex.push(next);
                }
                if !closed {
                    regex.push(']');
                }
            }
            other => regex.push_str(&regex::escape(&other.to_string())),
        }
    }
    regex.push('$');
    Regex::new(&regex)
        .map(|compiled| compiled.is_match(value))
        .unwrap_or(false)
}

pub fn violations(meta: &serde_json::Map<String, Value>, paths: &[String]) -> Vec<String> {
    let allowed = split_globs(meta.get("scope_allowed"));
    let forbidden = split_globs(meta.get("scope_forbidden"));
    if allowed.is_empty() && forbidden.is_empty() {
        return Vec::new();
    }
    let mut found = Vec::new();
    for path in paths {
        if let Some(hit) = forbidden.iter().find(|glob| matches(glob, path)) {
            found.push(format!("{path}: forbidden by scope `{hit}`"));
        } else if !allowed.is_empty() && !allowed.iter().any(|glob| matches(glob, path)) {
            found.push(format!(
                "{path}: outside allowed scope ({})",
                allowed.join(", ")
            ));
        }
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn directory_patterns_cover_children() {
        assert!(matches("src/api", "src/api/routes.rs"));
        assert!(matches("src/**", "src/api/routes.rs"));
        assert!(matches("src/**/test_*.rs", "src/a/b/test_x.rs"));
        assert!(!matches("src/payment/**", "src/auth/login.rs"));
        assert!(!matches("src/**", "../secret"));
    }
}
