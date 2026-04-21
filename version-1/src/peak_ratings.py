"""
Peak vs Current Ratings — dual rating sets for historical comparison.

Feature 5 from the Version 0.2 roadmap.

Produces two distinct rating perspectives for every player:

1. **Current Rating** — the existing recency-weighted rating (already computed
   by the main pipeline).  Recent form dominates.
2. **Peak Rating** — either a recency-free career aggregate *or* a sliding-
   window best-ever period.  This tells you how dominant a player was at
   their absolute best.

This allows fans to compare "Peak AB de Villiers" against "Current Suryakumar
Yadav" — a retired player's peak tells you how dominant they were even though
their "current" rating naturally decays.

Two approaches are provided:

- ``compute_peak_ratings`` — **Simple (Approach 1)**: re-aggregates career
  stats WITHOUT recency weighting.  Fast, produces stable "all-time" scores.
- ``compute_sliding_peak`` — **Sliding Window (Approach 2)**: finds each
  player's best N-day window by iterating over date-sorted innings and
  computing a rolling composite.  More expensive but gives a true "peak."

Usage
-----
    from src.peak_ratings import (
        compute_peak_ratings,
        compute_peak_ratings_bowl,
        compute_sliding_peak,
        compute_sliding_peak_bowl,
    )

    # Simple approach — recency-free career aggregate
    peak_bat = compute_peak_ratings(bat_components)
    peak_bowl = compute_peak_ratings_bowl(bowl_components)

    # Sliding window — true 2-year peak
    peak_window_bat = compute_sliding_peak(bat_components, window_days=730)
    peak_window_bowl = compute_sliding_peak_bowl(bowl_components, window_days=730)

Design notes
------------
- The simple approach works by dividing out the ``recency_weight`` from the
  combined ``opp_quality_weight``, then re-aggregating.  This preserves the
  opposition-quality and team-quality adjustments while removing time decay.
- The sliding window approach computes a quick composite from the three main
  component families (acceleration/power/control for batting, accuracy/
  control/threat for bowling) within each candidate window and tracks the
  maximum.
- Both approaches respect a minimum innings/spells threshold to avoid noisy
  peaks from tiny samples.
- Peak columns are prefixed with ``peak_`` to distinguish from current ratings.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import cfg

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PEAK_MIN_INNINGS_BAT: int = cfg("pipeline.min_bat_innings", default=10)
PEAK_MIN_SPELLS_BOWL: int = 10  # Analogous threshold for bowlers
PEAK_WINDOW_DAYS: int = 730  # 2-year default sliding window
PEAK_WINDOW_MIN_INNINGS: int = 5  # Minimum innings inside a sliding window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decat(df: pd.DataFrame, cols: list[str]) -> None:
    """Convert categorical columns to plain strings (in-place)."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)


def _safe_wmean(values: pd.Series, weights: pd.Series) -> float:
    """Weighted mean ignoring NaN in values."""
    mask = values.notna()
    v = values[mask]
    w = weights[mask]
    if len(v) == 0 or w.sum() == 0:
        return np.nan
    return float((v * w).sum() / w.sum())


def _safe_mean(series: pd.Series) -> float:
    """Plain mean ignoring NaN; NaN if all missing."""
    vals = series.dropna()
    return float(vals.mean()) if len(vals) > 0 else np.nan


# ---------------------------------------------------------------------------
# Approach 1 — Simple Peak (recency-free full-career aggregate)
# ---------------------------------------------------------------------------


def compute_peak_ratings(
    bat_components: pd.DataFrame,
    min_innings: int | None = None,
) -> pd.DataFrame:
    """
    Re-aggregate career batting stats WITHOUT recency weighting to produce
    'peak' (all-time) raw component means alongside the recency-weighted
    'current' ratings.

    The recency weight is divided out of the combined ``opp_quality_weight``
    so that opposition-quality and team-quality adjustments are preserved,
    but time decay is removed.

    Parameters
    ----------
    bat_components : pd.DataFrame
        Per-innings component data (output of ``compute_batting_components``).
    min_innings : int, optional
        Minimum innings to produce peak ratings.  Defaults to pipeline config.

    Returns
    -------
    pd.DataFrame
        One row per (batter_id, batter) with columns:
        - batter_id, batter
        - peak_acc_overall_sr, peak_acc_impact, peak_acc_xr
        - peak_pow_boundary_pct, peak_pow_six_rate, peak_pow_finishing_burst, peak_pow_power_impact
        - peak_ctrl_consistency, peak_ctrl_dot_control
        - peak_composite_batting
        - peak_innings_count
    """
    if min_innings is None:
        min_innings = PEAK_MIN_INNINGS_BAT

    if bat_components.empty:
        return pd.DataFrame()

    bc = bat_components.copy()
    _decat(bc, ["batter_id", "batter"])

    # ── Remove recency decay from weights ──
    # opp_quality_weight = base_opp_weight × recency_weight (in the pipeline)
    # To get recency-free weight: divide out recency_weight.
    if "recency_weight" in bc.columns and "opp_quality_weight" in bc.columns:
        recency = bc["recency_weight"].clip(lower=0.001)
        bc["peak_weight"] = bc["opp_quality_weight"] / recency
    elif "opp_quality_weight" in bc.columns:
        # No recency column — weights are already recency-free
        bc["peak_weight"] = bc["opp_quality_weight"]
    else:
        bc["peak_weight"] = 1.0

    grp = bc.groupby(["batter_id", "batter"], sort=False)

    records: list[dict] = []

    for (batter_id, batter_name), player_df in grp:
        n = len(player_df)
        if n < min_innings:
            continue

        w = player_df["peak_weight"]

        rec: dict = {
            "batter_id": batter_id,
            "batter": batter_name,
            "peak_innings_count": n,
        }

        # Acceleration
        rec["peak_acc_overall_sr"] = _safe_wmean(player_df["acc_overall_sr"], w)
        if "acc_impact" in player_df.columns:
            rec["peak_acc_impact"] = _safe_wmean(player_df["acc_impact"], w)
        else:
            rec["peak_acc_impact"] = np.nan
        if "acc_runs_above_expected" in player_df.columns:
            rec["peak_acc_xr"] = _safe_wmean(player_df["acc_runs_above_expected"], w)
        else:
            rec["peak_acc_xr"] = np.nan

        # Power
        if "pow_boundary_pct" in player_df.columns:
            rec["peak_pow_boundary_pct"] = _safe_wmean(player_df["pow_boundary_pct"], w)
        else:
            rec["peak_pow_boundary_pct"] = np.nan
        if "pow_six_rate" in player_df.columns:
            rec["peak_pow_six_rate"] = _safe_wmean(player_df["pow_six_rate"], w)
        else:
            rec["peak_pow_six_rate"] = np.nan
        if "pow_finishing_burst" in player_df.columns:
            rec["peak_pow_finishing_burst"] = _safe_wmean(
                player_df["pow_finishing_burst"], w
            )
        else:
            rec["peak_pow_finishing_burst"] = np.nan
        if "pow_power_impact" in player_df.columns:
            rec["peak_pow_power_impact"] = _safe_wmean(player_df["pow_power_impact"], w)
        else:
            rec["peak_pow_power_impact"] = np.nan
        if "pow_peak_phase_sr" in player_df.columns:
            rec["peak_pow_peak_phase_sr"] = _safe_wmean(
                player_df["pow_peak_phase_sr"], w
            )
        else:
            rec["peak_pow_peak_phase_sr"] = np.nan

        # Control
        if "ctrl_scoring_consistency" in player_df.columns:
            rec["peak_ctrl_consistency"] = _safe_wmean(
                player_df["ctrl_scoring_consistency"], w
            )
        else:
            rec["peak_ctrl_consistency"] = np.nan
        if "ctrl_dot_pct_weighted" in player_df.columns:
            rec["peak_ctrl_dot_control"] = _safe_wmean(
                player_df["ctrl_dot_pct_weighted"], w
            )
        else:
            rec["peak_ctrl_dot_control"] = np.nan
        if "ctrl_rotation" in player_df.columns:
            rec["peak_ctrl_rotation"] = _safe_wmean(player_df["ctrl_rotation"], w)
        else:
            rec["peak_ctrl_rotation"] = np.nan

        # Composite: simple mean of the three family means
        acc_parts = [
            rec["peak_acc_overall_sr"],
            rec.get("peak_acc_impact", np.nan),
        ]
        pow_parts = [
            rec.get("peak_pow_boundary_pct", np.nan),
            rec.get("peak_pow_peak_phase_sr", np.nan),
        ]
        ctrl_parts = [
            rec.get("peak_ctrl_consistency", np.nan),
            rec.get("peak_ctrl_dot_control", np.nan),
        ]

        def _family_mean(parts: list) -> float:
            valid = [v for v in parts if v is not None and not np.isnan(v)]
            return float(np.mean(valid)) if valid else np.nan

        acc_mean = _family_mean(acc_parts)
        pow_mean = _family_mean(pow_parts)
        ctrl_mean = _family_mean(ctrl_parts)

        composite_parts = [acc_mean, pow_mean, ctrl_mean]
        valid_composite = [v for v in composite_parts if not np.isnan(v)]
        rec["peak_composite_batting"] = (
            float(np.mean(valid_composite)) if valid_composite else np.nan
        )

        records.append(rec)

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


def compute_peak_ratings_bowl(
    bowl_components: pd.DataFrame,
    min_spells: int | None = None,
) -> pd.DataFrame:
    """
    Re-aggregate career bowling stats WITHOUT recency weighting.

    Parameters
    ----------
    bowl_components : pd.DataFrame
        Per-spell component data (output of ``compute_bowling_components``).
    min_spells : int, optional
        Minimum spells to produce peak ratings.

    Returns
    -------
    pd.DataFrame
        One row per (bowler_id, bowler) with peak_ prefixed columns.
    """
    if min_spells is None:
        min_spells = PEAK_MIN_SPELLS_BOWL

    if bowl_components.empty:
        return pd.DataFrame()

    bc = bowl_components.copy()
    _decat(bc, ["bowler_id", "bowler"])

    # Remove recency decay
    if "recency_weight" in bc.columns and "spell_weight" in bc.columns:
        recency = bc["recency_weight"].clip(lower=0.001)
        bc["peak_weight"] = bc["spell_weight"] / recency
    elif "spell_weight" in bc.columns:
        bc["peak_weight"] = bc["spell_weight"]
    else:
        bc["peak_weight"] = 1.0

    grp = bc.groupby(["bowler_id", "bowler"], sort=False)

    records: list[dict] = []

    for (bowler_id, bowler_name), player_df in grp:
        n = len(player_df)
        if n < min_spells:
            continue

        w = player_df["peak_weight"]

        rec: dict = {
            "bowler_id": bowler_id,
            "bowler": bowler_name,
            "peak_spells_count": n,
        }

        # Accuracy
        if "acc_economy_vs_par" in player_df.columns:
            rec["peak_acc_economy_vs_par"] = _safe_wmean(
                player_df["acc_economy_vs_par"], w
            )
        else:
            rec["peak_acc_economy_vs_par"] = np.nan
        if "acc_dot_pct" in player_df.columns:
            rec["peak_acc_dot_pct"] = _safe_wmean(player_df["acc_dot_pct"], w)
        else:
            rec["peak_acc_dot_pct"] = np.nan

        # Control
        if "ctrl_vs_others" in player_df.columns:
            rec["peak_ctrl_vs_others"] = _safe_wmean(player_df["ctrl_vs_others"], w)
        else:
            rec["peak_ctrl_vs_others"] = np.nan
        if "ctrl_entropy" in player_df.columns:
            rec["peak_ctrl_entropy"] = _safe_wmean(player_df["ctrl_entropy"], w)
        else:
            rec["peak_ctrl_entropy"] = np.nan

        # Threat
        if "threat_quality_wickets" in player_df.columns:
            rec["peak_threat_quality_wickets"] = _safe_wmean(
                player_df["threat_quality_wickets"], w
            )
        else:
            rec["peak_threat_quality_wickets"] = np.nan
        if "threat_pressure" in player_df.columns:
            rec["peak_threat_pressure"] = _safe_wmean(player_df["threat_pressure"], w)
        else:
            rec["peak_threat_pressure"] = np.nan

        # Composite
        acc_val = rec.get("peak_acc_economy_vs_par", np.nan)
        ctrl_val = rec.get("peak_ctrl_vs_others", np.nan)
        threat_val = rec.get("peak_threat_quality_wickets", np.nan)
        parts = [
            v
            for v in [acc_val, ctrl_val, threat_val]
            if v is not None and not np.isnan(v)
        ]
        rec["peak_composite_bowling"] = float(np.mean(parts)) if parts else np.nan

        records.append(rec)

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Approach 2 — Sliding Window Peak (true best N-day period)
# ---------------------------------------------------------------------------


def _compute_window_composite_bat(window: pd.DataFrame) -> float:
    """
    Quick composite score for a batting window.

    Uses the mean of key component columns across the window.  All components
    are already oriented so higher = better, so the mean is a reasonable
    single-number summary.
    """
    parts: list[float] = []

    for col in [
        "acc_overall_sr",
        "acc_impact",
        "pow_boundary_pct",
        "pow_peak_phase_sr",
        "ctrl_scoring_consistency",
        "ctrl_dot_pct_weighted",
    ]:
        if col in window.columns:
            val = window[col].dropna()
            if len(val) > 0:
                parts.append(float(val.mean()))

    return float(np.mean(parts)) if parts else np.nan


def _compute_window_composite_bowl(window: pd.DataFrame) -> float:
    """Quick composite score for a bowling window."""
    parts: list[float] = []

    for col in [
        "acc_economy_vs_par",
        "acc_dot_pct",
        "ctrl_vs_others",
        "ctrl_entropy",
        "threat_quality_wickets",
        "threat_pressure",
    ]:
        if col in window.columns:
            val = window[col].dropna()
            if len(val) > 0:
                parts.append(float(val.mean()))

    return float(np.mean(parts)) if parts else np.nan


def compute_sliding_peak(
    bat_components: pd.DataFrame,
    window_days: int | None = None,
    min_window_innings: int | None = None,
    min_career_innings: int | None = None,
) -> pd.DataFrame:
    """
    Find each batter's best sliding window of ``window_days`` duration.

    For each player, iterates over date-sorted innings.  At each position,
    considers all innings within [date − window_days, date] and computes a
    composite.  The window that produces the highest composite is recorded.

    Parameters
    ----------
    bat_components : pd.DataFrame
        Per-innings component data.
    window_days : int, optional
        Window size in days.  Default 730 (2 years).
    min_window_innings : int, optional
        Minimum innings inside a window for it to be valid.  Default 5.
    min_career_innings : int, optional
        Skip players with fewer total career innings.  Default 10.

    Returns
    -------
    pd.DataFrame
        One row per player with:
        - batter_id, batter
        - peak_window_start, peak_window_end
        - peak_window_innings
        - peak_window_composite
        - peak_window_avg_runs, peak_window_avg_sr
    """
    if window_days is None:
        window_days = PEAK_WINDOW_DAYS
    if min_window_innings is None:
        min_window_innings = PEAK_WINDOW_MIN_INNINGS
    if min_career_innings is None:
        min_career_innings = PEAK_MIN_INNINGS_BAT

    if bat_components.empty:
        return pd.DataFrame()

    bc = bat_components.copy()
    _decat(bc, ["batter_id", "batter"])

    # Ensure date is datetime
    bc["date"] = pd.to_datetime(bc["date"], errors="coerce")
    bc = bc.dropna(subset=["date"])
    bc = bc.sort_values(["batter_id", "date"]).reset_index(drop=True)

    results: list[dict] = []
    window_td = pd.Timedelta(days=window_days)

    for batter_id, player_df in bc.groupby("batter_id", sort=False):
        player_df = player_df.reset_index(drop=True)
        n = len(player_df)
        if n < min_career_innings:
            continue

        batter_name = player_df.iloc[-1]["batter"]
        dates = player_df["date"]

        best_composite = -np.inf
        best_window_end_idx: int | None = None
        best_window_start_idx: int | None = None

        # Use a sliding window with two pointers for efficiency
        left = 0
        for right in range(n):
            end_date = dates.iloc[right]
            start_date = end_date - window_td

            # Advance left pointer past the window boundary
            while left < right and dates.iloc[left] < start_date:
                left += 1

            window_size = right - left + 1
            if window_size < min_window_innings:
                continue

            window = player_df.iloc[left : right + 1]
            composite = _compute_window_composite_bat(window)

            if not np.isnan(composite) and composite > best_composite:
                best_composite = composite
                best_window_end_idx = right
                best_window_start_idx = left

            # Reset left for the next iteration — we need to re-scan because
            # as right advances, the window might expand to include earlier
            # dates that were previously excluded.
            # Actually, left only needs to move forward, so the two-pointer
            # approach is valid.  But we need to reset left to the saved
            # position for the next right, not keep advancing.
            # The two-pointer approach works because dates are sorted:
            # as right increases, start_date can only increase (or stay same),
            # so left can only advance.

        if best_window_end_idx is not None and best_window_start_idx is not None:
            best_window = player_df.iloc[
                best_window_start_idx : best_window_end_idx + 1
            ]
            rec = {
                "batter_id": batter_id,
                "batter": batter_name,
                "peak_window_start": dates.iloc[best_window_start_idx],
                "peak_window_end": dates.iloc[best_window_end_idx],
                "peak_window_innings": len(best_window),
                "peak_window_composite": best_composite,
            }

            # Supplementary stats for the peak window
            if "runs" in best_window.columns:
                rec["peak_window_avg_runs"] = float(best_window["runs"].mean())
            if "sr" in best_window.columns:
                sr_vals = best_window["sr"].dropna()
                rec["peak_window_avg_sr"] = (
                    float(sr_vals.mean()) if len(sr_vals) > 0 else np.nan
                )
            if "acc_overall_sr" in best_window.columns:
                rec["peak_window_sr_vs_par"] = _safe_mean(best_window["acc_overall_sr"])
            if "pow_boundary_pct" in best_window.columns:
                rec["peak_window_boundary_pct"] = _safe_mean(
                    best_window["pow_boundary_pct"]
                )

            results.append(rec)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    for col in ["peak_window_start", "peak_window_end"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def compute_sliding_peak_bowl(
    bowl_components: pd.DataFrame,
    window_days: int | None = None,
    min_window_spells: int | None = None,
    min_career_spells: int | None = None,
) -> pd.DataFrame:
    """
    Find each bowler's best sliding window of ``window_days`` duration.

    Parameters
    ----------
    bowl_components : pd.DataFrame
        Per-spell component data.
    window_days : int, optional
        Window size in days.  Default 730 (2 years).
    min_window_spells : int, optional
        Minimum spells inside a window for it to be valid.  Default 5.
    min_career_spells : int, optional
        Skip bowlers with fewer total career spells.  Default 10.

    Returns
    -------
    pd.DataFrame
        One row per bowler with peak window details.
    """
    if window_days is None:
        window_days = PEAK_WINDOW_DAYS
    if min_window_spells is None:
        min_window_spells = PEAK_WINDOW_MIN_INNINGS
    if min_career_spells is None:
        min_career_spells = PEAK_MIN_SPELLS_BOWL

    if bowl_components.empty:
        return pd.DataFrame()

    bc = bowl_components.copy()
    _decat(bc, ["bowler_id", "bowler"])

    bc["date"] = pd.to_datetime(bc["date"], errors="coerce")
    bc = bc.dropna(subset=["date"])
    bc = bc.sort_values(["bowler_id", "date"]).reset_index(drop=True)

    results: list[dict] = []
    window_td = pd.Timedelta(days=window_days)

    for bowler_id, player_df in bc.groupby("bowler_id", sort=False):
        player_df = player_df.reset_index(drop=True)
        n = len(player_df)
        if n < min_career_spells:
            continue

        bowler_name = player_df.iloc[-1]["bowler"]
        dates = player_df["date"]

        best_composite = -np.inf
        best_end_idx: int | None = None
        best_start_idx: int | None = None

        left = 0
        for right in range(n):
            end_date = dates.iloc[right]
            start_date = end_date - window_td

            while left < right and dates.iloc[left] < start_date:
                left += 1

            window_size = right - left + 1
            if window_size < min_window_spells:
                continue

            window = player_df.iloc[left : right + 1]
            composite = _compute_window_composite_bowl(window)

            if not np.isnan(composite) and composite > best_composite:
                best_composite = composite
                best_end_idx = right
                best_start_idx = left

        if best_end_idx is not None and best_start_idx is not None:
            best_window = player_df.iloc[best_start_idx : best_end_idx + 1]
            rec = {
                "bowler_id": bowler_id,
                "bowler": bowler_name,
                "peak_window_start": dates.iloc[best_start_idx],
                "peak_window_end": dates.iloc[best_end_idx],
                "peak_window_spells": len(best_window),
                "peak_window_composite": best_composite,
            }

            if "economy" in best_window.columns:
                rec["peak_window_avg_economy"] = _safe_mean(best_window["economy"])
            if "wickets" in best_window.columns:
                rec["peak_window_avg_wickets"] = _safe_mean(best_window["wickets"])
            if "acc_economy_vs_par" in best_window.columns:
                rec["peak_window_economy_vs_par"] = _safe_mean(
                    best_window["acc_economy_vs_par"]
                )

            results.append(rec)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    for col in ["peak_window_start", "peak_window_end"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out
