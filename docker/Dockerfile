# CAI Eval Platform
#
# Build:
#   docker build -f docker/Dockerfile -t cai-eval-platform .
#
# Run:
#   docker run -p 8080:8080 -v cai-eval-data:/data cai-eval-platform

FROM python:3.11-slim

RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        nginx curl sqlite3 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/
RUN pip install --no-cache-dir \
    "arize-phoenix>=4.0" \
    "opentelemetry-sdk>=1.20" \
    "opentelemetry-exporter-otlp-proto-http>=1.20" \
    "openinference-instrumentation-openai>=0.1" \
    "openai>=1.0" \
    "datasets>=2.14" \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "ragas>=0.2" \
    "pydantic>=2.0"

COPY backend/ /app/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY datasets/ /app/datasets/
RUN python -c "\
import json, pathlib; \
out = pathlib.Path('/app/datasets/spider/validation.json'); \
out.parent.mkdir(parents=True, exist_ok=True); \
print('Downloading Spider validation split from HuggingFace...', flush=True); \
from datasets import load_dataset; \
ds = load_dataset('xlangai/spider', split='validation'); \
records = [{'example_id': f'spider_{i}', 'question': r['question'], 'query': r['query'], 'db_id': r['db_id']} for i, r in enumerate(ds)]; \
out.write_text(json.dumps(records, indent=2)); \
print(f'Saved {len(records)} examples to {out}', flush=True) \
"

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
