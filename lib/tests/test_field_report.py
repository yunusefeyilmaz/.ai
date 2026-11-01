"""Regressions from a real project run: chief-only tasks, no TTY, locks, specs, wording."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from test_start import WorkspaceCase, git, run


def set_workflow(workspace: Path, **values) -> None:
    path = workspace / "config" / "workspace.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["workflow"].update(values)
    path.write_text(json.dumps(config), encoding="utf-8")


class ChiefOnlyTest(WorkspaceCase):
    def strict_gate(self, workspace: Path) -> None:
        set_workflow(workspace, chiefOnlyTasks=True)

    def test_an_implementer_cannot_create_tasks(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.strict_gate(workspace)
        refused = run(workspace, "task", "new", "Sneaky", "--agent", "implementer-1")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("Only the chief creates tasks", refused.stderr)
        plan = workspace.parent / "p.json"
        plan.write_text(json.dumps({"tasks": [{"key": "a", "title": "A"}]}), encoding="utf-8")
        self.assertEqual(run(workspace, "plan", "apply", str(plan)).returncode, 1)

    def test_the_chief_must_ask_the_user_first(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.strict_gate(workspace)
        refused = run(workspace, "task", "new", "Too early", "--role", "chief")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("ai setup", refused.stderr)
        self.assertEqual(run(workspace, "setup", "--defaults").returncode, 0)
        self.assertEqual(run(workspace, "task", "new", "Planned", "--role", "chief").returncode, 0)

    def test_role_can_come_from_the_environment(self) -> None:
        import os

        workspace = self.make_workspace(git_repo=False)
        self.strict_gate(workspace)
        run(workspace, "setup", "--defaults")
        env = dict(os.environ, AI_ROLE="chief", PYTHONUTF8="1")
        result = subprocess.run(
            [os.sys.executable, str(workspace / "ai.py"), "task", "new", "Via env"],
            cwd=str(workspace), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ai_start_points_at_the_chief_not_at_task_new(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        out = run(workspace, "start", "--no-demo").stdout
        self.assertIn("you are the chief", out)
        self.assertNotIn("task new", out)


class GitWithoutTerminalTest(WorkspaceCase):
    def fresh_repo(self) -> Path:
        workspace = self.make_workspace(git_repo=False)
        git(workspace, "init", "-q", "-b", "main")
        git(workspace, "config", "user.name", "T")
        git(workspace, "config", "user.email", "t@example.com")
        return workspace

    def test_setup_without_a_terminal_explains_yes(self) -> None:
        workspace = self.fresh_repo()
        refused = run(workspace, "git", "setup")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--yes", refused.stderr)

    def test_setup_yes_commits_the_baseline_and_lists_files(self) -> None:
        workspace = self.fresh_repo()
        done = run(workspace, "git", "setup", "--yes")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("confirmed with --yes", done.stdout)
        branches = subprocess.run(["git", "branch", "--list"], cwd=str(workspace), capture_output=True, text=True).stdout
        self.assertIn("develop", branches)
        self.assertIn("master", branches)

    def test_setup_yes_refuses_secret_looking_files(self) -> None:
        workspace = self.fresh_repo()
        (workspace / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
        refused = run(workspace, "git", "setup", "--yes")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("secrets", refused.stderr)
        self.assertIn(".env", refused.stderr)


class DirtyTreeTest(WorkspaceCase):
    def test_carry_moves_uncommitted_files_onto_the_task_branch(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=yes", "tests=no")
        run(workspace, "task", "new", "Carry")
        run(workspace, "git", "setup", stdin="y\n")
        (workspace / "errors.txt").write_text("notes\n", encoding="utf-8")  # product file, untracked
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        self.assertIn("--carry", claimed.stdout + claimed.stderr)  # the refusal says how to proceed
        started = run(workspace, "git", "start", "--task", "0001", "--agent", "w1", "--carry")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertTrue((workspace / "errors.txt").exists())
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=str(workspace), capture_output=True, text=True).stdout.strip()
        self.assertTrue(branch.startswith("feature/0001"))


class LocksAndSpecsTest(WorkspaceCase):
    def test_task_new_allow_locks_those_paths_and_manual_locks_are_covered(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Site", "--allow", "server/**", "--allow", "public/**")
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertIn("file locks: server/**, public/**", claimed.stdout)
        covered = run(workspace, "lock", "acquire", "server/app.js", "--agent", "w1", "--task", "0001")
        self.assertEqual(covered.returncode, 0, covered.stderr)
        self.assertIn("already covered", covered.stdout)
        other = run(workspace, "lock", "acquire", "server/app.js", "--agent", "w2", "--task", "0001")
        self.assertEqual(other.returncode, 1)

    def test_explicit_lock_option(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Docs", "--allow", "docs/**", "--lock", "docs/guide.md")
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertIn("file locks: docs/guide.md", claimed.stdout)

    def test_done_frees_hand_taken_locks_and_archives_the_spec(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Ship it")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        for resource in ("package.json", "README.md"):
            self.assertEqual(run(workspace, "lock", "acquire", resource, "--agent", "w1", "--task", "0001").returncode, 0)
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "w1").returncode, 0)
        run(workspace, "task", "release", "0001", "--agent", "w1")
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "r1").returncode, 0)
        locks = run(workspace, "lock", "status").stdout
        self.assertNotIn("package.json", locks)
        self.assertNotIn("README.md", locks)
        self.assertEqual(list((workspace / "specs" / "active").glob("0001-*.md")), [])
        archived = list((workspace / "specs" / "done").glob("0001-*.md"))
        self.assertEqual(len(archived), 1)
        task = next((workspace / "tasks" / "done").glob("0001-*.md")).read_text(encoding="utf-8")
        self.assertIn("specs/done/", task)

    def test_review_frees_hand_taken_locks(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Deliver")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        run(workspace, "lock", "acquire", "notes.md", "--agent", "w1", "--task", "0001")
        run(workspace, "task", "review", "0001", "--agent", "w1")
        self.assertEqual(run(workspace, "lock", "acquire", "notes.md", "--agent", "w2").returncode, 0)


class WordingTest(WorkspaceCase):
    def test_evidence_line_does_not_look_like_a_test_count(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        set_cfg = workspace / "config" / "workspace.json"
        config = json.loads(set_cfg.read_text(encoding="utf-8"))
        config["checks"] = [{"name": "unit", "command": 'python -c "print(8)"'}]
        set_cfg.write_text(json.dumps(config), encoding="utf-8")
        run(workspace, "task", "new", "Wording")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        checked = run(workspace, "check", "--task", "0001", "--agent", "w1")
        self.assertIn("unit passed", checked.stderr)
        self.assertNotIn("unit=0", checked.stderr)

    def test_setup_answers_are_confirmed_briefly(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        out = run(workspace, "setup", "--set", "review=yes", "git=no", "checks=no", "tests=yes").stdout
        self.assertIn("Saved to config/workspace.json: review=yes", out)
        self.assertNotIn("Should finished work be reviewed", out)  # no questionnaire replay

    def test_now_after_claim_points_at_the_work_not_at_check(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "setup", "--defaults")
        run(workspace, "task", "new", "Early")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        out = run(workspace, "now", "--agent", "w1").stdout
        self.assertIn("nothing is committed yet", out)


if __name__ == "__main__":
    unittest.main()
