"""
Venue & Pitch Difficulty Adjustment — Feature 9 from Version 0.2 roadmap.

Computes per-venue difficulty baselines from match context data, and a
career-level "Flat Track Bully" index that measures whether a batter
performs better at easier or harder venues.

Key outputs
-----------
- **Venue baselines**: Per-venue statistics (average par SR, boundary rate,
  difficulty score) derived from match context.
- **Flat Track Bully Index**: Career-level correlation between a batter's
  SR-vs-par performance and venue difficulty.  Positive = performs better at
  harder venues (clutch); negative = only excels at easy venues (flat-track
  bully).
- **Venue-adjusted performance**: Per-innings SR-vs-par adjusted by venue
  difficulty, and career-level venue-adjusted composite.

Design
------
- ``compute_venue_baselines()`` aggregates match context by venue, computes
  a normalised difficulty score (positive = harder, negative = easier), and
  filters by minimum match threshold.
- ``compute_flat_track_index()`` merges venue difficulty onto per-innings
  batting data and computes a Pearson correlation between performance and
  difficulty at the career level.
- ``compute_venue_adjusted_performance()`` produces a per-innings adjustment
  factor and a career-level venue-adjusted composite that rewards runs
  scored at difficult venues.
- ``compute_bowling_venue_baselines()`` and ``compute_bowling_flat_track_index()``
  provide the bowling equivalents.

All functions are pure — they take DataFrames in and return DataFrames out,
with no side effects or config reads (config is resolved by the caller in
``main.py``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# 1. Venue Baselines
# ──────────────────────────────────────────────────────────────────────────


def compute_venue_baselines(
    match_ctx: pd.DataFrame,
    min_matches: int = 5,
) -> pd.DataFrame:
    """
    Compute per-venue difficulty baselines from match context.

    Parameters
    ----------
    match_ctx : pd.DataFrame
        One row per match, must contain at least:
        ``match_id``, ``match_par_sr``, ``match_boundary_rate``,
        ``match_dot_pct``, ``match_date``.
        The ``venue`` column may be present here (if enriched upstream)
        or will need to be joined before calling this function.
    min_matches : int
        Minimum number of matches at a venue to include it in baselines.
        Venues with fewer matches are excluded (returns NaN when joined).

    Returns
    -------
    pd.DataFrame with columns:
        venue, venue_matches, venue_avg_par_sr, venue_par_std,
        venue_avg_boundary_rate, venue_avg_dot_pct,
        venue_difficulty, venue_difficulty_raw, venue_difficulty_index
    """
    if match_ctx.empty or "venue" not in match_ctx.columns:
        return pd.DataFrame(
            columns=[
                "venue",
                "venue_matches",
                "venue_avg_par_sr",
                "venue_par_std",
                "venue_avg_boundary_rate",
                "venue_avg_dot_pct",
                "venue_difficulty",
                "venue_difficulty_raw",
                "venue_difficulty_index",
            ]
        )

    df = match_ctx.copy()

    # Ensure venue is a plain string for groupby
    if hasattr(df["venue"], "cat"):
        df["venue"] = df["venue"].astype(str)

    # ── Per-venue aggregates ──
    venue_stats = (
        df.groupby("venue")
        .agg(
            venue_matches=("match_id", "nunique"),
            venue_avg_par_sr=("match_par_sr", "mean"),
            venue_par_std=("match_par_sr", "std"),
            venue_avg_boundary_rate=("match_boundary_rate", "mean"),
            venue_avg_dot_pct=("match_dot_pct", "mean"),
        )
        .reset_index()
    )

    # Fill NaN std (single-match venues) with 0 before filtering
    venue_stats["venue_par_std"] = venue_stats["venue_par_std"].fillna(0.0)

    # ── Filter by minimum matches ──
    venue_stats = venue_stats[venue_stats["venue_matches"] >= min_matches].copy()

    if venue_stats.empty:
        venue_stats["venue_difficulty"] = pd.Series(dtype=float)
        venue_stats["venue_difficulty_raw"] = pd.Series(dtype=float)
        venue_stats["venue_difficulty_index"] = pd.Series(dtype=float)
        return venue_stats

    # ── Global average par SR for comparison ──
    # Use all matches (not just qualified venues) for a fair global baseline
    global_avg_par = df["match_par_sr"].mean()

    # ── Raw difficulty: positive = harder (lower-scoring), negative = easier ──
    # This is the absolute difference from the global mean, in SR points.
    venue_stats["venue_difficulty_raw"] = (
        global_avg_par - venue_stats["venue_avg_par_sr"]
    )

    # ── Normalised difficulty: divide by venue std to get a z-like score ──
    # Clamp std to avoid division by zero / extreme values at low-variance
    # venues.  A venue with very consistent conditions gets std clipped to
    # a minimum, which means a small raw difference still maps to a small
    # normalised score (the venue is genuinely close to average).
    _min_std = max(df["match_par_sr"].std() * 0.25, 1.0)
    venue_stats["venue_difficulty"] = venue_stats["venue_difficulty_raw"] / (
        venue_stats["venue_par_std"].clip(lower=_min_std)
    )

    # Display scale 0–100: percentile rank among venues (higher = harder conditions).
    # Underlying venue_difficulty stays z-like for correlations and adjustments.
    _vd = venue_stats["venue_difficulty"]
    venue_stats["venue_difficulty_index"] = (
        _vd.rank(method="average", pct=True, ascending=True) * 100.0
    ).where(_vd.notna())

    return venue_stats


# ──────────────────────────────────────────────────────────────────────────
# 2. Flat Track Bully Index (Batting)
# ──────────────────────────────────────────────────────────────────────────


def compute_flat_track_index(
    bat_innings: pd.DataFrame,
    venue_baselines: pd.DataFrame,
    min_innings: int = 6,
    performance_col: str = "acc_overall_sr",
) -> pd.DataFrame:
    """
    Compute a career-level Flat Track Bully Index for each batter.

    The index is the Pearson correlation between a batter's per-innings
    performance metric and the venue difficulty of each innings.

    * **Positive** correlation → batter performs *better* at harder venues
      (anti-flat-track bully; clutch performer).
    * **Negative** correlation → batter's best innings come at easy venues
      (flat-track bully).
    * **Near zero** → no venue-dependent bias.

    Parameters
    ----------
    bat_innings : pd.DataFrame
        Per-innings batting data.  Must contain ``batter_id``, ``batter``,
        ``match_id``, ``venue`` (or joinable via match_id), and a numeric
        performance column (default ``acc_overall_sr``).
    venue_baselines : pd.DataFrame
        Output of ``compute_venue_baselines()``.
    min_innings : int
        Minimum innings at venues with known baselines to produce an index.
        Players below this threshold get NaN.
    performance_col : str
        Column name for the per-innings performance metric.

    Returns
    -------
    pd.DataFrame with columns:
        batter_id, batter, flat_track_index, ft_innings_at_known_venues,
        avg_venue_difficulty_faced
    """
    empty = pd.DataFrame(
        columns=[
            "batter_id",
            "batter",
            "flat_track_index",
            "ft_innings_at_known_venues",
            "avg_venue_difficulty_faced",
        ]
    )

    if bat_innings.empty or venue_baselines.empty:
        return empty

    if "venue" not in bat_innings.columns:
        return empty

    if performance_col not in bat_innings.columns:
        return empty

    # ── Merge venue difficulty onto innings ──
    merged = bat_innings.merge(
        venue_baselines[["venue", "venue_difficulty"]],
        on="venue",
        how="left",
    )

    # Drop innings at unknown venues (NaN difficulty)
    merged = merged.dropna(subset=["venue_difficulty", performance_col])

    if merged.empty:
        return empty

    # ── Career-level correlation ──
    def _corr(g: pd.DataFrame) -> pd.Series:
        perf = g[performance_col].values
        diff = g["venue_difficulty"].values

        n = len(g)
        if n < min_innings:
            return pd.Series(
                {
                    "flat_track_index": np.nan,
                    "ft_innings_at_known_venues": n,
                    "avg_venue_difficulty_faced": diff.mean(),
                }
            )

        # Check for zero variance (all same performance or same venue)
        if np.std(perf) < 1e-12 or np.std(diff) < 1e-12:
            return pd.Series(
                {
                    "flat_track_index": 0.0,
                    "ft_innings_at_known_venues": n,
                    "avg_venue_difficulty_faced": diff.mean(),
                }
            )

        corr_val = np.corrcoef(perf, diff)[0, 1]
        if np.isnan(corr_val):
            corr_val = 0.0

        return pd.Series(
            {
                "flat_track_index": float(corr_val),
                "ft_innings_at_known_venues": n,
                "avg_venue_difficulty_faced": float(diff.mean()),
            }
        )

    result = (
        merged.groupby(["batter_id", "batter"], observed=True)
        .apply(_corr, include_groups=False)
        .reset_index()
    )

    # Ensure correct dtypes
    result["flat_track_index"] = result["flat_track_index"].astype(float)
    result["ft_innings_at_known_venues"] = result["ft_innings_at_known_venues"].astype(
        int
    )
    result["avg_venue_difficulty_faced"] = result["avg_venue_difficulty_faced"].astype(
        float
    )

    return result


# ──────────────────────────────────────────────────────────────────────────
# 3. Venue-Adjusted Performance (Batting)
# ──────────────────────────────────────────────────────────────────────────


def compute_venue_adjusted_performance(
    bat_innings: pd.DataFrame,
    venue_baselines: pd.DataFrame,
    performance_col: str = "acc_overall_sr",
) -> pd.DataFrame:
    """
    Produce a venue-adjusted performance column for each batting innings.

    The adjustment boosts performances at harder venues and discounts
    performances at easier venues.  The adjustment factor is:

        adjustment = 1.0 + venue_difficulty * scale

    where ``scale`` maps venue difficulty to a proportional bonus/penalty
    (capped at ±30% to avoid extreme distortions).

    At the career level, a venue-adjusted composite is the weighted mean
    of adjusted performance, using ``opp_quality_weight`` if available.

    Parameters
    ----------
    bat_innings : pd.DataFrame
        Per-innings batting data with ``venue`` column.
    venue_baselines : pd.DataFrame
        Output of ``compute_venue_baselines()``.
    performance_col : str
        Column for the raw performance metric to adjust.

    Returns
    -------
    pd.DataFrame
        Career-level DataFrame with:
        batter_id, batter, venue_adjusted_composite, raw_composite_mean,
        venue_boost_pct (average % boost/penalty from venue adjustment)
    """
    empty = pd.DataFrame(
        columns=[
            "batter_id",
            "batter",
            "venue_adjusted_composite",
            "raw_composite_mean",
            "venue_boost_pct",
        ]
    )

    if bat_innings.empty or venue_baselines.empty:
        return empty

    if "venue" not in bat_innings.columns or performance_col not in bat_innings.columns:
        return empty

    merged = bat_innings.merge(
        venue_baselines[["venue", "venue_difficulty"]],
        on="venue",
        how="left",
    )

    # Fill unknown venues with 0 difficulty (neutral)
    merged["venue_difficulty"] = merged["venue_difficulty"].fillna(0.0)

    # ── Per-innings adjustment factor ──
    # Scale: 0.10 per unit of venue difficulty, capped at ±30%
    VENUE_SCALE = 0.10
    MAX_ADJUSTMENT = 0.30
    merged["venue_adj_factor"] = 1.0 + (merged["venue_difficulty"] * VENUE_SCALE).clip(
        lower=-MAX_ADJUSTMENT, upper=MAX_ADJUSTMENT
    )

    # Adjusted performance
    raw_perf = merged[performance_col].fillna(0.0)
    merged["venue_adjusted_perf"] = raw_perf * merged["venue_adj_factor"]

    # ── Career-level aggregate ──
    has_weight = "opp_quality_weight" in merged.columns

    def _career_agg(g: pd.DataFrame) -> pd.Series:
        adj = g["venue_adjusted_perf"].values
        raw = g[performance_col].fillna(0.0).values
        factors = g["venue_adj_factor"].values

        if has_weight:
            w = g["opp_quality_weight"].fillna(1.0).values
        else:
            w = np.ones(len(g))

        w_sum = w.sum()
        if w_sum < 1e-12:
            return pd.Series(
                {
                    "venue_adjusted_composite": np.nan,
                    "raw_composite_mean": np.nan,
                    "venue_boost_pct": 0.0,
                }
            )

        va_comp = np.average(adj, weights=w)
        raw_comp = np.average(raw, weights=w)
        avg_factor = np.average(factors, weights=w)

        return pd.Series(
            {
                "venue_adjusted_composite": float(va_comp),
                "raw_composite_mean": float(raw_comp),
                "venue_boost_pct": float((avg_factor - 1.0) * 100.0),
            }
        )

    result = (
        merged.groupby(["batter_id", "batter"], observed=True)
        .apply(_career_agg, include_groups=False)
        .reset_index()
    )

    return result


# ──────────────────────────────────────────────────────────────────────────
# 4. Bowling Venue Baselines & Flat Track Index
# ──────────────────────────────────────────────────────────────────────────


def compute_bowling_flat_track_index(
    bowl_spells: pd.DataFrame,
    venue_baselines: pd.DataFrame,
    min_spells: int = 6,
    performance_col: str = "acc_economy_vs_par",
) -> pd.DataFrame:
    """
    Compute a career-level venue difficulty correlation for bowlers.

    For bowlers, we INVERT the correlation logic: a bowler who performs
    *better* (lower economy vs par) at harder venues is rewarded.

    Since ``acc_economy_vs_par`` is negative-is-better, a **negative**
    correlation with venue difficulty (harder venue → lower/better economy)
    would mean the bowler steps up at tough venues.  We flip the sign so
    the output matches the batting convention:

    * **Positive** → bowler performs better at harder venues (good).
    * **Negative** → bowler's best figures come at easy venues (bad).

    Parameters
    ----------
    bowl_spells : pd.DataFrame
        Per-spell bowling data with ``bowler_id``, ``bowler``, ``venue``,
        and a performance column.
    venue_baselines : pd.DataFrame
        Output of ``compute_venue_baselines()``.
    min_spells : int
        Minimum spells at known venues for an index.
    performance_col : str
        Performance metric.  For economy-type columns where lower is better,
        the correlation sign is flipped.

    Returns
    -------
    pd.DataFrame with:
        bowler_id, bowler, flat_track_index_bowl,
        ft_spells_at_known_venues, avg_venue_difficulty_faced
    """
    empty = pd.DataFrame(
        columns=[
            "bowler_id",
            "bowler",
            "flat_track_index_bowl",
            "ft_spells_at_known_venues",
            "avg_venue_difficulty_faced",
        ]
    )

    if bowl_spells.empty or venue_baselines.empty:
        return empty

    if "venue" not in bowl_spells.columns:
        return empty

    if performance_col not in bowl_spells.columns:
        return empty

    merged = bowl_spells.merge(
        venue_baselines[["venue", "venue_difficulty"]],
        on="venue",
        how="left",
    )

    merged = merged.dropna(subset=["venue_difficulty", performance_col])

    if merged.empty:
        return empty

    # Determine if the performance column is "lower is better"
    # Economy-type columns: lower = better → invert correlation sign
    _economy_cols = {
        "acc_economy_vs_par",
        "ctrl_economy_vs_par",
        "bowler_economy",
        "economy",
    }
    invert = performance_col in _economy_cols

    def _corr(g: pd.DataFrame) -> pd.Series:
        perf = g[performance_col].values
        diff = g["venue_difficulty"].values

        n = len(g)
        if n < min_spells:
            return pd.Series(
                {
                    "flat_track_index_bowl": np.nan,
                    "ft_spells_at_known_venues": n,
                    "avg_venue_difficulty_faced": diff.mean(),
                }
            )

        if np.std(perf) < 1e-12 or np.std(diff) < 1e-12:
            return pd.Series(
                {
                    "flat_track_index_bowl": 0.0,
                    "ft_spells_at_known_venues": n,
                    "avg_venue_difficulty_faced": diff.mean(),
                }
            )

        corr_val = np.corrcoef(perf, diff)[0, 1]
        if np.isnan(corr_val):
            corr_val = 0.0

        # Invert for economy-type metrics so positive = good
        if invert:
            corr_val = -corr_val

        return pd.Series(
            {
                "flat_track_index_bowl": float(corr_val),
                "ft_spells_at_known_venues": n,
                "avg_venue_difficulty_faced": float(diff.mean()),
            }
        )

    result = (
        merged.groupby(["bowler_id", "bowler"], observed=True)
        .apply(_corr, include_groups=False)
        .reset_index()
    )

    result["flat_track_index_bowl"] = result["flat_track_index_bowl"].astype(float)
    result["ft_spells_at_known_venues"] = result["ft_spells_at_known_venues"].astype(
        int
    )
    result["avg_venue_difficulty_faced"] = result["avg_venue_difficulty_faced"].astype(
        float
    )

    return result


# ──────────────────────────────────────────────────────────────────────────
# 5. Venue enrichment helpers
# ──────────────────────────────────────────────────────────────────────────


def enrich_match_context_with_venue(
    match_ctx: pd.DataFrame,
    deliveries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add ``venue`` to match context DataFrame by joining from deliveries.

    The parser stores ``venue`` on every delivery row.  Match context
    (computed from innings context) doesn't carry it, so this helper
    extracts the unique (match_id, venue) mapping and merges it.

    Parameters
    ----------
    match_ctx : pd.DataFrame
        Output of ``build_full_context()`` — one row per match_id.
    deliveries : pd.DataFrame
        Raw delivery-level DataFrame from the parser.

    Returns
    -------
    pd.DataFrame
        Same as ``match_ctx`` with ``venue`` column added.
    """
    if "venue" in match_ctx.columns:
        return match_ctx

    if "venue" not in deliveries.columns:
        return match_ctx

    venue_map = deliveries[["match_id", "venue"]].drop_duplicates(subset=["match_id"])

    # Ensure both are string type for merge
    for c in ["match_id"]:
        if hasattr(venue_map[c], "cat"):
            venue_map[c] = venue_map[c].astype(str)
        if hasattr(match_ctx[c], "cat"):
            match_ctx = match_ctx.copy()
            match_ctx[c] = match_ctx[c].astype(str)

    result = match_ctx.merge(venue_map, on="match_id", how="left")
    return result


def enrich_innings_with_venue(
    innings_df: pd.DataFrame,
    deliveries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add ``venue`` to a per-innings DataFrame (batting or bowling) by
    joining from deliveries.

    Parameters
    ----------
    innings_df : pd.DataFrame
        Per-innings batting or bowling data with ``match_id``.
    deliveries : pd.DataFrame
        Raw delivery-level DataFrame from the parser.

    Returns
    -------
    pd.DataFrame
        Same as ``innings_df`` with ``venue`` column added.
    """
    if "venue" in innings_df.columns:
        return innings_df

    if "venue" not in deliveries.columns:
        return innings_df

    venue_map = deliveries[["match_id", "venue"]].drop_duplicates(subset=["match_id"])

    # Ensure match_id types are compatible
    for c in ["match_id"]:
        if hasattr(venue_map[c], "cat"):
            venue_map[c] = venue_map[c].astype(str)

    df = innings_df.copy()
    if hasattr(df["match_id"], "cat"):
        df["match_id"] = df["match_id"].astype(str)

    result = df.merge(venue_map, on="match_id", how="left")
    return result


def enrich_innings_with_match_meta(
    innings_df: pd.DataFrame,
    deliveries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add match-level metadata from deliveries: ``event_name``, ``winner``.

    Joins on ``match_id`` only so every innings row for that match gets the
    same values (GUI venue pages, chase/defend, team W/L).
    """
    if innings_df.empty or deliveries.empty:
        return innings_df

    want = [c for c in ("event_name", "winner") if c in deliveries.columns]
    if not want:
        return innings_df

    df = innings_df.copy()
    meta = (
        deliveries.groupby("match_id", observed=True)[want]
        .first()
        .reset_index()
    )

    for c in ["match_id"]:
        if c in meta.columns and hasattr(meta[c], "cat"):
            meta[c] = meta[c].astype(str)
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)

    for col in want:
        if col in df.columns:
            df = df.drop(columns=[col])

    return df.merge(meta, on="match_id", how="left")


# ──────────────────────────────────────────────────────────────────────────
# 6. Convenience: run all venue computations
# ──────────────────────────────────────────────────────────────────────────


def compute_all_venue_metrics(
    match_ctx: pd.DataFrame,
    deliveries: pd.DataFrame,
    bat_innings: pd.DataFrame,
    bowl_spells: pd.DataFrame,
    min_matches: int = 5,
    min_bat_innings: int = 6,
    min_bowl_spells: int = 6,
    batting_perf_col: str = "acc_overall_sr",
    bowling_perf_col: str = "acc_economy_vs_par",
) -> dict[str, pd.DataFrame]:
    """
    Run the full venue analysis pipeline and return all outputs.

    This is a convenience wrapper that:
    1. Enriches match context and innings data with venue.
    2. Computes venue baselines.
    3. Computes flat track bully index (batting + bowling).
    4. Computes venue-adjusted batting performance.

    Parameters
    ----------
    match_ctx : pd.DataFrame
        One row per match (from context module).
    deliveries : pd.DataFrame
        Raw delivery-level data (from parser).
    bat_innings : pd.DataFrame
        Per-innings batting data (bat_components).
    bowl_spells : pd.DataFrame
        Per-spell bowling data (bowl_components).
    min_matches : int
        Minimum matches at a venue for baseline inclusion.
    min_bat_innings : int
        Minimum batting innings at known venues for flat track index.
    min_bowl_spells : int
        Minimum bowling spells at known venues for flat track index.
    batting_perf_col : str
        Batting performance column for flat track correlation.
    bowling_perf_col : str
        Bowling performance column for flat track correlation.

    Returns
    -------
    dict with keys:
        ``venue_baselines``, ``flat_track_batting``, ``flat_track_bowling``,
        ``venue_adjusted_batting``, ``match_ctx_with_venue``
    """
    # 1. Enrich with venue
    match_ctx_v = enrich_match_context_with_venue(match_ctx, deliveries)
    bat_innings_v = enrich_innings_with_venue(bat_innings, deliveries)
    bowl_spells_v = enrich_innings_with_venue(bowl_spells, deliveries)

    # 2. Venue baselines
    baselines = compute_venue_baselines(match_ctx_v, min_matches=min_matches)

    # 3. Flat track bully (batting)
    ft_batting = compute_flat_track_index(
        bat_innings_v,
        baselines,
        min_innings=min_bat_innings,
        performance_col=batting_perf_col,
    )

    # 4. Flat track bully (bowling)
    ft_bowling = compute_bowling_flat_track_index(
        bowl_spells_v,
        baselines,
        min_spells=min_bowl_spells,
        performance_col=bowling_perf_col,
    )

    # 5. Venue-adjusted batting performance
    va_batting = compute_venue_adjusted_performance(
        bat_innings_v,
        baselines,
        performance_col=batting_perf_col,
    )

    return {
        "venue_baselines": baselines,
        "flat_track_batting": ft_batting,
        "flat_track_bowling": ft_bowling,
        "venue_adjusted_batting": va_batting,
        "match_ctx_with_venue": match_ctx_v,
    }
