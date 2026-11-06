---
id: 0007
title: "Docs truth pass and token diet"
status: review
owner: evren-deepseek-reviewer
priority: medium
spec: specs/active/0007-docs-truth-pass-and-token-diet.md
depends_on: "0001, 0002, 0003, 0005, 0004"
scope_allowed: "README.md, GUIDE.md, AGENTS.md, docs/**, prompts/**, adapters/README.md, lib/tests/test_docs.py"
scope_forbidden: null
locks: "README.md, GUIDE.md, AGENTS.md, docs/**, prompts/**, adapters/README.md, lib/tests/test_docs.py"
branch: feature/0007-docs-truth-pass-and-token-diet
created: 2026-11-04T08:14:04Z
updated: 2026-11-06T11:53:16Z
lock: task-0007
submitted_by: evren-deepseek
changes_requested_by: evren-deepseek-reviewer
---

# 0007 - Docs truth pass and token diet

## Intent

README and GUIDE claim adopt ignores .ai/, AGENTS.md claims PID is diagnostic only, and a worker is told to read five documents before starting. Docs must match the code and fit a small context budget.

## Acceptance criteria

- [ ] README and GUIDE describe the actual ignore rules from lib/config/adopt.py
- [ ] AGENTS.md describes the actual lock staleness rule and fits within the token target (~70 lines)
- [ ] prompts/worker.md requires at most one document before the first command
- [ ] Every command shown in the docs exists and runs (doc test covers it)
- [ ] Doc tests pass
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0007-docs-truth-pass-and-token-diet.md`

<!-- Filled by the planner. -->

## Notes

- 2026-11-06 review fixes: GUIDE/README/adapters now say the CI workflow path is
  always in `.gitignore` and `--ci` only writes the workflow file; docs/git-workflow
  no longer claims `.ai/` is ignored wholesale; AGENTS.md trimmed to 74 lines;
  test_adopt_ignore_rules_match_the_docs asserts the workflow entry and that
  README/GUIDE mention it. adapters/README.md was added to this task's scope and
  locks so the same truth pass could fix it.

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
- 2026-11-06T10:13:05Z | evren-deep-seek | todo -> in_progress | claimed
- 2026-11-06T10:13:06Z created branch feature/0007-docs-truth-pass-and-token-diet from develop by evren-deep-seek
- 2026-11-06T10:19:08Z committed: docs: docs: align adopt, lock and worker docs with the code
- 2026-11-06T10:22:28Z | evren-deep-seek | in_progress -> review | submitted for independent review | check passed @ab4f911e by evren-deep-seek (tests passed, ruff passed, mypy passed)
- 2026-11-06T10:26:23Z | evren-deepseek-reviewer | review -> review | claimed
- 2026-11-06T10:46:39Z | evren-deepseek-reviewer | review -> changes_requested | AC1 fails: GUIDE.md:58 (added in this diff) says the CI workflow 'is ignored only when --ci writes it'. In lib/config/adopt.py, ADOPT_IGNORE_ENTRIES always contains '.github/workflows/ai-check.yml' and adopt_gitignore() writes every entry unconditionally; --ci only controls whether write_ci() creates the file. So the GUIDE no longer describes the real ignore rules. Fix: state that the workflow path is always in .gitignore and that --ci only writes the workflow file, and add an assert for '.github/workflows/ai-check.yml' in test_adopt_ignore_rules_match_the_docs. Should-fix in the same truth pass (docs/** is in scope): docs/git-workflow.md:170 still says 'the workspace is git-ignored in the host', which the new adopt policy contradicts at line 170. adapters/README.md:21 also still claims adopt adds '.ai/' to .gitignore, but that file is outside scope_allowed - either widen the task scope or file a follow-up. Nit: AGENTS.md is 78 lines vs the ~70 target (test ceiling 85). Everything else checks out: doc tests and the full ai check are green on ab4f911e, and the worker-prompt and staleness changes match the code.
- 2026-11-06T10:51:00Z | evren-deepseek | changes_requested -> in_progress | claimed
- 2026-11-06T10:51:01Z switched to branch feature/0007-docs-truth-pass-and-token-diet from develop by evren-deepseek
- 2026-11-06T11:03:31Z committed: fix: state the always-ignored CI workflow and widen adopt docs to adapters
- 2026-11-06T11:07:02Z committed: chore: record the review fixes in the task notes
- 2026-11-06T11:08:49Z | evren-deepseek | in_progress -> review | submitted for independent review | check passed @0a3fcb81 by evren-deepseek (tests passed, ruff passed, mypy passed)
- 2026-11-06T11:35:05Z | evren-deepseek-reviewer | review -> review | claimed
- 2026-11-06T11:53:16Z committed: chore: chore(task): record review claim for 0007
