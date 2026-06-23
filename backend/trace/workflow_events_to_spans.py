"""Convert Agent Studio workflow events to OpenTelemetry spans for Phoenix."""

from datetime import datetime, timezone
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

tracer = trace.get_tracer("cai-eval-platform.workflow")

EVENT_SPAN_MAP = {
    "task_started": ("task", SpanKind.INTERNAL),
    "task_completed": ("task", SpanKind.INTERNAL),
    "agent_execution_started": ("agent", SpanKind.INTERNAL),
    "agent_execution_completed": ("agent", SpanKind.INTERNAL),
    "agent_execution_error": ("agent", SpanKind.INTERNAL),
    "tool_usage_started": ("tool", SpanKind.INTERNAL),
    "tool_usage_finished": ("tool", SpanKind.INTERNAL),
    "tool_usage_error": ("tool", SpanKind.INTERNAL),
    "llm_call_started": ("llm", SpanKind.CLIENT),
    "llm_call_completed": ("llm", SpanKind.CLIENT),
    "llm_call_failed": ("llm", SpanKind.CLIENT),
    "crew_kickoff_completed": ("workflow", SpanKind.SERVER),
    "crew_kickoff_failed": ("workflow", SpanKind.SERVER),
}


def export_workflow_trace(
    trace_id: str,
    events: list[dict],
    job_id: str,
    example_id: str,
    output_text: str = "",
) -> Optional[str]:
    """Export workflow events as OTEL spans. Returns root span_id hex if exported."""
    if not events:
        return None

    root_span_id = None
    with tracer.start_as_current_span(
        "workflow.kickoff",
        kind=SpanKind.SERVER,
        attributes={
            "workflow.trace_id": trace_id,
            "eval.job_id": job_id,
            "eval.example_id": example_id,
        },
    ) as root:
        root_span_id = format(root.get_span_context().span_id, "016x")

        for i, event in enumerate(events):
            etype = event.get("type", "unknown")
            prefix, kind = EVENT_SPAN_MAP.get(etype, ("event", SpanKind.INTERNAL))
            name = _span_name(prefix, event)

            with tracer.start_as_current_span(
                name,
                kind=kind,
                attributes=_event_attributes(event, etype),
            ) as span:
                if etype.endswith("_error") or etype == "crew_kickoff_failed":
                    span.set_status(Status(StatusCode.ERROR, event.get("error", etype)))
                if etype == "crew_kickoff_completed":
                    span.set_attribute("output.value", output_text[:4096])

    return root_span_id


def _span_name(prefix: str, event: dict) -> str:
    if prefix == "agent":
        return f"agent.{event.get('agent_name', 'unknown')}"
    if prefix == "tool":
        return f"tool.{event.get('tool_name', 'unknown')}"
    if prefix == "task":
        return f"task.{event.get('task_name', 'unknown')}"
    if prefix == "llm":
        return f"llm.{event.get('model', 'call')}"
    return event.get("type", "event")


def _event_attributes(event: dict, etype: str) -> dict:
    attrs = {"event.type": etype}
    for key in (
        "agent_name",
        "agent_studio_id",
        "task_name",
        "tool_name",
        "model",
        "error",
    ):
        if event.get(key):
            attrs[f"workflow.{key}"] = str(event[key])[:1024]
    if event.get("response"):
        attrs["llm.response"] = str(event["response"])[:2048]
    if event.get("output"):
        attrs["workflow.output"] = str(event["output"])[:2048]
    ts = event.get("timestamp")
    if ts:
        attrs["event.timestamp"] = str(ts)
    return attrs


def parse_timestamp(ts: Optional[str]) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
