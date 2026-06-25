#!/usr/bin/env python3
"""
Download and transform τ-bench retail tasks to cai-eval-platform format.

Source: sierra-research/tau-bench (GitHub) — tasks_test.py parsed with AST.
No package install required; works with stdlib only.

Usage:
    python scripts/download_tau_bench.py
"""

import ast
import io
import json
import pathlib
import sys
import urllib.request
import zipfile

OUTPUT = pathlib.Path(__file__).parent.parent / "datasets" / "tau_bench_retail"
OUTPUT.mkdir(parents=True, exist_ok=True)

GITHUB_URL = "https://github.com/sierra-research/tau-bench/archive/refs/heads/main.zip"

TASK_FILES = [
    "tau-bench-main/tau_bench/envs/retail/tasks_test.py",
    "tau-bench-main/tau_bench/envs/retail/tasks_train.py",
    "tau-bench-main/tau_bench/envs/retail/tasks_dev.py",
]


def _parse_tasks(src: str) -> list[dict]:
    """
    Parse Task(...) and Action(...) calls from Python source with ast.
    No imports of the tau_bench package are needed.
    """
    tree = ast.parse(src)
    tasks = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Task"):
            continue

        kw: dict = {}
        for k in node.keywords:
            try:
                kw[k.arg] = ast.literal_eval(k.value)
            except Exception:
                pass

        if "instruction" not in kw:
            continue

        actions = []
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "Action"):
                continue
            akw: dict = {}
            for ak in sub.keywords:
                try:
                    akw[ak.arg] = ast.literal_eval(ak.value)
                except Exception:
                    pass
            if "name" in akw:
                actions.append({
                    "name": akw["name"],
                    "args": akw.get("kwargs", {}),
                })

        outputs = kw.get("outputs", [])
        reference = outputs[0] if outputs else ""

        tasks.append({
            "instruction": kw["instruction"],
            "reference": reference,
            "actions": actions,
        })

    return tasks


def _from_github() -> list[dict]:
    print(f"Downloading tau-bench from GitHub: {GITHUB_URL}", flush=True)
    with urllib.request.urlopen(GITHUB_URL, timeout=180) as resp:
        raw = resp.read()
    print(f"  Downloaded {len(raw) // 1024} KB", flush=True)

    all_tasks: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        available = set(zf.namelist())
        for member in TASK_FILES:
            if member not in available:
                print(f"  Skipping {member} (not in zip)", flush=True)
                continue
            with zf.open(member) as f:
                src = f.read().decode()
            parsed = _parse_tasks(src)
            print(f"  {member.split('/')[-1]}: {len(parsed)} tasks", flush=True)
            all_tasks.extend(parsed)

    return all_tasks


def _to_records(tasks: list[dict]) -> list[dict]:
    return [
        {
            "example_id": f"tau_retail_{i}",
            "question": t["instruction"],
            "reference": t["reference"],
            "reference_tool_calls": t["actions"],
        }
        for i, t in enumerate(tasks)
    ]


def main() -> None:
    try:
        raw_tasks = _from_github()
    except Exception as e:
        print(f"ERROR: Download failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not raw_tasks:
        print("ERROR: No tasks found.", file=sys.stderr)
        sys.exit(1)

    records = _to_records(raw_tasks)
    out = OUTPUT / "validation.json"
    out.write_text(json.dumps(records, indent=2))
    print(f"\nSaved {len(records)} examples → {out}", flush=True)


if __name__ == "__main__":
    main()
