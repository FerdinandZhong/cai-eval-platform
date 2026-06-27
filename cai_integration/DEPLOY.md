# Deploying the CAI Eval Platform on CML

The platform runs as **one CML Application** (`cai_integration/start_platform.py`)
that serves both components behind nginx on the single port CML assigns:

```
nginx (CDSW_APP_PORT)
  ├── /      -> Phoenix tracing UI / REST  (127.0.0.1:6006)
  └── /app/  -> FastAPI eval API           (127.0.0.1:9000)
```

The backend talks to Phoenix over localhost (`PHOENIX_BASE_URL`, default
`http://127.0.0.1:6006`), so no cross-app wiring is needed.

## Prerequisites (all launch methods)

The environment-setup job must have run at least once so the venv, deps, and the
no-root nginx binary exist:

- `cai_integration/setup_environment.py` creates `/home/cdsw/.venv` and installs
  nginx to `~/.local/bin/nginx`.

Run it via the job chain (`git_sync` → `setup_eval_env`) or directly in a Session.

## Option A — Launch from inside the CML project (recommended for end users)

In a CML **Session** terminal (uses the workspace creds CML injects; no API key
needed):

```bash
python cai_integration/launch_in_project.py
```

This creates/restarts the `CAI Eval Platform` Application. Open it from the
**Applications** tab; the eval UI is under `/app/`, Phoenix under `/`.

## Option B — Create the Application manually in the CML UI

1. **Applications** tab → **New Application**.
2. **Script:** `cai_integration/start_platform.py`
3. **Subdomain:** e.g. `cai-eval`
4. **Resource profile:** ≥ 4 vCPU / 16 GiB recommended.
5. Select the same ML Runtime used for the setup job.
6. Create. After it reaches **Running**, open `<app-url>/` (Phoenix) and
   `<app-url>/app/` (eval API).

## Option C — GitHub Actions (CI)

`.github/workflows/deploy-eval-platform.yml` runs the full chain
(setup project → create jobs → setup env → launch application) using the
`CML_HOST` / `CML_API_KEY` / `RUNTIME_IDENTIFIER` secrets. Use
`skip_env_setup: true` to jump straight to launching the application when the
environment is already prepared.

## Standalone Phoenix (opt-in)

To run Phoenix as a separate, reusable tracing backend instead of co-located:

```bash
python cai_integration/launch_in_project.py --standalone-phoenix
# or, externally:
python cai_integration/create_applications.py --project-id <id> --standalone-phoenix
```

This deploys two apps — standalone Phoenix (`start_phoenix.py`) and the eval API
(`start_app.py`) — and injects `PHOENIX_BASE_URL` into the eval app pointing at
Phoenix.

> **Caveat:** the backend's Phoenix REST calls (dataset upload, experiment
> logging) send no auth headers. The eval app must be able to reach the Phoenix
> app **without** CML authentication for dataset/experiment logging to work in
> this mode; otherwise only the co-located default is fully functional.
