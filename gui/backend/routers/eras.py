"""
Eras router — /api/eras endpoint.

Provides:
- GET /api/eras  → Era baselines (par SR, boundary rate, dot%, multiplier) by year

The era data is derived from the batting innings detail DataFrame by
aggregating per-year baselines. If the pipeline has pre-computed era
columns in the careers data, those are used; otherwise we compute
them on the fly from the innings data.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from schemas import EraBaseline, EraResponse

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["eras"])


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


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _compute_era_baselines(store: Any) -> list[dict]:
    """Compute era baselines from batting innings detail data.

    Groups innings by year and computes:
    - par_sr: median strike rate for the year
    - boundary_rate: (fours + sixes) / balls_faced
    - dot_pct: dots / balls_faced
    - multiplier: ratio of latest year's par_sr to this year's par_sr

    Falls back to venue baselines or careers data if innings data is
    not available with the required columns.
    """
    import pandas as pd

    df = store.bat_innings

    if df.empty:
        return []

    # Ensure we have a date column to extract year
    if "date" not in df.columns:
        return []

    working = df.copy()

    # Extract year from date
    if not pd.api.types.is_datetime64_any_dtype(working["date"]):
        working["date"] = pd.to_datetime(working["date"], errors="coerce")

    working = working.dropna(subset=["date"])
    working["year"] = working["date"].dt.year

    # Filter to reasonable T20I era (2005 onwards)
    working = working[working["year"] >= 2005]

    if working.empty:
        return []

    # Determine which columns are available
    has_balls = "balls_faced" in working.columns
    has_runs = "runs" in working.columns
    has_sr = "sr" in working.columns
    has_fours = "fours" in working.columns
    has_sixes = "sixes" in working.columns
    has_dots = "dots" in working.columns

    results = []

    for year, group in working.groupby("year"):
        if len(group) < 10:
            continue

        entry: dict[str, Any] = {"year": int(year)}

        # Par SR
        if has_sr:
            sr_values = group["sr"].dropna()
            if len(sr_values) > 0:
                entry["par_sr"] = round(float(sr_values.median()), 2)
            else:
                entry["par_sr"] = None
        elif has_runs and has_balls:
            total_runs = group["runs"].sum()
            total_balls = group["balls_faced"].sum()
            if total_balls > 0:
                entry["par_sr"] = round(float(total_runs / total_balls * 100), 2)
            else:
                entry["par_sr"] = None
        else:
            entry["par_sr"] = None

        # Boundary rate
        if has_fours and has_sixes and has_balls:
            total_fours = group["fours"].fillna(0).sum()
            total_sixes = group["sixes"].fillna(0).sum()
            total_balls = group["balls_faced"].fillna(0).sum()
            if total_balls > 0:
                entry["boundary_rate"] = round(
                    float((total_fours + total_sixes) / total_balls * 100), 2
                )
            else:
                entry["boundary_rate"] = None
        else:
            entry["boundary_rate"] = None

        # Dot percentage
        if has_dots and has_balls:
            total_dots = group["dots"].fillna(0).sum()
            total_balls = group["balls_faced"].fillna(0).sum()
            if total_balls > 0:
                entry["dot_pct"] = round(float(total_dots / total_balls * 100), 2)
            else:
                entry["dot_pct"] = None
        else:
            entry["dot_pct"] = None

        # Matches count (for reference)
        if "match_id" in group.columns:
            entry["matches"] = int(group["match_id"].nunique())
        else:
            entry["matches"] = len(group)

        # Innings count
        entry["innings"] = len(group)

        results.append(entry)

    if not results:
        return []

    # Sort by year
    results.sort(key=lambda x: x["year"])

    # Compute era multiplier relative to the latest year
    latest_par_sr = None
    for entry in reversed(results):
        if entry.get("par_sr") is not None:
            latest_par_sr = entry["par_sr"]
            break

    if latest_par_sr and latest_par_sr > 0:
        for entry in results:
            if entry.get("par_sr") is not None and entry["par_sr"] > 0:
                entry["multiplier"] = round(latest_par_sr / entry["par_sr"], 3)
            else:
                entry["multiplier"] = None
    else:
        for entry in results:
            entry["multiplier"] = None

    return results


# ── Endpoints ─────────────────────────────────────────────────────


@router.get("/eras", response_model=EraResponse, summary="Era baselines by year")
async def get_eras(store=Depends(_get_store)):
    """Return era baselines showing how T20I cricket has evolved over time.

    Each entry contains:
    - **year**: The calendar year
    - **par_sr**: Median strike rate for that year (the "par" scoring rate)
    - **boundary_rate**: Percentage of balls that were boundaries
    - **dot_pct**: Percentage of balls that were dot balls
    - **multiplier**: Era adjustment factor (latest year = 1.00; earlier years > 1.00)

    A multiplier of 1.28 means a performance from that year is worth 28%
    more than the same raw numbers in the most recent year, because the
    overall scoring environment was harder.
    """
    baselines_raw = _compute_era_baselines(store)

    baselines = []
    for entry in baselines_raw:
        baselines.append(
            EraBaseline(
                year=entry.get("year", 0),
                par_sr=_safe_float(entry.get("par_sr")),
                boundary_rate=_safe_float(entry.get("boundary_rate")),
                dot_pct=_safe_float(entry.get("dot_pct")),
                multiplier=_safe_float(entry.get("multiplier")),
            )
        )

    return EraResponse(baselines=baselines)
