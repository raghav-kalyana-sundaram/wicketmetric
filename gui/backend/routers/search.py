"""
Search router — /api/search endpoint with trigram fuzzy matching.

Provides player search with filtering by role, country, archetype,
provisional status, and minimum innings. Results are ranked by
trigram overlap with exact-match boosting and overall-score tie-breaking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from schemas import PlayerSummary, SearchResponse

if TYPE_CHECKING:
    from search_index import TrigramIndex

router = APIRouter(prefix="/api", tags=["search"])


def _get_search_index():
    """Dependency placeholder — overridden in app.py at startup."""
    raise RuntimeError("Search index not initialised")


@router.get("/search", response_model=SearchResponse)
async def search_players(
    q: str = Query("", description="Search query (player name or substring)"),
    role: str | None = Query(
        None, description="Filter by role: bat, bowl, or all-rounder"
    ),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum innings/matches"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    index: "TrigramIndex" = Depends(_get_search_index),
) -> SearchResponse:
    """Fuzzy search for players by name with optional filters.

    The trigram index supports:
    - Exact substring matching ("Kohli" → "V Kohli")
    - Fuzzy matching ("Bumra" → "JJ Bumrah")
    - Country-filtered search ("India" + "K" → all Indian players starting with K)

    Results are ranked by trigram overlap, with bonuses for:
    - Exact full match (+1000)
    - Name starts with query (+500)
    - Name contains query as substring (+200)
    - Non-provisional players (+50)
    - Higher overall score (tie-break)
    """
    raw_results = index.search(
        query=q.strip(),
        role=role,
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        limit=limit,
    )

    results = []
    for entry in raw_results:
        results.append(
            PlayerSummary(
                id=entry.get("id", ""),
                name=entry.get("name", ""),
                country=entry.get("country", ""),
                role=entry.get("role", "bat"),
                archetype=entry.get("archetype", ""),
                grade_overall=entry.get("grade_overall", "D"),
                innings_count=entry.get("innings_count", 0),
                total_runs=entry.get("total_runs", 0),
                career_sr=entry.get("career_sr"),
                career_avg=entry.get("career_avg"),
                score_1=entry.get("score_1"),
                score_2=entry.get("score_2"),
                score_3=entry.get("score_3"),
                score_1_label=entry.get("score_1_label", "acceleration"),
                score_2_label=entry.get("score_2_label", "power"),
                score_3_label=entry.get("score_3_label", "control"),
                is_provisional=entry.get("is_provisional", True),
                overall_score=entry.get("overall_score"),
            )
        )

    return SearchResponse(results=results, total=len(results))


@router.get("/search/countries", response_model=list[str])
async def list_countries(
    index: "TrigramIndex" = Depends(_get_search_index),
) -> list[str]:
    """Return a sorted list of all countries in the dataset.

    Useful for populating country filter dropdowns in the frontend.
    """
    return index.all_countries()


@router.get("/search/archetypes", response_model=dict[str, list[str]])
async def list_archetypes(
    index: "TrigramIndex" = Depends(_get_search_index),
) -> dict[str, list[str]]:
    """Return sorted lists of archetypes keyed by role ('bat' and 'bowl').

    Useful for populating archetype filter dropdowns in the frontend.
    """
    return index.all_archetypes()


@router.get("/search/autocomplete", response_model=list[PlayerSummary])
async def autocomplete(
    q: str = Query("", min_length=2, description="Search query (min 2 characters)"),
    role: str | None = Query(None, description="Filter by role"),
    country: str | None = Query(None, description="Filter by country"),
    limit: int = Query(8, ge=1, le=20, description="Max suggestions"),
    index: "TrigramIndex" = Depends(_get_search_index),
) -> list[PlayerSummary]:
    """Lightweight autocomplete endpoint for search-as-you-type inputs.

    Returns up to `limit` player suggestions (default 8) matching the
    query string. Designed to be called on every keystroke after the
    user has typed at least 2 characters.

    Frontend should debounce calls by ~150ms.
    """
    raw_results = index.search(
        query=q.strip(),
        role=role,
        country=country,
        limit=limit,
    )

    return [
        PlayerSummary(
            id=entry.get("id", ""),
            name=entry.get("name", ""),
            country=entry.get("country", ""),
            role=entry.get("role", "bat"),
            archetype=entry.get("archetype", ""),
            grade_overall=entry.get("grade_overall", "D"),
            innings_count=entry.get("innings_count", 0),
            total_runs=entry.get("total_runs", 0),
            career_sr=entry.get("career_sr"),
            career_avg=entry.get("career_avg"),
            score_1=entry.get("score_1"),
            score_2=entry.get("score_2"),
            score_3=entry.get("score_3"),
            score_1_label=entry.get("score_1_label", "acceleration"),
            score_2_label=entry.get("score_2_label", "power"),
            score_3_label=entry.get("score_3_label", "control"),
            is_provisional=entry.get("is_provisional", True),
            overall_score=entry.get("overall_score"),
        )
        for entry in raw_results
    ]
