"""Convert Agent Studio workflow events to OpenTelemetry spans for Phoenix."""

import time
from datetime import datetime, timezone
from typing import Optional

from opentelemetry import context as otel_context
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


def _ts_to_ns(ts: Optional[str]) -> Optional[int]:
    """ISO timestamp string → nanoseconds since epoch (OTEL time unit)."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1e9)
    except Exception:
        return None


def export_workflow_trace(
    trace_id: str,
    events: list[dict],
    job_id: str,
    example_id: str,
    output_text: str = "",
) -> Optional[str]:
    """Export workflow events as OTEL spans with original event timestamps.

    Uses tracer.start_span() directly (not context manager) so we can set
    explicit start_time and end_time on every span. Without this, Phoenix
    shows the entire trace collapsed to <1 ms because Python processes all
    events nearly simultaneously.

    Returns root span_id hex if exported, else None.
    """
    if not events:
        return None

    now_ns = time.time_ns()
    timestamps = [_ts_to_ns(e.get("timestamp")) for e in events]
    valid_ts = [t for t in timestamps if t is not None]

    first_ts = valid_ts[0] if valid_ts else now_ns
    last_ts = max(valid_ts) if valid_ts else now_ns
    if last_ts <= first_ts:
        last_ts = first_ts + 1_000_000  # ensure ≥1 ms root duration

    root_span = tracer.start_span(
        "workflow.kickoff",
        kind=SpanKind.SERVER,
        start_time=first_ts,
        attributes={
            "workflow.trace_id": trace_id,
            "eval.job_id": job_id,
            "eval.example_id": example_id,
        },
    )
    root_span_id = format(root_span.get_span_context().span_id, "016x")

    root_ctx = trace.set_span_in_context(root_span)
    token = otel_context.attach(root_ctx)
    try:
        for i, event in enumerate(events):
            etype = event.get("type", "unknown")
            prefix, kind = EVENT_SPAN_MAP.get(etype, ("event", SpanKind.INTERNAL))
            name = _span_name(prefix, event)

            evt_start = timestamps[i] or now_ns
            if i + 1 < len(events):
                evt_end = timestamps[i + 1] or (evt_start + 1_000_000)
            else:
                evt_end = last_ts if last_ts > evt_start else evt_start + 1_000_000

            child = tracer.start_span(
                name,
                kind=kind,
                start_time=evt_start,
                attributes=_event_attributes(event, etype),
            )
            if etype.endswith("_error") or etype == "crew_kickoff_failed":
                child.set_status(Status(StatusCode.ERROR, event.get("error", etype)))
            if etype == "crew_kickoff_completed":
                child.set_attribute("output.value", output_text[:4096])
            child.end(end_time=evt_end)
    finally:
        otel_context.detach(token)
        root_span.end(end_time=last_ts)

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
