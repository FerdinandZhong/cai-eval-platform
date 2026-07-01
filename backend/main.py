"""FastAPI evaluation manager."""

import ragas_compat  # noqa: F401 — must load before any ragas import

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import evaluator
import phoenix_client
from dataset_schema import load_metadata, load_records
from metrics import METRICS, list_metrics, load_custom_metrics, register as register_metric
from targets.agent_studio import AgentStudioConfig, AgentStudioClient
from tracing import setup_tracing

DATASETS_DIR = Path(os.environ.get("DATASETS_DIR", "/app/datasets"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATIC_DIR = Path(__file__).parent / "static"

_jobs: Dict[str, evaluator.EvaluationJob] = {}
_lock = threading.Lock()

app = FastAPI(title="CAI Eval Platform", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class EvaluateRequest(BaseModel):
    target_type: str = "llm_endpoint"
    dataset_id: str = "spider"
    endpoint_url: str = ""
    workflow_url: str = ""
    api_key: str = ""
    model_name: str = "default"
    metrics: list[str] = Field(default_factory=lambda: ["execution_accuracy"])
    max_samples: int = 0
    concurrency: int = 4
    timeout: int = 120
    temperature: float = 0.0
    max_tokens: int = 512
    is_reasoning: bool = False
    system_prompt: str = ""
    metric_config: dict = Field(default_factory=dict)
    input_mapping: dict = Field(default_factory=dict)
    workflow_phoenix_url: str = ""


class LocalResultRequest(BaseModel):
    example_id: str
    output: str = ""
    events: list = Field(default_factory=list)
    trace_id: Optional[str] = None
    latency_ms: int = 0
    error: Optional[str] = None
    record: dict = Field(default_factory=dict)
    job_token: str = ""


class WorkflowDiscoverRequest(BaseModel):
    workflow_url: str
    api_key: str = ""


class _HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "GET /api/health" not in msg and "GET / HTTP" not in msg


@app.on_event("startup")
def on_startup():
    setup_tracing()
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
    load_custom_metrics(DATA_DIR)


def _list_datasets() -> list:
    datasets = []
    if not DATASETS_DIR.exists():
        return datasets
    for meta_file in sorted(DATASETS_DIR.glob("*/metadata.json")):
        try:
            meta = json.loads(meta_file.read_text())
            val_file = meta_file.parent / "validation.json"
            meta["available"] = val_file.exists()
            meta["phoenix_uploaded"] = phoenix_client.dataset_exists(meta.get("id", ""))
            datasets.append(meta)
        except Exception:
            pass
    return datasets


@app.get("/")
@app.get("/index.html")
def index():
    html = STATIC_DIR / "index.html"
    if html.exists():
        return FileResponse(html)
    raise HTTPException(404, "UI not found")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "phoenix_ready": phoenix_client.is_ready(),
        "phoenix_url": "/",
        "jobs_total": len(_jobs),
    }


@app.get("/api/datasets")
def datasets():
    return {"datasets": _list_datasets()}


@app.get("/api/metrics")
def metrics(task_type: Optional[str] = None):
    return {"metrics": list_metrics(task_type)}


@app.get("/api/jobs")
def jobs():
    with _lock:
        return {"jobs": [j.to_dict() for j in _jobs.values()]}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    data = job.to_dict()
    data["results"] = job.results
    return data


@app.post("/api/evaluate")
def start_evaluation(body: EvaluateRequest):
    if body.target_type == "llm_endpoint" and not body.endpoint_url.strip():
        raise HTTPException(400, "'endpoint_url' is required for LLM target")
    if body.target_type == "agent_studio" and not body.workflow_url.strip():
        raise HTTPException(400, "'workflow_url' is required for Agent Studio target")
    if body.target_type == "local_script":
        body.concurrency = 1

    job = evaluator.create_job(**body.model_dump())
    with _lock:
        _jobs[job.id] = job

    if body.target_type == "local_script":
        try:
            records = load_records(DATASETS_DIR, job.dataset_id)
            if job.max_samples > 0:
                records = records[: job.max_samples]
            job.total = len(records)
            job.status = "running"
            job.started_at = __import__("time").time()
        except Exception as e:
            job.status = "failed"
            job.error = str(e)

    if body.target_type != "local_script":
        client = phoenix_client if phoenix_client.is_ready() else None
        t = threading.Thread(target=evaluator.run_job, args=(job, client), daemon=True)
        t.start()

    return {"job_id": job.id, "status": "started", "job_token": job.job_token}


@app.post("/api/workflow/discover")
def discover_workflow(body: WorkflowDiscoverRequest):
    if not body.workflow_url.strip():
        raise HTTPException(400, "workflow_url required")
    client = AgentStudioClient(
        AgentStudioConfig(workflow_url=body.workflow_url, api_key=body.api_key)
    )
    try:
        wf = client.fetch_workflow()
        input_fields = []
        for task in wf.get("tasks", []):
            for inp in task.get("inputs", []):
                if inp not in input_fields:
                    input_fields.append(inp)
        return {
            "workflow": wf.get("workflow", {}),
            "input_fields": input_fields,
            "is_conversational": wf.get("workflow", {}).get("is_conversational", False),
            "tasks": wf.get("tasks", []),
        }
    except Exception as e:
        raise HTTPException(502, str(e)) from e


@app.patch("/api/datasets/{dataset_id}")
def update_dataset_metadata(dataset_id: str, body: dict):
    meta_file = DATASETS_DIR / dataset_id / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    meta = json.loads(meta_file.read_text())
    allowed = {"name", "description", "system_prompt", "size", "task_type",
               "input_fields", "reference_fields", "default_metrics"}
    for k, v in body.items():
        if k in allowed:
            meta[k] = v
    meta_file.write_text(json.dumps(meta, indent=2))
    return {"updated": dataset_id, "metadata": meta}


@app.post("/api/datasets/{dataset_id}/upload")
def upload_dataset_to_phoenix(dataset_id: str):
    val_file = DATASETS_DIR / dataset_id / "validation.json"
    meta_file = DATASETS_DIR / dataset_id / "metadata.json"
    if not val_file.exists():
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    if not phoenix_client.is_ready():
        raise HTTPException(503, "Phoenix is not ready yet")

    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    records = json.loads(val_file.read_text())
    try:
        result = phoenix_client.upload_dataset(
            name=dataset_id,
            records=records,
            description=meta.get("description", ""),
            meta=meta,
        )
        return {"uploaded": dataset_id, "phoenix_response": result}
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/datasets/upload-file")
def upload_dataset_file(body: dict):
    name = (body.get("name") or "").strip().replace(" ", "_").lower()
    records = body.get("records")
    if not name:
        raise HTTPException(400, "'name' is required")
    if not isinstance(records, list) or not records:
        raise HTTPException(400, "'records' must be a non-empty list")

    task_type = body.get("task_type", "general")
    out_dir = DATASETS_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validation.json").write_text(json.dumps(records, indent=2))
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": name,
                "name": name,
                "description": body.get("description", ""),
                "size": len(records),
                "task_type": task_type,
                "input_fields": body.get("input_fields") or ["question"],
                "reference_fields": body.get("reference_fields") or ["expected_output"],
                "system_prompt": body.get("system_prompt", ""),
                "requires_execution": body.get("requires_execution", False),
                "custom": True,
            },
            indent=2,
        )
    )
    return {"created": name, "size": len(records)}


@app.post("/api/metrics/define")
def define_metric(body: dict):
    name = (body.get("name") or "").strip().replace(" ", "_").lower()
    if not name:
        raise HTTPException(400, "'name' is required")
    if name in METRICS:
        raise HTTPException(409, f"Metric '{name}' already exists")

    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "'code' is required — provide a Python function named 'score'")

    def _import_error_msg(e: ImportError) -> str:
        pkg = getattr(e, "name", None) or str(e).removeprefix("No module named ").strip("'")
        return (
            f"Package '{pkg}' is not installed in the eval environment.\n"
            f"Install it first:\n"
            f"  /home/cdsw/.venv/bin/pip install {pkg}\n"
            f"Then re-register the metric."
        )

    # Validate: exec the code and check that score() is callable
    try:
        ns: dict = {}
        exec(compile(code, "<custom_metric>", "exec"), ns)  # noqa: S102
    except SyntaxError as e:
        raise HTTPException(400, f"Syntax error: {e}") from e
    except ImportError as e:
        raise HTTPException(400, _import_error_msg(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Error executing metric code: {e}") from e

    fn = ns.get("score")
    if not callable(fn):
        raise HTTPException(400, "Code must define a callable named 'score'")

    # Dry-run: call score("test", "test") to catch import errors and wrong signatures
    try:
        result = fn("test", "test")
        if not isinstance(result, (int, float, bool)):
            raise TypeError(f"score() must return a numeric value, got {type(result).__name__}")
    except TypeError as e:
        raise HTTPException(400, f"Dry-run failed: {e}") from e
    except ImportError as e:
        raise HTTPException(400, _import_error_msg(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Dry-run error: {e}") from e

    description = body.get("description") or ns.get("DESCRIPTION", "")
    metric_type = body.get("type") or ns.get("METRIC_TYPE", "continuous")
    task_types = ns.get("TASK_TYPES", ["text2sql", "agent", "general"])

    # Persist as .py for survival across restarts
    metrics_dir = DATA_DIR / "custom_metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    header = f'DESCRIPTION = {json.dumps(description)}\nMETRIC_TYPE = {json.dumps(metric_type)}\nTASK_TYPES = {json.dumps(task_types)}\n\n'
    (metrics_dir / f"{name}.py").write_text(header + code)

    # Register immediately — no restart needed
    register_metric(name, fn, description, metric_type, task_types=task_types)
    METRICS[name]["custom"] = True

    return {"defined": name}


@app.post("/api/jobs/{job_id}/results")
def push_local_result(job_id: str, body: LocalResultRequest):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    if job.target_type != "local_script":
        raise HTTPException(400, "Job is not a local_script target")
    if job.job_token and body.job_token != job.job_token:
        raise HTTPException(403, "Invalid job token")

    result = evaluator.ingest_local_result(job, body.model_dump())
    job.results.append(result)
    job.completed_count = len(job.results)
    job.total = max(job.total, job.completed_count)
    job.progress = int(job.completed_count / job.total * 100) if job.total else 100

    scores = [v for r in job.results for v in r.get("scores", {}).values()]
    if scores:
        job.accuracy = sum(float(s) for s in scores) / len(scores)

    if job.completed_count >= job.total and job.total > 0:
        job.status = "completed"
        job.finished_at = __import__("time").time()
        if phoenix_client.is_ready():
            try:
                records = load_records(DATASETS_DIR, job.dataset_id)
                phoenix_client.upload_evaluation_results(
                    dataset_id=job.dataset_id,
                    job_id=job.id,
                    model_name=job.model_name,
                    results=job.results,
                    records=records,
                )
            except Exception as e:
                print(f"[app] Phoenix upload failed: {e}", flush=True)

    return {"accepted": True, "completed_count": job.completed_count}


def main():
    import uvicorn

    port = int(os.environ.get("MANAGER_PORT", 9000))
    uvicorn.run("main:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
