"""Tests for evaluator.py — Spider DB download uses urllib not curl."""

import sys
import pathlib
import importlib

BACKEND = pathlib.Path(__file__).parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_no_subprocess_import_in_evaluator():
    """evaluator.py must not import subprocess (curl was the only user)."""
    import ast
    src = (BACKEND / "evaluator.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess", (
                    "evaluator.py imports subprocess — curl dependency may have returned"
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "subprocess", (
                "evaluator.py imports from subprocess"
            )


def test_urllib_used_for_spider_download():
    """_ensure_spider_databases must use urllib.request.urlretrieve, not curl."""
    src = (BACKEND / "evaluator.py").read_text()
    assert "urlretrieve" in src, "urllib.request.urlretrieve not found in evaluator.py"
    assert "curl" not in src, "curl still referenced in evaluator.py"


def test_ensure_spider_databases_skips_if_present(tmp_path):
    """_ensure_spider_databases must be a no-op if databases dir already has content."""
    import types, sys

    # Stub out ragas and its transitive deps before importing evaluator
    for mod in ["ragas", "ragas.messages", "ragas.llms", "ragas.llms.base",
                "ragas.evaluation", "langchain_community",
                "langchain_community.chat_models",
                "langchain_community.chat_models.vertexai"]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # Stub trace.event_to_ragas
    fake_e2r = types.ModuleType("trace.event_to_ragas")
    fake_e2r.events_to_user_input = lambda *a, **kw: []
    fake_e2r.extract_reference_tool_calls = lambda *a, **kw: []
    sys.modules["trace.event_to_ragas"] = fake_e2r

    # Clear cached evaluator so it re-imports with stubs
    sys.modules.pop("evaluator", None)

    import evaluator as ev
    original = ev.DATA_DIR
    ev.DATA_DIR = tmp_path

    # Create a fake populated databases dir
    db_dir = tmp_path / "spider" / "databases" / "fake_db"
    db_dir.mkdir(parents=True)
    (db_dir / "fake_db.sqlite").write_bytes(b"fake")

    try:
        result = ev._ensure_spider_databases()
        assert result == tmp_path / "spider" / "databases"
    finally:
        ev.DATA_DIR = original
