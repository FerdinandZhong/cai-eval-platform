"""Graded LLM-as-judge for agent outcome matching.

A more tolerant alternative to ragas' binary AgentGoalAccuracyWithReference,
which does a strict "same/different" comparison and often rejects correct
outputs that are worded differently from the reference.

This metric asks the judge to grade the workflow's final output against the
expected outcome on the dimensions that actually matter for these workflows —
the classification/severity and the recommended action — and return a graded
score:

    1.0  same severity/classification AND a compatible recommended action
    0.5  right classification but wrong/missing action (or vice versa)
    0.0  wrong classification and wrong action

Config (metric_config["agent_outcome_judge"], with JUDGE_LLM_* env fallback):
    url    Base URL of the judge endpoint
    token  API key / bearer token (default: "dummy")
    model  Model name (default: "default")
"""

import os
import re
from typing import Optional

_PROMPT = """\
You are evaluating whether an industrial-maintenance agent workflow produced the \
correct decision.

Expected outcome (reference):
{reference}

Workflow final output:
{prediction}

Judge ONLY these two dimensions, ignoring wording, formatting, extra detail, and \
numeric precision:
1. Classification/severity: does the output reach the same severity / risk \
   classification as the reference (e.g. CRITICAL / HIGH / MEDIUM / LOW / INVESTIGATE)?
2. Recommended action: is the recommended action compatible with the reference \
   (same intervention or an equivalent one)?

Scoring:
- Reply 1.0 if BOTH the classification and the action match.
- Reply 0.5 if exactly ONE matches.
- Reply 0.0 if NEITHER matches.

Respond with ONLY the number (1.0, 0.5, or 0.0). No other text."""


def score(gold: str, pred: str, config: Optional[dict] = None) -> float:
    return score_detailed(gold, pred, config)[0]


def score_detailed(gold: str, pred: str, config: Optional[dict] = None) -> tuple:
    cfg = config or {}
    url = (cfg.get("url", "") or os.environ.get("JUDGE_LLM_URL", "")).strip()
    token = (cfg.get("token", "") or os.environ.get("JUDGE_LLM_TOKEN", "dummy")).strip() or "dummy"
    model = (cfg.get("model", "") or os.environ.get("JUDGE_LLM_MODEL", "default")).strip() or "default"

    trace = {"judge_model": model, "judge_prompt": None, "judge_response": "", "judge_error": None}

    if not url:
        trace["judge_error"] = "agent_outcome_judge requires a judge LLM url (config or JUDGE_LLM_URL)"
        return 0.0, trace
    if not (gold or "").strip() or not (pred or "").strip():
        return 0.0, trace

    prompt = _PROMPT.format(reference=gold, prediction=pred)
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
