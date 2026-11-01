"""Smoke coverage for commands that had none: block/unblock, link, discard, brief,
artifact, clean, git begin/end, decision numbering."""

from __future__ import annotations

import json
import unittest

from test_start import WorkspaceCase, run


class TaskStateCommandsTest(WorkspaceCase):
    def test_block_then_unblock(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Blocked")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        blocked = run(workspace, "task", "block", "0001", "--agent", "w1", "--reason", "needs an API key")
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        self.assertIn("blocked", run(workspace, "task", "show", "0001").stdout)
        self.assertIn("needs an API key", run(workspace, "history", "0001").stdout)
        self.assertEqual(run(workspace, "task", "unblock", "0001", "--agent", "w1").returncode, 0)
        self.assertIn("todo", run(workspace, "task", "show", "0001").stdout)

    def test_link_records_issue_and_pr(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Linked")
        linked = run(workspace, "task", "link", "0001", "--issue", "https://github.com/o/r/issues/12",
                     "--pr", "https://github.com/o/r/pull/34")
        self.assertEqual(linked.returncode, 0, linked.stderr)
        shown = run(workspace, "task", "show", "0001").stdout
        self.assertIn("issues/12", shown)
        self.assertIn("pull/34", shown)

    def test_discard_is_destructive_so_it_needs_a_terminal(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Throwaway")
        refused = run(workspace, "task", "discard", "0001")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("interactive terminal", refused.stdout + refused.stderr)
        self.assertEqual(len(json.loads(run(workspace, "task", "list", "--json").stdout)["active"]), 1)

    def test_discard_refuses_a_task_that_someone_holds(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Held")
        run(workspace, "task", "claim", "0001", "--agent", "w1")
        self.assertEqual(run(workspace, "task", "discard", "0001").returncode, 1)


class BriefAndArtifactsTest(WorkspaceCase):
    def test_brief_contains_the_task_and_the_rules(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Brief me")
        brief = run(workspace, "brief", "0001")
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn("Brief me", brief.stdout)
        payload = json.loads(run(workspace, "brief", "0001", "--json").stdout)
        self.assertTrue(payload)

    def test_artifact_put_list_clean(self) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from test_start import COPY_IGNORE, ROOT

        host = Path(tempfile.mkdtemp(prefix="ai-art-"))
        self.addCleanup(shutil.rmtree, host, True)
        workspace = host / ".ai"  # a host project: scratch files live outside `.ai`
        shutil.copytree(ROOT, workspace, ignore=COPY_IGNORE)
        for sub in ("locks", "state", "artifacts", "logs"):
            shutil.rmtree(workspace / "runtime" / sub, ignore_errors=True)
        (host / "scratch.txt").write_text("notes\n", encoding="utf-8")
        put = run(workspace, "artifact", "put", str(host / "scratch.txt"), "--reason", "test", "--agent", "w1")
        self.assertEqual(put.returncode, 0, put.stdout + put.stderr)
        self.assertFalse((host / "scratch.txt").exists())
        self.assertIn("scratch.txt", run(workspace, "artifact", "list").stdout)
        self.assertEqual(run(workspace, "artifact", "clean").returncode, 1)  # needs --all
        self.assertEqual(run(workspace, "artifact", "clean", "--all").returncode, 0)
        self.assertIn("No quarantined artifacts", run(workspace, "artifact", "list").stdout)

    def test_artifact_put_refuses_paths_outside_the_project(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        outside = workspace.parent / "outside.txt"
        outside.write_text("x\n", encoding="utf-8")
        self.assertEqual(run(workspace, "artifact", "put", str(outside)).returncode, 1)
        self.assertTrue(outside.exists())

    def test_clean_needs_a_flag_and_removes_stale_locks(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        bare = run(workspace, "clean")
        self.assertEqual(bare.returncode, 1)
        self.assertIn("--stale-locks", bare.stderr)
        self.assertEqual(run(workspace, "clean", "--stale-locks", "--logs").returncode, 0)


class GitIndexGuardTest(WorkspaceCase):
    def test_begin_and_end_hold_and_free_the_index(self) -> None:
        workspace = self.make_workspace()
        begun = run(workspace, "git", "begin", "--agent", "w1")
        self.assertEqual(begun.returncode, 0, begun.stderr)
        self.assertIn("@git/index", run(workspace, "lock", "status").stdout)
        self.assertEqual(run(workspace, "git", "begin", "--agent", "w2").returncode, 1)
        self.assertEqual(run(workspace, "git", "end", "--agent", "w1").returncode, 0)
        self.assertEqual(run(workspace, "git", "begin", "--agent", "w2").returncode, 0)


class DecisionNumberingTest(WorkspaceCase):
    def test_numbers_increase_and_never_repeat(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        for title in ("One", "Two", "Three"):
            self.assertEqual(run(workspace, "decision", "new", title).returncode, 0)
        listing = run(workspace, "decision", "list").stdout
        for number in ("0001", "0002", "0003"):
            self.assertIn(number, listing)
        self.assertEqual(list((workspace / "docs" / "decisions").glob(".*.reserved")), [])


class ContextPayloadTest(WorkspaceCase):
    def test_json_payloads_are_compact_and_versioned(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Compact")
        payload = json.loads(run(workspace, "now", "--json").stdout)
        self.assertEqual(payload["schema"], 1)
        for task in payload["active"]:
            self.assertNotIn("_body", task)
            self.assertNotIn("_path", task)
        context = json.loads(run(workspace, "context", "--json").stdout)
        self.assertTrue(all("_body" not in t for t in context["active"]))


if __name__ == "__main__":
    unittest.main()
