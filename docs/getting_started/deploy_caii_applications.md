# Deploy on CAII Applications

**Cloudera AI Inference (CAII) Applications** is a Kubernetes-native deployment surface built into the Cloudera AI platform. It deploys Docker images directly as scalable k8s workloads — no git sync, no environment setup, no nginx compilation needed.

**Docker image:** [`ferdinandzhong/cai-eval-platform:0.1.0`](https://hub.docker.com/repository/docker/ferdinandzhong/cai-eval-platform/general)

## Step 1 — Create the Application

Navigate to **Applications** in the left sidebar → **Create Application**.

![Create CAII Application](../images/create_caii_application_from_ui.png)

Fill in the form:

| Field | Value |
|-------|-------|
| **Environment & Inference Service** | Select your inference cluster |
| **Name** | `cai-eval-platform` |
| **Subdomain** | `cai-eval-platform` (used to construct the public URL) |
| **Select Source** | **Docker** |
| **Docker URL** | `docker.io/ferdinandzhong/cai-eval-platform:0.1.0` |
| **Username** | `ferdinandzhong` |
| **Access Token** | Your Docker Hub access token |

Click **Create Application**.

## Step 2 — Configure instance and autoscaling

![Update CAII Application Configuration](../images/update_caii_application_configuration.png)

| Field | Recommended value |
|-------|-------------------|
| **Instance Type** | CPU instance with ≥ 4 vCPU / 16 GiB |
| **CPU** | 4 vCPU |
| **Memory** | 16 GiB |
| **Endpoint Autoscale Range** | Min: 1, Max: 3 |
| **Autoscale Metric Type** | Request Per Second |
| **Target Metric Value** | 200 |

## Step 3 — Environment variables (optional)

Add key-value pairs in the **Environment Variables** section:

| Variable | Description |
|----------|-------------|
| `JUDGE_LLM_URL` | OpenAI-compatible judge LLM base URL for Ragas metrics |
| `JUDGE_LLM_API_KEY` | API key for the judge LLM |

Click **Create Application** to deploy.

## Step 4 — Access the platform

Once the Application status reaches **Running**:

- `<app-url>/app/` — Eval UI + API
- `<app-url>/` — Arize Phoenix tracing UI

!!! tip
    The CAII Application uses the system nginx from the Docker image — full redirect support and all datasets (Spider + τ-bench) pre-baked in. No additional setup required.
