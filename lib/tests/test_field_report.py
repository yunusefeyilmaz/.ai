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
        self.assertEqual(run(workspace, "setup", "--set", "review=yes", "checks=yes", "git=yes", "tests=yes", "continue=no", "workers=1").returncode, 0)
        self.assertEqual(run(workspace, "task", "new", "Planned", "--role", "chief").returncode, 0)

    def test_role_can_come_from_the_environment(self) -> None:
        import os

        workspace = self.make_workspace(git_repo=False)
        self.strict_gate(workspace)
        run(workspace, "setup", "--set", "review=yes", "checks=yes", "git=yes", "tests=yes", "continue=no", "workers=1")
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
    def test_dirty_product_tree_rolls_back_and_recovery_reclaims(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=yes", "tests=no")
        run(workspace, "task", "new", "Carry")
        run(workspace, "git", "setup", stdin="y\n")
        (workspace / "errors.txt").write_text("notes\n", encoding="utf-8")  # product file, untracked
        refused = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("rolled back", refused.stderr)
        self.assertIn("ai task claim 0001 --agent w1", refused.stderr)
        # the claim did not leave the task owned by an agent without a checkout
        self.assertIn("status: todo", run(workspace, "task", "show", "0001").stdout)
        # the fix is to commit/stash the product file, then reclaim
        git(workspace, "add", "errors.txt")
        git(workspace, "commit", "-qm", "feat: carry the file")
        claimed = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(workspace), capture_output=True, text=True
        ).stdout.strip()
        self.assertTrue(branch.startswith("feature/0001"), branch)


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
        run(workspace, "setup", "--set", "review=yes", "checks=yes", "git=yes", "tests=yes", "continue=no", "workers=1")
        run(workspace, "task", "new", "Early")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        out = run(workspace, "now", "--agent", "w1").stdout
        self.assertIn("nothing is committed yet", out)


if __name__ == "__main__":
    unittest.main()


class LockNamingTest(WorkspaceCase):
    def test_resources_that_differ_only_in_separators_do_not_share_a_lock(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "lock", "acquire", "src/a", "--agent", "alice").returncode, 0)
        # `src-a` used to map to the same file name as `src/a` and was reported as taken
        self.assertEqual(run(workspace, "lock", "acquire", "src-a", "--agent", "bob").returncode, 0)
        # releasing one never deletes the other
        self.assertEqual(run(workspace, "lock", "release", "src/a", "--agent", "alice").returncode, 0)
        status = run(workspace, "lock", "status").stdout
        self.assertIn("src-a", status)
        self.assertNotIn("src/a ", status.replace("src-a", ""))


class JsonModeTest(WorkspaceCase):
    def test_json_outputs_are_one_document(self) -> None:
        workspace = self.make_workspace()
        cfg = workspace / "config" / "workspace.json"
        config = json.loads(cfg.read_text(encoding="utf-8"))
        config["checks"] = [{"name": "noisy", "command": 'python -c "print(\'LOUD OUTPUT\')"'}]
        cfg.write_text(json.dumps(config), encoding="utf-8")
        run(workspace, "setup", "--set", "review=yes", "checks=yes", "git=yes", "tests=yes", "continue=no", "workers=1")
        run(workspace, "task", "new", "Json")
        # `check --json`: the check's own output must not precede the JSON
        checked = run(workspace, "check", "--json")
        self.assertIn("LOUD OUTPUT", checked.stderr)
        self.assertIn("ok", json.loads(checked.stdout))
        # `task next --json`: claim chatter goes to stderr
        claimed = run(workspace, "task", "next", "--agent", "w1", "--json")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        self.assertEqual(json.loads(claimed.stdout)["meta"]["id"], "0001")


class SpecGateTest(WorkspaceCase):
    def with_gate(self, workspace: Path) -> None:
        set_workflow(workspace, requireSpec=True)

    def test_a_template_spec_blocks_the_claim_until_the_criteria_are_written(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.with_gate(workspace)
        run(workspace, "task", "new", "Unspecified")
        refused = run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("still the template", refused.stderr)
        spec = next((workspace / "specs" / "active").glob("0001-*.md"))
        text = spec.read_text(encoding="utf-8").replace(
            "- [ ] Criterion one, observable and independently testable", "- [ ] Visitors can read posts"
        )
        spec.write_text(text, encoding="utf-8")
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)

    def test_tasks_without_a_spec_by_choice_are_exempt(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.with_gate(workspace)
        run(workspace, "task", "new", "Tiny", "--no-spec")
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)

    def test_planned_tasks_carry_their_criteria_into_the_spec(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.with_gate(workspace)
        plan = workspace.parent / "spec-plan.json"
        plan.write_text(json.dumps({"tasks": [{
            "key": "a", "title": "Posts", "intent": "Readers need posts",
            "acceptance": ["GET /posts lists posts"],
        }]}), encoding="utf-8")
        self.assertEqual(run(workspace, "plan", "apply", str(plan)).returncode, 0)
        spec = next((workspace / "specs" / "active").glob("0001-*.md")).read_text(encoding="utf-8")
        self.assertIn("Readers need posts", spec)
        self.assertIn("GET /posts lists posts", spec)
        self.assertNotIn("Criterion one", spec)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)

    def test_doctor_warns_about_a_done_task_whose_spec_stayed_active(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Old")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        run(workspace, "task", "done", "0001", "--agent", "boss", "--force")
        spec = next((workspace / "specs" / "done").glob("0001-*.md"))
        spec.rename(workspace / "specs" / "active" / spec.name)  # simulate the old behavior
        task = next((workspace / "tasks" / "done").glob("0001-*.md"))
        task.write_text(task.read_text(encoding="utf-8").replace("specs/done/", "specs/active/"), encoding="utf-8")
        self.assertIn("its spec is still in specs/active/", run(workspace, "doctor").stdout)


class SelfMergeTest(WorkspaceCase):
    def test_the_producer_cannot_run_git_finish_on_its_own_work(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=yes", "tests=no")
        run(workspace, "task", "new", "Self merge")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        git(workspace, "commit", "--allow-empty", "-m", "feat: work")
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)
        refused = run(workspace, "git", "finish", "--task", "0001", "--agent", "alice")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("never merges its own work", refused.stderr)
        merged = run(workspace, "git", "finish", "--task", "0001", "--agent", "bob")
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)


class TemplateTest(WorkspaceCase):
    def test_the_manual_fallback_template_parses_to_plain_values(self) -> None:
        import sys

        from test_start import ROOT

        sys.path.insert(0, str(ROOT))
        from lib.tasks.store import parse_task

        meta, _ = parse_task(str(ROOT / "tasks" / "TEMPLATE.md"))
        for key in ("depends_on", "scope_allowed", "scope_forbidden", "locks"):
            self.assertIsNone(meta.get(key), key)  # no inline `# comment` leaking into values


class GitOffTest(WorkspaceCase):
    def test_without_git_review_ends_with_done_not_git_finish(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=no", "tests=no")
        run(workspace, "task", "new", "No git")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        delivered = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertIn("ai task done 0001 --agent <reviewer>", delivered.stdout)
        self.assertNotIn("git finish", delivered.stdout)
        self.assertIn("ai task done 0001 --agent bob", run(workspace, "now", "--agent", "bob", "--role", "reviewer").stdout + run(workspace, "task", "next", "--review", "--agent", "bob").stdout)
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "bob").returncode, 0)


class ReworkTest(WorkspaceCase):
    def test_rework_reruns_the_checks_after_a_new_claim(self) -> None:
        workspace = self.make_workspace(git_repo=False, mode="strict")
        cfg = workspace / "config" / "workspace.json"
        config = json.loads(cfg.read_text(encoding="utf-8"))
        config["checks"] = [{"name": "unit", "command": 'python -c "print(1)"'}]
        cfg.write_text(json.dumps(config), encoding="utf-8")
        run(workspace, "task", "new", "Rework")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)
        self.assertEqual(run(workspace, "task", "next", "--review", "--agent", "bob").returncode, 0)
        self.assertEqual(run(workspace, "task", "request-changes", "0001", "--agent", "bob", "--reason", "fix").returncode, 0)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "alice").returncode, 0)
        again = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(again.returncode, 0, again.stderr)  # used to fail: "older than the claim"
        self.assertIn("Running the project checks", again.stderr)

    def test_reviewer_can_take_a_delivered_task_without_any_release(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Handover")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "task", "review", "0001", "--agent", "alice")
        now = run(workspace, "now", "--agent", "bob", "--role", "reviewer").stdout
        self.assertIn("ai task next --review --agent bob", now)
        self.assertEqual(run(workspace, "task", "next", "--review", "--agent", "bob").returncode, 0)


class FieldReportBlockerTest(WorkspaceCase):
    """The three P0 blockers from the field report, each reproduced end to end."""

    def test_finish_budgets_the_index_guard_within_max_ttl(self) -> None:
        # Four checks with the old 1800s default asked for 600 + 7200 = 7800s,
        # above locks.maxTtlSeconds, so `git finish` could never take the guard.
        workspace = self.make_workspace()
        cfg = workspace / "config" / "workspace.json"
        config = json.loads(cfg.read_text(encoding="utf-8"))
        config["checks"] = [
            {"name": f"c{i}", "command": 'python -c "print(1)"'} for i in range(4)
        ]
        config["locks"]["maxTtlSeconds"] = 7200
        cfg.write_text(json.dumps(config), encoding="utf-8")
        run(workspace, "setup", "--set", "review=yes", "checks=yes", "git=yes", "tests=no")
        run(workspace, "task", "new", "Budgeted", "--no-spec")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        git(workspace, "commit", "--allow-empty", "-m", "feat: work")
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "alice").returncode, 0)
        merged = run(workspace, "git", "finish", "--task", "0001", "--agent", "bob")
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        self.assertIn("Merged", merged.stdout)

    def test_done_refuses_a_task_whose_branch_was_never_merged(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=yes", "tests=no")
        run(workspace, "task", "new", "Unmerged", "--no-spec")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        git(workspace, "commit", "--allow-empty", "-m", "feat: work")
        run(workspace, "task", "review", "0001", "--agent", "alice")
        refused = run(workspace, "task", "done", "0001", "--agent", "bob")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("not merged", refused.stderr)
        self.assertIn("ai git finish", refused.stderr)
        # the ledger did not move
        self.assertTrue(list((workspace / "tasks" / "active").glob("0001-*.md")))
        # finish then done works
        self.assertEqual(run(workspace, "git", "finish", "--task", "0001", "--agent", "bob").returncode, 0)
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "bob").returncode, 0)

    def test_a_plan_directory_lock_also_allows_files_under_it(self) -> None:
        workspace = self.make_workspace()
        plan = workspace.parent / "dir-lock-plan.json"
        plan.write_text(json.dumps({"tasks": [{
            "key": "shared", "title": "Shared package", "locks": ["packages/shared"],
            "acceptance": ["the package builds"],
        }]}), encoding="utf-8")
        self.assertEqual(run(workspace, "plan", "apply", str(plan)).returncode, 0)
        spec = next((workspace / "specs" / "active").glob("0001-*.md"))
        text = spec.read_text(encoding="utf-8").replace(
            "- [ ] Criterion one, observable and independently testable",
            "- [ ] the package builds",
        )
        spec.write_text(text, encoding="utf-8")
        run(workspace, "git", "setup", stdin="y\n")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        target = workspace / "packages" / "shared" / "src" / "index.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export const x = 1;\n", encoding="utf-8")
        git(workspace, "add", "packages/shared/src/index.ts")
        committed = run(
            workspace, "git", "commit", "--task", "0001", "--agent", "alice",
            "--type", "feat", "--message", "feat: shared package",
        )
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)

    def test_reopen_restores_a_done_task_and_its_spec(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Reopen me", "--no-spec")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "bob").returncode, 0)
        reopened = run(workspace, "task", "reopen", "0001", "--agent", "bob", "--reason", "not merged")
        self.assertEqual(reopened.returncode, 0, reopened.stdout + reopened.stderr)
        task = next((workspace / "tasks" / "active").glob("0001-*.md"))
        self.assertIn("status: review", task.read_text(encoding="utf-8"))

    def test_setup_can_set_a_check_timeout(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        stored = run(
            workspace, "setup", "--set", "review=yes", "checks=yes", "git=no", "tests=no",
            "--check", "unit=python -c 1", "--check-timeout", "unit=120",
        )
        self.assertEqual(stored.returncode, 0, stored.stdout + stored.stderr)
        config = json.loads((workspace / "config" / "workspace.json").read_text(encoding="utf-8"))
        self.assertEqual(config["checks"][0]["timeoutSeconds"], 120)

    def test_setup_records_who_answered(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "setup", "--set", "review=yes", "checks=no", "git=no", "tests=no",
            "--agent", "chief-1")
        shown = run(workspace, "setup", "--json").stdout
        payload = json.loads(shown)
        review = next(row for row in payload["questions"] if row["key"] == "review")
        self.assertEqual(review["answeredBy"], "chief-1")

    def test_now_tells_the_chief_to_ask_the_questions(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        out = run(workspace, "now", "--role", "chief").stdout
        self.assertIn("NEXT  ai setup", out)
        self.assertIn("ASK   review:", out)

    def test_a_manual_lock_also_widens_the_commit_scope(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Manual lock", "--allow", "docs/**", "--no-spec")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        acquired = run(workspace, "lock", "acquire", "notes/plan.md", "--agent", "alice", "--task", "0001")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        self.assertIn("scope_allowed", acquired.stdout)
        task = next((workspace / "tasks" / "active").glob("0001-*.md")).read_text(encoding="utf-8")
        self.assertIn("notes/plan.md", task)
