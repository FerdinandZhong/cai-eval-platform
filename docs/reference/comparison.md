# Why CAI Eval Platform vs alternatives

Several tools evaluate LLMs and agents — most notably **Weights & Biases (Weave)**, and
hosted eval SaaS such as LangSmith, Braintrust, or Arize's own cloud product. They are
capable and worth knowing. This page is an honest look at where CAI Eval Platform fits and
where it doesn't.

## The core difference: it runs inside Cloudera AI

CAI Eval Platform is deployed as a **CAI Application inside your own tenant**. Prompts,
datasets, and model outputs never leave your Cloudera environment — no data is sent to a
third-party SaaS. For regulated data or on-prem/air-gapped deployments, that is often the
deciding factor. Hosted eval platforms require shipping your evaluation data (and frequently
your prompts and completions) to their cloud.

## Comparison

| Capability | CAI Eval Platform | Hosted eval SaaS (e.g. W&B Weave) |
|------------|-------------------|-----------------------------------|
| **Where data lives** | Your Cloudera tenant; nothing leaves | Vendor cloud (SaaS) |
| **Deployment** | One-click AMP inside CAI Workbench / CAII | SDK + external account |
| **Self-hosted vLLM endpoints** | First-class (any OpenAI-compatible URL) | Supported via SDK, but eval data still leaves |
| **Cloudera Agent Studio workflows** | Native black-box eval via kickoff/events | Not aware of Agent Studio |
| **Tracing backend** | Bundled Arize Phoenix (OTEL), self-hosted | Vendor-hosted tracing |
| **Bundled benchmarks** | Spider, τ-bench, safety/truthfulness sets | Bring your own |
| **Cost model** | Open source; runs on your compute | Usage/seat pricing |
| **Ecosystem breadth** | Focused on the Cloudera stack | Broad, mature, large integrations |

## When a hosted platform is the better choice

Be fair about it — pick the other tool when:

- You are **not** on Cloudera and don't want to self-host.
- You need a **broad, mature integration ecosystem** and managed infrastructure.
- Sending eval data to a vendor cloud is acceptable for your data governance.

## The short version (sales point)

> If your models and data live in Cloudera AI, CAI Eval Platform evaluates them **where they
> already run** — including self-hosted vLLM endpoints and Agent Studio workflows — with
> Phoenix tracing and reproducible experiments, and nothing leaves your tenant. That
> data-locality + Cloudera-native workflow story is what a generic hosted eval SaaS can't match.
