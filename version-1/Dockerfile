# Cricket Metrics API — Dockerfile (DuckDB mode)
# Build context: repo root.
#
# The DuckDB file is NOT baked into the image. Mount it at /data/cricket/
# or set DUCKDB_REMOTE_URL to download on first boot.
#
# For Hetzner CAX11 (ARM64, 4GB RAM): use --workers 2
# For larger VPS (8GB+): use --workers 4

FROM python:3.12-slim

WORKDIR /app

COPY gui/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY gui/backend/ /app/

# DuckDB file lives on a mounted volume, not in the image
VOLUME ["/data/cricket"]

ENV DUCKDB_PATH=/data/cricket/cricket.duckdb
ENV DUCKDB_TEMP_DIR=/data/cricket/duckdb-tmp
ENV HOST=0.0.0.0

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/api/health'); assert r.status_code == 200"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
