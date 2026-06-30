# Quick Start

## Docker (fastest)

```bash
docker run -p 8080:8080 -v cai-eval-data:/data \
  ferdinandzhong/cai-eval-platform:latest
```

| URL | Service |
|-----|---------|
| http://localhost:8080/app/ | Eval UI |
| http://localhost:8080/ | Arize Phoenix |

## Build from source

```bash
git clone https://github.com/FerdinandZhong/cai-eval-platform.git
cd cai-eval-platform
docker build -f docker/Dockerfile -t cai-eval-platform .
docker run -p 8080:8080 -v cai-eval-data:/data cai-eval-platform
```

## Local development

```bash
cd backend
pip install -e ..
DATASETS_DIR=../datasets DATA_DIR=/tmp/cai-eval-data \
  uvicorn main:app --reload --port 9000
```

Run Phoenix separately:

```bash
phoenix serve --port 6006
```

## First evaluation

1. Open **http://localhost:8080/app/**
2. Select a dataset (e.g. `Agent Workflow Sample`)
3. Choose **Agent Studio Workflow** as the target
4. Enter your workflow URL and API key
5. Click **Discover Workflow Inputs** to auto-map fields
6. Select metrics and click **Run Evaluation**
7. View results and traces in Phoenix at **http://localhost:8080/**
