# datasets_extra

Prepared eval datasets that are **intentionally NOT auto-loaded** by the platform.

The app lists datasets by globbing `DATASETS_DIR/*/metadata.json` (default `datasets/`,
see `_list_datasets()` in `backend/main.py`). This `datasets_extra/` folder is a sibling of
`datasets/`, so nothing here appears in the UI until you explicitly load it. This keeps the
default bundled datasets unchanged.

## Contents

| Folder | Workflow | Input fields | Rows |
|--------|----------|--------------|------|
| `uc1_predictive_maintenance/` | UC1 Predictive Maintenance (CNC) | `machine_id`, `alert_timestamp`, `health_score` | 6 |
| `uc2_predictive_quality/` | UC2 Predictive Quality (Bike Mfg) | `machine_id`, `alert_timestamp`, `defect_rate`, `risk_level` | 6 |

Each folder holds a `metadata.json` (schema) and `validation.json` (records). Records use the
Agent Studio workflow input variables as columns plus an `expected_output` reference, and are
grounded in the seeded Iceberg demo data so a live workflow run finds matching rows.

## Evaluating a JSON output against a text ground truth

Both workflows finish by producing a **work-order JSON** (`work_order_<machine_id>.json`) plus a
short narrative, while the dataset ground truth is **text**. The two are aligned with two
complementary metrics — no naive `json == text` compare:

1. **`agent_goal_accuracy` (semantic, LLM judge).** Ragas `AgentGoalAccuracyWithReference` reads
   the agent's full trajectory (events) and the `expected_output` prose and decides whether the
   run achieved the goal. Format differences (JSON vs prose) don't matter — the judge reconciles
   them. Requires a judge LLM (`JUDGE_LLM_URL` env or the metric's config fields).
2. **`work_order_match` (structural, deterministic).** A custom metric in
   [`metrics/work_order_match.py`](metrics/work_order_match.py) that parses the predicted JSON
   from the workflow output and scores it field-by-field. The **expected** work order is embedded
   in each `expected_output` as a fenced ` ```json ` block, e.g.:

   ```json
   {"machine_id": "M02", "severity": "CRITICAL", "rul_hours": 6.5, "recommended_action": "immediate spindle bearing replacement", "priority": "high"}
   ```

   The metric extracts that block from the reference and the JSON object from the prediction, then
   compares each expected field: numbers within a relative tolerance (default 35%, so
   `rul_hours ~6.5` still matches ~6.4), strings by case-insensitive containment / word overlap,
   and lists by overlap. Score = fraction of expected fields matched (`work_order_id` and
   `created_at` are ignored by default). It returns `0.0` if no JSON can be parsed from either side.

The embedded JSON block lives inside `expected_output` on purpose: a custom metric only receives
the single reference string and the prediction, so per-record expected values must travel there.
The same string serves both metrics (the judge reads prose + JSON; the structural metric reads
only the JSON block).

### Observed workflow output shape (important)

In practice the workflow's final `crew_kickoff_completed.output` is a Markdown **fleet-status
narrative** that references the file by name (e.g. `work_order_M02.json`) but does **not** inline
the JSON — the JSON only lives in the Artifact File, whose content the black-box adapter never
fetches. Consequences:

- `agent_goal_accuracy` is unaffected: the narrative (with severity, action, parts) is captured
  from the `llm_call_completed` response and is enough for the judge.
- `work_order_match` therefore has a **per-field narrative fallback**: for each expected field it
  first checks the predicted JSON, then falls back to searching the narrative text. So a
  narrative-only run still scores partial credit for the fields it states, and a run that inlines
  the JSON scores full credit. In testing, the real M02 sample scores ~0.75 narrative-only (RUL is
  absent from the prose) vs 1.0 with the JSON inlined.
- The observed output contains `work_order_M02.json` but no `file_path` or `/tmp/`, so the adapter's
  `_looks_like_file_output` guard does **not** falsely error it.

**For full-fidelity structural scoring, have the final agent inline the work-order JSON** (fenced
` ```json `) in its Final Answer in addition to writing the Artifact File.

### Field calibration note

`priority` is intentionally **not** in the expected JSON: the workflow encodes it in a
deployment-specific way (e.g. `"P1 — Emergency"`) that will not match a literal like `"high"`.
Urgency is captured by `severity` (UC1) instead. Add `priority` back only once you know your
deployment's exact encoding. Expected `rul_hours` uses the model's approximate value and is matched
within a 35% tolerance.

### Registering `work_order_match`

The metric is not bundled, so register it once before selecting it:

- **UI:** Metrics section -> **Define Metric**, paste the contents of
  `datasets_extra/metrics/work_order_match.py` (must define `score(gold, pred, config=None)`).
- **API:**
  ```bash
  curl -X POST http://localhost:8080/api/metrics/define \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"work_order_match\",\"type\":\"continuous\",\"code\":$(python -c 'import json,sys;print(json.dumps(open("datasets_extra/metrics/work_order_match.py").read()))')}"
  ```
- **On disk (persistent):** copy the file into `DATA_DIR/custom_metrics/` and restart; it is
  auto-loaded by `load_custom_metrics()` at startup.

## Live workflows

- UC1: https://workflow-f6576176-8a34-4c8f-b947-3a84d0875b29.ml-a57ebe22-13d.qzhong-1.a465-9q4k.cloudera.site
  - Inputs: `machine_id`, `alert_timestamp`, `health_score`
- UC2: https://workflow-e08b0937-1d3e-4509-8fad-f69c509208c8.ml-a57ebe22-13d.qzhong-1.a465-9q4k.cloudera.site
  - Inputs: `machine_id`, `alert_timestamp`, `defect_rate`, `risk_level`

## How to load one (pick any)

1. **Copy into the scanned folder** — copy the dataset folder into `datasets/` and reload the app:
   ```bash
   cp -r datasets_extra/uc1_predictive_maintenance datasets/
   ```
2. **Upload via API** — POST the records to the upload endpoint:
   ```bash
   curl -X POST http://localhost:8080/api/datasets/upload-file \
     -H "Content-Type: application/json" \
     -d "{\"name\":\"uc1_predictive_maintenance\",\"task_type\":\"agent\",
          \"input_fields\":[\"machine_id\",\"alert_timestamp\",\"health_score\"],
          \"reference_fields\":[\"expected_output\"],
          \"records\":$(cat datasets_extra/uc1_predictive_maintenance/validation.json)}"
   ```
3. **Upload via UI** — paste the `validation.json` array into the **Upload Dataset** form
   (Datasets section), setting the input/reference fields to match the metadata.

## Running an eval

After loading, select the dataset, choose **Agent Studio Workflow** as the target, enter the
matching live workflow URL + API key, and use **Discover Workflow Inputs** to auto-map the
dataset columns to the workflow input variables.
