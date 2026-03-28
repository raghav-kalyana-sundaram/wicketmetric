#!/usr/bin/env bash
# Download official Cricsheet JSON zips, extract, and run the pipeline for each slice.
# Usage: from repo root, with Python env that has project dependencies:
#   chmod +x scripts/sync_cricsheet.sh && ./scripts/sync_cricsheet.sh
#
# Outputs under ./data/output/ (single tree):
#   data/output/mens_t20i   data/output/womens_t20i   data/output/mens_ipl   data/output/womens_ipl
#
# After a successful run, restart the API so it reloads Parquet.
# Cricsheet zips may nest *.json one level deep; the pipeline finds them automatically.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
  :
elif [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PYTHON="$ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "sync_cricsheet.sh: need python3 or a repo-root .venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2
  exit 1
fi
DATA="${CRICSHEET_DATA_DIR:-$ROOT/data/cricsheet}"
mkdir -p "$DATA"

fetch() {
  local url="$1" dest="$2"
  echo "Fetching $url"
  curl -fsSL -o "$dest" "$url" || wget -q -O "$dest" "$url"
}

fetch "https://cricsheet.org/downloads/t20s_male_json.zip" "$DATA/t20s_male_json.zip"
fetch "https://cricsheet.org/downloads/t20s_female_json.zip" "$DATA/t20s_female_json.zip"
fetch "https://cricsheet.org/downloads/ipl_male_json.zip" "$DATA/ipl_male_json.zip"
fetch "https://cricsheet.org/downloads/wpl_female_json.zip" "$DATA/wpl_female_json.zip"

unzip_dir() {
  local zip="$1" dir="$2"
  rm -rf "$dir"
  mkdir -p "$dir"
  unzip -q -o "$zip" -d "$dir"
}

unzip_dir "$DATA/t20s_male_json.zip" "$DATA/t20s_male_json"
unzip_dir "$DATA/t20s_female_json.zip" "$DATA/t20s_female_json"
unzip_dir "$DATA/ipl_male_json.zip" "$DATA/ipl_male_json"
unzip_dir "$DATA/wpl_female_json.zip" "$DATA/wpl_female_json"

cd "$ROOT"
"$PYTHON" src/main.py "$DATA/t20s_male_json" --output "$ROOT/data/output/mens_t20i" --format t20i
"$PYTHON" src/main.py "$DATA/t20s_female_json" --output "$ROOT/data/output/womens_t20i" --format t20i
"$PYTHON" src/main.py "$DATA/ipl_male_json" --output "$ROOT/data/output/mens_ipl" --format ipl
"$PYTHON" src/main.py "$DATA/wpl_female_json" --output "$ROOT/data/output/womens_ipl" --format ipl

echo "Done. Restart the FastAPI server to pick up new Parquet files."
