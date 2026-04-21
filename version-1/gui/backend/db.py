"""
DuckDB connection management and query helpers for Cricket Metrics API.

Replaces data_loader.py. Provides connection lifecycle, format validation,
and helper functions used by all routers.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Any

import duckdb

# Valid format keys (DuckDB schema names)
VALID_FORMATS = ("mens_t20i", "womens_t20i", "mens_ipl", "womens_ipl")
DEFAULT_FORMAT = "mens_t20i"

_VALID_FMT_SET = frozenset(VALID_FORMATS)

DB_PATH = Path(os.environ.get("DUCKDB_PATH", "/data/cricket/cricket.duckdb"))


def safe_fmt(fmt: str) -> str:
    """Validate and return a format string safe for SQL schema interpolation."""
    f = fmt.lower().strip()
    if f not in _VALID_FMT_SET:
        raise ValueError(f"Invalid format: {fmt!r}")
    return f


def _duckdb_temp_directory(db_path: str) -> str:
    """Writable temp dir for DuckDB spills. Docker sets DUCKDB_TEMP_DIR under /data."""
    configured = os.environ.get("DUCKDB_TEMP_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.append(str(Path(tempfile.gettempdir()) / "cricket-metrics-duckdb-tmp"))
    candidates.append("/data/cricket/duckdb-tmp")
    for d in candidates:
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            continue
    # Last resort: same directory as the DB file
    fallback = str(Path(db_path).resolve().parent / ".duckdb-tmp")
    Path(fallback).mkdir(parents=True, exist_ok=True)
    return fallback


def open_connection(path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection with resource caps."""
    p = str(path or DB_PATH)
    conn = duckdb.connect(p, read_only=True)
    conn.execute("SET memory_limit = '512MB'")
    conn.execute("SET threads = 2")
    tmp_dir = _duckdb_temp_directory(p)
    esc = tmp_dir.replace("'", "''")
    conn.execute(f"SET temp_directory = '{esc}'")
    return conn


def available_formats(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Return list of format schemas present in the DuckDB file."""
    rows = conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('mens_t20i','womens_t20i','mens_ipl','womens_ipl')"
    ).fetchall()
    return [r[0] for r in rows]


def max_last_match_date_iso(conn: duckdb.DuckDBPyConnection, fmt: str) -> str | None:
    """Latest last_match_date across batting and bowling careers (ISO yyyy-mm-dd)."""
    f = safe_fmt(fmt)
    result = conn.execute(f"""
        SELECT MAX(d) FROM (
            SELECT MAX(last_match_date) AS d FROM {f}.bat_careers
            WHERE last_match_date IS NOT NULL
            UNION ALL
            SELECT MAX(last_match_date) AS d FROM {f}.bowl_careers
            WHERE last_match_date IS NOT NULL
        )
    """).fetchone()
    if result and result[0] is not None:
        try:
            return result[0].strftime("%Y-%m-%d")
        except Exception:
            return str(result[0])[:10]
    return None


def active_recency_days_for_format(fmt: str) -> int:
    """How recent a player's last match must be to count as active."""
    f = str(fmt).lower()
    if f in ("mens_ipl", "womens_ipl"):
        return 730
    return 365


def activity_cutoff_date(conn: duckdb.DuckDBPyConnection, fmt: str) -> str | None:
    """Compute the activity cutoff date as an ISO string.

    Uses today minus the recency window. If data is older than that,
    anchors to max(last_match_date) minus recency window.
    """
    import datetime

    f = safe_fmt(fmt)
    days = active_recency_days_for_format(fmt)

    result = conn.execute(f"""
        SELECT MAX(d) FROM (
            SELECT MAX(last_match_date) AS d FROM {f}.bat_careers WHERE last_match_date IS NOT NULL
            UNION ALL
            SELECT MAX(last_match_date) AS d FROM {f}.bowl_careers WHERE last_match_date IS NOT NULL
        )
    """).fetchone()

    now = datetime.date.today()
    wall = now - datetime.timedelta(days=days)

    if result and result[0] is not None:
        try:
            data_max = result[0]
            if hasattr(data_max, 'date'):
                data_max = data_max.date()
            elif isinstance(data_max, str):
                data_max = datetime.date.fromisoformat(data_max[:10])
            if data_max < wall:
                cutoff = data_max - datetime.timedelta(days=days)
                return cutoff.isoformat()
        except Exception:
            pass

    return wall.isoformat()


# ── Shared SQL helpers ────────────────────────────────────────────


def query_one(conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> dict | None:
    """Execute SQL and return first row as a dict, or None."""
    result = conn.execute(sql, params or [])
    columns = [desc[0] for desc in result.description]
    row = result.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


def query_all(conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    """Execute SQL and return all rows as a list of dicts."""
    result = conn.execute(sql, params or [])
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def query_df(conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    """Execute SQL and return result as a pandas DataFrame."""
    return conn.execute(sql, params or []).fetchdf()


def query_count(conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> int:
    """Execute a COUNT query and return the integer result."""
    row = conn.execute(sql, params or []).fetchone()
    return int(row[0]) if row else 0


# ── Safe value extractors for serialization ───────────────────────
# These mirror the _safe_float/_safe_int/_safe_str patterns used across
# all routers to guard against NaN/None leaking into JSON responses.


def safe_float(v: Any) -> float | None:
    """Convert to float, returning None for NaN/inf."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def safe_int(v: Any) -> int:
    """Convert to int, returning 0 for NaN/None."""
    if v is None:
        return 0
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def safe_str(v: Any, default: str = "") -> str:
    """Convert to string, returning default for NaN/None."""
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s
