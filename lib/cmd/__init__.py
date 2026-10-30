"""CLI command layer.

Every module in this package (and in `skills/*/skill.py` at the workspace root) that defines
`register(sub)` is a command group. `ai.py` discovers them automatically, so a
new command is one new file: no central table to edit.

    ORDER = 100                       # optional, controls --help ordering
    def register(sub): ...            # add parsers, set_defaults(func=...)
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import re


def _modules_declaring(path: str, command: str) -> list[str]:
    pattern = re.compile(r'add_parser\(\s*"%s"' % re.escape(command))
    found = []
    for info in pkgutil.iter_modules([path]):
        if info.name.startswith("_"):
            continue
        try:
            with open(os.path.join(path, info.name + ".py"), encoding="utf-8") as handle:
                if pattern.search(handle.read()):
                    found.append(info.name)
        except OSError:
            continue
    return found


def _load(package: str, path: str) -> list:
    modules = []
    for info in pkgutil.iter_modules([path]):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        if hasattr(module, "register"):
            modules.append(module)
    return modules


def discover(command: str | None = None) -> list:
    """Return command modules ordered by (ORDER, name).

    With `command` (the first CLI argument) only the modules that declare that
    parser are imported, which roughly halves startup time. If none matches
    (--help, unknown command, skills) everything is loaded.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if command and not command.startswith("-"):
        wanted = _modules_declaring(here, command)
        if wanted:
            loaded = [importlib.import_module(f"lib.cmd.{name}") for name in wanted]
            return sorted(loaded, key=lambda m: (getattr(m, "ORDER", 1000), m.__name__))
    modules = _load("lib.cmd", here)
    skills = os.path.join(os.path.dirname(os.path.dirname(here)), "skills")
    if os.path.isdir(skills):
        for entry in sorted(os.listdir(skills)):
            if os.path.isfile(os.path.join(skills, entry, "skill.py")):
                module = importlib.import_module(f"skills.{entry}.skill")
                if hasattr(module, "register"):
                    modules.append(module)
    return sorted(modules, key=lambda m: (getattr(m, "ORDER", 1000), m.__name__))
