"""Smoke tests for the custom metric define endpoint."""

import sys
import pathlib
import importlib

import pytest

BACKEND = pathlib.Path(__file__).parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# ── Shared stubs ──────────────────────────────────────────────────────────────

def _stub_heavy_deps():
    """Stub out heavy deps so FastAPI app can be imported without them."""
    import types

    def _make(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    def _ensure(name):
        if name not in sys.modules:
            _make(name)
        return sys.modules[name]

    for mod_name in [
        "opentelemetry",
        "opentelemetry.sdk",
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.trace.export",
        "opentelemetry.exporter",
        "opentelemetry.exporter.otlp",
        "opentelemetry.exporter.otlp.proto",
        "opentelemetry.exporter.otlp.proto.grpc",
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        "opentelemetry.trace",
        "openinference",
        "openinference.instrumentation",
        "openinference.instrumentation.httpx",
        "openinference.instrumentation.openai",
        "datasets",
        "sqlalchemy",
        "httpx",
        "phoenix",
        "phoenix.otel",
    ]:
        _ensure(mod_name)

    # ragas submodules — need real-looking classes for ragas.messages
    ragas_mod = _ensure("ragas")
    ragas_metrics = _ensure("ragas.metrics")
    ragas_messages = _ensure("ragas.messages")

    # Define minimal message stubs used by trace/event_to_ragas.py
    class _Msg:
        def __init__(self, content="", **kw):
            self.content = content
            for k, v in kw.items():
                setattr(self, k, v)

    class _ToolCall(_Msg):
        def __init__(self, name="", args=None, **kw):
            super().__init__(**kw)
            self.name = name
            self.args = args or {}

    ragas_messages.AIMessage = type("AIMessage", (_Msg,), {})
    ragas_messages.HumanMessage = type("HumanMessage", (_Msg,), {})
    ragas_messages.ToolCall = _ToolCall
    ragas_messages.ToolMessage = type("ToolMessage", (_Msg,), {})

    # ragas_compat must not blow up
    if "ragas_compat" not in sys.modules:
        rc = types.ModuleType("ragas_compat")
        sys.modules["ragas_compat"] = rc


@pytest.fixture(autouse=True)
def _fresh_metrics(monkeypatch):
    """Each test gets a clean METRICS dict so registrations don't leak."""
    import metrics as m_mod
    original = dict(m_mod.METRICS)
    yield
    m_mod.METRICS.clear()
    m_mod.METRICS.update(original)


# ── Unit tests: metrics registry ──────────────────────────────────────────────

def test_register_and_call():
    from metrics import register, METRICS
    def score(pred, gold, **kw):
        return float(pred == gold)
    register("_test_eq", score, "equality", "binary")
    assert "_test_eq" in METRICS
    assert METRICS["_test_eq"]["fn"]("a", "a") == 1.0
    assert METRICS["_test_eq"]["fn"]("a", "b") == 0.0


def test_load_custom_metrics_from_disk(tmp_path):
    from metrics import load_custom_metrics, METRICS
    custom_dir = tmp_path / "custom_metrics"
    custom_dir.mkdir()
    (custom_dir / "my_metric.py").write_text(
        'DESCRIPTION = "test metric"\n'
        'METRIC_TYPE = "continuous"\n'
        'TASK_TYPES = ["general"]\n\n'
        "def score(pred, gold, **kw):\n    return 0.42\n"
    )
    load_custom_metrics(tmp_path)
    assert "my_metric" in METRICS
    assert METRICS["my_metric"]["description"] == "test metric"
    assert METRICS["my_metric"]["fn"]("x", "y") == 0.42


def test_load_custom_metrics_skips_no_score(tmp_path):
    from metrics import load_custom_metrics, METRICS
    custom_dir = tmp_path / "custom_metrics"
    custom_dir.mkdir()
    (custom_dir / "bad_metric.py").write_text("def not_score(x): return 1\n")
    load_custom_metrics(tmp_path)
    assert "bad_metric" not in METRICS


def test_load_custom_metrics_skips_syntax_error(tmp_path):
    from metrics import load_custom_metrics, METRICS
    custom_dir = tmp_path / "custom_metrics"
    custom_dir.mkdir()
    (custom_dir / "broken.py").write_text("def score(pred, gold\n")
    load_custom_metrics(tmp_path)  # must not raise
    assert "broken" not in METRICS


# ── Integration tests: POST /api/metrics/define ───────────────────────────────

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    _stub_heavy_deps()
    tmp = tmp_path_factory.mktemp("data")

    import types, sys as _sys
    # Stub tracing.setup_tracing so app startup doesn't connect to Phoenix
    tracing_mod = types.ModuleType("tracing")
    tracing_mod.setup_tracing = lambda: None
    tracing_mod.eval_example_span = lambda *a, **k: None
    _sys.modules["tracing"] = tracing_mod

    import os
    os.environ["DATA_DIR"] = str(tmp)
    os.environ["DATASETS_DIR"] = str(tmp / "datasets")

    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def test_define_metric_happy_path(client):
    r = client.post("/api/metrics/define", json={
        "name": "exact_match_custom",
        "description": "exact equality",
        "code": "def score(pred, gold, **kw):\n    return float(pred.strip() == gold.strip())\n",
    })
    assert r.status_code == 200
    assert r.json()["defined"] == "exact_match_custom"

    # Metric should now appear in the list
    r2 = client.get("/api/metrics")
    names = [m["name"] for m in r2.json()["metrics"]]
    assert "exact_match_custom" in names


def test_define_metric_syntax_error(client):
    r = client.post("/api/metrics/define", json={
        "name": "bad_syntax",
        "code": "def score(pred, gold\n    return 1\n",
    })
    assert r.status_code == 400
    assert "Syntax error" in r.json()["detail"]


def test_define_metric_missing_score_fn(client):
    r = client.post("/api/metrics/define", json={
        "name": "no_score",
        "code": "def helper(x): return x\n",
    })
    assert r.status_code == 400
    assert "score" in r.json()["detail"]


def test_define_metric_import_error(client):
    r = client.post("/api/metrics/define", json={
        "name": "needs_missing_pkg",
        "code": (
            "import this_package_does_not_exist_xyz\n"
            "def score(pred, gold, **kw):\n"
            "    return this_package_does_not_exist_xyz.compute(pred, gold)\n"
        ),
    })
    assert r.status_code == 400
    assert "Import error" in r.json()["detail"] or "Error" in r.json()["detail"]


def test_define_metric_wrong_return_type(client):
    r = client.post("/api/metrics/define", json={
        "name": "returns_string",
        "code": 'def score(pred, gold, **kw):\n    return "yes" if pred == gold else "no"\n',
    })
    assert r.status_code == 400
    assert "numeric" in r.json()["detail"].lower() or "Dry-run" in r.json()["detail"]


def test_define_metric_duplicate(client):
    code = "def score(pred, gold, **kw):\n    return 1.0\n"
    client.post("/api/metrics/define", json={"name": "dup_metric", "code": code})
    r = client.post("/api/metrics/define", json={"name": "dup_metric", "code": code})
    assert r.status_code == 409


def test_define_metric_missing_name(client):
    r = client.post("/api/metrics/define", json={
        "code": "def score(pred, gold, **kw):\n    return 1.0\n",
    })
    assert r.status_code == 400


def test_define_metric_missing_code(client):
    r = client.post("/api/metrics/define", json={"name": "no_code_metric"})
    assert r.status_code == 400
