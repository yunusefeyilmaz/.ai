"""Per-task Git worktrees: parallel workers in isolated checkouts, one shared workspace."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

from test_start import WorkspaceCase, run


def git_out(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def git_do(cwd, *args) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


class WorktreeCase(WorkspaceCase):
    def parallel_workspace(self, *titles, checks=None):
        workspace = self.make_workspace()
        setup = ["--set", "review=yes", "checks=%s" % ("yes" if checks else "no"), "git=yes", "tests=no", "workers=2"]
        args = ["setup", *setup] + (["--check", checks] if checks else [])
        self.assertEqual(run(workspace, *args).returncode, 0)
        for title in titles or ("First",):
            self.assertEqual(run(workspace, "task", "new", title, "--allow", f"src/{title.lower()}/**").returncode, 0)
        self.assertEqual(run(workspace, "git", "setup", stdin="y\n").returncode, 0)
        return workspace

    def worktree_of(self, workspace, task="0001") -> Path:
        result = run(workspace, "worktree", "path", task)
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip())

    def commit_file(self, workspace, task, agent, relative, text="x\n"):
        root = self.worktree_of(workspace, task)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git_do(root, "add", relative)
        self.assertEqual(run(workspace, "lock", "acquire", relative, "--agent", agent, "--task", task).returncode, 0)
        committed = run(workspace, "git", "commit", "--task", task, "--agent", agent, "--type", "feat", "--message", f"add {relative}")
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)


class IsolationTest(WorktreeCase):
    def test_setup_with_several_workers_switches_to_worktrees(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "setup", "--set", "workers=3")
        config = json.loads((workspace / "config" / "workspace.json").read_text(encoding="utf-8"))
        self.assertEqual(config["git"]["isolation"], "worktree")
        run(workspace, "setup", "--set", "workers=1")
        config = json.loads((workspace / "config" / "workspace.json").read_text(encoding="utf-8"))
        self.assertEqual(config["git"]["isolation"], "branch")

    def test_claim_creates_an_isolated_checkout_and_keeps_main_clean(self) -> None:
        workspace = self.parallel_workspace()
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)
        self.assertIn("worktree:", claimed.stdout)
        root = self.worktree_of(workspace)
        self.assertTrue(root.is_dir())
        self.assertEqual(root.parent.name, "worktrees")
        self.assertTrue(git_out(root, "branch", "--show-current").startswith("feature/0001"))
        # the main checkout did not move and sees no trace of the worktree
        self.assertIn(git_out(workspace, "branch", "--show-current"), ("master", "main", "develop"))
        self.assertNotIn("worktrees", git_out(workspace, "status", "--porcelain"))
        # the briefing tells the agent how to reach the shared workspace
        self.assertIn("ai.py", (root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(git_out(root, "status", "--porcelain"), "")  # briefing files are excluded
        self.assertIn("cd ", run(workspace, "now", "--agent", "w1").stdout)

    def test_two_workers_commit_to_their_own_branches_at_the_same_time(self) -> None:
        workspace = self.parallel_workspace("Alpha", "Beta")
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)
        self.assertEqual(run(workspace, "task", "claim", "0002", "--agent", "w2").returncode, 0)
        self.assertNotEqual(self.worktree_of(workspace, "0001"), self.worktree_of(workspace, "0002"))
        self.commit_file(workspace, "0001", "w1", "src/alpha/a.py")
        self.commit_file(workspace, "0002", "w2", "src/beta/b.py")
        b1 = git_out(workspace, "branch", "--list", "--format=%(refname:short)", "feature/0001*")
        b2 = git_out(workspace, "branch", "--list", "--format=%(refname:short)", "feature/0002*")
        self.assertIn("add src/alpha/a.py", git_out(workspace, "log", "-1", "--format=%s", b1))
        self.assertIn("add src/beta/b.py", git_out(workspace, "log", "-1", "--format=%s", b2))
        self.assertEqual(git_out(workspace, "ls-tree", "-r", "--name-only", b1).count("src/beta"), 0)
        listing = run(workspace, "worktree", "list").stdout
        self.assertIn("task 0001", listing)
        self.assertIn("task 0002", listing)

    def test_scope_is_enforced_inside_the_worktree(self) -> None:
        workspace = self.parallel_workspace("Alpha")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        root = self.worktree_of(workspace)
        (root / "src" / "other").mkdir(parents=True)
        (root / "src" / "other" / "x.py").write_text("x\n", encoding="utf-8")
        git_do(root, "add", "src/other/x.py")
        verified = run(workspace, "git", "verify", "--task", "0001")
        self.assertEqual(verified.returncode, 1)
        self.assertIn("outside allowed scope", verified.stdout)


class DeliveryTest(WorktreeCase):
    def test_review_checks_the_worktree_and_finish_merges_then_cleans_up(self) -> None:
        marker = 'python -c "import os, sys; sys.exit(0 if os.path.isfile(\'src/alpha/MARKER\') else 1)"'
        workspace = self.parallel_workspace("Alpha", checks=f"marker={marker}")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        # the marker exists only on the task branch, so the check passes only inside the worktree
        self.commit_file(workspace, "0001", "w1", "src/alpha/MARKER")
        self.assertFalse((workspace / "src" / "alpha" / "MARKER").exists())
        review = run(workspace, "task", "review", "0001", "--agent", "w1")
        self.assertEqual(review.returncode, 0, review.stdout + review.stderr)
        self.assertIn("Running the project checks", review.stderr)
        run(workspace, "task", "release", "0001", "--agent", "w1")
        root = self.worktree_of(workspace)
        finished = run(workspace, "git", "finish", "--task", "0001", "--agent", "r1")
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        self.assertFalse(root.exists())
        self.assertEqual(git_out(workspace, "branch", "--show-current"), "develop")
        self.assertTrue((workspace / "src" / "alpha" / "MARKER").exists())
        self.assertEqual(git_out(workspace, "branch", "--list", "feature/0001*"), "")
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "r1").returncode, 0)
        self.assertIn("No task worktrees", run(workspace, "worktree", "list").stdout)

    def test_finish_refuses_uncommitted_work_in_the_worktree(self) -> None:
        workspace = self.parallel_workspace("Alpha")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        root = self.worktree_of(workspace)
        (root / "unfinished.txt").write_text("wip\n", encoding="utf-8")
        run(workspace, "task", "review", "0001", "--agent", "w1")
        run(workspace, "task", "release", "0001", "--agent", "w1")
        refused = run(workspace, "git", "finish", "--task", "0001", "--agent", "r1")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("uncommitted changes", refused.stderr)
        self.assertTrue(root.exists())


class HostLayoutTest(WorktreeCase):
    """`.ai` installed inside a host project: worktrees live in `.ai/worktrees/`."""

    def test_worktrees_inside_a_host_project_do_not_dirty_it(self) -> None:
        import shutil
        import tempfile

        from test_start import COPY_IGNORE, ROOT

        host = Path(tempfile.mkdtemp(prefix="ai-host-"))
        self.addCleanup(shutil.rmtree, host, True)
        git_do(host, "init", "-q", "-b", "main")
        git_do(host, "config", "user.email", "t@example.com")
        git_do(host, "config", "user.name", "Tester")
        (host / "src").mkdir()
        (host / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
        git_do(host, "add", "-A")
        git_do(host, "commit", "-qm", "init")
        workspace = host / ".ai"
        shutil.copytree(ROOT, workspace, ignore=COPY_IGNORE)
        for sub in ("locks", "state", "artifacts", "logs"):
            shutil.rmtree(workspace / "runtime" / sub, ignore_errors=True)
        self.assertEqual(run(workspace, "adopt").returncode, 0)
        git_do(host, "add", ".gitignore")
        git_do(host, "commit", "-qm", "ignore the workspace")
        self.assertEqual(run(workspace, "setup", "--set", "review=yes", "checks=no", "git=yes", "tests=no", "workers=2").returncode, 0)
        self.assertEqual(run(workspace, "task", "new", "Hosted", "--allow", "src/**").returncode, 0)
        self.assertEqual(run(workspace, "git", "setup", stdin="y\n").returncode, 0)
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)
        root = Path(run(workspace, "worktree", "path", "0001").stdout.strip())
        self.assertEqual(root.parent, workspace / "worktrees")
        self.assertTrue((root / "src" / "app.py").exists())          # a real checkout of the host
        self.assertFalse((root / ".ai").exists())                      # the workspace is not duplicated
        self.assertEqual(git_out(host, "status", "--porcelain"), "")   # the host stays clean
        self.assertEqual(git_out(root, "status", "--porcelain"), "")   # so does the worktree
        # a worker inside the worktree reaches the shared workspace by absolute path
        inside = subprocess.run(
            [os.sys.executable, str(workspace / "ai.py"), "now", "--agent", "w1"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(inside.returncode, 0, inside.stderr)
        self.assertIn("0001 in_progress (w1)", inside.stdout)


class CleanupTest(WorktreeCase):
    def test_orphan_worktrees_are_reported_and_pruned(self) -> None:
        workspace = self.parallel_workspace("Alpha")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        root = self.worktree_of(workspace)
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "boss", "--force").returncode, 0)
        self.assertIn("has no active task", run(workspace, "doctor").stdout)
        pruned = run(workspace, "worktree", "prune")
        self.assertEqual(pruned.returncode, 0, pruned.stderr)
        self.assertFalse(root.exists())
        self.assertNotIn("has no active task", run(workspace, "doctor").stdout)

    def test_prune_keeps_worktrees_with_uncommitted_changes(self) -> None:
        workspace = self.parallel_workspace("Alpha")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        root = self.worktree_of(workspace)
        (root / "precious.txt").write_text("keep me\n", encoding="utf-8")
        run(workspace, "task", "done", "0001", "--agent", "boss", "--force")
        kept = run(workspace, "worktree", "prune")
        self.assertIn("uncommitted changes", kept.stderr)
        self.assertTrue((root / "precious.txt").exists())


if __name__ == "__main__":
    unittest.main()
