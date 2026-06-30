# CAI Eval Platform

**CAI Eval Platform** is an open-source evaluation framework for LLM endpoints and agentic workflows, built on [Arize Phoenix](https://phoenix.arize.com/) tracing.

![Eval App Landing Page](images/landing_page_eval_app.png)

## What it does

- **Benchmark LLM endpoints** — run text2sql (Spider, TPC-H) or agent tasks against any OpenAI-compatible API
- **Test Agent Studio workflows** — black-box evaluation of deployed Cloudera Agent Studio workflows via kickoff/events API
- **Score with Ragas** — AgentGoalAccuracy, ToolCallAccuracy, ToolCallF1 for agent tasks; SQL execution accuracy for text2sql
- **Trace everything** — OTEL spans per example, workflow event timelines, experiment runs linked in Phoenix

## Architecture

```
nginx (CDSW_APP_PORT)
  ├── /        →  Arize Phoenix  (tracing UI + REST)
  └── /app/    →  FastAPI eval API  (eval UI + jobs API)
```

Both components run co-located in a single CML Application or Docker container.

## Quick links

- [Quick Start](getting_started/quickstart.md)
- [Deploy on CML / CAI Workbench](getting_started/deploy_cml.md)
- [Agent Studio Workflow Evaluation](evaluation/agent_studio.md)
- [Sample Analytics Q&A Workflow](sample_workflows/analytics_qa.md)
