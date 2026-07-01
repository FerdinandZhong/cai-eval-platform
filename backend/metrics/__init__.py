"""Metric registry for evaluation benchmarks."""

from pathlib import Path
from typing import Callable, Optional

METRICS: dict[str, dict] = {}


def register(
    name: str,
    fn: Callable,
    description: str,
    metric_type: str = "binary",
    requires_config: bool = False,
    config_fields: Optional[list] = None,
    task_types: Optional[list] = None,
) -> None:
    METRICS[name] = {
        "name": name,
        "fn": fn,
        "description": description,
        "type": metric_type,
        "requires_config": requires_config,
        "config_fields": config_fields or [],
        "task_types": task_types or ["text2sql", "agent", "general"],
    }


def list_metrics(task_type: Optional[str] = None) -> list[dict]:
    out = []
    for m in METRICS.values():
        if task_type and task_type not in m.get("task_types", []):
            continue
        out.append(
            {
                "name": m["name"],
                "description": m["description"],
                "type": m["type"],
                "requires_config": m["requires_config"],
                "config_fields": m["config_fields"],
                "task_types": m.get("task_types", []),
            }
        )
    return out


def load_custom_metrics(data_dir: Path) -> None:
    """Load persisted custom metric .py files from DATA_DIR/custom_metrics/."""
    custom_dir = data_dir / "custom_metrics"
    if not custom_dir.exists():
        return
    for py_file in sorted(custom_dir.glob("*.py")):
        name = py_file.stem
        if name in METRICS:
            continue
        try:
            ns: dict = {}
            exec(compile(py_file.read_text(), str(py_file), "exec"), ns)  # noqa: S102
            fn = ns.get("score")
            if not callable(fn):
                continue
            register(
                name,
                fn,
                ns.get("DESCRIPTION", ""),
                ns.get("METRIC_TYPE", "continuous"),
                task_types=ns.get("TASK_TYPES", ["text2sql", "agent", "general"]),
            )
        except Exception:
            pass


from . import component_match as _cm
from . import exact_match as _em
from . import execution_accuracy as _ea
from . import llm_judge as _lj
from . import ragas_agent as _ra
from . import token_f1 as _tf

register(
    "execution_accuracy",
    _ea.score,
    "Execute both gold and predicted SQL against the database and compare result sets.",
    "binary",
    task_types=["text2sql"],
)
register(
    "exact_match",
    _em.score,
    "Exact string match after lowercasing and whitespace normalization.",
    "binary",
)
register(
    "token_f1",
    _tf.score,
    "Token-level F1 score between predicted and gold output.",
    "continuous",
)
register(
    "component_match",
    _cm.score,
    "Fraction of SQL clauses with matching token sets.",
    "continuous",
    task_types=["text2sql"],
)
register(
    "llm_as_judge_sql",
    _lj.score,
    "LLM judge for semantic SQL equivalence.",
    "binary",
    requires_config=True,
    config_fields=[
        {"name": "url", "label": "Judge LLM URL", "type": "url", "placeholder": "https://..."},
        {"name": "token", "label": "API Token", "type": "password", "placeholder": "sk-..."},
        {"name": "model", "label": "Model Name", "type": "text", "placeholder": "default"},
    ],
    task_types=["text2sql"],
)
register(
    "agent_goal_accuracy",
    lambda pred, gold, **kw: _ra.score_agent_goal_with_reference(
        kw.get("user_input", []), gold, kw.get("config")
    )[0],
    "Ragas AgentGoalAccuracyWithReference — did the workflow achieve the expected outcome?",
    "binary",
    requires_config=True,
    config_fields=[
        {"name": "url", "label": "Judge LLM URL", "type": "url", "placeholder": "https://..."},
        {"name": "token", "label": "API Token", "type": "password", "placeholder": "sk-..."},
        {"name": "model", "label": "Model Name", "type": "text", "placeholder": "default"},
    ],
    task_types=["agent", "general"],
)
register(
    "tool_call_accuracy",
    lambda pred, gold, **kw: _ra.score_tool_call_accuracy(
        kw.get("user_input", []),
        kw.get("reference_tool_calls", []),
        config=kw.get("config"),
    )[0],
    "Ragas ToolCallAccuracy — compare tool call sequence and arguments.",
    "continuous",
    task_types=["agent"],
)
register(
    "tool_call_f1",
    lambda pred, gold, **kw: _ra.score_tool_call_f1(
        kw.get("user_input", []),
        kw.get("reference_tool_calls", []),
        config=kw.get("config"),
    )[0],
    "Ragas ToolCallF1 — precision/recall for tool calls.",
    "continuous",
    task_types=["agent"],
)
