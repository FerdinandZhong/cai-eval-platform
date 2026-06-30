"""
Arize Phoenix client — dataset upload and evaluation experiment logging.
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

def _phoenix_base_url() -> str:
    """Root URL of the Phoenix REST API (no trailing slash).

    Defaults to localhost so a co-located deployment needs zero config; set
    PHOENIX_BASE_URL to point at a standalone/remote Phoenix instead.
    """
    base = os.environ.get("PHOENIX_BASE_URL")
    if base:
        return base.rstrip("/")
    port = int(os.environ.get("PHOENIX_PORT", 6006))
    return f"http://127.0.0.1:{port}"


PHOENIX_PORT = int(os.environ.get("PHOENIX_PORT", 6006))
_BASE = _phoenix_base_url()


def _http(method: str, path: str, body: Optional[dict] = None, params: str = "") -> dict:
    url = f"{_BASE}{path}"
    if params:
        url = f"{url}?{params}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Phoenix {method} {path} → {e.code}: {e.read().decode()}") from e


def is_ready() -> bool:
    try:
        urllib.request.urlopen(f"{_BASE}/healthz", timeout=2)
        return True
    except Exception:
        return False


def _find_dataset(name: str) -> Optional[dict]:
    try:
        result = _http("GET", "/v1/datasets")
        for d in result.get("data", []):
            if d.get("name") == name:
                return d
    except Exception:
        pass
    return None


def dataset_exists(name: str) -> bool:
    return _find_dataset(name) is not None


_UPLOAD_CHUNK_SIZE = 200


def upload_dataset(
    name: str,
    records: list,
    description: str = "",
    meta: Optional[dict] = None,
) -> dict:
    from dataset_schema import records_to_phoenix_arrays

    meta = meta or {}
    inputs, outputs, metadata = records_to_phoenix_arrays(records, meta)

    result: dict = {}
    for i in range(0, len(inputs), _UPLOAD_CHUNK_SIZE):
        chunk_inputs   = inputs[i:i + _UPLOAD_CHUNK_SIZE]
        chunk_outputs  = outputs[i:i + _UPLOAD_CHUNK_SIZE]
        chunk_metadata = metadata[i:i + _UPLOAD_CHUNK_SIZE]
        action = "create" if i == 0 else "append"
        print(f"[phoenix] uploading '{name}' chunk {i // _UPLOAD_CHUNK_SIZE + 1}"
              f" ({len(chunk_inputs)} records, action={action})", flush=True)
        result = _http(
            "POST",
            "/v1/datasets/upload",
            {
                "name": name,
                "description": description,
                "action": action,
                "inputs": chunk_inputs,
                "outputs": chunk_outputs,
                "metadata": chunk_metadata,
            },
            params="sync=true",
        )
    return result


def upload_evaluation_results(
    dataset_id: str,
    job_id: str,
    model_name: str,
    results: list,
    records: Optional[list] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    experiment_name = f"{dataset_id}_{model_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    ds = _find_dataset(dataset_id)
    if ds is None:
        raise RuntimeError(f"Dataset '{dataset_id}' not found in Phoenix")
    phoenix_dataset_id = ds["id"]

    examples_resp = _http("GET", f"/v1/datasets/{phoenix_dataset_id}/examples")
    examples = examples_resp.get("data", {}).get("examples", [])

    example_id_by_key: dict[str, str] = {}
    for ex in examples:
        meta = ex.get("metadata") or {}
        eid = meta.get("example_id") or meta.get("exampleId")
        if eid:
            example_id_by_key[str(eid)] = ex["id"]
        else:
            inp = ex.get("input") or {}
            q = inp.get("question") or inp.get("user_input") or ""
            if q:
                example_id_by_key[q] = ex["id"]

    exp_resp = _http(
        "POST",
        f"/v1/datasets/{phoenix_dataset_id}/experiments",
        {
            "name": experiment_name,
            "metadata": {"model": model_name, "job_id": job_id},
        },
    )
    experiment_id = exp_resp.get("data", {}).get("id") or exp_resp.get("id")
    if not experiment_id:
        raise RuntimeError(f"Unexpected experiment response: {exp_resp}")

    uploaded = 0
    for r in results:
        example_key = str(r.get("example_id", r.get("question", "")))
        example_id = example_id_by_key.get(example_key)
        if not example_id and records:
            for rec in records:
                if rec.get("example_id") == r.get("example_id"):
                    q = rec.get("question", "")
                    example_id = example_id_by_key.get(q)
                    break
        if not example_id:
            continue

        try:
            run_output = {
                "output": r.get("output_text") or r.get("pred_sql", ""),
                "pred_sql": r.get("pred_sql", ""),
                "trace_id": r.get("trace_id"),
                "span_id": r.get("span_id"),
                "workflow_phoenix_url": r.get("workflow_phoenix_url"),
            }
            if r.get("events"):
                run_output["events"] = r["events"]
            judge_traces = r.get("judge_traces", {})
            if judge_traces:
                run_output["judge_traces"] = judge_traces

            start_time = r.get("start_time") or now
            end_time = r.get("end_time") or now

            run_resp = _http(
                "POST",
                f"/v1/experiments/{experiment_id}/runs",
                {
                    "dataset_example_id": example_id,
                    "output": run_output,
                    "repetition_number": 1,
                    "start_time": start_time,
                    "end_time": end_time,
                    "error": r.get("error"),
                },
            )
            run_id = run_resp.get("data", {}).get("id") or run_resp.get("id")
            uploaded += 1

            scores = r.get("scores") or {}
            if not scores and "correct" in r:
                scores = {"execution_accuracy": 1.0 if r.get("correct") else 0.0}
            for metric_name, score_val in scores.items():
                if run_id:
                    try:
                        _http(
                            "POST",
                            "/v1/experiment_evaluations",
                            {
                                "experiment_run_id": run_id,
                                "name": metric_name,
                                "annotator_kind": "CODE",
                                "start_time": start_time,
                                "end_time": end_time,
                                "result": {
                                    "score": float(score_val),
                                    "label": "correct" if score_val >= 0.9 else "incorrect",
                                },
                            },
                        )
                    except Exception as e:
                        print(f"[phoenix] eval upload failed ({metric_name}): {e}", flush=True)

        except Exception as e:
            print(f"[phoenix] run upload failed for example {example_id}: {e}", flush=True)

    print(
        f"[phoenix] uploaded {uploaded}/{len(results)} runs to experiment '{experiment_name}'",
        flush=True,
    )


def get_phoenix_url() -> str:
    return "/"
