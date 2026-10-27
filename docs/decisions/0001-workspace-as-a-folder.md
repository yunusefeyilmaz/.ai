# 0001 - The workspace is a self-contained folder

- Status: accepted
- Date: 2026-10-27
- Deciders: project maintainers

## Context

AI agents need durable context, a task flow and a place for generated clutter.
Hosted task trackers and chat history do not travel with a repository, and they
cannot be read by an arbitrary agent on an arbitrary machine. A project also
should not be polluted by agent scratch files.

## Decision

Ship the entire system as a `.ai/` folder that can be cloned into any project.
All AI state — tasks, specs, decisions, logs, locks and scratch artifacts — lives
inside it. The project outside `.ai/` contains product code only.

The protocol is plain Markdown and files so any agent can follow it. A small
stdlib-only Python CLI automates the race-sensitive operations and is optional.

## Consequences

- Cloning or copying one folder is the whole installation.
- The workspace can be deleted without touching product code.
- Multiple agents coordinate through the filesystem, not a hosted service.
- Git ignores `runtime/`, so transient state never leaks into history.
- Cross-clone coordination still relies on branches and pull requests.

## Alternatives

- **Hosted task tracker.** Better dashboards, but no offline use, no agent-native
  file context, and credentials become a requirement.
- **A daemon or database.** Stronger locking, but a runtime service to install,
  start and keep alive — contrary to "clone and work".
- **Root-level files only.** Simpler for one agent, but the project tree fills
  with AI output and there is no quarantine boundary.
