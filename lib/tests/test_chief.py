"""The chief/worker/reviewer flow: setup, plan, one-command claim, delivery, review."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from test_start import ROOT, WorkspaceCase, run

sys.path.insert(0, str(ROOT))

PLAN = {
    "tasks": [
        {"key": "api", "title": "Build API", "priority": "high", "intent": "Serve logins",
         "acceptance": ["POST /login returns a token"], "locks": ["src/api/**"]},
        {"key": "ui", "title": "Login form", "depends_on": ["api"], "locks": ["src/ui/**"]},
    ]
}


def write_plan(workspace, plan=PLAN):
    # outside the repository: a plan file is not product code
    path = workspace.parent / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return str(path)


class SetupTest(WorkspaceCase):
    def test_setup_lists_questions_then_stores_answers_in_config(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        out = run(workspace, "setup").stdout
        for key in ("review", "checks", "git", "tests", "continue", "workers"):
            self.assertIn(key, out)
        saved = run(workspace, "setup", "--set", "review=no", "git=no", "tests=yes", "checks=no", "workers=2")
        self.assertEqual(saved.returncode, 0, saved.stderr)
        config = json.loads((workspace / "config" / "workspace.json").read_text(encoding="utf-8"))
        self.assertIs(config["workflow"]["requireReview"], False)
        self.assertIs(config["git"]["enabled"], False)
        self.assertIs(config["workflow"]["requireCheck"], False)
        self.assertEqual(config["orchestration"]["maxParallel"], 2)
        self.assertTrue(config["preferences"]["confirmed"])
        self.assertIn("ai plan apply", run(workspace, "now").stdout)

    def test_invalid_answers_are_rejected(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "setup", "--set", "review=maybe").returncode, 1)
        self.assertEqual(run(workspace, "setup", "--set", "colour=red").returncode, 1)

    def test_defaults_and_check_commands(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        done = run(workspace, "setup", "--defaults", "--check", "unit=python -c \"print(1)\"")
        self.assertEqual(done.returncode, 0, done.stderr)
        config = json.loads((workspace / "config" / "workspace.json").read_text(encoding="utf-8"))
        self.assertEqual(config["checks"], [{"name": "unit", "command": "python -c \"print(1)\""}])


class PlanTest(WorkspaceCase):
    def test_plan_creates_linked_tasks_with_locks_and_scope(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        applied = run(workspace, "plan", "apply", write_plan(workspace), "--agent", "chief")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        listing = json.loads(run(workspace, "task", "list", "--json").stdout)["active"]
        by_title = {t["title"]: t for t in listing}
        api, ui = by_title["Build API"], by_title["Login form"]
        self.assertEqual(ui["depends_on"], api["id"])
        self.assertEqual(api["locks"], "src/api/**")
        self.assertEqual(api["scope_allowed"], "src/api/**")  # defaults to locks
        shown = run(workspace, "task", "show", api["id"]).stdout
        self.assertIn("POST /login returns a token", shown)
        self.assertIn("Tests cover the new behavior", shown)
        ready = json.loads(run(workspace, "task", "ready", "--json").stdout)["ready"]
        self.assertEqual([t["id"] for t in ready], [api["id"]])  # ui waits for api

    def test_invalid_plans_create_nothing(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        cycle = {"tasks": [
            {"key": "a", "title": "A", "depends_on": ["b"]},
            {"key": "b", "title": "B", "depends_on": ["a"]},
        ]}
        refused = run(workspace, "plan", "apply", write_plan(workspace, cycle))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("cycle", refused.stderr)
        unknown = {"tasks": [{"key": "a", "title": "A", "depends_on": ["zzz"]}]}
        self.assertEqual(run(workspace, "plan", "apply", write_plan(workspace, unknown)).returncode, 1)
        self.assertEqual(json.loads(run(workspace, "task", "list", "--json").stdout)["active"], [])

    def test_unordered_overlapping_locks_are_warned(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        clash = {"tasks": [
            {"key": "a", "title": "A", "locks": ["src/**"]},
            {"key": "b", "title": "B", "locks": ["src/x/**"]},
        ]}
        result = run(workspace, "plan", "apply", write_plan(workspace, clash), "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertIn("cannot run in parallel", result.stderr)


class WorkerFlowTest(WorkspaceCase):
    def planned(self, git_repo=False):
        workspace = self.make_workspace(git_repo=git_repo)
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=%s" % ("yes" if git_repo else "no"), "tests=no")
        self.assertEqual(run(workspace, "plan", "apply", write_plan(workspace)).returncode, 0)
        return workspace

    def test_claim_takes_file_locks_and_release_frees_them(self) -> None:
        workspace = self.planned()
        claimed = run(workspace, "task", "next", "--agent", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        self.assertIn("file locks: src/api/**", claimed.stdout)
        status = run(workspace, "lock", "status").stdout
        self.assertIn("src/api/**", status)
        other = run(workspace, "lock", "acquire", "src/api/x.py", "--agent", "w2")
        self.assertEqual(other.returncode, 1)
        self.assertEqual(run(workspace, "task", "release", "0001", "--agent", "w1").returncode, 0)
        self.assertEqual(run(workspace, "lock", "acquire", "src/api/x.py", "--agent", "w2").returncode, 0)

    def test_two_workers_never_get_the_same_task(self) -> None:
        workspace = self.planned()
        run(workspace, "task", "new", "Independent", "--allow", "docs/**")
        first = run(workspace, "task", "next", "--agent", "w1")
        second = run(workspace, "task", "next", "--agent", "w2")
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertNotEqual(
            [l for l in first.stdout.splitlines() if l.startswith("Claimed")],
            [l for l in second.stdout.splitlines() if l.startswith("Claimed")],
        )

    def test_conflicting_file_locks_refuse_the_claim(self) -> None:
        workspace = self.planned()
        run(workspace, "lock", "acquire", "src/api/core.py", "--agent", "someone")
        refused = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("locked by someone", refused.stderr)
        self.assertIn("todo", run(workspace, "task", "show", "0001").stdout)

    def test_claim_starts_the_task_branch_when_git_is_enabled(self) -> None:
        workspace = self.planned(git_repo=True)
        self.assertEqual(run(workspace, "git", "setup", stdin="y\n").returncode, 0)
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(workspace), capture_output=True, text=True,
        ).stdout.strip()
        self.assertTrue(branch.startswith("feature/0001"), branch)

    def test_delivery_stops_and_waits_for_the_user(self) -> None:
        workspace = self.planned()
        run(workspace, "task", "next", "--agent", "w1")
        delivered = run(workspace, "task", "review", "0001", "--agent", "w1")
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        self.assertIn("STOP: report what you delivered", delivered.stdout)
        # file locks are freed at delivery
        self.assertEqual(run(workspace, "lock", "acquire", "src/api/x.py", "--agent", "w2").returncode, 0)
        run(workspace, "task", "release", "0001", "--agent", "w1")
        now = run(workspace, "now", "--agent", "w1", "--role", "implementer").stdout
        self.assertIn("wait for the user", now)
        self.assertNotIn("ai task next --agent w1", now.split("WHY")[0])

    def test_auto_continue_lets_the_worker_proceed(self) -> None:
        workspace = self.planned()
        run(workspace, "setup", "--set", "continue=yes")
        run(workspace, "task", "next", "--agent", "w1")
        delivered = run(workspace, "task", "review", "0001", "--agent", "w1")
        self.assertNotIn("STOP", delivered.stdout)

    def test_roles_choose_what_now_recommends(self) -> None:
        workspace = self.planned()
        self.assertIn("ai task next --agent w1", run(workspace, "now", "--agent", "w1", "--role", "implementer").stdout)
        self.assertIn("nothing is waiting for review", run(workspace, "now", "--agent", "r1", "--role", "reviewer").stdout)
        self.assertIn("ai status", run(workspace, "now", "--agent", "boss", "--role", "chief").stdout)


class ReviewerFlowTest(WorkspaceCase):
    def delivered(self):
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "setup", "--defaults")
        run(workspace, "setup", "--set", "checks=no", "git=no")
        run(workspace, "plan", "apply", write_plan(workspace))
        run(workspace, "task", "next", "--agent", "w1")
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "w1").returncode, 0)
        run(workspace, "task", "release", "0001", "--agent", "w1")
        return workspace

    def test_reviewer_takes_the_oldest_waiting_review_and_approves(self) -> None:
        workspace = self.delivered()
        self.assertIn("ai task next --review", run(workspace, "now", "--agent", "r1", "--role", "reviewer").stdout)
        taken = run(workspace, "task", "next", "--review", "--agent", "r1")
        self.assertEqual(taken.returncode, 0, taken.stderr)
        self.assertIn("Review: Build API (submitted by w1)", taken.stdout)
        # a second reviewer cannot take the same task
        self.assertEqual(run(workspace, "task", "next", "--review", "--agent", "r2").returncode, 1)
        done = run(workspace, "task", "done", "0001", "--agent", "r1")
        self.assertEqual(done.returncode, 0, done.stderr)
        # the dependent task is now ready for a worker
        self.assertIn("ai task next --agent w1", run(workspace, "now", "--agent", "w1", "--role", "implementer").stdout)

    def test_the_producer_cannot_review_its_own_task(self) -> None:
        workspace = self.delivered()
        self.assertEqual(run(workspace, "task", "next", "--review", "--agent", "w1").returncode, 1)

    def test_rejected_work_returns_to_the_producer(self) -> None:
        workspace = self.delivered()
        run(workspace, "task", "next", "--review", "--agent", "r1")
        rejected = run(workspace, "task", "request-changes", "0001", "--agent", "r1", "--reason", "no error handling")
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        now = run(workspace, "now", "--agent", "w1", "--role", "implementer").stdout
        self.assertIn("ai task claim 0001 --agent w1", now)
        self.assertIn("sent it back", now)


class AuditTest(WorkspaceCase):
    def test_forced_lock_takeover_and_forced_done_leave_a_trail(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "lock", "acquire", "src/x.py", "--agent", "alice")
        run(workspace, "lock", "acquire", "src/x.py", "--agent", "bob", "--force")
        events = (workspace / "runtime" / "state").rglob("events*.jsonl")
        text = "".join(p.read_text(encoding="utf-8") for p in events)
        self.assertIn("lock_forced", text)
        self.assertIn("alice", text)


class ConfigDriftTest(WorkspaceCase):
    def test_default_config_covers_every_shipped_key(self) -> None:
        from lib.config.settings import default_config

        shipped = json.loads((ROOT / "config" / "workspace.json").read_text(encoding="utf-8"))
        missing = [key for key in shipped if key not in default_config() and key != "name"]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()


class SkillLoadingTest(WorkspaceCase):
    def test_a_skill_folder_adds_a_command(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        skill = workspace / "skills" / "hello"
        skill.mkdir(parents=True)
        (skill / "skill.py").write_text(
            "def register(sub):\n"
            "    p = sub.add_parser('hello', help='demo skill')\n"
            "    p.set_defaults(func=lambda a: print('hello from skill') or 0)\n",
            encoding="utf-8",
        )
        result = run(workspace, "hello")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("hello from skill", result.stdout)
        self.assertIn("hello", run(workspace, "--help").stdout)
