#!/usr/bin/env python3
"""
Launch the CAI Eval Platform from INSIDE a CML project.

Run this in a CML Session or Job (not GitHub Actions). It reuses the workspace
credentials CML injects into every session (CDSW_API_URL / CDSW_APIV2_KEY) and
auto-detects the project from CDSW_PROJECT_ID, so no external CML_HOST /
CML_API_KEY is required.

    # In a CML Session terminal:
    python cai_integration/launch_in_project.py
    # or standalone Phoenix mode:
    python cai_integration/launch_in_project.py --standalone-phoenix

This is a thin wrapper around create_applications.py — the same code GitHub
Actions runs. See cai_integration/DEPLOY.md for the manual CML UI alternative.
"""

import argparse
import os
import sys

from create_applications import ApplicationManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the CAI Eval Platform from inside CML")
    parser.add_argument(
        "--project-id",
        default=os.environ.get("CDSW_PROJECT_ID"),
        help="CML project ID (defaults to CDSW_PROJECT_ID, injected in-project)",
    )
    parser.add_argument(
        "--standalone-phoenix",
        action="store_true",
        help="Deploy Phoenix and the eval API as two separate apps instead of one",
    )
    args = parser.parse_args()

    if not args.project_id:
        print("Error: CDSW_PROJECT_ID not set and --project-id not given.")
        print("   Run this inside a CML Session/Job, or pass --project-id <id>.")
        sys.exit(1)

    manager = ApplicationManager()  # picks up CDSW_API_URL / CDSW_APIV2_KEY
    ok = manager.run(args.project_id, standalone_phoenix=args.standalone_phoenix)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
