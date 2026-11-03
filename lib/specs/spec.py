"""specs.spec: split out of the former monolithic ai.py."""

from __future__ import annotations

import os
import re

from lib.core.paths import (
    PROJECT,
    SPECS_ACTIVE_DIR,
    SPECS_DIR,
    SPECS_DONE_DIR,
    SPECS_TEMPLATE,
    WORKSPACE,
)
from lib.core.fsio import (
    MAX_TASK_ID_DIGITS,
    normalize_id,
    read_text,
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
    match = re.search(r"## Acceptance criteria\n(.*?)(?:\n## |\Z)", text, flags=re.S)
    criteria = [
        line[5:].strip() if line.lstrip().startswith("- [") else line.strip()
        for line in (match.group(1).splitlines() if match else [])
        if line.lstrip().startswith("- [")
    ]
    real = [c for c in criteria if c and not c.lower().startswith(PLACEHOLDER_CRITERIA)]
    if not real:
        return f"spec {ref} has no acceptance criteria yet (it is still the template)"
    return None


def archive_spec(meta: dict) -> str | None:
    """Move a finished task's spec from specs/active to specs/done; return its new reference."""
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
