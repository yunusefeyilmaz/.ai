"""specs.spec: split out of the former monolithic ai.py."""

from __future__ import annotations

import os
import re

from lib.core.fsio import (
    MAX_TASK_ID_DIGITS,
    normalize_id,
    read_text,
    write_text_atomic,
)
from lib.core.paths import (
    PROJECT,
    SPECS_ACTIVE_DIR,
    SPECS_DIR,
    SPECS_DONE_DIR,
    SPECS_TEMPLATE,
    WORKSPACE,
)

FALLBACK_SPEC = """---
status: draft
task: {task_id}
approved_by: null
approved_on: null
---

# {title}

## Intent

<!-- The problem in one paragraph. What changes for the user? Why now? -->

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] Criterion one, observable and independently testable
- [ ] Criterion two
- [ ] Existing behavior X still holds

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
"""


PLACEHOLDER_CRITERIA = (
    "criterion one", "criterion two", "existing behavior x still holds",
    "observable criterion one", "observable criterion two",
)

CRITERION = re.compile(r"^\s*- \[(?P<mark>[ xX])\]\s*(?P<text>.*)$")


def spec_from_template(
    title: str, task_id: str, intent: str | None = None, acceptance: list[str] | None = None
) -> str:
    """Fill the repository spec template, or a compatible fallback."""
    text = None
    if os.path.isfile(SPECS_TEMPLATE):
        try:
            text = read_text(SPECS_TEMPLATE)
        except OSError:
            text = None
    if not text:
        text = FALLBACK_SPEC
    text = text.replace("task: null", f"task: {task_id}", 1)
    text = text.replace("# <title>", f"# {title}", 1)
    if intent:
        text = re.sub(r"(## Intent\n\n)<!--.*?-->", lambda m: m.group(1) + intent, text, count=1, flags=re.S)
    if acceptance:
        block = "\n".join(f"- [ ] {item}" for item in acceptance)
        text = re.sub(
            r"(## Acceptance criteria\n\n).*?(\n## )", lambda m: m.group(1) + block + "\n" + m.group(2),
            text, count=1, flags=re.S,
        )
    return text


def _criteria_section(text: str):
    return re.search(r"## Acceptance criteria\n(.*?)(?:\n## |\Z)", text, flags=re.S)


def acceptance_criteria(text: str) -> list[tuple[bool, str]]:
    """The `- [ ]`/`- [x]` bullets under "## Acceptance criteria", in order.

    One parser for the claim gate, `ai doctor`, `ai spec` and `ai review`, so a
    reviewer is never shown a different list - or a different tick - than the one
    the gate judged. The result is `(ticked, text)` per criterion.
    """
    match = _criteria_section(text)
    if not match:
        return []
    criteria = []
    for line in match.group(1).splitlines():
        item = CRITERION.match(line)
        if item:
            criteria.append((item.group("mark").lower() == "x", item.group("text").strip()))
    return criteria


def criterion_texts(criteria: list[tuple[bool, str]]) -> list[str]:
    """The text of each criterion, for callers that do not care about the box."""
    return [text for _, text in criteria]


def real_criteria(criteria: list[tuple[bool, str]]) -> list[tuple[bool, str]]:
    """Criteria that are not the template's placeholders."""
    return [(done, text) for done, text in criteria if text and not text.lower().startswith(PLACEHOLDER_CRITERIA)]


def criteria_progress(criteria: list[tuple[bool, str]]) -> tuple[int, int]:
    """(done, total) over the real criteria, ignoring template placeholders."""
    real = real_criteria(criteria)
    return sum(1 for done, _ in real if done), len(real)


def unticked_criteria(text: str) -> list[tuple[int, str]]:
    """Real criteria still unticked as `(1-based position, text)`.

    The position counts every criterion in the section (placeholders included), so
    it is the number `ai spec check <task> <n>` expects.
    """
    out = []
    for position, (done, criterion) in enumerate(acceptance_criteria(text), start=1):
        if done or not criterion:
            continue
        if criterion.lower().startswith(PLACEHOLDER_CRITERIA):
            continue
        out.append((position, criterion))
    return out


def tick_criterion(text: str, number: int) -> tuple[str, bool]:
    """Tick criterion `number` (1-based) in `text`; return `(new_text, changed)`.

    Idempotent: ticking an already ticked criterion changes nothing and reports
    `changed=False`. Raises `ValueError` when the number is out of range.
    """
    criteria = acceptance_criteria(text)
    if number < 1 or number > len(criteria):
        raise ValueError(f"there are {len(criteria)} acceptance criteria; {number} is out of range")
    match = _criteria_section(text)
    if not match:
        raise ValueError("the spec has no '## Acceptance criteria' section")
    section = match.group(1)
    rebuilt = []
    position = 0
    changed = False
    for line in section.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content):]
        if CRITERION.match(content):
            position += 1
            if position == number:
                if criteria[number - 1][0]:
                    rebuilt.append(line)
                    continue
                content = re.sub(r"^(\s*)- \[ \]", r"\1- [x]", content, count=1)
                changed = True
                line = content + ending
        rebuilt.append(line)
    new_text = text[: match.start(1)] + "".join(rebuilt) + text[match.end(1):]
    return new_text, changed


def mark_status(text: str, status: str) -> str:
    """Set the frontmatter `status:` line, leaving the rest of the spec untouched."""
    match = re.search(r"\A---\n(.*?)\n---\n", text, flags=re.S)
    if not match:
        return text
    frontmatter = match.group(1)
    if re.search(r"^status:", frontmatter, flags=re.M):
        updated = re.sub(r"^status:.*$", f"status: {status}", frontmatter, count=1, flags=re.M)
        return text[: match.start(1)] + updated + text[match.end(1):]
    return text[: match.start(1)] + f"status: {status}\n" + text[match.start(1):]


def spec_unticked(meta: dict) -> list[tuple[int, str]]:
    """Real criteria still unticked in the task's linked spec ([] when it has none)."""
    path = resolve_spec_path(meta)
    if not path:
        return []
    try:
        return unticked_criteria(read_text(path))
    except OSError:
        return []


def spec_problem(meta: dict) -> str | None:
    """Why this task's spec is not ready for work ("no spec, no code"), or None.

    A task created with `--no-spec` (spec: null) is exempt on purpose. Otherwise the
    spec must exist and carry at least one acceptance criterion that is not the
    template's placeholder.
    """
    ref = str(meta.get("spec") or "")
    if not ref or ref == "null":
        return None
    absolute = os.path.normpath(os.path.join(WORKSPACE, ref))
    if not os.path.isfile(absolute):
        return f"spec {ref} does not exist"
    try:
        text = read_text(absolute)
    except OSError:
        return f"spec {ref} cannot be read"
    if not real_criteria(acceptance_criteria(text)):
        return f"spec {ref} has no acceptance criteria yet (it is still the template)"
    return None


def archive_spec(meta: dict) -> str | None:
    """Move a finished task's spec from specs/active to specs/done; return its new reference.

    The archived copy is marked `status: shipped`: a shipped spec that still says
    `draft` claims the work never happened.
    """
    ref = str(meta.get("spec") or "")
    if not ref:
        return None
    absolute = os.path.normpath(os.path.join(WORKSPACE, ref))
    active = os.path.normpath(SPECS_ACTIVE_DIR)
    if os.path.dirname(absolute) != active or not os.path.isfile(absolute):
        return None
    os.makedirs(SPECS_DONE_DIR, exist_ok=True)
    target = os.path.join(SPECS_DONE_DIR, os.path.basename(absolute))
    if os.path.exists(target):
        return None
    os.replace(absolute, target)
    try:
        write_text_atomic(target, mark_status(read_text(target), "shipped"))
    except OSError:
        pass
    return os.path.relpath(target, WORKSPACE).replace(os.sep, "/")


def resolve_spec_path(meta: dict | None) -> str | None:
    if not meta:
        return None
    spec = meta.get("spec")
    if not spec:
        return None
    spec = str(spec).strip()
    candidates = []
    if os.path.isabs(spec):
        candidates.append(spec)
    else:
        candidates.extend([os.path.join(PROJECT, spec), os.path.join(WORKSPACE, spec)])
    if re.fullmatch(rf"\d{{1,{MAX_TASK_ID_DIGITS}}}", spec):
        prefix = normalize_id(spec) + "-"
        for folder in ("active", "done"):
            directory = os.path.join(SPECS_DIR, folder)
            if os.path.isdir(directory):
                for name in sorted(os.listdir(directory)):
                    if name.startswith(prefix) and name.endswith(".md"):
                        candidates.append(os.path.join(directory, name))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None
