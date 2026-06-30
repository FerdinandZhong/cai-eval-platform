#!/usr/bin/env python3
"""
Download the Spider Text-to-SQL validation split and write it to
datasets/spider/validation.json in cai-eval-platform format.

Requires: pip install datasets  (already in the eval venv)
Usage:    python scripts/download_spider.py
"""

import json
import pathlib
import sys

OUTPUT = pathlib.Path(__file__).parent.parent / "datasets" / "spider"
OUTPUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    out = OUTPUT / "validation.json"
    if out.exists():
        try:
            existing = json.loads(out.read_text())
            if len(existing) > 0:
                print(f"Spider already downloaded ({len(existing)} examples) — skipping", flush=True)
                return
        except Exception:
            pass

    print("Downloading Spider validation split from HuggingFace (xlangai/spider)...", flush=True)
    try:
        from datasets import load_dataset
    except ImportError:
        print("ERROR: 'datasets' package not installed. Run setup_environment.py first.", file=sys.stderr)
        sys.exit(1)

    try:
        ds = load_dataset("xlangai/spider", split="validation", trust_remote_code=True)
    except Exception as e:
        print(f"ERROR: Failed to download Spider: {e}", file=sys.stderr)
        sys.exit(1)

    records = [
        {
            "example_id": f"spider_{i}",
            "question": r["question"],
            "query": r["query"],
            "db_id": r["db_id"],
        }
        for i, r in enumerate(ds)
    ]

    out.write_text(json.dumps(records, indent=2))
    print(f"Saved {len(records)} examples → {out}", flush=True)


if __name__ == "__main__":
    main()
