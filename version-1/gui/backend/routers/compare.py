"""
Compare router — /api/compare for side-by-side 2–4 player comparison.

Provides:
- GET /api/compare?ids=id1,id2,...  → Side-by-side profiles for 2–4 players
- GET /api/compare/form?ids=...     → Overlaid form time-series for comparison
- GET /api/compare/shared-matchups  → Shared bowlers/batters between compared players

The compare endpoint returns full profiles for each player (batting or
bowling), enabling the frontend to render radar overlays, stat tables,
form comparisons, and phase breakdowns.
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from db import (
    DEFAULT_FORMAT,
    VALID_FORMATS,
    query_all,
    query_one,
    safe_float,
    safe_fmt,
    safe_int,
    safe_str,
)
from schemas import (
    BatterProfile,
    BowlerProfile,
    CompareResponse,
    FormPoint,
    FormResponse,
    MatchupSummary,
    PlayerSummary,
)

router = APIRouter(prefix="/api", tags=["compare"])

_COMPARE_FMT_PATTERN = "^(" + "|".join(VALID_FORMATS) + ")$"


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_multi_store():
    raise HTTPException(
        status_code=503,
        detail="DuckDB connection not initialised (dependency override missing).",
    )


# ── Helpers ───────────────────────────────────────────────────────


def _parse_ids(ids_str: str) -> list[str]:
    """Parse a comma-separated list of player IDs (2–4 required)."""
    raw = [pid.strip() for pid in ids_str.split(",") if pid.strip()]

    seen: set[str] = set()
    unique: list[str] = []
    for pid in raw:
        if pid not in seen:
            seen.add(pid)
            unique.append(pid)

    if len(unique) < 2:
        raise HTTPException(
            status_code=400,
            detail=(
                f"At least 2 player IDs are required for comparison, "
                f"got {len(unique)}. Provide IDs as comma-separated values: "
                f"?ids=id1,id2"
            ),
        )
    if len(unique) > 4:
        raise HTTPException(
            status_code=400,
            detail=(
                f"At most 4 player IDs are supported for comparison, "
                f"got {len(unique)}. Please reduce to 4 or fewer players."
            ),
        )
    return unique


def _parse_ids_form(ids_str: str) -> list[str]:
    """Parse comma-separated player IDs for multi-player form charts (2–10)."""
    raw = [pid.strip() for pid in ids_str.split(",") if pid.strip()]

    seen: set[str] = set()
    unique: list[str] = []
    for pid in raw:
        if pid not in seen:
            seen.add(pid)
            unique.append(pid)

    if len(unique) < 2:
        raise HTTPException(
            status_code=400,
            detail=(
                f"At least 2 player IDs are required for overlaid form data, "
                f"got {len(unique)}. Provide IDs as comma-separated values: "
                f"?ids=id1,id2"
            ),
        )
    if len(unique) > 10:
        raise HTTPException(
            status_code=400,
            detail=(
                f"At most 10 player IDs are supported for form charts, "
                f"got {len(unique)}. Please reduce to 10 or fewer players."
            ),
        )
    return unique


def _formats_search_order(preferred: str) -> list[str]:
    """Preferred format first, then remaining valid formats."""
    pref = preferred.lower()
    if pref in VALID_FORMATS:
        return [pref] + [f for f in VALID_FORMATS if f != pref]
    return list(VALID_FORMATS)


def _find_batter_row_across_formats(
    conn: duckdb.DuckDBPyConnection, pid: str, preferred_fmt: str
) -> tuple[dict, str] | tuple[None, None]:
    """Search all format schemas for a batter career row, preferred format first."""
    for fmt in _formats_search_order(preferred_fmt or DEFAULT_FORMAT):
        f = safe_fmt(fmt)
        try:
            row = query_one(conn, f"SELECT * FROM {f}.bat_careers WHERE batter_id = ?", [pid])
        except duckdb.CatalogException:
            continue
        if row is not None:
            return row, f
    return None, None


def _find_bowler_row_across_formats(
    conn: duckdb.DuckDBPyConnection, pid: str, preferred_fmt: str
) -> tuple[dict, str] | tuple[None, None]:
    """Search all format schemas for a bowler career row, preferred format first."""
    for fmt in _formats_search_order(preferred_fmt or DEFAULT_FORMAT):
        f = safe_fmt(fmt)
        try:
            row = query_one(conn, f"SELECT * FROM {f}.bowl_careers WHERE bowler_id = ?", [pid])
        except duckdb.CatalogException:
            continue
        if row is not None:
            return row, f
    return None, None


# ── Profile builders (reuse player router logic) ─────────────────


def _build_batter_profile_for_compare(
    row: dict, conn: duckdb.DuckDBPyConnection, fmt: str
) -> BatterProfile:
    from routers.player import _build_batter_profile, _compute_batting_phase_splits

    batter_id = safe_str(row.get("batter_id"))
    profile = _build_batter_profile(row, conn, fmt, top_k_matchups=3)
    profile.phases = _compute_batting_phase_splits(conn, fmt, batter_id)
    return profile


def _build_bowler_profile_for_compare(
    row: dict, conn: duckdb.DuckDBPyConnection, fmt: str
) -> BowlerProfile:
    from routers.player import _build_bowler_profile, _compute_bowling_phase_splits

    bowler_id = safe_str(row.get("bowler_id"))
    profile = _build_bowler_profile(row, conn, fmt, top_k_matchups=3)
    profile.phases = _compute_bowling_phase_splits(conn, fmt, bowler_id)
    return profile


# ── Route: GET /api/compare ──────────────────────────────────────


@router.get("/compare", response_model=CompareResponse)
async def compare_players(
    ids: str = Query(
        ...,
        description=(
            "Comma-separated player IDs (2–4). Example: ?ids=abc123,def456. "
            "Players can be a mix of batters and bowlers — each will be "
            "returned under the appropriate key in the response."
        ),
    ),
    conn: duckdb.DuckDBPyConnection = Depends(_get_multi_store),
    format: str = Query(
        DEFAULT_FORMAT,
        pattern=_COMPARE_FMT_PATTERN,
        description="Preferred dataset to search first; other loaded formats are tried per player.",
    ),
) -> CompareResponse:
    """Compare 2–4 players side-by-side.

    Returns full profiles for each player, separated into ``batters``
    and ``bowlers`` lists. The frontend can then render:

    - **Radar overlay**: overlaid polygons for each player's scores
    - **Stat table**: row-by-row comparison with automatic "winner" highlighting
    - **Form overlay**: line chart with multiple players' form over time
    - **Phase comparison**: grouped bars for powerplay/middle/death
    - **Shared matchups**: bowlers that multiple batters have both faced

    If a player ID is found in both batting and bowling careers (all-rounder),
    the batting profile takes precedence.

    Raises 400 if fewer than 2 or more than 4 IDs are provided.
    Raises 404 if any player ID is not found in either dataset.
    """
    player_ids = _parse_ids(ids)

    batters: list[BatterProfile] = []
    bowlers: list[BowlerProfile] = []
    not_found: list[str] = []

    for pid in player_ids:
        bat_row, bat_fmt = _find_batter_row_across_formats(conn, pid, format)
        if bat_row is not None and bat_fmt is not None:
            profile = _build_batter_profile_for_compare(bat_row, conn, bat_fmt)
            batters.append(profile)
            continue

        bowl_row, bowl_fmt = _find_bowler_row_across_formats(conn, pid, format)
        if bowl_row is not None and bowl_fmt is not None:
            profile = _build_bowler_profile_for_compare(bowl_row, conn, bowl_fmt)
            bowlers.append(profile)
            continue

        not_found.append(pid)

    if not_found:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Player(s) not found: {', '.join(not_found)}. "
                f"Check the player IDs and try again."
            ),
        )

    return CompareResponse(batters=batters, bowlers=bowlers)


# ── Route: GET /api/compare/form ─────────────────────────────────


def _build_batting_form_point(row: dict) -> FormPoint:
    return FormPoint(
        date=safe_str(row.get("date")),
        match_id=safe_str(row.get("match_id")),
        window_innings=safe_int(row.get("window_innings")),
        composite=safe_float(row.get("window_composite")),
        score_1=safe_float(row.get("window_score_acceleration")),
        score_2=safe_float(row.get("window_score_power")),
        score_3=safe_float(row.get("window_score_control")),
        score_1_label="acceleration",
        score_2_label="power",
        score_3_label="control",
        is_peak_window=bool(row.get("is_peak_window", False)),
        window_avg_runs=safe_float(row.get("window_avg_runs")),
        window_avg_sr=safe_float(row.get("window_avg_sr")),
        window_total_runs=safe_float(row.get("window_total_runs")),
        window_fours=safe_float(row.get("window_fours")),
        window_sixes=safe_float(row.get("window_sixes")),
        window_sr_vs_par=safe_float(row.get("window_sr_vs_par")),
        window_impact=safe_float(row.get("window_impact")),
        window_boundary_pct=safe_float(row.get("window_boundary_pct")),
        window_six_rate=safe_float(row.get("window_six_rate")),
        window_dot_control=safe_float(row.get("window_dot_control")),
        window_consistency=safe_float(row.get("window_consistency")),
        window_rotation=safe_float(row.get("window_rotation")),
    )


def _build_bowling_form_point(row: dict) -> FormPoint:
    return FormPoint(
        date=safe_str(row.get("date")),
        match_id=safe_str(row.get("match_id")),
        window_innings=safe_int(row.get("window_spells")),
        composite=safe_float(row.get("window_composite")),
        score_1=safe_float(row.get("window_score_accuracy")),
        score_2=safe_float(row.get("window_score_control")),
        score_3=safe_float(row.get("window_score_threat")),
        score_1_label="accuracy",
        score_2_label="control",
        score_3_label="threat",
        is_peak_window=bool(row.get("is_peak_window", False)),
        window_avg_runs=None,
        window_avg_sr=None,
        window_total_runs=None,
        window_fours=None,
        window_sixes=None,
        window_economy=safe_float(row.get("window_economy")),
        window_dot_pct=safe_float(row.get("window_dot_pct")),
        window_wickets_per_spell=safe_float(row.get("window_wickets_per_spell")),
        window_total_wickets=safe_float(row.get("window_total_wickets")),
        window_economy_vs_par=safe_float(row.get("window_economy_vs_par")),
        window_quality_wickets=safe_float(row.get("window_quality_wickets")),
        window_threat_pressure=safe_float(row.get("window_threat_pressure")),
    )


@router.get("/compare/form")
async def compare_form(
    ids: str = Query(
        ...,
        description="Comma-separated player IDs (2–10 for charts; compare UI still uses 2–4)",
    ),
    conn: duckdb.DuckDBPyConnection = Depends(_get_multi_store),
    format: str = Query(
        DEFAULT_FORMAT,
        pattern=_COMPARE_FMT_PATTERN,
        description="Preferred dataset to resolve each player's form series.",
    ),
) -> list[FormResponse]:
    """Return form time-series for multiple players for overlaid comparison.

    Each player's form series is returned as a separate ``FormResponse``
    entry in the list. Auto-detects whether each player is a batter or
    bowler and returns the appropriate form metrics.

    Supports 2–10 player IDs (for leaderboard charts); the main compare
    page continues to cap selections at 4 in the UI.
    """
    player_ids = _parse_ids_form(ids)
    results: list[FormResponse] = []

    for pid in player_ids:
        # Try batting form first
        bat_form_rows: list[dict] = []
        bat_fmt: str | None = None
        for fmt_key in _formats_search_order(format):
            f = safe_fmt(fmt_key)
            try:
                rows = query_all(
                    conn,
                    f"SELECT * FROM {f}.bat_form WHERE batter_id = ? ORDER BY date",
                    [pid],
                )
            except duckdb.CatalogException:
                continue
            if rows:
                bat_form_rows = rows
                bat_fmt = f
                break

        if bat_form_rows and bat_fmt:
            career = query_one(conn, f"SELECT batter FROM {bat_fmt}.bat_careers WHERE batter_id = ?", [pid])
            player_name = safe_str(career.get("batter")) if career else ""
            series = [_build_batting_form_point(r) for r in bat_form_rows]
            results.append(FormResponse(player_id=pid, player_name=player_name, series=series))
            continue

        # Try bowling form
        bowl_form_rows: list[dict] = []
        bowl_fmt: str | None = None
        for fmt_key in _formats_search_order(format):
            f = safe_fmt(fmt_key)
            try:
                rows = query_all(
                    conn,
                    f"SELECT * FROM {f}.bowl_form WHERE bowler_id = ? ORDER BY date",
                    [pid],
                )
            except duckdb.CatalogException:
                continue
            if rows:
                bowl_form_rows = rows
                bowl_fmt = f
                break

        if bowl_form_rows and bowl_fmt:
            career = query_one(conn, f"SELECT bowler FROM {bowl_fmt}.bowl_careers WHERE bowler_id = ?", [pid])
            player_name = safe_str(career.get("bowler")) if career else ""
            series = [_build_bowling_form_point(r) for r in bowl_form_rows]
            results.append(FormResponse(player_id=pid, player_name=player_name, series=series))
            continue

        results.append(FormResponse(player_id=pid, player_name="", series=[]))

    return results


# ── Route: GET /api/compare/shared-matchups ──────────────────────


@router.get("/compare/shared-matchups")
async def shared_matchups(
    ids: str = Query(
        ...,
        description=(
            "Comma-separated batter IDs (2–4). Returns bowlers that "
            "multiple batters have both faced, with per-batter stats."
        ),
    ),
    min_balls: int = Query(
        6, ge=1, description="Minimum balls faced per batter-bowler pair"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max shared matchups to return"),
    conn: duckdb.DuckDBPyConnection = Depends(_get_multi_store),
    format: str = Query(
        DEFAULT_FORMAT,
        pattern=_COMPARE_FMT_PATTERN,
        description="Preferred dataset when resolving each batter's matchup rows.",
    ),
) -> dict:
    """Find bowlers that two or more compared batters have both faced.

    Returns a list of shared matchups, where each entry contains the
    bowler's name/ID and each batter's stats against that bowler.

    Only returns matchups where **all** provided batters have faced
    the bowler with at least ``min_balls`` each.
    """
    batter_ids = _parse_ids(ids)

    # Resolve format for each batter: use the first schema that contains them
    batter_fmt: dict[str, str] = {}
    for bid in batter_ids:
        _, found_fmt = _find_batter_row_across_formats(conn, bid, format)
        if found_fmt:
            batter_fmt[bid] = found_fmt

    if len(batter_fmt) < 2:
        return {"batter_ids": batter_ids, "shared": []}

    # For batters that share a format, run a single efficient query;
    # otherwise, fall back to per-batter queries.
    # Group batters by format
    fmt_groups: dict[str, list[str]] = {}
    for bid, f in batter_fmt.items():
        fmt_groups.setdefault(f, []).append(bid)

    # Collect matchup rows per batter
    batter_matchups: dict[str, list[dict]] = {}
    bowler_sets: list[set[str]] = []

    for f, bids_in_fmt in fmt_groups.items():
        placeholders = ", ".join(["?"] * len(bids_in_fmt))
        rows = query_all(
            conn,
            f"""
            SELECT batter_id, bowler_id, bowler, balls_faced, runs_scored,
                   strike_rate, dismissals, dots, fours, sixes,
                   dot_pct, boundary_pct, dominance_index
            FROM {f}.matchups
            WHERE batter_id IN ({placeholders})
              AND balls_faced >= ?
            """,
            bids_in_fmt + [min_balls],
        )
        per_batter: dict[str, list[dict]] = {}
        for row in rows:
            bid = str(row["batter_id"])
            per_batter.setdefault(bid, []).append(row)

        for bid in bids_in_fmt:
            matchup_list = per_batter.get(bid, [])
            batter_matchups[bid] = matchup_list
            bowler_sets.append({str(r["bowler_id"]) for r in matchup_list})

    # For batters not yet in batter_matchups (shouldn't happen, but be safe)
    for bid in batter_ids:
        if bid not in batter_matchups:
            batter_matchups[bid] = []
            bowler_sets.append(set())

    if not bowler_sets:
        return {"batter_ids": batter_ids, "shared": []}

    common_bowlers = bowler_sets[0]
    for bs in bowler_sets[1:]:
        common_bowlers = common_bowlers & bs

    if not common_bowlers:
        return {"batter_ids": batter_ids, "shared": []}

    # Build shared matchup entries
    shared: list[dict] = []
    for bowler_id in common_bowlers:
        entry: dict[str, Any] = {
            "bowler_id": bowler_id,
            "bowler_name": "",
            "matchups": {},
        }

        for bid in batter_ids:
            for mrow in batter_matchups.get(bid, []):
                if str(mrow["bowler_id"]) != bowler_id:
                    continue
                if not entry["bowler_name"]:
                    entry["bowler_name"] = safe_str(mrow.get("bowler"))

                entry["matchups"][bid] = {
                    "balls": safe_int(mrow.get("balls_faced")),
                    "runs": safe_int(mrow.get("runs_scored")),
                    "sr": safe_float(mrow.get("strike_rate")),
                    "dismissals": safe_int(mrow.get("dismissals")),
                    "dots": safe_int(mrow.get("dots")),
                    "fours": safe_int(mrow.get("fours")),
                    "sixes": safe_int(mrow.get("sixes")),
                    "dot_pct": safe_float(mrow.get("dot_pct")),
                    "boundary_pct": safe_float(mrow.get("boundary_pct")),
                    "dominance_index": safe_float(mrow.get("dominance_index")),
                }
                break

        shared.append(entry)

    def _total_balls(entry: dict) -> int:
        return sum(m.get("balls", 0) for m in entry["matchups"].values())

    shared.sort(key=_total_balls, reverse=True)

    return {
        "batter_ids": batter_ids,
        "shared": shared[:limit],
    }
