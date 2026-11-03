"""Only the reviewer holding the live review claim may request changes."""

from __future__ import annotations

import sys
import unittest

from test_start import ROOT, WorkspaceCase, run

sys.path.insert(0, str(ROOT))


def deliver(case, workspace, agent: str = "alice") -> None:
    """Hand a task over to review with no reviewer claim yet."""
    case.assertEqual(run(workspace, "task", "new", "Rework").returncode, 0)
    case.assertEqual(run(workspace, "task", "claim", "0001", "--agent", agent).returncode, 0)
    review = run(workspace, "task", "review", "0001", "--agent", agent)
    case.assertEqual(review.returncode, 0, review.stderr)
    case.assertEqual(run(workspace, "task", "release", "0001", "--agent", agent).returncode, 0)


class RequestChangesClaimTest(WorkspaceCase):
    def test_unclaimed_review_is_refused_with_the_claiming_command(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        deliver(self, workspace)

        refused = run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "x")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("without a reviewer claim", refused.stderr)
        self.assertIn("ai task next --review --agent bob", refused.stderr)
        self.assertIn("review", run(workspace, "task", "show", "0001").stdout)

    def test_reviewer_who_claimed_can_request_changes(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        deliver(self, workspace)
        claimed = run(workspace, "task", "next", "--review", "--agent", "bob")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)

        sent = run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "x")
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        self.assertIn("changes_requested", run(workspace, "task", "list", "--json").stdout)
        # the reviewer's claim is gone, so the producer can pick the task up again
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "alice").returncode, 0)

    def test_a_plain_claim_on_a_review_task_is_enough(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        deliver(self, workspace)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "bob").returncode, 0)

        sent = run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "x")
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)

    def test_another_reviewers_claim_is_refused(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        deliver(self, workspace)
        self.assertEqual(run(workspace, "task", "next", "--review", "--agent", "bob").returncode, 0)

        refused = run(workspace, "task", "request-changes", "0001", "--agent", "carol", "--reason", "x")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("claimed for review by bob", refused.stderr)
        self.assertIn("ai task release 0001 --agent bob", refused.stderr)
        # the claim survives the refused attempt
        self.assertEqual(run(workspace, "task", "next", "--review", "--agent", "carol").returncode, 1)
        self.assertEqual(run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "y").returncode, 0)

    def test_submitter_is_refused_before_the_claim_check(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        deliver(self, workspace)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "alice").returncode, 0)

        refused = run(workspace, "task", "request-changes", "0001", "--agent", "alice", "--reason", "x")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("independent", refused.stderr)

    def test_a_task_outside_review_keeps_its_refusal(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Early")

        refused = run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "x")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("in review", refused.stderr)


if __name__ == "__main__":
    unittest.main()
