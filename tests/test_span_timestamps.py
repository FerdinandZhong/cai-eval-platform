"""Tests for workflow_events_to_spans.py — correct nanosecond timestamps."""

import sys
import pathlib
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

BACKEND = pathlib.Path(__file__).parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _iso(dt: datetime) -> str:
    return dt.isoformat()


BASE = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_events(*offsets_sec):
    """Return synthetic workflow events with ISO timestamps."""
    events = []
    types = [
        "agent_execution_started",
        "tool_usage_started",
        "tool_usage_finished",
        "agent_execution_completed",
        "crew_kickoff_completed",
    ]
    for i, sec in enumerate(offsets_sec):
        ts = BASE + timedelta(seconds=sec)
        events.append({
            "type": types[i % len(types)],
            "timestamp": _iso(ts),
            "agent_name": "test-agent",
        })
    return events


def _ns(sec_offset: float) -> int:
    dt = BASE + timedelta(seconds=sec_offset)
    return int(dt.timestamp() * 1e9)


class SpanRecorder:
    """Records start_span() calls instead of sending to a real OTEL backend."""
    def __init__(self):
        self.spans = []

    def start_span(self, name, kind=None, start_time=None, attributes=None, **kw):
        span = MagicMock()
        span.get_span_context.return_value = MagicMock(span_id=0x1234567890ABCDEF)
        entry = {"name": name, "start_time": start_time, "end_time": None, "mock": span}
        self.spans.append(entry)

        # Capture entry by reference so end() always updates the correct span
        def _end(end_time=None):
            entry["end_time"] = end_time

        span.end = _end
        return span


def test_root_span_uses_first_event_timestamp():
    events = _make_events(0, 1, 2, 3, 4)
    recorder = SpanRecorder()

    with patch("trace.workflow_events_to_spans.tracer", recorder):
        with patch("opentelemetry.context.attach", return_value=MagicMock()):
            with patch("opentelemetry.context.detach"):
                with patch("opentelemetry.trace.set_span_in_context", return_value=MagicMock()):
                    from trace.workflow_events_to_spans import export_workflow_trace
                    export_workflow_trace("tid", events, "job1", "ex1")

    root = next(s for s in recorder.spans if s["name"] == "workflow.kickoff")
    assert root["start_time"] == _ns(0), (
        f"Root span start_time should be {_ns(0)} (first event), got {root['start_time']}"
    )


def test_root_span_ends_at_last_event_timestamp():
    events = _make_events(0, 1, 2, 3, 10)
    recorder = SpanRecorder()

    with patch("trace.workflow_events_to_spans.tracer", recorder):
        with patch("opentelemetry.context.attach", return_value=MagicMock()):
            with patch("opentelemetry.context.detach"):
                with patch("opentelemetry.trace.set_span_in_context", return_value=MagicMock()):
                    from trace.workflow_events_to_spans import export_workflow_trace
                    export_workflow_trace("tid", events, "job1", "ex1")

    root = next(s for s in recorder.spans if s["name"] == "workflow.kickoff")
    assert root["end_time"] == _ns(10), (
        f"Root span end_time should be {_ns(10)} (last event), got {root['end_time']}"
    )


def test_ts_to_ns_z_suffix():
    """_ts_to_ns must handle Z-suffix ISO strings."""
    from trace.workflow_events_to_spans import _ts_to_ns
    ts = "2024-06-01T12:00:00Z"
    ns = _ts_to_ns(ts)
    expected = _ns(0)
    assert ns == expected, f"Expected {expected}, got {ns}"


def test_ts_to_ns_offset_aware():
    """_ts_to_ns must handle +00:00 suffix."""
    from trace.workflow_events_to_spans import _ts_to_ns
    ts = "2024-06-01T12:00:00+00:00"
    ns = _ts_to_ns(ts)
    assert ns == _ns(0)


def test_ts_to_ns_returns_none_for_empty():
    from trace.workflow_events_to_spans import _ts_to_ns
    assert _ts_to_ns(None) is None
    assert _ts_to_ns("") is None


def test_export_returns_none_for_empty_events():
    from trace.workflow_events_to_spans import export_workflow_trace
    result = export_workflow_trace("tid", [], "job1", "ex1")
    assert result is None
