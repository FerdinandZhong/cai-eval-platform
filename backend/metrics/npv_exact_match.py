"""Deterministic NPV exact-match metric for the Lab 2 Calculator workflow.

Parses the dollar amount from the reference (gold) and the workflow's final
output (pred) and checks whether they agree within a small tolerance.

No LLM, no config, no external dependencies — fully deterministic.

Score:
    1.0  the last dollar amount in pred matches the reference within ±$0.02
    0.0  no dollar amount found in pred, or the amounts differ

The ±$0.02 tolerance covers legitimate floating-point rounding differences
(e.g. $3,766.14 vs $3,766.1411... displayed as $3,766.14 on one platform and
$3,766.15 on another with a different rounding convention).

Register via the eval UI (Define Metric) or copy to DATA_DIR/custom_metrics/
for auto-load on app start.
"""

import re

DESCRIPTION = "Exact numeric match for NPV results: extracts the dollar figure from the workflow output and compares it to the pre-computed reference value."
METRIC_TYPE = "binary"
TASK_TYPES = ["agent", "general"]

_DOLLAR_RE = re.compile(r"\$[\d,]+\.\d{2}")
_TOLERANCE = 0.02


def _parse_dollar(text: str) -> float | None:
    """Return the last dollar amount in text as a float, or None."""
    if not text:
        return None
    matches = _DOLLAR_RE.findall(text)
    if not matches:
        return None
    raw = matches[-1].replace("$", "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def score(gold: str, pred: str, config=None) -> float:
    """Return 1.0 if pred contains the correct NPV answer, else 0.0."""
    expected = _parse_dollar(gold)
    if expected is None:
        return 0.0
    actual = _parse_dollar(pred)
    if actual is None:
        return 0.0
    return 1.0 if abs(expected - actual) <= _TOLERANCE else 0.0


if __name__ == "__main__":
    cases = [
        ("canonical match",      "The NPV is $3,766.14.", "The NPV is $3,766.14.", 1.0),
        ("within tolerance",     "The NPV is $3,766.14.", "NPV ≈ $3,766.15",       1.0),
        ("wrong answer",         "The NPV is $3,766.14.", "The NPV is $3,800.00.", 0.0),
        ("no dollar in pred",    "The NPV is $3,766.14.", "Unable to compute.",    0.0),
        ("no dollar in gold",    "Result not provided.", "The NPV is $3,766.14.", 0.0),
        ("dry run (both empty)", "test",                  "test",                  0.0),
        ("last dollar wins",     "The NPV is $3,766.14.", "Step 1: $10.00. NPV = $3,766.14.", 1.0),
    ]
    all_pass = True
    for label, gold, pred, expected in cases:
        got = score(gold, pred)
        status = "PASS" if got == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"{status}  {label:<35} expected={expected}  got={got}")
    print("\nAll tests passed" if all_pass else "\nSOME TESTS FAILED")
