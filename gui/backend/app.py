"""
Cricket Metrics — FastAPI Backend Application.

This is the main entry point for the Cricket Metrics API. It:

1. Loads all pipeline Parquet/CSV outputs into memory at startup.
2. Builds a trigram search index over all player names.
3. Mounts all API routers (search, player, rankings, matchups, compare, venues).
4. Configures CORS for frontend development.
5. Provides a health-check and metadata endpoint.

Usage:
    # Development
    cd gui/backend
    uvicorn app:app --reload --port 8000

    # Production
    uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4

Environment variables:
    OUTPUT_DIR  — Path to the pipeline output directory.
                  Default: ../../data/output (relative to this file’s directory).

    A ``.env`` file in this directory (``gui/backend/.env``) is loaded automatically
    on startup so variables like ``DATA_ROOT`` work without ``export`` in the shell.

    Optional Vercel Blob: set ``BLOB_PARQUET_BASE_URL`` to the public store origin
    (``https://<id>.public.blob.vercel-storage.com``) so Parquet is downloaded into
    a cache and ``DATA_ROOT`` is set before load. See ``blob_hydrate.py`` and PUBLISHING.md.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Ensure the backend package is importable ──────────────────────
# When running with `uvicorn app:app` from the gui/backend/ directory,
# Python's CWD-based imports should work. But just in case, we add
# the backend directory to sys.path.
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs into os.environ (does not override existing vars).

    Uvicorn does not read ``.env`` files; this mirrors ``python-dotenv``'s
    ``override=False`` behaviour so local ``gui/backend/.env`` works out of the box.
    """
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

from blob_hydrate import maybe_hydrate_data_root_from_blob

maybe_hydrate_data_root_from_blob()

from data_loader import (
    DEFAULT_FORMAT,
    VALID_FORMATS,
    DataStore,
    MultiDataStore,
    load_all_data,
    load_data,
    max_last_match_date_iso,
)


def _api_default_format(multi: MultiDataStore) -> str:
    """Format key advertised to clients as default — must appear in ``available_formats`` when non-empty."""
    avail = multi.available_formats
    if DEFAULT_FORMAT in avail:
        return DEFAULT_FORMAT
    for k in VALID_FORMATS:
        if k in avail:
            return k
    return DEFAULT_FORMAT
from fastapi import Query as FastAPIQuery
from routers import compare as compare_router
from routers import eras as eras_router
from routers import match_scorecards as match_scorecards_router
from routers import matchups as matchups_router
from routers import player as player_router
from routers import rankings as rankings_router

# Import routers
from routers import live_espn as live_espn_router
from routers import search as search_router
from routers import team as team_router
from routers import venues as venues_router
from schemas import LatestScorecardSummary, MetaResponse, T20ITeamTiers
from search_index import TrigramIndex, build_search_index
from t20i_team_tiers import get_t20i_tier_config, is_t20_international_format

# ── Global state (populated at startup) ───────────────────────────
_multi_store: MultiDataStore | None = None
_search_indices: dict[str, TrigramIndex] = {}

# Keep legacy single-store references for backward compat during transition
_store: DataStore | None = None
_search_index: TrigramIndex | None = None


# ── Dependency providers ──────────────────────────────────────────
# These are injected into route handlers via FastAPI's Depends() system.
# They are wired up after startup so the lifespan context has populated
# the globals.
#
# The `format` query parameter selects which dataset slice to use.
# All routers that depend on `get_store` / `get_search_index` will
# automatically receive the correct dataset for the requested format.

_FORMAT_REGEX = "^(" + "|".join(VALID_FORMATS) + ")$"


def get_store(
    format: str = FastAPIQuery(DEFAULT_FORMAT, pattern=_FORMAT_REGEX),
) -> DataStore:
    """Provide the in-memory DataStore for the requested format."""
    if _multi_store is None:
        raise RuntimeError(
            "DataStore not loaded. The application did not start correctly."
        )
    return _multi_store.get(format)


def get_multi_store() -> MultiDataStore:
    """Full multi-format store (used by compare endpoints for cross-slice lookup)."""
    if _multi_store is None:
        raise RuntimeError(
            "MultiDataStore not loaded. The application did not start correctly."
        )
    return _multi_store


def get_search_index(
    format: str = FastAPIQuery(DEFAULT_FORMAT, pattern=_FORMAT_REGEX),
) -> TrigramIndex:
    """Provide the trigram search index for the requested format."""
    fmt = format.lower()
    if fmt in _search_indices:
        return _search_indices[fmt]
    # Fallback to default
    if DEFAULT_FORMAT in _search_indices:
        return _search_indices[DEFAULT_FORMAT]
    raise RuntimeError(
        "Search index not built. The application did not start correctly."
    )


# ── Lifespan (startup / shutdown) ─────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    On startup:
    - Loads all pipeline outputs from Parquet/CSV into memory.
    - Builds the trigram search index.
    - Wires dependency overrides into all routers.

    On shutdown:
    - (No cleanup needed — in-memory data is released with the process.)
    """
    global _multi_store, _search_indices, _store, _search_index

    print("=" * 60)
    print("  Cricket Metrics API — Starting up")
    print("=" * 60)

    t0 = time.perf_counter()

    # ── 1. Load pipeline outputs (all formats) ────────────────
    # If OUTPUT_DIR is explicitly set, load as single-format (legacy).
    # Otherwise, use load_all_data() to discover per-slice output folders.
    output_dir_env = os.environ.get("OUTPUT_DIR")
    if output_dir_env:
        # Legacy single-directory mode
        print(f"\n  OUTPUT_DIR set → single-format mode: {output_dir_env}")
        _multi_store = MultiDataStore()
        store = load_data(output_dir_env)
        if store.loaded:
            _multi_store.stores[DEFAULT_FORMAT] = store
    else:
        _multi_store = load_all_data()

    if not _multi_store.available_formats:
        print(
            "\n⚠️  WARNING: No datasets loaded.\n"
            "   The API will start but most endpoints will return empty results.\n"
            "   Ensure pipeline output folders exist under data/output/ (or set DATA_ROOT / OUTPUT_DIR).\n"
        )

    # Legacy aliases (point to default format for any code that uses them)
    _store = _multi_store.default

    # ── 2. Build search indices (one per format) ──────────────
    print("\nBuilding search indices...")
    for fmt in _multi_store.available_formats:
        print(f"  Building index for {fmt.upper()}...")
        _search_indices[fmt] = build_search_index(_multi_store.get(fmt))
    # Legacy alias
    _search_index = _search_indices.get(DEFAULT_FORMAT)

    # ── 3. Wire dependency overrides into routers ─────────────
    # Each router defines a placeholder dependency function that
    # raises RuntimeError. We override those with our real providers.

    # Search router
    search_router._get_search_index = get_search_index  # type: ignore[attr-defined]
    search_router.router.dependency_overrides_provider = app  # type: ignore[attr-defined]

    # Player router
    player_router._get_store = get_store  # type: ignore[attr-defined]
    player_router._get_search_index = get_search_index  # type: ignore[attr-defined]

    # Rankings router
    rankings_router._get_store = get_store  # type: ignore[attr-defined]

    # Matchups router
    matchups_router._get_store = get_store  # type: ignore[attr-defined]

    # Match scorecards router
    match_scorecards_router._get_store = get_store  # type: ignore[attr-defined]

    # Compare router (cross-format player resolution)
    compare_router._get_multi_store = get_multi_store  # type: ignore[attr-defined]

    # Venues router
    venues_router._get_store = get_store  # type: ignore[attr-defined]

    # Eras router
    eras_router._get_store = get_store  # type: ignore[attr-defined]

    # Team router
    team_router._get_store = get_store  # type: ignore[attr-defined]

    elapsed = time.perf_counter() - t0
    print(f"\n✅ Startup complete in {elapsed:.2f}s")
    print(f"   Available formats: {_multi_store.available_formats}")
    for fmt in _multi_store.available_formats:
        s = _multi_store.get(fmt)
        idx = _search_indices.get(fmt)
        idx_size = idx.size if idx else 0
        print(
            f"   [{fmt.upper()}] Batters: {len(s.bat_careers):,}  "
            f"Bowlers: {len(s.bowl_careers):,}  "
            f"Search: {idx_size:,}  "
            f"Matchups: {len(s.matchups):,}  "
            f"Venues: {len(s.venue):,}"
        )
    print("=" * 60)
    print()

    yield  # Application is running

    # Shutdown
    print("\nCricket Metrics API — Shutting down")
    _multi_store = None
    _search_indices.clear()
    _store = None
    _search_index = None


# ── FastAPI application ───────────────────────────────────────────

app = FastAPI(
    title="Cricket Metrics API",
    description=(
        "T20 Player Performance Profiling Engine — API.\n\n"
        "Serves player profiles, leaderboards, matchups, form time-series, "
        "similarity data, venue analysis, and more from pre-computed pipeline "
        "outputs. All data is read-only and loaded into memory at startup "
        "for sub-millisecond response times.\n\n"
        "Supports multiple data slices (men's/women's T20 and IPL) via `?format=`.\n\n"
        "**Data source:** Cricsheet international T20, IPL, and WPL ball-by-ball JSON, "
        "processed through the Cricket Metrics pipeline."
    ),
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────
# Allow the React dev server (Vite), localhost, and production frontend origins.
# Set CORS_ORIGINS (comma-separated) in production to add your Vercel/frontend URL.
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
# FastAPI's dependency injection works by calling the function passed to
# Depends(). We need to replace the placeholder functions in each router
# module with our real providers. We do this by overriding the module-level
# functions that the routers reference.
#
# This approach avoids the need for a global `app.dependency_overrides`
# dict, which doesn't work well with module-level function references.
# Instead, we directly replace the function objects in the router modules.


app.dependency_overrides[search_router._get_search_index] = get_search_index
app.dependency_overrides[player_router._get_store] = get_store
app.dependency_overrides[player_router._get_search_index] = get_search_index
app.dependency_overrides[rankings_router._get_store] = get_store
app.dependency_overrides[matchups_router._get_store] = get_store
app.dependency_overrides[match_scorecards_router._get_store] = get_store
app.dependency_overrides[compare_router._get_multi_store] = get_multi_store
app.dependency_overrides[venues_router._get_store] = get_store
app.dependency_overrides[eras_router._get_store] = get_store
app.dependency_overrides[team_router._get_store] = get_store


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
    """Health check endpoint.

    Returns ``{"status": "ok"}`` if the application is running and
    data is loaded. Returns ``{"status": "degraded"}`` if the output
    data could not be loaded.
    """
    if _multi_store is not None and _multi_store.available_formats:
        return {
            "status": "ok",
            "formats": _multi_store.available_formats,
        }
    return {"status": "degraded", "reason": "Data not loaded"}


@app.get("/api/formats", tags=["meta"])
async def list_formats():
    """Return loaded dataset slice keys (e.g. mens_t20i, womens_t20i, womens_ipl).

    The frontend uses this to know which gender/competition options to show.
    """
    if _multi_store is None:
        return {"formats": [], "default": DEFAULT_FORMAT}
    return {
        "formats": _multi_store.available_formats,
        "default": _api_default_format(_multi_store),
    }


@app.get("/api/meta", response_model=MetaResponse, tags=["meta"])
async def api_metadata(
    format: str = FastAPIQuery(DEFAULT_FORMAT, pattern=_FORMAT_REGEX),
):
    """Return API metadata and dataset summary for a given format.

    Useful for the frontend to display dataset info (total players,
    countries, archetypes) and to verify the backend is connected
    and serving data.
    """
    if _multi_store is None:
        return MetaResponse(status="not_loaded")

    store = _multi_store.get(format)
    idx = _search_indices.get(format.lower())

    if not store.loaded or idx is None:
        return MetaResponse(status="not_loaded")

    latest_raw = match_scorecards_router.compute_latest_scorecard_summary(store)
    latest_sc = (
        LatestScorecardSummary(**latest_raw) if latest_raw is not None else None
    )

    tiers: T20ITeamTiers | None = None
    if is_t20_international_format(format):
        main_l, assoc_l, top_n = get_t20i_tier_config()
        if main_l or assoc_l:
            tiers = T20ITeamTiers(top_n=top_n, main=main_l, associates=assoc_l)

    return MetaResponse(
        status="ok",
        total_batters=len(store.bat_careers),
        total_bowlers=len(store.bowl_careers),
        total_matchups=len(store.matchups),
        total_venues=len(store.venue),
        countries=idx.all_countries(),
        archetypes=idx.all_archetypes(),
        data_through_date=max_last_match_date_iso(store),
        latest_scorecard=latest_sc,
        t20i_team_tiers=tiers,
    )


# ── Error handlers ────────────────────────────────────────────────


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 handler with a helpful message."""
    return JSONResponse(
        status_code=404,
        content={
            "detail": str(exc.detail) if hasattr(exc, "detail") else "Not found",
            "hint": (
                "Check the player ID or endpoint path. "
                "Use /api/search to find valid player IDs."
            ),
        },
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Custom 500 handler that avoids leaking stack traces."""
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
    print(f"  Output dir: {os.environ.get('OUTPUT_DIR', '(default)')}")
    print()

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
