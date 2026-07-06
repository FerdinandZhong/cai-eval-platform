"""Graded LLM-as-judge for agent outcome matching.

A more tolerant alternative to ragas' binary AgentGoalAccuracyWithReference,
which does a strict "same/different" comparison and often rejects correct
outputs that are worded differently from the reference.

This metric asks the judge to grade the workflow's final output against the
expected outcome and return a graded score (1.0 / 0.5 / 0.0), tolerant of
wording, formatting, extra detail, and numeric precision.

It is workflow-agnostic: the dimensions that define a "match" are configurable
so the same metric works for maintenance, quality, customer-service, RAG, or
any other Agent Studio workflow.

Config (metric_config["agent_outcome_judge"], with JUDGE_LLM_* env fallback):
    url         Base URL of the judge endpoint (or JUDGE_LLM_URL)
    token       API key / bearer token (or JUDGE_LLM_TOKEN, default "dummy")
    model       Model name (or JUDGE_LLM_MODEL, default "default")
    dimensions  Optional list[str] (or newline/semicolon string) of the
                dimensions to judge. When omitted, a single generic dimension
                ("the overall outcome matches the reference") is used.
"""

import os
import re
from typing import Optional

_GENERIC_DIMENSION = "Overall outcome: does the output achieve the same outcome as the reference?"

_PROMPT = """\
You are evaluating whether an AI agent workflow produced the correct outcome.

Expected outcome (reference):
{reference}

Workflow final output:
{prediction}

Judge the output against the reference on the following dimension(s), ignoring \
wording, formatting, extra detail, and numeric precision:
{dimensions}

Scoring:
- Reply 1.0 if ALL dimensions match.
- Reply 0.5 if SOME (but not all) dimensions match.
- Reply 0.0 if NONE match.
(If there is only one dimension, reply 1.0 if it matches, else 0.0.)

Respond with ONLY the number (1.0, 0.5, or 0.0). No other text."""


def _resolve_dimensions(cfg: dict) -> list:
    raw = cfg.get("dimensions")
    if not raw:
        return [_GENERIC_DIMENSION]
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[\n;]+", raw) if p.strip()]
        return parts or [_GENERIC_DIMENSION]
    if isinstance(raw, list):
        parts = [str(p).strip() for p in raw if str(p).strip()]
        return parts or [_GENERIC_DIMENSION]
    return [_GENERIC_DIMENSION]


def score(gold: str, pred: str, config: Optional[dict] = None) -> float:
    return score_detailed(gold, pred, config)[0]


def score_detailed(gold: str, pred: str, config: Optional[dict] = None) -> tuple:
    cfg = config or {}
    url = (cfg.get("url", "") or os.environ.get("JUDGE_LLM_URL", "")).strip()
    token = (cfg.get("token", "") or os.environ.get("JUDGE_LLM_TOKEN", "dummy")).strip() or "dummy"
    model = (cfg.get("model", "") or os.environ.get("JUDGE_LLM_MODEL", "default")).strip() or "default"
    dimensions = _resolve_dimensions(cfg)

    trace = {"judge_model": model, "judge_prompt": None, "judge_response": "",
             "judge_error": None, "dimensions": dimensions}

    if not url:
        trace["judge_error"] = "agent_outcome_judge requires a judge LLM url (config or JUDGE_LLM_URL)"
        return 0.0, trace
    if not (gold or "").strip() or not (pred or "").strip():
        return 0.0, trace

    dims_text = "\n".join(f"{i}. {d}" for i, d in enumerate(dimensions, 1))
    prompt = _PROMPT.format(reference=gold, prediction=pred, dimensions=dims_text)
    trace["judge_prompt"] = prompt

    try:
        import openai

        base = url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        client = openai.OpenAI(base_url=base, api_key=token)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=16,
            timeout=30,
        )
        answer = (resp.choices[0].message.content or "").strip()
        trace["judge_response"] = answer
        m = re.search(r"(1(?:\.0)?|0?\.5|0(?:\.0)?)", answer)
        if not m:
            return 0.0, trace
        val = float(m.group(1))
        return (max(0.0, min(1.0, val)), trace)
    except Exception as e:  # noqa: BLE001
        trace["judge_error"] = str(e)
        return 0.0, trace
