# API Reference

The eval API is a FastAPI application running at `<app-url>/app/` (co-located) or `http://localhost:9000` (local dev).

## Health

### `GET /api/health`

```json
{
  "status": "ok",
  "phoenix_ready": true,
  "phoenix_url": "/",
  "jobs_total": 3
}
```

## Datasets

### `GET /api/datasets`

List all datasets found in `DATASETS_DIR`.

```json
{
  "datasets": [
    {
      "id": "spider",
      "name": "Spider Text-to-SQL",
      "size": 1034,
      "task_type": "text2sql",
      "available": true,
      "phoenix_uploaded": false
    }
  ]
}
```

### `PATCH /api/datasets/{dataset_id}`

Update dataset metadata fields. Allowed fields: `name`, `description`, `system_prompt`, `size`, `task_type`, `input_fields`, `reference_fields`, `default_metrics`.

```json
{ "name": "My Dataset", "system_prompt": "You are a helpful assistant." }
```

### `POST /api/datasets/{dataset_id}/upload`

Upload dataset to Phoenix for experiment tracking (chunked automatically).

### `POST /api/datasets/upload-file`

Register a custom dataset from JSON.

```json
{
  "name": "my_dataset",
  "description": "...",
  "records": [{"example_id": "0", "question": "...", "expected_output": "..."}],
  "task_type": "agent"
}
```

## Metrics

### `GET /api/metrics?task_type=agent`

List available metrics, optionally filtered by task type.

### `POST /api/metrics/define`

Define a custom metric (saved to `DATA_DIR/custom_metrics/`).

## Evaluation

### `POST /api/evaluate`

Start an evaluation job.

```json
{
  "target_type": "agent_studio",
  "dataset_id": "agent_sample",
  "workflow_url": "http://my-workflow:8000",
  "api_key": "sk-...",
  "model_name": "gpt-4o",
  "metrics": ["agent_goal_accuracy"],
  "max_samples": 0,
  "concurrency": 4,
  "timeout": 120
}
```

Returns: `{"job_id": "...", "status": "started", "job_token": "..."}`

### `GET /api/jobs`

List all jobs.

### `GET /api/jobs/{job_id}`

Get job detail including per-example results.

## Workflow discovery

### `POST /api/workflow/discover`

Discover input field names from an Agent Studio workflow.

```json
{ "workflow_url": "http://my-workflow:8000", "api_key": "sk-..." }
```
