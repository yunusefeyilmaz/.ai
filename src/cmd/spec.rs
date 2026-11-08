//! `ai spec`: tick and show a task's acceptance criteria.

use serde_json::{json, Value};

use crate::core::error::Result;
use crate::core::fsio::{read_text, write_text_atomic};
use crate::core::workspace::{relative_to, Workspace};
use crate::specs::spec as spec_lib;
use crate::tasks::store;

use crate::{SpecAction, SpecArgs};

fn linked_spec(
    ws: &Workspace,
    meta: &serde_json::Map<String, Value>,
) -> (Option<std::path::PathBuf>, Option<String>) {
    let reference = meta
        .get("spec")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let id = meta.get("id").and_then(Value::as_str).unwrap_or("-");
    if reference.is_empty() || reference == "null" {
        return (
            None,
            Some(format!(
                "Task {id} has no spec: it was created with --no-spec."
            )),
        );
    }
    match spec_lib::resolve_spec_path(ws, meta) {
        Some(path) => (Some(path), None),
        None => (
            None,
            Some(format!(
                "Task {id} points at a spec that does not exist: {reference}"
            )),
        ),
    }
}

fn progress_line(criteria: &[(bool, String)]) -> String {
    let (done, total) = spec_lib::criteria_progress(criteria);
    if total == 0 {
        "no real acceptance criteria yet".to_string()
    } else {
        format!("{done}/{total} done")
    }
}

pub fn run(ws: &Workspace, args: &SpecArgs) -> Result<i32> {
    match &args.action {
        Some(SpecAction::Show { task_id, json }) => show(ws, task_id, *json),
        Some(SpecAction::Check { task_id, n }) => check(ws, task_id, *n),
        None => {
            eprintln!("Usage: ai spec show <task-id> | ai spec check <task-id> <n>");
            Ok(1)
        }
    }
}

fn show(ws: &Workspace, task_id: &str, json_out: bool) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (meta, _, _) = store::parse_task(&path)?;
    let (spec_path, error) = linked_spec(ws, &meta);
    let spec_path = match (spec_path, error) {
        (Some(path), _) => path,
        (None, Some(error)) => {
            eprintln!("{error}");
            return Ok(1);
        }
        (None, None) => return Ok(1),
    };
    let text = match read_text(&spec_path) {
        Ok(text) => text,
        Err(error) => {
            eprintln!(
                "Cannot read {}: {error}",
                relative_to(&ws.project, &spec_path)
            );
            return Ok(1);
        }
    };
    let criteria = spec_lib::acceptance_criteria(&text);
    if json_out {
        let (done, total) = spec_lib::criteria_progress(&criteria);
        println!(
            "{}",
            serde_json::to_string_pretty(&json!({
                "task": meta.get("id").and_then(Value::as_str).unwrap_or(""),
                "spec": relative_to(&ws.project, &spec_path),
                "criteria": criteria.iter().map(|(done, item)| json!([done, item])).collect::<Vec<_>>(),
                "done": done,
                "total": total,
            }))?
        );
        return Ok(0);
    }
    println!("Spec:     {}", relative_to(&ws.project, &spec_path));
    println!("Progress: {}", progress_line(&criteria));
    for (done, item) in &criteria {
        println!("  [{}] {item}", if *done { 'x' } else { ' ' });
    }
    Ok(0)
}

fn check(ws: &Workspace, task_id: &str, number: usize) -> Result<i32> {
    let path = match store::find_task(ws, task_id) {
        Some(path) => path,
        None => {
            eprintln!("No task with id {task_id}.");
            return Ok(1);
        }
    };
    let (meta, _, _) = store::parse_task(&path)?;
    if path.parent() != Some(ws.active_dir().as_path()) {
        eprintln!(
            "Task {task_id} is archived in done/ and its spec is immutable. Bring it back with `ai task reopen {task_id} --agent <name>` first."
        );
        return Ok(1);
    }
    let (spec_path, error) = linked_spec(ws, &meta);
    let spec_path = match (spec_path, error) {
        (Some(path), _) => path,
        (None, Some(error)) => {
            eprintln!("{error}");
            return Ok(1);
        }
        (None, None) => return Ok(1),
    };
    let text = match read_text(&spec_path) {
        Ok(text) => text,
        Err(error) => {
            eprintln!(
                "Cannot read {}: {error}",
                relative_to(&ws.project, &spec_path)
            );
            return Ok(1);
        }
    };
    let (updated, changed) = match spec_lib::tick_criterion(&text, number) {
        Ok(result) => result,
        Err(error) => {
            eprintln!(
                "Cannot tick criterion {number} of task {}: {error}.",
                meta.get("id").and_then(Value::as_str).unwrap_or("-")
            );
            eprintln!(
                "Inspect the spec with `ai spec show {}`.",
                meta.get("id").and_then(Value::as_str).unwrap_or("-")
            );
            return Ok(1);
        }
    };
    let criteria = spec_lib::acceptance_criteria(&updated);
    let item = criteria
        .get(number.saturating_sub(1))
        .map(|(_, item)| item.clone())
        .unwrap_or_default();
    if changed {
        write_text_atomic(&spec_path, &updated)?;
        println!("Ticked {number}: {item}");
    } else {
        println!("Criterion {number} was already ticked: {item}");
    }
    println!("Progress: {}", progress_line(&criteria));
    if spec_lib::unticked_criteria(&updated).is_empty() {
        println!(
            "Every acceptance criterion in {} is ticked.",
            spec_path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("the spec")
        );
    }
    Ok(0)
}
