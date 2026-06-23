"""Agent Studio workflow backend client."""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from targets.base import EvalContext, TargetResult, TargetSchema

TERMINAL_EVENTS = {"crew_kickoff_completed", "crew_kickoff_failed"}
POLL_INTERVAL_SEC = 5


@dataclass
class AgentStudioConfig:
    workflow_url: str
    api_key: str = ""
    poll_interval_sec: float = POLL_INTERVAL_SEC
    workflow_phoenix_url: str = ""


class AgentStudioClient:
    def __init__(self, config: AgentStudioConfig):
        self.base = config.workflow_url.rstrip("/")
        self.api_key = config.api_key
        self.poll_interval = config.poll_interval_sec
        self.workflow_phoenix_url = config.workflow_phoenix_url

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        params: str = "",
    ) -> dict:
        url = f"{self.base}{path}"
        if params:
            url = f"{url}?{params}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Workflow {method} {path} → {e.code}: {e.read().decode()}") from e

    def fetch_workflow(self) -> dict:
        return self._request("GET", "/api/workflow")

    def create_session(self) -> dict:
        return self._request("POST", "/api/workflow/createSession", {})

    def kickoff(self, payload: dict) -> dict:
        return self._request("POST", "/api/workflow/kickoff", payload)

    def get_events(self, trace_id: str) -> list:
        resp = self._request("GET", "/api/workflow/events", params=f"trace_id={trace_id}")
        return resp.get("events", [])


class AgentStudioWorkflowTarget:
    def __init__(self, config: AgentStudioConfig):
        self.config = config
        self.client = AgentStudioClient(config)
        self._session_id: Optional[str] = None
        self._schema: Optional[TargetSchema] = None

    def discover(self) -> TargetSchema:
        wf = self.client.fetch_workflow()
        input_fields: list[str] = []
        for task in wf.get("tasks", []):
            for inp in task.get("inputs", []):
                if inp not in input_fields:
                    input_fields.append(inp)
        is_conv = wf.get("workflow", {}).get("is_conversational", False)
        if is_conv and "user_input" not in input_fields:
            input_fields = ["user_input"]

        self._schema = TargetSchema(
            target_type="agent_studio",
            input_fields=input_fields or ["question"],
            is_conversational=is_conv,
            description=wf.get("workflow", {}).get("description", ""),
        )
        return self._schema

    def ensure_session(self) -> str:
        if not self._session_id:
            session = self.client.create_session()
            self._session_id = session["session_id"]
        return self._session_id

    def invoke(self, inputs: dict, ctx: EvalContext) -> TargetResult:
        start = time.time()
        start_iso = _iso_now()
        result = TargetResult(output_text="", start_time=start_iso)

        try:
            if self._schema is None:
                self.discover()

            mapped = _map_inputs(inputs, ctx.input_mapping)
            session_id = ctx.session_id or self.ensure_session()

            if self._schema and self._schema.is_conversational:
                kickoff_payload = {
                    "user_input": mapped.get("user_input") or mapped.get("question", ""),
                    "session_id": session_id,
                }
            else:
                kickoff_payload = {"inputs": mapped, "session_id": session_id}

            kickoff = self.client.kickoff(kickoff_payload)
            trace_id = kickoff.get("trace_id")
            result.trace_id = trace_id

            events, terminal = self._poll_until_terminal(trace_id, ctx.timeout)
            result.events = events
            result.raw = {"kickoff": kickoff, "events": events}

            if terminal:
                if terminal.get("type") == "crew_kickoff_failed":
                    result.error = terminal.get("error") or "Workflow failed"
                else:
                    output = terminal.get("output") or terminal.get("result") or ""
                    if _looks_like_file_output(output):
                        result.error = (
                            "Workflow returned a file output; v1 supports plain text only"
                        )
                        result.output_text = str(output)
                    else:
                        result.output_text = str(output).strip()
            else:
                result.error = f"Workflow timed out after {ctx.timeout}s"

        except Exception as e:
            result.error = str(e)

        result.latency_ms = (time.time() - start) * 1000
        result.end_time = _iso_now()
        return result

    def _poll_until_terminal(self, trace_id: str, timeout: int) -> tuple[list, Optional[dict]]:
        deadline = time.time() + timeout
        all_events: list = []
        seen = 0

        while time.time() < deadline:
            batch = self.client.get_events(trace_id)
            if len(batch) > seen:
                all_events.extend(batch[seen:])
                seen = len(batch)

            for event in reversed(all_events):
                if event.get("type") in TERMINAL_EVENTS:
                    return all_events, event

            time.sleep(self.config.poll_interval_sec)

        return all_events, None


def _map_inputs(inputs: dict, mapping: dict[str, str]) -> dict:
    if not mapping:
        return dict(inputs)
    out = {}
    for src, dst in mapping.items():
        if src in inputs:
            out[dst] = inputs[src]
    for k, v in inputs.items():
        out.setdefault(k, v)
    return out


def _looks_like_file_output(output: str) -> bool:
    if not output:
        return False
    lower = output.lower()
    markers = [".pdf", ".csv", ".xlsx", "file_path", "/tmp/", "download?file_path"]
    return any(m in lower for m in markers)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
