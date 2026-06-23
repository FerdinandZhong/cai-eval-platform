#!/usr/bin/env python3
"""Example local workflow for cai-eval-runner."""

def run(inputs: dict) -> dict:
    question = inputs.get("question", "")
    # Replace with your CrewAI/LangGraph workflow
    output = f"Echo: {question}"
    return {
        "output": output,
        "events": [
            {"type": "agent_execution_completed", "agent_name": "demo", "output": output},
        ],
    }
