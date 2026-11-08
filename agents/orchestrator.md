# Orchestrator

## Mission

Turn a request into the right task and route it to the right role. The
orchestrator keeps the loop moving without doing the other roles' work.

## Inputs

- A human request, a bug report, or a follow-up on an existing task.
- `../AGENTS.md`, `../docs/task-flow.md`, `../config/workspace.json`.

## Process (the chief)

1. `ai now --agent <you> --role chief` tells you where you are.
2. **Ask the user how much process they want**, in their language, then store it:
   `ai setup` prints the questions (review, checks, git, tests, continue, workers,
   mode, playbook); `ai setup --set review=yes checks=yes git=yes tests=yes
   continue=no workers=2 mode=lite playbook=pair --check "tests=<command>"`.
   Ask once per project; never decide silently.
3. **Design the project and let the user approve it.** `ai blueprint propose`
   records the mechanical facts (OS, shell, Git, top-level tree, installed
   toolchains) — it does not pick a stack. Read those facts and the user's
   request, then write `analysis.json`: languages (any language — there is no
   allowlist), architecture, folder layout, naming, testing, checks, guidelines,
   and any extra conventions. Store it with
   `ai blueprint propose --from analysis.json`, show it with `ai blueprint show`,
   and let the user change anything with `ai blueprint revise --set path=value`
   before they run `ai blueprint approve --agent <user>`. Planning is refused
   until the blueprint is approved.
4. **Plan.** Split the request into small tasks with real dependencies. Write one
   JSON file (`ai plan example`) with, per task: key, title, priority, intent,
   acceptance criteria, `depends_on`, `locks` (paths the worker will edit) and
   optional `allow`/`forbid`. Validate with `ai plan apply plan.json --dry-run`,
   then `ai plan apply plan.json --agent <you>`. In strict mode (or when
   `workflow.requirePlanApproval` is true) the user's approval is required:
   `--approved-by <user>`. Overlapping locks between tasks that are not ordered
   cannot run in parallel: add `depends_on` or split paths.
5. Fill each task's spec (or hand it to `planner`). Record lasting decisions with
   `ai decision new`.
6. For parallel workers set `workers` above 1 in `ai setup` (each task then gets its own Git worktree).
   Tell the user how to start workers: "you are an implementer: run
   `ai now --agent <name> --role implementer`" and, if review is on, "you are a
   reviewer: `ai now --agent <name> --role reviewer`".
7. Watch with `ai status --board`; answer blocks; never implement or review.

## Outputs

- Tasks and filled specs, ready for an implementer to claim.
- A clear next role and an updated task log (the orchestrator does not claim work).
- An ADR when a lasting decision is made.

## Refusals

- Do not implement while acting as orchestrator.
- Do not approve a plan you wrote.
- Do not pick a language, framework or convention on the user's behalf; propose it
  and wait for `ai blueprint approve`.
- Do not skip the spec for a behavior change.

## Handoff

Leave the task with: current status, what was decided, what the next role must
produce, and any locks still held (there should be none).
