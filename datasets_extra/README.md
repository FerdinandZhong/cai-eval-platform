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
