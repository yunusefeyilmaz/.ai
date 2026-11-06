"""git.setup: initialize Gitflow (branches, commit template, baseline commit).

Split out of `git/flow.py` so that file keeps only branch/commit/merge flow.
"""

from __future__ import annotations

import json
import os
import sys

from lib.core.paths import PROJECT, WORKSPACE
from lib.git import repo

BASELINE_COMMIT_MESSAGE = "chore: add ai workspace baseline"
_WORKSPACE_PREFIX = os.path.relpath(WORKSPACE, PROJECT).replace(os.sep, "/") + "/"


def baseline_paths() -> list[str]:
    """The only paths `ai adopt` may commit: the workspace ledger and .gitignore.

    Root adapters (AGENTS.md, CLAUDE.md, ...) are listed in .gitignore by adopt
    itself, so they are never part of a product commit. A `.ai` folder that is a
    bare gitlink cannot be staged as files, so it is left out and reported.
    """
    candidates = [
        WORKSPACE,
        os.path.join(PROJECT, ".gitignore"),
        os.path.join(PROJECT, ".gitattributes"),
    ]
    try:
        gitlink = repo.workspace_gitlink()
    except (OSError, ValueError):
        gitlink = None
    return [
        os.path.relpath(path, PROJECT).replace(os.sep, "/")
        for path in candidates
        if os.path.exists(path) and not (gitlink and os.path.abspath(path) == os.path.abspath(WORKSPACE))
    ]


def _print_baseline_commands(integration: str, paths: list[str]) -> None:
    print("Run exactly these commands, then retry `ai adopt`:")
    print(f"  git checkout {integration}")
    print("  git add -A -- " + " ".join(paths))
    print(f'  git commit -m "{BASELINE_COMMIT_MESSAGE}"')


def commit_workspace_baseline() -> int:
    """Commit the .ai/ and .gitignore baseline on the integration branch.

    `ai adopt` on an existing Git repository used to leave both untracked, so
    the first `ai start` refused with a dirty tree. Only the workspace baseline
    is committed here; product files are never touched.
    """
    state = repo.git_state()
    if not state.get("repo"):
        print(
            "Git: no repository yet. `ai git setup` initializes it and commits the "
            "baseline (including .ai/ and .gitignore)."
        )
        return 0
    if not state.get("head"):
        print(
            "Git: the repository has no commit yet. Run `ai git setup`; its initial "
            "baseline commit includes .ai/ and .gitignore."
        )
        return 0
    config = repo.git_config()
    integration = config["integration"]
    paths = baseline_paths()
    if not paths:
        return 0
    if not repo.branch_exists(integration):
        base = (
            repo.git_commit_id(f"refs/heads/{config['production']}")
            or str(state.get("head") or "")
        )
        code, _, err = repo.run_git(["branch", integration, base])
        if code != 0:
            print(
                f"Could not create the integration branch '{integration}': {err}",
                file=sys.stderr,
            )
            _print_baseline_commands(integration, paths)
            return 1
    if repo.git_state().get("branch") != integration:
        code, _, err = repo.run_git(["checkout", integration])
        if code != 0:
            print(
                f"Could not switch to the integration branch '{integration}': {err}",
                file=sys.stderr,
            )
            _print_baseline_commands(integration, paths)
            return 1
    code, _, err = repo.run_git(["add", "-A", "--", *paths])
    if code != 0:
        print(f"Could not stage the workspace baseline: {err}", file=sys.stderr)
        _print_baseline_commands(integration, paths)
        return 1
    staged_code, _, _ = repo.run_git(["diff", "--cached", "--quiet", "--", *paths])
    if staged_code == 0:
        print(f"Workspace baseline already committed on {integration}; nothing to commit.")
    else:
        code, _, err = repo.run_git(
            ["commit", "-m", BASELINE_COMMIT_MESSAGE, "--", *paths]
        )
        if code != 0:
            # Leave the tree exactly as it was before the attempt.
            repo.run_git(["reset", "-q", "--", *paths])
            print(
                f"Could not commit the workspace baseline: {err}", file=sys.stderr
            )
            _print_baseline_commands(integration, paths)
            return 1
        print(f"Workspace baseline committed on {integration}: {BASELINE_COMMIT_MESSAGE}")
    leftover = [
        path for path in repo.git_state().get("dirty", [])
        if path != ".gitignore" and not path.startswith(_WORKSPACE_PREFIX)
    ]
    if leftover:
        print(
            "Working tree still has changes outside the workspace baseline: "
            + ", ".join(leftover[:5])
            + (" ..." if len(leftover) > 5 else "")
        )
    print(f"HEAD: {integration}")
    return 0


def setup_git(yes: bool = False, json_out: bool = False) -> int:
    """Initialize Gitflow. Called by the CLI and by `ai start`."""
    state = repo.git_state()
    if not state.get("repo") and state.get("error"):
        error = str(state["error"])
        if "dubious ownership" in error.lower():
            project_path = os.path.abspath(PROJECT).replace("\\", "/")
            print(
                "Git found this repository but refused it because its ownership is untrusted. "
                "Ask the user to approve this exact checkout with `git config --global "
                f"--add safe.directory \"{project_path}\"`, then rerun `ai git setup`. "
                "Do not use a wildcard safe.directory entry.",
                file=sys.stderr,
            )
            return 1
        if "not a git repository" not in error.lower():
            print(f"Could not inspect the project Git repository: {error}", file=sys.stderr)
            return 1

    initialized = False
    if not state.get("repo"):
        production = repo.git_config()["production"]
        code, _, err = repo.run_git(["init", f"--initial-branch={production}"])
        if code != 0 and any(
            marker in err.lower()
            for marker in ("unknown option", "unrecognized option", "unknown switch")
        ):
            code, _, err = repo.run_git(["init"])
        if code != 0:
            print(f"Could not initialize Git in {PROJECT}: {err}", file=sys.stderr)
            return 1
        code, _, err = repo.run_git(["symbolic-ref", "HEAD", f"refs/heads/{production}"])
        if code != 0:
            print(f"Could not select the production branch: {err}", file=sys.stderr)
            return 1
        initialized = True
        state = repo.git_state()
        if not state.get("repo"):
            print(f"Git initialization did not produce a readable repository: {state.get('error') or 'unknown error'}", file=sys.stderr)
            return 1
    config = repo.git_config()
    template = repo.git_template_path()
    if not os.path.isfile(template):
        print(f"Commit template not found: {os.path.relpath(template, PROJECT)}", file=sys.stderr)
        return 1
    try:
        gitlink = repo.workspace_gitlink()
    except (OSError, ValueError):
        gitlink = None
    if gitlink:
        print(
            f"WARN  {gitlink} is a bare gitlink in this repository (it is its own clone and "
            "there is no .gitmodules). The ledger cannot be committed as files. Decide how it "
            "is versioned: `git submodule add <url> .ai` (pinned commit) or `git rm --cached "
            f"{gitlink}` plus `{gitlink}/` in .gitignore.",
            file=sys.stderr,
        )
    config_code, current_template, _ = repo.run_git(["config", "--local", "--get", "commit.template"])
    if (
        config_code != 0
        or os.path.normcase(os.path.abspath(current_template)) != os.path.normcase(os.path.abspath(template))
    ):
        code, _, err = repo.run_git(["config", "--local", "commit.template", template])
        if code != 0:
            print(f"Could not set commit.template: {err}", file=sys.stderr)
            return 1
    created_production = False
    created_integration = False
    created_baseline = False
    if repo.branch_ref_exists(config["production"]) and not repo.branch_exists(config["production"]):
        print(
            f"Production branch '{config['production']}' exists but does not resolve to a commit. "
            "Repair that ref manually before rerunning setup.",
            file=sys.stderr,
        )
        return 1
    if not state.get("head"):
        refs_code, refs_output, refs_err = repo.run_git([
            "for-each-ref", "--format=%(refname:short)", "refs/heads",
        ])
        if refs_code != 0:
            print(f"Could not inspect local Git branches: {refs_err}", file=sys.stderr)
            return 1
        refs: list[tuple[str, str]] = []
        for line in refs_output.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            commit = repo.git_commit_id(f"refs/heads/{candidate}")
            if commit:
                refs.append((candidate, commit))
        if repo.branch_exists(config["production"]):
            pass
        elif refs:
            current_ref = f"refs/heads/{state.get('branch')}"
            base_commit = next(
                (commit for ref, commit in refs if ref == current_ref), refs[0][1],
            )
            code, _, err = repo.run_git(["branch", config["production"], base_commit])
            if code != 0:
                print(f"Could not create production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            created_production = True
        else:
            code, _, err = repo.run_git(["symbolic-ref", "HEAD", f"refs/heads/{config['production']}"])
            if code != 0:
                print(f"Could not select production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            completed, result = repo.confirm_initial_baseline(
                config["production"], assume_yes=yes, json_out=json_out
            )
            if not completed:
                return result
            created_baseline = True
            created_production = True
        if not repo.branch_exists(config["production"]):
            print(f"Production branch '{config['production']}' is still missing.", file=sys.stderr)
            return 1
        state = repo.git_state()
        if not state.get("head"):
            code, _, err = repo.run_git(["symbolic-ref", "HEAD", f"refs/heads/{config['production']}"])
            if code != 0:
                print(f"Could not select production branch '{config['production']}': {err}", file=sys.stderr)
                return 1
            state = repo.git_state()
        if not state.get("head"):
            print("Gitflow setup could not establish a committed production base.", file=sys.stderr)
            return 1
    elif not repo.branch_exists(config["production"]):
        head_commit = state.get("head") or repo.git_commit_id("HEAD")
        if not head_commit:
            print("Cannot create the production branch: current HEAD has no commit.", file=sys.stderr)
            return 1
        code, _, err = repo.run_git(["branch", config["production"], head_commit])
        if code != 0:
            print(f"Could not create production branch '{config['production']}': {err}", file=sys.stderr)
            return 1
        created_production = True
    if not repo.branch_exists(config["integration"]):
        if repo.branch_ref_exists(config["integration"]):
            print(
                f"Integration branch '{config['integration']}' exists but does not resolve to a commit. "
                "Repair that ref manually before rerunning setup.",
                file=sys.stderr,
            )
            return 1
        production_commit = repo.git_commit_id(f"refs/heads/{config['production']}")
        if not production_commit:
            print(
                f"Cannot create integration branch '{config['integration']}': "
                f"production branch '{config['production']}' has no commit.",
                file=sys.stderr,
            )
            return 1
        code, _, err = repo.run_git([
            "branch", config["integration"], production_commit,
        ])
        if code != 0:
            print(f"Could not create integration branch '{config['integration']}': {err}", file=sys.stderr)
            return 1
        created_integration = True
    # Feature branches start from the integration branch. If it lags behind
    # production, every commit made on production (config, checks, docs) is
    # invisible to the work and the review gate can pass without running
    # anything. So: leave HEAD on the integration branch and make sure it
    # contains production's current commit.
    integration = config["integration"]
    production = config["production"]
    current_branch = repo.git_state().get("branch")
    checked_out_integration = False
    if current_branch != integration and (
        created_integration or current_branch in (production, "detached")
    ):
        code, _, err = repo.run_git(["checkout", integration])
        if code != 0:
            print(f"Could not switch to the integration branch '{integration}': {err}", file=sys.stderr)
            print(f"Run this yourself, then rerun setup: git checkout {integration}", file=sys.stderr)
            return 1
        checked_out_integration = True
    fast_forwarded_integration = False
    production_commit = repo.git_commit_id(f"refs/heads/{production}")
    integration_commit = repo.git_commit_id(f"refs/heads/{integration}")
    if production_commit and integration_commit:
        contains, _, _ = repo.run_git([
            "merge-base", "--is-ancestor", production_commit, integration_commit,
        ])
        if contains != 0:
            behind, _, _ = repo.run_git([
                "merge-base", "--is-ancestor", integration_commit, production_commit,
            ])
            if behind != 0:
                print(
                    f"Integration branch '{integration}' and production branch "
                    f"'{production}' have diverged; refusing to rewrite either. "
                    "Merge them deliberately, then rerun setup:",
                    file=sys.stderr,
                )
                print(f"  git checkout {integration}", file=sys.stderr)
                print(f"  git merge {production}", file=sys.stderr)
                return 1
            if repo.git_state().get("branch") != integration:
                print(
                    f"Integration branch '{integration}' does not contain production's "
                    f"latest commit. Run this yourself, then rerun setup:",
                    file=sys.stderr,
                )
                print(f"  git checkout {integration}", file=sys.stderr)
                print(f"  git merge --ff-only {production}", file=sys.stderr)
                return 1
            code, _, err = repo.run_git(["merge", "--ff-only", production])
            if code != 0:
                print(
                    f"Could not fast-forward '{integration}' to '{production}': {err}. "
                    "Commit or stash the listed files, then rerun setup.",
                    file=sys.stderr,
                )
                print(f"  git checkout {integration}", file=sys.stderr)
                print(f"  git merge --ff-only {production}", file=sys.stderr)
                return 1
            fast_forwarded_integration = True
    if json_out:
        print(json.dumps({
            "repo": True,
            "commitTemplate": os.path.relpath(template, PROJECT).replace(os.sep, "/"),
            "integration": config["integration"],
            "production": config["production"],
            "initializedRepository": initialized,
            "createdBaseline": created_baseline,
            "createdProduction": created_production,
            "createdIntegration": created_integration,
            "checkedOutIntegration": checked_out_integration,
            "fastForwardedIntegration": fast_forwarded_integration,
            "head": repo.git_state().get("branch"),
        }, indent=2))
        return 0
    print(f"commit.template = {os.path.relpath(template, PROJECT)}")
    if initialized:
        print("Git repository: initialized")
    if created_baseline:
        print(f"production branch: {config['production']} (created with the confirmed baseline)")
    else:
        print(f"production branch: {config['production']}" + (" (created)" if created_production else " (exists)"))
    print(f"integration branch: {config['integration']}" + (" (created)" if created_integration else " (exists)"))
    if fast_forwarded_integration:
        print(f"integration branch: fast-forwarded to {config['production']}")
    print(f"HEAD: {repo.git_state().get('branch')}" + (" (checked out)" if checked_out_integration else ""))
    print("Next: ai task claim <id> --agent <name>, then ai git start ...")
    return 0
