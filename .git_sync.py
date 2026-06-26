#!/usr/bin/env python3
"""
Git sync job for the CAI Eval Platform CML deployment.

Root job in the CML job chain (see cai_integration/jobs_config.yaml):
    git_sync  ->  setup_eval_env

Pulls the latest code from the project's git remote into the CML project
working directory so that every deploy runs against current code, then lets
CML auto-trigger the dependent setup_eval_env job.

The CML project is created from a git template, so the project working
directory (default /home/cdsw) is itself the git clone.

Env vars:
    GIT_SYNC_DIR     repo dir to sync (default: this script's directory)
    GIT_SYNC_BRANCH  branch to reset to (default: main)
"""

import os
import subprocess
import sys

def _repo_dir() -> str:
    # CML runs job scripts in an IPython-style engine where __file__ is not
    # defined, so fall back to the project working directory (CML jobs run
    # from the project root, e.g. /home/cdsw).
    if os.environ.get("GIT_SYNC_DIR"):
        return os.environ["GIT_SYNC_DIR"]
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.environ.get("CDSW_PROJECT", os.getcwd())


REPO_DIR = _repo_dir()
BRANCH = os.environ.get("GIT_SYNC_BRANCH", "main")


def run(cmd) -> bool:
    print(f"Running: {cmd}  (cwd={REPO_DIR})")
    result = subprocess.run(
        cmd, shell=True, cwd=REPO_DIR, capture_output=True, text=True
    )
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(f"Error output: {result.stderr}")
        return False
    return True


def main() -> int:
    print("=" * 70)
    print("CAI Eval Platform — Git Sync")
    print("=" * 70)
    print(f"Repo dir: {REPO_DIR}")
    print(f"Branch:   {BRANCH}")

    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        print(f"{REPO_DIR} is not a git repository — nothing to sync.")
        # Not fatal: a freshly cloned project is already up to date.
        return 0

    # fetch + hard reset so local matches the remote branch exactly,
    # discarding any drift in the project working copy.
    if not run("git fetch origin --prune"):
        print("git fetch failed")
        return 1
    if not run(f"git reset --hard origin/{BRANCH}"):
        print(f"git reset to origin/{BRANCH} failed")
        return 1

    run("git rev-parse --short HEAD")
    print("Git sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
