"""
Venues router — /api/venues endpoints (DuckDB backend).

Provides:
- GET /api/venues              → All venue baselines (difficulty, par SR, etc.)
- GET /api/venues/summary      → Venue summary stats
- GET /api/venues/detail       → Single venue detail
- GET /api/venues/profile      → Rich venue profile
- GET /api/venues/trends       → Venue trends over time
- GET /api/venues/teams        → Team records at a venue
- GET /api/venues/similar      → Similar venues
- GET /api/venues/matches      → Paginated match list at venue
- GET /api/venues/performances → Player performances (match-impact) at venue
- GET /api/venues/players      → Aggregated player stats at venue
- GET /api/player/{id}/venues  → Player's venue-by-venue splits
"""

from __future__ import annotations

import math
import urllib.parse
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from db import safe_float, safe_int, safe_str, safe_fmt, query_all, query_count
from schemas import VenueBaseline, VenueListResponse
from venue_analytics import (
    build_venue_matches,
    build_venue_performances,
    build_venue_profile,
    build_venue_similar,
    build_venue_teams,
    build_venue_trends,
    players_at_venue_batting,
    players_at_venue_bowling,
    resolve_venue_row,
)

router = APIRouter(prefix="/api", tags=["venues"])


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


# ── Helpers ───────────────────────────────────────────────────────


def _decode_venue_name(venue_name: str) -> str:
    """Decode a URL-encoded venue name and normalise whitespace."""
    return urllib.parse.unquote(venue_name).strip()


def _venue_row_to_baseline(row: dict) -> VenueBaseline:
    """Convert a venue dict row to a VenueBaseline schema."""
    return VenueBaseline(
        venue=safe_str(row.get("venue")),
        matches=safe_int(row.get("venue_matches")),
        avg_par_sr=safe_float(row.get("venue_avg_par_sr")),
        boundary_rate=safe_float(row.get("venue_avg_boundary_rate")),
        dot_pct=safe_float(row.get("venue_avg_dot_pct")),
        difficulty_score=safe_float(row.get("venue_difficulty_index")),
    )


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
    store=Depends(_get_store),
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
    conn, fmt = store
    f = safe_fmt(fmt)

    try:
        rows = query_all(conn, f"SELECT * FROM {f}.venue_with_difficulty ORDER BY venue")
    except duckdb.CatalogException:
        rows = query_all(conn, f"SELECT * FROM {f}.venue ORDER BY venue")

    if not rows:
        return VenueListResponse(venues=[])

    if min_matches > 0:
        rows = [r for r in rows if safe_int(r.get("venue_matches")) >= min_matches]

    if not rows:
        return VenueListResponse(venues=[])

    valid_sort_cols = {
        "venue_difficulty",
        "venue_matches",
        "venue_avg_par_sr",
        "venue_avg_boundary_rate",
        "venue_avg_dot_pct",
        "venue",
        "venue_difficulty_raw",
        "venue_par_std",
        "venue_difficulty_index",
    }
    sort_col = sort.strip()
    if sort_col not in valid_sort_cols and not any(sort_col in r for r in rows):
        sort_col = "venue_difficulty"

    ascending = order.lower() == "asc"

    def _sort_key(r: dict) -> tuple:
        v = r.get(sort_col)
        if v is None:
            return (1, 0)
        if isinstance(v, str):
            return (0, v.lower() if ascending else v.lower())
        return (0, v)

    rows.sort(key=_sort_key, reverse=not ascending)

    venues = [_venue_row_to_baseline(r) for r in rows]
    return VenueListResponse(venues=venues)


# ── Route: GET /api/venues/summary ────────────────────────────────


@router.get("/venues/summary")
async def venues_summary(
    store=Depends(_get_store),
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
    conn, fmt = store
    f = safe_fmt(fmt)

    try:
        rows = query_all(conn, f"SELECT * FROM {f}.venue_with_difficulty")
    except duckdb.CatalogException:
        rows = query_all(conn, f"SELECT * FROM {f}.venue")

    if not rows:
        return {
            "total_venues": 0,
            "hardest_venue": None,
            "easiest_venue": None,
            "most_used_venue": None,
            "avg_difficulty": None,
            "difficulty_distribution": [],
        }

    total_venues = len(rows)

    hardest_venue = None
    easiest_venue = None
    most_used_venue = None

    best_diff = None
    worst_diff = None
    most_matches = -1
    diff_values: list[float] = []

    for r in rows:
        d = r.get("venue_difficulty")
        di = r.get("venue_difficulty_index")
        m = safe_int(r.get("venue_matches"))

        if d is not None:
            try:
                dv = float(d)
                if not (math.isnan(dv) or math.isinf(dv)):
                    if best_diff is None or dv > best_diff:
                        best_diff = dv
                        hardest_venue = r
                    if worst_diff is None or dv < worst_diff:
                        worst_diff = dv
                        easiest_venue = r
            except (TypeError, ValueError):
                pass

        if di is not None:
            try:
                div = float(di)
                if not (math.isnan(div) or math.isinf(div)):
                    diff_values.append(div)
            except (TypeError, ValueError):
                pass

        if m > most_matches:
            most_matches = m
            most_used_venue = r

    avg_difficulty = safe_float(sum(diff_values) / len(diff_values)) if diff_values else None

    distribution: list[dict] = []
    if diff_values:
        edges = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
        for i in range(len(edges) - 1):
            low = edges[i]
            high = edges[i + 1]
            if i < len(edges) - 2:
                count = sum(1 for v in diff_values if low <= v < high)
            else:
                count = sum(1 for v in diff_values if low <= v <= high)
            distribution.append({"bin_low": round(low, 1), "bin_high": round(high, 1), "count": count})

    def _venue_summary(r: dict | None) -> dict | None:
        if r is None:
            return None
        return {
            "venue": safe_str(r.get("venue")),
            "difficulty": safe_float(r.get("venue_difficulty_index")),
            "matches": safe_int(r.get("venue_matches")),
        }

    return {
        "total_venues": total_venues,
        "hardest_venue": _venue_summary(hardest_venue),
        "easiest_venue": _venue_summary(easiest_venue),
        "most_used_venue": _venue_summary(most_used_venue),
        "avg_difficulty": avg_difficulty,
        "difficulty_distribution": distribution,
    }


# ── Route: GET /api/venues/detail ─────────────────────────────────


@router.get("/venues/detail")
async def venue_detail(
    venue: str = Query(
        ...,
        description=(
            "Venue name (URL-encoded if necessary). "
            "Use the exact venue name as returned by /api/venues."
        ),
    ),
    store=Depends(_get_store),
) -> dict:
    """Return detailed information for a single venue.

    Includes the venue baseline (difficulty, par SR, etc.) plus
    aggregate match statistics.

    **Example**: ``/api/venues/detail?venue=Melbourne+Cricket+Ground``

    Raises 404 if the venue is not found.
    """
    conn, fmt = store
    f = safe_fmt(fmt)
    venue_decoded = _decode_venue_name(venue)

    row, canonical = resolve_venue_row(conn, fmt, venue_decoded, exact=False)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")

    di = safe_float(row.get("venue_difficulty_index"))
    if di is None:
        try:
            vd = query_all(
                conn,
                f"SELECT venue_difficulty_index FROM {f}.venue_with_difficulty "
                f"WHERE LOWER(venue) = LOWER(?) LIMIT 1",
                [canonical],
            )
            if vd:
                di = safe_float(vd[0].get("venue_difficulty_index"))
        except duckdb.CatalogException:
            pass

    return {
        "venue": safe_str(row.get("venue")),
        "matches": safe_int(row.get("venue_matches")),
        "avg_par_sr": safe_float(row.get("venue_avg_par_sr")),
        "par_sr_std": safe_float(row.get("venue_par_std")),
        "boundary_rate": safe_float(row.get("venue_avg_boundary_rate")),
        "dot_pct": safe_float(row.get("venue_avg_dot_pct")),
        "difficulty_raw": safe_float(row.get("venue_difficulty_raw")),
        "difficulty_score": di,
    }


# ── Route: GET /api/venues/profile ────────────────────────────────


@router.get("/venues/profile")
async def venue_profile(
    venue: str = Query(..., description="Venue name (URL-encoded)"),
    exact: bool = Query(
        False,
        description="If true, require exact match to a baseline venue name",
    ),
    store=Depends(_get_store),
) -> dict:
    """Rich venue profile: vs world, chase/defend, phase breakdown, sample sizes."""
    conn, fmt = store
    out = build_venue_profile(conn, fmt, _decode_venue_name(venue), exact=exact)
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


# ── Route: GET /api/venues/trends ─────────────────────────────────


@router.get("/venues/trends")
async def venue_trends(
    venue: str = Query(...),
    bucket: str = Query(
        "rolling_3_match",
        description="rolling_3_match (default): rolling 3-match averages by date; year or season for yearly buckets",
    ),
    exact: bool = Query(False),
    store=Depends(_get_store),
) -> dict:
    conn, fmt = store
    out = build_venue_trends(
        conn, fmt, _decode_venue_name(venue), exact=exact, bucket=bucket
    )
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


# ── Route: GET /api/venues/teams ──────────────────────────────────


@router.get("/venues/teams")
async def venue_teams(
    venue: str = Query(...),
    exact: bool = Query(False),
    min_matches: int = Query(2, ge=1),
    sort: str = Query("win_pct"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    store=Depends(_get_store),
) -> dict:
    conn, fmt = store
    out = build_venue_teams(
        conn,
        fmt,
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


# ── Route: GET /api/venues/similar ────────────────────────────────


@router.get("/venues/similar")
async def venue_similar(
    venue: str = Query(...),
    exact: bool = Query(False),
    k: int = Query(8, ge=1, le=30),
    store=Depends(_get_store),
) -> dict:
    conn, fmt = store
    out = build_venue_similar(conn, fmt, _decode_venue_name(venue), exact=exact, k=k)
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


# ── Route: GET /api/venues/matches ────────────────────────────────


@router.get("/venues/matches")
async def venue_match_list(
    venue: str = Query(...),
    exact: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    store=Depends(_get_store),
) -> dict:
    """Paginated matches played at this venue."""
    conn, fmt = store
    out = build_venue_matches(
        conn,
        fmt,
        _decode_venue_name(venue),
        exact=exact,
        page=page,
        per_page=per_page,
    )
    if out is None:
        raise HTTPException(status_code=404, detail=f"Venue not found: {venue}")
    return out


# ── Route: GET /api/venues/performances ───────────────────────────


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
    store=Depends(_get_store),
) -> dict:
    conn, fmt = store
    out = build_venue_performances(
        conn,
        fmt,
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
    store=Depends(_get_store),
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
    """
    conn, fmt = store
    venue_decoded = _decode_venue_name(venue)

    if role == "bowl":
        return players_at_venue_bowling(
            conn, fmt, venue_decoded, min_innings, sort, order, page, per_page, exact
        )
    return players_at_venue_batting(
        conn, fmt, venue_decoded, min_innings, sort, order, page, per_page, exact
    )


# ── Route: GET /api/player/{id}/venues ────────────────────────────


@router.get("/player/{player_id}/venues")
async def player_venue_splits(
    player_id: str,
    min_innings: int = Query(2, ge=1, description="Minimum innings at a venue"),
    store=Depends(_get_store),
) -> dict:
    """Return a player's venue-by-venue batting splits.

    Groups all batting innings by venue and returns aggregated stats
    for each venue where the player has enough innings.
    """
    conn, fmt = store
    f = safe_fmt(fmt)

    rows = query_all(conn, f"""
        SELECT
            venue,
            COUNT(*) AS innings,
            SUM(COALESCE(runs, 0)) AS runs,
            SUM(COALESCE(balls_faced, 0)) AS balls_faced,
            SUM(COALESCE(fours, 0)) AS fours,
            SUM(COALESCE(sixes, 0)) AS sixes,
            SUM(COALESCE(dots, 0)) AS dots,
            AVG(CASE WHEN balls_faced > 0 THEN runs * 100.0 / balls_faced ELSE NULL END) AS avg_sr,
            MAX(date)::VARCHAR AS last_played
        FROM {f}.bat_innings
        WHERE batter_id = ?
        GROUP BY venue
        HAVING COUNT(*) >= ?
        ORDER BY COUNT(*) DESC
    """, [player_id, min_innings])

    venues_out: list[dict] = []
    for r in rows:
        innings = safe_int(r.get("innings"))
        runs = safe_int(r.get("runs"))
        balls = safe_int(r.get("balls_faced"))
        fours = safe_int(r.get("fours"))
        sixes = safe_int(r.get("sixes"))
        dots = safe_int(r.get("dots"))
        sr = round(runs / balls * 100.0, 1) if balls > 0 else None
        avg = round(runs / max(innings, 1), 1)
        dot_pct = round(dots / balls, 4) if balls > 0 else None
        bruns = fours * 4 + sixes * 6
        boundary_pct = round(bruns / runs, 4) if runs > 0 else None

        lp = safe_str(r.get("last_played"))
        venues_out.append({
            "venue": safe_str(r.get("venue")),
            "innings": innings,
            "runs": runs,
            "balls_faced": balls,
            "sr": safe_float(sr),
            "avg": safe_float(avg),
            "fours": fours,
            "sixes": sixes,
            "dots": dots,
            "dot_pct": safe_float(dot_pct),
            "boundary_pct": safe_float(boundary_pct),
            "last_played": lp[:10] if lp else None,
        })

    return {
        "player_id": player_id,
        "venues": venues_out,
        "total": len(venues_out),
    }
