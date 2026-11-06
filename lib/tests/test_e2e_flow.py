"""End to end: an existing repository through the whole v1.0.0 flow.

The unit suites cover each command in isolation. This test is the only one that
puts onboarding, the check gate and the acceptance-criteria gate together on a
real host repository with pre-existing Git history (``.ai/`` installed as a
subfolder, exactly like a user adopting an existing project):

    adopt -> setup -> plan -> claim -> checkpoint -> tick -> commit -> check
          -> review (refused while a criterion is unticked) -> review
          -> git finish -> task done

It pins the three regressions that used to slip through silently: onboarding
must leave HEAD on ``develop``, the configured check must really run, and a
criterion left unticked must keep the task out of review. The final archive
must say ``shipped`` with every box ticked and the working tree must be clean.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _workspace import _normalise, copy_project

ROOT = Path(__file__).resolve().parents[2]
BASELINE_MESSAGE = "chore: add ai workspace baseline"


def run(host: Path, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # The host's disposable copy may reuse .pyc files across CLI calls.
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return subprocess.run(
        [sys.executable, str(host / ".ai" / "ai.py"), *args],
        cwd=str(host),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


def git(host: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(host),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def git_ok(host: Path, *args: str) -> str:
    result = git(host, *args)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr or result.stdout}")
    return result.stdout.strip()


class ExistingRepoE2ETest(unittest.TestCase):
    def make_host(self) -> Path:
        """A pre-existing project with Git history and then a `.ai/` subfolder."""
        temp = Path(tempfile.mkdtemp(prefix="ai-e2e-existing-"))
        self.addCleanup(shutil.rmtree, temp, True)
        host = temp / "project"
        host.mkdir()
        (host / "README.md").write_text("# Existing project\n", encoding="utf-8")
        (host / "app.py").write_text("print('existing product')\n", encoding="utf-8")
        (host / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

        self.assertEqual(git(host, "init", "-q", "--initial-branch", "master").returncode, 0)
        git_ok(host, "config", "user.name", "E2E Test")
        git_ok(host, "config", "user.email", "e2e@example.test")
        git_ok(host, "add", "-A")
        git_ok(host, "commit", "-qm", "product baseline")

        copy_project(host / ".ai")
        shutil.rmtree(host / ".ai" / "runtime" / "temp", ignore_errors=True)
        # A newly adopted host has no task history yet: start from an empty
        # ledger so the planned task is 0001.
        _normalise(host / ".ai", "lite", None)
        config_path = host / ".ai" / "config" / "workspace.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.setdefault("workflow", {})["requireSpec"] = True
        config.setdefault("preferences", {})["confirmed"] = False
        config["preferences"]["answered"] = []
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return host

    def test_existing_repo_runs_the_full_flow(self) -> None:
        host = self.make_host()
        marker = host.parent / "e2e-check-ran.txt"
        self.assertFalse(marker.exists(), "the check must create the marker, not the fixture")

        # 1. Onboarding an existing repository: `.ai/` and .gitignore are
        #    committed on the integration branch and HEAD moves there.
        adopted = run(host, "adopt")
        self.assertEqual(adopted.returncode, 0, adopted.stderr + adopted.stdout)
        self.assertEqual(git_ok(host, "rev-parse", "--abbrev-ref", "HEAD"), "develop")
        self.assertEqual(git_ok(host, "status", "--porcelain"), "")

        # 2. The chief stores the workflow answers and the project's check.
        #    The check writes a file outside the repository, so the marker can
        #    prove later that the gate really executed it.
        inner = (
            "import pathlib, sys; "
            "pathlib.Path(sys.argv[1]).write_text('ran', encoding='utf-8')"
        )
        check_command = f'"{sys.executable}" -c "{inner}" "{marker.as_posix()}"'
        setup = run(
            host, "setup", "--set",
            "review=yes", "checks=yes", "git=yes", "tests=no", "continue=no", "workers=1",
            "--check", f"e2e={check_command}",
        )
        self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
        self.assertEqual(git_ok(host, "rev-parse", "--abbrev-ref", "HEAD"), "develop")

        # `ai setup` writes config after the first baseline; running the
        # idempotent adopt again records those answers as part of the workspace
        # baseline instead of leaving them dirty for the rest of the task.
        rebased = run(host, "adopt")
        self.assertEqual(rebased.returncode, 0, rebased.stderr + rebased.stdout)
        self.assertEqual(git_ok(host, "rev-parse", "--abbrev-ref", "HEAD"), "develop")
        self.assertEqual(git_ok(host, "status", "--porcelain"), "")

        # 3. The chief plans one concrete task with a file lock and two
        #    observable criteria (no automatic "write tests" criterion).
        plan = host.parent / "plan.json"
        plan.write_text(
            json.dumps({"tasks": [{
                "key": "feature",
                "title": "Ship the existing-repo feature",
                "priority": "high",
                "intent": "Prove an existing repository can run the whole flow.",
                "acceptance": [
                    "the feature file exists in the merged tree",
                    "the configured check command really ran",
                ],
                "locks": ["feature.txt"],
                "tests": False,
            }]}),
            encoding="utf-8",
        )
        applied = run(host, "plan", "apply", str(plan), "--agent", "chief", "--role", "chief")
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        self.assertIn("0001", applied.stdout)

        # 4. Claim opens the task branch and takes the declared lock.
        claimed = run(host, "task", "claim", "0001", "--agent", "worker")
        self.assertEqual(claimed.returncode, 0, claimed.stderr + claimed.stdout)
        branch = git_ok(host, "rev-parse", "--abbrev-ref", "HEAD")
        self.assertTrue(branch.startswith("feature/0001-"), branch)

        # 5. Do the work, checkpoint, and tick only the first criterion.
        (host / "feature.txt").write_text("the feature\n", encoding="utf-8")
        checkpoint = run(
            host, "checkpoint", "0001", "--agent", "worker", "--next", "tick and commit",
        )
        self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr + checkpoint.stdout)
        first = run(host, "spec", "check", "0001", "1")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)

        # 6. Commit through Gitflow, then run the real verification gate.
        git_ok(host, "add", "feature.txt")
        verified = run(host, "git", "verify", "--strict", "--task", "0001")
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        committed = run(
            host, "git", "commit", "--task", "0001", "--agent", "worker",
            "--type", "feat", "--message", "add the feature file",
        )
        self.assertEqual(committed.returncode, 0, committed.stderr + committed.stdout)

        checked = run(host, "check", "--task", "0001", "--agent", "worker")
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        self.assertTrue(marker.exists(), "the configured check never ran")
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran")

        # 7. Negative case: the second criterion is still unticked, so review
        #    must refuse and name it instead of silently delivering.
        refused = run(host, "task", "review", "0001", "--agent", "worker")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("unticked", refused.stderr)
        self.assertIn("the configured check command really ran", refused.stderr)
        spec_file = next((host / ".ai" / "specs" / "active").glob("0001-*.md"))
        self.assertIn("- [ ] the configured check command really ran",
                      spec_file.read_text(encoding="utf-8"))

        # 8. Tick the last criterion, then the same review succeeds.
        second = run(host, "spec", "check", "0001", "2")
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        reviewed = run(host, "task", "review", "0001", "--agent", "worker")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)
        self.assertIn("delivered for independent review", reviewed.stdout)
        # Review writes the task/spec/board handover state. Record that ledger
        # commit on the task branch so switching to develop cannot collide with
        # the (new) ledger files when the reviewer merges.
        git_ok(host, "add", "-A")
        git_ok(host, "commit", "-qm", "chore: record review 0001")

        # 9. A different agent merges and approves.
        merged = run(host, "git", "finish", "--task", "0001", "--agent", "reviewer")
        self.assertEqual(merged.returncode, 0, merged.stderr + merged.stdout)
        done = run(host, "task", "done", "0001", "--agent", "reviewer")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)

        # The whole point: an existing repo ends on develop with a clean tree.
        self.assertEqual(git_ok(host, "rev-parse", "--abbrev-ref", "HEAD"), "develop")
        self.assertEqual(git_ok(host, "status", "--porcelain"), "")
        self.assertEqual((host / "feature.txt").read_text(encoding="utf-8"), "the feature\n")

        # The shipped spec is archived with every criterion ticked.
        archived_specs = list((host / ".ai" / "specs" / "done").glob("0001-*.md"))
        self.assertEqual(len(archived_specs), 1)
        archived_text = archived_specs[0].read_text(encoding="utf-8")
        self.assertIn("status: shipped", archived_text)
        self.assertNotIn("- [ ]", archived_text)
        self.assertEqual(archived_text.count("- [x]"), 2)
        self.assertEqual(list((host / ".ai" / "specs" / "active").glob("0001-*.md")), [])

        archived_tasks = list((host / ".ai" / "tasks" / "done").glob("0001-*.md"))
        self.assertEqual(len(archived_tasks), 1)
        self.assertIn("status: done", archived_tasks[0].read_text(encoding="utf-8"))
        self.assertEqual(list((host / ".ai" / "tasks" / "active").glob("0001-*.md")), [])


if __name__ == "__main__":
    unittest.main()
