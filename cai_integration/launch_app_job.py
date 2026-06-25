#!/usr/bin/env python3
"""
CML Application / Job entry point for the CAI Eval Platform.

CML requires a Python script as the entry point (not a bash script).
This script activates the venv and delegates to start_app.py via a bash
wrapper, matching the pattern established in ray-serve-cai/cai_integration.

Configure this as a CML *Application* (persistent service) so that
Phoenix + FastAPI + nginx stay running after the script launches them.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()


def main() -> int:
    wrapper = REPO_ROOT / "cai_integration" / "launch_app.sh"
    if not wrapper.exists():
        print(f"ERROR: launch_app.sh not found at {wrapper}")
        return 1

    result = subprocess.run(
        ["bash", str(wrapper)],
        cwd=str(REPO_ROOT),
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
