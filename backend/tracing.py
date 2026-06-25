"""OpenTelemetry / Phoenix tracing setup."""

import os
import threading

_initialized = False
_lock = threading.Lock()


def setup_tracing() -> None:
    global _initialized
    with _lock:
        if _initialized:
            return

        phoenix_port = int(os.environ.get("PHOENIX_PORT", 6006))
        endpoint = f"http://127.0.0.1:{phoenix_port}/v1/traces"
        project = os.environ.get("PHOENIX_PROJECT", "cai-eval")

        try:
            from phoenix.otel import register

            register(project_name=project, endpoint=endpoint)
        except Exception as e:
            print(f"[tracing] Phoenix OTEL register failed: {e}", flush=True)

        try:
            from openinference.instrumentation.openai import OpenAIInstrumentor

            OpenAIInstrumentor().instrument()
        except Exception as e:
            print(f"[tracing] OpenAI instrumentor failed: {e}", flush=True)

        _initialized = True


def eval_example_span(job_id: str, example_id: str, dataset_id: str):
    """Context manager for per-example eval span."""
    from opentelemetry import trace

    tracer = trace.get_tracer("cai-eval-platform")
    return tracer.start_as_current_span(
        "eval.example",
        attributes={
            "eval.job_id": job_id,
            "eval.example_id": example_id,
            "eval.dataset_id": dataset_id,
        },
    )
