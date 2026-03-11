# ── Cricket Metrics — Backend Dockerfile (root-level) ─────────────
# Build context: project root (so output_t20i/ and output_ipl/ are accessible).
#
# Railway setup:
#   - Root Directory: (repo root, leave blank or set to "/")
#   - Railway will auto-detect this Dockerfile at the repo root.
#
# Local build:
#   docker build -t cricket-metrics-backend .

FROM python:3.12-slim

WORKDIR /app

# ── 1. Install Python dependencies ───────────────────────────────
COPY gui/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── 2. Copy pipeline output data ─────────────────────────────────
# These directories contain the pre-computed Parquet/CSV files that
# the backend loads into memory at startup.
COPY output_t20i/ /app/output_t20i/
COPY output_ipl/  /app/output_ipl/

# ── 3. Copy backend application code ─────────────────────────────
COPY gui/backend/ /app/

# ── 4. Tell the data loader where to find data ───────────────────
# DATA_ROOT overrides the default project-root resolution so the
# backend finds /app/output_t20i/ and /app/output_ipl/ correctly.
ENV DATA_ROOT=/app

# ── 5. Respect Railway's dynamic PORT ────────────────────────────
# Railway injects $PORT at runtime. Default to 8000 for local builds.
ENV HOST=0.0.0.0


EXPOSE ${PORT}

# Use shell form so $PORT is expanded at runtime
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}
