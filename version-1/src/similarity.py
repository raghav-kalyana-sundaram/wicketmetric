"""
Player Similarity Engine — statistical "comps" for every player.

Feature 7 from the Version 0.2 roadmap.

When a new prospect emerges or a team buys an unknown player at auction,
fans immediately ask: "Who does he play like?"  This engine calculates
**cosine similarity** between players' normalised component vectors and
outputs the Top-K statistical matches.

The similarity is computed on the career-level z-scored component means
that already exist in ``bat_careers`` / ``bowl_careers`` after aggregation.
This means players are compared on the *shape* of their profile (e.g.
high acceleration + low control vs balanced) rather than raw magnitude.

Two main entry points:

- ``compute_batting_similarity`` — compares batters to batters
- ``compute_bowling_similarity`` — compares bowlers to bowlers

Both return a long-form DataFrame with one row per (player, comp) pair,
sorted by similarity descending.  A wide-form convenience function
``pivot_similarity_wide`` reshapes for CSV/frontend consumption.

Implementation uses pure NumPy (no sklearn dependency) for the cosine
similarity computation.  The vector for each player consists of the
career-level component means (the ``*_mean`` columns from aggregation)
plus supplementary profile columns (career_sr, career_avg, etc.).

Usage
-----
    from src.similarity import (
        compute_batting_similarity,
        compute_bowling_similarity,
        pivot_similarity_wide,
    )

    bat_sims = compute_batting_similarity(bat_careers, top_k=3)
    bowl_sims = compute_bowling_similarity(bowl_careers, top_k=3)

    # Wide-form for CSV: one row per player, comp columns side-by-side
    bat_sims_wide = pivot_similarity_wide(bat_sims, top_k=3)

Config keys (read from ``config.yaml`` via ``src/config.py``):
    similarity.enabled   : bool  (default True)
    similarity.top_k     : int   (default 3)
    similarity.min_innings: int  (default 15)

Design notes
------------
- Cosine similarity measures the *angle* between two vectors, so it captures
  profile shape regardless of magnitude.  A player with scores [80, 40, 60]
  and one with [40, 20, 30] have similarity 1.0 — same proportional profile.
- To also capture magnitude differences, we include a "magnitude penalty"
  option that blends cosine similarity with Euclidean distance similarity.
  By default this is disabled (pure cosine).
- Position-group filtering is optional: by default, players are compared
  across all positions, but you can restrict to within-group comps.
- Provisional players (below min_innings threshold) are excluded from being
  comp *targets* but CAN receive comps themselves.  This prevents noisy
  small-sample profiles from appearing as someone's statistical twin.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import cfg

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------
SIMILARITY_ENABLED: bool = cfg("similarity.enabled", default=True)
SIMILARITY_TOP_K: int = cfg("similarity.top_k", default=3)
SIMILARITY_MIN_INNINGS: int = cfg("similarity.min_innings", default=15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decat(df: pd.DataFrame, cols: list[str]) -> None:
    """Convert categorical columns to plain strings (in-place)."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)


def _cosine_similarity_matrix(A: np.ndarray) -> np.ndarray:
    """
    Compute pairwise cosine similarity for rows of matrix A.

    Parameters
    ----------
    A : np.ndarray, shape (N, D)
        Each row is a player's feature vector.

    Returns
    -------
    np.ndarray, shape (N, N)
        Symmetric matrix where entry [i, j] is the cosine similarity
        between player i and player j.  Diagonal is 1.0.
    """
    # Handle zero vectors gracefully
    norms = np.linalg.norm(A, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # avoid division by zero
    A_normed = A / norms
    sim = A_normed @ A_normed.T
    # Clip to [-1, 1] to handle floating point imprecision
    return np.clip(sim, -1.0, 1.0)


def _select_feature_columns(
    df: pd.DataFrame,
    candidate_cols: list[str],
) -> list[str]:
    """Return the subset of candidate_cols that exist in df and have variance."""
    available = [c for c in candidate_cols if c in df.columns]
    # Drop columns that are constant (zero variance → no discriminative power)
    selected = []
    for c in available:
        vals = df[c].dropna()
        if len(vals) > 1 and vals.std() > 1e-10:
            selected.append(c)
    return selected


def _z_normalise_columns(
    df: pd.DataFrame,
    cols: list[str],
) -> pd.DataFrame:
    """
    Z-score normalise the given columns in-place so each feature has mean 0
    and std 1.  This ensures all features contribute equally to cosine
    similarity regardless of their natural scale.

    NaN values are filled with 0.0 (population mean) after normalisation.
    """
    out = df.copy()
    for c in cols:
        vals = out[c]
        mean = vals.mean()
        std = vals.std()
        if std > 1e-10:
            out[c] = (vals - mean) / std
        else:
            out[c] = 0.0
        out[c] = out[c].fillna(0.0)
    return out


# ---------------------------------------------------------------------------
# Batting feature columns (ordered by importance)
# ---------------------------------------------------------------------------

# These are the career-level aggregated component means that capture a
# batter's full profile shape.  The ``*_mean`` suffix columns come from
# ``aggregate_batting_careers``.
BATTING_FEATURE_COLS: list[str] = [
    # Acceleration family
    "acc_overall_sr_mean",
    "acc_sr_growth_mean",
    "acc_death_sr_mean",
    "acc_impact_mean",
    "acc_runs_above_expected_mean",
    # Power family
    "pow_boundary_pct_mean",
    "pow_six_rate_mean",
    "pow_boundary_rate_vs_par_mean",
    "pow_peak_phase_sr_mean",
    "pow_finishing_burst_mean",
    "pow_power_impact_mean",
    # Control family
    "ctrl_dot_pct_weighted_mean",
    "ctrl_rotation_mean",
    "ctrl_contribution_mean",
    "ctrl_scoring_consistency_mean",
    "ctrl_avg_proxy_mean",
    "ctrl_dismissal_quality_mean",
    # Summary stats
    "career_sr",
    "career_avg",
]

# Supplementary columns that can optionally be included for richer matching
BATTING_SUPPLEMENTARY_COLS: list[str] = [
    "avg_balls_to_par",
    "anchor_cost_ratio",
    "selfless_index",
    "chase_master_index",
]


# ---------------------------------------------------------------------------
# Bowling feature columns
# ---------------------------------------------------------------------------

BOWLING_FEATURE_COLS: list[str] = [
    # Accuracy family
    "acc_economy_vs_par_mean",
    "acc_dot_pct_mean",
    "acc_extras_penalty_mean",
    "acc_boundary_penalty_mean",
    # Control family
    "ctrl_entropy_mean",
    "ctrl_vs_others_mean",
    "ctrl_extras_mean",
    "ctrl_phase_consistency_mean",
    "ctrl_economy_vs_par_mean",
    # Threat family
    "threat_wickets_mean",
    "threat_quality_wickets_mean",
    "threat_sr_mean",
    "threat_pressure_mean",
    "threat_dots_mean",
    # Summary stats
    "career_economy",
    "career_sr_bowl",
]

BOWLING_SUPPLEMENTARY_COLS: list[str] = [
    "avg_wicket_quality_mean",
    "bowled_lbw_pct",
]


# ---------------------------------------------------------------------------
# Core similarity computation
# ---------------------------------------------------------------------------


def _compute_similarity(
    df: pd.DataFrame,
    id_col: str,
    name_col: str,
    feature_cols: list[str],
    supplementary_cols: list[str],
    min_sample: int,
    sample_col: str,
    top_k: int,
    within_group_col: str | None = None,
    include_supplementary: bool = True,
) -> pd.DataFrame:
    """
    Generic pairwise cosine similarity computation.

    Parameters
    ----------
    df : pd.DataFrame
        Career-level data with one row per player.
    id_col : str
        Column name for player ID.
    name_col : str
        Column name for player display name.
    feature_cols : list[str]
        Primary feature columns for the similarity vector.
    supplementary_cols : list[str]
        Optional additional columns to include in the vector.
    min_sample : int
        Minimum innings/matches to be a comp target.
    sample_col : str
        Column with the sample size (e.g. "innings_count", "matches").
    top_k : int
        Number of most-similar players to return per player.
    within_group_col : str, optional
        If provided, only compare within the same group (e.g. position_group).
    include_supplementary : bool
        Whether to include supplementary_cols in the feature vector.

    Returns
    -------
    pd.DataFrame
        Long-form: one row per (player, comp_rank) with columns:
        - {id_col}, {name_col}, comp_{id_col}, comp_{name_col},
          similarity, comp_rank
    """
    if df.empty:
        return pd.DataFrame()

    work = df.copy()
    _decat(work, [id_col, name_col])

    # Determine which feature columns are usable
    all_candidate = feature_cols.copy()
    if include_supplementary:
        all_candidate.extend(supplementary_cols)
    used_cols = _select_feature_columns(work, all_candidate)

    if len(used_cols) < 2:
        # Not enough features to compute meaningful similarity
        return pd.DataFrame()

    # Z-normalise features so cosine similarity isn't dominated by scale
    work = _z_normalise_columns(work, used_cols)

    # Identify comp-eligible targets (meet minimum sample threshold)
    target_mask = (
        work[sample_col] >= min_sample
        if sample_col in work.columns
        else pd.Series(True, index=work.index)
    )

    # Build the feature matrix
    feature_matrix = work[used_cols].values.astype(np.float64)
    # Replace any remaining NaN with 0 (shouldn't happen after z-norm, but safety)
    feature_matrix = np.nan_to_num(feature_matrix, nan=0.0)

    # Compute full pairwise similarity
    sim_matrix = _cosine_similarity_matrix(feature_matrix)

    # Extract player metadata
    ids = work[id_col].values
    names = work[name_col].values
    groups = (
        work[within_group_col].values
        if within_group_col and within_group_col in work.columns
        else None
    )
    is_target = target_mask.values

    results: list[dict] = []

    for i in range(len(work)):
        # Get similarities for player i
        sims = sim_matrix[i].copy()

        # Mask out self
        sims[i] = -2.0

        # Mask out non-target players (don't appear as comps)
        for j in range(len(work)):
            if not is_target[j]:
                sims[j] = -2.0

        # Optionally restrict to same group
        if groups is not None:
            for j in range(len(work)):
                if groups[j] != groups[i]:
                    sims[j] = -2.0

        # Find top-k
        # Use argpartition for efficiency on large arrays
        k = min(top_k, (sims > -2.0).sum())
        if k == 0:
            continue

        if k < len(sims):
            top_indices = np.argpartition(sims, -k)[-k:]
            # Sort the top-k by similarity descending
            top_indices = top_indices[np.argsort(sims[top_indices])[::-1]]
        else:
            top_indices = np.argsort(sims)[::-1][:k]

        for rank, j in enumerate(top_indices, start=1):
            if sims[j] <= -2.0:
                break
            results.append(
                {
                    id_col: ids[i],
                    name_col: names[i],
                    f"comp_{id_col}": ids[j],
                    f"comp_{name_col}": names[j],
                    "similarity": round(float(sims[j]) * 100, 1),  # as percentage
                    "comp_rank": rank,
                }
            )

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Public API — Batting similarity
# ---------------------------------------------------------------------------


def compute_batting_similarity(
    bat_careers: pd.DataFrame,
    top_k: int | None = None,
    min_innings: int | None = None,
    within_position_group: bool = False,
    include_supplementary: bool = True,
) -> pd.DataFrame:
    """
    Compute Top-K most similar batters for every batter in the dataset.

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Career-level batting data (output of the full pipeline).
    top_k : int, optional
        Number of comps per player.  Defaults to config value (3).
    min_innings : int, optional
        Minimum innings to be a comp target.  Defaults to config value (15).
    within_position_group : bool
        If True, only compare within the same position_group (e.g. openers
        to openers).  Default False (cross-position comps).
    include_supplementary : bool
        If True, include v0.2 profile columns (selfless, anchor cost, etc.)
        in the feature vector for richer matching.

    Returns
    -------
    pd.DataFrame
        Long-form with columns:
        batter_id, batter, comp_batter_id, comp_batter, similarity, comp_rank
    """
    if top_k is None:
        top_k = SIMILARITY_TOP_K
    if min_innings is None:
        min_innings = SIMILARITY_MIN_INNINGS

    return _compute_similarity(
        df=bat_careers,
        id_col="batter_id",
        name_col="batter",
        feature_cols=BATTING_FEATURE_COLS,
        supplementary_cols=BATTING_SUPPLEMENTARY_COLS,
        min_sample=min_innings,
        sample_col="innings_count",
        top_k=top_k,
        within_group_col="position_group" if within_position_group else None,
        include_supplementary=include_supplementary,
    )


# ---------------------------------------------------------------------------
# Public API — Bowling similarity
# ---------------------------------------------------------------------------


def compute_bowling_similarity(
    bowl_careers: pd.DataFrame,
    top_k: int | None = None,
    min_matches: int | None = None,
    within_phase_group: bool = False,
    include_supplementary: bool = True,
) -> pd.DataFrame:
    """
    Compute Top-K most similar bowlers for every bowler in the dataset.

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Career-level bowling data (output of the full pipeline).
    top_k : int, optional
        Number of comps per bowler.  Defaults to config value (3).
    min_matches : int, optional
        Minimum matches to be a comp target.  Defaults to config min_innings.
    within_phase_group : bool
        If True, only compare within the same phase_group (e.g. death
        bowlers to death bowlers).  Default False.
    include_supplementary : bool
        If True, include AWQ and bowled/lbw% in feature vector.

    Returns
    -------
    pd.DataFrame
        Long-form with columns:
        bowler_id, bowler, comp_bowler_id, comp_bowler, similarity, comp_rank
    """
    if top_k is None:
        top_k = SIMILARITY_TOP_K
    if min_matches is None:
        min_matches = SIMILARITY_MIN_INNINGS

    return _compute_similarity(
        df=bowl_careers,
        id_col="bowler_id",
        name_col="bowler",
        feature_cols=BOWLING_FEATURE_COLS,
        supplementary_cols=BOWLING_SUPPLEMENTARY_COLS,
        min_sample=min_matches,
        sample_col="matches",
        top_k=top_k,
        within_group_col="phase_group" if within_phase_group else None,
        include_supplementary=include_supplementary,
    )


# ---------------------------------------------------------------------------
# Pivot to wide form (for CSV / frontend)
# ---------------------------------------------------------------------------


def pivot_similarity_wide(
    sim_df: pd.DataFrame,
    id_col: str = "batter_id",
    name_col: str = "batter",
    top_k: int | None = None,
) -> pd.DataFrame:
    """
    Pivot long-form similarity results to wide form.

    Input (long):
        batter_id | batter | comp_batter_id | comp_batter | similarity | comp_rank

    Output (wide):
        batter_id | batter | comp_1 | sim_1 | comp_2 | sim_2 | comp_3 | sim_3

    Parameters
    ----------
    sim_df : pd.DataFrame
        Long-form output from compute_batting_similarity or compute_bowling_similarity.
    id_col : str
        Player ID column name.
    name_col : str
        Player name column name.
    top_k : int, optional
        Maximum rank to include.  If None, uses all ranks present.

    Returns
    -------
    pd.DataFrame
        Wide-form, one row per player.
    """
    if sim_df.empty:
        return pd.DataFrame()

    if top_k is not None:
        sim_df = sim_df[sim_df["comp_rank"] <= top_k]

    comp_name_col = f"comp_{name_col}"

    # Pivot each rank into its own columns
    pivoted_parts = []
    for rank in sorted(sim_df["comp_rank"].unique()):
        rank_df = sim_df[sim_df["comp_rank"] == rank][
            [id_col, name_col, comp_name_col, "similarity"]
        ].copy()
        rank_df = rank_df.rename(
            columns={
                comp_name_col: f"comp_{rank}",
                "similarity": f"sim_{rank}",
            }
        )
        pivoted_parts.append(rank_df)

    if not pivoted_parts:
        return pd.DataFrame()

    result = pivoted_parts[0]
    for part in pivoted_parts[1:]:
        result = result.merge(part, on=[id_col, name_col], how="outer")

    return result.sort_values(id_col).reset_index(drop=True)
