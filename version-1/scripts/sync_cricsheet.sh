#!/usr/bin/env bash
# Download official Cricsheet JSON zips, extract, and run the pipeline for each slice.
# Usage: from repo root, with Python env that has project dependencies:
#   chmod +x scripts/sync_cricsheet.sh && ./scripts/sync_cricsheet.sh
#
# Outputs under ./data/output/ (single tree):
#   data/output/mens_t20i   data/output/womens_t20i   data/output/mens_ipl   data/output/womens_ipl
#
# Incremental (default): only parses JSON for matches not yet in
#   data/output/<slice>/.cache/deliveries_pre_xr.parquet
# then re-runs the full pipeline on the merged delivery table (ratings stay consistent).
# Set INCREMENTAL=0 or SYNC_FULL=1 to always do a full re-parse (e.g. after changing config.yaml).
#
# Unzip merges into existing folders (no rm -rf) so unchanged JSON files stay on disk until
# overwritten by the zip.
#
# After a successful run, rebuild DuckDB if you use it (see build_duckdb.py) and restart the API.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
  :
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PYTHON="$ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "sync_cricsheet.sh: need python3 or a repo-root .venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2
  exit 1
fi

INCREMENTAL="${INCREMENTAL:-1}"
if [[ "${SYNC_FULL:-0}" == "1" ]]; then
  INCREMENTAL=0
fi
INC_FLAG=()
if [[ "$INCREMENTAL" == "1" ]]; then
  INC_FLAG=(--incremental)
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

# Merge into existing dirs (overwrite files from the zip) — do not delete the whole tree.
unzip_merge() {
  local zip="$1" dir="$2"
  mkdir -p "$dir"
  unzip -q -o "$zip" -d "$dir"
}

unzip_merge "$DATA/t20s_male_json.zip" "$DATA/t20s_male_json"
unzip_merge "$DATA/t20s_female_json.zip" "$DATA/t20s_female_json"
unzip_merge "$DATA/ipl_male_json.zip" "$DATA/ipl_male_json"
unzip_merge "$DATA/wpl_female_json.zip" "$DATA/wpl_female_json"

cd "$ROOT"
"$PYTHON" src/main.py "$DATA/t20s_male_json" --output "$ROOT/data/output/mens_t20i" --format t20i "${INC_FLAG[@]}"
"$PYTHON" src/main.py "$DATA/t20s_female_json" --output "$ROOT/data/output/womens_t20i" --format t20i "${INC_FLAG[@]}"
"$PYTHON" src/main.py "$DATA/ipl_male_json" --output "$ROOT/data/output/mens_ipl" --format ipl "${INC_FLAG[@]}"
"$PYTHON" src/main.py "$DATA/wpl_female_json" --output "$ROOT/data/output/womens_ipl" --format ipl "${INC_FLAG[@]}"

echo "Done. Rebuild DuckDB if needed:  .venv/bin/python build_duckdb.py --parquet-root data/output --output data/cricket.duckdb"
echo "Then restart the FastAPI server."
