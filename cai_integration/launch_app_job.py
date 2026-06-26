#!/usr/bin/env python3
"""
CML Application entry point for the CAI Eval Platform.

CML requires a Python script as the entry point (not a bash script).
This script activates the venv and delegates to start_app.py via a bash
wrapper.

Configure this as a CML *Application* (persistent service) so that
FastAPI + nginx stay running after the script launches them.
"""

import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    # CML runs application scripts in an IPython-style engine where __file__
    # is not defined. CML clones the repo into /home/cdsw and runs from there.
    try:
        return Path(__file__).parent.parent.resolve()
    except NameError:
        for cand in ("/home/cdsw", os.getcwd()):
            if (Path(cand) / ".git").is_dir():
                return Path(cand).resolve()
        return Path("/home/cdsw")


REPO_ROOT = _repo_root()


def main() -> None:
    wrapper = REPO_ROOT / "cai_integration" / "launch_app.sh"
    if not wrapper.exists():
        raise RuntimeError(f"launch_app.sh not found at {wrapper}")

    result = subprocess.run(["bash", str(wrapper)], cwd=str(REPO_ROOT))
    if result.returncode != 0:
        raise RuntimeError(f"launch_app.sh exited with code {result.returncode}")


if __name__ == "__main__":
    main()
