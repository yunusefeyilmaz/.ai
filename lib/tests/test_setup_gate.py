"""`ai setup --defaults` must not be usable as a fake human approval.

The chief's questionnaire exists so a person decides how much process a project
gets. `--defaults` used to accept every recommendation in one non-interactive
command, so an agent could skip the conversation and claim the user agreed.
"""

from __future__ import annotations

import json
import unittest

from test_start import WorkspaceCase, run


class DefaultsGateTest(WorkspaceCase):
    def preferences(self, workspace) -> dict:
        config = json.loads((workspace / "config" / "workspace.json").read_text(encoding="utf-8"))
        return config["preferences"]

    def test_defaults_without_yes_is_refused(self) -> None:
        workspace = self.make_workspace(git_repo=False)

        result = run(workspace, "setup", "--defaults")

        self.assertEqual(result.returncode, 1)
        self.assertIn("--yes", result.stderr)
        self.assertFalse(self.preferences(workspace)["confirmed"])

    def test_defaults_with_yes_still_needs_a_terminal(self) -> None:
        workspace = self.make_workspace(git_repo=False)

        result = run(workspace, "setup", "--defaults", "--yes")

        self.assertEqual(result.returncode, 1)
        self.assertIn("interactive terminal", result.stderr)
        self.assertFalse(self.preferences(workspace)["confirmed"])

    def test_explicit_answers_still_work_without_a_terminal(self) -> None:
        workspace = self.make_workspace(git_repo=False)

        result = run(workspace, "setup", "--set", "review=yes", "checks=no", "git=no", "tests=yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.preferences(workspace)["confirmed"])


class ChiefCreationGateTest(WorkspaceCase):
    def gated_workspace(self):
        workspace = self.make_workspace(git_repo=False)
        path = workspace / "config" / "workspace.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["workflow"]["chiefOnlyTasks"] = True
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return workspace

    def test_unconfirmed_preferences_block_task_creation(self) -> None:
        workspace = self.gated_workspace()

        refused = run(workspace, "task", "new", "Should wait", "--role", "chief")

        self.assertEqual(refused.returncode, 1)
        self.assertIn("Ask the user", refused.stderr)
        self.assertEqual(list((workspace / "tasks" / "active").glob("*.md")), [])

    def test_stored_answers_unblock_creation(self) -> None:
        workspace = self.gated_workspace()
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=no", "tests=yes")

        created = run(workspace, "task", "new", "Now allowed", "--role", "chief")

        self.assertEqual(created.returncode, 0, created.stderr)


if __name__ == "__main__":
    unittest.main()
