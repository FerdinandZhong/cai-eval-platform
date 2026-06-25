#!/usr/bin/env python3
"""
CAI Eval Platform — CML Application launcher.

Runs the FastAPI eval API directly on CDSW_APP_PORT. No nginx needed —
CML routes external traffic straight to this port, just like start_phoenix.py.

Prerequisites:
  - Run cai_integration/setup_environment.py (CML job) to install deps
  - Set PHOENIX_COLLECTOR_ENDPOINT to the standalone Phoenix Application URL
    (e.g. https://phoenix.<cml-domain>/v1/traces) so tracing is enabled

Env vars:
  CDSW_APP_PORT              — external port CML assigns        (default: 8080)
  PHOENIX_COLLECTOR_ENDPOINT — Phoenix OTLP ingest URL          (no default — warn if missing)
  DATA_DIR                   — persistent storage root          (default: /home/cdsw/cai-eval-data)
  DATASETS_DIR               — bundled datasets directory       (default: <repo>/datasets)
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()

APP_PORT    = int(os.environ.get("CDSW_APP_PORT", 8080))
DATA_DIR    = Path(os.environ.get("DATA_DIR", "/home/cdsw/cai-eval-data"))
DATASETS_DIR = Path(os.environ.get("DATASETS_DIR", str(REPO_ROOT / "datasets")))
PHOENIX_COLLECTOR_ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "")


def main() -> int:
    print("=" * 70)
    print("CAI Eval Platform — Eval API Application")
    print(f"  CDSW_APP_PORT              : {APP_PORT}")
    print(f"  DATA_DIR                   : {DATA_DIR}")
    print(f"  DATASETS_DIR               : {DATASETS_DIR}")
    print(f"  PHOENIX_COLLECTOR_ENDPOINT : {PHOENIX_COLLECTOR_ENDPOINT or '(not set — tracing disabled)'}")
    print(f"  REPO_ROOT                  : {REPO_ROOT}")
    print("=" * 70)

    backend_dir = REPO_ROOT / "backend"
    if not (backend_dir / "main.py").exists():
        print(f"ERROR: backend/main.py not found at {backend_dir}")
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Propagate env vars to uvicorn (and thereby to the backend)
    os.environ["DATA_DIR"] = str(DATA_DIR)
    os.environ["DATASETS_DIR"] = str(DATASETS_DIR)

    if PHOENIX_COLLECTOR_ENDPOINT:
        os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = PHOENIX_COLLECTOR_ENDPOINT
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = PHOENIX_COLLECTOR_ENDPOINT
    else:
        print(
            "\nWARNING: PHOENIX_COLLECTOR_ENDPOINT not set.\n"
            "  Evaluation traces will not be sent to Phoenix.\n"
            "  Set this env var to the Phoenix CML Application URL to enable tracing.\n"
        )

    uvicorn_argv = [
        sys.executable, "-m", "uvicorn", "main:app",
        "--host", "0.0.0.0",
        "--port", str(APP_PORT),
    ]
    print(f"\n[eval API] exec: {' '.join(uvicorn_argv)}")
    print(f"  working dir: {backend_dir}")
    print("=" * 70)

    # Change to backend dir so uvicorn resolves 'main:app' correctly,
    # then replace this Python process with uvicorn.
    os.chdir(str(backend_dir))
    os.execv(sys.executable, uvicorn_argv)
    # os.execv never returns


if __name__ == "__main__":
    sys.exit(main())
