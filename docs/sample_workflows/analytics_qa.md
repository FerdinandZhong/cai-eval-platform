# Sample Analytics Q&A Workflow

A minimal two-agent pipeline that answers business analytics questions in plain text. Use this as a smoke test for the eval platform.

**Eval dataset:** `agent_sample` (2 examples)

| Field | Value |
|-------|-------|
| Input | `question` |
| Reference | `expected_output` |
| Metrics | `agent_goal_accuracy`, `exact_match` |

## Workflow overview

```
Input: {question}
       │
       ▼
┌──────────────────┐
│   Agent 1        │  LLM only
│  Question        │  Classify intent · extract entities
│  Analyst         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Agent 2        │  LLM only
│  Answer          │  Lookup mock facts · compose answer
│  Composer        │
└──────────────────┘

Output: plain-text answer
```

**Workflow settings:** Structured (not conversational) · input variable `question`

## Agent 1 — Question Analyst

| Attribute | Value |
|-----------|-------|
| **Role** | Business Question Classifier |
| **Backstory** | You are a senior business analyst with 10 years of experience interpreting analytics requests from executives. You are precise and structured, always outputting clean JSON so downstream agents can work without ambiguity. You never answer the question yourself — your job is classification only. |

**Goal:** Read `{question}` and output a JSON brief for Agent 2.

**Task — Classify Question**

```json
{
  "intent": "revenue_summary",
  "time_period": "Q1",
  "entity": "revenue",
  "original_question": "<paste question here>"
}
```

## Agent 2 — Answer Composer

| Attribute | Value |
|-----------|-------|
| **Role** | Analytics Response Writer |
| **Backstory** | You are a concise executive communications specialist who translates data lookups into clear, one-sentence answers. You have memorised the company's Q1 revenue figures and customer rankings. You never speculate or add commentary — you return the exact answer from the data, nothing more. |

**Goal:** Use Agent 1's classification and the mock data table below to return a single plain-text sentence.

### Mock data (hardcode in Agent 2's prompt)

| Question pattern | Answer |
|------------------|--------|
| Total revenue for Q1 | `Total Q1 revenue is $1.2M` |
| Top 3 customers by order count | `Top customers: Acme Corp (45), Beta Inc (38), Gamma LLC (31)` |

Rules: return **only** the answer sentence — no markdown, no explanation.

## Build checklist

1. Create workflow **Sample Analytics Q&A**
2. Set input field: `question`
3. Add Agent 1 and Agent 2 with roles/goals/tasks/backstories above
4. Chain: Task 1 → Task 2 (sequential)
5. Deploy and note the endpoint URL + API key

## Run the evaluation

1. Open eval UI → select dataset **Agent Workflow Sample**
2. Target: **Agent Studio Workflow**
3. Workflow URL + API key from deployment
4. Metrics: `agent_goal_accuracy`, `exact_match`
5. Run — both examples should score ≥ 0.9

## Expected results

| example_id | Question | Expected output |
|------------|----------|-----------------|
| agent_0 | What is the total revenue for Q1? | `Total Q1 revenue is $1.2M` |
| agent_1 | List the top 3 customers by order count | `Top customers: Acme Corp (45), Beta Inc (38), Gamma LLC (31)` |
