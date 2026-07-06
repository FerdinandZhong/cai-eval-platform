"""Ragas agent evaluation metrics."""

import asyncio
import os
from typing import Optional


def _get_judge_llm(config: Optional[dict] = None):
    from openai import AsyncOpenAI
    from ragas.llms.base import llm_factory

    cfg = config or {}
    url = cfg.get("url", "").strip() or os.environ.get("JUDGE_LLM_URL", "")
    token = cfg.get("token", "").strip() or os.environ.get("JUDGE_LLM_TOKEN", "dummy")
    model = cfg.get("model", "").strip() or os.environ.get("JUDGE_LLM_MODEL", "default")
    # ragas' instructor LLM defaults to max_tokens=1024, which truncates the
    # structured goal-accuracy output and raises "output is incomplete due to a
    # max_tokens length limit", scoring every example 0.0. Raise the ceiling.
    max_tokens = int(cfg.get("max_tokens") or os.environ.get("JUDGE_LLM_MAX_TOKENS", 4096))

    if not url:
        raise ValueError("Ragas metrics require judge LLM url in metric_config or JUDGE_LLM_URL env")

    base = url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"

    client = AsyncOpenAI(base_url=base, api_key=token)
    return llm_factory(model, client=client, max_tokens=max_tokens)


# #region agent log
def _dbg_summarize_user_input(user_input):
    """Runtime summary of exactly what is handed to the goal-accuracy judge."""
    try:
        msgs = user_input or []
        roles, joined, total = [], [], 0
        for m in msgs:
            role = type(m).__name__
            content = getattr(m, "content", "") or ""
            roles.append(role)
            total += len(content)
            joined.append(f"{role}: {content}")
        blob = "\n".join(joined)
        markers = ["Action Input", "Observation:", "execute_query", "tool_output", "Thought:", "get_schema"]
        return {
            "msg_count": len(msgs),
            "roles": roles,
            "total_chars": total,
            "contains_event_markers": any(mk in blob for mk in markers),
            "preview": blob[:800],
        }
    except Exception as e:  # noqa: BLE001
        return {"summarize_error": str(e)}


def _dbg_log(payload):
    try:
        import json as _json
        import time as _t
        with open(
            "/Users/zhongqishuai/Projects/cldr_projects/cai-eval-platform/.cursor/debug-a2e409.log",
            "a",
        ) as _f:
            _f.write(_json.dumps({"sessionId": "a2e409", "timestamp": int(_t.time() * 1000), **payload}) + "\n")
    except Exception:
        pass
# #endregion


def score_agent_goal_with_reference(
    user_input: list,
    reference: str,
    config: Optional[dict] = None,
) -> tuple[float, dict]:
    from ragas.metrics.collections import AgentGoalAccuracyWithReference

    async def _run():
        llm = _get_judge_llm(config)
        metric = AgentGoalAccuracyWithReference(llm=llm)
        result = await metric.ascore(user_input=user_input, reference=reference)
        return float(result.value)

    trace = {"metric": "agent_goal_accuracy_with_reference", "reference": reference}
    # #region agent log
    _summary = _dbg_summarize_user_input(user_input)
    trace["debug_judge_input"] = _summary
    trace["debug_code_version"] = "judge-maxtokens4096-v3"
    _dbg_log({
        "runId": "post-fix",
        "hypothesisId": "H4_max_tokens",
        "location": "ragas_agent.py:score_agent_goal_with_reference",
        "message": "judge input actually received",
        "data": _summary,
    })
    # #endregion
    try:
        val = asyncio.run(_run())
        return val, trace
    except Exception as e:
        trace["error"] = str(e)
        return 0.0, trace


def score_tool_call_accuracy(
    user_input: list,
    reference_tool_calls: list,
    strict_order: bool = True,
    config: Optional[dict] = None,
) -> tuple[float, dict]:
    from ragas.metrics.collections import ToolCallAccuracy

    async def _run():
        metric = ToolCallAccuracy(strict_order=strict_order)
        result = await metric.ascore(
            user_input=user_input,
            reference_tool_calls=reference_tool_calls,
        )
        return float(result.value)

    trace = {"metric": "tool_call_accuracy"}
    try:
        val = asyncio.run(_run())
        return val, trace
    except Exception as e:
        trace["error"] = str(e)
        return 0.0, trace


def score_tool_call_f1(
    user_input: list,
    reference_tool_calls: list,
    config: Optional[dict] = None,
) -> tuple[float, dict]:
    from ragas.metrics.collections import ToolCallF1

    async def _run():
        metric = ToolCallF1()
        result = await metric.ascore(
            user_input=user_input,
            reference_tool_calls=reference_tool_calls,
        )
        return float(result.value)

    trace = {"metric": "tool_call_f1"}
    try:
        val = asyncio.run(_run())
        return val, trace
    except Exception as e:
        trace["error"] = str(e)
        return 0.0, trace
