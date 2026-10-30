# skills

Reserved for optional extensions (data/prompts live here; shared scripts stay in `lib/`). Nothing here is required by the core.

A skill is a folder with a `skill.py`:

```
skills/<name>/
├── skill.py        defines register(sub) (same contract as lib/cmd/*.py)
├── README.md       what it does and when an agent should use it
└── ...             prompts, templates, data the skill owns
```

Rules: depend downward only (tasks, git, runtime, config, core); never edit the
core's state files directly, use the library functions; keep output short
(agents pay per token); add black-box tests in `lib/tests/`.
