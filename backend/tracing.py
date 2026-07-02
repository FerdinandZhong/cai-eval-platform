"""OpenTelemetry / Phoenix tracing setup."""

import os
import threading

# One-time OpenAI auto-instrumentation
_setup_done = False
_setup_lock = threading.Lock()

# Per-project TracerProvider cache
_project_providers: dict = {}
_provider_lock = threading.Lock()


def phoenix_base_url() -> str:
    """Root URL of the Phoenix server (no trailing slash).

    Defaults to localhost so a co-located deployment needs zero config; set
    PHOENIX_BASE_URL to point at a standalone/remote Phoenix instead.
    """
    base = os.environ.get("PHOENIX_BASE_URL")
    if base:
        return base.rstrip("/")
    port = int(os.environ.get("PHOENIX_PORT", 6006))
    return f"http://127.0.0.1:{port}"


def _otlp_endpoint() -> str:
    return (
        os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or f"{phoenix_base_url()}/v1/traces"
    )


def setup_tracing() -> None:
    """Install OpenAI auto-instrumentation once.

    Phoenix project registration is done lazily per project in
    _get_project_tracer(), so this function no longer calls register().
    """
    global _setup_done
    with _setup_lock:
        if _setup_done:
            return
        try:
            from openinference.instrumentation.openai import OpenAIInstrumentor

            OpenAIInstrumentor().instrument()
        except Exception as e:
            print(f"[tracing] OpenAI instrumentor failed: {e}", flush=True)
        _setup_done = True


def _get_project_tracer(project_name: str):
    """Return a tracer backed by a TracerProvider whose Resource carries
    openinference.project.name = project_name.

    Phoenix routes spans to a project via the TracerProvider's Resource
    attribute, not span-level attributes.  Each unique project name gets its
    own provider (created on first use, then cached).
    """
    with _provider_lock:
        if project_name not in _project_providers:
            try:
                from phoenix.otel import register

                provider = register(
                    endpoint=_otlp_endpoint(),
                    project_name=project_name,
                    set_global_tracer_provider=False,
                )
                _project_providers[project_name] = provider
            except Exception as e:
                print(
                    f"[tracing] Phoenix register failed for project '{project_name}': {e}",
                    flush=True,
                )
                # Fall back to the global tracer provider so spans still emit
                from opentelemetry import trace

                return trace.get_tracer("cai-eval-platform")
        provider = _project_providers[project_name]
    return provider.get_tracer("cai-eval-platform")


def eval_example_span(job_id: str, example_id: str, dataset_id: str,
                      project_name: str = "cai-eval"):
    """Context manager for per-example eval span.

    Uses a TracerProvider whose Resource has openinference.project.name set,
    which is what Phoenix uses to route spans to the correct project.
    """
    tracer = _get_project_tracer(project_name)
    return tracer.start_as_current_span(
        "eval.example",
        attributes={
            "eval.job_id": job_id,
            "eval.example_id": example_id,
            "eval.dataset_id": dataset_id,
            "openinference.project.name": project_name,
        },
    )
