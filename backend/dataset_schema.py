"""Generic dataset schema helpers."""

import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT_FIELDS = ["question"]
DEFAULT_REFERENCE_FIELDS = ["query"]
DEFAULT_OUTPUT_FIELD = "expected_output"


def load_metadata(datasets_dir: Path, dataset_id: str) -> dict:
    meta_file = datasets_dir / dataset_id / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}


def load_records(datasets_dir: Path, dataset_id: str) -> list[dict]:
    val_file = datasets_dir / dataset_id / "validation.json"
    if not val_file.exists():
        raise FileNotFoundError(f"Validation file not found: {val_file}")
    records = json.loads(val_file.read_text())
    for i, rec in enumerate(records):
        rec.setdefault("example_id", rec.get("id") or f"{dataset_id}_{i}")
    return records


def get_input_fields(meta: dict) -> list[str]:
    return meta.get("input_fields") or DEFAULT_INPUT_FIELDS


def get_reference_fields(meta: dict) -> list[str]:
    refs = meta.get("reference_fields")
    if refs:
        return refs
    task = meta.get("task_type", "text2sql")
    if task == "agent":
        return [DEFAULT_OUTPUT_FIELD, "expected_output", "reference"]
    return DEFAULT_REFERENCE_FIELDS


def extract_inputs(record: dict, input_fields: list[str]) -> dict:
    return {f: record.get(f, "") for f in input_fields}


def extract_reference(record: dict, reference_fields: list[str]) -> str:
    for field in reference_fields:
        val = record.get(field)
        if val is not None and str(val).strip():
            return str(val)
    return ""


def records_to_phoenix_arrays(records: list[dict], meta: dict) -> tuple[list, list, list]:
    input_fields = get_input_fields(meta)
    reference_fields = get_reference_fields(meta)

    inputs = []
    outputs = []
    metadata = []

    for rec in records:
        inputs.append(extract_inputs(rec, input_fields))
        ref_val = extract_reference(rec, reference_fields)
        out_key = reference_fields[0] if reference_fields else "reference"
        outputs.append({out_key: ref_val})
        meta_row = {
            k: v
            for k, v in rec.items()
            if k not in (*input_fields, *reference_fields)
        }
        meta_row["example_id"] = rec.get("example_id", "")
        metadata.append(meta_row)

    return inputs, outputs, metadata


def build_example_id_map(records: list[dict]) -> dict[str, str]:
    """Map example_id -> record index for Phoenix matching."""
    return {str(r.get("example_id", i)): str(i) for i, r in enumerate(records)}
