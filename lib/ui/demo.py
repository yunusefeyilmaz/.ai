"""ui.demo: a self-playing fake workspace for `ai ui --demo`.

Shows every screen with realistic, moving data (tasks advance, locks tick, events
stream in) without touching any real state. Output has exactly the shape of
`data.load_snapshot`, so the screens cannot tell the difference.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

from lib.core.paths import VERSION
from lib.ui.data import LIST_ORDER, STATUS_ORDER, STATUS_WEIGHT

SPEC_TEXT = "Users can sign in with email and a password; sessions expire after 30 minutes of inactivity."
TASKS = [
    # id, title, priority, status, owner, deps, locks, criteria (text, done)
    ("0001", "Build the REST API skeleton", "high", "done", None, [], ["src/api/**"],
     [("GET /health returns {\"ok\":true}", True), ("Unknown route returns 404 with a JSON error", True)]),
    ("0002", "Login form and session handling", "high", "review", "claude-1", ["0001"], ["src/auth/**", "src/ui/login/**"],
     [("Valid login sets a session cookie", True), ("Wrong password returns 401 and no cookie", True), ("Session expires after 30 min idle", True), ("Logout clears the cookie", False)]),
    ("0003", "Payment webhooks with retry", "high", "in_progress", "codex-1", ["0001"], ["src/payments/**"],
     [("Signed webhook is accepted", True), ("Bad signature returns 400", True), ("Failed delivery retries 3 times", False), ("Idempotency key prevents double charge", False)]),
    ("0004", "Product search index", "medium", "in_progress", "cursor-1", ["0001"], ["src/search/**"],
     [("Query returns ranked results under 200 ms", False), ("Empty query returns the newest 20", True), ("Index rebuild is resumable", False)]),
    ("0005", "Admin dashboard", "medium", "todo", None, ["0002"], ["src/admin/**"],
     [("Admins see order totals per day", False), ("Non-admins get 403", False)]),
    ("0006", "Rate limiting middleware", "medium", "changes_requested", "claude-1", ["0001"], ["src/api/middleware/**"],
     [("100 req/min per key", True), ("429 carries Retry-After", False), ("Limits are configurable", False)]),
    ("0007", "Transactional email templates", "low", "todo", None, [], ["src/mail/**"],
     [("Welcome email renders in plain text and HTML", False), ("Unsubscribe link is signed", False)]),
    ("0008", "Migrate database to Postgres", "high", "blocked", "codex-1", ["0003"], ["db/**", "src/payments/**"],
     [("Zero-downtime cutover rehearsed", False), ("Rollback script verified", False)]),
    ("0009", "API reference docs", "low", "done", None, ["0001"], ["docs/api/**"],
     [("Every endpoint has an example request", True), ("Docs build has no warnings", True)]),
    ("0010", "Harden the CI pipeline", "medium", "todo", None, [], [".github/**"],
     [("Pipeline fails on lint errors", False), ("Build is cached between runs", False)]),
]
AGENTS = {
    "claude-chief": ["orchestrator"], "claude-1": ["implementer"], "codex-1": ["implementer"],
    "cursor-1": ["implementer"], "claude-rev": ["reviewer"], "codex-rev": ["reviewer", "qa"],
}
NEW_TITLES = ["Webhook dashboard", "Audit log export", "Dark mode toggle", "Bulk CSV import", "Health check probes", "Cache warmup job"]


def _iso(moment: dt.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class DemoWorld:
    def __init__(self, seed: int = 11) -> None:
        self.rng = random.Random(seed)
        self.start = dt.datetime.now(dt.timezone.utc)
        self.last_tick = 0.0
        self.tasks: list[dict] = []
        self.events: list[dict] = []
        self.next_id = 11
        base = self.start - dt.timedelta(hours=6)
        for index, (tid, title, prio, status, owner, deps, locks, crit) in enumerate(TASKS):
            created = base + dt.timedelta(minutes=index * 7)
            self.tasks.append({
                "id": tid, "title": title, "priority": prio, "status": status, "owner": owner, "deps": deps, "locks": locks,
                "criteria": [list(c) for c in crit], "created": created, "updated": created + dt.timedelta(minutes=40 + index * 9),
                "submitted_by": "claude-1" if tid in ("0002", "0006") else None,
                "log": [(created, "claude-chief", "-", "todo", "created")],
            })
            self._emit("task_created", created, task=tid, agent="claude-chief")
            if status != "todo":
                self._emit("task_claimed", created + dt.timedelta(minutes=12), task=tid, agent=owner or "codex-1")
            if status == "done":
                self._emit("task_reviewed", created + dt.timedelta(minutes=50), task=tid, agent="claude-rev")
                self._emit("task_merged", created + dt.timedelta(minutes=52), task=tid, agent="claude-rev", branch=f"feature/{tid}")
                self._emit("task_done", created + dt.timedelta(minutes=53), task=tid, agent="claude-rev")
        self._emit("lock_refused", self.start - dt.timedelta(minutes=22), agent="cursor-1", task="0004", resource="src/api/**", conflict="src/api/**", conflict_agent="claude-1")
        self._emit("checkpoint", self.start - dt.timedelta(minutes=9), task="0003", agent="codex-1")
        self.events.sort(key=lambda e: e["timestamp"])
        self.lock_age = {"0003": 540, "0004": 1320, "0006": 210, "0002": 90}

    def _emit(self, name: str, when: dt.datetime, **fields) -> None:
        self.events.append({"timestamp": _iso(when), "event": name, **fields})

    # --- simulation ---------------------------------------------------------
    def tick(self, now_ts: float) -> list[dict]:
        """Advance the story every ~4 seconds. Returns the new events."""
        if now_ts - self.last_tick < 4.0:
            return []
        self.last_tick = now_ts
        before = len(self.events)
        now = dt.datetime.now(dt.timezone.utc)
        r = self.rng
        by_status = {s: [t for t in self.tasks if t["status"] == s] for s in STATUS_ORDER}
        done_ids = {t["id"] for t in by_status["done"]}
        choice = r.random()
        if choice < 0.40 and by_status["in_progress"]:
            task = r.choice(by_status["in_progress"])
            open_items = [c for c in task["criteria"] if not c[1]]
            if open_items:
                open_items[0][1] = True
                self._emit("checkpoint", now, task=task["id"], agent=task["owner"])
            else:
                task["status"], task["submitted_by"] = "review", task["owner"]
                task["owner"] = None
                self._emit("task_reviewed", now, task=task["id"], agent=task["submitted_by"])
        elif choice < 0.62 and by_status["review"]:
            task = r.choice(by_status["review"])
            reviewer = r.choice(["claude-rev", "codex-rev"])
            for c in task["criteria"]:
                c[1] = True
            task["status"], task["owner"] = "done", None
            self._emit("task_merged", now, task=task["id"], agent=reviewer, branch=f"feature/{task['id']}")
            self._emit("task_done", now, task=task["id"], agent=reviewer)
        elif choice < 0.85:
            ready = [t for t in by_status["todo"] + by_status["changes_requested"] if all(d in done_ids for d in t["deps"])]
            if ready:
                task = ready[0]
                worker = r.choice(["claude-1", "codex-1", "cursor-1"])
                task["status"], task["owner"] = "in_progress", worker
                self.lock_age[task["id"]] = 0
                self._emit("task_claimed", now, task=task["id"], agent=worker)
        elif choice < 0.92 and by_status["in_progress"]:
            task = r.choice(by_status["in_progress"])
            self._emit("lock_refused", now, agent=task["owner"], task=task["id"], resource="src/shared/**", conflict="src/shared/**", conflict_agent="codex-1")
        if len([t for t in self.tasks if t["status"] != "done"]) < 4:
            tid = f"{self.next_id:04d}"
            self.next_id += 1
            title = r.choice(NEW_TITLES)
            self.tasks.append({"id": tid, "title": title, "priority": r.choice(["low", "medium", "high"]), "status": "todo", "owner": None,
                               "deps": [], "locks": [f"src/{title.split()[0].lower()}/**"], "criteria": [[f"{title}: observable behaviour one", False], [f"{title}: failure case", False]],
                               "created": now, "updated": now, "submitted_by": None, "log": [(now, "claude-chief", "-", "todo", "created")]})
            self._emit("task_created", now, task=tid, agent="claude-chief")
        for task in self.tasks:
            if any(e.get("task") == task["id"] for e in self.events[before:]):
                task["updated"] = now
        return self.events[before:]

    # --- snapshot -----------------------------------------------------------
    def snapshot(self, role: str | None = None) -> dict:
        now = dt.datetime.now(dt.timezone.utc)
        done_ids = {t["id"] for t in self.tasks if t["status"] == "done"}
        tasks = []
        for t in self.tasks:
            crit = [(bool(d), text) for text, d in t["criteria"]]
            done_n = sum(1 for d, _ in crit if d)
            waiting = [d for d in t["deps"] if d not in done_ids]
            status = t["status"]
            log = [{"kind": "transition", "at": _iso(a), "actor": actor, "from": None if f == "-" else f, "to": to, "reason": reason, "evidence": ""}
                   for a, actor, f, to, reason in t["log"]]
            if status != "todo":
                log.append({"kind": "transition", "at": _iso(t["updated"]), "actor": t["owner"] or t["submitted_by"] or "claude-rev",
                            "from": "todo", "to": status, "reason": "demo", "evidence": ""})
            tasks.append({
                "id": t["id"], "title": t["title"], "status": status, "folder": "done" if status == "done" else "active",
                "owner": t["owner"], "priority": t["priority"], "spec_ref": f"specs/active/{t['id']}-spec.md", "spec": None,
                "depends_on": t["deps"], "waiting_on": ", ".join(waiting) if waiting else ("blocked " + ", ".join(t["deps"]) if status == "blocked" else "-"),
                "locks": t["locks"], "scope_allowed": [lk for lk in t["locks"]], "scope_forbidden": ["src/payments/**"] if t["id"] != "0003" else [],
                "branch": f"feature/{t['id']}-{t['title'].split()[0].lower()}" if status in ("in_progress", "review", "changes_requested", "done") else None,
                "worktree": None, "created": _iso(t["created"]), "updated": _iso(t["updated"]),
                "submitted_by": t["submitted_by"], "reviewed_by": "claude-rev" if status == "done" else None, "changes_requested_by": "codex-rev" if status == "changes_requested" else None,
                "age_seconds": (now - t["created"]).total_seconds(), "idle_seconds": (now - t["updated"]).total_seconds(),
                "criteria": crit, "criteria_done": done_n, "criteria_total": len(crit),
                "intent": SPEC_TEXT if t["id"] == "0002" else f"{t['title']}: what changes for users, and why now.",
                "plan": "1. write the failing tests\n2. implement behind the lock\n3. ai check, then ai task review", "notes": "",
                "log": log, "evidence": {"done": "green", "review": "green", "in_progress": "none", "changes_requested": "invalidated"}.get(status, "none"),
                "evidence_summary": "check passed @a3f9c21d by claude-1 (tests passed)" if status in ("review", "done") else "",
                "checkpoint_minutes": 9.0 if t["id"] == "0003" else (41.0 if t["id"] == "0004" else None), "stale_after": 3600,
            })
        order = {s: i for i, s in enumerate(LIST_ORDER)}
        tasks.sort(key=lambda t: (t["folder"] == "done", order.get(t["status"], 9), {"high": 0, "medium": 1, "low": 2}.get(t["priority"], 1), t["id"]))
        specs = [{
            "file": f"{t['id']}-spec.md", "folder": "done" if t["status"] == "done" else "active", "path": "", "ref": f"specs/active/{t['id']}-spec.md",
            "title": t["title"], "status": {"done": "shipped", "in_progress": "in progress", "review": "in progress", "changes_requested": "in progress"}.get(t["status"], "approved" if t["id"] < "0006" else "draft"),
            "task": t["id"], "approved_by": "you" if t["id"] < "0008" else None, "approved_on": None, "criteria": t["criteria"], "real_criteria": t["criteria"],
            "criteria_done": t["criteria_done"], "criteria_total": t["criteria_total"], "template": False, "intent": t["intent"],
            "changed": "Requests are validated before any side effect.\nErrors are JSON with a stable `code` field.", "out_of_scope": "Mobile clients, SSO, and billing UI.", "body": "",
        } for t in tasks]
        for spec in specs:
            spec["criteria"] = [(d, text) for d, text in spec["criteria"]]
            spec["real_criteria"] = spec["criteria"]
        counts = {s: sum(1 for t in tasks if t["status"] == s) for s in STATUS_ORDER}
        total = len(tasks)
        locks = []
        for t in self.tasks:
            if t["status"] in ("in_progress", "review", "changes_requested") and t["owner"]:
                for resource in t["locks"][:2]:
                    age = self.lock_age.get(t["id"], 120) + (now - self.start).total_seconds()
                    ttl = 1800
                    locks.append({"resource": resource, "agent": t["owner"], "task": t["id"], "ttl_seconds": ttl, "host": "demo",
                                  "remaining_seconds": int(max(0, ttl - age % ttl)), "state": "held", "started_at": _iso(now), "updated_at": _iso(now)})
        locks.append({"resource": "@git/index", "agent": "claude-1", "task": "0002", "ttl_seconds": 600, "host": "demo", "remaining_seconds": 420, "state": "held"})
        locks.append({"resource": "docs/old/**", "agent": "cursor-1", "task": "0004", "ttl_seconds": 1800, "host": "demo", "remaining_seconds": 0, "state": "stale"})
        refusals = [e for e in self.events if e["event"] == "lock_refused"][-6:]
        per_day = [self.rng.randint(0, 14) if i < 24 else 0 for i in range(28)]
        per_day = [max(0, (v if i % 6 else 0)) for i, v in enumerate(per_day)]
        per_day[-1] = sum(1 for _ in self.events)
        per_agent: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for e in self.events:
            if e.get("agent"):
                per_agent[e["agent"]] = per_agent.get(e["agent"], 0) + 1
            kinds[e["event"]] = kinds.get(e["event"], 0) + 1
        agents: list[dict[str, Any]] = []
        for name, roles in AGENTS.items():
            owned = [t["id"] for t in self.tasks if t["owner"] == name]
            reviews = [t["id"] for t in self.tasks if t["submitted_by"] == name and t["status"] in ("review", "changes_requested")]
            last = next((e for e in reversed(self.events) if e.get("agent") == name), None)
            idle = (now - dt.datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))).total_seconds() if last else None
            agents.append({"name": name, "roles": roles, "tasks": owned, "reviews": reviews, "locks": sum(1 for lock in locks if lock["agent"] == name),
                           "events": per_agent.get(name, 0), "last": last["timestamp"] if last else None, "last_event": last["event"] if last else None,
                           "checkpoints": 0, "idle_seconds": idle})
        agents.sort(key=lambda a: (-len(a["tasks"]), -a["events"], a["name"]))
        ready = [t for t in tasks if t["status"] in ("todo", "changes_requested") and t["waiting_on"] == "-"]
        reviews_q = [t for t in tasks if t["status"] == "review"]
        rec: dict[str, Any]
        if role == "reviewer" and reviews_q:
            rec = {"cmd": "ai task next --review --agent <n>", "why": f"{len(reviews_q)} task(s) wait for independent review; this claims the oldest"}
        elif role == "chief":
            rec = {"cmd": "ai status --board", "why": "the plan is in place; workers claim tasks themselves. Watch progress, unblock, answer questions"}
        elif ready:
            rec = {"cmd": "ai task next --agent <n>", "why": f"claims the highest-priority ready task ({ready[0]['id']} [{ready[0]['priority']}] {ready[0]['title']}) and sets everything up"}
        else:
            rec = {"cmd": None, "why": "nothing is ready; tell the user and stop (the chief plans new work)"}
        rec["extra"] = []
        return {
            "demo": True, "errors": [], "warnings": [], "taken_at": _iso(now), "load_ms": 3, "role": role,
            "config": {"mode": "strict", "name": "acme-shop", "agents": ["orchestrator", "planner", "implementer", "reviewer", "qa"],
                       "orchestration": {"maxParallel": 3}, "workflow": {"requireReview": True, "requireCheck": "strict", "requireSpec": True, "chiefOnlyTasks": True, "autoContinue": False},
                       "team": {n: {"roles": r} for n, r in AGENTS.items()}, "locks": {"defaultTtlSeconds": 1800, "staleAfterSeconds": 3600},
                       "budget": {"contextTokens": 200000, "warnAtPercent": 70}, "handoff": {"checkpointEveryMinutes": 20, "warnAfterMinutes": 30},
                       "testing": {"writeTests": True}, "language": {"documents": "en"}},
            "project": {"name": "acme-shop", "path": "~/code/acme-shop", "workspace": "~/code/acme-shop/.ai", "version": VERSION, "mode": "strict"},
            "git": {"repo": True, "branch": "feature/0004-product", "head": "a3f9c21d", "dirty": ["src/search/index.py", "src/search/rank.py"], "staged": [], "integration": "develop",
                    "production": "master", "isolation": "worktree", "merge": "no-ff", "ahead": 3, "branches": ["master", "develop", "feature/0004-product"],
                    "commits": [
                        {"hash": "a3f9c21", "author": "cursor-1", "when": "4 minutes ago", "subject": "feat(0004): rank results by recency and score", "refs": "HEAD -> feature/0004-product"},
                        {"hash": "9be0d47", "author": "codex-1", "when": "21 minutes ago", "subject": "feat(0003): verify webhook signatures", "refs": "feature/0003-payment"},
                        {"hash": "5c7a118", "author": "claude-rev", "when": "1 hour ago", "subject": "Merge task 0009 into develop", "refs": "develop"},
                        {"hash": "e41d9aa", "author": "claude-1", "when": "2 hours ago", "subject": "docs(0009): add example request per endpoint", "refs": ""},
                        {"hash": "0f2b6c3", "author": "claude-rev", "when": "3 hours ago", "subject": "Merge task 0001 into develop", "refs": "master"}]},
            "tasks": tasks, "specs": specs, "counts": counts, "total_tasks": total,
            "progress": counts["done"] / total, "progress_weighted": sum(STATUS_WEIGHT[t["status"]] for t in tasks) / total,
            "criteria": {"done": sum(t["criteria_done"] for t in tasks), "total": sum(t["criteria_total"] for t in tasks)},
            "locks": locks, "refusals": refusals,
            "checkpoints": [{"task": "0003", "agent": "codex-1", "reason": "periodic", "percent": 55, "age_minutes": 9.0, "next": "retry policy", "status": ""},
                            {"task": "0004", "agent": "cursor-1", "reason": "periodic", "percent": 40, "age_minutes": 41.0, "next": "rank", "status": ""}],
            "handoffs": [{"task": "0006", "agent": "claude-1", "reason": "context at 86%"}],
            "events": {"recent": self.events[-300:], "total": len(self.events), "per_day": per_day, "per_agent": per_agent, "kinds": kinds},
            "metrics": {"tasks_completed": counts["done"], "median_creation_to_done_seconds": 5400.0, "median_review_to_merge_seconds": 780.0,
                        "lock_refusals": kinds.get("lock_refused", 0), "retries": 2, "resumes": 1, "per_agent": per_agent},
            "decisions": [{"file": "0001-use-postgres.md", "title": "Use Postgres for orders", "status": "accepted"},
                          {"file": "0002-webhook-retries.md", "title": "Retry webhooks with backoff", "status": "proposed"}],
            "adapters": [{"name": "claude-code", "tool": "claude-code", "entry": "CLAUDE.md", "supports": ["auto-load"], "wired": True},
                         {"name": "codex", "tool": "codex", "entry": "AGENTS.md", "supports": ["auto-load"], "wired": True},
                         {"name": "cursor", "tool": "cursor", "entry": ".cursor/rules/ai-workspace.mdc", "supports": ["auto-load"], "wired": True},
                         {"name": "github-copilot", "tool": "github-copilot", "entry": ".github/copilot-instructions.md", "supports": ["auto-load"], "wired": False}],
            "agents": agents, "preferences": {"confirmed": True, "questions": [], "checks": ["tests", "lint"]}, "artifacts": 2,
            "now": {"recommended": rec}, "findings": [
                {"level": "warn", "message": "checkpoint for task 0004 is 41m old (limit 30m)", "hint": "ai checkpoint 0004 --agent cursor-1 --next \"<step>\""},
                {"level": "warn", "message": "docs/old/** lock is stale", "hint": "ai clean"}],
        }
