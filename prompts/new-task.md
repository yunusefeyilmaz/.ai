# New task

Use this prompt when the human describes a piece of work.

## 1. Locate

- Search `tasks/active/` and `tasks/done/` for an existing task that covers it.
- If it exists, work with that task. Do not create a twin.

## 2. Classify

- **New behavior** -> spec lane. A spec in `specs/active/` is required.
- **Bug** -> reproduce first, then a spec if the fix changes behavior.
- **Trivial** (typo, obvious one-liner) -> task with a one-line note, no spec.
- **Question** -> answer, no task.

## 3. Create

```sh
ai task new "<short imperative title>" --priority <low|medium|high>
```

Fill in `## Intent` and at least one acceptance criterion. Leave the plan to the
planner unless you are acting as both.

## 4. Claim and work

```sh
ai task claim <id> --agent <name>
```

Follow `docs/task-flow.md`. Acquire locks before editing shared resources. Keep
scratch files inside `.ai/`.

## 5. Hand off

Leave the task with: status, decisions, what the next role must produce, and a
pointer to evidence. Release locks you no longer need.

## Refusals

- Do not create a task without acceptance criteria.
- Do not start implementing a behavior change without a spec.
- Do not claim a task owned by another agent.
