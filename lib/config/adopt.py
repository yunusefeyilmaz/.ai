"""config.adopt: split out of the former monolithic ai.py."""

from __future__ import annotations

import os

from lib.core.fsio import (
    read_text,
    write_text_atomic,
)
from lib.core.paths import (
    PROJECT,
)

ROOT_BLOCK = """<!-- ai-workspace:start -->
## AI workspace

This project uses the `.ai` engineering workspace. Task state, specs, locks,
checkpoints, logs and scratch artifacts live under `.ai/` and nowhere else.

Start every session with `.ai/ai now --agent <name>`: it prints the state and
the single next required command. `.ai/ai context` gives the project memory
(open work, shipped work, decisions) when you are new here.

Who you are decides what you may do. If the user gave you a job and there are no
tasks yet, you are the **chief**: do not write code and do not create tasks
yourself first. Run `.ai/ai now --agent <name> --role chief`, ask the user the
setup questions, then plan. Only the chief creates tasks; implementers claim
existing ones and reviewers review.

Before any file-changing task, use Gitflow unless the user explicitly asks not
to use Git:
1. Read `.ai/AGENTS.md`, `.ai/GUIDE.md`, `.ai/docs/task-flow.md` and
   `.ai/docs/git-workflow.md`.
2. Run `.ai/ai git setup`. It initializes Git if needed and, when the
   repo has no commits, previews non-ignored files and asks before the initial
   commit. It ends with HEAD on the integration branch, which contains every
   production commit. If Git reports dubious ownership, ask the user
   to approve trusting only this exact checkout; never use a wildcard entry.
3. Create or claim one task, then successfully run
   `.ai/ai git start --task <id> --agent <name> --type <type>`. If it
   fails, stop before editing and report the blocker.
4. Stage only owned paths, run `.ai/ai git verify --strict`, then commit
   with `.ai/ai git commit`. Submit the task for review; a different
   reviewer runs `.ai/ai git finish` before the task is marked done.

Read-only tasks do not need a branch. Do not skip Gitflow just because `.git`
is absent; setup initializes the repository.

Checkpoint before the context window fills. Verify with
`.ai/ai check`; "done" requires its output.

Never create task notes, scratch files or generated logs outside `.ai/`.
<!-- ai-workspace:end -->
"""


BOOTSTRAP_PROMPT = """This project uses the .ai engineering workspace.

1. Run `.ai/ai now --agent <name>` for the state and next required command,
   then read .ai/AGENTS.md, .ai/GUIDE.md, .ai/docs/task-flow.md,
   .ai/docs/multi-agent.md and .ai/docs/git-workflow.md.
2. Run `.ai/ai adopt` once so every AI tool in this project finds the workspace.
   On an existing Git repository it also commits the `.ai/` and `.gitignore`
   baseline on the integration branch, leaving a clean tree. If that commit
   cannot be made (identity, permissions), it prints the exact commands to run.
3. Run `.ai/ai doctor`. Before file-changing work, run
   `.ai/ai git setup` once in this clone; it initializes Git when
   needed and leaves HEAD on the integration branch (`develop`), which contains
   everything that exists on the production branch. Then claim a task and
   successfully run `.ai/ai git start` before editing; follow the commit and
   independent review flow in `.ai/docs/git-workflow.md`.

Read-only tasks need no branch. Skip Gitflow only when the user explicitly asks
not to use Git. If Git reports dubious ownership, ask approval to trust only
this exact checkout. All AI state stays under .ai/. Claim a task before editing,
checkpoint before your context fills, and never call work done without
`.ai/ai check`.
"""


def upsert_managed(path: str, block: str, force: bool = False) -> str:
    start_marker = "<!-- ai-workspace:start -->"
    end_marker = "<!-- ai-workspace:end -->"
    existing = read_text(path) if os.path.exists(path) else ""
    if start_marker in existing and end_marker in existing:
        if not force:
            return "unchanged"
        start = existing.index(start_marker)
        end = existing.index(end_marker) + len(end_marker)
        updated = existing[:start].rstrip("\n") + "\n" + block.strip() + "\n" + existing[end:].lstrip("\n")
        write_text_atomic(path, updated)
        return "updated"
    separator = "\n\n" if existing.strip() else ""
    write_text_atomic(path, existing.rstrip("\n") + separator + block.strip() + "\n")
    return "written"


def adopt_root(force: bool = False, check: bool = False) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    targets = [
        os.path.join(PROJECT, "AGENTS.md"),
        os.path.join(PROJECT, "CLAUDE.md"),
        os.path.join(PROJECT, ".cursor", "rules", "ai-workspace.mdc"),
        os.path.join(PROJECT, ".github", "copilot-instructions.md"),
    ]
    for path in targets:
        if check:
            existing = read_text(path) if os.path.exists(path) else ""
            state = "ok" if "<!-- ai-workspace:start -->" in existing else "missing"
            results.append((os.path.relpath(path, PROJECT), state))
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if path.endswith(".mdc") and not os.path.exists(path):
            write_text_atomic(
                path,
                "---\ndescription: AI workspace entry rules\nalwaysApply: true\n---\n\n" + ROOT_BLOCK.strip() + "\n",
            )
            results.append((os.path.relpath(path, PROJECT), "written"))
            continue
        results.append((os.path.relpath(path, PROJECT), upsert_managed(path, ROOT_BLOCK, force)))
    return results


# The ledger (tasks/, specs/, docs/decisions/, config/) is the project's memory
# and must be committed; only ephemeral state and generated adapters stay local.
ADOPT_IGNORE_ENTRIES = (
    ".ai/runtime/",
    ".ai/worktrees/",
    "/AGENTS.md",
    "/CLAUDE.md",
    ".cursor/rules/ai-workspace.mdc",
    ".github/copilot-instructions.md",
    ".github/workflows/ai-check.yml",
)


def normalized_ignore_entry(line: str) -> str | None:
    value = line.strip()
    if not value or value.startswith("#") or value.startswith("!"):
        return None
    while value.startswith("/"):
        value = value[1:]
    value = value.replace("\\", "/")
    if value.endswith("/"):
        value = value[:-1]
    return value


def adopt_gitattributes(check: bool = False) -> tuple[str, bool]:
    """Add `* text=auto eol=lf` when the project has no .gitattributes yet.

    Only a missing file is created: rewriting an existing policy is the
    project's decision. The point is to end Windows' "LF will be replaced by
    CRLF" noise and cross-platform diffs on a fresh adopt.
    """
    path = os.path.join(PROJECT, ".gitattributes")
    if os.path.exists(path):
        return "ok", False
    if check:
        return "missing", True
    write_text_atomic(path, "* text=auto eol=lf\n")
    return "created", True


def adopt_gitignore(check: bool = False) -> tuple[str, list[str]]:
    path = os.path.join(PROJECT, ".gitignore")
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as handle:
            existing = handle.read()
    lines = existing.splitlines()
    present = {normalized_ignore_entry(line) for line in lines}
    missing = [
        entry for entry in ADOPT_IGNORE_ENTRIES
        if normalized_ignore_entry(entry) not in present
    ]
    # An older adopt ignored `.ai/` wholesale, which also hid the ledger from the
    # host repository. Migrate that line away instead of leaving it behind.
    blanket = [line for line in lines if normalized_ignore_entry(line) == ".ai"]
    if check:
        return ("ok" if not missing and not blanket else "missing"), missing
    if not missing and not blanket:
        return "unchanged", []

    crlf = chr(13) + chr(10)
    newline = crlf if crlf in existing else chr(10)
    kept = "".join(line + newline for line in lines if normalized_ignore_entry(line) != ".ai")
    addition = newline.join([
        "# Added by ai adopt: only ephemeral workspace state and generated adapters stay local.",
        *missing,
    ]) + newline
    write_text_atomic(path, kept + addition)
    return ("created" if not existing else "updated"), missing


CI_WORKFLOW = """name: ai-workspace

on:
  push:
  pull_request:

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Workspace health
        run: python .ai/ai.py doctor --strict
      - name: Verification contract
        run: python .ai/ai.py check --strict
"""


def write_ci() -> None:
    path = os.path.join(PROJECT, ".github", "workflows", "ai-check.yml")
    if os.path.exists(path):
        print(f"CI workflow already exists: {os.path.relpath(path, PROJECT)}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text_atomic(path, CI_WORKFLOW)
    print(f"CI workflow: {os.path.relpath(path, PROJECT)}")
