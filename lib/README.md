# lib

All behavior of the `ai` CLI. `ai.py` (one level up) only builds the parser and
dispatches. Each folder owns its code **and** the data it manages.

`lib/` contains **only scripts**. The data they manage stays in its original
folder next to `ai.py`.

```
lib/                                   scripts            data they manage (outside lib)
├── core/       paths · fsio · timeutil · findings        -
├── config/     settings · adopt                          config/workspace.json
├── runtime/    leases · mutex · events · checkpoints     runtime/{artifacts,locks,logs,state}
│               · evidence · health · reset · overview
├── tasks/      store · lifecycle · board · gates         tasks/{active,done}, tasks/BOARD.md
│               · workflow · discard · links
├── specs/      spec                                      specs/{active,done}
├── git/        repo · flow                               templates/git/
├── decisions/  adr                                       docs/decisions/
├── cmd/        one file per command group                -
└── tests/      stdlib unittest, black-box via ai.py      -
skills/ (outside lib)  optional extensions, same register(sub) contract
```

## Layers (imports go downward only)

```
cmd, skills          command layer: parse args, print, return an exit code
   │
tasks · git · specs · decisions     domain logic
   │
runtime              locks, checkpoints, events, evidence, health
   │
config · core        settings, paths, atomic IO, time   (core imports nothing from lib)
```

`lib/runtime/{leases,mutex,events,dirs}`, `lib/config/settings` and `lib/core/*` are leaf modules: they may be imported with
`from x import name`. Everything above them is imported as a module
(`from lib.tasks import store`; `store.find_task(...)`), which keeps call sites
greppable and allows the occasional cycle between `tasks` and `git`.

## How the parts call each other (typical flow)

| User/agent runs | cmd module | Uses |
|---|---|---|
| `ai now` | `cmd/now` | `runtime/overview` → `tasks/workflow`, `git/repo`, `runtime/checkpoints`, `runtime/evidence` |
| `ai task claim` | `cmd/task` | `tasks/lifecycle.claim_task` → `runtime/leases.acquire_lock`, `tasks/store`, `tasks/board`, `runtime/events` |
| `ai task review` / `done` | `cmd/task` | `tasks/gates` (rules) → `runtime/evidence`, `tasks/store` |
| `ai git start/commit/finish` | `cmd/git` → `git/flow` | `git/repo`, `runtime/leases` (`@git/index`), `tasks/store` |
| `ai checkpoint` / `resume` | `cmd/checkpoint` | `runtime/checkpoints`, `git/repo` (drift) |
| `ai check` | `cmd/doctor` | `runtime/health`, `runtime/evidence` (records the result) |

## Add a command

Create `lib/cmd/<name>.py`:

```python
ORDER = 200                      # optional, position in --help

def cmd_hello(args) -> int:
    print("hello")
    return 0

def register(sub) -> None:       # discovered automatically; no table to edit
    p = sub.add_parser("hello", help="say hello")
    p.set_defaults(func=cmd_hello)
```

Put real logic in the matching domain folder, not in the command file, so other
commands and skills can reuse it. Add a test in `lib/tests/` and list the
command in `AGENTS.md` if agents need it.

## Add a skill (future)

`skills/<name>/skill.py` (at the workspace root, outside `lib/`) with the same
`register(sub)` contract is loaded by `ai.py` automatically. A skill keeps its
own prompts, templates and data in its folder and may call any `lib/` layer.
See `skills/README.md`.

## Tests

```sh
python lib/tests/run.py              # parallel, one process per module (-j N)
python lib/tests/run.py test_doctor  # selected modules
python -m unittest discover -s lib/tests -q   # serial
```
