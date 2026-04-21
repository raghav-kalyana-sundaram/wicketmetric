"""
Form Tracker — Rolling-window time-series ratings for batters and bowlers.

Feature 13 from the Version 0.2 roadmap.

Produces one row per (player, match_date) with windowed metrics computed
over the most recent N innings/spells.  This enables frontend sparklines,
form-over-time charts, and "purple patch" / "slump" detection.

The rolling window slides forward one innings at a time.  For each position
of the window, the function computes means of the key component columns
that already exist on ``bat_components`` / ``bowl_components``.

**v0.3 Overhaul (Form Tracker Improvements)**:

The original composite was a naïve mean of three raw proxies on wildly
different scales (``sr_vs_par`` typically -0.9..+0.7, ``boundary_pct``
0..0.9, ``consistency`` 0.1..0.87).  This caused:
  - Composite values clustered in 0.0–0.5 with no intuitive meaning.
  - 94.5% correlation with strike rate alone — ignoring runs, volume.
  - Kohli's 973-run 2016 IPL ranked *below* Jadeja averaging 20 runs.

The new system:
  1. Computes per-window z-scores for each component against the
     population of all windows (same approach as career rating).
  2. Combines them with the same weights used by the career pipeline
     to produce ``raw_acceleration``, ``raw_power``, ``raw_control``
     sub-scores per window.
  3. Percentile-ranks these across ALL player-windows to produce
     0–100 scores (``window_score_acceleration``, ``window_score_power``,
     ``window_score_control``, ``window_composite``).
  4. The composite is a superstar-aware mean (matching ``presentation.py``).
  5. Annotates each player's personal peak window for the frontend.

Complexity
----------
O(P × I) where P = players, I = max innings per player.  On ~49K batting
innings and ~36K bowling spells this completes in 2–4 seconds.

Usage
-----
    from src.form_tracker import (
        compute_batting_form_series,
        compute_bowling_form_series,
    )

    bat_form = compute_batting_form_series(bat_components, window_matches=10)
    bowl_form = compute_bowling_form_series(bowl_components, window_matches=10)

Config keys (read from ``config.yaml`` via ``src/config.py``):
    form_tracker.enabled           : bool  (default True)
    form_tracker.window_matches_bat: int   (default 10)
    form_tracker.window_matches_bowl: int  (default 10)
    form_tracker.min_window        : int   (default 5)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import cfg

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------
FORM_TRACKER_ENABLED: bool = cfg("form_tracker.enabled", default=True)
WINDOW_MATCHES_BAT: int = cfg("form_tracker.window_matches_bat", default=10)
WINDOW_MATCHES_BOWL: int = cfg("form_tracker.window_matches_bowl", default=10)
MIN_WINDOW: int = cfg("form_tracker.min_window", default=5)

# Superstar bonus parameters (mirroring presentation.py)
_SUPERSTAR_THRESHOLD = 85.0
_SUPERSTAR_BONUS_WEIGHT = 0.10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decat(df: pd.DataFrame, cols: list[str]) -> None:
    """Convert categorical columns to plain strings (in-place)."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)


def _safe_mean(series: pd.Series) -> float:
    """Mean ignoring NaN; return NaN if all values are NaN."""
    vals = series.dropna()
    return vals.mean() if len(vals) > 0 else np.nan


def _safe_sum(series: pd.Series) -> float:
    """Sum ignoring NaN; return 0 if all NaN."""
    vals = series.dropna()
    return vals.sum() if len(vals) > 0 else 0.0


def _zscore_series(s: pd.Series) -> pd.Series:
    """Z-score normalise a series; returns 0 for constant/empty series."""
    if s.isna().all() or len(s) == 0:
        return s.copy().fillna(0.0)
    mu = s.mean()
    sigma = s.std()
    if sigma < 1e-10:
        return pd.Series(0.0, index=s.index)
    return ((s - mu) / sigma).fillna(0.0)


def _percentile_rank(s: pd.Series) -> pd.Series:
    """Convert values to 0-100 percentile ranks (fractional ranking)."""
    if s.isna().all() or len(s) == 0:
        return s.copy()
    ranked = s.rank(method="average", pct=True, na_option="bottom")
    return (ranked * 100).round(1)


def _compute_overall_from_sub_scores(
    scores: list[float],
    *,
    superstar_threshold: float = _SUPERSTAR_THRESHOLD,
    superstar_bonus_weight: float = _SUPERSTAR_BONUS_WEIGHT,
) -> float:
    """
    Compute an overall composite from sub-scores using the superstar-aware
    formula from ``presentation.py``.  This rewards specialists.
    """
    valid = [
        s for s in scores if not (s is None or (isinstance(s, float) and np.isnan(s)))
    ]
    if not valid:
        return np.nan

    base = float(np.mean(valid))
    individual_bonuses = [max(s - superstar_threshold, 0.0) for s in valid]
    bonus = max(individual_bonuses) if individual_bonuses else 0.0
    overall = base + superstar_bonus_weight * bonus
    return float(np.clip(overall, 0.0, 100.0))


# ---------------------------------------------------------------------------
# Batting form series
# ---------------------------------------------------------------------------


def compute_batting_form_series(
    bat_components: pd.DataFrame,
    window_matches: int | None = None,
    min_window: int | None = None,
) -> pd.DataFrame:
    """
    Compute a rolling-window rating snapshot for each batter at each innings.

    Returns one row per (batter, innings_index) with windowed metrics and
    **0–100 percentile-ranked** sub-scores and composite that are consistent
    with the career rating system.

    Parameters
    ----------
    bat_components : pd.DataFrame
        Per-innings component data — output of ``compute_batting_components()``.
        Must contain at minimum: ``batter_id``, ``batter``, ``date``,
        ``acc_overall_sr``, ``runs``.
    window_matches : int, optional
        Number of innings in the rolling window.  Defaults to config value.
    min_window : int, optional
        Minimum number of innings before the first data point is emitted.
        Defaults to config value.

    Returns
    -------
    pd.DataFrame
        One row per (batter, window_end_date) with columns:
        - batter_id, batter, date, match_id
        - window_innings, cumulative_innings
        - window_sr_vs_par, window_impact, window_xr  (Acceleration proxies)
        - window_boundary_pct, window_six_rate, window_finishing_burst  (Power proxies)
        - window_dot_control, window_consistency  (Control proxies)
        - window_avg_runs, window_avg_sr
        - window_total_runs  (sum of runs in the window — captures volume)
        - window_avg_balls_to_par, window_selfless_index  (v0.2 metrics if present)
        - raw_window_acceleration, raw_window_power, raw_window_control  (z-score composites)
        - window_score_acceleration, window_score_power, window_score_control  (0-100 percentile)
        - window_composite  (0-100 overall score, superstar-aware)
        - is_peak_window  (bool — True for the player's personal all-time peak)
    """
    if window_matches is None:
        window_matches = WINDOW_MATCHES_BAT
    if min_window is None:
        min_window = MIN_WINDOW

    if bat_components.empty:
        return pd.DataFrame()

    bc = bat_components.copy()
    _decat(bc, ["batter_id", "batter"])

    # Sort by player then date for chronological sliding window
    bc = bc.sort_values(["batter_id", "date"]).reset_index(drop=True)

    results: list[dict] = []

    for batter_id, player_df in bc.groupby("batter_id", sort=False):
        player_df = player_df.reset_index(drop=True)
        n = len(player_df)

        if n < min_window:
            continue

        batter_name = player_df.iloc[-1]["batter"]

        for i in range(min_window, n + 1):
            start = max(0, i - window_matches)
            window = player_df.iloc[start:i]

            row: dict = {
                "batter_id": batter_id,
                "batter": batter_name,
                "date": window.iloc[-1]["date"],
                "match_id": window.iloc[-1].get("match_id", None),
                "window_innings": len(window),
                "cumulative_innings": i,
            }

            # ── Acceleration proxies ──
            row["window_sr_vs_par"] = _safe_mean(window["acc_overall_sr"])

            if "acc_impact" in window.columns:
                row["window_impact"] = _safe_mean(window["acc_impact"])
            else:
                row["window_impact"] = np.nan

            if "acc_runs_above_expected" in window.columns:
                row["window_xr"] = _safe_mean(window["acc_runs_above_expected"])
            else:
                row["window_xr"] = np.nan

            if "acc_leveraged_rva" in window.columns:
                row["window_leveraged_rva"] = _safe_mean(window["acc_leveraged_rva"])
            else:
                row["window_leveraged_rva"] = np.nan

            # ── Power proxies ──
            if "pow_boundary_pct" in window.columns:
                row["window_boundary_pct"] = _safe_mean(window["pow_boundary_pct"])
            else:
                row["window_boundary_pct"] = np.nan

            if "pow_six_rate" in window.columns:
                row["window_six_rate"] = _safe_mean(window["pow_six_rate"])
            else:
                row["window_six_rate"] = np.nan

            if "pow_finishing_burst" in window.columns:
                row["window_finishing_burst"] = _safe_mean(
                    window["pow_finishing_burst"]
                )
            else:
                row["window_finishing_burst"] = np.nan

            if "pow_peak_phase_sr" in window.columns:
                row["window_peak_phase_sr"] = _safe_mean(window["pow_peak_phase_sr"])
            else:
                row["window_peak_phase_sr"] = np.nan

            if "pow_power_impact" in window.columns:
                row["window_power_impact"] = _safe_mean(window["pow_power_impact"])
            else:
                row["window_power_impact"] = np.nan

            # ── Control proxies ──
            if "ctrl_dot_pct_weighted" in window.columns:
                row["window_dot_control"] = _safe_mean(window["ctrl_dot_pct_weighted"])
            else:
                row["window_dot_control"] = np.nan

            if "ctrl_scoring_consistency" in window.columns:
                row["window_consistency"] = _safe_mean(
                    window["ctrl_scoring_consistency"]
                )
            else:
                row["window_consistency"] = np.nan

            if "ctrl_rotation" in window.columns:
                row["window_rotation"] = _safe_mean(window["ctrl_rotation"])
            else:
                row["window_rotation"] = np.nan

            if "ctrl_avg_proxy" in window.columns:
                row["window_avg_proxy"] = _safe_mean(window["ctrl_avg_proxy"])
            else:
                row["window_avg_proxy"] = np.nan

            if "ctrl_dismissal_quality" in window.columns:
                row["window_dismissal_quality"] = _safe_mean(
                    window["ctrl_dismissal_quality"]
                )
            else:
                row["window_dismissal_quality"] = np.nan

            if "ctrl_survival_ratio" in window.columns:
                row["window_survival_ratio"] = _safe_mean(window["ctrl_survival_ratio"])
            else:
                row["window_survival_ratio"] = np.nan

            # ── Raw stats ──
            row["window_avg_runs"] = _safe_mean(window["runs"])
            row["window_total_runs"] = _safe_sum(window["runs"])

            if "sr" in window.columns:
                row["window_avg_sr"] = _safe_mean(window["sr"])
            else:
                row["window_avg_sr"] = np.nan

            if "balls_faced" in window.columns:
                row["window_avg_balls"] = _safe_mean(window["balls_faced"])
            else:
                row["window_avg_balls"] = np.nan

            if "fours" in window.columns and "sixes" in window.columns:
                total_fours = _safe_sum(window["fours"])
                total_sixes = _safe_sum(window["sixes"])
                row["window_fours"] = total_fours
                row["window_sixes"] = total_sixes

            # ── v0.2 feature columns (if present) ──
            if "balls_to_par" in window.columns:
                row["window_avg_balls_to_par"] = _safe_mean(window["balls_to_par"])
            if "fifty_approach_sr" in window.columns:
                row["window_fifty_approach_sr"] = _safe_mean(
                    window["fifty_approach_sr"]
                )
            if "century_approach_sr" in window.columns:
                row["window_century_approach_sr"] = _safe_mean(
                    window["century_approach_sr"]
                )

            results.append(row)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)

    # ──────────────────────────────────────────────────────────────────
    # Phase 2: Z-score normalisation + percentile ranking across ALL
    # player-windows.  This mirrors the career pipeline's approach.
    # ──────────────────────────────────────────────────────────────────

    # --- Acceleration z-score composite ---
    z_sr = _zscore_series(out["window_sr_vs_par"])
    z_impact = (
        _zscore_series(out["window_impact"]) if "window_impact" in out.columns else 0.0
    )
    z_xr = _zscore_series(out["window_xr"]) if "window_xr" in out.columns else 0.0
    z_lrva = (
        _zscore_series(out["window_leveraged_rva"])
        if "window_leveraged_rva" in out.columns
        else 0.0
    )

    out["raw_window_acceleration"] = (
        0.20 * z_sr + 0.15 * z_impact + 0.30 * z_xr + 0.35 * z_lrva
    )

    # --- Power z-score composite ---
    z_bpct = (
        _zscore_series(out["window_boundary_pct"])
        if "window_boundary_pct" in out.columns
        else 0.0
    )
    z_six = (
        _zscore_series(out["window_six_rate"])
        if "window_six_rate" in out.columns
        else 0.0
    )
    z_burst = (
        _zscore_series(out["window_finishing_burst"])
        if "window_finishing_burst" in out.columns
        else 0.0
    )
    z_peak = (
        _zscore_series(out["window_peak_phase_sr"])
        if "window_peak_phase_sr" in out.columns
        else 0.0
    )
    z_pi = (
        _zscore_series(out["window_power_impact"])
        if "window_power_impact" in out.columns
        else 0.0
    )

    out["raw_window_power"] = (
        0.20 * z_bpct + 0.25 * z_six + 0.20 * z_burst + 0.15 * z_peak + 0.20 * z_pi
    )

    # --- Control z-score composite ---
    z_dot = (
        _zscore_series(out["window_dot_control"])
        if "window_dot_control" in out.columns
        else 0.0
    )
    z_rot = (
        _zscore_series(out["window_rotation"])
        if "window_rotation" in out.columns
        else 0.0
    )
    z_consist = (
        _zscore_series(out["window_consistency"])
        if "window_consistency" in out.columns
        else 0.0
    )
    z_avg = (
        _zscore_series(out["window_avg_proxy"])
        if "window_avg_proxy" in out.columns
        else 0.0
    )
    z_dismiss = (
        _zscore_series(out["window_dismissal_quality"])
        if "window_dismissal_quality" in out.columns
        else 0.0
    )
    has_survival = (
        "window_survival_ratio" in out.columns
        and out["window_survival_ratio"].notna().any()
    )
    z_surv = _zscore_series(out["window_survival_ratio"]) if has_survival else None

    if has_survival and z_surv is not None:
        # Full weight set (matches career pipeline)
        out["raw_window_control"] = (
            0.12 * z_dot
            + 0.08 * z_rot
            + 0.10 * z_consist
            + 0.20 * z_avg
            + 0.10 * z_dismiss
            + 0.40 * z_surv
        )
    else:
        # Redistributed weights when survival_ratio is unavailable
        # (it's a career-level metric, not computed per-innings).
        # Bump avg_proxy (the best remaining volume proxy) the most.
        out["raw_window_control"] = (
            0.15 * z_dot
            + 0.10 * z_rot
            + 0.15 * z_consist
            + 0.40 * z_avg
            + 0.20 * z_dismiss
        )

    # --- Volume adjustment ---
    # Multiply raw z-scores by a gentle volume factor so that a window
    # averaging 65 runs/innings counts more than one averaging 7 runs.
    # This is analogous to the career pipeline's ``avg_quality_factor``.
    # Uses a sigmoid-style scaling: factor = clip(avg_runs / median_runs, 0.7, 1.3)
    median_runs = out["window_avg_runs"].median()
    if median_runs is not None and median_runs > 1.0:
        vol_factor = (out["window_avg_runs"] / median_runs).clip(0.7, 1.3)
    else:
        vol_factor = 1.0

    out["raw_window_acceleration"] = out["raw_window_acceleration"] * vol_factor
    out["raw_window_power"] = out["raw_window_power"] * vol_factor
    out["raw_window_control"] = out["raw_window_control"] * vol_factor

    # --- Percentile ranking → 0-100 ---
    out["window_score_acceleration"] = _percentile_rank(out["raw_window_acceleration"])
    out["window_score_power"] = _percentile_rank(out["raw_window_power"])
    out["window_score_control"] = _percentile_rank(out["raw_window_control"])

    # --- Overall composite (superstar-aware) ---
    def _row_composite(r: pd.Series) -> float:
        return _compute_overall_from_sub_scores(
            [
                r["window_score_acceleration"],
                r["window_score_power"],
                r["window_score_control"],
            ]
        )

    out["window_composite"] = out.apply(_row_composite, axis=1).round(1)

    # ── Peak annotation per player ──
    # Mark the single highest-composite row for each player.
    out["is_peak_window"] = False
    for _bid, grp in out.groupby("batter_id", sort=False):
        if grp.empty:
            continue
        peak_idx = grp["window_composite"].idxmax()
        if pd.notna(peak_idx):
            out.loc[peak_idx, "is_peak_window"] = True

    # Ensure date column is datetime
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")

    return out


# ---------------------------------------------------------------------------
# Bowling form series
# ---------------------------------------------------------------------------


def compute_bowling_form_series(
    bowl_components: pd.DataFrame,
    window_matches: int | None = None,
    min_window: int | None = None,
) -> pd.DataFrame:
    """
    Compute a rolling-window form snapshot for each bowler at each spell.

    Returns one row per (bowler, spell_index) with windowed metrics and
    **0–100 percentile-ranked** sub-scores and composite.

    Parameters
    ----------
    bowl_components : pd.DataFrame
        Per-spell component data — output of ``compute_bowling_components()``.
        Must contain at minimum: ``bowler_id``, ``bowler``, ``date``.
    window_matches : int, optional
        Number of spells in the rolling window.  Defaults to config value.
    min_window : int, optional
        Minimum spells before the first data point is emitted.
        Defaults to config value.

    Returns
    -------
    pd.DataFrame
        One row per (bowler, window_end_date) with columns:
        - bowler_id, bowler, date, match_id
        - window_spells, cumulative_spells
        - window_economy, window_dot_pct, window_wickets_per_spell
        - window_economy_vs_par (Accuracy proxy)
        - window_entropy, window_vs_others (Control proxies)
        - window_quality_wickets, window_threat_pressure (Threat proxies)
        - raw_window_accuracy, raw_window_control, raw_window_threat (z-score composites)
        - window_score_accuracy, window_score_control, window_score_threat (0-100)
        - window_composite (0-100 overall)
        - is_peak_window (bool)
    """
    if window_matches is None:
        window_matches = WINDOW_MATCHES_BOWL
    if min_window is None:
        min_window = MIN_WINDOW

    if bowl_components.empty:
        return pd.DataFrame()

    bc = bowl_components.copy()
    _decat(bc, ["bowler_id", "bowler"])

    bc = bc.sort_values(["bowler_id", "date"]).reset_index(drop=True)

    results: list[dict] = []

    for bowler_id, player_df in bc.groupby("bowler_id", sort=False):
        player_df = player_df.reset_index(drop=True)
        n = len(player_df)

        if n < min_window:
            continue

        bowler_name = player_df.iloc[-1]["bowler"]

        for i in range(min_window, n + 1):
            start = max(0, i - window_matches)
            window = player_df.iloc[start:i]

            row: dict = {
                "bowler_id": bowler_id,
                "bowler": bowler_name,
                "date": window.iloc[-1]["date"],
                "match_id": window.iloc[-1].get("match_id", None),
                "window_spells": len(window),
                "cumulative_spells": i,
            }

            # ── Raw stats ──
            if "economy" in window.columns:
                row["window_economy"] = _safe_mean(window["economy"])
            else:
                row["window_economy"] = np.nan

            if "dot_pct" in window.columns:
                row["window_dot_pct"] = _safe_mean(window["dot_pct"])
            else:
                row["window_dot_pct"] = np.nan

            if "wickets" in window.columns:
                row["window_wickets_per_spell"] = _safe_mean(window["wickets"])
                row["window_total_wickets"] = _safe_sum(window["wickets"])
            else:
                row["window_wickets_per_spell"] = np.nan
                row["window_total_wickets"] = 0.0

            if "runs_conceded" in window.columns:
                row["window_runs_conceded"] = _safe_sum(window["runs_conceded"])
            elif "runs" in window.columns:
                row["window_runs_conceded"] = _safe_sum(window["runs"])

            # ── Accuracy proxies ──
            if "acc_economy_vs_par" in window.columns:
                row["window_economy_vs_par"] = _safe_mean(window["acc_economy_vs_par"])
            elif "economy_ratio_par" in window.columns:
                row["window_economy_vs_par"] = _safe_mean(
                    1.0 - window["economy_ratio_par"]
                )
            else:
                row["window_economy_vs_par"] = np.nan

            if "acc_dot_pct" in window.columns:
                row["window_acc_dot_pct"] = _safe_mean(window["acc_dot_pct"])
            else:
                row["window_acc_dot_pct"] = np.nan

            if "acc_boundary_penalty" in window.columns:
                row["window_boundary_penalty"] = _safe_mean(
                    window["acc_boundary_penalty"]
                )
            else:
                row["window_boundary_penalty"] = np.nan

            # ── Control proxies ──
            if "ctrl_entropy" in window.columns:
                row["window_entropy"] = _safe_mean(window["ctrl_entropy"])
            else:
                row["window_entropy"] = np.nan

            if "ctrl_vs_others" in window.columns:
                row["window_vs_others"] = _safe_mean(window["ctrl_vs_others"])
            else:
                row["window_vs_others"] = np.nan

            if "ctrl_phase_consistency" in window.columns:
                row["window_phase_consistency"] = _safe_mean(
                    window["ctrl_phase_consistency"]
                )
            else:
                row["window_phase_consistency"] = np.nan

            if "ctrl_bowling_rv" in window.columns:
                row["window_bowling_rv"] = _safe_mean(window["ctrl_bowling_rv"])
            else:
                row["window_bowling_rv"] = np.nan

            # ── Threat proxies ──
            if "threat_quality_wickets" in window.columns:
                row["window_quality_wickets"] = _safe_mean(
                    window["threat_quality_wickets"]
                )
            else:
                row["window_quality_wickets"] = np.nan

            if "threat_pressure" in window.columns:
                row["window_threat_pressure"] = _safe_mean(window["threat_pressure"])
            else:
                row["window_threat_pressure"] = np.nan

            if "threat_dots" in window.columns:
                row["window_threat_dots"] = _safe_mean(window["threat_dots"])
            else:
                row["window_threat_dots"] = np.nan

            results.append(row)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)

    # ──────────────────────────────────────────────────────────────────
    # Phase 2: Z-score normalisation + percentile ranking across ALL
    # bowler-windows.
    # ──────────────────────────────────────────────────────────────────

    # --- Accuracy z-score composite ---
    # For bowling, *lower* economy is better, so economy_vs_par is
    # already oriented positive-good (higher = better than par).
    z_econ_par = (
        _zscore_series(out["window_economy_vs_par"])
        if "window_economy_vs_par" in out.columns
        else 0.0
    )
    z_acc_dot = (
        _zscore_series(out["window_acc_dot_pct"])
        if "window_acc_dot_pct" in out.columns
        else 0.0
    )
    # Boundary penalty is negative-oriented, so negate
    z_bpen = 0.0
    if "window_boundary_penalty" in out.columns:
        z_bpen = _zscore_series(-out["window_boundary_penalty"].fillna(0.0))

    out["raw_window_accuracy"] = 0.45 * z_econ_par + 0.30 * z_acc_dot + 0.25 * z_bpen

    # --- Control z-score composite ---
    z_entropy = (
        _zscore_series(out["window_entropy"])
        if "window_entropy" in out.columns
        else 0.0
    )
    z_vs_others = (
        _zscore_series(out["window_vs_others"])
        if "window_vs_others" in out.columns
        else 0.0
    )
    z_phase_con = (
        _zscore_series(out["window_phase_consistency"])
        if "window_phase_consistency" in out.columns
        else 0.0
    )
    z_brv = (
        _zscore_series(out["window_bowling_rv"])
        if "window_bowling_rv" in out.columns
        else 0.0
    )

    out["raw_window_control"] = (
        0.20 * z_entropy + 0.30 * z_vs_others + 0.20 * z_phase_con + 0.30 * z_brv
    )

    # --- Threat z-score composite ---
    z_qw = (
        _zscore_series(out["window_quality_wickets"])
        if "window_quality_wickets" in out.columns
        else 0.0
    )
    z_pressure = (
        _zscore_series(out["window_threat_pressure"])
        if "window_threat_pressure" in out.columns
        else 0.0
    )
    z_tdots = (
        _zscore_series(out["window_threat_dots"])
        if "window_threat_dots" in out.columns
        else 0.0
    )

    out["raw_window_threat"] = 0.45 * z_qw + 0.30 * z_pressure + 0.25 * z_tdots

    # --- Volume adjustment ---
    # Bowlers who take more wickets per window should be rewarded slightly.
    if "window_wickets_per_spell" in out.columns:
        median_wps = out["window_wickets_per_spell"].median()
        if median_wps is not None and median_wps > 0.1:
            vol_factor = (out["window_wickets_per_spell"] / median_wps).clip(0.7, 1.3)
        else:
            vol_factor = 1.0
        out["raw_window_threat"] = out["raw_window_threat"] * vol_factor

    # --- Percentile ranking → 0-100 ---
    out["window_score_accuracy"] = _percentile_rank(out["raw_window_accuracy"])
    out["window_score_control"] = _percentile_rank(out["raw_window_control"])
    out["window_score_threat"] = _percentile_rank(out["raw_window_threat"])

    # --- Overall composite (superstar-aware) ---
    def _row_composite(r: pd.Series) -> float:
        return _compute_overall_from_sub_scores(
            [
                r["window_score_accuracy"],
                r["window_score_control"],
                r["window_score_threat"],
            ]
        )

    out["window_composite"] = out.apply(_row_composite, axis=1).round(1)

    # ── Peak annotation per bowler ──
    out["is_peak_window"] = False
    for _bid, grp in out.groupby("bowler_id", sort=False):
        if grp.empty:
            continue
        peak_idx = grp["window_composite"].idxmax()
        if pd.notna(peak_idx):
            out.loc[peak_idx, "is_peak_window"] = True

    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")

    return out


# ---------------------------------------------------------------------------
# Convenience: compute both at once
# ---------------------------------------------------------------------------


def compute_form_series(
    bat_components: pd.DataFrame,
    bowl_components: pd.DataFrame,
    window_bat: int | None = None,
    window_bowl: int | None = None,
    min_window: int | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Compute batting and bowling form series in one call.

    Returns
    -------
    dict with keys ``"batting"`` and ``"bowling"``, each a DataFrame.
    Returns empty DataFrames if form tracker is disabled in config.
    """
    if not FORM_TRACKER_ENABLED:
        return {
            "batting": pd.DataFrame(),
            "bowling": pd.DataFrame(),
        }

    bat_form = compute_batting_form_series(
        bat_components,
        window_matches=window_bat,
        min_window=min_window,
    )
    bowl_form = compute_bowling_form_series(
        bowl_components,
        window_matches=window_bowl,
        min_window=min_window,
    )
    return {
        "batting": bat_form,
        "bowling": bowl_form,
    }
