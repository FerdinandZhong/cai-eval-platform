#!/usr/bin/env python3
"""
Download and transform the Safety & Security dataset subset into
cai-eval-platform format (single-LLM evaluation).

Builds four datasets under datasets/<id>/{metadata.json,validation.json}:

    advbench        walledai/AdvBench            harmful behaviors → expect refusal
    do_not_answer   LibrAI/do-not-answer         prompts to decline → expect refusal
    jailbreakbench  JailbreakBench/JBB-Behaviors harmful + benign control
    truthfulqa      truthfulqa/truthful_qa       truthfulness / hallucination

Each record is {example_id, question, reference}. `reference` carries the
expected disposition ("refuse"/"comply") for the safety datasets, and a
formatted correct/incorrect answer key for TruthfulQA — consumed by the
safety_judge / truthfulness_judge metrics respectively.

metadata.json is written only when missing (so UI/manual edits persist), but
its `size` is always refreshed to match the generated validation.json.

Requires: pip install datasets   (already in the eval venv)
Usage:    python scripts/download_safety_datasets.py
"""

import csv
import io
import json
import pathlib
import sys
import urllib.request

DATASETS_DIR = pathlib.Path(__file__).parent.parent / "datasets"

CATEGORY = "Safety & Security"

# Default metadata written when a dataset folder has no metadata.json yet.
METADATA = {
    "advbench": {
        "id": "advbench",
        "name": "AdvBench (Harmful Behaviors)",
        "description": "Harmful-behavior instructions from AdvBench (Zou et al., "
        "arXiv:2307.15043). Single-LLM safety test — a safe model should refuse "
        "every prompt. Scored with safety_judge (refusal rate).",
        "category": CATEGORY,
        "task_type": "safety",
        "input_fields": ["question"],
        "reference_fields": ["reference"],
        "default_metrics": ["safety_judge"],
        "system_prompt": "You are a helpful assistant.",
        "source": "https://github.com/llm-attacks/llm-attacks",
        "license": "MIT",
    },
    "do_not_answer": {
        "id": "do_not_answer",
        "name": "Do-Not-Answer",
        "description": "Prompts spanning risk areas that a responsible model should "
        "decline (Wang et al., LibrAI, arXiv:2308.13387). Single-LLM safety test — "
        "expected behavior is refusal. Scored with safety_judge.",
        "category": CATEGORY,
        "task_type": "safety",
        "input_fields": ["question"],
        "reference_fields": ["reference"],
        "default_metrics": ["safety_judge"],
        "system_prompt": "You are a helpful assistant.",
        "source": "https://github.com/Libr-AI/do-not-answer",
        "license": "Apache-2.0",
    },
    "jailbreakbench": {
        "id": "jailbreakbench",
        "name": "JailbreakBench (JBB-Behaviors)",
        "description": "100 harmful + 100 benign behaviors (Chao et al., "
        "arXiv:2404.01318). The benign control detects over-refusal. Harmful → "
        "expect refusal; benign → expect helpful compliance. Scored with safety_judge.",
        "category": CATEGORY,
        "task_type": "safety",
        "input_fields": ["question"],
        "reference_fields": ["reference"],
        "default_metrics": ["safety_judge"],
        "system_prompt": "You are a helpful assistant.",
        "source": "https://github.com/JailbreakBench/jailbreakbench",
        "license": "MIT",
    },
    "truthfulqa": {
        "id": "truthfulqa",
        "name": "TruthfulQA",
        "description": "Questions where models tend to echo common human "
        "misconceptions (Lin et al., arXiv:2109.07958). Single-LLM hallucination / "
        "truthfulness test. Scored with truthfulness_judge against the known "
        "correct/incorrect answers.",
        "category": CATEGORY,
        "task_type": "safety",
        "input_fields": ["question"],
        "reference_fields": ["reference"],
        "default_metrics": ["truthfulness_judge"],
        "system_prompt": "Answer the following question as truthfully and accurately "
        "as possible. If you are not sure, say so rather than guessing.",
        "source": "https://github.com/sylinrl/TruthfulQA",
        "license": "Apache-2.0",
    },
}


def _load(*args, **kwargs):
    from datasets import load_dataset
    return load_dataset(*args, **kwargs)


# Canonical AdvBench harmful behaviors (ungated, MIT) — the walledai/AdvBench
# HF mirror is gated, so pull the original CSV from the llm-attacks repo.
_ADVBENCH_CSV = (
    "https://raw.githubusercontent.com/llm-attacks/llm-attacks/main/"
    "data/advbench/harmful_behaviors.csv"
)


def build_advbench() -> list[dict]:
    with urllib.request.urlopen(_ADVBENCH_CSV, timeout=120) as resp:
        text = resp.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return [
        {"example_id": f"advbench_{i}", "question": row["goal"], "reference": "refuse"}
        for i, row in enumerate(reader)
        if row.get("goal")
    ]


def build_do_not_answer() -> list[dict]:
    ds = _load("LibrAI/do-not-answer", split="train")
    return [
        {"example_id": f"dna_{i}", "question": row["question"], "reference": "refuse"}
        for i, row in enumerate(ds)
    ]


def build_jailbreakbench() -> list[dict]:
    records: list[dict] = []
    for split, disposition in (("harmful", "refuse"), ("benign", "comply")):
        ds = _load("JailbreakBench/JBB-Behaviors", "behaviors", split=split)
        for i, row in enumerate(ds):
            records.append({
                "example_id": f"jbb_{split}_{i}",
                "question": row["Goal"],
                "reference": disposition,
            })
    return records


def _format_answer_key(row: dict) -> str:
    correct = row.get("correct_answers") or []
    incorrect = row.get("incorrect_answers") or []
    best = row.get("best_answer", "")
    lines = [f"Best answer: {best}"]
    if correct:
        lines.append("Known correct answers: " + " | ".join(correct))
    if incorrect:
        lines.append("Known incorrect (false) answers: " + " | ".join(incorrect))
    return "\n".join(lines)


def build_truthfulqa() -> list[dict]:
    ds = _load("truthfulqa/truthful_qa", "generation", split="validation")
    return [
        {
            "example_id": f"truthfulqa_{i}",
            "question": row["question"],
            "reference": _format_answer_key(row),
        }
        for i, row in enumerate(ds)
    ]


BUILDERS = {
    "advbench": build_advbench,
    "do_not_answer": build_do_not_answer,
    "jailbreakbench": build_jailbreakbench,
    "truthfulqa": build_truthfulqa,
}


def _write_dataset(ds_id: str, records: list[dict]) -> None:
    out_dir = DATASETS_DIR / ds_id
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "validation.json").write_text(json.dumps(records, indent=2))

    meta_file = out_dir / "metadata.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else dict(METADATA[ds_id])
    meta["size"] = len(records)
    meta_file.write_text(json.dumps(meta, indent=2))

    print(f"  {ds_id}: {len(records)} examples → {out_dir}", flush=True)


def main() -> None:
    try:
        import datasets  # noqa: F401
    except ImportError:
        print("ERROR: 'datasets' package not installed. Install it in the eval venv.",
              file=sys.stderr)
        sys.exit(1)

    failed = []
    for ds_id, builder in BUILDERS.items():
        print(f"Building {ds_id} ...", flush=True)
        try:
            records = builder()
            if not records:
                raise RuntimeError("no records produced")
            _write_dataset(ds_id, records)
        except Exception as e:
            print(f"  ERROR building {ds_id}: {e}", file=sys.stderr, flush=True)
            failed.append(ds_id)

    if failed:
        print(f"\nCompleted with failures: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)
    print("\nAll safety datasets built.", flush=True)


if __name__ == "__main__":
    main()
