"""`ai review <id>` is the reviewer's single read-only package.

It must contain everything a reviewer needs (task, spec criteria, diff, evidence,
history, checklist), never write anything, and degrade honestly when the proof is
missing.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from test_start import WorkspaceCase, run

SPEC = """---
status: approved
task: 0001
---

# Review package scenario

## Intent

Prove the package is complete.

## Acceptance criteria

- [ ] the package lists this criterion
- [ ] the diff shows the branch change

## Out of scope

Nothing.
"""


class ReviewPackageCase(WorkspaceCase):
    def prepared(self) -> Path:
        """A claimed task on its branch with one committed product change."""
        workspace = self.make_workspace()
        for branch in ("develop", "master"):
            subprocess.run(
                ["git", "branch", branch], cwd=str(workspace), check=True,
                capture_output=True, text=True, timeout=20,
            )
        created = run(workspace, "task", "new", "Review package scenario")
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)

        spec = next((workspace / "specs" / "active").glob("0001-*.md"))
        spec.write_text(SPEC, encoding="utf-8")
        (workspace / "src.txt").write_text("the branch change\n", encoding="utf-8")
        subprocess.run(["git", "add", "src.txt"], cwd=str(workspace), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "feat: add the branch change"],
            cwd=str(workspace), check=True, capture_output=True,
        )
        return workspace

    def test_the_package_carries_every_review_input(self) -> None:
        workspace = self.prepared()
        result = run(workspace, "review", "0001")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        out = result.stdout

        self.assertIn("=== REVIEW PACKAGE 0001 ===", out)
        self.assertIn("Review package scenario", out)
        self.assertIn("Acceptance criteria", out)
        self.assertIn("the package lists this criterion", out)
        self.assertIn("Diff", out)
        self.assertIn("the branch change", out)          # the patch body
        self.assertIn("Evidence", out)
        self.assertIn("no check was ever recorded", out)  # honest about missing proof
        self.assertIn("History", out)
        self.assertIn("claimed", out)
        self.assertIn("Checklist", out)
        self.assertIn("ai task next --review", out)
        self.assertIn("=== END REVIEW PACKAGE ===", out)

    def test_stat_shows_the_summary_without_the_patch(self) -> None:
        workspace = self.prepared()
        result = run(workspace, "review", "0001", "--stat")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("src.txt", result.stdout)
        self.assertNotIn("+the branch change", result.stdout)
        self.assertIn("--stat", result.stdout)

    def test_max_lines_truncates_visibly(self) -> None:
        workspace = self.prepared()
        (workspace / "src.txt").write_text(
            "\n".join(f"line {n}" for n in range(40)) + "\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "src.txt"], cwd=str(workspace), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "feat: more lines"], cwd=str(workspace), check=True,
            capture_output=True,
        )

        result = run(workspace, "review", "0001", "--max-lines", "5")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("[truncated: 5 of", result.stdout)
        self.assertIn("--max-lines", result.stdout)

    def test_json_publishes_the_same_content(self) -> None:
        workspace = self.prepared()
        result = run(workspace, "review", "0001", "--json")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {"task", "git", "spec", "diff", "evidence", "history", "checklist"})
        self.assertEqual(payload["task"]["id"], "0001")
        self.assertIn("the package lists this criterion", payload["spec"]["criteria"])
        self.assertIn("src.txt", payload["diff"]["stat"])
        self.assertIn("+the branch change", payload["diff"]["patch"])
        self.assertEqual(payload["evidence"]["state"], "none")
        self.assertTrue(payload["history"])
        self.assertIn("every acceptance criterion", " ".join(payload["checklist"]))
        self.assertEqual(payload["git"]["branch"], payload["task"]["branch"])

    def test_an_unknown_id_is_refused_with_the_next_command(self) -> None:
        workspace = self.prepared()
        result = run(workspace, "review", "0099")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No task with id 0099", result.stderr)
        self.assertIn("ai task list", result.stderr)

    def test_the_command_is_read_only(self) -> None:
        workspace = self.prepared()
        task_file = next((workspace / "tasks" / "active").glob("0001-*.md"))
        before = task_file.read_bytes()
        locks_before = sorted(p.name for p in (workspace / "runtime" / "locks").glob("*.lock"))

        for extra in ((), ("--json",), ("--stat",)):
            result = run(workspace, "review", "0001", *extra)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        self.assertEqual(task_file.read_bytes(), before)
        after = sorted(p.name for p in (workspace / "runtime" / "locks").glob("*.lock"))
        self.assertEqual(after, locks_before, "ai review must not claim or lock anything")

    def test_capabilities_describe_the_command(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        payload = json.loads(run(workspace, "capabilities").stdout)
        self.assertIn("review", payload["commands"])
        self.assertNotIn("--help", payload["commands"]["review"])
        self.assertIn("--max-lines", payload["flags"]["review"])


if __name__ == "__main__":
    unittest.main()
