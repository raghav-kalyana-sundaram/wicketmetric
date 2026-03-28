"""
Venues router — /api/venues endpoints.

Provides:
- GET /api/venues              → All venue baselines (difficulty, par SR, etc.)
- GET /api/venues/{venue_name} → Detailed breakdown for a single venue
- GET /api/venues/{venue_name}/players → Player performance at a specific venue
- GET /api/player/{id}/venues  → A player's venue-by-venue splits
"""

from __future__ import annotations

import math
import urllib.parse
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query
from schemas import VenueBaseline, VenueListResponse
from venue_analytics import (
    attach_global_venue_difficulty_index,
    build_venue_matches,
    build_venue_performances,
    build_venue_profile,
    build_venue_similar,
    build_venue_teams,
    build_venue_trends,
    filter_bat_by_venue,
    filter_bowl_by_venue,
    pick_venue_col,
    resolve_venue_row,
)

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["venues"])


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise RuntimeError("DataStore not initialised")


# ── Helpers ───────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
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


def _safe_int(v: Any) -> int:
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


def _safe_str(v: Any, default: str = "") -> str:
    """Convert to string, returning default for NaN/None."""
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s


def _get_val(row: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from a pandas Series or dict."""
    try:
        if hasattr(row, "get"):
            return row.get(key, default)
        return getattr(row, key, default)
    except Exception:
        return default


def _series_mean_numeric(s: "pd.Series") -> float:
    """Pandas groupby-agg helper: mean of numeric values, else NaN."""
    import pandas as pd

    v = pd.to_numeric(s, errors="coerce")
    m = v.mean()
    return float(m) if pd.notna(m) else float("nan")


def _venue_row_to_baseline(row: Any) -> VenueBaseline:
    """Convert a venue baselines DataFrame row to a VenueBaseline schema."""
    return VenueBaseline(
        venue=_safe_str(_get_val(row, "venue")),
        matches=_safe_int(_get_val(row, "venue_matches")),
        avg_par_sr=_safe_float(_get_val(row, "venue_avg_par_sr")),
        boundary_rate=_safe_float(_get_val(row, "venue_avg_boundary_rate")),
        dot_pct=_safe_float(_get_val(row, "venue_avg_dot_pct")),
        difficulty_score=_safe_float(_get_val(row, "venue_difficulty_index")),
    )


def _decode_venue_name(venue_name: str) -> str:
    """Decode a URL-encoded venue name and normalise whitespace."""
    decoded = urllib.parse.unquote(venue_name).strip()
    return decoded


# ── Route: GET /api/venues ────────────────────────────────────────


@router.get("/venues", response_model=VenueListResponse)
async def list_venues(
    sort: str = Query(
        "venue_difficulty",
        description=(
            "Column to sort by. Options: venue_difficulty, venue_matches, "
            "venue_avg_par_sr, venue_avg_boundary_rate, venue_avg_dot_pct, venue"
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    min_matches: int = Query(
        10,
        ge=0,
        description="Minimum number of matches played at the venue (default 10)",
    ),
    store: "DataStore" = Depends(_get_store),
) -> VenueListResponse:
    """Return all venue baselines with difficulty scores.

    Each venue includes:
    - **difficulty_score**: 0–100 index (higher = harder conditions). Percentile
      rank of the internal difficulty metric across all venues in the dataset.
    - **avg_par_sr**: average par strike rate at this venue.
    - **boundary_rate**: average boundary rate (boundaries / total balls).
    - **dot_pct**: average dot ball percentage.
    - **matches**: number of T20I matches played at this venue.

    Sorted by difficulty score descending by default (hardest venues first).
    Use ``order=asc`` for easiest-first.

    **Examples**:
    - ``/api/venues`` — all venues sorted by difficulty (hardest first)
    - ``/api/venues?sort=venue_matches&order=desc`` — most-used venues first
    - ``/api/venues?min_matches=10&sort=venue_avg_par_sr&order=asc`` — lowest par SR venues with 10+ matches
    """
    if store.venue.empty:
        return VenueListResponse(venues=[])

    df = store.venue.copy()

    # Apply minimum matches filter
    if min_matches > 0 and "venue_matches" in df.columns:
        df = df.loc[df["venue_matches"] >= min_matches]

    if df.empty:
        return VenueListResponse(venues=[])

    # Human-facing difficulty 0–100 (sorting still uses z-style venue_difficulty)
    idx_tbl = attach_global_venue_difficulty_index(store.venue)[
        ["venue", "venue_difficulty_index"]
    ]
    df = df.merge(idx_tbl, on="venue", how="left")

    # Sort
    sort_col = sort.strip()
    valid_sort_cols = {
        "venue_difficulty",
        "venue_matches",
        "venue_avg_par_sr",
        "venue_avg_boundary_rate",
        "venue_avg_dot_pct",
        "venue",
        "venue_difficulty_raw",
        "venue_par_std",
    }
    if sort_col not in valid_sort_cols:
        if sort_col in df.columns:
            pass  # Allow any column that exists in the DataFrame
        else:
            sort_col = "venue_difficulty"

    ascending = order.lower() == "asc"
    if sort_col in df.columns:
        df = df.sort_values(sort_col, ascending=ascending, na_position="last")
    else:
        df = df.sort_values("venue_difficulty", ascending=False, na_position="last")

    venues: list[VenueBaseline] = []
    for _, row in df.iterrows():
        venues.append(_venue_row_to_baseline(row))

    return VenueListResponse(venues=venues)


# ── Route: GET /api/venues/{venue_name} ───────────────────────────


@router.get("/venues/detail")
async def venue_detail(
    venue: str = Query(
        ...,
        description=(
            "Venue name (URL-encoded if necessary). "
            "Use the exact venue name as returned by /api/venues."
        ),
    ),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Return detailed information for a single venue.

    Includes the venue baseline (difficulty, par SR, etc.) plus
    aggregate match statistics.

    **Example**: ``/api/venues/detail?venue=Melbourne+Cricket+Ground``

    Raises 404 if the venue is not found.
    """
    if store.venue.empty:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")

    venue_decoded = _decode_venue_name(venue)

    # Case-insensitive match
    mask = store.venue["venue"].str.lower() == venue_decoded.lower()
    matches = store.venue.loc[mask]

    if matches.empty:
        # Try partial match
        mask_partial = (
            store.venue["venue"]
            .str.lower()
            .str.contains(venue_decoded.lower(), na=False)
        )
        matches = store.venue.loc[mask_partial]

    if matches.empty:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")

    row = matches.iloc[0]

    indexed = attach_global_venue_difficulty_index(store.venue)
    vnm = _safe_str(_get_val(row, "venue"))
    d_idx = None
    if vnm and not indexed.empty:
        hit = indexed[indexed["venue"].astype(str) == vnm]
        if not hit.empty:
            d_idx = _safe_float(_get_val(hit.iloc[0], "venue_difficulty_index"))

    return {
        "venue": vnm,
        "matches": _safe_int(_get_val(row, "venue_matches")),
        "avg_par_sr": _safe_float(_get_val(row, "venue_avg_par_sr")),
        "par_sr_std": _safe_float(_get_val(row, "venue_par_std")),
        "boundary_rate": _safe_float(_get_val(row, "venue_avg_boundary_rate")),
        "dot_pct": _safe_float(_get_val(row, "venue_avg_dot_pct")),
        "difficulty_raw": _safe_float(_get_val(row, "venue_difficulty_raw")),
        "difficulty_score": d_idx,
    }


# ── Route: GET /api/venues/profile ────────────────────────────────


@router.get("/venues/profile")
async def venue_profile(
    venue: str = Query(..., description="Venue name (URL-encoded)"),
    exact: bool = Query(
        False,
        description="If true, require exact match to a baseline venue name",
    ),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Rich venue profile: vs world, chase/defend, phase breakdown, sample sizes."""
    out = build_venue_profile(store, _decode_venue_name(venue), exact=exact)
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


@router.get("/venues/trends")
async def venue_trends(
    venue: str = Query(...),
    bucket: str = Query(
        "rolling_3_match",
        description="rolling_3_match (default): rolling 3-match averages by date; year or season for yearly buckets",
    ),
    exact: bool = Query(False),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    out = build_venue_trends(
        store, _decode_venue_name(venue), exact=exact, bucket=bucket
    )
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


@router.get("/venues/teams")
async def venue_teams(
    venue: str = Query(...),
    exact: bool = Query(False),
    min_matches: int = Query(2, ge=1),
    sort: str = Query("win_pct"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    out = build_venue_teams(
        store,
        _decode_venue_name(venue),
        exact=exact,
        min_matches=min_matches,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
    )
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


@router.get("/venues/similar")
async def venue_similar(
    venue: str = Query(...),
    exact: bool = Query(False),
    k: int = Query(8, ge=1, le=30),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    out = build_venue_similar(store, _decode_venue_name(venue), exact=exact, k=k)
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


@router.get("/venues/matches")
async def venue_match_list(
    venue: str = Query(...),
    exact: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Paginated matches played at this venue."""
    out = build_venue_matches(
        store,
        _decode_venue_name(venue),
        exact=exact,
        page=page,
        per_page=per_page,
    )
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


@router.get("/venues/performances")
async def venue_performances(
    venue: str = Query(...),
    role: str = Query("bat", description="bat or bowl"),
    sort: str = Query(
        "bat_impact",
        description=(
            "bat: bat_impact, total_impact, bowl_impact, runs, acc_leveraged_rva, … "
            "bowl: bowl_impact, total_impact, bat_impact, wickets, economy, …"
        ),
    ),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    min_balls: int = Query(5, ge=1, description="Min balls faced (bat) or min legal balls (bowl, at least 6)"),
    exact: bool = Query(False),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    out = build_venue_performances(
        store,
        _decode_venue_name(venue),
        exact=exact,
        role=role,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
        min_balls=min_balls,
    )
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


# ── Route: GET /api/venues/players ────────────────────────────────


@router.get("/venues/players")
async def players_at_venue(
    venue: str = Query(
        ...,
        description="Venue name (URL-encoded if necessary)",
    ),
    role: str = Query(
        "bat",
        description="Role: 'bat' for batting stats, 'bowl' for bowling stats",
    ),
    min_innings: int = Query(
        2,
        ge=1,
        description="Minimum innings/spells at this venue",
    ),
    sort: str = Query(
        "venue_overall_score",
        description=(
            "Batting: venue_overall_score, venue_score_acceleration, venue_score_power, "
            "venue_score_control, runs, innings, sr, avg, overall_score (career), … "
            "Bowling: venue_overall_score, venue_score_accuracy, venue_score_control, "
            "venue_score_threat, wickets, spells, economy, overall_score (career), …"
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    exact: bool = Query(
        False,
        description="Match venue string exactly (recommended when picking from list)",
    ),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Return player performance at a specific venue.

    Aggregates all innings/spells played at the given venue per player,
    then returns sorted, paginated results.

    For **batting** (role=bat): returns runs, balls, SR, innings count,
    fours, sixes per batter at this venue.

    For **bowling** (role=bowl): returns wickets, runs conceded, economy,
    overs bowled, spells per bowler at this venue.

    **Examples**:
    - ``/api/venues/players?venue=Melbourne+Cricket+Ground&role=bat&sort=runs&order=desc``
    - ``/api/venues/players?venue=Dubai&role=bowl&sort=wickets&order=desc&min_innings=3``

    Note: This endpoint requires that the innings/spells detail DataFrames
    include a 'venue' column. If venue data is not available at the innings
    level, returns an empty result with a message.
    """
    venue_decoded = _decode_venue_name(venue)

    if role == "bowl":
        return _players_at_venue_bowling(
            store, venue_decoded, min_innings, sort, order, page, per_page, exact
        )
    else:
        return _players_at_venue_batting(
            store, venue_decoded, min_innings, sort, order, page, per_page, exact
        )


def _players_at_venue_batting(
    store: "DataStore",
    venue: str,
    min_innings: int,
    sort: str,
    order: str,
    page: int,
    per_page: int,
    exact: bool,
) -> dict:
    """Aggregate batting stats per player at a given venue + career overlay."""
    if store.bat_innings.empty:
        return {
            "venue": venue,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "message": "No innings data available.",
        }

    row, canonical = resolve_venue_row(store, venue, exact)
    if row is None:
        canonical = venue.strip()
    venue_innings = filter_bat_by_venue(store.bat_innings, canonical, exact=exact)

    if pick_venue_col(store.bat_innings) is None:
        return {
            "venue": canonical,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "message": (
                "Venue column not found in innings detail data. "
                "Re-run the pipeline with venue enrichment."
            ),
        }

    if venue_innings.empty:
        return {
            "venue": canonical,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    agg_kw: dict = {
        "innings": ("runs", "count"),
        "runs": ("runs", "sum"),
        "balls_faced": ("balls_faced", "sum"),
        "fours": ("fours", "sum"),
        "sixes": ("sixes", "sum"),
        "dots": ("dots", "sum"),
    }
    if "date" in venue_innings.columns:
        agg_kw["last_played_at_venue"] = ("date", "max")

    for src, dest in (
        ("score_acceleration", "venue_score_acceleration"),
        ("score_power", "venue_score_power"),
        ("score_control", "venue_score_control"),
        ("overall_score", "venue_overall_score"),
    ):
        if src in venue_innings.columns:
            agg_kw[dest] = (src, _series_mean_numeric)

    agg = (
        venue_innings.groupby(["batter_id", "batter"], observed=True)
        .agg(**agg_kw)
        .reset_index()
    )

    balls = pd.to_numeric(agg["balls_faced"], errors="coerce").fillna(0)
    runs = pd.to_numeric(agg["runs"], errors="coerce").fillna(0)
    dots = pd.to_numeric(agg["dots"], errors="coerce").fillna(0)
    fours = pd.to_numeric(agg["fours"], errors="coerce").fillna(0)
    sixes = pd.to_numeric(agg["sixes"], errors="coerce").fillna(0)
    agg["sr"] = np.where(balls > 0, (runs / balls * 100.0).round(1), np.nan)
    agg["avg"] = (runs / np.maximum(agg["innings"], 1)).round(1)
    agg["dot_pct"] = np.where(balls > 0, (dots / balls).round(4), np.nan)
    bruns = fours * 4 + sixes * 6
    agg["boundary_pct"] = np.where(runs > 0, (bruns / runs).round(4), np.nan)
    agg["six_rate"] = np.where(balls > 0, (sixes / balls).round(4), np.nan)

    agg = agg.loc[agg["innings"] >= min_innings]
    total = len(agg)
    if total == 0:
        return {
            "venue": canonical,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Career join
    if not store.bat_careers.empty and "batter_id" in store.bat_careers.columns:
        car = store.bat_careers.copy()
        want = [
            c
            for c in (
                "batter_id",
                "career_sr",
                "career_avg",
                "career_dot_pct",
                "total_runs",
                "total_balls",
                "total_fours",
                "total_sixes",
                "country",
                "overall_score",
                "overall_grade",
                "score_acceleration",
                "score_power",
                "score_control",
            )
            if c in car.columns
        ]
        if want:
            car = car[want].drop_duplicates(subset=["batter_id"], keep="first")
            car["batter_id"] = car["batter_id"].astype(str)
            agg["batter_id"] = agg["batter_id"].astype(str)
            agg = agg.merge(car, on="batter_id", how="left", suffixes=("", "_c"))
            tr = pd.to_numeric(agg.get("total_runs"), errors="coerce").fillna(0)
            tb = pd.to_numeric(agg.get("total_balls"), errors="coerce").fillna(0)
            tf = pd.to_numeric(agg.get("total_fours"), errors="coerce").fillna(0)
            ts = pd.to_numeric(agg.get("total_sixes"), errors="coerce").fillna(0)
            agg["career_boundary_pct"] = np.where(
                tr > 0, ((tf * 4 + ts * 6) / tr).round(4), np.nan
            )
            agg["career_six_rate"] = np.where(tb > 0, (ts / tb).round(4), np.nan)
            if "career_sr" in agg.columns:
                agg["sr_delta"] = agg["sr"] - pd.to_numeric(
                    agg["career_sr"], errors="coerce"
                )
            else:
                agg["sr_delta"] = np.nan
            if "career_avg" in agg.columns:
                agg["avg_delta"] = agg["avg"] - pd.to_numeric(
                    agg["career_avg"], errors="coerce"
                )
            else:
                agg["avg_delta"] = np.nan
            if "career_dot_pct" in agg.columns:
                agg["dot_pct_delta"] = agg["dot_pct"] - pd.to_numeric(
                    agg["career_dot_pct"], errors="coerce"
                )
            else:
                agg["dot_pct_delta"] = np.nan
            agg["boundary_pct_delta"] = agg["boundary_pct"] - pd.to_numeric(
                agg["career_boundary_pct"], errors="coerce"
            )
            agg["six_rate_delta"] = agg["six_rate"] - pd.to_numeric(
                agg["career_six_rate"], errors="coerce"
            )

    alias = {
        "innings_count": "innings",
        "total_runs": "runs",
        "score_1": "venue_score_acceleration",
        "score_2": "venue_score_power",
        "score_3": "venue_score_control",
    }
    sort_col = alias.get(sort.strip(), sort.strip())
    if sort_col not in agg.columns:
        sort_col = (
            "venue_overall_score"
            if "venue_overall_score" in agg.columns
            else "runs"
        )
    ascending = order.lower() == "asc"
    agg = agg.sort_values(sort_col, ascending=ascending, na_position="last")

    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_df = agg.iloc[start : start + per_page]

    players: list[dict] = []
    for _, row in page_df.iterrows():
        lp = row.get("last_played_at_venue")
        lp_out = None
        if lp is not None and hasattr(lp, "isoformat"):
            lp_out = lp.isoformat()[:10]
        elif lp is not None:
            lp_out = str(lp)[:10]
        players.append(
            {
                "id": _safe_str(_get_val(row, "batter_id")),
                "name": _safe_str(_get_val(row, "batter")),
                "country": _safe_str(_get_val(row, "country"), ""),
                "innings": _safe_int(_get_val(row, "innings")),
                "runs": _safe_int(_get_val(row, "runs")),
                "balls_faced": _safe_int(_get_val(row, "balls_faced")),
                "sr": _safe_float(_get_val(row, "sr")),
                "avg": _safe_float(_get_val(row, "avg")),
                "dot_pct": _safe_float(_get_val(row, "dot_pct")),
                "boundary_pct": _safe_float(_get_val(row, "boundary_pct")),
                "six_rate": _safe_float(_get_val(row, "six_rate")),
                "fours": _safe_int(_get_val(row, "fours")),
                "sixes": _safe_int(_get_val(row, "sixes")),
                "dots": _safe_int(_get_val(row, "dots")),
                "last_played_at_venue": lp_out,
                "career_sr": _safe_float(_get_val(row, "career_sr")),
                "career_avg": _safe_float(_get_val(row, "career_avg")),
                "career_dot_pct": _safe_float(_get_val(row, "career_dot_pct")),
                "career_boundary_pct": _safe_float(_get_val(row, "career_boundary_pct")),
                "career_six_rate": _safe_float(_get_val(row, "career_six_rate")),
                "sr_delta": _safe_float(_get_val(row, "sr_delta")),
                "avg_delta": _safe_float(_get_val(row, "avg_delta")),
                "dot_pct_delta": _safe_float(_get_val(row, "dot_pct_delta")),
                "boundary_pct_delta": _safe_float(_get_val(row, "boundary_pct_delta")),
                "six_rate_delta": _safe_float(_get_val(row, "six_rate_delta")),
                "overall_score": _safe_float(_get_val(row, "overall_score")),
                "overall_grade": _safe_str(_get_val(row, "overall_grade"), "D"),
                "score_acceleration": _safe_float(_get_val(row, "score_acceleration")),
                "score_power": _safe_float(_get_val(row, "score_power")),
                "score_control": _safe_float(_get_val(row, "score_control")),
                "venue_overall_score": _safe_float(_get_val(row, "venue_overall_score")),
                "venue_score_acceleration": _safe_float(
                    _get_val(row, "venue_score_acceleration")
                ),
                "venue_score_power": _safe_float(_get_val(row, "venue_score_power")),
                "venue_score_control": _safe_float(_get_val(row, "venue_score_control")),
            }
        )

    return {
        "venue": canonical,
        "role": "bat",
        "players": players,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def _players_at_venue_bowling(
    store: "DataStore",
    venue: str,
    min_innings: int,
    sort: str,
    order: str,
    page: int,
    per_page: int,
    exact: bool,
) -> dict:
    """Aggregate bowling stats per player at a given venue + career overlay."""
    if store.bowl_spells.empty:
        return {
            "venue": venue,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "message": "No spells data available.",
        }

    row, canonical = resolve_venue_row(store, venue, exact)
    if row is None:
        canonical = venue.strip()

    if pick_venue_col(store.bowl_spells) is None:
        return {
            "venue": canonical,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "message": "Venue column not found in spells detail data.",
        }

    venue_spells = filter_bowl_by_venue(store.bowl_spells, canonical, exact=exact)

    if venue_spells.empty:
        return {
            "venue": canonical,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    dots_col = "dots_bowler" if "dots_bowler" in venue_spells.columns else None
    agg_kw: dict = {
        "spells": ("wickets", "count"),
        "wickets": ("wickets", "sum"),
        "runs_conceded": ("runs_conceded", "sum"),
        "legal_balls": ("legal_balls", "sum"),
        "fours_conceded": ("fours_conceded", "sum"),
        "sixes_conceded": ("sixes_conceded", "sum"),
    }
    if dots_col:
        agg_kw["dots_bowler"] = (dots_col, "sum")
    if "date" in venue_spells.columns:
        agg_kw["last_played_at_venue"] = ("date", "max")

    for src, dest in (
        ("score_accuracy", "venue_score_accuracy"),
        ("score_control", "venue_score_control"),
        ("score_threat", "venue_score_threat"),
        ("overall_score", "venue_overall_score"),
    ):
        if src in venue_spells.columns:
            agg_kw[dest] = (src, _series_mean_numeric)

    agg = (
        venue_spells.groupby(["bowler_id", "bowler"], observed=True)
        .agg(**agg_kw)
        .reset_index()
    )

    lb = pd.to_numeric(agg["legal_balls"], errors="coerce").fillna(0)
    rc = pd.to_numeric(agg["runs_conceded"], errors="coerce").fillna(0)
    wk = pd.to_numeric(agg["wickets"], errors="coerce").fillna(0)
    overs = lb / 6.0
    agg["overs_bowled"] = overs.round(1)
    agg["economy"] = np.where(overs > 0, (rc / overs).round(2), np.nan)
    agg["strike_rate_bowl"] = np.where(wk > 0, (lb / wk).round(1), np.nan)
    if dots_col:
        db = pd.to_numeric(agg["dots_bowler"], errors="coerce").fillna(0)
        agg["dot_pct"] = np.where(lb > 0, (db / lb).round(4), np.nan)
    else:
        agg["dot_pct"] = np.nan

    agg = agg.loc[agg["spells"] >= min_innings]
    total = len(agg)
    if total == 0:
        return {
            "venue": canonical,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    if not store.bowl_careers.empty and "bowler_id" in store.bowl_careers.columns:
        car = store.bowl_careers.copy()
        want = [
            c
            for c in (
                "bowler_id",
                "career_economy",
                "career_sr_bowl",
                "career_dot_pct",
                "country",
                "overall_score",
                "overall_grade",
                "score_accuracy",
                "score_control",
                "score_threat",
            )
            if c in car.columns
        ]
        if want:
            car = car[want].copy()
            car["bowler_id"] = car["bowler_id"].astype(str)
            agg["bowler_id"] = agg["bowler_id"].astype(str)
            agg = agg.merge(car, on="bowler_id", how="left")
            if "career_economy" in agg.columns:
                agg["economy_delta"] = agg["economy"] - pd.to_numeric(
                    agg["career_economy"], errors="coerce"
                )
            else:
                agg["economy_delta"] = np.nan
            if "career_sr_bowl" in agg.columns:
                agg["strike_rate_delta"] = agg["strike_rate_bowl"] - pd.to_numeric(
                    agg["career_sr_bowl"], errors="coerce"
                )
            else:
                agg["strike_rate_delta"] = np.nan
            if "career_dot_pct" in agg.columns:
                agg["dot_pct_delta"] = agg["dot_pct"] - pd.to_numeric(
                    agg["career_dot_pct"], errors="coerce"
                )
            else:
                agg["dot_pct_delta"] = np.nan

    alias = {
        "innings_count": "spells",
        "total_runs": "wickets",
        "score_1": "venue_score_accuracy",
        "score_2": "venue_score_control",
        "score_3": "venue_score_threat",
    }
    sort_col = alias.get(sort.strip(), sort.strip())
    if sort_col == "strike_rate":
        sort_col = "strike_rate_bowl"
    if sort_col not in agg.columns:
        sort_col = (
            "venue_overall_score"
            if "venue_overall_score" in agg.columns
            else "wickets"
        )
    ascending = order.lower() == "asc"
    agg = agg.sort_values(sort_col, ascending=ascending, na_position="last")

    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_df = agg.iloc[start : start + per_page]

    players: list[dict] = []
    for _, row in page_df.iterrows():
        lp = row.get("last_played_at_venue")
        lp_out = lp.isoformat()[:10] if lp is not None and hasattr(lp, "isoformat") else None
        if lp_out is None and lp is not None:
            lp_out = str(lp)[:10]
        players.append(
            {
                "id": _safe_str(_get_val(row, "bowler_id")),
                "name": _safe_str(_get_val(row, "bowler")),
                "country": _safe_str(_get_val(row, "country"), ""),
                "spells": _safe_int(_get_val(row, "spells")),
                "wickets": _safe_int(_get_val(row, "wickets")),
                "runs_conceded": _safe_int(_get_val(row, "runs_conceded")),
                "overs_bowled": _safe_float(_get_val(row, "overs_bowled")),
                "legal_balls": _safe_int(_get_val(row, "legal_balls")),
                "economy": _safe_float(_get_val(row, "economy")),
                "strike_rate_bowl": _safe_float(_get_val(row, "strike_rate_bowl")),
                "dot_pct": _safe_float(_get_val(row, "dot_pct")),
                "fours_conceded": _safe_int(_get_val(row, "fours_conceded")),
                "sixes_conceded": _safe_int(_get_val(row, "sixes_conceded")),
                "last_played_at_venue": lp_out,
                "career_economy": _safe_float(_get_val(row, "career_economy")),
                "career_sr_bowl": _safe_float(_get_val(row, "career_sr_bowl")),
                "career_dot_pct": _safe_float(_get_val(row, "career_dot_pct")),
                "economy_delta": _safe_float(_get_val(row, "economy_delta")),
                "strike_rate_delta": _safe_float(_get_val(row, "strike_rate_delta")),
                "dot_pct_delta": _safe_float(_get_val(row, "dot_pct_delta")),
                "overall_score": _safe_float(_get_val(row, "overall_score")),
                "overall_grade": _safe_str(_get_val(row, "overall_grade"), "D"),
                "score_accuracy": _safe_float(_get_val(row, "score_accuracy")),
                "score_control": _safe_float(_get_val(row, "score_control")),
                "score_threat": _safe_float(_get_val(row, "score_threat")),
                "venue_overall_score": _safe_float(_get_val(row, "venue_overall_score")),
                "venue_score_accuracy": _safe_float(_get_val(row, "venue_score_accuracy")),
                "venue_score_control": _safe_float(_get_val(row, "venue_score_control")),
                "venue_score_threat": _safe_float(_get_val(row, "venue_score_threat")),
            }
        )

    return {
        "venue": canonical,
        "role": "bowl",
        "players": players,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Route: GET /api/venues/summary ────────────────────────────────


@router.get("/venues/summary")
async def venues_summary(
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Return a high-level summary of venue data.

    Includes:
    - Total number of venues
    - Hardest / easiest venue
    - Most-used venue (by match count)
    - Average difficulty across all venues
    - Difficulty distribution buckets (for histogram rendering)

    Useful for the Venue Analysis page header/overview section.
    """
    if store.venue.empty:
        return {
            "total_venues": 0,
            "hardest_venue": None,
            "easiest_venue": None,
            "most_used_venue": None,
            "avg_difficulty": None,
            "difficulty_distribution": [],
        }

    df = attach_global_venue_difficulty_index(store.venue.copy())

    total_venues = len(df)

    # Hardest venue (highest underlying z-difficulty; display 0–100 index)
    hardest_row = None
    if "venue_difficulty" in df.columns:
        hardest_idx = df["venue_difficulty"].idxmax()
        if hardest_idx is not None:
            hardest_row = df.loc[hardest_idx]

    # Easiest venue (lowest z-difficulty)
    easiest_row = None
    if "venue_difficulty" in df.columns:
        easiest_idx = df["venue_difficulty"].idxmin()
        if easiest_idx is not None:
            easiest_row = df.loc[easiest_idx]

    # Most used venue (highest match count)
    most_used_row = None
    if "venue_matches" in df.columns:
        most_used_idx = df["venue_matches"].idxmax()
        if most_used_idx is not None:
            most_used_row = df.loc[most_used_idx]

    # Average difficulty (0–100 scale)
    avg_difficulty = None
    if "venue_difficulty_index" in df.columns:
        avg_difficulty = _safe_float(
            pd.to_numeric(df["venue_difficulty_index"], errors="coerce").mean()
        )

    # Difficulty distribution: fixed 0–100 bins for the index scale
    distribution: list[dict] = []
    if "venue_difficulty_index" in df.columns:
        difficulty_vals = pd.to_numeric(
            df["venue_difficulty_index"], errors="coerce"
        ).dropna()
        if not difficulty_vals.empty:
            edges = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
            for i in range(len(edges) - 1):
                low = edges[i]
                high = edges[i + 1]
                if i < len(edges) - 2:
                    count = int(
                        ((difficulty_vals >= low) & (difficulty_vals < high)).sum()
                    )
                else:
                    count = int(
                        ((difficulty_vals >= low) & (difficulty_vals <= high)).sum()
                    )
                distribution.append(
                    {
                        "bin_low": round(low, 1),
                        "bin_high": round(high, 1),
                        "count": count,
                    }
                )

    return {
        "total_venues": total_venues,
        "hardest_venue": (
            {
                "venue": _safe_str(_get_val(hardest_row, "venue")),
                "difficulty": _safe_float(
                    _get_val(hardest_row, "venue_difficulty_index")
                ),
                "matches": _safe_int(_get_val(hardest_row, "venue_matches")),
            }
            if hardest_row is not None
            else None
        ),
        "easiest_venue": (
            {
                "venue": _safe_str(_get_val(easiest_row, "venue")),
                "difficulty": _safe_float(
                    _get_val(easiest_row, "venue_difficulty_index")
                ),
                "matches": _safe_int(_get_val(easiest_row, "venue_matches")),
            }
            if easiest_row is not None
            else None
        ),
        "most_used_venue": (
            {
                "venue": _safe_str(_get_val(most_used_row, "venue")),
                "matches": _safe_int(_get_val(most_used_row, "venue_matches")),
                "difficulty": _safe_float(
                    _get_val(most_used_row, "venue_difficulty_index")
                ),
            }
            if most_used_row is not None
            else None
        ),
        "avg_difficulty": avg_difficulty,
        "difficulty_distribution": distribution,
    }
