"""Acceptance criteria are tickable state, not decoration.

The spec is the one place where "done" is defined, so these tests pin the whole
contract: the parser keeps `[ ]` vs `[x]`, `ai spec check` ticks, `ai spec show`
counts, `ai task review` refuses while a real criterion is unticked, `ai review`
renders the boxes, the archived spec says `shipped`, and the task body points at
the spec instead of duplicating the list.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from test_start import ROOT, WorkspaceCase, run

sys.path.insert(0, str(ROOT))

from lib.specs import spec as spec_lib  # noqa: E402

SPEC = """---
status: draft
task: 0001
approved_by: null
approved_on: null
---

# Acceptance criteria scenario

## Intent

Prove the boxes are real.

## Acceptance criteria

- [ ] the first criterion holds
- [x] the second criterion holds

## Out of scope

Nothing.
"""


def write_spec(workspace: Path, text: str = SPEC) -> Path:
    spec = next((workspace / "specs" / "active").glob("0001-*.md"))
    spec.write_text(text, encoding="utf-8")
    return spec


def enable_spec_gate(workspace: Path) -> None:
    path = workspace / "config" / "workspace.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["workflow"]["requireSpec"] = True
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


class ParserTest(unittest.TestCase):
    def test_the_parser_preserves_the_ticked_state(self) -> None:
        self.assertEqual(
            spec_lib.acceptance_criteria(SPEC),
            [(False, "the first criterion holds"), (True, "the second criterion holds")],
        )

    def test_criterion_texts_is_the_thin_wrapper_for_text_only_callers(self) -> None:
        self.assertEqual(
            spec_lib.criterion_texts(spec_lib.acceptance_criteria(SPEC)),
            ["the first criterion holds", "the second criterion holds"],
        )

    def test_placeholders_are_not_real_criteria(self) -> None:
        text = SPEC.replace("the first criterion holds", "Criterion one, observable and independently testable")
        self.assertEqual(spec_lib.unticked_criteria(text), [])  # placeholder skipped, second is ticked

    def test_unticked_criteria_keep_their_command_number(self) -> None:
        text = SPEC.replace("- [x] the second", "- [ ] the second")
        self.assertEqual(
            spec_lib.unticked_criteria(text),
            [(1, "the first criterion holds"), (2, "the second criterion holds")],
        )

    def test_ticking_is_idempotent_and_rejects_out_of_range(self) -> None:
        updated, changed = spec_lib.tick_criterion(SPEC, 1)
        self.assertTrue(changed)
        self.assertIn("- [x] the first criterion holds", updated)
        again, changed = spec_lib.tick_criterion(updated, 1)
        self.assertFalse(changed)
        self.assertEqual(again, updated)
        with self.assertRaises(ValueError):
            spec_lib.tick_criterion(SPEC, 9)

    def test_mark_status_rewrites_only_the_frontmatter(self) -> None:
        shipped = spec_lib.mark_status(SPEC, "shipped")
        self.assertIn("status: shipped", shipped)
        self.assertNotIn("status: draft", shipped)
        self.assertIn("## Out of scope", shipped)  # the body is untouched


class SpecCommandTest(WorkspaceCase):
    def prepared(self) -> Path:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "task", "new", "Criteria scenario").returncode, 0)
        write_spec(workspace)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)
        return workspace

    def test_show_prints_each_box_and_the_progress(self) -> None:
        workspace = self.prepared()
        shown = run(workspace, "spec", "show", "0001")
        self.assertEqual(shown.returncode, 0, shown.stderr + shown.stdout)
        self.assertIn("[ ] the first criterion holds", shown.stdout)
        self.assertIn("[x] the second criterion holds", shown.stdout)
        self.assertIn("1/2 done", shown.stdout)

    def test_check_ticks_one_criterion_and_is_idempotent(self) -> None:
        workspace = self.prepared()
        ticked = run(workspace, "spec", "check", "0001", "1")
        self.assertEqual(ticked.returncode, 0, ticked.stderr + ticked.stdout)
        self.assertIn("Ticked 1:", ticked.stdout)
        self.assertIn("2/2 done", ticked.stdout)

        shown = run(workspace, "spec", "show", "0001")
        self.assertIn("[x] the first criterion holds", shown.stdout)

        again = run(workspace, "spec", "check", "0001", "1")
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertIn("already ticked", again.stdout)

    def test_an_out_of_range_number_is_a_clean_error(self) -> None:
        workspace = self.prepared()
        refused = run(workspace, "spec", "check", "0001", "9")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("out of range", refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)

    def test_a_task_without_a_spec_is_refused_with_the_reason(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "No spec", "--no-spec")
        refused = run(workspace, "spec", "show", "0001")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--no-spec", refused.stderr)


class ReviewGateTest(WorkspaceCase):
    def gated(self) -> Path:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "task", "new", "Criteria gate").returncode, 0)
        write_spec(workspace)
        enable_spec_gate(workspace)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)
        return workspace

    def test_review_refuses_and_names_the_unticked_criteria(self) -> None:
        workspace = self.gated()
        refused = run(workspace, "task", "review", "0001", "--agent", "w1")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("unticked", refused.stderr)
        self.assertIn("the first criterion holds", refused.stderr)
        self.assertIn("ai spec check 0001", refused.stderr)

    def test_review_passes_once_every_real_criterion_is_ticked(self) -> None:
        workspace = self.gated()
        self.assertEqual(run(workspace, "spec", "check", "0001", "1").returncode, 0)
        reviewed = run(workspace, "task", "review", "0001", "--agent", "w1")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)
        self.assertIn("delivered for independent review", reviewed.stdout)


class ArchivedSpecTest(WorkspaceCase):
    def test_done_marks_the_archived_spec_shipped(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "task", "new", "Ship it").returncode, 0)
        write_spec(workspace)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "w1").returncode, 0)
        self.assertEqual(run(workspace, "spec", "check", "0001", "1").returncode, 0)
        self.assertEqual(run(workspace, "task", "review", "0001", "--agent", "w1").returncode, 0)

        done = run(workspace, "task", "done", "0001", "--agent", "reviewer")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        archived = next((workspace / "specs" / "done").glob("0001-*.md"))
        self.assertIn("status: shipped", archived.read_text(encoding="utf-8"))


class SingleSourceTest(WorkspaceCase):
    def test_the_task_body_points_at_the_spec_instead_of_duplicating_it(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "task", "new", "Pointer task").returncode, 0)
        task_file = next((workspace / "tasks" / "active").glob("0001-*.md"))
        body = task_file.read_text(encoding="utf-8")
        self.assertNotIn("- [ ] Criterion one", body)
        self.assertIn("Criteria live in the spec", body)

        shown = run(workspace, "task", "show", "0001")
        self.assertEqual(shown.returncode, 0, shown.stderr + shown.stdout)
        self.assertIn("Criterion one, observable and independently testable", shown.stdout)


class ReviewPackageTest(WorkspaceCase):
    def package(self) -> Path:
        workspace = self.make_workspace(git_repo=False)
        self.assertEqual(run(workspace, "task", "new", "Package").returncode, 0)
        write_spec(workspace)
        return workspace

    def test_the_package_renders_boxes_and_progress(self) -> None:
        workspace = self.package()
        out = run(workspace, "review", "0001").stdout
        self.assertIn("[ ] the first criterion holds", out)
        self.assertIn("[x] the second criterion holds", out)
        self.assertIn("1/2 ticked", out)
        self.assertIn("[ ] every acceptance criterion is met", out)

    def test_the_checklist_box_reflects_the_spec(self) -> None:
        workspace = self.package()
        self.assertEqual(run(workspace, "spec", "check", "0001", "1").returncode, 0)
        out = run(workspace, "review", "0001").stdout
        self.assertIn("[x] every acceptance criterion is met", out)

    def test_json_keeps_the_text_list_and_publishes_the_state(self) -> None:
        workspace = self.package()
        payload = json.loads(run(workspace, "review", "0001", "--json").stdout)
        self.assertIn("the first criterion holds", payload["spec"]["criteria"])
        self.assertIn([False, "the first criterion holds"], payload["spec"]["criteria_state"])
        self.assertEqual((payload["spec"]["done"], payload["spec"]["total"]), (1, 2))


if __name__ == "__main__":
    unittest.main()
