//! Task creation, claiming, readiness and ownership.

use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use crate::config::roles;
use crate::config::settings::lock_settings;
use crate::core::error::{fail, AiError, Result};
use crate::core::fsio::{normalize_id, read_json, slugify, write_json_atomic, write_text_atomic};
use crate::core::time::iso;
use crate::core::workspace::Workspace;
use crate::runtime::dirs::ensure_dirs;
use crate::runtime::events::append_event;
use crate::runtime::leases::{
    acquire_lock, heartbeat_lock, list_locks, lock_is_stale, release_lock,
};
use crate::runtime::mutex::workspace_state_guard;
use crate::specs::spec;
use crate::tasks::board;
use crate::tasks::gates;
use crate::tasks::history;
use crate::tasks::scope;
use crate::tasks::store::{self, Task};

pub struct TaskIndexGuard<'a> {
    ws: &'a Workspace,
}

impl Drop for TaskIndexGuard<'_> {
    fn drop(&mut self) {
        let _ = release_lock(self.ws, "tasks.index", Some("task-index"), true, true);
    }
}

fn task_index_guard(ws: &Workspace) -> Result<TaskIndexGuard<'_>> {
    let result = acquire_lock(ws, "tasks.index", Some("task-index"), None, Some(60), false)?;
    if !result.ok {
        let holder = result.holder.unwrap_or_else(|| json!({}));
        return fail(format!(
            "Could not allocate a task id: the task index is locked by {}.",
            holder
                .get("agent")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ));
    }
    Ok(TaskIndexGuard { ws })
}

fn allocate_task_number(ws: &Workspace) -> Result<u64> {
    let holder = crate::runtime::leases::read_holder(&crate::core::fsio::lock_path(
        &ws.locks_dir(),
        "tasks.index",
    ))
    .unwrap_or_else(|| json!({}));
    if holder.get("agent").and_then(Value::as_str) != Some("task-index") {
        return fail("task ID allocation requires the tasks.index lock");
    }
    let mut last = match read_json(&ws.counter_path()) {
        Ok(Some(value)) => value.get("last").and_then(Value::as_u64).unwrap_or(0),
        Ok(None) => 0,
        Err(error) => {
            append_event(
                ws,
                "state_repaired",
                &[
                    (
                        "file",
                        json!(ws
                            .counter_path()
                            .strip_prefix(&ws.root)
                            .map(|p| p.to_string_lossy().replace('\\', "/"))
                            .unwrap_or_default()),
                    ),
                    ("error", json!(error.to_string())),
                ],
            );
            0
        }
    };
    for task in store::load_tasks(ws) {
        let digits: String = task.id().chars().filter(|ch| ch.is_ascii_digit()).collect();
        if let Ok(value) = digits.parse::<u64>() {
            last = last.max(value);
        }
    }
    let number = last + 1;
    write_json_atomic(&ws.counter_path(), &json!({"last": number}))?;
    Ok(number)
}

#[derive(Clone, Debug, Default)]
pub struct NewTask {
    pub title: String,
    pub priority: String,
    pub spec: Option<String>,
    pub depends_on: Option<String>,
    pub make_spec: bool,
    pub scope_allowed: Option<String>,
    pub scope_forbidden: Option<String>,
    pub actor: Option<String>,
    pub locks: Option<String>,
    pub intent: Option<String>,
    pub acceptance: Option<Vec<String>>,
    pub demo: bool,
}

pub fn create_task(ws: &Workspace, new: NewTask) -> Result<Value> {
    ensure_dirs(ws)?;
    let _state = workspace_state_guard(ws)?;
    let number = {
        let _index = task_index_guard(ws)?;
        allocate_task_number(ws)?
    };
    let task_id = format!("{number:04}");
    let title = new.title.trim().to_string();
    if title.is_empty() {
        return fail("a task needs a non-empty title");
    }
    let slug = slugify(&title);
    let path = ws.active_dir().join(format!("{task_id}-{slug}.md"));
    let mut spec_ref = new.spec.clone();
    if spec_ref.is_none() && new.make_spec {
        let spec_path = ws.specs_active_dir().join(format!("{task_id}-{slug}.md"));
        let text = spec::spec_from_template(
            ws,
            &title,
            &task_id,
            new.intent.as_deref(),
            new.acceptance.as_deref(),
        );
        write_text_atomic(&spec_path, &text)?;
        spec_ref = Some(
            spec_path
                .strip_prefix(&ws.root)
                .map(|p| p.to_string_lossy().replace('\\', "/"))
                .unwrap_or_else(|_| spec_path.to_string_lossy().replace('\\', "/")),
        );
    }
    let mut meta = Map::new();
    meta.insert("id".into(), json!(task_id));
    meta.insert("title".into(), json!(title));
    meta.insert("status".into(), json!("todo"));
    meta.insert("owner".into(), Value::Null);
    meta.insert("priority".into(), json!(new.priority));
    meta.insert(
        "spec".into(),
        spec_ref.as_ref().map(|s| json!(s)).unwrap_or(Value::Null),
    );
    meta.insert(
        "depends_on".into(),
        new.depends_on
            .as_ref()
            .map(|s| json!(s))
            .unwrap_or(Value::Null),
    );
    meta.insert(
        "scope_allowed".into(),
        new.scope_allowed
            .as_ref()
            .map(|s| json!(s))
            .unwrap_or(Value::Null),
    );
    meta.insert(
        "scope_forbidden".into(),
        new.scope_forbidden
            .as_ref()
            .map(|s| json!(s))
            .unwrap_or(Value::Null),
    );
    let locks = new.locks.clone().or_else(|| new.scope_allowed.clone());
    meta.insert(
        "locks".into(),
        locks.as_ref().map(|s| json!(s)).unwrap_or(Value::Null),
    );
    meta.insert("created".into(), json!(iso(None)));
    meta.insert("updated".into(), json!(iso(None)));
    meta.insert("lock".into(), Value::Null);
    if new.demo {
        meta.insert("demo".into(), json!(true));
    }
    let criteria = match &spec_ref {
        Some(reference) => format!(
            "Criteria live in the spec: `{reference}`. Tick each one as it becomes true: `ai spec check {task_id} <n>`."
        ),
        None => "<!-- No spec: this task was created with --no-spec, so it has no criteria to tick. -->".to_string(),
    };
    let plan = match &spec_ref {
        Some(reference) => format!("Spec: `{reference}`\n\n<!-- Filled by the planner. -->"),
        None => "<!-- Filled by the planner. Link the spec when one exists. -->".to_string(),
    };
    let intent = new
        .intent
        .clone()
        .unwrap_or_else(|| "<!-- What problem does this solve? Who is it for? -->".to_string());
    let body = format!(
        r#"# {task_id} - {title}

## Intent

{intent}

## Acceptance criteria

{criteria}

## Plan

{plan}

## Notes

## Log

{}
"#,
        history::line(new.actor.as_deref(), None, "todo", "created", "")
    );
    store::write_task(&path, &meta, &body)?;
    board::write_board(ws, &store::load_tasks(ws))?;
    append_event(ws, "task_created", &[("task", json!(task_id))]);
    Ok(json!({
        "id": task_id,
        "path": path.to_string_lossy(),
        "spec": spec_ref,
        "slug": slug,
    }))
}

pub fn claim_task(ws: &Workspace, path: &Path, agent: &str, force: bool) -> Result<(bool, String)> {
    let (current_meta, _, _) = store::parse_task(path)?;
    let current = current_meta
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let action = if current == "review" {
        "task.done"
    } else {
        "task.claim"
    };
    if !force {
        if let Err(denied) = roles::authorize(ws, Some(agent), action) {
            return Ok((false, denied));
        }
    }
    if current != "review" && !force {
        let task = Task {
            meta: current_meta.clone(),
            body: String::new(),
            path: path.to_path_buf(),
            folder: "active".into(),
        };
        if let Some(unready) = gates::spec_gate(ws, &task) {
            return Ok((false, unready));
        }
    }
    if path.parent() != Some(ws.active_dir().as_path()) {
        return Ok((false, "This task is already in done/.".to_string()));
    }
    let _state = workspace_state_guard(ws)?;
    let (mut meta, body, _) = store::parse_task(path)?;
    let task_id = meta
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if meta.get("status").and_then(Value::as_str) == Some("blocked") && !force {
        return Ok((
            false,
            format!("Task {task_id} is blocked. Unblock it with `ai task unblock {task_id}`."),
        ));
    }
    let blockers = store::dependency_blockers(ws, &meta);
    if !blockers.is_empty() && !force {
        return Ok((
            false,
            format!(
                "Task {task_id} is blocked by {}. Use --force to override.",
                blockers.join(", ")
            ),
        ));
    }
    let resource = format!("task-{task_id}");
    let result = acquire_lock(ws, &resource, Some(agent), Some(&task_id), None, force)?;
    let new_claim = result.ok;
    if !result.ok {
        if let Some(error) = result.error {
            append_event(
                ws,
                "lock_refused",
                &[
                    ("resource", json!(resource)),
                    ("agent", json!(agent)),
                    ("task", json!(task_id)),
                ],
            );
            return Ok((false, format!("Could not claim task {task_id}: {error}")));
        }
        let holder = result.holder.unwrap_or_else(|| json!({}));
        let holder_agent = holder
            .get("agent")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        if holder_agent == agent {
            heartbeat_lock(ws, &resource, Some(agent), true)?;
        } else {
            append_event(
                ws,
                "lock_refused",
                &[
                    ("resource", json!(resource)),
                    ("agent", json!(agent)),
                    ("task", json!(task_id)),
                    (
                        "conflict",
                        holder.get("resource").cloned().unwrap_or(Value::Null),
                    ),
                    ("conflict_agent", json!(holder_agent)),
                ],
            );
            return Ok((
                false,
                format!(
                    "Task {task_id} is locked by {holder_agent} (pid {}, since {}).",
                    holder
                        .get("pid")
                        .map(|v| v.to_string())
                        .unwrap_or_else(|| "-".into()),
                    holder
                        .get("started_at")
                        .and_then(Value::as_str)
                        .unwrap_or("-")
                ),
            ));
        }
    }
    if store::find_task(ws, &task_id).as_deref() != Some(path) {
        let _ = release_lock(ws, &resource, Some(agent), true, true);
        return Ok((
            false,
            format!("Task {task_id} was removed while it was being claimed."),
        ));
    }
    let previous = meta
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("todo")
        .to_string();
    meta.insert("owner".into(), json!(agent));
    meta.insert(
        "status".into(),
        json!(if previous == "review" {
            "review"
        } else {
            "in_progress"
        }),
    );
    meta.insert("updated".into(), json!(iso(None)));
    meta.insert("lock".into(), json!(resource));
    let new_status = meta
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("in_progress")
        .to_string();
    let new_body = history::append(
        &body,
        Some(agent),
        Some(&previous),
        &new_status,
        "claimed",
        "",
    );
    store::write_task(path, &meta, &new_body)?;
    board::write_board(ws, &store::load_tasks(ws))?;
    if new_claim {
        append_event(
            ws,
            "task_claimed",
            &[("task", json!(task_id)), ("agent", json!(agent))],
        );
    }
    Ok((true, task_id))
}

/// Undo `claim_task` when a later step (the task branch) failed.
pub fn rollback_claim(
    ws: &Workspace,
    path: &Path,
    agent: &str,
    previous_status: Option<&str>,
    reason: &str,
) -> Result<Option<String>> {
    let task_id;
    let meta;
    {
        let _state = workspace_state_guard(ws)?;
        let (mut current_meta, mut body, _) = store::parse_task(path)?;
        task_id = current_meta
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if current_meta.get("owner").and_then(Value::as_str) != Some(agent) {
            return Ok(None);
        }
        let current = current_meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        current_meta.insert("owner".into(), Value::Null);
        current_meta.insert("lock".into(), Value::Null);
        current_meta.insert("status".into(), json!(previous_status.unwrap_or("todo")));
        current_meta.insert("updated".into(), json!(iso(None)));
        let restored = current_meta
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("todo")
            .to_string();
        body = history::append(
            &body,
            Some(agent),
            Some(&current),
            &restored,
            "claim rolled back",
            reason,
        );
        store::write_task(path, &current_meta, &body)?;
        board::write_board(ws, &store::load_tasks(ws))?;
        meta = current_meta;
    }
    release_task_locks(ws, &meta, Some(agent))?;
    let _ = release_lock(ws, &format!("task-{task_id}"), Some(agent), true, true);
    append_event(
        ws,
        "claim_rolled_back",
        &[
            ("task", json!(task_id)),
            ("agent", json!(agent)),
            ("reason", json!(reason)),
        ],
    );
    Ok(Some(task_id))
}

pub fn ready_and_waiting(ws: &Workspace) -> (Vec<Task>, Vec<(Task, Vec<String>)>) {
    let active: Vec<Task> = store::load_tasks(ws)
        .into_iter()
        .filter(Task::is_active)
        .collect();
    let locks: std::collections::HashMap<String, Value> = list_locks(ws, false)
        .into_iter()
        .filter_map(|lock| {
            lock.get("resource")
                .and_then(Value::as_str)
                .map(|resource| (resource.to_string(), lock.clone()))
        })
        .collect();
    let (_, stale_after) = lock_settings(ws);
    let mut ready = Vec::new();
    let mut waiting = Vec::new();
    for task in active {
        if !matches!(task.status().as_str(), "todo" | "changes_requested") {
            continue;
        }
        let mut reasons = store::dependency_blockers(ws, &task.meta);
        if let Some(lock) = locks.get(&format!("task-{}", task.id())) {
            if !lock_is_stale(Some(lock), stale_after) {
                reasons.push(format!(
                    "leased by {}",
                    lock.get("agent")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown")
                ));
            }
        }
        if reasons.is_empty() {
            ready.push(task);
        } else {
            waiting.push((task, reasons));
        }
    }
    ready.sort_by(|a, b| {
        let rework_a = if a.status() == "changes_requested" {
            0
        } else {
            1
        };
        let rework_b = if b.status() == "changes_requested" {
            0
        } else {
            1
        };
        rework_a
            .cmp(&rework_b)
            .then_with(|| {
                store::priority_rank(a.priority().as_deref())
                    .cmp(&store::priority_rank(b.priority().as_deref()))
            })
            .then_with(|| a.id().cmp(&b.id()))
    });
    (ready, waiting)
}

/// File resources a task declared it will edit (acquired on claim).
pub fn file_locks(task: &Task) -> Vec<String> {
    scope::split_globs(task.meta.get("locks"))
}

/// Lock every declared resource for `agent`; all or nothing.
pub fn acquire_task_locks(ws: &Workspace, task: &Task, agent: &str) -> Result<(bool, String)> {
    let task_id = task.id();
    let mut taken: Vec<String> = Vec::new();
    for resource in file_locks(task) {
        let result = acquire_lock(ws, &resource, Some(agent), Some(&task_id), None, false)?;
        if !result.ok {
            for done in &taken {
                let _ = release_lock(ws, done, Some(agent), false, true);
            }
            let holder = result.holder.unwrap_or_else(|| json!({}));
            return Ok((
                false,
                format!(
                    "Resource '{resource}' is locked by {} (task {}); task {task_id} stays unclaimed by file locks.",
                    holder.get("agent").and_then(Value::as_str).unwrap_or("?"),
                    holder.get("task").and_then(Value::as_str).unwrap_or("-")
                ),
            ));
        }
        taken.push(resource);
    }
    Ok((true, taken.join(", ")))
}

/// Free the file locks of a task: declared ones and any taken by hand for it.
pub fn release_task_locks(
    ws: &Workspace,
    meta: &Map<String, Value>,
    agent: Option<&str>,
) -> Result<()> {
    let task_id = meta.get("id").and_then(Value::as_str).unwrap_or("");
    let mut resources: std::collections::BTreeSet<String> =
        scope::split_globs(meta.get("locks")).into_iter().collect();
    for lock in list_locks(ws, false) {
        let resource = lock.get("resource").and_then(Value::as_str).unwrap_or("");
        if !resource.is_empty()
            && !resource.starts_with("task-")
            && lock.get("task").and_then(Value::as_str) == Some(task_id)
        {
            let owner = lock.get("agent").and_then(Value::as_str);
            if agent.is_none() || owner == agent {
                resources.insert(resource.to_string());
            }
        }
    }
    for resource in resources {
        let _ = release_lock(ws, &resource, agent, agent.is_none(), true);
    }
    Ok(())
}

pub fn resolve_task_id(ws: &Workspace, task_id: Option<&str>) -> Option<String> {
    store::resolve_task_id(ws, task_id)
}

pub fn find_task(ws: &Workspace, task_id: &str) -> Option<PathBuf> {
    store::find_task(ws, task_id)
}

pub fn normalized_id(task_id: &str) -> Result<String> {
    normalize_id(task_id)
}

pub fn active_dir(ws: &Workspace) -> PathBuf {
    ws.active_dir()
}

pub fn config_error(message: impl Into<String>) -> AiError {
    AiError::Msg(message.into())
}
