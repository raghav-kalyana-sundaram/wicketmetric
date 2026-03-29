"""
Rankings router — /api/rankings/{role} with sorting, filtering, pagination.

Provides sortable, filterable leaderboards for batting and bowling metrics.
Supports sorting by any numeric column, filtering by country/archetype/
provisional status/minimum innings, and cursor-based pagination.

Endpoints:
- GET /api/rankings/bat   → Batting leaderboard
- GET /api/rankings/bowl  → Bowling leaderboard
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query
from data_loader import (
    DEFAULT_FORMAT,
    VALID_FORMATS,
    activity_reference_cutoff,
)
from rating_display import (
    apply_display_rating_sort_column,
    batting_display_ratings,
    bowling_display_ratings,
    drop_display_rating_sort_column,
)
from schemas import LeaderboardResponse, PlayerSummary

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["rankings"])

_FORMAT_PATTERN = "^(" + "|".join(VALID_FORMATS) + ")$"


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


def _recent_team_from_row(row: Any) -> str | None:
    """Latest-match team from merged ``recent_team`` column."""
    v = (
        row.get("recent_team")
        if hasattr(row, "get")
        else getattr(row, "recent_team", None)
    )
    s = _safe_str(v, "").strip()
    return s or None


def _metric_map(row: Any, metric_keys: set[str]) -> dict[str, float | None]:
    """Extract leaderboard-sortable metrics into a compact metric map."""
    metrics: dict[str, float | None] = {}
    for key in metric_keys:
        if hasattr(row, 'index') and key not in row.index:
            continue
        value = row.get(key) if hasattr(row, 'get') else getattr(row, key, None)
        metrics[key] = _safe_float(value)
    return metrics


# ── Valid sort columns per role ───────────────────────────────────

BATTING_SORT_COLUMNS = {
    "score_acceleration",
    "score_power",
    "score_control",
    "rating_current",
    "rating_overall",
    "overall_score",
    "career_sr",
    "career_avg",
    "innings_count",
    "total_runs",
    "total_balls",
    "total_fours",
    "total_sixes",
    "war_batting",
    "war_batting_rate",
    "clutch_index",
    "clutch_sr_delta",
    "chase_master_index",
    "chase_master_full",
    "flat_track_index",
    "venue_adjusted_composite",
    "selfless_index",
    "anchor_cost_ratio",
    "avg_balls_to_par",
    "avg_dominance",
    "pct_dominant",
    "matchup_consistency",
    "peak_composite_batting",
    "peak_window_composite",
}

BOWLING_SORT_COLUMNS = {
    "score_accuracy",
    "score_control",
    "score_threat",
    "rating_current",
    "rating_overall",
    "overall_score",
    "career_economy",
    "career_sr_bowl",
    "career_dot_pct",
    "matches",
    "total_wickets",
    "total_overs",
    "total_runs_conceded",
    "war_bowling",
    "war_bowling_rate",
    "clutch_index_bowl",
    "flat_track_index_bowl",
    "avg_dominance_bowl",
    "pct_dominant_bowl",
    "bowled_lbw_pct",
    "peak_composite_bowling",
    "peak_window_composite",
}


# ── Filtering logic ───────────────────────────────────────────────


def _apply_filters(
    df: "pd.DataFrame",
    *,
    country: str | None = None,
    archetype: str | None = None,
    provisional: bool | None = None,
    min_innings: int | None = None,
    position_group: str | None = None,
    phase_group: str | None = None,
    modal_slot: int | None = None,
    provisional_col: str = "is_provisional_bat",
    innings_col: str = "innings_count",
) -> "pd.DataFrame":
    """Apply all leaderboard filters to a career DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Career-level DataFrame (batting or bowling).
    country : str, optional
        Filter by country (case-insensitive exact match).
    archetype : str, optional
        Filter by archetype (case-insensitive exact match).
    provisional : bool, optional
        True = only provisional, False = exclude provisional, None = all.
    min_innings : int, optional
        Minimum innings (batting) or matches (bowling).
    position_group : str, optional
        Filter by batting position group (top_order, middle_order, etc.).
    phase_group : str, optional
        Filter by bowling phase group (powerplay, middle, death, etc.).
    modal_slot : int, optional
        Batting only: filter rows where ``modal_position`` equals this slot (1–11).
    provisional_col : str
        Name of the provisional boolean column.
    innings_col : str
        Name of the innings/matches count column.

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame.
    """
    import pandas as pd

    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    # Country filter (case-insensitive)
    if country and "country" in df.columns:
        mask = mask & (df["country"].str.lower() == country.lower().strip())

    # Archetype filter (case-insensitive)
    if archetype and "archetype" in df.columns:
        mask = mask & (df["archetype"].str.lower() == archetype.lower().strip())

    # Provisional filter
    if provisional is not None and provisional_col in df.columns:
        if provisional:
            mask = mask & (df[provisional_col] == True)  # noqa: E712
        else:
            mask = mask & (df[provisional_col] != True)  # noqa: E712

    # Minimum innings filter
    if min_innings is not None and min_innings > 0 and innings_col in df.columns:
        mask = mask & (df[innings_col] >= min_innings)

    # Position group filter (batting)
    if position_group and "position_group" in df.columns:
        mask = mask & (
            df["position_group"].str.lower() == position_group.lower().strip()
        )

    # Phase group filter (bowling)
    if phase_group and "phase_group" in df.columns:
        mask = mask & (df["phase_group"].str.lower() == phase_group.lower().strip())

    # Modal batting slot 1–11 (careers must expose ``modal_position``)
    if modal_slot is not None and "modal_position" in df.columns:
        try:
            slot_i = int(modal_slot)
        except (TypeError, ValueError):
            slot_i = None
        if slot_i is not None and 1 <= slot_i <= 11:
            mp = pd.to_numeric(df["modal_position"], errors="coerce")
            mask = mask & (mp == slot_i)

    return df.loc[mask]


def _activity_fields_from_row(
    row: Any, cutoff: "pd.Timestamp"
) -> tuple[str | None, bool]:
    """ISO last-match date and whether player is active vs *cutoff*."""
    import pandas as pd

    lm_val = (
        row.get("last_match_date")
        if hasattr(row, "get")
        else getattr(row, "last_match_date", None)
    )
    if lm_val is None:
        return None, False
    ts = pd.Timestamp(lm_val)
    if pd.isna(ts):
        return None, False
    last_s = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
    return last_s, bool(ts >= cutoff)


def _filter_by_activity(
    df: "pd.DataFrame",
    activity: str,
    cutoff: "pd.Timestamp",
) -> "pd.DataFrame":
    """Keep active, retired, or all players using ``last_match_date`` vs *cutoff*."""
    import pandas as pd

    act = (activity or "all").lower().strip()
    if df.empty or act == "all":
        return df
    if "last_match_date" not in df.columns:
        return df.iloc[0:0] if act == "active" else df

    lm = pd.to_datetime(df["last_match_date"], errors="coerce")
    if act == "active":
        return df.loc[lm.notna() & (lm >= cutoff)]
    if act == "retired":
        return df.loc[lm.isna() | (lm < cutoff)]
    return df


# ── Row → PlayerSummary converters ────────────────────────────────


def _bat_row_to_summary(
    row: Any, fmt: str, activity_cutoff: "pd.Timestamp"
) -> PlayerSummary:
    """Convert a batting career row to a PlayerSummary."""
    last_md, active_flag = _activity_fields_from_row(row, activity_cutoff)
    rating_overall, rating_current = batting_display_ratings(row)
    mp = _safe_int(
        row.get("modal_position") if hasattr(row, "get") else getattr(row, "modal_position", 0)
    )
    modal_position = mp if 1 <= mp <= 11 else None
    return PlayerSummary(
        id=_safe_str(
            row.get("batter_id")
            if hasattr(row, "get")
            else getattr(row, "batter_id", "")
        ),
        name=_safe_str(
            row.get("batter") if hasattr(row, "get") else getattr(row, "batter", "")
        ),
        country=_safe_str(
            row.get("country") if hasattr(row, "get") else getattr(row, "country", "")
        ),
        role="bat",
        archetype=_safe_str(
            row.get("archetype")
            if hasattr(row, "get")
            else getattr(row, "archetype", "")
        ),
        grade_overall=_safe_str(
            row.get("overall_grade")
            if hasattr(row, "get")
            else getattr(row, "overall_grade", "D"),
            "D",
        ),
        innings_count=_safe_int(
            row.get("innings_count")
            if hasattr(row, "get")
            else getattr(row, "innings_count", 0)
        ),
        total_runs=_safe_int(
            row.get("total_runs")
            if hasattr(row, "get")
            else getattr(row, "total_runs", 0)
        ),
        career_sr=_safe_float(
            row.get("career_sr")
            if hasattr(row, "get")
            else getattr(row, "career_sr", None)
        ),
        career_avg=_safe_float(
            row.get("career_avg")
            if hasattr(row, "get")
            else getattr(row, "career_avg", None)
        ),
        score_1=_safe_float(
            row.get("score_acceleration")
            if hasattr(row, "get")
            else getattr(row, "score_acceleration", None)
        ),
        score_2=_safe_float(
            row.get("score_power")
            if hasattr(row, "get")
            else getattr(row, "score_power", None)
        ),
        score_3=_safe_float(
            row.get("score_control")
            if hasattr(row, "get")
            else getattr(row, "score_control", None)
        ),
        score_1_label="acceleration",
        score_2_label="power",
        score_3_label="control",
        is_provisional=bool(
            row.get("is_provisional_bat")
            if hasattr(row, "get")
            else getattr(row, "is_provisional_bat", True)
        ),
        overall_score=_safe_float(
            row.get("overall_score")
            if hasattr(row, "get")
            else getattr(row, "overall_score", None)
        ),
        metrics=_metric_map(row, BATTING_SORT_COLUMNS),
        last_match_date=last_md,
        is_active=active_flag,
        rating_current=rating_current,
        rating_overall=rating_overall,
        modal_position=modal_position,
    )


def _bowl_row_to_summary(
    row: Any, fmt: str, activity_cutoff: "pd.Timestamp"
) -> PlayerSummary:
    """Convert a bowling career row to a PlayerSummary."""
    last_md, active_flag = _activity_fields_from_row(row, activity_cutoff)
    rating_overall, rating_current = bowling_display_ratings(row)
    return PlayerSummary(
        id=_safe_str(
            row.get("bowler_id")
            if hasattr(row, "get")
            else getattr(row, "bowler_id", "")
        ),
        name=_safe_str(
            row.get("bowler") if hasattr(row, "get") else getattr(row, "bowler", "")
        ),
        country=_safe_str(
            row.get("country") if hasattr(row, "get") else getattr(row, "country", "")
        ),
        role="bowl",
        archetype=_safe_str(
            row.get("archetype")
            if hasattr(row, "get")
            else getattr(row, "archetype", "")
        ),
        grade_overall=_safe_str(
            row.get("overall_grade")
            if hasattr(row, "get")
            else getattr(row, "overall_grade", "D"),
            "D",
        ),
        innings_count=_safe_int(
            row.get("matches") if hasattr(row, "get") else getattr(row, "matches", 0)
        ),
        total_runs=_safe_int(
            row.get("total_wickets")
            if hasattr(row, "get")
            else getattr(row, "total_wickets", 0)
        ),
        career_sr=_safe_float(
            row.get("career_economy")
            if hasattr(row, "get")
            else getattr(row, "career_economy", None)
        ),
        career_avg=_safe_float(
            row.get("career_sr_bowl")
            if hasattr(row, "get")
            else getattr(row, "career_sr_bowl", None)
        ),
        score_1=_safe_float(
            row.get("score_accuracy")
            if hasattr(row, "get")
            else getattr(row, "score_accuracy", None)
        ),
        score_2=_safe_float(
            row.get("score_control")
            if hasattr(row, "get")
            else getattr(row, "score_control", None)
        ),
        score_3=_safe_float(
            row.get("score_threat")
            if hasattr(row, "get")
            else getattr(row, "score_threat", None)
        ),
        score_1_label="accuracy",
        score_2_label="control",
        score_3_label="threat",
        is_provisional=bool(
            row.get("is_provisional_bowl")
            if hasattr(row, "get")
            else getattr(row, "is_provisional_bowl", True)
        ),
        overall_score=_safe_float(
            row.get("overall_score")
            if hasattr(row, "get")
            else getattr(row, "overall_score", None)
        ),
        metrics=_metric_map(row, BOWLING_SORT_COLUMNS),
        last_match_date=last_md,
        is_active=active_flag,
        rating_current=rating_current,
        rating_overall=rating_overall,
        modal_position=None,
        recent_team=_recent_team_from_row(row),
    )


def _batting_leaderboard_source_df(
    store: "DataStore",
    *,
    ctx_entry_phase: str,
    ctx_knockouts_only: bool,
    ctx_chase_high_rpo: bool,
) -> "pd.DataFrame":
    """Pick the career table for batting rankings (full vs context slice)."""
    import pandas as pd

    if ctx_knockouts_only or ctx_chase_high_rpo:
        return pd.DataFrame()
    phase = (ctx_entry_phase or "none").strip().lower()
    if phase == "early":
        return getattr(store, "bat_careers_ctx_entry_early", pd.DataFrame())
    if phase == "death":
        return getattr(store, "bat_careers_ctx_entry_death", pd.DataFrame())
    return store.bat_careers


# ── Route: GET /api/rankings/bat ──────────────────────────────────


@router.get("/rankings/bat", response_model=LeaderboardResponse)
async def batting_leaderboard(
    sort: str = Query(
        "rating_current",
        description=(
            "Column to sort by. Includes rating_current, rating_overall (display "
            "ratings), overall_score (pipeline composite), score_acceleration, "
            "score_power, score_control, career_sr, career_avg, innings_count, "
            "total_runs, war_batting, clutch_index, chase_master_index, "
            "flat_track_index, etc."
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    position_group: str | None = Query(
        None,
        description=(
            "Filter by batting position group: "
            "top_order, middle_order, lower_order, opener"
        ),
    ),
    modal_slot: int | None = Query(
        None,
        ge=1,
        le=11,
        description="Filter by modal batting entry position (1–11).",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum innings played"),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    activity: str = Query(
        "active",
        description=(
            "Player pool: active (last match within 1y for T20I, 2y for IPL), "
            "retired, or all"
        ),
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    ctx_entry_phase: str = Query(
        "none",
        description=(
            "Innings entry context: none (full career), early (first ball overs 1–4), "
            "death (first ball overs 16–20)."
        ),
        pattern="^(none|early|death)$",
    ),
    ctx_knockouts_only: bool = Query(
        False,
        description="Knockout/playoff-only leaderboard (not yet supported — returns empty).",
    ),
    ctx_chase_high_rpo: bool = Query(
        False,
        description="High required-rate chase leaderboard (not yet supported — returns empty).",
    ),
    store: "DataStore" = Depends(_get_store),
) -> LeaderboardResponse:
    """Return a sorted, filterable, paginated batting leaderboard.

    All filter parameters are combinable and reflected in URL query params
    for shareability.

    Sort columns include all 0–100 scores, career aggregates, and
    advanced metrics (WAR, Clutch, Chase Master, Flat Track Index, etc.).

    **Default behaviour**: sorted by ``rating_current`` descending,
    **active players only** (see ``activity``), first page of 25 results.

    **Examples**:
    - ``/api/rankings/bat?sort=score_power&order=desc&min_innings=20``
    - ``/api/rankings/bat?country=India&archetype=Chase+Master``
    - ``/api/rankings/bat?sort=war_batting&provisional=false&per_page=50``
    - ``/api/rankings/bat?activity=all`` — include retired players
    """
    source = _batting_leaderboard_source_df(
        store,
        ctx_entry_phase=ctx_entry_phase,
        ctx_knockouts_only=ctx_knockouts_only,
        ctx_chase_high_rpo=ctx_chase_high_rpo,
    )
    if source.empty:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    ac = activity_reference_cutoff(store, format)

    # Validate sort column
    sort_col = sort.strip()
    if sort_col not in BATTING_SORT_COLUMNS:
        # Fall back if invalid column provided (user-friendly for URL tinkering)
        if sort_col in source.columns:
            pass  # Allow any column that exists in the DataFrame
        else:
            sort_col = "rating_current"

    # Apply filters
    filtered = _apply_filters(
        source,
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        position_group=position_group,
        modal_slot=modal_slot,
        provisional_col="is_provisional_bat",
        innings_col="innings_count",
    )

    filtered = _filter_by_activity(filtered, activity, ac)

    total = len(filtered)
    if total == 0:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    # Sort (display ratings are computed columns — see rating_display module)
    filtered, eff_sort_col = apply_display_rating_sort_column(filtered, sort_col, "bat")
    ascending = order.lower() == "asc"
    if eff_sort_col in filtered.columns:
        filtered = filtered.sort_values(
            eff_sort_col, ascending=ascending, na_position="last"
        )
    else:
        filtered = filtered.sort_values(
            "overall_score", ascending=False, na_position="last"
        )
    filtered = drop_display_rating_sort_column(filtered)

    # Paginate
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    end = start + per_page
    page_df = filtered.iloc[start:end]

    # Convert rows to PlayerSummary
    players: list[PlayerSummary] = []
    for _, row in page_df.iterrows():
        players.append(_bat_row_to_summary(row, format, ac))

    return LeaderboardResponse(
        players=players,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# ── Route: GET /api/rankings/bowl ─────────────────────────────────


@router.get("/rankings/bowl", response_model=LeaderboardResponse)
async def bowling_leaderboard(
    sort: str = Query(
        "rating_current",
        description=(
            "Column to sort by. Includes rating_current, rating_overall (display "
            "ratings), overall_score (pipeline composite), score_accuracy, "
            "score_control, score_threat, career_economy, career_sr_bowl, "
            "career_dot_pct, matches, total_wickets, war_bowling, "
            "clutch_index_bowl, flat_track_index_bowl, etc."
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    country: str | None = Query(
        None, description="Filter by country (case-insensitive)"
    ),
    archetype: str | None = Query(
        None, description="Filter by archetype (case-insensitive)"
    ),
    phase_group: str | None = Query(
        None,
        description="Filter by bowling phase group: powerplay, middle, death",
    ),
    min_innings: int | None = Query(None, ge=0, description="Minimum matches bowled"),
    provisional: bool | None = Query(
        None,
        description="True = only provisional, False = exclude provisional, None = all",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    activity: str = Query(
        "active",
        description=(
            "Player pool: active (last match within 1y for T20I, 2y for IPL), "
            "retired, or all"
        ),
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    store: "DataStore" = Depends(_get_store),
) -> LeaderboardResponse:
    """Return a sorted, filterable, paginated bowling leaderboard.

    All filter parameters are combinable and reflected in URL query params
    for shareability.

    Sort columns include all 0–100 scores, career aggregates, and
    advanced metrics (WAR, Clutch, Flat Track Index, etc.).

    **Default behaviour**: sorted by ``rating_current`` descending,
    **active players only**, first page of 25 results.

    **Note on sort direction**: For bowling economy and SR, you might want
    ``order=asc`` (lower is better). The API does **not** auto-invert —
    it always respects the explicit ``order`` parameter.

    **Examples**:
    - ``/api/rankings/bowl?sort=score_threat&order=desc&min_innings=10``
    - ``/api/rankings/bowl?country=Australia&sort=career_economy&order=asc``
    - ``/api/rankings/bowl?sort=war_bowling&provisional=false&per_page=50``
    """
    if store.bowl_careers.empty:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    ac = activity_reference_cutoff(store, format)

    # Validate sort column
    sort_col = sort.strip()
    if sort_col not in BOWLING_SORT_COLUMNS:
        if sort_col in store.bowl_careers.columns:
            pass  # Allow any column that exists in the DataFrame
        else:
            sort_col = "rating_current"

    # Apply filters
    filtered = _apply_filters(
        store.bowl_careers,
        country=country,
        archetype=archetype,
        provisional=provisional,
        min_innings=min_innings,
        phase_group=phase_group,
        provisional_col="is_provisional_bowl",
        innings_col="matches",
    )

    filtered = _filter_by_activity(filtered, activity, ac)

    total = len(filtered)
    if total == 0:
        return LeaderboardResponse(
            players=[], total=0, page=page, per_page=per_page, total_pages=0
        )

    # Sort (display ratings are computed columns — see apply_display_rating_sort_column)
    filtered, eff_sort_col = apply_display_rating_sort_column(filtered, sort_col, "bowl")
    ascending = order.lower() == "asc"
    if eff_sort_col in filtered.columns:
        filtered = filtered.sort_values(
            eff_sort_col, ascending=ascending, na_position="last"
        )
    else:
        filtered = filtered.sort_values(
            "overall_score", ascending=False, na_position="last"
        )
    filtered = drop_display_rating_sort_column(filtered)

    # Paginate
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    end = start + per_page
    page_df = filtered.iloc[start:end]

    # Convert rows to PlayerSummary
    players: list[PlayerSummary] = []
    for _, row in page_df.iterrows():
        players.append(_bowl_row_to_summary(row, format, ac))

    return LeaderboardResponse(
        players=players,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# ── Route: GET /api/rankings/columns/bat ──────────────────────────


@router.get("/rankings/columns/bat", response_model=list[str])
async def batting_sort_columns() -> list[str]:
    """Return the list of valid sort columns for the batting leaderboard.

    Useful for the frontend to dynamically build sort dropdowns.
    """
    return sorted(BATTING_SORT_COLUMNS)


# ── Route: GET /api/rankings/columns/bowl ─────────────────────────


@router.get("/rankings/columns/bowl", response_model=list[str])
async def bowling_sort_columns() -> list[str]:
    """Return the list of valid sort columns for the bowling leaderboard.

    Useful for the frontend to dynamically build sort dropdowns.
    """
    return sorted(BOWLING_SORT_COLUMNS)


# ── Route: GET /api/rankings/top ──────────────────────────────────


@router.get("/rankings/top")
async def top_players(
    role: str = Query("bat", description="Role: bat or bowl"),
    metric: str = Query("overall_score", description="Metric to rank by"),
    limit: int = Query(5, ge=1, le=50, description="Number of top players"),
    provisional: bool | None = Query(
        None,
        description=(
            "True = only provisional, False = exclude provisional, "
            "omit = all (default for dashboard cards)"
        ),
    ),
    min_innings: int | None = Query(None, description="Minimum innings/matches"),
    activity: str = Query(
        "active",
        description="active, retired, or all (same recency rules as main leaderboard)",
        pattern="^(active|retired|all)$",
    ),
    format: str = Query(
        DEFAULT_FORMAT,
        description="Dataset slice (e.g. mens_t20i, womens_t20i, womens_ipl).",
        pattern=_FORMAT_PATTERN,
    ),
    store: "DataStore" = Depends(_get_store),
) -> list[PlayerSummary]:
    """Quick endpoint to get top-N players for a specific metric.

    Designed for the homepage dashboard cards (e.g. "Top 5 Power Hitters",
    "Top 5 Bowlers by Threat"). Lightweight alternative to the full
    leaderboard endpoint.

    **Examples**:
    - ``/api/rankings/top?role=bat&metric=score_power&limit=5``
    - ``/api/rankings/top?role=bowl&metric=score_threat&limit=10``
    - ``/api/rankings/top?role=bat&metric=clutch_index&limit=5&min_innings=20``
    """
    ac = activity_reference_cutoff(store, format)

    if role == "bowl":
        if store.bowl_careers.empty:
            return []

        filtered = _apply_filters(
            store.bowl_careers,
            provisional=provisional,
            min_innings=min_innings,
            provisional_col="is_provisional_bowl",
            innings_col="matches",
        )
        filtered = _filter_by_activity(filtered, activity, ac)

        if filtered.empty:
            return []

        m = metric.strip()
        filtered, eff = apply_display_rating_sort_column(filtered, m, "bowl")
        if eff not in filtered.columns:
            eff = "overall_score"
        if eff not in filtered.columns:
            return []
        top = filtered.nlargest(limit, eff)
        top = drop_display_rating_sort_column(top)
        return [_bowl_row_to_summary(row, format, ac) for _, row in top.iterrows()]

    else:
        if store.bat_careers.empty:
            return []

        filtered = _apply_filters(
            store.bat_careers,
            provisional=provisional,
            min_innings=min_innings,
            provisional_col="is_provisional_bat",
            innings_col="innings_count",
        )
        filtered = _filter_by_activity(filtered, activity, ac)

        if filtered.empty:
            return []

        m = metric.strip()
        filtered, eff = apply_display_rating_sort_column(filtered, m, "bat")
        if eff not in filtered.columns:
            eff = "overall_score"
        if eff not in filtered.columns:
            return []
        top = filtered.nlargest(limit, eff)
        top = drop_display_rating_sort_column(top)
        return [_bat_row_to_summary(row, format, ac) for _, row in top.iterrows()]
