"""Map Agent Studio workflow events to Ragas message format."""

from ragas.messages import AIMessage, HumanMessage, ToolCall, ToolMessage


def events_to_user_input(events: list[dict], initial_question: str = "") -> list:
    """Build Ragas user_input message list from workflow events."""
    messages = []
    if initial_question:
        messages.append(HumanMessage(content=initial_question))

    for event in events:
        etype = event.get("type", "")

        if etype == "llm_call_completed" and event.get("response"):
            tool_calls = _extract_tool_calls(event)
            messages.append(
                AIMessage(content=str(event["response"]), tool_calls=tool_calls or None)
            )
        elif etype == "tool_usage_finished":
            output = event.get("tool_output") or event.get("result") or ""
            messages.append(ToolMessage(content=str(output)))
        elif etype == "agent_execution_completed" and event.get("output"):
            messages.append(AIMessage(content=str(event["output"])))

    return messages


def extract_reference_tool_calls(record: dict) -> list:
    """Parse reference_tool_calls from dataset record."""
    raw = record.get("reference_tool_calls") or record.get("expected_tool_calls") or []
    if not raw:
        return []
    calls = []
    for item in raw:
        if isinstance(item, dict):
            calls.append(
                ToolCall(name=item.get("name", ""), args=item.get("args") or {})
            )
    return calls


def _extract_tool_calls(event: dict) -> list:
    calls = []
    tool_name = event.get("tool_name")
    if tool_name:
        args = event.get("tool_input") or event.get("tool_args") or {}
        if isinstance(args, str):
            try:
                import json

                args = json.loads(args)
            except Exception:
                args = {"raw": args}
        calls.append(ToolCall(name=tool_name, args=args if isinstance(args, dict) else {}))
    return calls
