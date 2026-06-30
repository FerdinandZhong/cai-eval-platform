# Docker Deployment

## Pull and run

```bash
docker run -p 8080:8080 -v cai-eval-data:/data \
  ferdinandzhong/cai-eval-platform:0.1.0
```

The image is pre-built with the Spider and τ-bench datasets included.

## Ports and URLs

| Port | URL path | Service |
|------|----------|---------|
| 8080 | `/app/` | Eval UI + REST API |
| 8080 | `/` | Arize Phoenix tracing UI |

## Environment variables

```bash
docker run -p 8080:8080 -v cai-eval-data:/data \
  -e JUDGE_LLM_URL=http://my-llm:8000/v1 \
  -e JUDGE_LLM_API_KEY=sk-... \
  ferdinandzhong/cai-eval-platform:0.1.0
```

See [Environment Variables](../reference/env_vars.md) for the full list.

## Persistent data

Mount `/data` to persist Phoenix traces and evaluation results across restarts:

```bash
docker run -p 8080:8080 \
  -v /path/to/local/data:/data \
  ferdinandzhong/cai-eval-platform:0.1.0
```

## Build your own image

```bash
git clone https://github.com/FerdinandZhong/cai-eval-platform.git
cd cai-eval-platform
docker build -f docker/Dockerfile -t my-eval-platform .
```

!!! note
    Spider (`xlangai/spider`) is downloaded from HuggingFace at build time.
    τ-bench is downloaded from GitHub. Both are baked into the image.
