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

import math
from typing import TYPE_CHECKING, Any

from data_loader import DEFAULT_FORMAT, MultiDataStore, VALID_FORMATS

from fastapi import APIRouter, Depends, HTTPException, Query
from schemas import (
    BatterProfile,
    BowlerProfile,
    CompareResponse,
    FormPoint,
    FormResponse,
    MatchupSummary,
    PlayerSummary,
)

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["compare"])

_COMPARE_FMT_PATTERN = "^(" + "|".join(VALID_FORMATS) + ")$"


# ── Dependency placeholders (overridden in app.py) ────────────────


def _get_multi_store():
    raise RuntimeError("MultiDataStore not initialised")


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


def _parse_ids(ids_str: str) -> list[str]:
    """Parse a comma-separated list of player IDs.

    Validates that 2–4 IDs are provided.

    Parameters
    ----------
    ids_str : str
        Comma-separated player IDs, e.g. "abc123,def456".

    Returns
    -------
    list[str]
        Parsed and stripped player IDs.

    Raises
    ------
    HTTPException
        If fewer than 2 or more than 4 IDs are provided.
    """
    raw = [pid.strip() for pid in ids_str.split(",") if pid.strip()]

    # Deduplicate while preserving order
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


def _formats_search_order(multi: MultiDataStore, preferred: str) -> list[str]:
    """Prefer *preferred* format, then other loaded formats."""
    avail = multi.available_formats
    if not avail:
        return []
    pref = preferred.lower()
    if pref in avail:
        return [pref] + [f for f in avail if f != pref]
    return list(avail)


def _find_batter_row_and_store(
    multi: MultiDataStore, pid: str, preferred_fmt: str
) -> tuple["DataStore", Any] | tuple[None, None]:
    from data_loader import get_batter_by_id

    order = _formats_search_order(multi, preferred_fmt or DEFAULT_FORMAT)
    for fmt in order:
        store = multi.get(fmt)
        row = get_batter_by_id(store, pid)
        if row is not None:
            return store, row
    return None, None


def _find_bowler_row_and_store(
    multi: MultiDataStore, pid: str, preferred_fmt: str
) -> tuple["DataStore", Any] | tuple[None, None]:
    from data_loader import get_bowler_by_id

    order = _formats_search_order(multi, preferred_fmt or DEFAULT_FORMAT)
    for fmt in order:
        store = multi.get(fmt)
        row = get_bowler_by_id(store, pid)
        if row is not None:
            return store, row
    return None, None


# ── Profile builders (reuse logic from player router) ─────────────


def _build_batter_profile_for_compare(row: Any, store: "DataStore") -> BatterProfile:
    """Build a BatterProfile for comparison (lighter than the full profile).

    Includes scores, grades, advanced metrics, components, and chase splits
    but omits the full matchup and similarity lists (those are available
    via the player-specific endpoints).
    """
    # Import the builder from the player router to avoid code duplication
    from routers.player import _build_batter_profile, _compute_batting_phase_splits

    batter_id = _safe_str(_get_val(row, "batter_id"))
    profile = _build_batter_profile(row, store, top_k_matchups=3)
    # Attach phase splits computed from innings data
    profile.phases = _compute_batting_phase_splits(store, batter_id)
    return profile


def _build_bowler_profile_for_compare(row: Any, store: "DataStore") -> BowlerProfile:
    """Build a BowlerProfile for comparison."""
    from routers.player import _build_bowler_profile, _compute_bowling_phase_splits

    bowler_id = _safe_str(_get_val(row, "bowler_id"))
    profile = _build_bowler_profile(row, store, top_k_matchups=3)
    profile.phases = _compute_bowling_phase_splits(store, bowler_id)
    return profile


# ── Route: GET /api/compare ───────────────────────────────────────


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
    multi: MultiDataStore = Depends(_get_multi_store),
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
    the batting profile takes precedence. Use ``/api/player/{id}/bowling``
    for the explicit bowling profile.

    **URL is shareable**: ``/compare?ids=abc123,def456``

    **Examples**:
    - ``/api/compare?ids=abc123,def456`` — compare two batters
    - ``/api/compare?ids=a,b,c`` — compare three players
    - ``/api/compare?ids=a,b,c,d`` — compare four players (max)

    Raises 400 if fewer than 2 or more than 4 IDs are provided.
    Raises 404 if any player ID is not found in either dataset.
    """
    player_ids = _parse_ids(ids)

    batters: list[BatterProfile] = []
    bowlers: list[BowlerProfile] = []
    not_found: list[str] = []

    for pid in player_ids:
        # Try batting first (takes precedence for all-rounders)
        store_b, bat_row = _find_batter_row_and_store(multi, pid, format)
        if bat_row is not None and store_b is not None:
            profile = _build_batter_profile_for_compare(bat_row, store_b)
            batters.append(profile)
            continue

        # Try bowling
        store_w, bowl_row = _find_bowler_row_and_store(multi, pid, format)
        if bowl_row is not None and store_w is not None:
            profile = _build_bowler_profile_for_compare(bowl_row, store_w)
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


# ── Route: GET /api/compare/form ──────────────────────────────────


@router.get("/compare/form")
async def compare_form(
    ids: str = Query(
        ...,
        description="Comma-separated player IDs (2–4)",
    ),
    multi: MultiDataStore = Depends(_get_multi_store),
    format: str = Query(
        DEFAULT_FORMAT,
        pattern=_COMPARE_FMT_PATTERN,
        description="Preferred dataset to resolve each player's form series.",
    ),
) -> list[FormResponse]:
    """Return form time-series for 2–4 players for overlaid comparison.

    Each player's form series is returned as a separate ``FormResponse``
    entry in the list. The frontend can overlay them on the same chart
    with different colours.

    Auto-detects whether each player is a batter or bowler and returns
    the appropriate form metrics.

    **Example**: ``/api/compare/form?ids=abc123,def456``
    """
    from data_loader import (
        get_batter_by_id,
        get_batter_form,
        get_bowler_by_id,
        get_bowler_form,
    )

    player_ids = _parse_ids(ids)
    results: list[FormResponse] = []

    for pid in player_ids:
        bat_store: "DataStore | None" = None
        bat_form = None
        for fmt in _formats_search_order(multi, format):
            st = multi.get(fmt)
            bf_try = get_batter_form(st, pid)
            if not bf_try.empty:
                bat_store = st
                bat_form = bf_try
                break

        # Try batting form first
        if bat_store is not None and bat_form is not None and not bat_form.empty:
            bat_row = get_batter_by_id(bat_store, pid)
            player_name = (
                _safe_str(_get_val(bat_row, "batter")) if bat_row is not None else ""
            )

            series: list[FormPoint] = []
            for _, row in bat_form.iterrows():  # type: ignore[union-attr]
                series.append(
                    FormPoint(
                        date=_safe_str(_get_val(row, "date")),
                        match_id=_safe_str(_get_val(row, "match_id")),
                        window_innings=_safe_int(_get_val(row, "window_innings")),
                        composite=_safe_float(_get_val(row, "window_composite")),
                        # 0-100 sub-scores
                        score_1=_safe_float(_get_val(row, "window_score_acceleration")),
                        score_2=_safe_float(_get_val(row, "window_score_power")),
                        score_3=_safe_float(_get_val(row, "window_score_control")),
                        score_1_label="acceleration",
                        score_2_label="power",
                        score_3_label="control",
                        # Peak annotation
                        is_peak_window=bool(_get_val(row, "is_peak_window", False)),
                        # Raw stats for tooltip
                        window_avg_runs=_safe_float(_get_val(row, "window_avg_runs")),
                        window_avg_sr=_safe_float(_get_val(row, "window_avg_sr")),
                        window_total_runs=_safe_float(
                            _get_val(row, "window_total_runs")
                        ),
                        window_fours=_safe_float(_get_val(row, "window_fours")),
                        window_sixes=_safe_float(_get_val(row, "window_sixes")),
                        # Raw component means
                        window_sr_vs_par=_safe_float(_get_val(row, "window_sr_vs_par")),
                        window_impact=_safe_float(_get_val(row, "window_impact")),
                        window_boundary_pct=_safe_float(
                            _get_val(row, "window_boundary_pct")
                        ),
                        window_six_rate=_safe_float(_get_val(row, "window_six_rate")),
                        window_dot_control=_safe_float(
                            _get_val(row, "window_dot_control")
                        ),
                        window_consistency=_safe_float(
                            _get_val(row, "window_consistency")
                        ),
                        window_rotation=_safe_float(_get_val(row, "window_rotation")),
                    )
                )
            results.append(
                FormResponse(
                    player_id=pid,
                    player_name=player_name,
                    series=series,
                )
            )
            continue

        bowl_store: "DataStore | None" = None
        bowl_form = None
        for fmt in _formats_search_order(multi, format):
            st = multi.get(fmt)
            bf_try = get_bowler_form(st, pid)
            if not bf_try.empty:
                bowl_store = st
                bowl_form = bf_try
                break

        # Try bowling form
        if bowl_store is not None and bowl_form is not None and not bowl_form.empty:
            bowl_row = get_bowler_by_id(bowl_store, pid)
            player_name = (
                _safe_str(_get_val(bowl_row, "bowler")) if bowl_row is not None else ""
            )

            series = []
            for _, row in bowl_form.iterrows():  # type: ignore[union-attr]
                series.append(
                    FormPoint(
                        date=_safe_str(_get_val(row, "date")),
                        match_id=_safe_str(_get_val(row, "match_id")),
                        window_innings=_safe_int(_get_val(row, "window_spells")),
                        composite=_safe_float(_get_val(row, "window_composite")),
                        # 0-100 sub-scores
                        score_1=_safe_float(_get_val(row, "window_score_accuracy")),
                        score_2=_safe_float(_get_val(row, "window_score_control")),
                        score_3=_safe_float(_get_val(row, "window_score_threat")),
                        score_1_label="accuracy",
                        score_2_label="control",
                        score_3_label="threat",
                        # Peak annotation
                        is_peak_window=bool(_get_val(row, "is_peak_window", False)),
                        # Raw stats for tooltip (not applicable for bowling)
                        window_avg_runs=None,
                        window_avg_sr=None,
                        window_total_runs=None,
                        window_fours=None,
                        window_sixes=None,
                        # Raw component means
                        window_economy=_safe_float(_get_val(row, "window_economy")),
                        window_dot_pct=_safe_float(_get_val(row, "window_dot_pct")),
                        window_wickets_per_spell=_safe_float(
                            _get_val(row, "window_wickets_per_spell")
                        ),
                        window_total_wickets=_safe_float(
                            _get_val(row, "window_total_wickets")
                        ),
                        window_economy_vs_par=_safe_float(
                            _get_val(row, "window_economy_vs_par")
                        ),
                        window_quality_wickets=_safe_float(
                            _get_val(row, "window_quality_wickets")
                        ),
                        window_threat_pressure=_safe_float(
                            _get_val(row, "window_threat_pressure")
                        ),
                    )
                )
            results.append(
                FormResponse(
                    player_id=pid,
                    player_name=player_name,
                    series=series,
                )
            )
            continue

        # No form data — return empty series
        results.append(FormResponse(player_id=pid, player_name="", series=[]))

    return results


# ── Route: GET /api/compare/shared-matchups ───────────────────────


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
    multi: MultiDataStore = Depends(_get_multi_store),
    format: str = Query(
        DEFAULT_FORMAT,
        pattern=_COMPARE_FMT_PATTERN,
        description="Preferred dataset when resolving each batter's matchup rows.",
    ),
) -> dict:
    """Find bowlers that two or more compared batters have both faced.

    Returns a list of shared matchups, where each entry contains the
    bowler's name/ID and each batter's stats against that bowler. This
    enables apples-to-apples comparison ("Both faced Rashid Khan:
    Kohli SR 167, Buttler SR 141").

    Only returns matchups where **all** provided batters have faced
    the bowler with at least ``min_balls`` each.

    **Example**: ``/api/compare/shared-matchups?ids=abc,def&min_balls=10``

    Response format:
    ```json
    {
      "batter_ids": ["abc", "def"],
      "shared": [
        {
          "bowler_id": "xyz",
          "bowler_name": "Rashid Khan",
          "matchups": {
            "abc": { "balls": 28, "runs": 47, "sr": 167.9, ... },
            "def": { "balls": 34, "runs": 48, "sr": 141.2, ... }
          }
        }
      ]
    }
    ```
    """
    import pandas as pd

    batter_ids = _parse_ids(ids)

    # For each batter, get the set of bowlers they've faced
    # (with min_balls filter)
    bowler_sets: list[set[str]] = []
    batter_matchup_dfs: dict[str, pd.DataFrame] = {}

    for bid in batter_ids:
        st_b, _row = _find_batter_row_and_store(multi, bid, format)
        if st_b is None or st_b.matchups.empty:
            bowler_sets.append(set())
            batter_matchup_dfs[bid] = pd.DataFrame()
            continue
        mask = (st_b.matchups["batter_id"] == bid) & (
            st_b.matchups["balls_faced"] >= min_balls
        )
        bdf = st_b.matchups.loc[mask]
        if bdf.empty:
            bowler_sets.append(set())
        else:
            bowler_sets.append(set(bdf["bowler_id"].unique()))
        batter_matchup_dfs[bid] = bdf

    # Find bowlers common to ALL batters
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
            bdf = batter_matchup_dfs[bid]
            bmask = bdf["bowler_id"] == bowler_id
            brows = bdf.loc[bmask]
            if brows.empty:
                continue

            brow = brows.iloc[0]
            # Set bowler name from first match
            if not entry["bowler_name"]:
                entry["bowler_name"] = _safe_str(_get_val(brow, "bowler"))

            entry["matchups"][bid] = {
                "balls": _safe_int(_get_val(brow, "balls_faced")),
                "runs": _safe_int(_get_val(brow, "runs_scored")),
                "sr": _safe_float(_get_val(brow, "strike_rate")),
                "dismissals": _safe_int(_get_val(brow, "dismissals")),
                "dots": _safe_int(_get_val(brow, "dots")),
                "fours": _safe_int(_get_val(brow, "fours")),
                "sixes": _safe_int(_get_val(brow, "sixes")),
                "dot_pct": _safe_float(_get_val(brow, "dot_pct")),
                "boundary_pct": _safe_float(_get_val(brow, "boundary_pct")),
                "dominance_index": _safe_float(_get_val(brow, "dominance_index")),
            }

        shared.append(entry)

    # Sort shared matchups by total balls across all batters (descending)
    # so the most meaningful matchups appear first
    def _total_balls(entry: dict) -> int:
        return sum(m.get("balls", 0) for m in entry["matchups"].values())

    shared.sort(key=_total_balls, reverse=True)

    return {
        "batter_ids": batter_ids,
        "shared": shared[:limit],
    }
