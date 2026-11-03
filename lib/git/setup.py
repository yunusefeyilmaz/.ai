"""git.setup: initialize Gitflow (branches, commit template, baseline commit).

Split out of `git/flow.py` so that file keeps only branch/commit/merge flow.
"""

from __future__ import annotations

import json
import os
import sys

from lib.core.paths import PROJECT
from lib.git import repo


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
    print("Next: ai task claim <id> --agent <name>, then ai git start ...")
    return 0
