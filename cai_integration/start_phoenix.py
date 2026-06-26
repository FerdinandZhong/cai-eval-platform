#!/usr/bin/env python3
"""
Standalone Phoenix CML Application entry point.

Runs Phoenix on CDSW_APP_PORT so CML can route external traffic directly
to it. No nginx needed — CML handles TLS termination and the external URL.

Env vars:
  CDSW_APP_PORT        — external port CML assigns  (default: 8080)
  PHOENIX_WORKING_DIR  — persistent storage for traces (default: /home/cdsw/cai-eval-data/phoenix)
"""

import os
import subprocess
from pathlib import Path

APP_PORT = int(os.environ.get("CDSW_APP_PORT", 8080))
WORKING_DIR = Path(os.environ.get("PHOENIX_WORKING_DIR", "/home/cdsw/cai-eval-data/phoenix"))


def find_phoenix() -> str:
    import shutil
    venv_phoenix = Path("/home/cdsw/.venv/bin/phoenix")
    if venv_phoenix.is_file() and os.access(str(venv_phoenix), os.X_OK):
        return str(venv_phoenix)
    found = shutil.which("phoenix")
    if found:
        return found
    raise RuntimeError(
        "phoenix binary not found. Run cai_integration/setup_environment.py first."
    )


def main() -> None:
    print("=" * 70)
    print("CAI Eval Platform — Phoenix Application")
    print(f"  CDSW_APP_PORT      : {APP_PORT}")
    print(f"  PHOENIX_WORKING_DIR: {WORKING_DIR}")
    print("=" * 70)

    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["PHOENIX_WORKING_DIR"] = str(WORKING_DIR)

    phoenix_bin = find_phoenix()

    print(f"\n[Phoenix] starting: {phoenix_bin} serve --port {APP_PORT} --host 0.0.0.0")
    # Use subprocess.run (blocking) instead of os.execv: the CML IPython
    # engine treats process replacement (execv) as a crash. Keeping Python
    # alive as the parent while Phoenix runs as a child is the correct pattern.
    result = subprocess.run(
        [phoenix_bin, "serve", "--port", str(APP_PORT), "--host", "0.0.0.0"],
    )
    if result.returncode != 0:
        raise RuntimeError(f"Phoenix exited with code {result.returncode}")


# CML runs application scripts in an IPython engine where __name__ is NOT
# "__main__", so guard the call unconditionally.
main()
