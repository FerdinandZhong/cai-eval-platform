#!/usr/bin/env bash
# Activate the CML venv and launch the eval platform stack.
# Called by launch_app_job.py (the CML entry point).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="/home/cdsw/.venv"

if [[ -f "${VENV}/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
    echo "[launch_app.sh] activated venv: ${VENV}"
else
    echo "[launch_app.sh] WARNING: venv not found at ${VENV}, using system Python"
fi

exec python "${REPO_ROOT}/cai_integration/start_app.py" "$@"
