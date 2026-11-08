//! Specs: acceptance criteria, the "no spec, no code" gate and archiving.
//!
//! One parser is shared by the claim gate, `ai doctor`, `ai spec` and `ai
//! review`, so a reviewer is never shown a different list - or a different tick
//! - than the one the gate judged.

use std::fs;
use std::path::{Path, PathBuf};

use regex::Regex;
use serde_json::Value;

use crate::core::error::Result;
use crate::core::fsio::{normalize_id, read_text, write_text_atomic};
use crate::core::workspace::Workspace;

pub const FALLBACK_SPEC: &str = r#"---
status: draft
task: {task_id}
approved_by: null
approved_on: null
---

# {title}

## Intent

<!-- The problem in one paragraph. What changes for the user? Why now? -->

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] Criterion one, observable and independently testable
- [ ] Criterion two
- [ ] Existing behavior X still holds

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
"#;

const PLACEHOLDER_CRITERIA: &[&str] = &[
    "criterion one",
    "criterion two",
    "existing behavior x still holds",
    "observable criterion one",
    "observable criterion two",
];

pub fn spec_from_template(
    ws: &Workspace,
    title: &str,
    task_id: &str,
    intent: Option<&str>,
    acceptance: Option<&[String]>,
) -> String {
    let text =
        fs::read_to_string(ws.specs_template()).unwrap_or_else(|_| FALLBACK_SPEC.to_string());
    let text = text.replacen("task: null", &format!("task: {task_id}"), 1);
    let text = text.replacen("# <title>", &format!("# {title}"), 1);
    let mut text = text;
    if let Some(intent) = intent.filter(|value| !value.trim().is_empty()) {
        let re = Regex::new(r"(?s)(## Intent\n\n)<!--.*?-->").expect("static regex");
        text = re
            .replacen(&text, 1, |caps: &regex::Captures| {
                format!("{}{}", &caps[1], intent)
            })
            .to_string();
    }
    if let Some(items) = acceptance {
        if !items.is_empty() {
            let block = items
                .iter()
                .map(|item| format!("- [ ] {item}"))
                .collect::<Vec<_>>()
                .join("\n");
            let re =
                Regex::new(r"(?s)(## Acceptance criteria\n\n).*?(\n## )").expect("static regex");
            text = re
                .replacen(&text, 1, |caps: &regex::Captures| {
                    format!("{}{}\n{}", &caps[1], block, &caps[2])
                })
                .to_string();
        }
    }
    text
}

fn criteria_section(text: &str) -> Option<regex::Captures<'_>> {
    Regex::new(r"(?s)## Acceptance criteria\n(.*?)(?:\n## |\z)")
        .expect("static regex")
        .captures(text)
}

/// The `- [ ]`/`- [x]` bullets under "## Acceptance criteria", in order.
pub fn acceptance_criteria(text: &str) -> Vec<(bool, String)> {
    let section = match criteria_section(text) {
        Some(section) => section,
        None => return Vec::new(),
    };
    let criterion = Regex::new(r"^\s*- \[([ xX])\]\s*(.*)$").expect("static regex");
    let mut criteria = Vec::new();
    for line in section[1].lines() {
        if let Some(caps) = criterion.captures(line) {
            criteria.push((
                caps[1].eq_ignore_ascii_case("x"),
                caps[2].trim().to_string(),
            ));
        }
    }
    criteria
}

pub fn real_criteria(criteria: &[(bool, String)]) -> Vec<(bool, String)> {
    criteria
        .iter()
        .filter(|(_, text)| {
            !text.is_empty()
                && !PLACEHOLDER_CRITERIA
                    .iter()
                    .any(|placeholder| text.to_lowercase().starts_with(placeholder))
        })
        .cloned()
        .collect()
}

pub fn criteria_progress(criteria: &[(bool, String)]) -> (usize, usize) {
    let real = real_criteria(criteria);
    (real.iter().filter(|(done, _)| *done).count(), real.len())
}

/// Real criteria still unticked as `(1-based position, text)`. The position
/// counts every criterion in the section, placeholders included.
pub fn unticked_criteria(text: &str) -> Vec<(usize, String)> {
    acceptance_criteria(text)
        .into_iter()
        .enumerate()
        .filter_map(|(index, (done, criterion))| {
            if done || criterion.is_empty() {
                return None;
            }
            if PLACEHOLDER_CRITERIA
                .iter()
                .any(|placeholder| criterion.to_lowercase().starts_with(placeholder))
            {
                return None;
            }
            Some((index + 1, criterion))
        })
        .collect()
}

/// Tick criterion `number` (1-based); returns `(new_text, changed)`.
pub fn tick_criterion(text: &str, number: usize) -> Result<(String, bool)> {
    let criteria = acceptance_criteria(text);
    if number < 1 || number > criteria.len() {
        return crate::core::error::fail(format!(
            "there are {} acceptance criteria; {number} is out of range",
            criteria.len()
        ));
    }
    let section = match criteria_section(text) {
        Some(section) => section,
        None => {
            return crate::core::error::fail("the spec has no '## Acceptance criteria' section")
        }
    };
    let body = &section[1];
    let mut rebuilt = String::new();
    let mut position = 0;
    let mut changed = false;
    let criterion = Regex::new(r"^(\s*)- \[ \]").expect("static regex");
    let rendered_criterion = Regex::new(r"^\s*- \[([ xX])\]\s*(.*)$").expect("static regex");
    for line in body.split_inclusive('\n') {
        let content = line.trim_end_matches(['\r', '\n']);
        let ending = &line[content.len()..];
        let rendered = rendered_criterion.is_match(content);
        if rendered {
            position += 1;
            if position == number {
                if criteria[number - 1].0 {
                    rebuilt.push_str(line);
                    continue;
                }
                let replaced = criterion.replace(content, "${1}- [x]").to_string();
                rebuilt.push_str(&replaced);
                rebuilt.push_str(ending);
                changed = true;
                continue;
            }
        }
        rebuilt.push_str(line);
    }
    let start = section.get(1).map(|m| m.start()).unwrap_or(0);
    let end = section.get(1).map(|m| m.end()).unwrap_or(0);
    let mut output = String::new();
    output.push_str(&text[..start]);
    output.push_str(&rebuilt);
    output.push_str(&text[end..]);
    Ok((output, changed))
}

/// Set the frontmatter `status:` line, leaving the rest of the spec untouched.
pub fn mark_status(text: &str, status: &str) -> String {
    let front = Regex::new(r"(?s)\A---\n(.*?)\n---\n").expect("static regex");
    let caps = match front.captures(text) {
        Some(caps) => caps,
        None => return text.to_string(),
    };
    let frontmatter = &caps[1];
    let start = caps.get(1).expect("group").start();
    let end = caps.get(1).expect("group").end();
    let updated = if Regex::new(r"(?m)^status:")
        .expect("static regex")
        .is_match(frontmatter)
    {
        Regex::new(r"(?m)^status:.*$")
            .expect("static regex")
            .replacen(frontmatter, 1, format!("status: {status}"))
            .to_string()
    } else {
        format!("status: {status}\n{frontmatter}")
    };
    format!("{}{}{}", &text[..start], updated, &text[end..])
}

pub fn spec_unticked(
    ws: &Workspace,
    meta: &serde_json::Map<String, Value>,
) -> Vec<(usize, String)> {
    match resolve_spec_path(ws, meta) {
        Some(path) => read_text(&path)
            .map(|text| unticked_criteria(&text))
            .unwrap_or_default(),
        None => Vec::new(),
    }
}

/// Why this task's spec is not ready for work, or None.
pub fn spec_problem(ws: &Workspace, meta: &serde_json::Map<String, Value>) -> Option<String> {
    let reference = meta
        .get("spec")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if reference.is_empty() || reference == "null" {
        return None;
    }
    let absolute = if Path::new(&reference).is_absolute() {
        PathBuf::from(&reference)
    } else {
        ws.root.join(&reference)
    };
    if !absolute.is_file() {
        return Some(format!("spec {reference} does not exist"));
    }
    let text = match read_text(&absolute) {
        Ok(text) => text,
        Err(_) => return Some(format!("spec {reference} cannot be read")),
    };
    if real_criteria(&acceptance_criteria(&text)).is_empty() {
        return Some(format!(
            "spec {reference} has no acceptance criteria yet (it is still the template)"
        ));
    }
    None
}

/// Move a finished task's spec from specs/active to specs/done.
pub fn archive_spec(ws: &Workspace, meta: &mut serde_json::Map<String, Value>) -> Option<String> {
    let reference = meta
        .get("spec")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if reference.is_empty() {
        return None;
    }
    let absolute = if Path::new(&reference).is_absolute() {
        PathBuf::from(&reference)
    } else {
        ws.root.join(&reference)
    };
    let active =
        std::fs::canonicalize(ws.specs_active_dir()).unwrap_or_else(|_| ws.specs_active_dir());
    let absolute = std::fs::canonicalize(&absolute).unwrap_or(absolute);
    if absolute.parent() != Some(active.as_path()) || !absolute.is_file() {
        return None;
    }
    let target = ws.specs_done_dir().join(absolute.file_name()?);
    if target.exists() {
        return None;
    }
    fs::rename(&absolute, &target).ok()?;
    if let Ok(text) = read_text(&target) {
        let _ = write_text_atomic(&target, &mark_status(&text, "shipped"));
    }
    Some(
        target
            .strip_prefix(&ws.root)
            .map(|rest| rest.to_string_lossy().replace('\\', "/"))
            .unwrap_or_else(|_| target.to_string_lossy().replace('\\', "/")),
    )
}

pub fn resolve_spec_path(ws: &Workspace, meta: &serde_json::Map<String, Value>) -> Option<PathBuf> {
    let spec = meta.get("spec")?.as_str()?.trim().to_string();
    if spec.is_empty() {
        return None;
    }
    let mut candidates: Vec<PathBuf> = Vec::new();
    if Path::new(&spec).is_absolute() {
        candidates.push(PathBuf::from(&spec));
    } else {
        candidates.push(ws.project.join(&spec));
        candidates.push(ws.root.join(&spec));
    }
    if let Ok(id) = normalize_id(&spec) {
        let prefix = format!("{id}-");
        for folder in ["active", "done"] {
            let directory = ws.specs_dir().join(folder);
            if let Ok(entries) = fs::read_dir(directory) {
                let mut names: Vec<String> = entries
                    .flatten()
                    .map(|entry| entry.file_name().to_string_lossy().to_string())
                    .filter(|name| name.starts_with(&prefix) && name.ends_with(".md"))
                    .collect();
                names.sort();
                for name in names {
                    candidates.push(ws.specs_dir().join(folder).join(name));
                }
            }
        }
    }
    candidates.into_iter().find(|path| path.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn criteria_round_trip() {
        let text = "---\nstatus: draft\n---\n\n## Acceptance criteria\n\n- [ ] One\n- [x] Two\n\n## Out of scope\n\nnothing\n";
        let criteria = acceptance_criteria(text);
        assert_eq!(criteria.len(), 2);
        assert_eq!(criteria_progress(&criteria), (1, 2));
        let (changed, ticked) = tick_criterion(text, 1).unwrap();
        assert!(ticked);
        assert!(changed.contains("- [x] One"));
        assert_eq!(unticked_criteria(&changed).len(), 0);
        assert!(mark_status(text, "shipped").contains("status: shipped"));
    }
}
