# Cricket Metrics API — Dockerfile for Railway (repo root build)
# Build context: repo root. Data not copied; use DATA_ROOT at runtime (volume or baked image).
#
# Mount pipeline outputs at /app/output (e.g. data/output/ from the repo) and set
# DATA_ROOT=/app so the backend loads /app/output/mens_t20i, … See DEPLOYMENT.md.
#
# Railway: leave Root Directory empty so this file is used.

FROM python:3.12-slim

WORKDIR /app

COPY gui/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY gui/backend/ /app/

ENV DATA_ROOT=/app
ENV HOST=0.0.0.0
EXPOSE 8080
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
