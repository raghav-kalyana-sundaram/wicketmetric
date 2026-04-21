"""
Era-Adjusted Ratings (Cross-Generational Harmonization) — Feature 15 from
Version 0.2 roadmap.

As T20 cricket evolves, average scores keep rising.  A strike rate of 140 in
2012 was elite; in 2024, it is average.  Era-adjusted ratings ensure that
historical performances are mathematically adjusted to modern terms, enabling
fair cross-generational comparisons.

Key outputs
-----------
- **Era baselines**: Per-year statistics (smoothed par SR, boundary rate,
  dot percentage) derived from match context data.
- **Era multipliers**: Adjustment factors that convert historical performances
  to "modern equivalent" terms.  A multiplier > 1.0 means the era was harder
  (lower scoring) and performances should be boosted.
- **Era-adjusted components**: Per-innings component values multiplied by the
  era multiplier for their match year, ready for downstream z-scoring.

Design
------
- ``compute_era_baselines()`` aggregates match context by year, computes
  rolling-window smoothed averages (default: 3-year centered window), and
  derives era multipliers relative to the most recent year.
- ``apply_era_adjustment_to_innings()`` merges the year-level multiplier onto
  per-innings data and adjusts specified component columns.
- ``compute_era_summary()`` produces a human-readable summary table showing
  how each year maps to a modern-equivalent multiplier.

All functions are pure — they take DataFrames in and return DataFrames out,
with no side effects or config reads (config is resolved by the caller in
``main.py``).

Integration
-----------
Called from ``main.py`` **before** career aggregation and z-scoring.  The
era multiplier is applied to per-innings component values so that when
career means are computed and z-scored, historical performances are already
on a level playing field with modern ones.

The existing ``match_par_sr``-based normalisation handles pitch-level
differences within a single match.  Era adjustment handles the *global*
shift in how extreme those normalised ratios can get across decades.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# 1. Era Baselines
# ──────────────────────────────────────────────────────────────────────────


def compute_era_baselines(
    match_ctx: pd.DataFrame,
    rolling_years: int = 3,
    min_matches_per_year: int = 10,
) -> pd.DataFrame:
    """
    Compute yearly era baselines for cross-generational normalization.

    Returns a DataFrame with one row per year containing era statistics
    and multipliers to adjust historical performances to "modern terms."

    Parameters
    ----------
    match_ctx : pd.DataFrame
        One row per match from the context module.  Must contain at least:
        ``match_id``, ``match_par_sr``, ``match_boundary_rate``,
        ``match_dot_pct``, ``match_date``.
    rolling_years : int
        Width of the centered rolling window for smoothing yearly averages.
        Default 3 means each year's baseline is the average of that year
        plus one year on either side.  This prevents single-year spikes
        (e.g. a World Cup year with only high-quality pitches) from
        distorting the era multiplier.
    min_matches_per_year : int
        Years with fewer matches than this are still included (they benefit
        from rolling smoothing) but are flagged.

    Returns
    -------
    pd.DataFrame with columns:
        year, year_matches, year_avg_par_sr, year_std_par_sr,
        year_avg_boundary_rate, year_avg_dot_pct,
        era_par_sr, era_boundary_rate, era_dot_pct,
        era_sr_multiplier, era_boundary_multiplier,
        is_thin_year (True if year_matches < min_matches_per_year)

    Notes
    -----
    The **most recent year** in the data is used as the reference point.
    All multipliers are relative to it:
    - ``era_sr_multiplier = modern_par / historical_par``
    - A multiplier of 1.25 means the historical era had 20% lower par SR,
      so performances from that era should be boosted by 25%.
    """
    empty_cols = [
        "year",
        "year_matches",
        "year_avg_par_sr",
        "year_std_par_sr",
        "year_avg_boundary_rate",
        "year_avg_dot_pct",
        "era_par_sr",
        "era_boundary_rate",
        "era_dot_pct",
        "era_sr_multiplier",
        "era_boundary_multiplier",
        "is_thin_year",
    ]

    if match_ctx.empty or "match_par_sr" not in match_ctx.columns:
        return pd.DataFrame(columns=empty_cols)

    df = match_ctx.copy()

    # ── Extract year from match_date ──
    if "match_date" in df.columns:
        df["year"] = pd.to_datetime(df["match_date"], errors="coerce").dt.year
    elif "date" in df.columns:
        df["year"] = pd.to_datetime(df["date"], errors="coerce").dt.year
    else:
        return pd.DataFrame(columns=empty_cols)

    # Drop rows where year extraction failed
    df = df.dropna(subset=["year"])
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    df["year"] = df["year"].astype(int)

    # ── Per-year aggregates ──
    agg_dict = {
        "year_matches": ("match_id", "nunique"),
        "year_avg_par_sr": ("match_par_sr", "mean"),
        "year_std_par_sr": ("match_par_sr", "std"),
    }

    if "match_boundary_rate" in df.columns:
        agg_dict["year_avg_boundary_rate"] = ("match_boundary_rate", "mean")
    if "match_dot_pct" in df.columns:
        agg_dict["year_avg_dot_pct"] = ("match_dot_pct", "mean")

    era_stats = df.groupby("year").agg(**agg_dict).reset_index()

    # Fill NaN std (single-match years) and missing optional columns
    era_stats["year_std_par_sr"] = era_stats["year_std_par_sr"].fillna(0.0)
    if "year_avg_boundary_rate" not in era_stats.columns:
        era_stats["year_avg_boundary_rate"] = np.nan
    if "year_avg_dot_pct" not in era_stats.columns:
        era_stats["year_avg_dot_pct"] = np.nan

    # Sort by year for rolling window
    era_stats = era_stats.sort_values("year").reset_index(drop=True)

    # ── Flag thin years ──
    era_stats["is_thin_year"] = era_stats["year_matches"] < min_matches_per_year

    # ── Rolling-window smoothed averages ──
    # Use centered window so each year absorbs context from neighbours.
    # min_periods=1 ensures the first/last years still get a value.
    window = max(rolling_years, 1)

    era_stats["era_par_sr"] = (
        era_stats["year_avg_par_sr"].rolling(window, min_periods=1, center=True).mean()
    )

    era_stats["era_boundary_rate"] = (
        era_stats["year_avg_boundary_rate"]
        .rolling(window, min_periods=1, center=True)
        .mean()
    )

    era_stats["era_dot_pct"] = (
        era_stats["year_avg_dot_pct"].rolling(window, min_periods=1, center=True).mean()
    )

    # ── Reference point: most recent year ──
    # This is the "modern standard" — all multipliers are relative to it.
    global_ref_sr = era_stats["era_par_sr"].iloc[-1]
    global_ref_br = era_stats["era_boundary_rate"].iloc[-1]

    # ── Era multipliers ──
    # Multiplier > 1.0 → era was harder → boost historical performances.
    # Multiplier < 1.0 → era was easier → discount (rare in T20 history).
    # Clip par SR denominator to avoid division by zero or extreme values.
    era_stats["era_sr_multiplier"] = _safe_divide(
        global_ref_sr, era_stats["era_par_sr"], floor=50.0
    )

    era_stats["era_boundary_multiplier"] = _safe_divide(
        global_ref_br, era_stats["era_boundary_rate"], floor=0.01
    )

    # Clamp multipliers to a reasonable range [0.70, 1.60]
    # This prevents extreme distortions from very early years with few matches.
    era_stats["era_sr_multiplier"] = era_stats["era_sr_multiplier"].clip(
        lower=0.70, upper=1.60
    )
    era_stats["era_boundary_multiplier"] = era_stats["era_boundary_multiplier"].clip(
        lower=0.70, upper=1.60
    )

    return era_stats[
        [
            "year",
            "year_matches",
            "year_avg_par_sr",
            "year_std_par_sr",
            "year_avg_boundary_rate",
            "year_avg_dot_pct",
            "era_par_sr",
            "era_boundary_rate",
            "era_dot_pct",
            "era_sr_multiplier",
            "era_boundary_multiplier",
            "is_thin_year",
        ]
    ]


# ──────────────────────────────────────────────────────────────────────────
# 2. Apply Era Adjustment to Per-Innings Data
# ──────────────────────────────────────────────────────────────────────────


def apply_era_adjustment_to_innings(
    innings_df: pd.DataFrame,
    era_baselines: pd.DataFrame,
    adjust_cols: list[str] | None = None,
    multiplier_col: str = "era_sr_multiplier",
    date_col: str = "date",
) -> pd.DataFrame:
    """
    Apply era multipliers to per-innings component columns.

    Merges the era multiplier (from era baselines) onto each innings row
    via the match year, then multiplies specified component columns by it.

    Parameters
    ----------
    innings_df : pd.DataFrame
        Per-innings data (batting or bowling).  Must contain a date column
        from which the year can be derived.
    era_baselines : pd.DataFrame
        Output of ``compute_era_baselines()``.  Must contain ``year`` and
        the column named by ``multiplier_col``.
    adjust_cols : list[str], optional
        Which columns to multiply by the era multiplier.  For batting, the
        roadmap suggests ``["acc_overall_sr"]``.  If None, defaults to
        ``["acc_overall_sr"]``.
    multiplier_col : str
        Name of the multiplier column from era_baselines to use.
    date_col : str
        Name of the date column on innings_df.

    Returns
    -------
    pd.DataFrame
        Copy of innings_df with:
        - ``era_year`` column added (the match year)
        - ``era_multiplier`` column added (the multiplier applied)
        - Specified columns adjusted (multiplied by era_multiplier)
        - Original un-adjusted values preserved as ``{col}_pre_era``
    """
    if adjust_cols is None:
        adjust_cols = ["acc_overall_sr"]

    df = innings_df.copy()

    if era_baselines.empty or multiplier_col not in era_baselines.columns:
        # No adjustment — add neutral columns and return
        df["era_year"] = np.nan
        df["era_multiplier"] = 1.0
        return df

    # ── Extract year from the innings date ──
    if date_col in df.columns:
        df["era_year"] = pd.to_datetime(df[date_col], errors="coerce").dt.year
    elif "match_date" in df.columns:
        df["era_year"] = pd.to_datetime(df["match_date"], errors="coerce").dt.year
    else:
        df["era_year"] = np.nan
        df["era_multiplier"] = 1.0
        return df

    # ── Merge era multiplier ──
    era_map = era_baselines[["year", multiplier_col]].copy()
    era_map = era_map.rename(columns={multiplier_col: "era_multiplier"})
    era_map["year"] = era_map["year"].astype(float)  # for safe merge
    df["era_year"] = df["era_year"].astype(float)

    df = df.merge(
        era_map,
        left_on="era_year",
        right_on="year",
        how="left",
        suffixes=("", "_era_dup"),
    )

    # Drop duplicate year column if created
    if "year_era_dup" in df.columns:
        df.drop(columns=["year_era_dup"], inplace=True)
    if "year" in df.columns and "year" not in innings_df.columns:
        df.drop(columns=["year"], inplace=True)

    # Fill NaN multipliers (years not in baselines) with 1.0 (neutral)
    df["era_multiplier"] = df["era_multiplier"].fillna(1.0)

    # ── Apply the multiplier to specified columns ──
    for col in adjust_cols:
        if col in df.columns:
            # Preserve the original
            df[f"{col}_pre_era"] = df[col].copy()
            # Apply era adjustment
            df[col] = df[col] * df["era_multiplier"]

    return df


# ──────────────────────────────────────────────────────────────────────────
# 3. Bowling Era Adjustment
# ──────────────────────────────────────────────────────────────────────────


def apply_era_adjustment_to_bowling(
    bowl_spells: pd.DataFrame,
    era_baselines: pd.DataFrame,
    adjust_cols: list[str] | None = None,
    multiplier_col: str = "era_sr_multiplier",
    date_col: str = "date",
) -> pd.DataFrame:
    """
    Apply era adjustment to bowling spell data.

    For bowling, the era adjustment works differently: in a higher-scoring
    era, conceding runs is more "normal," so economy-based metrics should
    be *discounted* (divided by the multiplier rather than multiplied).

    For threat/wicket-based metrics, a multiplier > 1 means batting was
    harder historically, so taking wickets was relatively easier — those
    should be divided too.

    However, the simplest and most defensible approach (matching the roadmap)
    is to use the **inverse** of the SR multiplier for bowling: if the
    batting multiplier is 1.25 (boost old batting), the bowling multiplier
    is 1/1.25 = 0.80 (discount old bowling economy, since lower economy
    was easier to achieve in a low-scoring era).

    Parameters
    ----------
    bowl_spells : pd.DataFrame
        Per-spell bowling data.
    era_baselines : pd.DataFrame
        Output of ``compute_era_baselines()``.
    adjust_cols : list[str], optional
        Bowling columns to adjust.  Default: ``["acc_economy_vs_par"]``.
    multiplier_col : str
        The batting-era multiplier column.  The inverse is applied.
    date_col : str
        Date column on bowl_spells.

    Returns
    -------
    pd.DataFrame
        Copy of bowl_spells with era-adjusted columns and metadata.
    """
    if adjust_cols is None:
        adjust_cols = ["acc_economy_vs_par"]

    df = bowl_spells.copy()

    if era_baselines.empty or multiplier_col not in era_baselines.columns:
        df["era_year"] = np.nan
        df["era_multiplier_bowl"] = 1.0
        return df

    # ── Extract year ──
    if date_col in df.columns:
        df["era_year"] = pd.to_datetime(df[date_col], errors="coerce").dt.year
    elif "match_date" in df.columns:
        df["era_year"] = pd.to_datetime(df["match_date"], errors="coerce").dt.year
    else:
        df["era_year"] = np.nan
        df["era_multiplier_bowl"] = 1.0
        return df

    # ── Merge and invert multiplier ──
    era_map = era_baselines[["year", multiplier_col]].copy()
    era_map["era_multiplier_bowl"] = _safe_divide(
        1.0, era_map[multiplier_col], floor=0.5
    )
    era_map["year"] = era_map["year"].astype(float)
    df["era_year"] = df["era_year"].astype(float)

    df = df.merge(
        era_map[["year", "era_multiplier_bowl"]],
        left_on="era_year",
        right_on="year",
        how="left",
        suffixes=("", "_era_dup"),
    )

    if "year_era_dup" in df.columns:
        df.drop(columns=["year_era_dup"], inplace=True)
    if "year" in df.columns and "year" not in bowl_spells.columns:
        df.drop(columns=["year"], inplace=True)

    df["era_multiplier_bowl"] = df["era_multiplier_bowl"].fillna(1.0)

    # ── Apply adjustment ──
    for col in adjust_cols:
        if col in df.columns:
            df[f"{col}_pre_era"] = df[col].copy()
            df[col] = df[col] * df["era_multiplier_bowl"]

    return df


# ──────────────────────────────────────────────────────────────────────────
# 4. Era Summary Table (for documentation / debugging)
# ──────────────────────────────────────────────────────────────────────────


def compute_era_summary(
    era_baselines: pd.DataFrame,
) -> pd.DataFrame:
    """
    Produce a human-readable summary of era multipliers.

    This is primarily for documentation, spot-checking, and frontend
    display — showing fans how different eras compare.

    Parameters
    ----------
    era_baselines : pd.DataFrame
        Output of ``compute_era_baselines()``.

    Returns
    -------
    pd.DataFrame with columns:
        year, era_par_sr, era_sr_multiplier, effect_pct,
        era_boundary_rate, era_boundary_multiplier, year_matches
    """
    if era_baselines.empty:
        return pd.DataFrame(
            columns=[
                "year",
                "era_par_sr",
                "era_sr_multiplier",
                "effect_pct",
                "era_boundary_rate",
                "era_boundary_multiplier",
                "year_matches",
            ]
        )

    df = era_baselines.copy()

    # Effect percentage: how much boost/discount this era gets
    df["effect_pct"] = ((df["era_sr_multiplier"] - 1.0) * 100.0).round(1)

    cols = [
        "year",
        "era_par_sr",
        "era_sr_multiplier",
        "effect_pct",
    ]
    if "era_boundary_rate" in df.columns:
        cols.append("era_boundary_rate")
    if "era_boundary_multiplier" in df.columns:
        cols.append("era_boundary_multiplier")
    cols.append("year_matches")

    available = [c for c in cols if c in df.columns]
    result = df[available].copy()

    # Round for readability
    for c in [
        "era_par_sr",
        "era_sr_multiplier",
        "era_boundary_rate",
        "era_boundary_multiplier",
    ]:
        if c in result.columns:
            result[c] = result[c].round(3)

    return result


# ──────────────────────────────────────────────────────────────────────────
# 5. Era Multiplier Lookup (for ad-hoc use)
# ──────────────────────────────────────────────────────────────────────────


def get_era_multiplier(
    era_baselines: pd.DataFrame,
    year: int,
    multiplier_col: str = "era_sr_multiplier",
) -> float:
    """
    Look up the era multiplier for a specific year.

    Parameters
    ----------
    era_baselines : pd.DataFrame
        Output of ``compute_era_baselines()``.
    year : int
        The year to look up.
    multiplier_col : str
        Which multiplier column to return.

    Returns
    -------
    float
        The era multiplier for the given year, or 1.0 if not found.
    """
    if era_baselines.empty or "year" not in era_baselines.columns:
        return 1.0

    match = era_baselines[era_baselines["year"] == year]
    if match.empty:
        return 1.0

    val = match[multiplier_col].iloc[0]
    if pd.isna(val):
        return 1.0

    return float(val)


# ──────────────────────────────────────────────────────────────────────────
# 6. Batch era adjustment for career DataFrames (post-hoc)
# ──────────────────────────────────────────────────────────────────────────


def compute_era_adjusted_career_composite(
    bat_careers: pd.DataFrame,
    bat_innings: pd.DataFrame,
    era_baselines: pd.DataFrame,
    composite_cols: list[str] | None = None,
    date_col: str = "date",
) -> pd.DataFrame:
    """
    Compute an era-adjusted career composite by re-aggregating per-innings
    data with era multipliers applied.

    This is an alternative to applying era adjustment before z-scoring.
    Instead, it produces a standalone "era-adjusted composite" column that
    can sit alongside the standard (non-era-adjusted) ratings.

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Career-level batting data (for joining results back).
    bat_innings : pd.DataFrame
        Per-innings batting data with component columns.
    era_baselines : pd.DataFrame
        Output of ``compute_era_baselines()``.
    composite_cols : list[str], optional
        Component columns to include in the era-adjusted composite.
        Default: ``["acc_overall_sr", "pow_boundary_pct",
        "ctrl_contribution"]``.
    date_col : str
        Date column on bat_innings.

    Returns
    -------
    pd.DataFrame
        Career-level DataFrame with ``batter_id``, ``batter``, and
        ``era_adjusted_composite`` columns.
    """
    if composite_cols is None:
        composite_cols = [
            "acc_overall_sr",
            "pow_boundary_pct",
            "ctrl_contribution",
        ]

    empty = pd.DataFrame(columns=["batter_id", "batter", "era_adjusted_composite"])

    if bat_innings.empty or era_baselines.empty:
        return empty

    # Apply era multiplier to innings
    adjusted = apply_era_adjustment_to_innings(
        bat_innings,
        era_baselines,
        adjust_cols=composite_cols,
        date_col=date_col,
    )

    if adjusted.empty:
        return empty

    # ── Career-level weighted mean of adjusted components ──
    has_weight = "opp_quality_weight" in adjusted.columns

    def _career_composite(g: pd.DataFrame) -> float:
        vals = []
        for col in composite_cols:
            if col in g.columns:
                v = g[col].fillna(0.0).values
            else:
                v = np.zeros(len(g))
            vals.append(v)

        if not vals:
            return np.nan

        # Simple mean across components, then weighted mean across innings
        component_avg = np.mean(vals, axis=0)

        if has_weight:
            w = g["opp_quality_weight"].fillna(1.0).values
        else:
            w = np.ones(len(g))

        w_sum = w.sum()
        if w_sum < 1e-12:
            return np.nan

        return float(np.average(component_avg, weights=w))

    result = (
        adjusted.groupby(["batter_id", "batter"], observed=True)
        .apply(_career_composite, include_groups=False)
        .reset_index(name="era_adjusted_composite")
    )

    return result


# ──────────────────────────────────────────────────────────────────────────
# 7. Convenience: run all era computations
# ──────────────────────────────────────────────────────────────────────────


def compute_all_era_metrics(
    match_ctx: pd.DataFrame,
    bat_innings: pd.DataFrame | None = None,
    bowl_spells: pd.DataFrame | None = None,
    rolling_years: int = 3,
    min_matches_per_year: int = 10,
    batting_adjust_cols: list[str] | None = None,
    bowling_adjust_cols: list[str] | None = None,
    date_col: str = "date",
) -> dict[str, pd.DataFrame]:
    """
    Run the full era-adjustment pipeline and return all outputs.

    Parameters
    ----------
    match_ctx : pd.DataFrame
        Match context data.
    bat_innings : pd.DataFrame, optional
        Per-innings batting data to adjust.
    bowl_spells : pd.DataFrame, optional
        Per-spell bowling data to adjust.
    rolling_years : int
        Rolling window for era smoothing.
    min_matches_per_year : int
        Minimum matches per year for thin-year flagging.
    batting_adjust_cols : list[str], optional
        Batting columns to era-adjust.
    bowling_adjust_cols : list[str], optional
        Bowling columns to era-adjust.
    date_col : str
        Date column name.

    Returns
    -------
    dict with keys:
        ``era_baselines`` — yearly baselines and multipliers
        ``era_summary`` — human-readable summary table
        ``bat_innings_adjusted`` — era-adjusted batting innings (if provided)
        ``bowl_spells_adjusted`` — era-adjusted bowling spells (if provided)
    """
    # 1. Compute baselines
    baselines = compute_era_baselines(
        match_ctx,
        rolling_years=rolling_years,
        min_matches_per_year=min_matches_per_year,
    )

    # 2. Summary table
    summary = compute_era_summary(baselines)

    result: dict[str, pd.DataFrame] = {
        "era_baselines": baselines,
        "era_summary": summary,
    }

    # 3. Adjust batting innings (if provided)
    if bat_innings is not None and not bat_innings.empty and not baselines.empty:
        result["bat_innings_adjusted"] = apply_era_adjustment_to_innings(
            bat_innings,
            baselines,
            adjust_cols=batting_adjust_cols,
            date_col=date_col,
        )
    else:
        result["bat_innings_adjusted"] = (
            bat_innings if bat_innings is not None else pd.DataFrame()
        )

    # 4. Adjust bowling spells (if provided)
    if bowl_spells is not None and not bowl_spells.empty and not baselines.empty:
        result["bowl_spells_adjusted"] = apply_era_adjustment_to_bowling(
            bowl_spells,
            baselines,
            adjust_cols=bowling_adjust_cols,
            date_col=date_col,
        )
    else:
        result["bowl_spells_adjusted"] = (
            bowl_spells if bowl_spells is not None else pd.DataFrame()
        )

    return result


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────


def _safe_divide(
    numerator: float | pd.Series,
    denominator: float | pd.Series,
    floor: float = 1e-9,
) -> float | pd.Series:
    """
    Divide numerator by denominator, clipping denominator to avoid
    division by zero or near-zero values.

    Parameters
    ----------
    numerator : float or Series
    denominator : float or Series
    floor : float
        Minimum absolute value for the denominator.

    Returns
    -------
    float or Series
    """
    if isinstance(denominator, pd.Series):
        safe_denom = denominator.clip(lower=floor)
        return numerator / safe_denom
    else:
        safe_denom = max(abs(denominator), floor)
        if denominator < 0:
            safe_denom = -safe_denom
        return numerator / safe_denom
