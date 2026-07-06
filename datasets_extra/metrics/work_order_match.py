"""Structured work-order JSON field-match metric (UC1 / UC2 IoT workflows).

The IoT workflows emit a work-order JSON (plus a narrative), while the dataset
ground truth is text. This metric aligns the two structurally:

  - `gold`  is the dataset `expected_output` string. The expected work order is
    embedded in it as a fenced ```json ... ``` block (the surrounding prose is
    still used by the LLM-judge metric `agent_goal_accuracy`).
  - `pred`  is the workflow's final output text. The predicted work order is the
    JSON object found in that text (fenced or raw).

In practice the workflow's final answer is often a Markdown *narrative* that
references the work-order file by name (e.g. "work_order_M02.json") without
inlining the JSON — the JSON only lives in the Artifact File, whose content the
black-box adapter does not fetch. So for each expected field this metric first
tries the predicted JSON object and, if the field is absent, falls back to
searching the whole prediction text for the expected value. That way the metric
scores correctly whether the run inlines the JSON or only emits the narrative.

Score = fraction of expected fields that match the predicted work order, with
type-aware comparison:
  - numbers  -> within relative tolerance (default 35%), so approximate model
               outputs like rul_hours ~6.5 still match;
  - strings  -> case-insensitive containment either direction, else >=50% word
               overlap (handles "immediate spindle bearing replacement" vs
               "replace spindle bearing immediately");
  - lists    -> Jaccard-style overlap of normalized items;
  - other    -> normalized equality.

Returns 0.0 when no JSON can be parsed from either side (including the dry-run
call `score("test", "test")`).

Register via the eval UI (Define Metric) or POST /api/metrics/define, or copy
this file into DATA_DIR/custom_metrics/ and restart.
"""

import json
import re

DESCRIPTION = "Structured field match between the predicted work-order JSON and the expected work order embedded in the reference."
METRIC_TYPE = "continuous"
TASK_TYPES = ["agent", "general"]

_NUMBER_TOLERANCE = 0.35
_WORD_OVERLAP_THRESHOLD = 0.5

# Predicted work orders may name a field differently than the reference.
_KEY_ALIASES = {
    "recommended_action": ["corrective_action", "action", "recommendation"],
    "corrective_action": ["recommended_action", "action", "recommendation"],
    "severity": ["risk_level", "risk", "priority"],
    "priority": ["severity", "risk_level", "risk"],
    "rul_hours": ["rul", "remaining_useful_life", "rul_h"],
    "defect_code": ["defect", "defect_id"],
    "root_cause": ["cause", "failure_mode"],
}

_STOPWORDS = {"the", "a", "an", "of", "to", "and", "for", "with", "at", "in", "on", "by"}


def _extract_json(text):
    """Return the most relevant JSON object dict from text, or None."""
    if not text or not isinstance(text, str):
        return None

    candidates = []

    # 1. Prefer fenced ```json ... ``` blocks.
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE):
        candidates.append(m.group(1))

    # 2. Fall back to balanced top-level {...} objects scanned from the text.
    if not candidates:
        candidates = _scan_balanced_objects(text)

    # Parse candidates; keep the largest object that looks like a work order.
    best = None
    best_size = -1
    for raw in candidates:
        obj = _try_load(raw)
        if isinstance(obj, dict) and len(obj) > best_size:
            best = obj
            best_size = len(obj)
    return best


def _scan_balanced_objects(text):
    objects = []
    depth = 0
    start = None
    in_str = False
    escape = False
    quote = ""
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start : i + 1])
                    start = None
    return objects


def _try_load(raw):
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Tolerate single quotes / trailing commas from loosely-formatted output.
    cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        return json.loads(cleaned)
    except Exception:
        try:
            return json.loads(cleaned.replace("'", '"'))
        except Exception:
            return None


def _norm(s):
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", _norm(s)) if w not in _STOPWORDS}


def _to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else None


def _match_value(expected, actual):
    if actual is None:
        return False

    # Numeric comparison with tolerance.
    exp_num = _to_number(expected)
    if exp_num is not None and not isinstance(expected, str):
        act_num = _to_number(actual)
        if act_num is None:
            return False
        tol = max(abs(exp_num) * _NUMBER_TOLERANCE, 1e-9)
        return abs(exp_num - act_num) <= tol

    # List / set overlap.
    if isinstance(expected, list):
        exp_items = {_norm(x) for x in expected}
        act_items = (
            {_norm(x) for x in actual}
            if isinstance(actual, list)
            else _words(actual)
        )
        if not exp_items:
            return True
        overlap = len(exp_items & act_items) / len(exp_items)
        return overlap >= _WORD_OVERLAP_THRESHOLD

    if isinstance(expected, bool):
        return bool(expected) == bool(actual)

    # String comparison: containment either direction, else word overlap.
    exp_n, act_n = _norm(expected), _norm(actual)
    if not exp_n:
        return True
    if exp_n in act_n or act_n in exp_n:
        return True
    exp_w, act_w = _words(expected), _words(actual)
    if not exp_w:
        return True
    return len(exp_w & act_w) / len(exp_w) >= _WORD_OVERLAP_THRESHOLD


def _text_has_value(expected, text):
    """Fallback: is the expected value present anywhere in the free text?"""
    if not text:
        return False

    exp_num = _to_number(expected)
    if exp_num is not None and not isinstance(expected, str):
        tol = max(abs(exp_num) * _NUMBER_TOLERANCE, 1e-9)
        for m in re.finditer(r"-?\d+(?:\.\d+)?", text):
            if abs(float(m.group()) - exp_num) <= tol:
                return True
        return False

    if isinstance(expected, list):
        if not expected:
            return True
        hits = sum(1 for item in expected if _text_has_value(item, text))
        return hits / len(expected) >= _WORD_OVERLAP_THRESHOLD

    exp_w = _words(expected)
    if not exp_w:
        return True
    text_w = _words(text)
    return len(exp_w & text_w) / len(exp_w) >= _WORD_OVERLAP_THRESHOLD


def _resolve(expected_key, pred):
    lowered = {k.lower(): v for k, v in pred.items()}
    if expected_key.lower() in lowered:
        return lowered[expected_key.lower()]
    for alias in _KEY_ALIASES.get(expected_key, []):
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    # Loose substring match on key names.
    ek = expected_key.lower()
    for k, v in lowered.items():
        if ek in k or k in ek:
            return v
    return None


def score(gold, pred, config=None):
    cfg = config or {}
    expected = _extract_json(gold)
    if not expected:
        return 0.0
    predicted = _extract_json(pred) or {}

    ignore = {k.lower() for k in cfg.get("ignore_fields", ["work_order_id", "created_at"])}
    keys = [k for k in expected if k.lower() not in ignore]
    if not keys:
        return 0.0

    pred_text = pred if isinstance(pred, str) else ""
    matched = 0
    for k in keys:
        actual = _resolve(k, predicted)
        if actual is not None and _match_value(expected[k], actual):
            matched += 1
        elif _text_has_value(expected[k], pred_text):
            matched += 1
    return matched / len(keys)


if __name__ == "__main__":
    gold_text = (
        "CRITICAL severity for M02 ... immediate bearing replacement.\n\n"
        "Expected work order (for structured scoring):\n"
        "```json\n"
        '{"machine_id":"M02","severity":"CRITICAL","rul_hours":6.5,'
        '"recommended_action":"immediate spindle bearing replacement","priority":"high"}\n'
        "```"
    )
    pred_good = (
        "Fleet update: M02 is critical.\n"
        '{"work_order_id":"WO-M02-001","machine_id":"M02","severity":"CRITICAL",'
        '"rul_hours":6.4,"recommended_action":"Replace the spindle bearing immediately",'
        '"priority":"HIGH","created_at":"2025-06-24T14:35:00Z"}'
    )
    pred_bad = '{"machine_id":"M02","severity":"LOW","rul_hours":120,"recommended_action":"monitor"}'
    print("good:", score(gold_text, pred_good))
    print("bad :", score(gold_text, pred_bad))
    print("dry :", score("test", "test"))
