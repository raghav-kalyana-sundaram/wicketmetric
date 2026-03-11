# ── Cricket Metrics — Backend Dockerfile (local / Docker Compose) ──
#
# This Dockerfile is for LOCAL development with Docker Compose, where
# the output data directories are mounted as volumes at runtime.
#
# For Railway / production deployment, use the root-level Dockerfile.backend
# which copies the data directories into the image at build time.
#
# Local usage:
#   cd gui/backend
#   docker build -t cricket-metrics-backend .
#   docker run -p 8000:8000 \
#     -v ../../output_t20i:/app/output_t20i:ro \
#     -v ../../output_ipl:/app/output_ipl:ro \
#     cricket-metrics-backend

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Data directories (output_t20i/, output_ipl/) should be mounted as
# volumes at runtime — they are NOT copied into the image.
# DATA_ROOT tells the data loader where to find them.
ENV DATA_ROOT=/app
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE ${PORT}

# Use shell form so $PORT is expanded at runtime
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}
