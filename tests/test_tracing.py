"""Tests for tracing.py — per-project TracerProvider routing."""

import importlib
import sys
import threading
import types


def _fresh_tracing_module():
    """Return a freshly imported tracing module with Phoenix/OTel stubbed out."""
    sys.modules.pop("tracing", None)

    # Stub openinference
    oi = types.ModuleType("openinference")
    oi_instr = types.ModuleType("openinference.instrumentation")
    oi_openai = types.ModuleType("openinference.instrumentation.openai")
    sys.modules["openinference"] = oi
    sys.modules["openinference.instrumentation"] = oi_instr
    sys.modules["openinference.instrumentation.openai"] = oi_openai

    call_log = []

    class FakeInstrumentor:
        def instrument(self):
            call_log.append("instrument")

    oi_openai.OpenAIInstrumentor = FakeInstrumentor

    # Stub phoenix.otel — register returns a fake TracerProvider
    phoenix = types.ModuleType("phoenix")
    phoenix_otel = types.ModuleType("phoenix.otel")
    sys.modules["phoenix"] = phoenix
    sys.modules["phoenix.otel"] = phoenix_otel

    class FakeProvider:
        def __init__(self, project_name):
            self.project_name = project_name

        def get_tracer(self, name):
            return object()

    def fake_register(endpoint="", project_name="default",
                      set_global_tracer_provider=True):
        call_log.append(("register", project_name))
        return FakeProvider(project_name)

    phoenix_otel.register = fake_register

    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "tracing",
        pathlib.Path(__file__).parent.parent / "backend" / "tracing.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, call_log


def test_setup_tracing_instruments_openai_once():
    """setup_tracing() called N times must only install OpenAI instrumentation once."""
    mod, call_log = _fresh_tracing_module()

    for _ in range(5):
        mod.setup_tracing()

    instrument_calls = [c for c in call_log if c == "instrument"]
    assert len(instrument_calls) == 1, f"Expected 1 instrument call, got {instrument_calls}"


def test_setup_tracing_does_not_call_register():
    """setup_tracing() must NOT call phoenix register — that is done per-project."""
    mod, call_log = _fresh_tracing_module()
    mod.setup_tracing()

    register_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "register"]
    assert len(register_calls) == 0, f"setup_tracing should not call register, got {register_calls}"


def test_get_project_tracer_creates_provider_per_project():
    """Each unique project name gets its own register() call."""
    mod, call_log = _fresh_tracing_module()

    mod._get_project_tracer("dataset_a_model_x")
    mod._get_project_tracer("dataset_b_model_y")

    register_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "register"]
    projects = [c[1] for c in register_calls]
    assert "dataset_a_model_x" in projects
    assert "dataset_b_model_y" in projects
    assert len(register_calls) == 2


def test_get_project_tracer_caches_provider():
    """Calling _get_project_tracer with the same name must not re-register."""
    mod, call_log = _fresh_tracing_module()

    mod._get_project_tracer("my_project")
    mod._get_project_tracer("my_project")
    mod._get_project_tracer("my_project")

    register_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "register"]
    assert len(register_calls) == 1, f"Expected 1 register call, got {len(register_calls)}"


def test_setup_tracing_thread_safe():
    """Concurrent setup_tracing() calls must only instrument once."""
    mod, call_log = _fresh_tracing_module()

    threads = [threading.Thread(target=mod.setup_tracing) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    instrument_calls = [c for c in call_log if c == "instrument"]
    assert len(instrument_calls) == 1, (
        f"Race condition: instrument called {len(instrument_calls)} times "
        f"(expected 1) from 20 concurrent threads"
    )


def test_get_project_tracer_thread_safe():
    """Concurrent calls for the same project must only register once."""
    mod, call_log = _fresh_tracing_module()

    threads = [
        threading.Thread(target=mod._get_project_tracer, args=("shared_project",))
        for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    register_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "register"]
    assert len(register_calls) == 1, (
        f"Race condition: register called {len(register_calls)} times "
        f"(expected 1) from 20 concurrent threads"
    )
