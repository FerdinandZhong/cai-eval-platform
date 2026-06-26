"""Tests for agent_studio.py — session-per-example fix."""

import sys
import pathlib

# Add backend to sys.path so relative imports inside the module resolve
BACKEND = pathlib.Path(__file__).parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from unittest.mock import MagicMock, patch, call
from targets.agent_studio import AgentStudioConfig, AgentStudioWorkflowTarget
from targets.base import EvalContext


def _make_target(session_counter=None):
    cfg = AgentStudioConfig(workflow_url="http://fake-studio")
    target = AgentStudioWorkflowTarget(cfg)

    counter = {"n": 0}

    def fake_create_session():
        counter["n"] += 1
        return {"session_id": f"session-{counter['n']}"}

    def fake_kickoff(payload):
        return {"trace_id": f"trace-{payload.get('session_id')}"}

    def fake_get_events(trace_id):
        return [{"type": "crew_kickoff_completed", "output": "done", "timestamp": "2024-01-01T00:00:00Z"}]

    def fake_discover():
        from targets.base import TargetSchema
        target._schema = TargetSchema(
            target_type="agent_studio",
            input_fields=["question"],
            is_conversational=False,
        )
        return target._schema

    target.client.create_session = fake_create_session
    target.client.kickoff = fake_kickoff
    target.client.get_events = fake_get_events
    target.discover = fake_discover

    return target, counter


def _ctx(**kwargs):
    defaults = dict(
        job_id="job-1",
        example_id="ex-1",
        timeout=30,
        input_mapping={},
        session_id=None,
    )
    defaults.update(kwargs)
    return EvalContext(**defaults)


def test_each_example_gets_fresh_session():
    """invoke() called N times must create N distinct sessions."""
    target, counter = _make_target()
    target.discover()

    results = []
    for i in range(3):
        ctx = _ctx(example_id=f"ex-{i}")
        r = target.invoke({"question": f"Q{i}"}, ctx)
        results.append(r)

    assert counter["n"] == 3, f"Expected 3 sessions, got {counter['n']}"
    # Each kickoff used a distinct session_id
    session_ids = set()
    for r in results:
        raw = r.raw or {}
        kickoff = raw.get("kickoff", {})
        trace_id = kickoff.get("trace_id", "")
        session_ids.add(trace_id)
    assert len(session_ids) == 3, f"Expected 3 distinct trace IDs, got {session_ids}"


def test_explicit_session_id_not_overridden():
    """If ctx.session_id is set, create_session() must NOT be called."""
    target, counter = _make_target()
    target.discover()

    ctx = _ctx(session_id="pinned-session-123")
    r = target.invoke({"question": "Q"}, ctx)

    assert counter["n"] == 0, "create_session() should not be called when ctx.session_id is set"
    assert r.error is None or r.error == "", f"Unexpected error: {r.error}"


def test_no_shared_session_state_between_invocations():
    """target._session_id must stay None — session state must not leak between calls."""
    target, counter = _make_target()
    target.discover()

    target.invoke({"question": "A"}, _ctx(example_id="e1"))
    target.invoke({"question": "B"}, _ctx(example_id="e2"))

    assert target._session_id is None, (
        f"_session_id should remain None (was: {target._session_id!r}); "
        "sessions must not be shared across invocations"
    )
