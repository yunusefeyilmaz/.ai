"""Transition history, per-task evidence, changes_requested, scope and roles."""

from __future__ import annotations

import json
import unittest

import sys

from test_start import ROOT, WorkspaceCase, git, run

sys.path.insert(0, str(ROOT))


def set_config(workspace, **updates) -> None:
    path = workspace / "config" / "workspace.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.update(updates)
    path.write_text(json.dumps(config), encoding="utf-8")


def submit(case, workspace, agent="alice", task="0001"):
    case.assertEqual(run(workspace, "task", "claim", task, "--agent", agent).returncode, 0)
    review = run(workspace, "task", "review", task, "--agent", agent)
    case.assertEqual(review.returncode, 0, review.stderr)
    case.assertEqual(run(workspace, "task", "release", task, "--agent", agent).returncode, 0)


class HistoryTest(WorkspaceCase):
    def test_every_transition_is_recorded_with_actor_and_states(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "History work", "--agent", "planner-1")
        submit(self, workspace)
        done = run(workspace, "task", "done", "0001", "--agent", "bob")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = run(workspace, "history", "0001").stdout
        for needle in (
            "planner-1", "-> todo", "todo -> in_progress", "in_progress -> review",
            "review -> review", "review -> done", "bob",
        ):
            self.assertIn(needle, out)
        payload = json.loads(run(workspace, "history", "0001", "--json").stdout)
        kinds = [(e["actor"], e["from"], e["to"]) for e in payload["transitions"] if e["kind"] == "transition"]
        self.assertEqual(kinds[0], ("planner-1", None, "todo"))
        self.assertIn(("alice", "in_progress", "review"), kinds)
        self.assertEqual(kinds[-1], ("bob", "review", "done"))

    def test_unknown_task(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "history", "0099").returncode, 1)


class EvidenceTest(WorkspaceCase):
    def configure_check(self, workspace, command="python -c \"print('ok')\"") -> None:
        set_config(workspace, mode="strict", checks=[{"name": "unit", "command": command}])

    def test_evidence_is_attached_and_cited_in_history(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.configure_check(workspace)
        run(workspace, "task", "new", "Proof")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        checked = run(workspace, "check", "--task", "0001", "--agent", "alice")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Evidence recorded for task 0001", checked.stderr)
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)
        history = run(workspace, "history", "0001", "--evidence").stdout
        self.assertIn("proof: check passed", history)
        self.assertIn("unit=0", history)

    def test_failed_check_blocks_review(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.configure_check(workspace, command="python -c \"raise SystemExit(3)\"")
        run(workspace, "task", "new", "Red")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(run(workspace, "check", "--task", "0001", "--agent", "alice").returncode, 1)
        refused = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("failed", refused.stderr)

    def test_evidence_goes_stale_when_head_moves_and_review_reverifies(self) -> None:
        workspace = self.make_workspace()
        self.configure_check(workspace)
        run(workspace, "task", "new", "Stale")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "alice")  # also starts the task branch
        run(workspace, "checkpoint", "0001", "--agent", "alice", "--next", "finish")
        self.assertEqual(run(workspace, "check", "--task", "0001", "--agent", "alice").returncode, 0)
        (workspace / "late.txt").write_text("new work\n", encoding="utf-8")
        git(workspace, "add", "late.txt")
        git(workspace, "commit", "-m", "late change")
        self.assertIn("STALE", run(workspace, "resume", "0001").stdout)
        # review never trusts old evidence: it re-runs the checks on the new HEAD
        review = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertIn("Running the project checks", review.stderr)

    def test_resume_reports_verification_state(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.configure_check(workspace)
        run(workspace, "task", "new", "Resume proof")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "checkpoint", "0001", "--agent", "alice", "--next", "go")
        self.assertIn("verification: none recorded", run(workspace, "resume", "0001").stdout)
        run(workspace, "check", "--task", "0001", "--agent", "alice")
        self.assertIn("verification: still valid", run(workspace, "resume", "0001").stdout)


class ChangesRequestedTest(WorkspaceCase):
    def test_request_changes_round_trip(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Rework")
        submit(self, workspace)
        sent = run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "missing error handling")
        self.assertEqual(sent.returncode, 0, sent.stderr)
        listing = run(workspace, "task", "list", "--json").stdout
        self.assertIn("changes_requested", listing)
        self.assertIn("ai task claim 0001", run(workspace, "now", "--agent", "alice").stdout)
        self.assertIn("missing error handling", run(workspace, "history", "0001").stdout)
        # it is ready again and the producer takes it back
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "alice").returncode, 0)
        self.assertIn("in_progress", run(workspace, "task", "show", "0001").stdout)
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)

    def test_submitter_cannot_request_changes_on_own_work(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Self")
        submit(self, workspace)
        refused = run(workspace, "task", "request-changes", "0001", "--agent", "alice", "--reason", "x")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("independent", refused.stderr)

    def test_only_tasks_in_review(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Early")
        refused = run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "x")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("in review", refused.stderr)


class ScopeTest(WorkspaceCase):
    def started(self, workspace, *scope_args):
        run(workspace, "task", "new", "Scoped", *scope_args)
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "git", "setup", stdin="y\n")
        started = run(workspace, "git", "start", "--task", "0001", "--agent", "alice", "--type", "feature")
        self.assertEqual(started.returncode, 0, started.stderr)

    def stage(self, workspace, relative: str) -> None:
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
        git(workspace, "add", relative)

    def test_commit_outside_allowed_scope_is_refused(self) -> None:
        workspace = self.make_workspace()
        self.started(workspace, "--allow", "src/auth/**")
        self.stage(workspace, "src/payment/pay.py")
        result = run(workspace, "git", "commit", "--task", "0001", "--agent", "alice", "--type", "feat", "--message", "pay")
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside allowed scope", result.stderr)

    def test_forbidden_path_wins_over_allowed(self) -> None:
        workspace = self.make_workspace()
        self.started(workspace, "--allow", "src/**", "--forbid", "src/payment/**")
        self.stage(workspace, "src/payment/pay.py")
        result = run(workspace, "git", "verify", "--task", "0001")
        self.assertEqual(result.returncode, 1)
        self.assertIn("forbidden by scope", result.stdout)

    def test_inside_scope_commits(self) -> None:
        workspace = self.make_workspace()
        self.started(workspace, "--allow", "src/auth/**")
        self.stage(workspace, "src/auth/login.py")
        verified = run(workspace, "git", "verify", "--task", "0001")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn("inside the scope", verified.stdout)

    def test_glob_semantics(self) -> None:
        from lib.tasks.scope import matches, violations

        self.assertTrue(matches("src/auth/**", "src/auth/a/b.py"))
        self.assertTrue(matches("src/*.py", "src/a.py"))
        self.assertFalse(matches("src/*.py", "src/a/b.py"))
        self.assertTrue(matches("docs/", "docs/x/y.md"))
        self.assertEqual(violations({}, ["anything"]), [])


class RolesTest(WorkspaceCase):
    def team(self, workspace) -> None:
        set_config(workspace, team={
            "claude-1": {"roles": ["implementer"]},
            "codex-1": {"roles": ["reviewer"]},
        })

    def test_without_a_team_table_everything_is_allowed(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Open")
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "anyone").returncode, 0)

    def test_roles_limit_who_may_approve(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.team(workspace)
        run(workspace, "task", "new", "Guarded")
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "codex-1").returncode, 1)
        submit(self, workspace, agent="claude-1")
        denied = run(workspace, "task", "done", "0001", "--agent", "claude-1")
        self.assertEqual(denied.returncode, 1)
        approved = run(workspace, "task", "done", "0001", "--agent", "codex-1")
        self.assertEqual(approved.returncode, 0, approved.stderr)

    def test_implementer_may_not_request_changes(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.team(workspace)
        run(workspace, "task", "new", "Roles")
        submit(self, workspace, agent="claude-1")
        result = run(workspace, "task", "request-changes", "0001", "--agent", "claude-1", "--reason", "x")
        self.assertEqual(result.returncode, 1)
        self.assertIn("may not", result.stderr)

    def test_unknown_agent_policy_deny(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.team(workspace)
        set_config(workspace, policy={"unknownAgent": "deny"})
        run(workspace, "task", "new", "Deny")
        result = run(workspace, "task", "claim", "0001", "--agent", "stranger")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not listed under `team`", result.stderr)

    def test_doctor_warns_about_unknown_role(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        set_config(workspace, team={"x": {"roles": ["wizard"]}})
        self.assertIn("unknown role 'wizard'", run(workspace, "doctor").stdout)


if __name__ == "__main__":
    unittest.main()
