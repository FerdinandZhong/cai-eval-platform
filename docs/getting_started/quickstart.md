# Quick Start

## Docker (fastest)

```bash
docker run -p 8080:8080 -v cai-eval-data:/data \
  ferdinandzhong/cai-eval-platform:latest
```

| URL | Service |
|-----|---------|
| http://localhost:8080/app/ | Eval UI |
| http://localhost:8080/ | Arize Phoenix |

## Build from source

```bash
git clone https://github.com/FerdinandZhong/cai-eval-platform.git
cd cai-eval-platform
docker build -f docker/Dockerfile -t cai-eval-platform .
docker run -p 8080:8080 -v cai-eval-data:/data cai-eval-platform
```

## Local development

```bash
cd backend
pip install -e ..
DATASETS_DIR=../datasets DATA_DIR=/tmp/cai-eval-data \
  uvicorn main:app --reload --port 9000
```

Run Phoenix separately:

```bash
phoenix serve --port 6006
```

## First evaluation (end to end)

This walks a "client brings up a model" scenario all the way to concrete results.
Not sure which evaluation fits your model? See [Choosing the right evaluation](../evaluation/choosing.md).

1. **Open the app** — `http://localhost:8080/app/`.

    ![Eval app landing page](../images/landing_page_eval_app.png)

2. **Pick the target type** — an LLM endpoint (text2sql / safety) or an Agent Studio workflow.

    ![Select eval mode](../images/select_eval_mode_llm_or_agent.png)

3. **Select a dataset and metrics.** For a model endpoint, choose e.g. `spider` with
   `execution_accuracy`; for a workflow, choose `agent_sample` and click
   **Discover Workflow Inputs** to auto-map dataset columns, then pick Ragas metrics.

    ![Detailed eval configuration](../images/detailed_configuration_of_single_llm_evaluation.png)

4. **Enter the endpoint / workflow URL + API key** (and a judge LLM URL for judge-based metrics), then **Run Evaluation**.

5. **Read the results.** Each run produces per-example scores and an aggregate. The run
   detail shows every example's input, output, and score.

    ![Experiment results](../images/experiments_results.png)

6. **Inspect traces in Phoenix** at `http://localhost:8080/`. Every example is an
   `eval.example` OTEL span; the run lives in a `{dataset}_{model}` project so different
   models are directly comparable.

    ![Trace detail](../images/eval_tracing.png)

To compare a second model, re-run the same dataset + metrics with a different endpoint — the
new run appears as a separate Phoenix project alongside the first.
