//! Turn one plan document into many linked tasks.

use std::collections::{HashMap, HashSet};

use regex::Regex;
use serde_json::{json, Value};

use crate::config::settings::bool_preference;
use crate::core::error::{fail, Result};
use crate::core::workspace::Workspace;
use crate::runtime::leases::resources_overlap;
use crate::tasks::lifecycle::{self, NewTask};
use crate::tasks::scope;

pub fn example() -> Value {
    json!({
        "tasks": [
            {"key": "api", "title": "Build the REST API", "priority": "high",
             "intent": "Why this exists and for whom.",
             "acceptance": ["Observable criterion one"], "locks": ["src/api/**"], "depends_on": []},
            {"key": "ui", "title": "Login form", "priority": "medium",
             "acceptance": ["Observable criterion"], "locks": ["src/ui/**"], "depends_on": ["api"]}
        ]
    })
}

fn list(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| {
                item.as_str()
                    .map(ToString::to_string)
                    .unwrap_or_else(|| item.to_string())
            })
            .collect(),
        Some(Value::String(text)) => scope::split_globs(Some(&Value::String(text.clone()))),
        Some(Value::Null) | None => Vec::new(),
        Some(other) => scope::split_globs(Some(other)),
    }
}

fn tasks_of(plan: &Value) -> Option<&Vec<Value>> {
    plan.get("tasks").and_then(Value::as_array)
}

pub fn validate(plan: &Value) -> (Vec<String>, Vec<String>) {
    let mut errors = Vec::new();
    let mut warnings = Vec::new();
    let tasks = match tasks_of(plan) {
        Some(tasks) if !tasks.is_empty() => tasks,
        _ => {
            return (
                vec!["plan must be {\"tasks\": [ ... ]} with at least one task".into()],
                warnings,
            )
        }
    };
    let key_re = Regex::new(r"^[a-z0-9][a-z0-9_-]*$").expect("static regex");
    let mut keys: HashMap<String, &Value> = HashMap::new();
    for (index, item) in tasks.iter().enumerate() {
        let index = index + 1;
        let object = match item.as_object() {
            Some(object) => object,
            None => {
                errors.push(format!("task #{index} is not an object"));
                continue;
            }
        };
        let key = object
            .get("key")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if !key_re.is_match(&key) {
            errors.push(format!(
                "task #{index}: key must match [a-z0-9][a-z0-9_-]* (got '{key}')"
            ));
        } else if keys.contains_key(&key) {
            errors.push(format!("duplicate key '{key}'"));
        }
        keys.insert(key.clone(), item);
        let title = object.get("title").and_then(Value::as_str).unwrap_or("");
        if title.trim().is_empty() {
            errors.push(format!("task '{key}': title is required"));
        }
        let priority = object
            .get("priority")
            .and_then(Value::as_str)
            .unwrap_or("medium");
        if !matches!(priority, "low" | "medium" | "high") {
            errors.push(format!(
                "task '{key}': priority must be low, medium or high"
            ));
        }
    }
    for (key, item) in &keys {
        for dep in list(item.get("depends_on")) {
            if !keys.contains_key(&dep) {
                errors.push(format!("task '{key}' depends on unknown key '{dep}'"));
            } else if &dep == key {
                errors.push(format!("task '{key}' depends on itself"));
            }
        }
    }
    if errors.is_empty() {
        let items: Vec<Value> = keys.values().map(|value| (*value).clone()).collect();
        if order(&items).is_none() {
            errors.push("dependency cycle between tasks".into());
        }
    }
    if errors.is_empty() {
        let items: Vec<Value> = keys.values().map(|value| (*value).clone()).collect();
        warnings = lock_warnings(&items);
    }
    (errors, warnings)
}

fn order(items: &[Value]) -> Option<Vec<Value>> {
    let mut remaining: Vec<Value> = items.to_vec();
    let mut placed = Vec::new();
    let mut done: HashSet<String> = HashSet::new();
    while !remaining.is_empty() {
        let ready: Vec<Value> = remaining
            .iter()
            .filter(|task| {
                list(task.get("depends_on"))
                    .iter()
                    .all(|dep| done.contains(dep))
            })
            .cloned()
            .collect();
        if ready.is_empty() {
            return None;
        }
        for task in ready {
            placed.push(task.clone());
            if let Some(key) = task.get("key").and_then(Value::as_str) {
                done.insert(key.to_string());
            }
            remaining.retain(|item| item != &task);
        }
    }
    Some(placed)
}

fn ancestors(key: &str, by_key: &HashMap<String, Value>, seen: &mut HashSet<String>) {
    if let Some(item) = by_key.get(key) {
        for dep in list(item.get("depends_on")) {
            if seen.insert(dep.clone()) {
                ancestors(&dep, by_key, seen);
            }
        }
    }
}

fn lock_warnings(items: &[Value]) -> Vec<String> {
    let by_key: HashMap<String, Value> = items
        .iter()
        .filter_map(|item| {
            item.get("key")
                .and_then(Value::as_str)
                .map(|key| (key.to_string(), item.clone()))
        })
        .collect();
    let mut warnings = Vec::new();
    for (i, a) in items.iter().enumerate() {
        for b in items.iter().skip(i + 1) {
            let a_key = a.get("key").and_then(Value::as_str).unwrap_or("");
            let b_key = b.get("key").and_then(Value::as_str).unwrap_or("");
            let mut seen_b = HashSet::new();
            ancestors(b_key, &by_key, &mut seen_b);
            let mut seen_a = HashSet::new();
            ancestors(a_key, &by_key, &mut seen_a);
            if seen_b.contains(a_key) || seen_a.contains(b_key) {
                continue;
            }
            for x in list(a.get("locks")) {
                for y in list(b.get("locks")) {
                    if resources_overlap(&x, &y).unwrap_or(false) {
                        warnings.push(format!(
                            "'{a_key}' and '{b_key}' both lock overlapping paths ({x} / {y}) without a dependency: they cannot run in parallel. Add depends_on or split the paths."
                        ));
                    }
                }
            }
        }
    }
    warnings
}

pub fn apply(ws: &Workspace, plan: &Value, actor: Option<&str>) -> Result<Vec<Value>> {
    let writes_tests = bool_preference(ws, "testing.writeTests", true);
    let mut ids: HashMap<String, String> = HashMap::new();
    let mut created = Vec::new();
    let tasks = match tasks_of(plan) {
        Some(tasks) => tasks.clone(),
        None => return fail("plan must contain a tasks array"),
    };
    let ordered = match order(&tasks) {
        Some(ordered) => ordered,
        None => return fail("dependency cycle between tasks"),
    };
    for item in ordered {
        let key = item
            .get("key")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let locks = list(item.get("locks"));
        let mut allow = list(item.get("allow"));
        if allow.is_empty() {
            allow = locks.clone();
        }
        let mut acceptance = list(item.get("acceptance"));
        if item
            .get("tests")
            .and_then(Value::as_bool)
            .unwrap_or(writes_tests)
        {
            acceptance.push("Tests cover the new behavior and pass".to_string());
        }
        let mut deps = Vec::new();
        for dep in list(item.get("depends_on")) {
            if let Some(id) = ids.get(&dep) {
                deps.push(id.clone());
            }
        }
        let new = NewTask {
            title: item
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
            priority: item
                .get("priority")
                .and_then(Value::as_str)
                .unwrap_or("medium")
                .to_string(),
            spec: None,
            depends_on: if deps.is_empty() {
                None
            } else {
                Some(deps.join(", "))
            },
            make_spec: item.get("spec").and_then(Value::as_bool).unwrap_or(true),
            scope_allowed: scope::join_globs(Some(&allow)),
            scope_forbidden: scope::join_globs(Some(&list(item.get("forbid")))),
            actor: actor.map(ToString::to_string),
            locks: scope::join_globs(Some(&locks)),
            intent: item
                .get("intent")
                .and_then(Value::as_str)
                .filter(|text| !text.is_empty())
                .map(ToString::to_string),
            acceptance: if acceptance.is_empty() {
                None
            } else {
                Some(acceptance)
            },
            demo: false,
        };
        let result = lifecycle::create_task(ws, new)?;
        let id = result
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        ids.insert(key.clone(), id.clone());
        created.push(json!({
            "key": key,
            "id": id,
            "title": item.get("title"),
            "depends_on": deps,
            "locks": locks,
        }));
    }
    Ok(created)
}
