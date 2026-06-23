#!/usr/bin/env python3
"""CLI to execute local Python workflow scripts and push results to CAI Eval Platform."""

import importlib.util
import json
import sys
import time
from pathlib import Path

import click
import httpx

from cai_eval_runner.client import EvalClient


def _load_run_fn(script_path: Path):
    spec = importlib.util.spec_from_file_location("user_workflow", script_path)
    if spec is None or spec.loader is None:
        raise click.ClickException(f"Cannot load script: {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "run"):
        raise click.ClickException("Script must define run(inputs: dict) -> dict")
    return mod.run


@click.group()
def main():
    """CAI Eval Runner — local workflow execution for CAI Eval Platform."""


@main.command("run")
@click.option("--script", required=True, type=click.Path(exists=True), help="Python script with run(inputs) function")
@click.option("--dataset", required=True, type=click.Path(exists=True), help="Dataset JSON file (array of records)")
@click.option("--eval-server", required=True, help="Eval platform base URL")
@click.option("--job-id", required=True, help="Job ID from eval platform UI")
@click.option("--job-token", default="", help="Job token for local_script jobs")
@click.option("--max-samples", default=0, type=int, help="Limit examples (0 = all)")
def run_cmd(script, dataset, eval_server, job_id, job_token, max_samples):
    """Run workflow script over dataset and push results to eval platform."""
    run_fn = _load_run_fn(Path(script))
    records = json.loads(Path(dataset).read_text())
    if not isinstance(records, list):
        raise click.ClickException("Dataset must be a JSON array")
    if max_samples > 0:
        records = records[:max_samples]

    client = EvalClient(eval_server, job_id, job_token)
    click.echo(f"Running {len(records)} examples from {dataset}")

    for i, record in enumerate(records):
        example_id = record.get("example_id") or record.get("id") or f"ex_{i}"
        inputs = {k: v for k, v in record.items() if k not in ("expected_output", "reference", "query", "reference_tool_calls")}
        start = time.time()
        error = None
        output = ""
        events = []
        trace_id = None
        try:
            result = run_fn(inputs)
            if isinstance(result, dict):
                output = str(result.get("output", result.get("output_text", "")))
                events = result.get("events", [])
                trace_id = result.get("trace_id")
            else:
                output = str(result)
        except Exception as e:
            error = str(e)

        payload = {
            "example_id": example_id,
            "output": output,
            "events": events,
            "trace_id": trace_id,
            "latency_ms": int((time.time() - start) * 1000),
            "error": error,
            "record": record,
        }
        resp = client.push_result(payload)
        click.echo(f"  [{i+1}/{len(records)}] {example_id} → {resp.get('completed_count', '?')} accepted")

    click.echo("Done.")


if __name__ == "__main__":
    main()
