"""Tests for tracing.py — threading.Lock race condition fix."""

import importlib
import sys
import threading


def _fresh_tracing_module():
    """Return a freshly imported tracing module (not from cache)."""
    for mod in list(sys.modules.keys()):
        if "tracing" in mod and "cai" not in mod and "test" not in mod:
            pass
    sys.modules.pop("tracing", None)
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "tracing",
        pathlib.Path(__file__).parent.parent / "backend" / "tracing.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # Stub out phoenix and openinference so no network calls happen
    sys.modules.setdefault("phoenix", type(sys)("phoenix"))
    sys.modules.setdefault("phoenix.otel", type(sys)("phoenix.otel"))
    sys.modules.setdefault("openinference", type(sys)("openinference"))
    sys.modules.setdefault("openinference.instrumentation", type(sys)("openinference.instrumentation"))
    sys.modules.setdefault("openinference.instrumentation.openai", type(sys)("openinference.instrumentation.openai"))

    call_log = []

    # Stub register to record calls
    sys.modules["phoenix.otel"].register = lambda **kw: call_log.append(("register", kw))

    class FakeInstrumentor:
        def instrument(self):
            call_log.append(("instrument",))

    sys.modules["openinference.instrumentation.openai"].OpenAIInstrumentor = FakeInstrumentor

    spec.loader.exec_module(mod)
    return mod, call_log


def test_setup_tracing_runs_once():
    """setup_tracing() called N times must only execute setup body once."""
    mod, call_log = _fresh_tracing_module()

    for _ in range(5):
        mod.setup_tracing()

    register_calls = [c for c in call_log if c[0] == "register"]
    assert len(register_calls) == 1, f"Expected 1 register call, got {register_calls}"


def test_setup_tracing_thread_safe():
    """Concurrent calls must not execute setup body more than once."""
    mod, call_log = _fresh_tracing_module()

    errors = []
    threads = [
        threading.Thread(target=mod.setup_tracing)
        for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    register_calls = [c for c in call_log if c[0] == "register"]
    assert len(register_calls) == 1, (
        f"Race condition: register called {len(register_calls)} times "
        f"(expected 1) from 20 concurrent threads"
    )


def test_setup_tracing_sets_initialized():
    """After setup_tracing(), _initialized must be True."""
    mod, _ = _fresh_tracing_module()
    assert mod._initialized is False
    mod.setup_tracing()
    assert mod._initialized is True
