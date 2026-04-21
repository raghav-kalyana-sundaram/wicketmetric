"""
Cricket Metrics — FastAPI Backend Application (DuckDB mode).

This is the main entry point for the Cricket Metrics API. It:

1. Opens a read-only DuckDB connection at startup.
2. Builds a trigram search index over all player names from DuckDB.
3. Mounts all API routers (search, player, rankings, matchups, compare, venues).
4. Configures CORS for frontend development.
5. Provides a health-check and metadata endpoint.

Usage:
    # Development
    cd gui/backend
    uvicorn app:app --reload --port 8000

    # Production (2 workers for 4 GB RAM VPS)
    uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2

Environment variables:
    DUCKDB_PATH       — Path to the cricket.duckdb file.
                        Default: /data/cricket/cricket.duckdb
    DUCKDB_REMOTE_URL — (Optional) URL to download the .duckdb file from.
    DUCKDB_SHA256_URL — (Optional) URL for checksum verification.

    A ``.env`` file in this directory (``gui/backend/.env``) is loaded automatically
    on startup.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import duckdb
from fastapi import FastAPI, HTTPException, Query as FastAPIQuery
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs into os.environ (does not override existing vars)."""
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, _, value = s.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        existing = os.environ.get(key)
        if existing is None or (isinstance(existing, str) and existing.strip() == ""):
            os.environ[key] = value


_load_env_file(_BACKEND_DIR / ".env")

from duckdb_hydrate import maybe_hydrate_duckdb

maybe_hydrate_duckdb()

from db import (
    DEFAULT_FORMAT,
    VALID_FORMATS,
    available_formats as db_available_formats,
    max_last_match_date_iso,
    open_connection,
    safe_fmt,
    query_count,
)
from routers import compare as compare_router
from routers import eras as eras_router
from routers import live_espn as live_espn_router
from routers import match_scorecards as match_scorecards_router
from routers import matchups as matchups_router
from routers import player as player_router
from routers import rankings as rankings_router
from routers import search as search_router
from routers import team as team_router
from routers import teams as teams_router
from routers import venues as venues_router
from schemas import LatestScorecardSummary, MetaResponse, T20ITeamTiers
from search_index import TrigramIndex, build_search_index_from_db
from t20i_team_tiers import get_t20i_tier_config, is_t20_international_format

# ── Global state (populated at startup) ───────────────────────────
_db_conn: duckdb.DuckDBPyConnection | None = None
_available_formats: list[str] = []
_search_indices: dict[str, TrigramIndex] = {}

_FORMAT_REGEX = "^(" + "|".join(VALID_FORMATS) + ")$"


# ── Dependency providers ──────────────────────────────────────────

def _data_unavailable_detail() -> str:
    """Human-readable reason for 503 when DuckDB is missing or empty."""
    db_path = Path(os.environ.get("DUCKDB_PATH", "/data/cricket/cricket.duckdb"))
    if not db_path.exists():
        return (
            "DuckDB file not found. Set DUCKDB_PATH to your cricket.duckdb file "
            f"(looked for {db_path})."
        )
    return "DuckDB is not connected; check backend logs for startup errors."


def get_db(
    format: str = FastAPIQuery(DEFAULT_FORMAT, pattern=_FORMAT_REGEX),
) -> tuple[duckdb.DuckDBPyConnection, str]:
    """Provide (connection, validated_format) for routers."""
    if _db_conn is None:
        raise HTTPException(status_code=503, detail=_data_unavailable_detail())
    return _db_conn, safe_fmt(format)


def get_db_conn() -> duckdb.DuckDBPyConnection:
    """Provide the raw DuckDB connection (for cross-format queries)."""
    if _db_conn is None:
        raise HTTPException(status_code=503, detail=_data_unavailable_detail())
    return _db_conn


def get_search_index(
    format: str = FastAPIQuery(DEFAULT_FORMAT, pattern=_FORMAT_REGEX),
) -> TrigramIndex:
    """Provide the trigram search index for the requested format."""
    fmt = format.lower()
    if fmt in _search_indices:
        return _search_indices[fmt]
    if DEFAULT_FORMAT in _search_indices:
        return _search_indices[DEFAULT_FORMAT]
    raise HTTPException(
        status_code=503,
        detail=(
            "Search index is not available. "
            "Ensure DuckDB is loaded and search indices built at startup."
        ),
    )


def _api_default_format() -> str:
    """Format key advertised to clients as default."""
    if DEFAULT_FORMAT in _available_formats:
        return DEFAULT_FORMAT
    for k in VALID_FORMATS:
        if k in _available_formats:
            return k
    return DEFAULT_FORMAT


# ── Lifespan (startup / shutdown) ─────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _db_conn, _available_formats, _search_indices

    print("=" * 60)
    print("  Cricket Metrics API — Starting up (DuckDB mode)")
    print("=" * 60)

    t0 = time.perf_counter()

    # ── 1. Open DuckDB connection ──────────────────────────────
    db_path = Path(os.environ.get("DUCKDB_PATH", "/data/cricket/cricket.duckdb"))
    if not db_path.exists():
        print(f"\n  WARNING: DuckDB file not found at {db_path}")
        print("  The API will start but most endpoints will return empty results.\n")
        _db_conn = None
        _available_formats = []
    else:
        print(f"\n  Opening DuckDB: {db_path}")
        _db_conn = open_connection(db_path)
        _available_formats = db_available_formats(_db_conn)
        print(f"  Available formats: {_available_formats}")

    # ── 2. Build trigram search indices ────────────────────────
    if _db_conn and _available_formats:
        print("\nBuilding search indices...")
        for fmt in _available_formats:
            print(f"  Building index for {fmt.upper()}...")
            _search_indices[fmt] = build_search_index_from_db(_db_conn, fmt)

    # ── 3. Wire dependency overrides into routers ─────────────
    search_router._get_search_index = get_search_index  # type: ignore[attr-defined]
    player_router._get_store = get_db  # type: ignore[attr-defined]
    player_router._get_search_index = get_search_index  # type: ignore[attr-defined]
    rankings_router._get_store = get_db  # type: ignore[attr-defined]
    matchups_router._get_store = get_db  # type: ignore[attr-defined]
    match_scorecards_router._get_store = get_db  # type: ignore[attr-defined]
    compare_router._get_multi_store = get_db_conn  # type: ignore[attr-defined]
    venues_router._get_store = get_db  # type: ignore[attr-defined]
    eras_router._get_store = get_db  # type: ignore[attr-defined]
    team_router._get_store = get_db  # type: ignore[attr-defined]

    elapsed = time.perf_counter() - t0
    print(f"\n  Startup complete in {elapsed:.2f}s")
    print(f"   Available formats: {_available_formats}")
    if _db_conn:
        for fmt in _available_formats:
            f = safe_fmt(fmt)
            try:
                bat_count = query_count(_db_conn, f"SELECT COUNT(*) FROM {f}.bat_careers")
                bowl_count = query_count(_db_conn, f"SELECT COUNT(*) FROM {f}.bowl_careers")
                idx = _search_indices.get(fmt)
                idx_size = idx.size if idx else 0
                print(
                    f"   [{fmt.upper()}] Batters: {bat_count:,}  "
                    f"Bowlers: {bowl_count:,}  "
                    f"Search: {idx_size:,}"
                )
            except Exception:
                pass
    print("=" * 60)
    print()

    yield

    print("\nCricket Metrics API — Shutting down")
    if _db_conn:
        _db_conn.close()
        _db_conn = None
    _search_indices.clear()
    _available_formats.clear()


# ── FastAPI application ───────────────────────────────────────────

app = FastAPI(
    title="Cricket Metrics API",
    description=(
        "T20 Player Performance Profiling Engine — API.\n\n"
        "Serves player profiles, leaderboards, matchups, form time-series, "
        "similarity data, venue analysis, and more from a DuckDB database. "
        "All data is read-only with sub-millisecond response times.\n\n"
        "Supports multiple data slices (men's/women's T20 and IPL) via `?format=`.\n\n"
        "**Data source:** Cricsheet international T20, IPL, and WPL ball-by-ball JSON, "
        "processed through the Cricket Metrics pipeline."
    ),
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────
_default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:4173",
]
_cors_origins_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = _default_origins + [
    o.strip() for o in _cors_origins_env.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)


# ── Override dependency functions in router modules ────────────────

app.dependency_overrides[search_router._get_search_index] = get_search_index
app.dependency_overrides[player_router._get_store] = get_db
app.dependency_overrides[player_router._get_search_index] = get_search_index
app.dependency_overrides[rankings_router._get_store] = get_db
app.dependency_overrides[matchups_router._get_store] = get_db
app.dependency_overrides[match_scorecards_router._get_store] = get_db
app.dependency_overrides[compare_router._get_multi_store] = get_db_conn
app.dependency_overrides[venues_router._get_store] = get_db
app.dependency_overrides[eras_router._get_store] = get_db
app.dependency_overrides[team_router._get_store] = get_db
app.dependency_overrides[teams_router._get_store] = get_db


# ── Include routers ───────────────────────────────────────────────

app.include_router(search_router.router)
app.include_router(player_router.router)
app.include_router(rankings_router.router)
app.include_router(matchups_router.router)
app.include_router(match_scorecards_router.router)
app.include_router(compare_router.router)
app.include_router(venues_router.router)
app.include_router(eras_router.router)
app.include_router(team_router.router)
app.include_router(teams_router.router)
app.include_router(live_espn_router.router)


# ── Root / health / meta endpoints ────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API documentation."""
    return JSONResponse(
        content={
            "message": "Cricket Metrics API",
            "docs": "/api/docs",
            "redoc": "/api/redoc",
            "health": "/api/health",
            "meta": "/api/meta",
        }
    )


@app.get("/api/health", tags=["meta"])
async def health_check():
    if _db_conn is not None and _available_formats:
        return {"status": "ok", "formats": _available_formats}
    return {"status": "degraded", "reason": "Data not loaded"}


@app.get("/api/formats", tags=["meta"])
async def list_formats():
    return {
        "formats": _available_formats,
        "default": _api_default_format(),
    }


@app.get("/api/meta", response_model=MetaResponse, tags=["meta"])
async def api_metadata(
    format: str = FastAPIQuery(DEFAULT_FORMAT, pattern=_FORMAT_REGEX),
):
    if _db_conn is None or not _available_formats:
        return MetaResponse(status="not_loaded")

    fmt = format.lower()
    idx = _search_indices.get(fmt)
    if fmt not in _available_formats or idx is None:
        return MetaResponse(status="not_loaded")

    f = safe_fmt(fmt)
    bat_count = query_count(_db_conn, f"SELECT COUNT(*) FROM {f}.bat_careers")
    bowl_count = query_count(_db_conn, f"SELECT COUNT(*) FROM {f}.bowl_careers")
    matchup_count = query_count(_db_conn, f"SELECT COUNT(*) FROM {f}.matchups")
    venue_count = query_count(_db_conn, f"SELECT COUNT(*) FROM {f}.venue")

    latest_sc = match_scorecards_router.compute_latest_scorecard_summary_db(_db_conn, f)
    latest_obj = LatestScorecardSummary(**latest_sc) if latest_sc is not None else None

    tiers: T20ITeamTiers | None = None
    if is_t20_international_format(format):
        main_l, assoc_l, top_n = get_t20i_tier_config()
        if main_l or assoc_l:
            tiers = T20ITeamTiers(top_n=top_n, main=main_l, associates=assoc_l)

    return MetaResponse(
        status="ok",
        total_batters=bat_count,
        total_bowlers=bowl_count,
        total_matchups=matchup_count,
        total_venues=venue_count,
        countries=idx.all_countries(),
        archetypes=idx.all_archetypes(),
        data_through_date=max_last_match_date_iso(_db_conn, fmt),
        latest_scorecard=latest_obj,
        t20i_team_tiers=tiers,
    )


# ── Error handlers ────────────────────────────────────────────────

@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "detail": str(exc.detail) if hasattr(exc, "detail") else "Not found",
            "hint": "Check the player ID or endpoint path. Use /api/search to find valid player IDs.",
        },
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "hint": "Check the backend logs for details.",
        },
    )


# ── Main (for direct execution) ──────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    reload = os.environ.get("RELOAD", "false").lower() in ("true", "1", "yes")

    print(f"Starting Cricket Metrics API on {host}:{port}")
    print(f"  Reload: {reload}")
    print(f"  DuckDB: {os.environ.get('DUCKDB_PATH', '(default)')}")
    print()

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
