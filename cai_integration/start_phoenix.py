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
import sys
from pathlib import Path

APP_PORT = int(os.environ.get("CDSW_APP_PORT", 8080))
WORKING_DIR = Path(os.environ.get("PHOENIX_WORKING_DIR", "/home/cdsw/cai-eval-data/phoenix"))


def find_phoenix() -> str:
    import shutil
    # prefer venv-installed phoenix
    venv_phoenix = Path("/home/cdsw/.venv/bin/phoenix")
    if venv_phoenix.is_file() and os.access(str(venv_phoenix), os.X_OK):
        return str(venv_phoenix)
    found = shutil.which("phoenix")
    if found:
        return found
    raise RuntimeError(
        "phoenix binary not found. Run cai_integration/setup_environment.py first."
    )


def main() -> int:
    print("=" * 70)
    print("CAI Eval Platform — Phoenix Application")
    print(f"  CDSW_APP_PORT      : {APP_PORT}")
    print(f"  PHOENIX_WORKING_DIR: {WORKING_DIR}")
    print("=" * 70)

    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["PHOENIX_WORKING_DIR"] = str(WORKING_DIR)

    try:
        phoenix_bin = find_phoenix()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"\n[Phoenix] exec: {phoenix_bin} serve --port {APP_PORT} --host 0.0.0.0")
    # Replace this Python process with Phoenix — CML keeps the Application
    # alive as long as phoenix is running.
    os.execv(phoenix_bin, [phoenix_bin, "serve", "--port", str(APP_PORT), "--host", "0.0.0.0"])
    # os.execv never returns


if __name__ == "__main__":
    sys.exit(main())
