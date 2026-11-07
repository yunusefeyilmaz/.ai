//! Support commands: metrics, capabilities, version, artifact, clean, reset,
//! adopt, worktree and the read-only terminal dashboard.

use serde_json::Value;

use crate::core::error::Result;
use crate::core::workspace::Workspace;
use crate::runtime::metrics;

use crate::MetricsArgs;
pub fn run(ws: &Workspace, args: &MetricsArgs) -> Result<i32> {
    let since = match metrics::metrics_since(args.since.as_deref()) {
        Ok(since) => since,
        Err(error) => {
            eprintln!("{error}");
            return Ok(2);
        }
    };
    let result = metrics::collect_metrics(ws, since);
    if args.json {
        println!("{}", serde_json::to_string_pretty(&result)?);
        return Ok(0);
    }
    println!(
        "Events recorded: {}",
        result
            .get("events_recorded")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    );
    println!(
        "Tasks completed: {}",
        result
            .get("tasks_completed")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    );
    for (key, label) in [
        ("median_creation_to_done_seconds", "Median creation-to-done"),
        ("median_review_to_merge_seconds", "Median review-to-merge"),
    ] {
        match result.get(key).and_then(Value::as_f64) {
            Some(value) => println!("{label}: {value:.1} seconds"),
            None => println!("{label}: n/a"),
        }
    }
    println!(
        "Lock refusals: {}",
        result
            .get("lock_refusals")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    );
    println!(
        "Retries: {}",
        result.get("retries").and_then(Value::as_u64).unwrap_or(0)
    );
    println!(
        "Resumes: {}",
        result.get("resumes").and_then(Value::as_u64).unwrap_or(0)
    );
    println!("Per-agent events:");
    if let Some(agents) = result.get("per_agent").and_then(Value::as_object) {
        for (agent, count) in agents {
            println!("  {agent}: {}", count.as_u64().unwrap_or(0));
        }
    }
    Ok(0)
}
