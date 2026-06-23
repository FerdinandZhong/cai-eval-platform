# CAI Eval Platform — Implementation Summary

This document summarizes what was built when extracting the evaluation platform from `ray-serve-cai-bench` into the standalone **`cai-eval-platform`** repository, following the [Eval Platform Standalone Roadmap](https://github.com/cloudera/cai-eval-platform).

---

## Overview

| Before | After |
|--------|-------|
| Eval platform lived under `ray-serve-cai-bench/docker/` | Standalone repo at `cai-eval-platform/` |
| stdlib `http.server` backend | **FastAPI** + Uvicorn |
| Text-to-SQL only | LLM endpoints, **Agent Studio workflows**, **local Python scripts** |
| Phoenix experiments only (REST) | Experiments **plus OTEL traces** |
| Hardcoded dataset schema | **Generic dataset schema** via metadata |

`ray-serve-cai-bench` now focuses on load testing (Locust, Vegeta, vLLM). A pointer README lives at [`docker/README.md`](../ray-serve-cai-bench/docker/README.md).

---

## Repository Structure

```
cai-eval-platform/
├── backend/                 # FastAPI eval manager + engine
│   ├── main.py              # REST API
│   ├── evaluator.py         # Job orchestration
│   ├── phoenix_client.py    # Phoenix datasets/experiments
│   ├── tracing.py           # OTEL setup
│   ├── dataset_schema.py    # Generic dataset helpers
│   ├── targets/             # Evaluation target adapters
│   ├── trace/               # Event → span / Ragas conversion
│   ├── metrics/             # Built-in + Ragas metrics
│   └── static/index.html    # Web UI
├── datasets/                # Bundled benchmarks
│   ├── spider/              # Text-to-SQL (1034 examples, built at Docker image time)
│   ├── tpch/                # Trino SQL (22 examples)
│   └── agent_sample/        # Agent workflow sample (2 examples)
├── docker/                  # Dockerfile + entrypoint (Phoenix + nginx)
├── runner/                  # cai-eval-runner CLI
└── pyproject.toml
```

---

## Phase 0 — Extraction & Target Adapter Refactor

### Standalone repo

- Created `cai-eval-platform` as a sibling project to `ray-serve-cai-bench`
- Moved backend, datasets, Docker config, and added project-level `pyproject.toml` and `README.md`

### Target adapter pattern

Introduced a pluggable target interface in `backend/targets/base.py`:

| Type | Class | Purpose |
|------|-------|---------|
| `llm_endpoint` | `LLMEndpointTarget` | OpenAI-compatible chat completions (existing text2sql path) |
| `agent_studio` | `AgentStudioWorkflowTarget` | Agent Studio deployed workflow backend |
| `local_script` | (via push API) | User runs Python locally; results pushed to platform |

Each target implements `discover()` and `invoke(inputs, ctx) → TargetResult` with:

- `output_text`, `trace_id`, `events`, `latency_ms`, `start_time`, `end_time`

### Generic dataset schema

Replaced hardcoded `{question, db_id}` / `{gold_sql}` Phoenix upload with metadata-driven fields:

```json
{
  "id": "my-agent-bench",
  "task_type": "agent",
  "input_fields": ["question"],
  "reference_fields": ["expected_output"],
  "requires_execution": false
}
```

- Records carry stable `example_id` for Phoenix example matching
- `dataset_schema.py` handles input/reference extraction and Phoenix array conversion

### FastAPI backend

`backend/main.py` exposes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health + Phoenix status |
| GET | `/api/datasets` | List datasets |
| GET | `/api/metrics` | List metrics (optional `?task_type=`) |
| POST | `/api/evaluate` | Start eval job |
| GET | `/api/jobs`, `/api/jobs/{id}` | Job list + detail (includes results) |
| POST | `/api/workflow/discover` | Discover Agent Studio input fields |
| POST | `/api/datasets/{id}/upload` | Upload dataset to Phoenix |
| POST | `/api/datasets/upload-file` | Register custom dataset |
| POST | `/api/jobs/{id}/results` | Push result from local runner |

---

## Phase 1 — Phoenix Tracing

### OTEL instrumentation

`backend/tracing.py`:

- Registers Phoenix OTEL exporter (`phoenix.otel.register`)
- Instruments OpenAI SDK via `openinference-instrumentation-openai`
- Wraps each dataset example in an `eval.example` parent span

### Experiment run linking

`backend/phoenix_client.py` now uploads:

- Real `start_time` / `end_time` per example (not batch timestamp)
- `trace_id`, `span_id` in run output metadata
- Full workflow `events` array for UI drill-down
- Example matching by `example_id` (fallback to question text)

---

## Phase 2 — Agent Studio Workflow Testing

### Workflow client

`backend/targets/agent_studio.py` ports the Agent Studio UI integration pattern:

| Step | API |
|------|-----|
| Discover | `GET /api/workflow` |
| Session | `POST /api/workflow/createSession` |
| Execute | `POST /api/workflow/kickoff` |
| Poll | `GET /api/workflow/events?trace_id=` |

- Auth: `Authorization: Bearer {api_key}`
- Polls until `crew_kickoff_completed` or `crew_kickoff_failed`
- **v1 limitation:** plain-text output only; file outputs (PDF/CSV) are rejected with a warning

### Ragas agent metrics

`backend/metrics/ragas_agent.py` integrates:

| Metric | Use case |
|--------|----------|
| `agent_goal_accuracy` | Black-box output vs ground truth (primary) |
| `tool_call_accuracy` | Tool sequence + argument correctness |
| `tool_call_f1` | Precision/recall for tool calls |

Requires a judge LLM URL in metric config or `JUDGE_LLM_URL` env var.

Existing text metrics (`exact_match`, `token_f1`, `execution_accuracy`, etc.) remain for text2sql.

### Event conversion

| Module | Role |
|--------|------|
| `trace/event_to_ragas.py` | Agent Studio events → Ragas `HumanMessage` / `AIMessage` / `ToolCall` |
| `trace/workflow_events_to_spans.py` | Events → OTEL spans exported to eval platform Phoenix |

### Three-tier tracing strategy

| Tier | Mechanism | Status |
|------|-----------|--------|
| **1** | Poll events → convert to OTEL spans → eval Phoenix | Implemented |
| **2** | Store `workflow_trace_id` + optional `workflow_phoenix_url`; UI deep link | Implemented |
| **3** | Workflow backend exports OTEL to same Phoenix collector | Deployment-time config (documented) |

### UI changes

`backend/static/index.html`:

- **Evaluation target** selector: LLM Endpoint / Agent Studio Workflow / Local Python Script
- Workflow URL, API key, optional Phoenix URL, input mapping JSON
- **Discover Workflow Inputs** button → `POST /api/workflow/discover`
- Job table with target type column
- **Job detail panel** with per-example output, trace ID, event timeline, Phoenix deep links

---

## Phase 3 — Local Python Script Runner

### CLI package

`runner/cai_eval_runner/` — installable via `pip install -e runner/`:

```bash
cai-eval-runner run \
  --script my_workflow.py \
  --dataset dataset.json \
  --eval-server http://localhost:8080 \
  --job-id <job_id> \
  --job-token <token>
```

### Script contract

```python
def run(inputs: dict) -> dict:
    return {
        "output": "...",       # required
        "events": [...],       # optional, for Ragas + tracing
        "trace_id": "...",     # optional
    }
```

### Flow

1. User creates a **Local Python Script** job in the UI → receives `job_id` + `job_token`
2. Runner executes `run(inputs)` for each dataset record in the user's local Python env
3. Runner POSTs each result to `/api/jobs/{id}/results`
4. Platform scores with Ragas, exports to Phoenix when all examples are received

Example script: `runner/examples/demo_workflow.py`

---

## Docker Deployment

```bash
docker build -f docker/Dockerfile -t cai-eval-platform .
docker run -p 8080:8080 -v cai-eval-data:/data cai-eval-platform
```

| URL | Service |
|-----|---------|
| http://localhost:8080/app/ | Eval UI + API |
| http://localhost:8080/ | Arize Phoenix |

Container runs: Phoenix → FastAPI (Uvicorn) → nginx on `:8080`.

Spider `validation.json` is downloaded from HuggingFace at image build time.

---

## Bundled Datasets

| ID | Task | Examples | Notes |
|----|------|----------|-------|
| `spider` | text2sql | 1034 | Execution-based; SQLite DBs cached on first run |
| `tpch` | text2sql | 22 | Text metrics only; embedded Trino schema |
| `agent_sample` | agent | 2 | `question` + `expected_output` for workflow testing |

---

## Key Files Reference

| Purpose | Path |
|---------|------|
| API entry | `backend/main.py` |
| Eval engine | `backend/evaluator.py` |
| Phoenix client | `backend/phoenix_client.py` |
| OTEL setup | `backend/tracing.py` |
| LLM target | `backend/targets/llm_endpoint.py` |
| Agent Studio target | `backend/targets/agent_studio.py` |
| Span export | `backend/trace/workflow_events_to_spans.py` |
| Ragas conversion | `backend/trace/event_to_ragas.py` |
| Ragas metrics | `backend/metrics/ragas_agent.py` |
| Web UI | `backend/static/index.html` |
| Local runner CLI | `runner/cai_eval_runner/cli.py` |

---

## Deferred / Not in v1

- File output evaluation (PDF/CSV download + text extraction)
- Remote sandbox for arbitrary Python execution
- GitHub Actions CI for Docker build + API tests
- React frontend migration (current UI remains single-page HTML)
- Custom metrics loaded at runtime (still metadata-only stubs)
- Persistent job store (jobs remain in-memory; results persisted to `/data/results/`)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PHOENIX_PORT` | 6006 | Internal Phoenix port |
| `MANAGER_PORT` | 9000 | Eval API port |
| `DATA_DIR` | /data | Persistent volume |
| `DATASETS_DIR` | /app/datasets | Bundled datasets |
| `PHOENIX_PROJECT` | cai-eval | OTEL project name |
| `JUDGE_LLM_URL` | — | Default judge LLM for Ragas metrics |
