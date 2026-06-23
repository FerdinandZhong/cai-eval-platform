"""OpenAI-compatible LLM endpoint target."""

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from targets.base import EvalContext, TargetResult, TargetSchema


def extract_sql(text: str, strip_thinking: bool = False) -> str:
    if strip_thinking:
        text = re.sub(
            r"<think>.*?</think>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
    match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip().rstrip(";")


@dataclass
class LLMEndpointConfig:
    endpoint_url: str
    api_key: str = ""
    model_name: str = "default"
    max_tokens: int = 512
    temperature: float = 0.0
    timeout: int = 60
    is_reasoning: bool = False
    system_prompt: str = ""
    output_mode: str = "text"  # text | sql


class LLMEndpointTarget:
    def __init__(self, config: LLMEndpointConfig):
        self.config = config

    def discover(self) -> TargetSchema:
        return TargetSchema(
            target_type="llm_endpoint",
            input_fields=["question"],
            description="OpenAI-compatible chat completions endpoint",
        )

    def invoke(self, inputs: dict, ctx: EvalContext) -> TargetResult:
        import openai

        question = inputs.get("question", "")
        schema = inputs.get("schema", ctx.extra.get("schema", ""))
        cfg = self.config

        base = cfg.endpoint_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"

        if cfg.system_prompt:
            system_prompt = cfg.system_prompt.replace("{schema}", schema)
        else:
            system_prompt = (
                "You are a helpful assistant. Answer the user's question concisely."
            )

        start = time.time()
        start_iso = _iso_now()
        result = TargetResult(output_text="", start_time=start_iso)

        try:
            client = openai.OpenAI(
                base_url=base,
                api_key=cfg.api_key or os.environ.get("OPENAI_API_KEY", "dummy"),
            )
            response = client.chat.completions.create(
                model=cfg.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                timeout=cfg.timeout,
            )
            raw = response.choices[0].message.content.strip()
            if cfg.output_mode == "sql":
                result.output_text = extract_sql(raw, strip_thinking=cfg.is_reasoning)
            else:
                result.output_text = raw
            result.raw = {"response": raw}
        except Exception as e:
            result.error = str(e)

        result.latency_ms = (time.time() - start) * 1000
        result.end_time = _iso_now()
        return result


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
