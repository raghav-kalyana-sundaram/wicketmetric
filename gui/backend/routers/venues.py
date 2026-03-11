"""
Venues router — /api/venues endpoints.

Provides:
- GET /api/venues              → All venue baselines (difficulty, par SR, etc.)
- GET /api/venues/{venue_name} → Detailed breakdown for a single venue
- GET /api/venues/{venue_name}/players → Player performance at a specific venue
- GET /api/player/{id}/venues  → A player's venue-by-venue splits
- GET /api/venues/flat-track-index → Flat Track Bully leaderboard
"""

from __future__ import annotations

import math
import urllib.parse
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from schemas import VenueBaseline, VenueListResponse

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


def _venue_row_to_baseline(row: Any) -> VenueBaseline:
    """Convert a venue baselines DataFrame row to a VenueBaseline schema."""
    return VenueBaseline(
        venue=_safe_str(_get_val(row, "venue")),
        matches=_safe_int(_get_val(row, "venue_matches")),
        avg_par_sr=_safe_float(_get_val(row, "venue_avg_par_sr")),
        boundary_rate=_safe_float(_get_val(row, "venue_avg_boundary_rate")),
        dot_pct=_safe_float(_get_val(row, "venue_avg_dot_pct")),
        difficulty_score=_safe_float(_get_val(row, "venue_difficulty")),
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
        0,
        ge=0,
        description="Minimum number of matches played at the venue",
    ),
    store: "DataStore" = Depends(_get_store),
) -> VenueListResponse:
    """Return all venue baselines with difficulty scores.

    Each venue includes:
    - **difficulty_score**: normalised difficulty (positive = harder than average,
      negative = easier). Computed from par SR, boundary rate, and dot %.
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

    return {
        "venue": _safe_str(_get_val(row, "venue")),
        "matches": _safe_int(_get_val(row, "venue_matches")),
        "avg_par_sr": _safe_float(_get_val(row, "venue_avg_par_sr")),
        "par_sr_std": _safe_float(_get_val(row, "venue_par_std")),
        "boundary_rate": _safe_float(_get_val(row, "venue_avg_boundary_rate")),
        "dot_pct": _safe_float(_get_val(row, "venue_avg_dot_pct")),
        "difficulty_raw": _safe_float(_get_val(row, "venue_difficulty_raw")),
        "difficulty_score": _safe_float(_get_val(row, "venue_difficulty")),
    }


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
        "runs",
        description=(
            "Column to sort by. For batting: runs, sr, balls_faced, innings. "
            "For bowling: wickets, economy, overs_bowled, spells."
        ),
    ),
    order: str = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
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
            store, venue_decoded, min_innings, sort, order, page, per_page
        )
    else:
        return _players_at_venue_batting(
            store, venue_decoded, min_innings, sort, order, page, per_page
        )


def _players_at_venue_batting(
    store: "DataStore",
    venue: str,
    min_innings: int,
    sort: str,
    order: str,
    page: int,
    per_page: int,
) -> dict:
    """Aggregate batting stats per player at a given venue."""
    import pandas as pd

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

    # Check if venue column exists in innings data
    # The venue info might be embedded in match_id or in a separate column
    # We try several possible column names
    venue_col = None
    for col_name in ["venue", "ground", "stadium"]:
        if col_name in store.bat_innings.columns:
            venue_col = col_name
            break

    if venue_col is None:
        # Venue data not available at innings level — return informational message
        return {
            "venue": venue,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "message": (
                "Venue column not found in innings detail data. "
                "Venue-level player splits require the pipeline to propagate "
                "venue information onto the innings DataFrame."
            ),
        }

    # Filter innings at this venue (case-insensitive partial match)
    venue_lower = venue.lower()
    mask = (
        store.bat_innings[venue_col]
        .astype(str)
        .str.lower()
        .str.contains(venue_lower, na=False)
    )
    venue_innings = store.bat_innings.loc[mask]

    if venue_innings.empty:
        return {
            "venue": venue,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Aggregate per batter
    agg = (
        venue_innings.groupby(["batter_id", "batter"])
        .agg(
            innings=("runs", "count"),
            runs=("runs", "sum"),
            balls_faced=("balls_faced", "sum"),
            fours=("fours", "sum"),
            sixes=("sixes", "sum"),
            dots=("dots", "sum"),
        )
        .reset_index()
    )

    # Compute derived stats
    agg["sr"] = agg.apply(
        lambda r: (
            round(r["runs"] / r["balls_faced"] * 100, 1)
            if r["balls_faced"] > 0
            else None
        ),
        axis=1,
    )
    agg["avg"] = agg.apply(
        lambda r: round(r["runs"] / max(r["innings"], 1), 1),
        axis=1,
    )

    # Apply min innings filter
    agg = agg.loc[agg["innings"] >= min_innings]

    total = len(agg)
    if total == 0:
        return {
            "venue": venue,
            "role": "bat",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Sort
    sort_col = sort.strip()
    if sort_col not in agg.columns:
        sort_col = "runs"

    ascending = order.lower() == "asc"
    agg = agg.sort_values(sort_col, ascending=ascending, na_position="last")

    # Paginate
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    end = start + per_page
    page_df = agg.iloc[start:end]

    players: list[dict] = []
    for _, row in page_df.iterrows():
        players.append(
            {
                "id": _safe_str(_get_val(row, "batter_id")),
                "name": _safe_str(_get_val(row, "batter")),
                "innings": _safe_int(_get_val(row, "innings")),
                "runs": _safe_int(_get_val(row, "runs")),
                "balls_faced": _safe_int(_get_val(row, "balls_faced")),
                "sr": _safe_float(_get_val(row, "sr")),
                "avg": _safe_float(_get_val(row, "avg")),
                "fours": _safe_int(_get_val(row, "fours")),
                "sixes": _safe_int(_get_val(row, "sixes")),
                "dots": _safe_int(_get_val(row, "dots")),
            }
        )

    return {
        "venue": venue,
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
) -> dict:
    """Aggregate bowling stats per player at a given venue."""
    import pandas as pd

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

    # Check for venue column
    venue_col = None
    for col_name in ["venue", "ground", "stadium"]:
        if col_name in store.bowl_spells.columns:
            venue_col = col_name
            break

    if venue_col is None:
        return {
            "venue": venue,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "message": (
                "Venue column not found in spells detail data. "
                "Venue-level player splits require the pipeline to propagate "
                "venue information onto the spells DataFrame."
            ),
        }

    venue_lower = venue.lower()
    mask = (
        store.bowl_spells[venue_col]
        .astype(str)
        .str.lower()
        .str.contains(venue_lower, na=False)
    )
    venue_spells = store.bowl_spells.loc[mask]

    if venue_spells.empty:
        return {
            "venue": venue,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Aggregate per bowler
    agg = (
        venue_spells.groupby(["bowler_id", "bowler"])
        .agg(
            spells=("wickets", "count"),
            wickets=("wickets", "sum"),
            runs_conceded=("runs_conceded", "sum"),
            legal_balls=("legal_balls", "sum"),
            fours_conceded=("fours_conceded", "sum"),
            sixes_conceded=("sixes_conceded", "sum"),
        )
        .reset_index()
    )

    # Compute derived stats
    agg["overs_bowled"] = agg["legal_balls"].apply(
        lambda b: round(float(b) / 6, 1) if b > 0 else 0.0
    )
    agg["economy"] = agg.apply(
        lambda r: (
            round(r["runs_conceded"] / (r["legal_balls"] / 6), 2)
            if r["legal_balls"] > 0
            else None
        ),
        axis=1,
    )
    agg["strike_rate"] = agg.apply(
        lambda r: (
            round(r["legal_balls"] / r["wickets"], 1) if r["wickets"] > 0 else None
        ),
        axis=1,
    )

    # Apply min spells filter
    agg = agg.loc[agg["spells"] >= min_innings]

    total = len(agg)
    if total == 0:
        return {
            "venue": venue,
            "role": "bowl",
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Sort
    sort_col = sort.strip()
    if sort_col not in agg.columns:
        sort_col = "wickets"

    ascending = order.lower() == "asc"
    agg = agg.sort_values(sort_col, ascending=ascending, na_position="last")

    # Paginate
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    end = start + per_page
    page_df = agg.iloc[start:end]

    players: list[dict] = []
    for _, row in page_df.iterrows():
        players.append(
            {
                "id": _safe_str(_get_val(row, "bowler_id")),
                "name": _safe_str(_get_val(row, "bowler")),
                "spells": _safe_int(_get_val(row, "spells")),
                "wickets": _safe_int(_get_val(row, "wickets")),
                "runs_conceded": _safe_int(_get_val(row, "runs_conceded")),
                "overs_bowled": _safe_float(_get_val(row, "overs_bowled")),
                "economy": _safe_float(_get_val(row, "economy")),
                "strike_rate": _safe_float(_get_val(row, "strike_rate")),
                "fours_conceded": _safe_int(_get_val(row, "fours_conceded")),
                "sixes_conceded": _safe_int(_get_val(row, "sixes_conceded")),
            }
        )

    return {
        "venue": venue,
        "role": "bowl",
        "players": players,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── Route: GET /api/venues/flat-track-index ───────────────────────


@router.get("/venues/flat-track-index")
async def flat_track_bully_leaderboard(
    role: str = Query(
        "bat",
        description="Role: 'bat' for batting FTB index, 'bowl' for bowling",
    ),
    min_innings: int = Query(
        20,
        ge=1,
        description="Minimum innings/spells at known venues",
    ),
    provisional: bool | None = Query(
        False,
        description="Include provisional players (default: exclude)",
    ),
    sort: str = Query(
        "flat_track_index",
        description="Column to sort by (default: flat_track_index)",
    ),
    order: str = Query(
        "asc",
        description=(
            "Sort order. Default asc — most negative FTB index first "
            "(biggest flat track bullies). Use desc for most consistent."
        ),
    ),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page"),
    store: "DataStore" = Depends(_get_store),
) -> dict:
    """Return a leaderboard of Flat Track Bully Index values.

    The **Flat Track Bully (FTB) Index** is the Pearson correlation
    between a player's SR-vs-par (or economy ratio) and the venue
    difficulty across their career innings/spells. A strongly negative
    value means the player performs disproportionately well at easy
    venues (a "flat track bully"). A value near zero means consistent
    performance regardless of conditions.

    **Interpretation**:
    - ``FTB ≈ 0``: ✅ Consistent everywhere
    - ``FTB < -0.15``: ⚠ Slight flat-track bias
    - ``FTB < -0.30``: 🚩 Flat track bully

    **Examples**:
    - ``/api/venues/flat-track-index?role=bat&min_innings=30``
    - ``/api/venues/flat-track-index?role=bowl&order=desc`` — most consistent bowlers
    """
    import pandas as pd

    if role == "bowl":
        df = (
            store.bowl_careers.copy()
            if not store.bowl_careers.empty
            else pd.DataFrame()
        )
        ftb_col = "flat_track_index_bowl"
        prov_col = "is_provisional_bowl"
        innings_col = "ft_spells_at_known_venues"
        id_col = "bowler_id"
        name_col = "bowler"
        score_cols = ["score_accuracy", "score_control", "score_threat"]
    else:
        df = store.bat_careers.copy() if not store.bat_careers.empty else pd.DataFrame()
        ftb_col = "flat_track_index"
        prov_col = "is_provisional_bat"
        innings_col = "ft_innings_at_known_venues"
        id_col = "batter_id"
        name_col = "batter"
        score_cols = ["score_acceleration", "score_power", "score_control"]

    if df.empty or ftb_col not in df.columns:
        return {
            "role": role,
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Filter out NaN FTB values
    df = df.dropna(subset=[ftb_col])

    # Apply minimum innings at known venues filter
    if innings_col in df.columns:
        df = df.loc[df[innings_col] >= min_innings]

    # Provisional filter
    if provisional is not None and prov_col in df.columns:
        if not provisional:
            df = df.loc[df[prov_col] != True]  # noqa: E712
        elif provisional:
            df = df.loc[df[prov_col] == True]  # noqa: E712

    total = len(df)
    if total == 0:
        return {
            "role": role,
            "players": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
        }

    # Sort
    sort_col = sort.strip()
    if sort_col not in df.columns:
        sort_col = ftb_col

    ascending = order.lower() == "asc"
    df = df.sort_values(sort_col, ascending=ascending, na_position="last")

    # Paginate
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    end = start + per_page
    page_df = df.iloc[start:end]

    players: list[dict] = []
    for _, row in page_df.iterrows():
        entry: dict[str, Any] = {
            "id": _safe_str(_get_val(row, id_col)),
            "name": _safe_str(_get_val(row, name_col)),
            "country": _safe_str(_get_val(row, "country")),
            "flat_track_index": _safe_float(_get_val(row, ftb_col)),
            "innings_at_known_venues": _safe_int(_get_val(row, innings_col)),
            "avg_venue_difficulty_faced": _safe_float(
                _get_val(row, "avg_venue_difficulty_faced")
            ),
            "overall_grade": _safe_str(_get_val(row, "overall_grade"), "D"),
            "archetype": _safe_str(_get_val(row, "archetype")),
        }

        # Add the 3 metric scores
        for sc in score_cols:
            if sc in row.index if hasattr(row, "index") else False:
                entry[sc] = _safe_float(_get_val(row, sc))
            else:
                entry[sc] = None

        # Interpretation label
        ftb_val = _safe_float(_get_val(row, ftb_col))
        if ftb_val is not None:
            if ftb_val < -0.30:
                entry["interpretation"] = "Flat track bully"
                entry["icon"] = "🚩"
            elif ftb_val < -0.15:
                entry["interpretation"] = "Slight flat-track bias"
                entry["icon"] = "⚠️"
            else:
                entry["interpretation"] = "Consistent everywhere"
                entry["icon"] = "✅"
        else:
            entry["interpretation"] = "Insufficient data"
            entry["icon"] = "—"

        players.append(entry)

    return {
        "role": role,
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

    df = store.venue.copy()

    total_venues = len(df)

    # Hardest venue (highest difficulty score)
    hardest_row = None
    if "venue_difficulty" in df.columns:
        hardest_idx = df["venue_difficulty"].idxmax()
        if hardest_idx is not None:
            hardest_row = df.loc[hardest_idx]

    # Easiest venue (lowest difficulty score)
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

    # Average difficulty
    avg_difficulty = None
    if "venue_difficulty" in df.columns:
        avg_difficulty = _safe_float(df["venue_difficulty"].mean())

    # Difficulty distribution (for histogram)
    distribution: list[dict] = []
    if "venue_difficulty" in df.columns:
        difficulty_vals = df["venue_difficulty"].dropna()
        if not difficulty_vals.empty:
            # Create 5 equal-width bins
            import numpy as np

            bins = np.linspace(difficulty_vals.min(), difficulty_vals.max(), num=6)
            for i in range(len(bins) - 1):
                low = float(bins[i])
                high = float(bins[i + 1])
                count = int(
                    ((difficulty_vals >= low) & (difficulty_vals <= high)).sum()
                )
                distribution.append(
                    {
                        "bin_low": round(low, 2),
                        "bin_high": round(high, 2),
                        "count": count,
                    }
                )

    return {
        "total_venues": total_venues,
        "hardest_venue": (
            {
                "venue": _safe_str(_get_val(hardest_row, "venue")),
                "difficulty": _safe_float(_get_val(hardest_row, "venue_difficulty")),
                "matches": _safe_int(_get_val(hardest_row, "venue_matches")),
            }
            if hardest_row is not None
            else None
        ),
        "easiest_venue": (
            {
                "venue": _safe_str(_get_val(easiest_row, "venue")),
                "difficulty": _safe_float(_get_val(easiest_row, "venue_difficulty")),
                "matches": _safe_int(_get_val(easiest_row, "venue_matches")),
            }
            if easiest_row is not None
            else None
        ),
        "most_used_venue": (
            {
                "venue": _safe_str(_get_val(most_used_row, "venue")),
                "matches": _safe_int(_get_val(most_used_row, "venue_matches")),
                "difficulty": _safe_float(_get_val(most_used_row, "venue_difficulty")),
            }
            if most_used_row is not None
            else None
        ),
        "avg_difficulty": avg_difficulty,
        "difficulty_distribution": distribution,
    }
