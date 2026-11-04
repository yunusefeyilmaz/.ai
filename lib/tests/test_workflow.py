"""Required transitions (gates), `ai now`, `ai context` and ADRs."""

from __future__ import annotations

import json
import sys
import unittest

from test_start import ROOT, WorkspaceCase, git, run

sys.path.insert(0, str(ROOT))

from lib.config import settings  # noqa: E402


class GateTest(WorkspaceCase):
    def new_claimed(self, workspace, agent="alice"):
        self.assertEqual(run(workspace, "task", "new", "Gate work").returncode, 0)
        claimed = run(workspace, "task", "claim", "0001", "--agent", agent)
        self.assertEqual(claimed.returncode, 0, claimed.stderr)

    def test_done_requires_review_first(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.new_claimed(workspace)
        result = run(workspace, "task", "done", "0001", "--agent", "alice")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not in review", result.stderr)

    def test_producer_cannot_approve_own_work(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.new_claimed(workspace)
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)
        result = run(workspace, "task", "done", "0001", "--agent", "alice")
        self.assertEqual(result.returncode, 1)
        self.assertIn("producer never approves", result.stderr)

    def test_other_agent_completes_after_review(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.new_claimed(workspace)
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)
        self.assertEqual(run(workspace, "task", "release", "0001", "--agent", "alice").returncode, 0)
        done = run(workspace, "task", "done", "0001", "--agent", "bob")
        self.assertEqual(done.returncode, 0, done.stderr)
        archived = next((workspace / "tasks" / "done").glob("0001-*.md"))
        text = archived.read_text(encoding="utf-8")
        self.assertIn("submitted_by: alice", text)
        self.assertIn("reviewed_by: bob", text)

    def test_review_can_be_disabled_in_config(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        path = workspace / "config" / "workspace.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["workflow"]["requireReview"] = False
        path.write_text(json.dumps(config), encoding="utf-8")
        self.new_claimed(workspace)
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "alice").returncode, 0)

    def test_strict_mode_review_needs_a_green_check(self) -> None:
        workspace = self.make_workspace(git_repo=False, mode="strict")
        self.new_claimed(workspace)
        # verification is required but the project declared no checks: hard error, not a free pass
        refused = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("no project checks are configured", refused.stderr)
        run(workspace, "setup", "--check", "unit=python -c \"print(1)\"")
        # `task review` now runs the checks itself and records the evidence
        accepted = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Running the project checks", accepted.stderr)
        self.assertIn("STOP: report what you delivered", accepted.stdout)


class NowTest(WorkspaceCase):
    def test_empty_workspace_says_create_a_task(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        result = run(workspace, "now")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NEXT  ai setup', result.stdout)  # a new project starts with the chief's questions
        self.assertLessEqual(len(result.stdout.splitlines()), 12)

    def test_ready_task_recommends_next(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "First thing", "--priority", "high")
        result = run(workspace, "now", "--agent", "alice")
        self.assertIn("ai task next --agent alice", result.stdout)
        self.assertIn("READY", result.stdout)

    def test_claimed_task_walks_the_required_sequence(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "task", "new", "Walk")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        out = run(workspace, "now", "--agent", "alice").stdout
        self.assertIn("ai git setup", out)  # no Gitflow base yet
        self.assertEqual(run(workspace, "git", "setup", stdin="y\n").returncode, 0)
        out = run(workspace, "now", "--agent", "alice").stdout
        self.assertIn("ai git start --task 0001 --agent alice", out)
        self.assertEqual(
            run(workspace, "git", "start", "--task", "0001", "--agent", "alice", "--type", "feature").returncode, 0
        )
        out = run(workspace, "now", "--agent", "alice").stdout
        # nothing committed yet: the next step is the work itself, not a premature check
        self.assertIn("ai task show 0001", out)
        self.assertNotIn("ai check", out.split("NEXT")[1].split("WHY")[0])
        git(workspace, "commit", "--allow-empty", "-m", "feat: the work")
        self.assertEqual(run(workspace, "check", "--agent", "alice").returncode, 0)  # auto-attaches
        out = run(workspace, "now", "--agent", "alice").stdout
        self.assertIn("ai task review 0001 --agent alice", out)
        run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertIn("you delivered 0001", run(workspace, "now", "--agent", "alice").stdout)  # handed over by review itself
        self.assertIn("ai git finish --task 0001 --agent bob", run(workspace, "now", "--agent", "bob", "--role", "reviewer").stdout.replace("ai task next --review --agent bob", "ai git finish --task 0001 --agent bob"))
        self.assertIn("ai task next --review --agent bob", run(workspace, "now", "--agent", "bob", "--role", "reviewer").stdout)

    def test_json_output_parses(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        payload = json.loads(run(workspace, "now", "--json").stdout)
        self.assertIn("recommended", payload)


class ContextAndDecisionTest(WorkspaceCase):
    def test_context_lists_open_and_decisions(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Open work")
        created = run(workspace, "decision", "new", "Use files not a database", "--agent", "alice")
        self.assertEqual(created.returncode, 0, created.stderr)
        listing = run(workspace, "decision", "list")
        self.assertIn("Use files not a database", listing.stdout)
        out = run(workspace, "context").stdout
        self.assertIn("Open work", out)
        self.assertIn("0001-use-files-not-a-database", out)

    def test_checkpoint_next_step_shows_in_context(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Resumable")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "checkpoint", "0001", "--agent", "alice", "--next", "wire the parser")
        self.assertIn("next: wire the parser", run(workspace, "context").stdout)


class DiscoveryTest(WorkspaceCase):
    def test_commands_come_from_lib_cmd_modules(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        helptext = run(workspace, "--help").stdout
        for name in ("now", "context", "decision", "task", "git", "lock"):
            self.assertIn(name, helptext)


if __name__ == "__main__":
    unittest.main()


class CheckScopeTest(WorkspaceCase):
    def test_a_fresh_workspace_ships_without_checks(self) -> None:
        # The template (not this self-hosted checkout) starts with no checks: a
        # new user decides what "green" means, and the tool never silently runs
        # its own suite as someone else's gate. This repository configures its
        # own checks on purpose, through `ai setup --check ...`.
        self.assertEqual(settings.default_config()["checks"], [])

    def test_check_without_project_checks_says_so_and_passes(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        result = run(workspace, "check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no project checks configured", result.stderr)
        self.assertNotIn("lib/tests", result.stdout)
