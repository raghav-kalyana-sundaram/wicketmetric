"""
Display ratings — dual headline scores (current vs overall) per product spec.

- ``rating_overall``: career-style overall_score capped by the player's historical
  ceiling from the form tracker (max ``window_composite`` ever observed), falling
  back to ``peak_window_composite`` when form series is missing.
- ``rating_current``: latest rolling-window composite from the form series,
  capped by the same ceiling, when sample size is enough (≥10 innings/spells);
  otherwise falls back to ``rating_overall``.

See ``docs/product-spec-team-ratings.md``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _get(row: Mapping[str, Any] | Any, key: str) -> Any:
    if hasattr(row, "get"):
        return row.get(key)
    return getattr(row, key, None)


def batting_display_ratings(row: Mapping[str, Any] | Any) -> tuple[float | None, float | None]:
    """Return (rating_overall, rating_current) for a batting career row."""
    overall_raw = _to_float(_get(row, "overall_score"))
    peak = _to_float(_get(row, "peak_window_composite"))
    fmax = _to_float(_get(row, "form_composite_max"))
    flatest = _to_float(_get(row, "form_composite_latest"))
    try:
        innings = int(_get(row, "innings_count") or 0)
    except (TypeError, ValueError):
        innings = 0

    ceiling = fmax if fmax is not None else peak

    rating_overall = overall_raw
    if overall_raw is not None and ceiling is not None:
        rating_overall = min(overall_raw, ceiling)

    rating_current = rating_overall
    if innings >= 10 and flatest is not None:
        if ceiling is not None:
            rating_current = min(flatest, ceiling)
        else:
            rating_current = flatest

    return rating_overall, rating_current


def bowling_display_ratings(row: Mapping[str, Any] | Any) -> tuple[float | None, float | None]:
    """Return (rating_overall, rating_current) for a bowling career row."""
    overall_raw = _to_float(_get(row, "overall_score"))
    peak = _to_float(_get(row, "peak_window_composite"))
    fmax = _to_float(_get(row, "form_composite_max"))
    flatest = _to_float(_get(row, "form_composite_latest"))
    try:
        matches = int(_get(row, "matches") or 0)
    except (TypeError, ValueError):
        matches = 0

    ceiling = fmax if fmax is not None else peak

    rating_overall = overall_raw
    if overall_raw is not None and ceiling is not None:
        rating_overall = min(overall_raw, ceiling)

    rating_current = rating_overall
    if matches >= 10 and flatest is not None:
        if ceiling is not None:
            rating_current = min(flatest, ceiling)
        else:
            rating_current = flatest

    return rating_overall, rating_current


# ── Leaderboard sort (computed columns; shared by API + static export) ─

LEADERBOARD_SORT_TEMP_COL = "__cm_leaderboard_sort__"


def apply_display_rating_sort_column(df: Any, sort_col: str, role: str) -> tuple[Any, str]:
    """If ``sort_col`` is a display rating, append a numeric temp column and return its name."""
    if sort_col not in ("rating_current", "rating_overall"):
        return df, sort_col
    if df is None or getattr(df, "empty", True):
        return df, sort_col

    fn = batting_display_ratings if role == "bat" else bowling_display_ratings
    pos = 1 if sort_col == "rating_current" else 0
    values: list[float] = []
    for _, row in df.iterrows():
        pair = fn(row)
        v = pair[pos]
        values.append(float(v) if v is not None else float("nan"))

    out = df.copy()
    out[LEADERBOARD_SORT_TEMP_COL] = values
    return out, LEADERBOARD_SORT_TEMP_COL


def drop_display_rating_sort_column(df: Any) -> Any:
    if df is None or not hasattr(df, "columns"):
        return df
    if LEADERBOARD_SORT_TEMP_COL in df.columns:
        return df.drop(columns=[LEADERBOARD_SORT_TEMP_COL])
    return df
