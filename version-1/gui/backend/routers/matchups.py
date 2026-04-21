"""
Matchups router — /api/matchups endpoints.

Provides:
- GET /api/matchups              → Head-to-head between a specific batter and bowler
- GET /api/matchups/explore      → Browse all matchups for a given player
- GET /api/matchups/top-bunnies  → Bowler's easiest targets
- GET /api/matchups/top-nemeses  → Batter's toughest opponents
- GET /api/matchups/top-dominant → Batter's favourite opponents
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from db import safe_float, safe_int, safe_str, safe_fmt, query_one, query_all
from schemas import (
    HeadToHeadResponse,
    MatchupExploreResponse,
    MatchupPhase,
    MatchupSummary,
)

router = APIRouter(prefix="/api", tags=["matchups"])

_VALID_SORT_COLS = frozenset({
    "dominance_index",
    "balls_faced",
    "runs_scored",
    "strike_rate",
    "dismissals",
    "dot_pct",
    "boundary_pct",
    "average",
})


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


# ── Helpers ───────────────────────────────────────────────────────


def _matchup_row_to_summary(
    row: dict, opponent_id_col: str, opponent_name_col: str
) -> MatchupSummary:
    return MatchupSummary(
        opponent_id=safe_str(row.get(opponent_id_col)),
        opponent_name=safe_str(row.get(opponent_name_col)),
        balls=safe_int(row.get("balls_faced")),
        runs=safe_int(row.get("runs_scored")),
        sr=safe_float(row.get("strike_rate")),
        dismissals=safe_int(row.get("dismissals")),
        dot_pct=safe_float(row.get("dot_pct")),
        boundary_pct=safe_float(row.get("boundary_pct")),
        dominance_index=safe_float(row.get("dominance_index")),
    )


def _phase_row_to_matchup_phase(row: dict) -> MatchupPhase:
    return MatchupPhase(
        phase=safe_str(row.get("phase")),
        balls=safe_int(row.get("balls_faced")),
        runs=safe_int(row.get("runs_scored")),
        sr=safe_float(row.get("strike_rate")),
        dots=safe_int(row.get("dots")),
        dismissals=safe_int(row.get("dismissals")),
        dominance_index=safe_float(row.get("dominance_index")),
    )


def _validated_sort_col(col: str) -> str:
    c = col.strip()
    if c in _VALID_SORT_COLS:
        return c
    return "dominance_index"


# ── Route: GET /api/matchups ─────────────────────────────────────


@router.get("/matchups", response_model=HeadToHeadResponse)
async def head_to_head(
    bat: str = Query(..., description="Batter player ID"),
    bowl: str = Query(..., description="Bowler player ID"),
    db=Depends(_get_store),
) -> HeadToHeadResponse:
    """Return the full head-to-head matchup between a batter and bowler.

    Includes overall stats and phase-by-phase breakdown (powerplay,
    middle, death). The dominance index indicates who dominates:
    positive = batter dominates, negative = bowler dominates.

    Raises 404 if no matchup data is found for this pair.
    """
    conn, fmt = db
    f = safe_fmt(fmt)

    overall = query_one(
        conn,
        f"SELECT * FROM {f}.matchups WHERE batter_id = $1 AND bowler_id = $2 LIMIT 1",
        [bat, bowl],
    )

    if overall is None:
        raise HTTPException(
            status_code=404,
            detail=f"No matchup data found for batter={bat} vs bowler={bowl}",
        )

    phases = query_all(
        conn,
        f"SELECT * FROM {f}.matchups_phase WHERE batter_id = $1 AND bowler_id = $2 ORDER BY phase",
        [bat, bowl],
    )

    by_phase = [_phase_row_to_matchup_phase(p) for p in phases]

    return HeadToHeadResponse(
        batter_id=bat,
        batter_name=safe_str(overall.get("batter")),
        bowler_id=bowl,
        bowler_name=safe_str(overall.get("bowler")),
        balls=safe_int(overall.get("balls_faced")),
        runs=safe_int(overall.get("runs_scored")),
        sr=safe_float(overall.get("strike_rate")),
        dismissals=safe_int(overall.get("dismissals")),
        dots=safe_int(overall.get("dots")),
        fours=safe_int(overall.get("fours")),
        sixes=safe_int(overall.get("sixes")),
        dot_pct=safe_float(overall.get("dot_pct")),
        boundary_pct=safe_float(overall.get("boundary_pct")),
        dominance_index=safe_float(overall.get("dominance_index")),
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
    db=Depends(_get_store),
) -> MatchupExploreResponse:
    """Browse all matchups for a given player, with filtering and sorting."""
    conn, fmt = db
    f = safe_fmt(fmt)

    sort_col = _validated_sort_col(sort)
    direction = "ASC" if order.lower() == "asc" else "DESC"

    if role == "bowl":
        where_col = "bowler_id"
        opponent_id_col = "batter_id"
        opponent_name_col = "batter"
    else:
        where_col = "batter_id"
        opponent_id_col = "bowler_id"
        opponent_name_col = "bowler"

    count_sql = (
        f"SELECT COUNT(*) FROM {f}.matchups "
        f"WHERE {where_col} = $1 AND balls_faced >= $2"
    )
    total = conn.execute(count_sql, [player_id, min_balls]).fetchone()[0]

    if total == 0:
        return MatchupExploreResponse(
            matchups=[], total=0, page=page, per_page=per_page
        )

    offset = (page - 1) * per_page
    data_sql = (
        f"SELECT * FROM {f}.matchups "
        f"WHERE {where_col} = $1 AND balls_faced >= $2 "
        f"ORDER BY {sort_col} {direction} NULLS LAST "
        f"LIMIT $3 OFFSET $4"
    )
    rows = query_all(conn, data_sql, [player_id, min_balls, per_page, offset])

    matchups = [
        _matchup_row_to_summary(r, opponent_id_col, opponent_name_col) for r in rows
    ]

    return MatchupExploreResponse(
        matchups=matchups,
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
    db=Depends(_get_store),
) -> list[MatchupSummary]:
    """Return a bowler's top 'bunnies' — batters they dominate.

    Sorted by dominance_index ascending (most negative = bowler
    dominates most).
    """
    conn, fmt = db
    f = safe_fmt(fmt)

    rows = query_all(
        conn,
        f"SELECT * FROM {f}.matchups "
        f"WHERE bowler_id = $1 AND balls_faced >= $2 "
        f"ORDER BY dominance_index ASC NULLS LAST LIMIT $3",
        [bowler_id, min_balls, limit],
    )

    return [_matchup_row_to_summary(r, "batter_id", "batter") for r in rows]


# ── Route: GET /api/matchups/top-nemeses ──────────────────────────


@router.get("/matchups/top-nemeses")
async def top_nemeses(
    batter_id: str = Query(..., description="Batter player ID"),
    min_balls: int = Query(6, ge=1, description="Minimum balls faced"),
    limit: int = Query(10, ge=1, le=50, description="Number of nemeses to return"),
    db=Depends(_get_store),
) -> list[MatchupSummary]:
    """Return a batter's top 'nemeses' — bowlers who dominate them.

    Sorted by dominance_index ascending (most negative = bowler
    dominates most).
    """
    conn, fmt = db
    f = safe_fmt(fmt)

    rows = query_all(
        conn,
        f"SELECT * FROM {f}.matchups "
        f"WHERE batter_id = $1 AND balls_faced >= $2 "
        f"ORDER BY dominance_index ASC NULLS LAST LIMIT $3",
        [batter_id, min_balls, limit],
    )

    return [_matchup_row_to_summary(r, "bowler_id", "bowler") for r in rows]


# ── Route: GET /api/matchups/top-dominant ─────────────────────────


@router.get("/matchups/top-dominant")
async def top_dominant_matchups(
    batter_id: str = Query(..., description="Batter player ID"),
    min_balls: int = Query(6, ge=1, description="Minimum balls faced"),
    limit: int = Query(10, ge=1, le=50, description="Number of matchups to return"),
    db=Depends(_get_store),
) -> list[MatchupSummary]:
    """Return the bowlers a batter dominates the most.

    Sorted by dominance_index descending (most positive = batter
    dominates most).
    """
    conn, fmt = db
    f = safe_fmt(fmt)

    rows = query_all(
        conn,
        f"SELECT * FROM {f}.matchups "
        f"WHERE batter_id = $1 AND balls_faced >= $2 "
        f"ORDER BY dominance_index DESC NULLS LAST LIMIT $3",
        [batter_id, min_balls, limit],
    )

    return [_matchup_row_to_summary(r, "bowler_id", "bowler") for r in rows]
