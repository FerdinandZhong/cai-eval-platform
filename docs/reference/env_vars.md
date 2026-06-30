# Environment Variables

## Core

| Variable | Default | Description |
|----------|---------|-------------|
| `PHOENIX_PORT` | `6006` | Internal Phoenix port (co-located) |
| `MANAGER_PORT` | `9000` | FastAPI eval API port |
| `DATA_DIR` | `/data` | Persistent volume root (Phoenix state, results, custom metrics) |
| `DATASETS_DIR` | `/app/datasets` | Directory containing bundled dataset subdirectories |

## Phoenix

| Variable | Default | Description |
|----------|---------|-------------|
| `PHOENIX_BASE_URL` | `http://127.0.0.1:6006` | Base URL of Phoenix REST API (override for standalone/remote Phoenix) |
| `PHOENIX_PROJECT` | `cai-eval` | OTEL project name (overridden per-run to `{dataset_id}_{model_name}`) |
| `PHOENIX_COLLECTOR_ENDPOINT` | — | Explicit OTLP endpoint (takes precedence over `PHOENIX_BASE_URL`) |

## Evaluation

| Variable | Default | Description |
|----------|---------|-------------|
| `JUDGE_LLM_URL` | — | Default judge LLM base URL for Ragas metrics |
| `JUDGE_LLM_API_KEY` | — | API key for the judge LLM |

## CML / CAI deployment

| Variable | Injected by CML | Description |
|----------|----------------|-------------|
| `CDSW_APP_PORT` | ✓ | Port nginx binds on (the single public port for the Application) |
| `CDSW_API_URL` | ✓ | Workspace API URL (used by `launch_in_project.py`) |
| `CDSW_APIV2_KEY` | ✓ | Workspace API key |
| `CDSW_PROJECT_ID` | ✓ | Current project ID |

## CI / GitHub Actions secrets

| Secret | Description |
|--------|-------------|
| `CML_HOST` | CML workspace URL |
| `CML_API_KEY` | API key with project-create permission |
| `RUNTIME_IDENTIFIER` | Full ML Runtime identifier string |
| `GH_PAT` | GitHub PAT for repo access from CML |
