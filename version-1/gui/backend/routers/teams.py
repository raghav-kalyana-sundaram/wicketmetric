"""
Teams router — league-wide standings for the active format (Men/Women × T20I/IPL).
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query

from league_teams import (
    build_league_team_standings,
    build_team_composition_series,
    build_team_detail,
    build_team_proficient_players,
    list_team_names_chips,
)
from schemas import (
    LeagueTeamStandingsResponse,
    TeamChipsResponse,
    TeamCompositionResponse,
    TeamDetailResponse,
    TeamProficientPlayersResponse,
)

router = APIRouter(prefix="/api", tags=["teams"])


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


@router.get("/teams", response_model=LeagueTeamStandingsResponse)
async def league_team_standings(
    min_matches: int = Query(3, ge=1, description="Minimum distinct matches for a team to appear"),
    sort: str = Query(
        "win_pct",
        description="Sort column: team, matches, wins, losses, win_pct, avg_innings_runs",
    ),
    order: str = Query("desc", description="asc or desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    q: str | None = Query(None, description="Filter teams by name substring (case-insensitive)"),
    store=Depends(_get_store),
) -> LeagueTeamStandingsResponse:
    """Team records in the selected dataset (international T20 or franchise IPL/WPL slice)."""
    conn, fmt = store
    raw = build_league_team_standings(
        conn,
        fmt,
        min_matches=min_matches,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
        q=q,
    )
    return LeagueTeamStandingsResponse.model_validate(raw)


@router.get("/teams/chips", response_model=TeamChipsResponse)
async def team_chips(store=Depends(_get_store)) -> TeamChipsResponse:
    """Distinct team names for the format (horizontal picker)."""
    conn, fmt = store
    names = list_team_names_chips(conn, fmt)
    return TeamChipsResponse(teams=names)


@router.get("/teams/composition", response_model=TeamCompositionResponse)
async def team_composition(
    team: str = Query(..., min_length=1, description="Team / franchise name as in scorecards"),
    limit: int = Query(40, ge=1, le=80, description="Max recent innings per series (batting / bowling)"),
    store=Depends(_get_store),
) -> TeamCompositionResponse:
    """Per-innings composition for stacked area charts (runs mix when batting, wickets when bowling)."""
    conn, fmt = store
    decoded = urllib.parse.unquote(team).strip()
    raw = build_team_composition_series(conn, fmt, decoded, limit=limit)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Unknown team in this format: {decoded}")
    return TeamCompositionResponse.model_validate(raw)


@router.get("/teams/detail", response_model=TeamDetailResponse)
async def team_detail(
    team: str = Query(..., min_length=1, description="Team / franchise name as in scorecards"),
    recent_limit: int = Query(20, ge=1, le=50),
    store=Depends(_get_store),
) -> TeamDetailResponse:
    """Recent match results (W/L/NR) and squad lists for one side."""
    conn, fmt = store
    decoded = urllib.parse.unquote(team).strip()
    raw = build_team_detail(conn, fmt, decoded, recent_limit=recent_limit)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Unknown team in this format: {decoded}")
    return TeamDetailResponse.model_validate(raw)


@router.get("/teams/proficient", response_model=TeamProficientPlayersResponse)
async def team_proficient_players(
    team: str = Query(..., min_length=1, description="Team / franchise name as in scorecards"),
    limit: int = Query(24, ge=1, le=50),
    min_innings: int = Query(3, ge=1, le=30, description="Min batting innings for this side to count as a batter signal"),
    min_spells: int = Query(3, ge=1, le=30, description="Min bowling spells for this side to count as a bowler signal"),
    store=Depends(_get_store),
) -> TeamProficientPlayersResponse:
    """Career WAR for players who have batted or bowled for this team, tagged batter / bowler / allrounder."""
    conn, fmt = store
    decoded = urllib.parse.unquote(team).strip()
    raw = build_team_proficient_players(
        conn,
        fmt,
        decoded,
        min_team_innings=min_innings,
        min_team_spells=min_spells,
        limit=limit,
    )
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Unknown team in this format: {decoded}")
    return TeamProficientPlayersResponse.model_validate(raw)
