FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Do NOT set OUTPUT_DIR — the backend auto-discovers output_t20i/ and
# output_ipl/ via load_all_data() when OUTPUT_DIR is unset.
# Mount the data directories as volumes at runtime (see docker-compose.yml).
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
