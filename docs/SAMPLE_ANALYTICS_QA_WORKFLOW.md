# Sample Analytics Q&A Workflow

Use this document as the **source of truth for Agent Studio UI** — copy agents and tasks from here to build a workflow that can be evaluated with the bundled **`agent_sample`** dataset in [cai-eval-platform](https://github.com/cloudera/cai-eval-platform).

**Purpose:** A minimal two-agent pipeline that answers business analytics questions in plain text. No file uploads, no external databases — answers come from a fixed mock dataset embedded in the workflow prompt.

**Eval dataset:** `datasets/agent_sample/validation.json`

| Field | Value |
|-------|-------|
| Input | `question` |
| Reference | `expected_output` |
| Metrics | `agent_goal_accuracy`, `exact_match` |

---

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│           SAMPLE ANALYTICS Q&A — TWO-AGENT PIPELINE         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Input: {question}                                          │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────────┐                                       │
│  │   AGENT 1        │  ← LLM only                            │
│  │  Question        │    Classify intent · extract entities  │
│  │  Analyst         │                                       │
│  └────────┬─────────┘                                       │
│           │                                                 │
│           ▼                                                 │
│  ┌──────────────────┐                                       │
│  │   AGENT 2        │  ← LLM only                            │
│  │  Answer          │    Lookup mock facts · compose answer  │
│  │  Composer        │                                       │
│  └──────────────────┘                                       │
│                                                             │
│  Output: plain-text answer (final crew output)              │
└─────────────────────────────────────────────────────────────┘
```

**Workflow settings**

| Setting | Value |
|---------|-------|
| Mode | Structured (not conversational) |
| Input variable | `question` |
| Output | Plain text string |

---

## Mock Data (embedded in Agent 2 prompt)

Agent 2 must answer **only** from this table. Do not invent numbers or names.

| Question pattern | Answer |
|------------------|--------|
| Total revenue for Q1 | Total Q1 revenue is $1.2M |
| Top 3 customers by order count | Top customers: Acme Corp (45), Beta Inc (38), Gamma LLC (31) |

---

## Agent 1 — Question Analyst

| Attribute | Value |
|-----------|-------|
| **Name** | Question Analyst |
| **Role** | Business Question Classifier |

**Goal:** Read `{question}` and classify what the user is asking for. Output a short structured brief for Agent 2.

**Tools:** None (LLM only)

**Task — Classify Question**

Given the user question `{question}`, determine:

1. **Intent** — one of: `revenue_summary`, `customer_ranking`, `unknown`
2. **Time period** — if mentioned (e.g. Q1, Q2); otherwise `null`
3. **Entity** — what is being ranked or summed (e.g. customers, revenue)

**Expected output (internal, passed to Agent 2):**

```json
{
  "intent": "revenue_summary",
  "time_period": "Q1",
  "entity": "revenue",
  "original_question": "<paste question here>"
}
```

---

## Agent 2 — Answer Composer

| Attribute | Value |
|-----------|-------|
| **Name** | Answer Composer |
| **Role** | Analytics Response Writer |

**Goal:** Use Agent 1's classification and the mock data table above to return a **single plain-text sentence** that directly answers `{question}`.

**Tools:** None (LLM only)

**Task — Compose Answer**

Using the classification from Agent 1 and the mock data table in this document:

- If intent is `revenue_summary` and time period is Q1 → answer exactly:  
  `Total Q1 revenue is $1.2M`
- If intent is `customer_ranking` and entity is customers → answer exactly:  
  `Top customers: Acme Corp (45), Beta Inc (38), Gamma LLC (31)`
- If intent is `unknown` → answer:  
  `I don't have data for that question in the sample dataset.`

Rules:

- Return **only** the answer sentence — no markdown, no explanation, no bullet list
- Do not add extra commentary or caveats
- Match wording from the mock data table when a row applies

**Expected final workflow output (examples):**

```
Total Q1 revenue is $1.2M
```

```
Top customers: Acme Corp (45), Beta Inc (38), Gamma LLC (31)
```

---

## Agent Studio Build Checklist

1. Create workflow **Sample Analytics Q&A**
2. Set input field: `question` (text)
3. Add Agent 1 and Agent 2 with roles/goals/tasks above
4. Chain: Task 1 → Task 2 (sequential)
5. Deploy workflow and note the endpoint URL + API key

---

## Eval Platform Setup

1. Start cai-eval-platform (Docker or local)
2. Select dataset **`agent_sample`**
3. Evaluation target: **Agent Studio Workflow**
4. Workflow URL + API key from deployment
5. Input mapping (auto-discovered or manual):

```json
{
  "question": "question"
}
```

6. Metrics: `agent_goal_accuracy`, `exact_match`
7. Run evaluation — check Phoenix for experiment runs and workflow event traces

**Local runner alternative:** use `runner/examples/demo_workflow.py` as a stub, or point `cai-eval-runner` at a script that returns the mock answers for each `question`.

---

## Sample Test Cases

| example_id | question | expected_output |
|------------|----------|-----------------|
| agent_0 | What is the total revenue for Q1? | Total Q1 revenue is $1.2M |
| agent_1 | List the top 3 customers by order count | Top customers: Acme Corp (45), Beta Inc (38), Gamma LLC (31) |

Pass criteria for smoke test: both examples score ≥ 0.9 on `exact_match` or `agent_goal_accuracy`.
