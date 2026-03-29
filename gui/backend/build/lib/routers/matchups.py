"""
Matchups router — /api/matchups endpoints.

Provides:
- GET /api/matchups              → Head-to-head between a specific batter and bowler
- GET /api/matchups/explore      → Browse all matchups for a given player
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from schemas import (
    HeadToHeadResponse,
    MatchupExploreResponse,
    MatchupPhase,
    MatchupSummary,
)

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["matchups"])


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


def _matchup_row_to_summary(
    row: Any, opponent_id_col: str, opponent_name_col: str
) -> MatchupSummary:
    """Convert a matchup DataFrame row to a MatchupSummary."""
    return MatchupSummary(
        opponent_id=_safe_str(_get_val(row, opponent_id_col)),
        opponent_name=_safe_str(_get_val(row, opponent_name_col)),
        balls=_safe_int(_get_val(row, "balls_faced")),
        runs=_safe_int(_get_val(row, "runs_scored")),
        sr=_safe_float(_get_val(row, "strike_rate")),
        dismissals=_safe_int(_get_val(row, "dismissals")),
        dot_pct=_safe_float(_get_val(row, "dot_pct")),
        boundary_pct=_safe_float(_get_val(row, "boundary_pct")),
        dominance_index=_safe_float(_get_val(row, "dominance_index")),
    )


def _phase_row_to_matchup_phase(row: Any) -> MatchupPhase:
    """Convert a matchup-by-phase DataFrame row to a MatchupPhase."""
    return MatchupPhase(
        phase=_safe_str(_get_val(row, "phase")),
        balls=_safe_int(_get_val(row, "balls_faced")),
        runs=_safe_int(_get_val(row, "runs_scored")),
        sr=_safe_float(_get_val(row, "strike_rate")),
        dots=_safe_int(_get_val(row, "dots")),
        dismissals=_safe_int(_get_val(row, "dismissals")),
        dominance_index=_safe_float(_get_val(row, "dominance_index")),
    )


# ── Route: GET /api/matchups ─────────────────────────────────────


@router.get("/matchups", response_model=HeadToHeadResponse)
async def head_to_head(
    bat: str = Query(..., description="Batter player ID"),
    bowl: str = Query(..., description="Bowler player ID"),
    store: "DataStore" = Depends(_get_store),
) -> HeadToHeadResponse:
    """Return the full head-to-head matchup between a batter and bowler.

    Includes overall stats and phase-by-phase breakdown (powerplay,
    middle, death). The dominance index indicates who dominates:
    positive = batter dominates, negative = bowler dominates.

    Raises 404 if no matchup data is found for this pair.

    **Example**: ``/api/matchups?bat=abc123&bowl=def456``
    """
    from data_loader import get_head_to_head

    h2h = get_head_to_head(store, batter_id=bat, bowler_id=bowl)

    overall_df = h2h["overall"]
    phase_df = h2h["by_phase"]

    if overall_df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No matchup data found for batter={bat} vs bowler={bowl}",
        )

    # Overall stats (should be a single row)
    orow = overall_df.iloc[0]

    # Resolve player names
    batter_name = _safe_str(_get_val(orow, "batter"))
    bowler_name = _safe_str(_get_val(orow, "bowler"))

    # Phase breakdown
    by_phase: list[MatchupPhase] = []
    if not phase_df.empty:
        for _, prow in phase_df.iterrows():
            by_phase.append(_phase_row_to_matchup_phase(prow))

    return HeadToHeadResponse(
        batter_id=bat,
        batter_name=batter_name,
        bowler_id=bowl,
        bowler_name=bowler_name,
        balls=_safe_int(_get_val(orow, "balls_faced")),
        runs=_safe_int(_get_val(orow, "runs_scored")),
        sr=_safe_float(_get_val(orow, "strike_rate")),
        dismissals=_safe_int(_get_val(orow, "dismissals")),
        dots=_safe_int(_get_val(orow, "dots")),
        fours=_safe_int(_get_val(orow, "fours")),
        sixes=_safe_int(_get_val(orow, "sixes")),
        dot_pct=_safe_float(_get_val(orow, "dot_pct")),
        boundary_pct=_safe_float(_get_val(orow, "boundary_pct")),
        dominance_index=_safe_float(_get_val(orow, "dominance_index")),
        by_phase=by_phase,
    )


# ── Route: GET /api/matchups/explore ──────────────────────────────


@router.get("/matchups/explore", response_model=MatchupExploreResponse)
async def explore_matchups(
    player_id: str = Query(..., description="Player ID to explore matchups for"),
    role: str = Query(
        "bat",
        description=(
            "Player's role in the matchup: 'bat' to show bowlers they faced, "
            "'bowl' to show batters they bowled to"
        ),
    ),
    min_balls: int = Query(6, ge=1, description="Minimum balls faced/bowled"),
    sort: str = Query(
        "dominance_index",
        description=(
            "Column to sort by. Options: dominance_index, balls_faced, "
            "runs_scored, strike_rate, dismissals, dot_pct, boundary_pct"
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    store: "DataStore" = Depends(_get_store),
) -> MatchupExploreResponse:
    """Browse all matchups for a given player, with filtering and sorting.

    For batters (role=bat): returns all bowlers they've faced, with
    stats from the batter's perspective. Sort by dominance_index to
    find their best/worst matchups.

    For bowlers (role=bowl): returns all batters they've bowled to.
    Sort ascending by dominance_index to find their "bunnies".

    **Examples**:
    - ``/api/matchups/explore?player_id=abc&role=bat&sort=dominance_index&order=desc``
    - ``/api/matchups/explore?player_id=xyz&role=bowl&sort=dismissals&order=desc&min_balls=10``
    """
    from data_loader import get_matchups_for_batter, get_matchups_for_bowler

    if role == "bowl":
        matchups_df = get_matchups_for_bowler(store, player_id, min_balls=min_balls)
        opponent_id_col = "batter_id"
        opponent_name_col = "batter"
    else:
        matchups_df = get_matchups_for_batter(store, player_id, min_balls=min_balls)
        opponent_id_col = "bowler_id"
        opponent_name_col = "bowler"

    if matchups_df.empty:
        return MatchupExploreResponse(
            matchups=[], total=0, page=page, per_page=per_page
        )

    # Sort
    sort_col = sort.strip()
    valid_sort_cols = {
        "dominance_index",
        "balls_faced",
        "runs_scored",
        "strike_rate",
        "dismissals",
        "dot_pct",
        "boundary_pct",
        "average",
    }
    if sort_col not in valid_sort_cols:
        if sort_col in matchups_df.columns:
            pass  # Allow any column that exists
        else:
            sort_col = "dominance_index"

    ascending = order.lower() == "asc"
    if sort_col in matchups_df.columns:
        matchups_df = matchups_df.sort_values(
            sort_col, ascending=ascending, na_position="last"
        )

    total = len(matchups_df)

    # Paginate
    start = (page - 1) * per_page
    end = start + per_page
    page_df = matchups_df.iloc[start:end]

    matchup_list: list[MatchupSummary] = []
    for _, mrow in page_df.iterrows():
        matchup_list.append(
            _matchup_row_to_summary(mrow, opponent_id_col, opponent_name_col)
        )

    return MatchupExploreResponse(
        matchups=matchup_list,
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Route: GET /api/matchups/top-bunnies ──────────────────────────


@router.get("/matchups/top-bunnies")
async def top_bunnies(
    bowler_id: str = Query(..., description="Bowler player ID"),
    min_balls: int = Query(6, ge=1, description="Minimum balls bowled"),
    limit: int = Query(10, ge=1, le=50, description="Number of bunnies to return"),
    store: "DataStore" = Depends(_get_store),
) -> list[MatchupSummary]:
    """Return a bowler's top 'bunnies' — batters they dominate.

    Sorted by dominance_index ascending (most negative = bowler
    dominates most). These are the batters who struggle against
    this bowler.

    **Example**: ``/api/matchups/top-bunnies?bowler_id=xyz&min_balls=10&limit=5``
    """
    from data_loader import get_matchups_for_bowler

    matchups_df = get_matchups_for_bowler(store, bowler_id, min_balls=min_balls)
    if matchups_df.empty:
        return []

    # Bunnies = lowest dominance_index (bowler dominates)
    bunnies_df = matchups_df.nsmallest(limit, "dominance_index")

    return [
        _matchup_row_to_summary(row, "batter_id", "batter")
        for _, row in bunnies_df.iterrows()
    ]


# ── Route: GET /api/matchups/top-nemeses ──────────────────────────


@router.get("/matchups/top-nemeses")
async def top_nemeses(
    batter_id: str = Query(..., description="Batter player ID"),
    min_balls: int = Query(6, ge=1, description="Minimum balls faced"),
    limit: int = Query(10, ge=1, le=50, description="Number of nemeses to return"),
    store: "DataStore" = Depends(_get_store),
) -> list[MatchupSummary]:
    """Return a batter's top 'nemeses' — bowlers who dominate them.

    Sorted by dominance_index ascending (most negative = bowler
    dominates most). These are the bowlers the batter struggles against.

    **Example**: ``/api/matchups/top-nemeses?batter_id=abc&min_balls=10&limit=5``
    """
    from data_loader import get_matchups_for_batter

    matchups_df = get_matchups_for_batter(store, batter_id, min_balls=min_balls)
    if matchups_df.empty:
        return []

    # Nemeses = lowest dominance_index (bowler dominates)
    nemeses_df = matchups_df.nsmallest(limit, "dominance_index")

    return [
        _matchup_row_to_summary(row, "bowler_id", "bowler")
        for _, row in nemeses_df.iterrows()
    ]


# ── Route: GET /api/matchups/top-dominant ─────────────────────────


@router.get("/matchups/top-dominant")
async def top_dominant_matchups(
    batter_id: str = Query(..., description="Batter player ID"),
    min_balls: int = Query(6, ge=1, description="Minimum balls faced"),
    limit: int = Query(10, ge=1, le=50, description="Number of matchups to return"),
    store: "DataStore" = Depends(_get_store),
) -> list[MatchupSummary]:
    """Return the bowlers a batter dominates the most.

    Sorted by dominance_index descending (most positive = batter
    dominates most). These are the bowlers the batter thrives against.

    **Example**: ``/api/matchups/top-dominant?batter_id=abc&min_balls=10&limit=5``
    """
    from data_loader import get_matchups_for_batter

    matchups_df = get_matchups_for_batter(store, batter_id, min_balls=min_balls)
    if matchups_df.empty:
        return []

    # Dominant = highest dominance_index (batter dominates)
    dominant_df = matchups_df.nlargest(limit, "dominance_index")

    return [
        _matchup_row_to_summary(row, "bowler_id", "bowler")
        for _, row in dominant_df.iterrows()
    ]
