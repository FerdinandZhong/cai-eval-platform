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

    if not url:
        raise ValueError("Ragas metrics require judge LLM url in metric_config or JUDGE_LLM_URL env")

    base = url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"

    client = AsyncOpenAI(base_url=base, api_key=token)
    return llm_factory(model, client=client)


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
