#!/usr/bin/env bash
# refresh_duckdb.sh — Download new DuckDB file and hot-swap without downtime.
#
# Usage:
#   ./scripts/refresh_duckdb.sh [REMOTE_URL] [SHA256_URL]
#
# Or set environment variables:
#   DUCKDB_REMOTE_URL=https://...
#   DUCKDB_SHA256_URL=https://...
#   DUCKDB_PATH=/data/cricket/cricket.duckdb

set -euo pipefail

DUCKDB_PATH="${DUCKDB_PATH:-/data/cricket/cricket.duckdb}"
REMOTE_URL="${1:-${DUCKDB_REMOTE_URL:-}}"
SHA256_URL="${2:-${DUCKDB_SHA256_URL:-}}"

if [ -z "$REMOTE_URL" ]; then
    echo "ERROR: No remote URL provided. Set DUCKDB_REMOTE_URL or pass as argument."
    exit 1
fi

NEW_FILE="${DUCKDB_PATH}.new"
CHECKSUM_FILE="${DUCKDB_PATH}.sha256"

echo "=== DuckDB Refresh ==="
echo "  Remote: $REMOTE_URL"
echo "  Local:  $DUCKDB_PATH"

# Download new file
echo "  Downloading..."
curl -fSL -o "$NEW_FILE" "$REMOTE_URL"
echo "  Downloaded: $(du -h "$NEW_FILE" | cut -f1)"

# Verify checksum if URL provided
if [ -n "$SHA256_URL" ]; then
    echo "  Fetching checksum..."
    EXPECTED=$(curl -fsSL "$SHA256_URL" | awk '{print $1}')
    ACTUAL=$(sha256sum "$NEW_FILE" | awk '{print $1}')
    if [ "$EXPECTED" != "$ACTUAL" ]; then
        echo "  ERROR: Checksum mismatch!"
        echo "    Expected: $EXPECTED"
        echo "    Actual:   $ACTUAL"
        rm -f "$NEW_FILE"
        exit 1
    fi
    echo "  Checksum verified."
fi

# Atomic swap (same filesystem = atomic rename on Linux)
echo "  Swapping files..."
mv "$NEW_FILE" "$DUCKDB_PATH"

# Signal uvicorn to gracefully restart workers
UVICORN_PID=$(pgrep -f "uvicorn.*app:app" | head -1 || true)
if [ -n "$UVICORN_PID" ]; then
    echo "  Sending SIGHUP to uvicorn (PID $UVICORN_PID) for graceful worker restart..."
    kill -HUP "$UVICORN_PID" 2>/dev/null || true
    echo "  Workers will restart and pick up the new file."
else
    echo "  No uvicorn process found. The new file will be used on next startup."
fi

echo "=== Refresh complete ==="
