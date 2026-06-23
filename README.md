# CAI Eval Platform

Model and agentic workflow evaluation platform with Arize Phoenix tracing.

## Features

- **LLM endpoint evaluation** — OpenAI-compatible APIs, text2sql benchmarks (Spider, TPC-H)
- **Agent Studio workflow testing** — black-box test deployed workflows via kickoff/events API
- **Ragas agent metrics** — AgentGoalAccuracy, ToolCallAccuracy, ToolCallF1
- **Phoenix tracing** — OTEL spans for LLM calls; workflow events exported as spans
- **Local Python runner** — execute CrewAI/custom scripts locally, push results to platform

## Quick start

```bash
docker build -f docker/Dockerfile -t cai-eval-platform .
docker run -p 8080:8080 -v cai-eval-data:/data cai-eval-platform
```

- Eval UI: http://localhost:8080/app/
- Phoenix: http://localhost:8080/

## Local development

```bash
cd backend
pip install -e ..
uvicorn main:app --reload --port 9000
```

Set `DATASETS_DIR=../datasets` and `DATA_DIR=/tmp/cai-eval-data`.

## Agent Studio workflow eval

1. Open eval UI → select **Agent Studio Workflow**
2. Enter workflow URL and API key
3. Click **Discover Workflow Inputs** to auto-map dataset columns
4. Upload dataset with `question` and `expected_output` fields
5. Select Ragas metrics (e.g. `agent_goal_accuracy`)
6. Run evaluation — trajectories appear in Phoenix

## Local script runner

```bash
pip install -e runner/
cai-eval-runner run \
  --script my_workflow.py \
  --dataset dataset.json \
  --eval-server http://localhost:8080 \
  --job-id <job_id> \
  --job-token <token>
```

Your script must implement:

```python
def run(inputs: dict) -> dict:
    return {"output": "...", "events": [...]}  # events optional
```

## Project structure

```
backend/          FastAPI eval manager + engine
  targets/        LLM endpoint, Agent Studio adapters
  trace/          Event→OTEL span, event→Ragas conversion
  metrics/        Built-in + Ragas metrics
datasets/         Bundled benchmarks
docker/           Dockerfile + entrypoint
runner/           cai-eval-runner CLI
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PHOENIX_PORT` | 6006 | Internal Phoenix port |
| `MANAGER_PORT` | 9000 | Eval API port |
| `DATA_DIR` | /data | Persistent data volume |
| `DATASETS_DIR` | /app/datasets | Bundled datasets |
| `JUDGE_LLM_URL` | — | Default judge LLM for Ragas metrics |
