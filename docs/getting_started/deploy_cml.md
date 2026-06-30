# Deploy on CML / CAI Workbench

The platform runs as a **single CML Application** — Phoenix + FastAPI behind nginx, all co-located on one port.

```
nginx (CDSW_APP_PORT)
  ├── /        →  Phoenix tracing UI
  └── /app/    →  FastAPI eval API
```

## Prerequisites

- A CML / CAI Workbench project pointing at this repository
- An ML Runtime with Python 3.11
- At least 4 vCPU / 16 GiB memory for the Application

## Option A — GitHub Actions (CI)

Configure these repository secrets:

| Secret | Value |
|--------|-------|
| `CML_HOST` | Your CML workspace URL |
| `CML_API_KEY` | API key with project-create permission |
| `RUNTIME_IDENTIFIER` | Full ML Runtime identifier string |
| `GH_PAT` | GitHub PAT for repo access from CML |

Then trigger **Actions → Deploy CAI Eval Platform to CML → Run workflow**.

Use `skip_env_setup: true` on subsequent runs when the environment is already prepared.

## Option B — In-project launch

In a CML Session terminal (uses workspace credentials automatically):

```bash
python cai_integration/launch_in_project.py
```

## Option C — CML UI

1. **Applications** tab → **New Application**
2. **Script:** `cai_integration/start_platform.py`
3. **Subdomain:** e.g. `cai-eval`
4. **Resource profile:** ≥ 4 vCPU / 16 GiB
5. Select the same ML Runtime used for setup

## Environment setup (first run only)

The `setup_eval_env` CML job must run before the Application launches:

- Creates `/home/cdsw/.venv` with all dependencies
- Compiles nginx from source (no root required)
- Downloads Spider and τ-bench datasets

This runs automatically via the GitHub Actions workflow, or manually:

```bash
python cai_integration/setup_environment.py
```

!!! warning
    nginx is compiled without the PCRE library (unavailable without root in CML).
    The rewrite module is disabled — `return 302` redirects are not available.
    Phoenix is at `/` and the eval app is at `/app/`.
