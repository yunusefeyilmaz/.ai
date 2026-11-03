"""`ai doctor` audits the meaning of the ledger, not only its shape.

An active task can be structurally valid and still stuck: its spec is the empty
template, its dependencies form a cycle, nobody owns it, or it has no branch.
Each case below builds a throwaway workspace, breaks exactly one thing and checks
both the level of the finding and the command its hint names.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from test_start import WorkspaceCase, run


def parse_json(case: unittest.TestCase, result: subprocess.CompletedProcess) -> dict:
    case.assertTrue(result.stdout.lstrip().startswith("{"), result.stderr + result.stdout)
    return json.loads(result.stdout)


def findings_with(payload: dict, needle: str) -> list[dict]:
    return [
        finding for finding in payload["check"]["findings"]
        if needle in finding["message"]
    ]


def finding_with(case: unittest.TestCase, payload: dict, needle: str) -> dict:
    rows = findings_with(payload, needle)
    case.assertTrue(rows, f"no finding containing {needle!r} in {payload['check']['findings']}")
    return rows[0]


def set_config(workspace: Path, **updates) -> None:
    """Change workspace settings the test depends on (the harness disables specs)."""
    config_path = workspace / "config" / "workspace.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for dotted, value in updates.items():
        section, _, key = dotted.partition("__")
        target = config if not key else config.setdefault(section, {})
        target[key or section] = value
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def rewrite(workspace: Path, task_file: Path, **fields: str) -> None:
    """Replace simple `key: value` lines in a task's front matter."""
    lines = task_file.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        key = line.split(":", 1)[0].strip()
        if key in fields and not line.startswith(" "):
            out.append(f"{key}: {fields[key]}")
        else:
            out.append(line)
    task_file.write_text("\n".join(out) + "\n", encoding="utf-8")


class SpecAuditTest(WorkspaceCase):
    def test_an_unfilled_spec_is_reported_with_its_path(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        set_config(workspace, workflow__requireSpec=True)
        created = run(workspace, "task", "new", "Needs a real spec")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        task_file = self.task_files(workspace)[0]

        result = run(workspace, "doctor", "--json")
        payload = parse_json(self, result)
        finding = finding_with(self, payload, "has no acceptance criteria yet")
        self.assertEqual(finding["level"], "warn")
        self.assertIn("specs/active/", finding["message"])
        self.assertIn("acceptance criteria", finding["hint"])
        # a warning is not fatal on its own, but --strict is strict
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(run(workspace, "doctor", "--strict").returncode, 1)
        self.assertTrue(task_file.is_file())

    def test_a_project_without_required_specs_is_left_alone(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        created = run(workspace, "task", "new", "Optional spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        set_config(workspace, workflow__requireSpec=False)

        payload = parse_json(self, run(workspace, "doctor", "--json"))
        self.assertEqual(findings_with(payload, "no acceptance criteria yet"), [])


class DependencyCycleTest(WorkspaceCase):
    def test_a_cycle_is_an_error_naming_the_cycle(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        for title in ("One", "Two"):
            created = run(workspace, "task", "new", title, "--no-spec")
            self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        first, second = self.task_files(workspace)
        rewrite(workspace, first, depends_on="0002")
        rewrite(workspace, second, depends_on="0001")

        result = run(workspace, "doctor", "--json")
        payload = parse_json(self, result)
        finding = finding_with(self, payload, "dependency cycle")
        self.assertEqual(finding["level"], "error")
        self.assertIn("0001 -> 0002 -> 0001", finding["message"])
        self.assertIn("depends_on", finding["hint"])
        self.assertEqual(result.returncode, 1)

    def test_an_unknown_dependency_is_still_only_a_warning(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        created = run(workspace, "task", "new", "Waits for a ghost", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        rewrite(workspace, self.task_files(workspace)[0], depends_on="0042")

        result = run(workspace, "doctor", "--json")
        payload = parse_json(self, result)
        finding = finding_with(self, payload, "depends_on unknown task 0042")
        self.assertEqual(finding["level"], "warn")
        self.assertEqual(findings_with(payload, "dependency cycle"), [])
        self.assertEqual(result.returncode, 0)


class OwnershipAuditTest(WorkspaceCase):
    def test_in_progress_without_an_owner_is_reported(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        created = run(workspace, "task", "new", "Nobody owns this", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        rewrite(workspace, self.task_files(workspace)[0], status="in_progress", owner="null")

        payload = parse_json(self, run(workspace, "doctor", "--json"))
        finding = finding_with(self, payload, "in_progress without an owner")
        self.assertEqual(finding["level"], "warn")
        self.assertIn("ai task claim", finding["hint"])

    def test_a_task_waiting_in_review_is_not_orphaned(self) -> None:
        # The review queue is a handover state: no owner until a reviewer claims it.
        workspace = self.make_workspace(git_repo=False)
        created = run(workspace, "task", "new", "Waiting in review", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        rewrite(workspace, self.task_files(workspace)[0], status="review", owner="null")

        payload = parse_json(self, run(workspace, "doctor", "--json"))
        self.assertEqual(findings_with(payload, "review without an owner"), [])
        self.assertEqual(findings_with(payload, "without an owner"), [])


class BranchAuditTest(WorkspaceCase):
    def test_a_claimed_task_without_a_branch_is_reported(self) -> None:
        workspace = self.make_workspace()
        # The audit only applies once the Gitflow base exists (`ai git setup`).
        for branch in ("develop", "master"):
            subprocess.run(
                ["git", "branch", branch], cwd=str(workspace), check=True,
                capture_output=True, text=True, timeout=20,
            )
        created = run(workspace, "task", "new", "Work without a branch", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        rewrite(
            workspace, self.task_files(workspace)[0],
            status="in_progress", owner="alice", branch="null",
        )

        payload = parse_json(self, run(workspace, "doctor", "--json"))
        finding = finding_with(self, payload, "in_progress without a task branch")
        self.assertEqual(finding["level"], "warn")
        self.assertIn("ai git start --task 0001 --agent alice", finding["hint"])

    def test_a_missing_git_base_is_a_setup_step_not_an_orphan_branch(self) -> None:
        # `ai start` claims before the Gitflow base exists, so a claim with no
        # branch is normal until `ai git setup` has run.
        workspace = self.make_workspace()
        created = run(workspace, "task", "new", "Waiting for git setup", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        rewrite(
            workspace, self.task_files(workspace)[0],
            status="in_progress", owner="alice", branch="null",
        )

        payload = parse_json(self, run(workspace, "doctor", "--json"))
        self.assertEqual(findings_with(payload, "without a task branch"), [])

    def test_git_off_silences_the_branch_audit(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        set_config(workspace, git__enabled=False)
        created = run(workspace, "task", "new", "No git here", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        rewrite(
            workspace, self.task_files(workspace)[0],
            status="in_progress", owner="alice", branch="null",
        )

        payload = parse_json(self, run(workspace, "doctor", "--json"))
        self.assertEqual(findings_with(payload, "without a task branch"), [])


class CleanWorkspaceTest(WorkspaceCase):
    def test_an_empty_workspace_stays_clean_and_strict_passes(self) -> None:
        workspace = self.make_workspace()
        result = run(workspace, "doctor", "--json")
        payload = parse_json(self, result)
        self.assertEqual(payload["check"]["findings"], [], payload["check"])
        self.assertEqual(result.returncode, 0)

        strict = run(workspace, "doctor", "--strict", "--json")
        self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)


if __name__ == "__main__":
    unittest.main()
