"""specs.spec: split out of the former monolithic ai.py."""

from __future__ import annotations

import os
import re

from lib.core.paths import (
    PROJECT,
    SPECS_DIR,
    SPECS_TEMPLATE,
    WORKSPACE,
)
from lib.core.fsio import (
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


def spec_from_template(title: str, task_id: str) -> str:
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
    return text


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
    if re.fullmatch(r"\d{1,4}", spec):
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
