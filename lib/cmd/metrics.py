"""cmd.metrics: split out of the former monolithic ai.py."""

from __future__ import annotations

import json
import sys

from lib.runtime import metrics as runtime_metrics


def cmd_metrics(args) -> int:
    try:
        since = runtime_metrics.metrics_since(args.since)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = runtime_metrics.collect_metrics(since)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"Events recorded: {result['events_recorded']}")
    print(f"Tasks completed: {result['tasks_completed']}")
    for key, label in (
        ("median_creation_to_done_seconds", "Median creation-to-done"),
        ("median_review_to_merge_seconds", "Median review-to-merge"),
    ):
        value = result[key]
        print(f"{label}: {value:.1f} seconds" if value is not None else f"{label}: n/a")
    print(f"Lock refusals: {result['lock_refusals']}")
    print(f"Retries: {result['retries']}")
    print(f"Resumes: {result['resumes']}")
    print("Per-agent events:")
    for agent, count in result["per_agent"].items():
        print(f"  {agent}: {count}")
    return 0


ORDER = 40


def register(sub) -> None:
    """Attach this command group's parsers to the root subparsers."""
    metrics = sub.add_parser("metrics", help="summarize local workflow metrics")
    metrics.add_argument("--since", default=None, help="filter on or after an ISO date or timestamp")
    metrics.add_argument("--json", action="store_true")
    metrics.set_defaults(func=cmd_metrics)
