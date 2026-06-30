"""
Evaluation engine with target adapter support.

Supports LLM endpoints, Agent Studio workflows, and local script push results.
"""

import json
import os
import sqlite3
import time
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from dataset_schema import (
    extract_inputs,
    extract_reference,
    get_input_fields,
    get_reference_fields,
    load_metadata,
    load_records,
)
from targets.agent_studio import AgentStudioConfig, AgentStudioWorkflowTarget
from targets.base import EvalContext
from targets.llm_endpoint import LLMEndpointConfig, LLMEndpointTarget, extract_sql
from trace.event_to_ragas import events_to_user_input, extract_reference_tool_calls
from trace.workflow_events_to_spans import export_workflow_trace
from tracing import eval_example_span, setup_tracing

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
BUNDLED_DATASETS_DIR = Path(os.environ.get("DATASETS_DIR", "/app/datasets"))
SPIDER_DB_URL = "https://github.com/taoyds/spider/archive/refs/heads/master.zip"


@dataclass
class EvaluationJob:
    id: str
    dataset_id: str
    target_type: str
    model_name: str
    metrics: list
    max_samples: int
    concurrency: int
    timeout: int
    temperature: float

    endpoint_url: str = ""
    api_key: str = ""
    max_tokens: int = 512
    is_reasoning: bool = False
    system_prompt: str = ""
    workflow_url: str = ""
    workflow_phoenix_url: str = ""
    input_mapping: dict = field(default_factory=dict)
    metric_config: dict = field(default_factory=dict)

    status: str = "pending"
    progress: int = 0
    total: int = 0
    completed_count: int = 0
    accuracy: Optional[float] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    results: list = field(default_factory=list)
    results_path: Optional[str] = None
    job_token: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "target_type": self.target_type,
            "endpoint_url": self.endpoint_url,
            "workflow_url": self.workflow_url,
            "model_name": self.model_name,
            "metrics": self.metrics,
            "max_samples": self.max_samples,
            "concurrency": self.concurrency,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "completed_count": self.completed_count,
            "accuracy": self.accuracy,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results_path": self.results_path,
            "job_token": self.job_token,
        }


def create_job(**kwargs) -> EvaluationJob:
    return EvaluationJob(
        id=str(uuid.uuid4())[:8],
        dataset_id=kwargs.get("dataset_id", "spider"),
        target_type=kwargs.get("target_type", "llm_endpoint"),
        endpoint_url=kwargs.get("endpoint_url", "").rstrip("/"),
        workflow_url=kwargs.get("workflow_url", "").rstrip("/"),
        model_name=kwargs.get("model_name", "default"),
        metrics=kwargs.get("metrics") or ["execution_accuracy"],
        max_samples=int(kwargs.get("max_samples", 0)),
        concurrency=int(kwargs.get("concurrency", 4)),
        timeout=int(kwargs.get("timeout", 120)),
        temperature=float(kwargs.get("temperature", 0.0)),
        metric_config=kwargs.get("metric_config") or {},
        api_key=kwargs.get("api_key", ""),
        max_tokens=int(kwargs.get("max_tokens", 512)),
        is_reasoning=bool(kwargs.get("is_reasoning", False)),
        system_prompt=kwargs.get("system_prompt", ""),
        workflow_phoenix_url=kwargs.get("workflow_phoenix_url", ""),
        input_mapping=kwargs.get("input_mapping") or {},
        job_token=str(uuid.uuid4()) if kwargs.get("target_type") == "local_script" else None,
    )


def _build_target(job: EvaluationJob):
    if job.target_type == "agent_studio":
        return AgentStudioWorkflowTarget(
            AgentStudioConfig(
                workflow_url=job.workflow_url,
                api_key=job.api_key,
                workflow_phoenix_url=job.workflow_phoenix_url,
            )
        )
    return LLMEndpointTarget(
        LLMEndpointConfig(
            endpoint_url=job.endpoint_url,
            api_key=job.api_key,
            model_name=job.model_name,
            max_tokens=job.max_tokens,
            temperature=job.temperature,
            timeout=job.timeout,
            is_reasoning=job.is_reasoning,
            system_prompt=job.system_prompt,
            output_mode="sql" if job.metrics and "execution_accuracy" in job.metrics else "text",
        )
    )


def _ensure_spider_databases() -> Path:
    db_dir = DATA_DIR / "spider" / "databases"
    if db_dir.exists() and any(db_dir.iterdir()):
        return db_dir

    zip_path = DATA_DIR / "spider" / "spider-master.zip"
    db_dir.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SPIDER_DB_URL, str(zip_path))

    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.startswith("spider-master/database/"):
                target = db_dir.parent / member.replace("spider-master/", "", 1)
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
    zip_path.unlink(missing_ok=True)
    return db_dir


def _find_database(db_id: str, databases_dir: Path) -> Optional[Path]:
    db_path = databases_dir / db_id / f"{db_id}.sqlite"
    if db_path.exists():
        return db_path
    for d in databases_dir.iterdir():
        if d.name.lower() == db_id.lower() and d.is_dir():
            sqlite_file = d / f"{d.name}.sqlite"
            if sqlite_file.exists():
                return sqlite_file
    return None


def _get_db_schema(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL;")
    schemas = [row[0] for row in cursor.fetchall()]
    conn.close()
    return "\n\n".join(schemas)


def _execute_sql(db_path: Path, sql: str) -> tuple:
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout = 5000;")
        cursor = conn.cursor()
        cursor.execute(sql)
        results = set(cursor.fetchall())
        conn.close()
        return results, None
    except Exception as e:
        return None, str(e)


def _score_result(result: dict, record: dict, job: EvaluationJob, meta: dict) -> None:
    from metrics import METRICS
    from metrics.llm_judge import score_detailed
    from metrics.ragas_agent import (
        score_agent_goal_with_reference,
        score_tool_call_accuracy,
        score_tool_call_f1,
    )
    from trace.event_to_ragas import events_to_user_input, extract_reference_tool_calls

    reference = extract_reference(record, get_reference_fields(meta))
    pred = result.get("output_text") or result.get("pred_sql", "")
    result["scores"] = result.get("scores") or {}

    user_input = events_to_user_input(
        result.get("events", []),
        initial_question=record.get("question", ""),
    )
    ref_tools = extract_reference_tool_calls(record)

    for metric_name in job.metrics:
        if metric_name == "execution_accuracy":
            continue
        m = METRICS.get(metric_name)
        if not m:
            continue
        cfg = dict(job.metric_config.get(metric_name, {}))

        if metric_name == "llm_as_judge_sql":
            cfg.setdefault("question", record.get("question", ""))
            cfg.setdefault("schema", meta.get("schema", ""))
            score_val, judge_trace = score_detailed(reference, pred, config=cfg)
            result["scores"][metric_name] = score_val
            result.setdefault("judge_traces", {})[metric_name] = judge_trace
        elif metric_name == "agent_goal_accuracy":
            score_val, trace = score_agent_goal_with_reference(user_input, reference, cfg)
            result["scores"][metric_name] = score_val
            result.setdefault("judge_traces", {})[metric_name] = trace
        elif metric_name == "tool_call_accuracy" and ref_tools:
            score_val, trace = score_tool_call_accuracy(user_input, ref_tools, config=cfg)
            result["scores"][metric_name] = score_val
            result.setdefault("judge_traces", {})[metric_name] = trace
        elif metric_name == "tool_call_f1" and ref_tools:
            score_val, trace = score_tool_call_f1(user_input, ref_tools, config=cfg)
            result["scores"][metric_name] = score_val
            result.setdefault("judge_traces", {})[metric_name] = trace
        else:
            result["scores"][metric_name] = m["fn"](reference, pred, config=cfg if cfg else None)

    if "exact_match" in result["scores"]:
        result["correct"] = result["scores"]["exact_match"] == 1.0
    elif "agent_goal_accuracy" in result["scores"]:
        result["correct"] = result["scores"]["agent_goal_accuracy"] >= 0.9
    elif result["scores"]:
        result["correct"] = max(result["scores"].values()) >= 0.9


def _evaluate_example(
    record: dict,
    job: EvaluationJob,
    meta: dict,
    target,
    session_id: Optional[str],
    db_dir: Optional[Path],
) -> dict:
    example_id = str(record.get("example_id", ""))
    input_fields = get_input_fields(meta)
    inputs = extract_inputs(record, input_fields)

    reference = extract_reference(record, get_reference_fields(meta))
    result = {
        "example_id": example_id,
        "question": record.get("question", ""),
        "db_id": record.get("db_id", ""),
        "gold_sql": record.get("query", reference),
        "reference": reference,
        "pred_sql": "",
        "output_text": "",
        "correct": False,
        "scores": {},
        "error": None,
        "latency_ms": 0,
        "trace_id": None,
        "span_id": None,
        "events": [],
        "workflow_phoenix_url": job.workflow_phoenix_url or None,
    }

    setup_tracing()
    project_name = f"{job.dataset_id}_{job.model_name}" if job.model_name and job.model_name != "default" else job.dataset_id
    with eval_example_span(job.id, example_id, job.dataset_id, project_name=project_name):
        if job.target_type == "agent_studio":
            ctx = EvalContext(
                job_id=job.id,
                example_id=example_id,
                timeout=job.timeout,
                session_id=session_id,
                input_mapping=job.input_mapping,
            )
            tr = target.invoke(inputs, ctx)
            result["output_text"] = tr.output_text
            result["pred_sql"] = tr.output_text
            result["latency_ms"] = int(tr.latency_ms)
            result["error"] = tr.error
            result["trace_id"] = tr.trace_id
            result["events"] = tr.events
            result["start_time"] = tr.start_time
            result["end_time"] = tr.end_time

            if tr.trace_id and tr.events:
                span_id = export_workflow_trace(
                    tr.trace_id,
                    tr.events,
                    job.id,
                    example_id,
                    tr.output_text,
                )
                result["span_id"] = span_id

            if not tr.error:
                _score_result(result, record, job, meta)
        else:
            schema = meta.get("schema", "")
            if record.get("db_id") and db_dir:
                db_path = _find_database(record["db_id"], db_dir)
                if db_path:
                    schema = _get_db_schema(db_path)

            ctx = EvalContext(
                job_id=job.id,
                example_id=example_id,
                timeout=job.timeout,
                extra={"schema": schema},
            )
            inputs["schema"] = schema
            tr = target.invoke(inputs, ctx)
            result["output_text"] = tr.output_text
            result["pred_sql"] = tr.output_text
            result["latency_ms"] = int(tr.latency_ms)
            result["error"] = tr.error
            result["start_time"] = tr.start_time
            result["end_time"] = tr.end_time

            if tr.error:
                return result

            requires_execution = meta.get("requires_execution", True)
            if requires_execution and "execution_accuracy" in job.metrics and db_dir:
                db_path = _find_database(record["db_id"], db_dir)
                if not db_path:
                    result["error"] = f"Database not found: {record['db_id']}"
                    return result
                gold_results, gold_err = _execute_sql(db_path, record["query"])
                if gold_err:
                    result["error"] = f"Gold SQL error: {gold_err}"
                    return result
                pred_results, pred_err = _execute_sql(db_path, tr.output_text)
                if pred_err:
                    result["error"] = f"Predicted SQL error: {pred_err}"
                    return result
                result["correct"] = gold_results == pred_results
                result["scores"]["execution_accuracy"] = 1.0 if result["correct"] else 0.0
            else:
                _score_result(result, record, job, meta)

    return result


def run_job(job: EvaluationJob, phoenix_client=None) -> None:
    job.status = "running"
    job.started_at = time.time()
    setup_tracing()

    print(
        f"[evaluator] job {job.id} started — target={job.target_type} dataset={job.dataset_id}",
        flush=True,
    )

    try:
        meta = load_metadata(BUNDLED_DATASETS_DIR, job.dataset_id)
        if not job.system_prompt:
            job.system_prompt = meta.get("system_prompt", "")

        records = load_records(BUNDLED_DATASETS_DIR, job.dataset_id)
        if job.max_samples > 0:
            records = records[: job.max_samples]

        job.total = len(records)
        target = _build_target(job)
        session_id = None
        if job.target_type == "agent_studio":
            target.discover()
            if job.concurrency > 1:
                job.concurrency = 1

        db_dir = None
        if meta.get("requires_execution", True) and job.target_type == "llm_endpoint":
            db_dir = _ensure_spider_databases()

        results = []
        with ThreadPoolExecutor(max_workers=job.concurrency) as executor:
            futures = {
                executor.submit(
                    _evaluate_example, rec, job, meta, target, session_id, db_dir
                ): i
                for i, rec in enumerate(records)
            }
            for future in as_completed(futures):
                results.append(future.result())
                job.completed_count = len(results)
                job.progress = int(job.completed_count / job.total * 100) if job.total else 100

        correct = sum(1 for r in results if r.get("correct"))
        all_metric_scores: dict = {}
        for r in results:
            for k, v in r.get("scores", {}).items():
                all_metric_scores.setdefault(k, []).append(float(v))

        if all_metric_scores:
            primary = (
                "agent_goal_accuracy"
                if "agent_goal_accuracy" in all_metric_scores
                else "exact_match"
                if "exact_match" in all_metric_scores
                else "execution_accuracy"
                if "execution_accuracy" in all_metric_scores
                else next(iter(all_metric_scores))
            )
            job.accuracy = sum(all_metric_scores[primary]) / len(results) if results else 0.0
        elif results:
            job.accuracy = correct / len(results)
        else:
            job.accuracy = 0.0

        job.results = results

        out_dir = DATA_DIR / "results" / f"{job.dataset_id}_{job.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        results_file = out_dir / "results.json"
        with open(results_file, "w") as f:
            json.dump(
                {
                    "job_id": job.id,
                    "dataset_id": job.dataset_id,
                    "target_type": job.target_type,
                    "accuracy": job.accuracy,
                    "total": job.total,
                    "correct": correct,
                    "timestamp": datetime.now().isoformat(),
                    "results": results,
                },
                f,
                indent=2,
            )
        job.results_path = str(results_file)

        if phoenix_client is not None:
            try:
                if not phoenix_client.dataset_exists(job.dataset_id):
                    phoenix_client.upload_dataset(
                        name=job.dataset_id,
                        records=records,
                        description=meta.get("description", ""),
                        meta=meta,
                    )
            except Exception as e:
                print(f"[evaluator] Phoenix dataset upload failed: {e}", flush=True)

            try:
                phoenix_client.upload_evaluation_results(
                    dataset_id=job.dataset_id,
                    job_id=job.id,
                    model_name=job.model_name,
                    results=results,
                    records=records,
                )
            except Exception as e:
                print(f"[evaluator] Phoenix upload failed: {e}", flush=True)

        job.status = "completed"
        print(f"[evaluator] job {job.id} completed — accuracy={job.accuracy:.1%}", flush=True)

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        print(f"[evaluator] job {job.id} FAILED: {e}", flush=True)

    finally:
        job.finished_at = time.time()


def ingest_local_result(job: EvaluationJob, payload: dict) -> dict:
    """Score and append a result pushed by cai-eval-runner."""
    meta = load_metadata(BUNDLED_DATASETS_DIR, job.dataset_id)
    record = payload.get("record") or {}
    result = {
        "example_id": payload.get("example_id") or record.get("example_id", ""),
        "question": record.get("question", ""),
        "output_text": payload.get("output", ""),
        "pred_sql": payload.get("output", ""),
        "events": payload.get("events", []),
        "trace_id": payload.get("trace_id"),
        "latency_ms": payload.get("latency_ms", 0),
        "error": payload.get("error"),
        "scores": {},
        "correct": False,
    }
    if not result["error"]:
        _score_result(result, record, job, meta)
    return result
