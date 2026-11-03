---
id: 0016
title: "Add needs_human and next_args to ai now --json"
status: done
owner: buffy-reviewer
priority: high
spec: specs/done/0016-add-needs-human-and-next-args-to-ai-now-json.md
depends_on: null
scope_allowed: "lib/runtime/overview.py, lib/cmd/now.py, lib/tests/test_now_json.py, lib/tests/test_commands_smoke.py"
scope_forbidden: null
locks: "lib/runtime/overview.py, lib/cmd/now.py, lib/tests/test_now_json.py, lib/tests/test_commands_smoke.py"
branch: null
created: 2026-11-03T09:12:54Z
updated: 2026-11-03T09:28:40Z
lock: null
submitted_by: buffy-s4
merged_into: develop
merged_at: 2026-11-03T09:28:36Z
reviewed_by: buffy-reviewer
reviewed_at: 2026-11-03T09:28:40Z
---

# 0016 - Add needs_human and next_args to ai now --json

## Intent

An agent reading ai now --json must not have to interpret prose to know whether it should act or ask the user, and NEXT must be executable with the caller's own agent name.

## Acceptance criteria

- [ ] ai now --json --agent X publishes schema 2 with needs_human (bool), question (string or null), next_args (list of argv tokens without the leading `ai`) and blocker (string or null)
- [ ] needs_human is true and question is non-empty whenever the next step is a question to the user (unconfirmed setup, nothing ready, delivered work awaiting a go-ahead) and false while a claimable or claimed task exists
- [ ] next_args is concrete when --agent is given (no `<n>` placeholder) and reconstructs the printed NEXT command
- [ ] the human-readable ai now output is unchanged in shape and still shows NEXT with a runnable command
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0016-add-needs-human-and-next-args-to-ai-now-json.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T09:12:54Z | orchestrator | - -> todo | created
- 2026-11-03T09:14:43Z | buffy-s4 | todo -> in_progress | claimed
- 2026-11-03T09:14:44Z created branch feature/0016-add-needs-human-and-next-args-to-ai-now from develop by buffy-s4
- 2026-11-03T09:27:53Z committed: feat: publish needs_human and next_args in ai now --json
- 2026-11-03T09:28:17Z | buffy-s4 | in_progress -> review | submitted for independent review | check passed @b766c14e by buffy-s4 (no commands)
- 2026-11-03T09:28:24Z | buffy-reviewer | review -> review | claimed
- 2026-11-03T09:28:34Z committed: chore: chore(0016): record the review handover
- 2026-11-03T09:28:36Z merged feature/0016-add-needs-human-and-next-args-to-ai-now into develop by buffy-reviewer
- 2026-11-03T09:28:40Z | buffy-reviewer | review -> done | approved | check passed @efa443cb by buffy-reviewer (no commands)
