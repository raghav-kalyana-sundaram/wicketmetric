"""
Feature 4: Head-to-Head / Matchup Analysis

Generates batter × bowler matchup statistics from the delivery-level DataFrame.

Since bowling_style is not available in Cricsheet JSON data, matchups are
built from the existing batter_id × bowler_id pairings, with optional
phase-level breakdowns.

Key outputs
-----------
- ``matchups`` : Per (batter, bowler) aggregate stats — balls faced, runs,
  SR, dots, boundaries, dismissals, dominance index.
- ``matchups_by_phase`` : Same but split by phase (powerplay / middle / death).
- ``batter_bowling_style_matchups`` : If an external bowling-style lookup is
  provided, aggregates batter performance vs each bowling style.
- ``dominance_index`` : A single number summarising who "wins" in a matchup
  (positive = batter dominates, negative = bowler dominates).
- ``bayesian_matchup_quality`` : Shrunk matchup estimate that blends the
  sparse head-to-head record toward broader archetype baselines, per
  algorithm_update.md's Multilevel Mixed-Effects Matchup Model section.

Integration
-----------
Called from ``main.py`` after delivery parsing and context computation.
Output as ``matchups.parquet`` and optionally ``matchups_by_phase.parquet``
in the output directory.

The module is deliberately self-contained: it only needs the raw delivery
DataFrame and does NOT depend on batting/bowling component DataFrames
(except for optional archetype-based shrinkage).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# ───────────────────────────────────────────────────────────────────────────
# Configuration defaults (overridable via config.yaml → matchups.*)
# ───────────────────────────────────────────────────────────────────────────

_DEFAULT_MIN_BALLS = 6  # Minimum batter-balls faced in a matchup to include
_DEFAULT_MIN_BALLS_PHASE = 4  # Min batter-balls per phase matchup
_DEFAULT_TOP_K_BUNNIES = 5  # Top-K bunnies / nemeses per player
_DEFAULT_TOP_K_DOMINANT = 5  # Top-K dominated matchups per player

# Bayesian shrinkage defaults for matchup quality estimation
_DEFAULT_SHRINKAGE_BALLS = 30  # Balls at which head-to-head data equals prior weight


# ───────────────────────────────────────────────────────────────────────────
# Internal helpers
# ───────────────────────────────────────────────────────────────────────────


def _decat(df: pd.DataFrame, cols: list[str]) -> None:
    """Convert categorical columns to plain strings (in-place)."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)


def _safe_sr(runs: pd.Series, balls: pd.Series) -> pd.Series:
    """Strike rate = runs / balls * 100, safe against zero division."""
    return pd.Series(
        np.where(balls > 0, runs / balls * 100.0, np.nan),
        index=runs.index,
    )


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """Safe float division, returning NaN where denominator is 0."""
    return pd.Series(
        np.where(den > 0, num / den, np.nan),
        index=num.index,
    )


# ───────────────────────────────────────────────────────────────────────────
# Core: compute raw matchup aggregates
# ───────────────────────────────────────────────────────────────────────────


def compute_matchups(
    deliveries: pd.DataFrame,
    *,
    min_balls: int = _DEFAULT_MIN_BALLS,
    include_phase: bool = True,
    bowling_style_lookup: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Compute head-to-head matchup statistics from the delivery DataFrame.

    Parameters
    ----------
    deliveries : pd.DataFrame
        Raw delivery-level DataFrame from ``parser.parse_all_matches()``.
        Required columns: ``batter_id``, ``batter``, ``bowler_id``,
        ``bowler``, ``batter_runs``, ``is_batter_ball``, ``is_wicket``,
        ``is_four``, ``is_six``, ``is_dot_batter``, ``phase``,
        ``match_id``, ``innings_num``, ``is_wide``.
    min_balls : int
        Minimum number of *batter balls* faced in a matchup for it to be
        included in the output.  Default 6.
    include_phase : bool
        If True, also produce phase-level breakdowns.
    bowling_style_lookup : pd.DataFrame | None
        Optional lookup table with columns ``bowler_id`` and
        ``bowling_style``.  If provided, an additional output keyed by
        ``batter_id × bowling_style`` is generated.

    Returns
    -------
    dict with keys:
        ``matchups`` : pd.DataFrame
            One row per (batter_id, bowler_id) pair.
        ``matchups_by_phase`` : pd.DataFrame
            One row per (batter_id, bowler_id, phase) triple.
            Empty DataFrame if ``include_phase=False``.
        ``bowling_style_matchups`` : pd.DataFrame
            One row per (batter_id, bowling_style) pair.
            Empty DataFrame if ``bowling_style_lookup`` is None.
    """
    df = deliveries.copy()
    _decat(
        df,
        [
            "match_id",
            "batter_id",
            "batter",
            "bowler_id",
            "bowler",
            "phase",
            "player_out",
            "player_out_id",
            "wicket_kind",
            "batting_team",
            "bowling_team",
        ],
    )

    # ── Filter to batter-balls only (exclude wides) ──────────────────────
    faced = df[df["is_batter_ball"] == True].copy()  # noqa: E712

    if faced.empty:
        empty = pd.DataFrame()
        return {
            "matchups": empty,
            "matchups_by_phase": empty,
            "bowling_style_matchups": empty,
        }

    # ── Pre-compute per-delivery helper columns ──────────────────────────
    # Dismissal attributed to the bowler (not run-outs)
    bowler_dismissal_kinds = {
        "bowled",
        "caught",
        "caught and bowled",
        "lbw",
        "stumped",
        "hit wicket",
    }
    wk_kind = faced["wicket_kind"].fillna("").str.lower()
    faced["is_bowler_dismissal"] = (
        faced["is_wicket"]
        & wk_kind.isin(bowler_dismissal_kinds)
        & (faced["player_out_id"] == faced["batter_id"])
    )

    faced["is_boundary"] = faced["is_four"] | faced["is_six"]

    # ── 1. Overall matchups (batter × bowler) ────────────────────────────
    matchups = _aggregate_matchup(
        faced,
        group_cols=["batter_id", "batter", "bowler_id", "bowler"],
        min_balls=min_balls,
    )

    # ── 2. Phase-level matchups ──────────────────────────────────────────
    matchups_by_phase = pd.DataFrame()
    if include_phase:
        matchups_by_phase = _aggregate_matchup(
            faced,
            group_cols=["batter_id", "batter", "bowler_id", "bowler", "phase"],
            min_balls=max(min_balls // 2, _DEFAULT_MIN_BALLS_PHASE),
        )

    # ── 3. Bowling-style matchups (if lookup provided) ───────────────────
    style_matchups = pd.DataFrame()
    if bowling_style_lookup is not None and not bowling_style_lookup.empty:
        style_matchups = _compute_bowling_style_matchups(
            faced, bowling_style_lookup, min_balls=min_balls
        )

    return {
        "matchups": matchups,
        "matchups_by_phase": matchups_by_phase,
        "bowling_style_matchups": style_matchups,
    }


def _aggregate_matchup(
    faced: pd.DataFrame,
    group_cols: list[str],
    min_balls: int,
) -> pd.DataFrame:
    """
    Aggregate batter-faced deliveries by the given grouping columns.

    Produces batting stats + a dominance index for each group.
    """
    grp = faced.groupby(group_cols, observed=True)

    agg = grp.agg(
        balls_faced=("batter_runs", "size"),
        runs_scored=("batter_runs", "sum"),
        dots=("is_dot_batter", "sum"),
        fours=("is_four", "sum"),
        sixes=("is_six", "sum"),
        boundaries=("is_boundary", "sum"),
        dismissals=("is_bowler_dismissal", "sum"),
        total_wickets=("is_wicket", "sum"),
        matches=("match_id", "nunique"),
    ).reset_index()

    # Filter by minimum balls
    agg = agg[agg["balls_faced"] >= min_balls].copy()

    if agg.empty:
        return agg

    # ── Derived metrics ──────────────────────────────────────────────────
    agg["strike_rate"] = _safe_sr(agg["runs_scored"], agg["balls_faced"])

    agg["dot_pct"] = _safe_div(agg["dots"], agg["balls_faced"])

    agg["boundary_pct"] = _safe_div(agg["boundaries"], agg["balls_faced"])

    # Average (runs per dismissal; if no dismissal, uses balls_faced as proxy
    # capped to avoid inflating average for undismissed batters)
    agg["average"] = np.where(
        agg["dismissals"] > 0,
        agg["runs_scored"] / agg["dismissals"],
        agg["runs_scored"].astype(float),  # not-out: just use total runs
    )

    # ── Dominance Index ──────────────────────────────────────────────────
    # A composite measure: positive = batter dominates, negative = bowler.
    #
    # Components (all normalised to similar scale):
    #   + SR premium    : (SR - 130) / 100   (130 is a reasonable T20 par)
    #   + Boundary rate : boundary_pct * 2
    #   - Dot penalty   : dot_pct * -1.5
    #   - Dismissal rate: dismissals / balls * -10
    #
    # The index is roughly on a -2 to +2 scale.
    sr_premium = (agg["strike_rate"].fillna(130.0) - 130.0) / 100.0
    bdry_bonus = agg["boundary_pct"].fillna(0) * 2.0
    dot_penalty = agg["dot_pct"].fillna(0) * -1.5
    dismissal_rate = _safe_div(agg["dismissals"], agg["balls_faced"]).fillna(0) * -10.0

    agg["dominance_index"] = sr_premium + bdry_bonus + dot_penalty + dismissal_rate

    # Confidence — how much to trust the raw matchup data (0 → 1 as balls grow)
    # This is exposed for downstream Bayesian shrinkage.
    agg["matchup_confidence"] = agg["balls_faced"] / (
        agg["balls_faced"] + _DEFAULT_SHRINKAGE_BALLS
    )

    # Round for readability
    for c in [
        "strike_rate",
        "dot_pct",
        "boundary_pct",
        "average",
        "dominance_index",
        "matchup_confidence",
    ]:
        if c in agg.columns:
            agg[c] = agg[c].round(4)

    # Sort by most balls faced (most meaningful matchups first)
    agg = agg.sort_values("balls_faced", ascending=False).reset_index(drop=True)

    return agg


# ───────────────────────────────────────────────────────────────────────────
# Bowling-style matchups (requires external lookup)
# ───────────────────────────────────────────────────────────────────────────


def _compute_bowling_style_matchups(
    faced: pd.DataFrame,
    bowling_style_lookup: pd.DataFrame,
    min_balls: int = _DEFAULT_MIN_BALLS,
) -> pd.DataFrame:
    """
    Aggregate batter performance vs each bowling style.

    Parameters
    ----------
    faced : pd.DataFrame
        Delivery-level DataFrame (already filtered to batter-balls).
    bowling_style_lookup : pd.DataFrame
        Must contain ``bowler_id`` and ``bowling_style`` columns.
    min_balls : int
        Minimum batter-balls against a style to include.
    """
    if "bowling_style" not in bowling_style_lookup.columns:
        return pd.DataFrame()

    lookup = bowling_style_lookup[["bowler_id", "bowling_style"]].drop_duplicates()
    merged = faced.merge(lookup, on="bowler_id", how="inner")

    if merged.empty:
        return pd.DataFrame()

    return _aggregate_matchup(
        merged,
        group_cols=["batter_id", "batter", "bowling_style"],
        min_balls=min_balls,
    )


# ───────────────────────────────────────────────────────────────────────────
# Player-centric views: bunnies, nemeses, dominant matchups
# ───────────────────────────────────────────────────────────────────────────


def find_batter_nemeses(
    matchups: pd.DataFrame,
    *,
    top_k: int = _DEFAULT_TOP_K_BUNNIES,
    min_balls: int = _DEFAULT_MIN_BALLS,
) -> pd.DataFrame:
    """
    For each batter, find the bowlers who trouble them most.

    A "nemesis" is a bowler with the lowest dominance_index (bowler-
    favourable) against this batter, with at least ``min_balls`` faced.

    Returns
    -------
    pd.DataFrame
        Long-form: one row per (batter, rank) with the nemesis bowler info.
    """
    if matchups.empty:
        return pd.DataFrame()

    qualified = matchups[matchups["balls_faced"] >= min_balls].copy()
    if qualified.empty:
        return pd.DataFrame()

    # Sort: lowest dominance = biggest nemesis
    qualified = qualified.sort_values(
        ["batter_id", "dominance_index"], ascending=[True, True]
    )

    result = qualified.groupby("batter_id", observed=True).head(top_k).copy()
    result["nemesis_rank"] = result.groupby("batter_id", observed=True).cumcount() + 1

    return result.reset_index(drop=True)


def find_bowler_bunnies(
    matchups: pd.DataFrame,
    *,
    top_k: int = _DEFAULT_TOP_K_BUNNIES,
    min_balls: int = _DEFAULT_MIN_BALLS,
) -> pd.DataFrame:
    """
    For each bowler, find the batters they dominate most.

    A "bunny" is a batter with the lowest dominance_index (bowler-
    favourable) in their matchup, with at least ``min_balls`` faced.

    Returns
    -------
    pd.DataFrame
        Long-form: one row per (bowler, rank) with the bunny batter info.
    """
    if matchups.empty:
        return pd.DataFrame()

    qualified = matchups[matchups["balls_faced"] >= min_balls].copy()
    if qualified.empty:
        return pd.DataFrame()

    # Sort: lowest dominance = bowler dominates most
    qualified = qualified.sort_values(
        ["bowler_id", "dominance_index"], ascending=[True, True]
    )

    result = qualified.groupby("bowler_id", observed=True).head(top_k).copy()
    result["bunny_rank"] = result.groupby("bowler_id", observed=True).cumcount() + 1

    return result.reset_index(drop=True)


def find_batter_dominant_matchups(
    matchups: pd.DataFrame,
    *,
    top_k: int = _DEFAULT_TOP_K_DOMINANT,
    min_balls: int = _DEFAULT_MIN_BALLS,
) -> pd.DataFrame:
    """
    For each batter, find the bowlers they dominate most (highest
    dominance_index = most batter-favourable).

    Returns
    -------
    pd.DataFrame
        Long-form: one row per (batter, rank) with the dominated bowler info.
    """
    if matchups.empty:
        return pd.DataFrame()

    qualified = matchups[matchups["balls_faced"] >= min_balls].copy()
    if qualified.empty:
        return pd.DataFrame()

    # Sort: highest dominance = batter dominates most
    qualified = qualified.sort_values(
        ["batter_id", "dominance_index"], ascending=[True, False]
    )

    result = qualified.groupby("batter_id", observed=True).head(top_k).copy()
    result["dominant_rank"] = result.groupby("batter_id", observed=True).cumcount() + 1

    return result.reset_index(drop=True)


# ───────────────────────────────────────────────────────────────────────────
# Career-level summaries: how well does a batter handle variety?
# ───────────────────────────────────────────────────────────────────────────


def compute_matchup_diversity_stats(
    matchups: pd.DataFrame,
    min_balls: int = _DEFAULT_MIN_BALLS,
) -> pd.DataFrame:
    """
    Per batter, compute summary stats across all their qualified matchups.

    This tells you how *consistent* a batter is across different bowlers.

    Columns produced
    ----------------
    - ``unique_bowlers`` : Number of distinct bowlers faced (qualified)
    - ``avg_dominance`` : Mean dominance index across all matchups
    - ``std_dominance`` : Std dev of dominance index (lower = more consistent)
    - ``pct_dominant`` : Fraction of matchups where dominance_index > 0
    - ``worst_matchup_dominance`` : Lowest dominance index (worst matchup)
    - ``best_matchup_dominance`` : Highest dominance index (best matchup)
    - ``matchup_consistency`` : 1 - normalised std (higher = more consistent)
    """
    if matchups.empty:
        return pd.DataFrame()

    qualified = matchups[matchups["balls_faced"] >= min_balls].copy()
    if qualified.empty:
        return pd.DataFrame()

    # Need batter name for the output
    name_map = (
        qualified.groupby("batter_id", observed=True)["batter"].first().reset_index()
    )

    grp = qualified.groupby("batter_id", observed=True)

    stats = grp.agg(
        unique_bowlers=("bowler_id", "nunique"),
        avg_dominance=("dominance_index", "mean"),
        std_dominance=("dominance_index", "std"),
        worst_matchup_dominance=("dominance_index", "min"),
        best_matchup_dominance=("dominance_index", "max"),
        total_matchup_balls=("balls_faced", "sum"),
    ).reset_index()

    stats = stats.merge(name_map, on="batter_id", how="left")

    # Percentage of matchups the batter dominates (dominance > 0)
    pct_dom = (
        qualified[qualified["dominance_index"] > 0]
        .groupby("batter_id", observed=True)
        .size()
        .reset_index(name="dominant_count")
    )
    total_count = (
        qualified.groupby("batter_id", observed=True)
        .size()
        .reset_index(name="total_count")
    )
    pct_df = total_count.merge(pct_dom, on="batter_id", how="left")
    pct_df["dominant_count"] = pct_df["dominant_count"].fillna(0)
    pct_df["pct_dominant"] = pct_df["dominant_count"] / pct_df["total_count"]
    stats = stats.merge(
        pct_df[["batter_id", "pct_dominant"]], on="batter_id", how="left"
    )

    # Matchup consistency: 1 - normalised std_dominance
    # Normalise by the range (best - worst) to get a 0–1 scale
    dom_range = stats["best_matchup_dominance"] - stats["worst_matchup_dominance"]
    stats["matchup_consistency"] = np.where(
        dom_range > 0,
        1.0 - (stats["std_dominance"] / dom_range).clip(upper=1.0),
        1.0,  # No variation = perfectly consistent
    )

    # Round for readability
    for c in [
        "avg_dominance",
        "std_dominance",
        "worst_matchup_dominance",
        "best_matchup_dominance",
        "pct_dominant",
        "matchup_consistency",
    ]:
        if c in stats.columns:
            stats[c] = stats[c].round(4)

    # Reorder columns
    col_order = [
        "batter_id",
        "batter",
        "unique_bowlers",
        "total_matchup_balls",
        "avg_dominance",
        "std_dominance",
        "pct_dominant",
        "worst_matchup_dominance",
        "best_matchup_dominance",
        "matchup_consistency",
    ]
    col_order = [c for c in col_order if c in stats.columns]

    return (
        stats[col_order]
        .sort_values("avg_dominance", ascending=False)
        .reset_index(drop=True)
    )


def compute_bowler_matchup_summary(
    matchups: pd.DataFrame,
    min_balls: int = _DEFAULT_MIN_BALLS,
) -> pd.DataFrame:
    """
    Per bowler, compute summary stats across all their qualified matchups.

    Columns produced
    ----------------
    - ``unique_batters`` : Number of distinct batters faced (qualified)
    - ``avg_dominance`` : Mean dominance index across all matchups
      (lower = more bowler-dominant)
    - ``pct_dominant_bowl`` : Fraction of matchups where bowler wins
      (dominance_index < 0)
    - ``best_matchup_dominance`` : Lowest dominance (most bowler-favourable)
    - ``worst_matchup_dominance`` : Highest dominance (most batter-favourable)
    """
    if matchups.empty:
        return pd.DataFrame()

    qualified = matchups[matchups["balls_faced"] >= min_balls].copy()
    if qualified.empty:
        return pd.DataFrame()

    name_map = (
        qualified.groupby("bowler_id", observed=True)["bowler"].first().reset_index()
    )

    grp = qualified.groupby("bowler_id", observed=True)

    stats = grp.agg(
        unique_batters=("batter_id", "nunique"),
        avg_dominance=("dominance_index", "mean"),
        std_dominance=("dominance_index", "std"),
        best_matchup_dominance=("dominance_index", "min"),
        worst_matchup_dominance=("dominance_index", "max"),
        total_matchup_balls=("balls_faced", "sum"),
        total_dismissals=("dismissals", "sum"),
    ).reset_index()

    stats = stats.merge(name_map, on="bowler_id", how="left")

    # Fraction where bowler dominates (dominance < 0)
    bowl_dom = (
        qualified[qualified["dominance_index"] < 0]
        .groupby("bowler_id", observed=True)
        .size()
        .reset_index(name="bowl_dom_count")
    )
    total_count = (
        qualified.groupby("bowler_id", observed=True)
        .size()
        .reset_index(name="total_count")
    )
    pct_df = total_count.merge(bowl_dom, on="bowler_id", how="left")
    pct_df["bowl_dom_count"] = pct_df["bowl_dom_count"].fillna(0)
    pct_df["pct_dominant_bowl"] = pct_df["bowl_dom_count"] / pct_df["total_count"]
    stats = stats.merge(
        pct_df[["bowler_id", "pct_dominant_bowl"]], on="bowler_id", how="left"
    )

    for c in [
        "avg_dominance",
        "std_dominance",
        "best_matchup_dominance",
        "worst_matchup_dominance",
        "pct_dominant_bowl",
    ]:
        if c in stats.columns:
            stats[c] = stats[c].round(4)

    col_order = [
        "bowler_id",
        "bowler",
        "unique_batters",
        "total_matchup_balls",
        "total_dismissals",
        "avg_dominance",
        "std_dominance",
        "pct_dominant_bowl",
        "best_matchup_dominance",
        "worst_matchup_dominance",
    ]
    col_order = [c for c in col_order if c in stats.columns]

    # Sort by lowest avg dominance (bowler wins most)
    return (
        stats[col_order]
        .sort_values("avg_dominance", ascending=True)
        .reset_index(drop=True)
    )


# ───────────────────────────────────────────────────────────────────────────
# Pivot helpers for CSV output
# ───────────────────────────────────────────────────────────────────────────


def pivot_matchup_summary_for_batter(
    matchups: pd.DataFrame,
    batter_id: str,
    top_k: int = 10,
) -> pd.DataFrame:
    """
    Extract and rank all matchups for a single batter.

    Returns a DataFrame sorted by balls_faced descending, limited to top_k.
    Useful for player-profile pages.
    """
    if matchups.empty:
        return pd.DataFrame()

    player = matchups[matchups["batter_id"] == batter_id].copy()
    if player.empty:
        return pd.DataFrame()

    return (
        player.sort_values("balls_faced", ascending=False)
        .head(top_k)
        .reset_index(drop=True)
    )


def pivot_matchup_summary_for_bowler(
    matchups: pd.DataFrame,
    bowler_id: str,
    top_k: int = 10,
) -> pd.DataFrame:
    """
    Extract and rank all matchups for a single bowler.

    Returns a DataFrame sorted by balls_faced descending, limited to top_k.
    Useful for player-profile pages.
    """
    if matchups.empty:
        return pd.DataFrame()

    player = matchups[matchups["bowler_id"] == bowler_id].copy()
    if player.empty:
        return pd.DataFrame()

    return (
        player.sort_values("balls_faced", ascending=False)
        .head(top_k)
        .reset_index(drop=True)
    )


# ───────────────────────────────────────────────────────────────────────────
# Convenience wrapper (called from main.py)
# ───────────────────────────────────────────────────────────────────────────


def compute_all_matchup_metrics(
    deliveries: pd.DataFrame,
    *,
    min_balls: int = _DEFAULT_MIN_BALLS,
    include_phase: bool = True,
    bowling_style_lookup: pd.DataFrame | None = None,
    top_k_bunnies: int = _DEFAULT_TOP_K_BUNNIES,
    top_k_dominant: int = _DEFAULT_TOP_K_DOMINANT,
) -> dict[str, pd.DataFrame]:
    """
    Run the full matchup analysis pipeline and return all outputs.

    Parameters
    ----------
    deliveries : pd.DataFrame
        Raw delivery-level DataFrame.
    min_balls : int
        Minimum batter-balls for a qualified matchup.
    include_phase : bool
        Whether to produce phase-level breakdowns.
    bowling_style_lookup : pd.DataFrame | None
        Optional external lookup for bowling style.
    top_k_bunnies : int
        Number of top nemeses / bunnies per player.
    top_k_dominant : int
        Number of top dominant matchups per player.

    Returns
    -------
    dict with keys:
        ``matchups`` — overall batter × bowler matchups
        ``matchups_by_phase`` — phase-level matchups
        ``bowling_style_matchups`` — batter × bowling_style (if lookup given)
        ``batter_nemeses`` — top nemeses per batter
        ``bowler_bunnies`` — top bunnies per bowler
        ``batter_dominant`` — top dominant matchups per batter
        ``batter_diversity`` — matchup diversity stats per batter
        ``bowler_summary`` — matchup summary per bowler
    """
    # Step 1: Core matchup aggregation
    core = compute_matchups(
        deliveries,
        min_balls=min_balls,
        include_phase=include_phase,
        bowling_style_lookup=bowling_style_lookup,
    )

    matchups = core["matchups"]

    # Step 2: Player-centric views
    batter_nemeses = find_batter_nemeses(
        matchups, top_k=top_k_bunnies, min_balls=min_balls
    )
    bowler_bunnies = find_bowler_bunnies(
        matchups, top_k=top_k_bunnies, min_balls=min_balls
    )
    batter_dominant = find_batter_dominant_matchups(
        matchups, top_k=top_k_dominant, min_balls=min_balls
    )

    # Step 3: Career-level summaries
    batter_diversity = compute_matchup_diversity_stats(matchups, min_balls=min_balls)
    bowler_summary = compute_bowler_matchup_summary(matchups, min_balls=min_balls)

    return {
        "matchups": matchups,
        "matchups_by_phase": core["matchups_by_phase"],
        "bowling_style_matchups": core["bowling_style_matchups"],
        "batter_nemeses": batter_nemeses,
        "bowler_bunnies": bowler_bunnies,
        "batter_dominant": batter_dominant,
        "batter_diversity": batter_diversity,
        "bowler_summary": bowler_summary,
    }


# ───────────────────────────────────────────────────────────────────────────
# Bayesian Matchup Shrinkage (algorithm_update.md §Matchup Modeling)
# ───────────────────────────────────────────────────────────────────────────
#
# Per algorithm_update.md:
#   "To handle situations where a batter and bowler have only faced each
#   other for six deliveries, a Bayesian head-to-head random effect is
#   applied. This calculates the True Matchup Quality by shrinking the
#   small-sample head-to-head record toward the players' baseline
#   performances against similar player archetypes."
#
# Implementation:
#   For each (batter, bowler) matchup the "prior" is the batter's career
#   dominance index against all bowlers of the *same archetype* (or phase
#   group) as the specific bowler.  The posterior blends the observed
#   head-to-head dominance with this archetype prior using an Empirical
#   Bayes shrinkage factor proportional to balls faced:
#
#       λ = k / (n + k)
#       bayesian_dominance = (1 − λ) · observed + λ · archetype_prior
#
#   where k = _DEFAULT_SHRINKAGE_BALLS and n = balls_faced.
#
#   This allows the platform to generate projected matchup values even
#   for encounters with very sparse data, by leaning on the broader
#   archetype signal.


def compute_archetype_baselines(
    matchups: pd.DataFrame,
    bowler_archetypes: pd.DataFrame | None = None,
    batter_archetypes: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Compute archetype-level baseline dominance indices.

    For each batter, computes their average dominance index against each
    *bowler archetype* (or bowling phase group).  Symmetrically, for each
    bowler, computes how batters of each *batter archetype* (or position
    group) perform against them.

    Parameters
    ----------
    matchups : pd.DataFrame
        Output of ``compute_matchups()`` with at least ``batter_id``,
        ``bowler_id``, ``dominance_index``, ``balls_faced``.
    bowler_archetypes : pd.DataFrame, optional
        Must contain ``bowler_id`` and ``archetype`` (or ``phase_group``).
        If None, archetype-based shrinkage is skipped and a global prior
        is used instead.
    batter_archetypes : pd.DataFrame, optional
        Must contain ``batter_id`` and ``archetype`` (or ``position_group``).
        If None, batter archetype baselines are skipped.

    Returns
    -------
    dict with keys:
        ``batter_vs_bowler_archetype`` : pd.DataFrame
            One row per (batter_id, bowler_archetype) with
            ``archetype_dominance`` and ``archetype_balls``.
        ``bowler_vs_batter_archetype`` : pd.DataFrame
            One row per (bowler_id, batter_archetype) with
            ``archetype_dominance`` and ``archetype_balls``.
    """
    if matchups.empty:
        return {
            "batter_vs_bowler_archetype": pd.DataFrame(),
            "bowler_vs_batter_archetype": pd.DataFrame(),
        }

    m = matchups.copy()
    _decat(m, ["batter_id", "bowler_id"])

    batter_vs_bowler_arch = pd.DataFrame()
    bowler_vs_batter_arch = pd.DataFrame()

    # ── Batter vs bowler archetype baselines ──
    if bowler_archetypes is not None and not bowler_archetypes.empty:
        ba = bowler_archetypes.copy()
        # Determine archetype column name
        arch_col = None
        for candidate in ["archetype", "phase_group"]:
            if candidate in ba.columns:
                arch_col = candidate
                break

        if arch_col is not None:
            _decat(ba, ["bowler_id", arch_col])
            m_arch = m.merge(
                ba[["bowler_id", arch_col]].drop_duplicates("bowler_id"),
                on="bowler_id",
                how="left",
            )
            m_arch[arch_col] = m_arch[arch_col].fillna("unknown")
            m_arch = m_arch.rename(columns={arch_col: "_bowler_archetype"})

            batter_vs_bowler_arch = (
                m_arch.groupby(["batter_id", "_bowler_archetype"])
                .agg(
                    archetype_dominance=(
                        "dominance_index",
                        lambda s: (
                            np.average(
                                s.values,
                                weights=m_arch.loc[s.index, "balls_faced"].values,
                            )
                            if len(s) > 0
                            else 0.0
                        ),
                    ),
                    archetype_balls=("balls_faced", "sum"),
                    archetype_matchups=("bowler_id", "nunique"),
                )
                .reset_index()
                .rename(columns={"_bowler_archetype": "bowler_archetype"})
            )

            for c in ["archetype_dominance"]:
                if c in batter_vs_bowler_arch.columns:
                    batter_vs_bowler_arch[c] = batter_vs_bowler_arch[c].round(4)

    # ── Bowler vs batter archetype baselines ──
    if batter_archetypes is not None and not batter_archetypes.empty:
        ba2 = batter_archetypes.copy()
        arch_col2 = None
        for candidate in ["archetype", "position_group"]:
            if candidate in ba2.columns:
                arch_col2 = candidate
                break

        if arch_col2 is not None:
            _decat(ba2, ["batter_id", arch_col2])
            m_arch2 = m.merge(
                ba2[["batter_id", arch_col2]].drop_duplicates("batter_id"),
                on="batter_id",
                how="left",
            )
            m_arch2[arch_col2] = m_arch2[arch_col2].fillna("unknown")
            m_arch2 = m_arch2.rename(columns={arch_col2: "_batter_archetype"})

            bowler_vs_batter_arch = (
                m_arch2.groupby(["bowler_id", "_batter_archetype"])
                .agg(
                    archetype_dominance=(
                        "dominance_index",
                        lambda s: (
                            np.average(
                                s.values,
                                weights=m_arch2.loc[s.index, "balls_faced"].values,
                            )
                            if len(s) > 0
                            else 0.0
                        ),
                    ),
                    archetype_balls=("balls_faced", "sum"),
                    archetype_matchups=("batter_id", "nunique"),
                )
                .reset_index()
                .rename(columns={"_batter_archetype": "batter_archetype"})
            )

            # Invert dominance for bowler perspective (negative = bowler wins)
            if "archetype_dominance" in bowler_vs_batter_arch.columns:
                bowler_vs_batter_arch["archetype_dominance"] = bowler_vs_batter_arch[
                    "archetype_dominance"
                ].round(4)

    return {
        "batter_vs_bowler_archetype": batter_vs_bowler_arch,
        "bowler_vs_batter_archetype": bowler_vs_batter_arch,
    }


def apply_bayesian_matchup_shrinkage(
    matchups: pd.DataFrame,
    bowler_archetypes: pd.DataFrame | None = None,
    batter_archetypes: pd.DataFrame | None = None,
    shrinkage_balls: int = _DEFAULT_SHRINKAGE_BALLS,
) -> pd.DataFrame:
    """
    Apply Bayesian shrinkage to matchup dominance indices.

    Per algorithm_update.md §Matchup Modeling:
        "Every delivery is evaluated as a zero-sum transaction. [...] To
        handle situations where a batter and bowler have only faced each
        other for six deliveries, a Bayesian head-to-head random effect
        is applied.  This calculates the True Matchup Quality by shrinking
        the small-sample head-to-head record toward the players' baseline
        performances against similar player archetypes."

    The shrinkage formula (Empirical Bayes):
        λ = k / (n + k)
        bayesian_dominance = (1 − λ) · observed_dominance + λ · prior

    where:
        - n = balls_faced in the specific head-to-head matchup
        - k = shrinkage_balls (configurable, default 30)
        - prior = batter's average dominance vs all bowlers of the same
          archetype (or global average if no archetype data available)

    This ensures that a 6-ball matchup is heavily regressed toward the
    archetype baseline, while a 120-ball matchup is trusted almost entirely.

    Parameters
    ----------
    matchups : pd.DataFrame
        Output of ``compute_matchups()`` or ``_aggregate_matchup()``.
        Must contain ``batter_id``, ``bowler_id``, ``dominance_index``,
        ``balls_faced``.
    bowler_archetypes : pd.DataFrame, optional
        Bowler career data with ``bowler_id`` and ``archetype`` (or
        ``phase_group``).  Used to compute archetype-level priors.
    batter_archetypes : pd.DataFrame, optional
        Batter career data with ``batter_id`` and ``archetype`` (or
        ``position_group``).  Used for bowler-side archetype priors.
    shrinkage_balls : int
        Number of balls at which the observed data and prior receive
        equal weight.  Higher = more conservative shrinkage.

    Returns
    -------
    pd.DataFrame — a copy of ``matchups`` with additional columns:
        ``archetype_prior`` : float — the prior dominance from archetype baseline
        ``bayesian_dominance`` : float — shrunk dominance estimate
        ``matchup_confidence`` : float — weight on observed data (0 → 1)
        ``shrinkage_applied`` : float — amount of shrinkage (0 → 1)
    """
    if matchups.empty:
        return matchups.copy()

    result = matchups.copy()
    _decat(result, ["batter_id", "bowler_id"])

    n = result["balls_faced"].fillna(0).astype(float)

    # ── Compute archetype priors ──
    baselines = compute_archetype_baselines(
        matchups,
        bowler_archetypes=bowler_archetypes,
        batter_archetypes=batter_archetypes,
    )

    batter_vs_arch = baselines["batter_vs_bowler_archetype"]

    # ── Merge archetype prior onto each matchup ──
    if (
        not batter_vs_arch.empty
        and bowler_archetypes is not None
        and not bowler_archetypes.empty
    ):
        ba = bowler_archetypes.copy()
        arch_col = None
        for candidate in ["archetype", "phase_group"]:
            if candidate in ba.columns:
                arch_col = candidate
                break

        if arch_col is not None:
            _decat(ba, ["bowler_id", arch_col])
            # Map each bowler to their archetype
            result = result.merge(
                ba[["bowler_id", arch_col]]
                .drop_duplicates("bowler_id")
                .rename(columns={arch_col: "_bowler_archetype"}),
                on="bowler_id",
                how="left",
            )
            result["_bowler_archetype"] = result["_bowler_archetype"].fillna("unknown")

            # Merge the batter-specific archetype prior
            result = result.merge(
                batter_vs_arch[
                    ["batter_id", "bowler_archetype", "archetype_dominance"]
                ].rename(
                    columns={
                        "bowler_archetype": "_bowler_archetype",
                        "archetype_dominance": "archetype_prior",
                    }
                ),
                on=["batter_id", "_bowler_archetype"],
                how="left",
            )

            result.drop(columns=["_bowler_archetype"], inplace=True, errors="ignore")
        else:
            result["archetype_prior"] = np.nan
    else:
        result["archetype_prior"] = np.nan

    # ── Fill missing priors with global batter average dominance ──
    # For each batter, their global average dominance across all matchups
    # serves as a fallback prior when archetype data is unavailable.
    global_batter_prior = (
        result.groupby("batter_id")
        .apply(
            lambda g: (
                np.average(
                    g["dominance_index"].values,
                    weights=g["balls_faced"].values,
                )
                if len(g) > 0
                else 0.0
            ),
            include_groups=False,
        )
        .rename("_global_prior")
    )

    result = result.merge(global_batter_prior, on="batter_id", how="left")
    result["archetype_prior"] = result["archetype_prior"].fillna(
        result["_global_prior"]
    )
    result["archetype_prior"] = result["archetype_prior"].fillna(0.0)
    result.drop(columns=["_global_prior"], inplace=True, errors="ignore")

    # ── Apply Empirical Bayes shrinkage ──
    k = float(max(shrinkage_balls, 1))
    lam = k / (n + k)  # shrinkage factor: 1.0 for n=0, 0.5 for n=k, →0 for large n

    observed = result["dominance_index"].fillna(0.0)
    prior = result["archetype_prior"].fillna(0.0)

    result["bayesian_dominance"] = ((1.0 - lam) * observed + lam * prior).round(4)
    result["shrinkage_applied"] = lam.round(4)

    # Update matchup_confidence if not already present
    if "matchup_confidence" not in result.columns:
        result["matchup_confidence"] = (n / (n + k)).round(4)

    return result


def project_unseen_matchup(
    batter_id: str,
    bowler_id: str,
    batter_vs_bowler_arch: pd.DataFrame,
    bowler_archetypes: pd.DataFrame,
    global_dominance: float = 0.0,
) -> dict[str, float | str]:
    """
    Project a matchup value for a batter-bowler pair that has never occurred.

    Per algorithm_update.md:
        "If a batter historically struggles against all right-arm wrist
        spinners, their sparse data against a specific debutant wrist
        spinner is mathematically dragged toward that broader archetype
        weakness.  This allows the platform to generate projected matchup
        values and simulate encounters that have never historically
        occurred."

    When the head-to-head sample is exactly zero, the projection is
    the batter's career dominance against the bowler's archetype.  If
    archetype data is also unavailable, falls back to the global mean.

    Parameters
    ----------
    batter_id : str
        The batter's ID.
    bowler_id : str
        The bowler's ID.
    batter_vs_bowler_arch : pd.DataFrame
        Output of ``compute_archetype_baselines()["batter_vs_bowler_archetype"]``.
    bowler_archetypes : pd.DataFrame
        Must contain ``bowler_id`` and ``archetype`` (or ``phase_group``).
    global_dominance : float
        Fallback dominance index when no archetype data is available.

    Returns
    -------
    dict with keys:
        ``projected_dominance`` : float — the projected matchup dominance
        ``confidence`` : float — always 0.0 (no direct observations)
        ``source`` : str — "archetype" or "global" indicating projection basis
    """
    if bowler_archetypes is None or bowler_archetypes.empty:
        return {
            "projected_dominance": global_dominance,
            "confidence": 0.0,
            "source": "global",
        }

    ba = bowler_archetypes.copy()
    _decat(ba, ["bowler_id"])

    arch_col = None
    for candidate in ["archetype", "phase_group"]:
        if candidate in ba.columns:
            arch_col = candidate
            break

    if arch_col is None:
        return {
            "projected_dominance": global_dominance,
            "confidence": 0.0,
            "source": "global",
        }

    bowler_row = ba[ba["bowler_id"] == bowler_id]
    if bowler_row.empty:
        return {
            "projected_dominance": global_dominance,
            "confidence": 0.0,
            "source": "global",
        }

    bowler_arch = str(bowler_row.iloc[0][arch_col])

    if batter_vs_bowler_arch.empty:
        return {
            "projected_dominance": global_dominance,
            "confidence": 0.0,
            "source": "global",
        }

    _decat(batter_vs_bowler_arch, ["batter_id", "bowler_archetype"])
    prior_row = batter_vs_bowler_arch[
        (batter_vs_bowler_arch["batter_id"] == batter_id)
        & (batter_vs_bowler_arch["bowler_archetype"] == bowler_arch)
    ]

    if prior_row.empty:
        return {
            "projected_dominance": global_dominance,
            "confidence": 0.0,
            "source": "global",
        }

    projected = float(prior_row.iloc[0]["archetype_dominance"])
    return {
        "projected_dominance": round(projected, 4),
        "confidence": 0.0,
        "source": "archetype",
    }
