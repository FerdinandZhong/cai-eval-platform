"""Target adapter protocol for evaluation backends."""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class TargetSchema:
    target_type: str
    input_fields: list[str]
    is_conversational: bool = False
    description: str = ""


@dataclass
class EvalContext:
    job_id: str
    example_id: str
    timeout: int = 120
    session_id: Optional[str] = None
    input_mapping: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetResult:
    output_text: str
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    events: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class EvalTarget(Protocol):
    def discover(self) -> TargetSchema: ...

    def invoke(self, inputs: dict, ctx: EvalContext) -> TargetResult: ...
