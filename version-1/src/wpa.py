"""
Feature 10: Win Probability Added (WPA) / Leverage Multiplier

Computes how much each delivery changes the probability of the batting team
winning, then attributes that change to the batter and bowler involved.

Architecture
------------
1. **Build a win-probability model** from historical data.
   - For **2nd innings**: use the empirical batting-team win rate at each
     game state (over, wickets, score_ratio = runs_scored / target).
   - For **1st innings**: estimate win probability via a "par score at this
     stage" model — compare current score / wickets against the historical
     average for that (over, wickets) state.
   - Smoothing via Laplace (additive) smoothing + fallback interpolation
     for sparse buckets ensures every state has a reasonable estimate.

2. **Score each delivery** with win_prob_before and win_prob_after, then
   compute ``wpa = win_prob_after - win_prob_before``.

3. **Aggregate** per player:
   - ``career_wpa`` : Sum of WPA across all deliveries (additive — rewards
     both volume and quality).
   - ``wpa_per_match`` : career_wpa / matches (intensity measure).
   - ``positive_wpa`` : Sum of only positive WPA contributions (clutch).
   - ``negative_wpa`` : Sum of only negative WPA contributions (chokes).

Integration
-----------
Called from ``main.py`` after delivery parsing.  Disabled by default
(``wpa.enabled: false`` in config) because it is computationally expensive
on ~750K deliveries.

Output files: ``wpa_batting.parquet``, ``wpa_bowling.parquet``, and columns
merged onto career DataFrames.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# ───────────────────────────────────────────────────────────────────────────
# Configuration defaults
# ───────────────────────────────────────────────────────────────────────────

_DEFAULT_SCORE_RATIO_BUCKETS = 10  # number of buckets for score/target ratio
_DEFAULT_FIRST_INN_SCORE_BUCKETS = 8  # buckets for 1st-innings run-rate ratio
_DEFAULT_LAPLACE_ALPHA = 2  # Laplace smoothing pseudo-count
_DEFAULT_MIN_BUCKET_OBS = 3  # min observations before using a bucket value

# ───────────────────────────────────────────────────────────────────────────
# Internal helpers
# ───────────────────────────────────────────────────────────────────────────


def _decat(df: pd.DataFrame, cols: list[str]) -> None:
    """Convert categorical columns to plain strings (in-place)."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)


def _bucketise(series: pd.Series, n_buckets: int) -> pd.Series:
    """
    Map a 0–1+ float series into discrete buckets: 0.0, 1/n, 2/n, …, 1.0.

    Values > 1.0 are clipped to 1.0.  NaN stays NaN.
    """
    clipped = series.clip(lower=0.0, upper=1.0)
    return (clipped * n_buckets).round() / n_buckets


# ───────────────────────────────────────────────────────────────────────────
# Step 1a: Build 2nd-innings win-probability model (empirical lookup)
# ───────────────────────────────────────────────────────────────────────────


def build_second_innings_wp_model(
    deliveries: pd.DataFrame,
    *,
    score_ratio_buckets: int = _DEFAULT_SCORE_RATIO_BUCKETS,
    laplace_alpha: int = _DEFAULT_LAPLACE_ALPHA,
) -> dict[tuple[int, int, float], float]:
    """
    Build an empirical win probability lookup for 2nd-innings states.

    For each game state (over, wickets_fallen, score_ratio_bucket),
    compute the historical batting team win percentage with Laplace
    smoothing.

    Parameters
    ----------
    deliveries : pd.DataFrame
        Full delivery-level DataFrame.  Must include: ``innings_num``,
        ``over``, ``team_wickets_before``, ``team_score_before``,
        ``target_runs``, ``batting_team``, ``winner``, ``match_id``.
    score_ratio_buckets : int
        Number of discrete buckets for score / target ratio.
    laplace_alpha : int
        Pseudo-count for Laplace smoothing (higher = more conservative
        towards 50%).

    Returns
    -------
    dict
        Keys: ``(over_bucket, wickets_bucket, score_ratio_bucket)``
        Values: float win probability [0, 1] for the batting team.
    """
    df = deliveries.copy()
    _decat(df, ["match_id", "batting_team", "winner", "bowling_team"])

    # Only 2nd innings deliveries
    d2 = df[df["innings_num"] == 2].copy()
    if d2.empty:
        return {}

    # Game state features
    d2["over_bucket"] = d2["over"].clip(upper=19).astype(int)
    d2["wickets_bucket"] = d2["team_wickets_before"].clip(upper=9).astype(int)

    # Score ratio: runs scored so far / target
    target = pd.to_numeric(d2["target_runs"], errors="coerce").fillna(0)
    d2["score_ratio"] = np.where(
        target > 0,
        d2["team_score_before"].astype(float) / target,
        0.0,
    )
    d2["score_ratio_bucket"] = _bucketise(d2["score_ratio"], score_ratio_buckets)

    # Did the batting (chasing) team win?
    d2["batting_won"] = (d2["batting_team"] == d2["winner"]).astype(int)

    # De-duplicate: take only the first delivery per state per match
    # to avoid weighting long overs more heavily.
    d2_dedup = d2.drop_duplicates(
        subset=["match_id", "over_bucket", "wickets_bucket", "score_ratio_bucket"],
        keep="first",
    )

    # Aggregate with Laplace smoothing
    grouped = (
        d2_dedup.groupby(["over_bucket", "wickets_bucket", "score_ratio_bucket"])
        .agg(
            wins=("batting_won", "sum"),
            total=("batting_won", "count"),
        )
        .reset_index()
    )

    wp_table: dict[tuple[int, int, float], float] = {}
    for _, row in grouped.iterrows():
        key = (
            int(row["over_bucket"]),
            int(row["wickets_bucket"]),
            float(row["score_ratio_bucket"]),
        )
        wins = row["wins"] + laplace_alpha
        total = row["total"] + 2 * laplace_alpha
        wp_table[key] = wins / total

    return wp_table


# ───────────────────────────────────────────────────────────────────────────
# Step 1b: Build 1st-innings win-probability model
# ───────────────────────────────────────────────────────────────────────────


def _compute_first_innings_par_scores(
    deliveries: pd.DataFrame,
) -> dict[tuple[int, int], float]:
    """
    Compute the average 1st-innings score at each (over, wickets) state.

    Returns a lookup: ``(over, wickets_fallen) → avg_team_score_before``.
    """
    df = deliveries.copy()
    _decat(df, ["match_id"])

    d1 = df[df["innings_num"] == 1].copy()
    if d1.empty:
        return {}

    d1["over_bucket"] = d1["over"].clip(upper=19).astype(int)
    d1["wickets_bucket"] = d1["team_wickets_before"].clip(upper=9).astype(int)

    par = (
        d1.groupby(["over_bucket", "wickets_bucket"])
        .agg(
            avg_score=("team_score_before", "mean"),
        )
        .reset_index()
    )

    return {
        (int(r["over_bucket"]), int(r["wickets_bucket"])): float(r["avg_score"])
        for _, r in par.iterrows()
    }


def build_first_innings_wp_model(
    deliveries: pd.DataFrame,
    *,
    rr_ratio_buckets: int = _DEFAULT_FIRST_INN_SCORE_BUCKETS,
    laplace_alpha: int = _DEFAULT_LAPLACE_ALPHA,
) -> tuple[dict[tuple[int, int, float], float], dict[tuple[int, int], float]]:
    """
    Build a win-probability model for 1st-innings deliveries.

    The idea: at any point in the 1st innings, we compute how the batting
    team's current score compares to the historical average score at this
    (over, wickets) state.  ``rr_ratio = actual_score / par_score``.
    Then we look up the historical win rate for teams in that position.

    Parameters
    ----------
    deliveries : pd.DataFrame
        Full delivery-level DataFrame.
    rr_ratio_buckets : int
        Number of discrete buckets for the run-rate ratio.
    laplace_alpha : int
        Laplace smoothing pseudo-count.

    Returns
    -------
    (wp_table_inn1, par_scores)
        wp_table_inn1 : dict (over, wickets, rr_ratio_bucket) → float
        par_scores : dict (over, wickets) → avg_score
    """
    df = deliveries.copy()
    _decat(df, ["match_id", "batting_team", "winner"])

    par_scores = _compute_first_innings_par_scores(df)

    d1 = df[df["innings_num"] == 1].copy()
    if d1.empty:
        return {}, par_scores

    d1["over_bucket"] = d1["over"].clip(upper=19).astype(int)
    d1["wickets_bucket"] = d1["team_wickets_before"].clip(upper=9).astype(int)

    # Look up par score for each state
    d1["par_score"] = d1.apply(
        lambda r: par_scores.get(
            (int(r["over_bucket"]), int(r["wickets_bucket"])), 1.0
        ),
        axis=1,
    )
    d1["par_score"] = d1["par_score"].clip(lower=1.0)

    # Run-rate ratio: how far ahead/behind the batting team is
    d1["rr_ratio"] = d1["team_score_before"].astype(float) / d1["par_score"]
    d1["rr_ratio_bucket"] = _bucketise(
        d1["rr_ratio"].clip(upper=2.0) / 2.0,  # map 0-2 → 0-1 for bucketing
        rr_ratio_buckets,
    )

    # Did the batting team win?
    d1["batting_won"] = (d1["batting_team"] == d1["winner"]).astype(int)

    d1_dedup = d1.drop_duplicates(
        subset=["match_id", "over_bucket", "wickets_bucket", "rr_ratio_bucket"],
        keep="first",
    )

    grouped = (
        d1_dedup.groupby(["over_bucket", "wickets_bucket", "rr_ratio_bucket"])
        .agg(
            wins=("batting_won", "sum"),
            total=("batting_won", "count"),
        )
        .reset_index()
    )

    wp_table: dict[tuple[int, int, float], float] = {}
    for _, row in grouped.iterrows():
        key = (
            int(row["over_bucket"]),
            int(row["wickets_bucket"]),
            float(row["rr_ratio_bucket"]),
        )
        wins = row["wins"] + laplace_alpha
        total = row["total"] + 2 * laplace_alpha
        wp_table[key] = wins / total

    return wp_table, par_scores


# ───────────────────────────────────────────────────────────────────────────
# Step 2: Score each delivery with WPA
# ───────────────────────────────────────────────────────────────────────────


def _lookup_wp_2nd(
    over: int,
    wickets: int,
    score: float,
    target: float,
    wp_table: dict[tuple[int, int, float], float],
    n_buckets: int,
) -> float:
    """
    Look up 2nd-innings win probability for a game state.

    Falls back to nearest available bucket if exact state not found.
    """
    over_b = min(int(over), 19)
    wkt_b = min(int(wickets), 9)

    # Score ratio bucketed
    ratio = score / target if target > 0 else 0.0
    ratio = min(max(ratio, 0.0), 1.0)
    sr_bucket = round(ratio * n_buckets) / n_buckets

    # Direct lookup
    key = (over_b, wkt_b, sr_bucket)
    if key in wp_table:
        return wp_table[key]

    # Fallback: find nearest score_ratio bucket at this (over, wickets)
    candidates = {k: v for k, v in wp_table.items() if k[0] == over_b and k[1] == wkt_b}
    if candidates:
        nearest_key = min(candidates.keys(), key=lambda k: abs(k[2] - sr_bucket))
        return candidates[nearest_key]

    # Broader fallback: same over, any wickets, nearest score ratio
    candidates = {k: v for k, v in wp_table.items() if k[0] == over_b}
    if candidates:
        nearest_key = min(
            candidates.keys(),
            key=lambda k: abs(k[1] - wkt_b) * 10 + abs(k[2] - sr_bucket),
        )
        return candidates[nearest_key]

    # Last resort: 50/50
    return 0.5


def _lookup_wp_1st(
    over: int,
    wickets: int,
    score: float,
    wp_table: dict[tuple[int, int, float], float],
    par_scores: dict[tuple[int, int], float],
    n_buckets: int,
) -> float:
    """
    Look up 1st-innings win probability for a game state.
    """
    over_b = min(int(over), 19)
    wkt_b = min(int(wickets), 9)

    par = par_scores.get((over_b, wkt_b), 1.0)
    par = max(par, 1.0)
    rr_ratio = score / par
    rr_ratio = min(max(rr_ratio, 0.0), 2.0)
    rr_bucket = round((rr_ratio / 2.0) * n_buckets) / n_buckets

    key = (over_b, wkt_b, rr_bucket)
    if key in wp_table:
        return wp_table[key]

    # Fallback: nearest rr_ratio bucket at (over, wickets)
    candidates = {k: v for k, v in wp_table.items() if k[0] == over_b and k[1] == wkt_b}
    if candidates:
        nearest_key = min(candidates.keys(), key=lambda k: abs(k[2] - rr_bucket))
        return candidates[nearest_key]

    # Broader fallback
    candidates = {k: v for k, v in wp_table.items() if k[0] == over_b}
    if candidates:
        nearest_key = min(
            candidates.keys(),
            key=lambda k: abs(k[1] - wkt_b) * 10 + abs(k[2] - rr_bucket),
        )
        return candidates[nearest_key]

    return 0.5


def compute_delivery_wpa(
    deliveries: pd.DataFrame,
    wp_model_2nd: dict[tuple[int, int, float], float],
    wp_model_1st: dict[tuple[int, int, float], float],
    par_scores_1st: dict[tuple[int, int], float],
    *,
    score_ratio_buckets: int = _DEFAULT_SCORE_RATIO_BUCKETS,
    rr_ratio_buckets: int = _DEFAULT_FIRST_INN_SCORE_BUCKETS,
) -> pd.DataFrame:
    """
    Add ``wpa`` column to a delivery DataFrame.

    For each delivery, compute:
        win_prob_before  — win probability of the batting team BEFORE this delivery
        win_prob_after   — win probability AFTER this delivery's outcome
        wpa              — win_prob_after - win_prob_before

    Positive WPA = delivery helped the batting team.
    Negative WPA = delivery hurt the batting team (helped the bowling team).

    Parameters
    ----------
    deliveries : pd.DataFrame
        Full delivery-level DataFrame.
    wp_model_2nd : dict
        Lookup table for 2nd-innings states.
    wp_model_1st : dict
        Lookup table for 1st-innings states.
    par_scores_1st : dict
        (over, wickets) → average 1st-innings score at that state.
    score_ratio_buckets : int
        Bucket count used when building the 2nd-innings model.
    rr_ratio_buckets : int
        Bucket count used when building the 1st-innings model.

    Returns
    -------
    pd.DataFrame
        Copy of deliveries with ``win_prob_before``, ``win_prob_after``,
        and ``wpa`` columns added.
    """
    df = deliveries.copy()
    _decat(
        df,
        [
            "match_id",
            "batting_team",
            "winner",
            "bowling_team",
            "batter_id",
            "batter",
            "bowler_id",
            "bowler",
        ],
    )

    n = len(df)
    wp_before = np.full(n, 0.5)
    wp_after = np.full(n, 0.5)

    # Pre-extract arrays for speed (avoid per-row DataFrame access)
    innings_arr = df["innings_num"].values
    over_arr = df["over"].values
    wkt_before_arr = df["team_wickets_before"].values
    score_before_arr = df["team_score_before"].values.astype(float)
    total_runs_arr = df["total_runs"].values.astype(float)
    is_wicket_arr = df["is_wicket"].values.astype(bool)
    target_arr = (
        pd.to_numeric(df["target_runs"], errors="coerce").fillna(0).values.astype(float)
    )

    for i in range(n):
        inn = int(innings_arr[i])
        ov = int(over_arr[i])
        wkt = int(wkt_before_arr[i])
        score = float(score_before_arr[i])
        total_runs_dlv = float(total_runs_arr[i])
        is_wkt = bool(is_wicket_arr[i])
        target = float(target_arr[i])

        # State AFTER this delivery
        score_after = score + total_runs_dlv
        wkt_after = wkt + (1 if is_wkt else 0)

        if inn == 2 and wp_model_2nd:
            wp_b = _lookup_wp_2nd(
                ov, wkt, score, target, wp_model_2nd, score_ratio_buckets
            )
            wp_a = _lookup_wp_2nd(
                ov,
                wkt_after,
                score_after,
                target,
                wp_model_2nd,
                score_ratio_buckets,
            )

            # Terminal states: chase completed or all out
            if score_after >= target and target > 0:
                wp_a = 1.0  # batting team wins
            elif wkt_after >= 10:
                wp_a = 0.0  # batting team all out

        elif inn == 1 and wp_model_1st:
            wp_b = _lookup_wp_1st(
                ov, wkt, score, wp_model_1st, par_scores_1st, rr_ratio_buckets
            )
            wp_a = _lookup_wp_1st(
                ov,
                wkt_after,
                score_after,
                wp_model_1st,
                par_scores_1st,
                rr_ratio_buckets,
            )

            # Terminal: all out in first innings (bad for batting team)
            if wkt_after >= 10:
                # Don't set to 0 — batting team can still win, just unlikely
                # Use a low but non-zero probability
                wp_a = max(wp_a, 0.10)

        else:
            # Innings 3+ (super overs etc.) — skip WPA
            wp_b = 0.5
            wp_a = 0.5

        wp_before[i] = wp_b
        wp_after[i] = wp_a

    df["win_prob_before"] = wp_before
    df["win_prob_after"] = wp_after
    df["wpa"] = df["win_prob_after"] - df["win_prob_before"]

    return apply_chase_start_win_prob_continuity(df)


def apply_chase_start_win_prob_continuity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Align the **first ball of innings 2** with the end of innings 1.

    The 2nd-innings lookup uses score/target ratio; at 0/0 that often maps to
    ~50% for the chaser, which **re-anchors** the match and contradicts the
    first-innings model's implied P(match win).

    Here: after the last ball of innings 1, ``win_prob_after`` is P(innings-1
    batting team wins). The chasing team is the opponent, so at the start of
    the chase P(chaser wins) = 1 - that value. We set that as
    ``win_prob_before`` on the **first delivery of innings 2** only and
    recompute ``wpa`` for that row. Later deliveries are unchanged.

    Innings 3+ (super overs) are not adjusted.
    """
    if df.empty:
        return df
    need = {
        "match_id",
        "innings_num",
        "over",
        "ball_idx",
        "batting_team",
        "win_prob_before",
        "win_prob_after",
        "wpa",
    }
    if not need.issubset(df.columns):
        return df

    for _, g in df.groupby("match_id", observed=True, sort=False):
        g = g.sort_values(["innings_num", "over", "ball_idx"])
        inn1 = g[g["innings_num"] == 1]
        inn2 = g[g["innings_num"] == 2]
        if inn1.empty or inn2.empty:
            continue

        last1 = inn1.iloc[-1]
        first2_idx = inn2.index[0]

        bat1 = str(last1["batting_team"])
        bat2 = str(df.loc[first2_idx, "batting_team"])
        if bat1 == bat2:
            continue

        wp1_end = float(last1["win_prob_after"])
        if not np.isfinite(wp1_end):
            continue
        wp1_end = float(np.clip(wp1_end, 0.0, 1.0))

        wp_before_chase = 1.0 - wp1_end
        wp_before_chase = float(np.clip(wp_before_chase, 0.0, 1.0))

        df.loc[first2_idx, "win_prob_before"] = wp_before_chase
        wa = float(df.loc[first2_idx, "win_prob_after"])
        if np.isfinite(wa):
            df.loc[first2_idx, "wpa"] = wa - wp_before_chase

    return df


# ───────────────────────────────────────────────────────────────────────────
# Vectorised WPA scoring (faster alternative for large datasets)
# ───────────────────────────────────────────────────────────────────────────


def compute_delivery_wpa_vectorised(
    deliveries: pd.DataFrame,
    wp_model_2nd: dict[tuple[int, int, float], float],
    wp_model_1st: dict[tuple[int, int, float], float],
    par_scores_1st: dict[tuple[int, int], float],
    *,
    score_ratio_buckets: int = _DEFAULT_SCORE_RATIO_BUCKETS,
    rr_ratio_buckets: int = _DEFAULT_FIRST_INN_SCORE_BUCKETS,
) -> pd.DataFrame:
    """
    Vectorised version of ``compute_delivery_wpa`` for better performance.

    Uses the same model but pre-computes bucket keys and does batch lookups
    instead of per-row Python loops.

    Falls back to the row-level loop for any state not found in the batch
    lookup.
    """
    df = deliveries.copy()
    _decat(
        df,
        [
            "match_id",
            "batting_team",
            "winner",
            "bowling_team",
            "batter_id",
            "batter",
            "bowler_id",
            "bowler",
        ],
    )

    target_vals = (
        pd.to_numeric(df["target_runs"], errors="coerce").fillna(0).astype(float)
    )

    # --- Second innings ---
    mask_2 = df["innings_num"] == 2
    # --- First innings ---
    mask_1 = df["innings_num"] == 1

    df["win_prob_before"] = 0.5
    df["win_prob_after"] = 0.5

    # ── 2nd innings ──
    if mask_2.any() and wp_model_2nd:
        idx2 = df.index[mask_2]
        ov2 = df.loc[idx2, "over"].clip(upper=19).astype(int)
        wkt2 = df.loc[idx2, "team_wickets_before"].clip(upper=9).astype(int)
        score2 = df.loc[idx2, "team_score_before"].astype(float)
        tgt2 = target_vals.loc[idx2]
        total_runs2 = df.loc[idx2, "total_runs"].astype(float)
        is_wkt2 = df.loc[idx2, "is_wicket"].astype(bool)

        ratio_before = np.where(tgt2 > 0, score2 / tgt2, 0.0)
        ratio_before = np.clip(ratio_before, 0.0, 1.0)
        sr_bucket_before = (
            np.round(ratio_before * score_ratio_buckets) / score_ratio_buckets
        )

        score_after2 = score2 + total_runs2
        wkt_after2 = wkt2 + is_wkt2.astype(int)
        wkt_after2 = wkt_after2.clip(upper=9)
        ratio_after = np.where(tgt2 > 0, score_after2 / tgt2, 0.0)
        ratio_after = np.clip(ratio_after, 0.0, 1.0)
        sr_bucket_after = (
            np.round(ratio_after * score_ratio_buckets) / score_ratio_buckets
        )

        wp_b_arr = np.array(
            [
                wp_model_2nd.get((int(o), int(w), float(s)), 0.5)
                for o, w, s in zip(ov2.values, wkt2.values, sr_bucket_before)
            ]
        )
        wp_a_arr = np.array(
            [
                wp_model_2nd.get((int(o), int(w), float(s)), 0.5)
                for o, w, s in zip(ov2.values, wkt_after2.values, sr_bucket_after)
            ]
        )

        # Terminal states
        chase_won = (score_after2 >= tgt2) & (tgt2 > 0)
        all_out = wkt_after2 >= 10
        wp_a_arr = np.where(chase_won, 1.0, wp_a_arr)
        wp_a_arr = np.where(all_out & ~chase_won, 0.0, wp_a_arr)

        df.loc[idx2, "win_prob_before"] = wp_b_arr
        df.loc[idx2, "win_prob_after"] = wp_a_arr

    # ── 1st innings ──
    if mask_1.any() and wp_model_1st:
        idx1 = df.index[mask_1]
        ov1 = df.loc[idx1, "over"].clip(upper=19).astype(int)
        wkt1 = df.loc[idx1, "team_wickets_before"].clip(upper=9).astype(int)
        score1 = df.loc[idx1, "team_score_before"].astype(float)
        total_runs1 = df.loc[idx1, "total_runs"].astype(float)
        is_wkt1 = df.loc[idx1, "is_wicket"].astype(bool)

        # Par scores lookup
        par1 = np.array(
            [
                max(par_scores_1st.get((int(o), int(w)), 1.0), 1.0)
                for o, w in zip(ov1.values, wkt1.values)
            ]
        )

        rr_ratio_before = np.clip(score1.values / par1, 0.0, 2.0)
        rr_bucket_before = (
            np.round((rr_ratio_before / 2.0) * rr_ratio_buckets) / rr_ratio_buckets
        )

        score_after1 = score1 + total_runs1
        wkt_after1 = wkt1 + is_wkt1.astype(int)
        wkt_after1 = wkt_after1.clip(upper=9)

        par_after = np.array(
            [
                max(par_scores_1st.get((int(o), int(w)), 1.0), 1.0)
                for o, w in zip(ov1.values, wkt_after1.values)
            ]
        )

        rr_ratio_after = np.clip(score_after1.values / par_after, 0.0, 2.0)
        rr_bucket_after = (
            np.round((rr_ratio_after / 2.0) * rr_ratio_buckets) / rr_ratio_buckets
        )

        wp_b_arr1 = np.array(
            [
                wp_model_1st.get((int(o), int(w), float(s)), 0.5)
                for o, w, s in zip(ov1.values, wkt1.values, rr_bucket_before)
            ]
        )
        wp_a_arr1 = np.array(
            [
                wp_model_1st.get((int(o), int(w), float(s)), 0.5)
                for o, w, s in zip(ov1.values, wkt_after1.values, rr_bucket_after)
            ]
        )

        df.loc[idx1, "win_prob_before"] = wp_b_arr1
        df.loc[idx1, "win_prob_after"] = wp_a_arr1

    df["wpa"] = df["win_prob_after"] - df["win_prob_before"]

    return apply_chase_start_win_prob_continuity(df)


# ───────────────────────────────────────────────────────────────────────────
# Step 3: Aggregate WPA per player
# ───────────────────────────────────────────────────────────────────────────


def aggregate_batting_wpa(
    wpa_deliveries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate delivery-level WPA into career batting WPA stats.

    Only counts deliveries where the batter actually faced the ball
    (``is_batter_ball == True``).

    Columns produced
    ----------------
    - ``career_wpa_bat`` : Total WPA (sum). Positive = net match-winner.
    - ``positive_wpa_bat`` : Sum of positive-only WPA.
    - ``negative_wpa_bat`` : Sum of negative-only WPA.
    - ``wpa_matches_bat`` : Number of matches with WPA data.
    - ``wpa_per_match_bat`` : career_wpa / matches.
    - ``wpa_per_ball_bat`` : career_wpa / balls_faced.
    - ``clutch_wpa_pct_bat`` : positive_wpa / (positive + |negative|).
      A value > 0.5 means more positive contributions than negative.
    """
    df = wpa_deliveries.copy()
    _decat(df, ["batter_id", "batter"])

    # Only batter-faced balls
    faced = df[df["is_batter_ball"] == True].copy()  # noqa: E712
    if faced.empty:
        return pd.DataFrame()

    faced["positive_wpa"] = faced["wpa"].clip(lower=0.0)
    faced["negative_wpa"] = faced["wpa"].clip(upper=0.0)

    grp = faced.groupby(["batter_id", "batter"], observed=True)

    agg = grp.agg(
        career_wpa_bat=("wpa", "sum"),
        positive_wpa_bat=("positive_wpa", "sum"),
        negative_wpa_bat=("negative_wpa", "sum"),
        wpa_balls_bat=("wpa", "count"),
        wpa_matches_bat=("match_id", "nunique"),
    ).reset_index()

    agg["wpa_per_match_bat"] = np.where(
        agg["wpa_matches_bat"] > 0,
        agg["career_wpa_bat"] / agg["wpa_matches_bat"],
        0.0,
    )
    agg["wpa_per_ball_bat"] = np.where(
        agg["wpa_balls_bat"] > 0,
        agg["career_wpa_bat"] / agg["wpa_balls_bat"],
        0.0,
    )

    # Clutch WPA percentage: fraction of total absolute WPA that is positive
    total_abs = agg["positive_wpa_bat"] + agg["negative_wpa_bat"].abs()
    agg["clutch_wpa_pct_bat"] = np.where(
        total_abs > 0,
        agg["positive_wpa_bat"] / total_abs,
        0.5,
    )

    # Round
    for c in [
        "career_wpa_bat",
        "positive_wpa_bat",
        "negative_wpa_bat",
        "wpa_per_match_bat",
        "wpa_per_ball_bat",
        "clutch_wpa_pct_bat",
    ]:
        agg[c] = agg[c].round(6)

    return agg.sort_values("career_wpa_bat", ascending=False).reset_index(drop=True)


def aggregate_bowling_wpa(
    wpa_deliveries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate delivery-level WPA into career bowling WPA stats.

    For bowlers, *negative* WPA (from the batting team's perspective) is a
    good thing — the bowler reduced the batting team's chance of winning.
    We negate the sign so that positive ``career_wpa_bowl`` = good bowler.

    Columns produced
    ----------------
    - ``career_wpa_bowl`` : Total WPA contribution (sign-flipped; positive = good).
    - ``positive_wpa_bowl`` : Sum of positive bowling WPA contributions.
    - ``negative_wpa_bowl`` : Sum of negative bowling WPA contributions.
    - ``wpa_matches_bowl`` : Number of matches.
    - ``wpa_per_match_bowl`` : career_wpa_bowl / matches.
    - ``wpa_per_ball_bowl`` : career_wpa_bowl / legal balls bowled.
    """
    df = wpa_deliveries.copy()
    _decat(df, ["bowler_id", "bowler"])

    if df.empty or "wpa" not in df.columns:
        return pd.DataFrame()

    # Bowling WPA = negative of batting WPA (bowler helps when batting team's
    # win prob decreases)
    df["bowl_wpa"] = -df["wpa"]
    df["positive_bowl_wpa"] = df["bowl_wpa"].clip(lower=0.0)
    df["negative_bowl_wpa"] = df["bowl_wpa"].clip(upper=0.0)

    grp = df.groupby(["bowler_id", "bowler"], observed=True)

    agg = grp.agg(
        career_wpa_bowl=("bowl_wpa", "sum"),
        positive_wpa_bowl=("positive_bowl_wpa", "sum"),
        negative_wpa_bowl=("negative_bowl_wpa", "sum"),
        wpa_balls_bowl=("is_legal", "sum"),
        wpa_matches_bowl=("match_id", "nunique"),
    ).reset_index()

    agg["wpa_per_match_bowl"] = np.where(
        agg["wpa_matches_bowl"] > 0,
        agg["career_wpa_bowl"] / agg["wpa_matches_bowl"],
        0.0,
    )
    agg["wpa_per_ball_bowl"] = np.where(
        agg["wpa_balls_bowl"] > 0,
        agg["career_wpa_bowl"] / agg["wpa_balls_bowl"],
        0.0,
    )

    for c in [
        "career_wpa_bowl",
        "positive_wpa_bowl",
        "negative_wpa_bowl",
        "wpa_per_match_bowl",
        "wpa_per_ball_bowl",
    ]:
        agg[c] = agg[c].round(6)

    return agg.sort_values("career_wpa_bowl", ascending=False).reset_index(drop=True)


# ───────────────────────────────────────────────────────────────────────────
# Match-level WPA (for single-match detail views)
# ───────────────────────────────────────────────────────────────────────────


def compute_match_wpa_summary(
    wpa_deliveries: pd.DataFrame,
    match_id: str,
) -> dict[str, pd.DataFrame]:
    """
    Extract per-player WPA for a single match.

    Useful for match summary pages showing who were the key contributors.

    Returns
    -------
    dict with:
        ``batting_wpa`` : per-batter WPA in this match
        ``bowling_wpa`` : per-bowler WPA in this match
        ``wpa_timeline`` : ball-by-ball win probability curve
    """
    df = wpa_deliveries[wpa_deliveries["match_id"] == match_id].copy()
    _decat(df, ["batter_id", "batter", "bowler_id", "bowler"])

    if df.empty:
        empty = pd.DataFrame()
        return {
            "batting_wpa": empty,
            "bowling_wpa": empty,
            "wpa_timeline": empty,
        }

    # Batting WPA per player
    bat_faced = df[df["is_batter_ball"] == True]  # noqa: E712
    bat_wpa = (
        bat_faced.groupby(["batter_id", "batter", "innings_num"], observed=True)
        .agg(
            wpa=("wpa", "sum"),
            balls=("wpa", "count"),
            runs=("batter_runs", "sum"),
        )
        .reset_index()
        .sort_values("wpa", ascending=False)
    )

    # Bowling WPA per player (sign-flipped)
    bowl_wpa = df.copy()
    bowl_wpa["bowl_wpa"] = -bowl_wpa["wpa"]
    bowl_wpa = (
        bowl_wpa.groupby(["bowler_id", "bowler", "innings_num"], observed=True)
        .agg(
            wpa=("bowl_wpa", "sum"),
            balls=("is_legal", "sum"),
        )
        .reset_index()
        .sort_values("wpa", ascending=False)
    )

    # Timeline
    timeline = df[
        ["innings_num", "over", "win_prob_before", "win_prob_after", "wpa"]
    ].copy()
    timeline["ball_number"] = range(1, len(timeline) + 1)

    return {
        "batting_wpa": bat_wpa,
        "bowling_wpa": bowl_wpa,
        "wpa_timeline": timeline,
    }


# ───────────────────────────────────────────────────────────────────────────
# Delivery-level win probability (shared by WPA aggregates + scorecards)
# ───────────────────────────────────────────────────────────────────────────


def score_deliveries_win_probability(
    deliveries: pd.DataFrame,
    *,
    score_ratio_buckets: int = _DEFAULT_SCORE_RATIO_BUCKETS,
    rr_ratio_buckets: int = _DEFAULT_FIRST_INN_SCORE_BUCKETS,
    use_vectorised: bool = True,
) -> pd.DataFrame:
    """
    Build WP models from ``deliveries`` and return a copy with
    ``win_prob_before``, ``win_prob_after``, and ``wpa`` per row.

    Used for per-match scorecard JSON (GUI charts) and as the first stage
    of the full WPA pipeline.
    """
    wp_model_2nd = build_second_innings_wp_model(
        deliveries,
        score_ratio_buckets=score_ratio_buckets,
    )
    wp_model_1st, par_scores_1st = build_first_innings_wp_model(
        deliveries,
        rr_ratio_buckets=rr_ratio_buckets,
    )
    if use_vectorised:
        return compute_delivery_wpa_vectorised(
            deliveries,
            wp_model_2nd,
            wp_model_1st,
            par_scores_1st,
            score_ratio_buckets=score_ratio_buckets,
            rr_ratio_buckets=rr_ratio_buckets,
        )
    return compute_delivery_wpa(
        deliveries,
        wp_model_2nd,
        wp_model_1st,
        par_scores_1st,
        score_ratio_buckets=score_ratio_buckets,
        rr_ratio_buckets=rr_ratio_buckets,
    )


# ───────────────────────────────────────────────────────────────────────────
# Convenience wrapper (called from main.py)
# ───────────────────────────────────────────────────────────────────────────


def compute_all_wpa_metrics(
    deliveries: pd.DataFrame,
    *,
    score_ratio_buckets: int = _DEFAULT_SCORE_RATIO_BUCKETS,
    rr_ratio_buckets: int = _DEFAULT_FIRST_INN_SCORE_BUCKETS,
    use_vectorised: bool = True,
) -> dict[str, Any]:
    """
    Run the full WPA pipeline: build models → score deliveries → aggregate.

    Parameters
    ----------
    deliveries : pd.DataFrame
        Raw delivery-level DataFrame from the parser.
    score_ratio_buckets : int
        Buckets for the 2nd-innings score/target ratio.
    rr_ratio_buckets : int
        Buckets for the 1st-innings run-rate ratio.
    use_vectorised : bool
        If True, use the vectorised scorer (faster). If False, use the
        row-by-row scorer (slower but with full fallback logic).

    Returns
    -------
    dict with keys:
        ``wpa_deliveries`` : pd.DataFrame — deliveries with wpa column
        ``batting_wpa`` : pd.DataFrame — career batting WPA
        ``bowling_wpa`` : pd.DataFrame — career bowling WPA
        ``wp_model_2nd`` : dict — 2nd innings WP model
        ``wp_model_1st`` : dict — 1st innings WP model
        ``par_scores_1st`` : dict — 1st innings par scores
    """
    wp_model_2nd = build_second_innings_wp_model(
        deliveries,
        score_ratio_buckets=score_ratio_buckets,
    )
    wp_model_1st, par_scores_1st = build_first_innings_wp_model(
        deliveries,
        rr_ratio_buckets=rr_ratio_buckets,
    )
    if use_vectorised:
        wpa_df = compute_delivery_wpa_vectorised(
            deliveries,
            wp_model_2nd,
            wp_model_1st,
            par_scores_1st,
            score_ratio_buckets=score_ratio_buckets,
            rr_ratio_buckets=rr_ratio_buckets,
        )
    else:
        wpa_df = compute_delivery_wpa(
            deliveries,
            wp_model_2nd,
            wp_model_1st,
            par_scores_1st,
            score_ratio_buckets=score_ratio_buckets,
            rr_ratio_buckets=rr_ratio_buckets,
        )

    batting_wpa = aggregate_batting_wpa(wpa_df)
    bowling_wpa = aggregate_bowling_wpa(wpa_df)

    return {
        "wpa_deliveries": wpa_df,
        "batting_wpa": batting_wpa,
        "bowling_wpa": bowling_wpa,
        "wp_model_2nd": wp_model_2nd,
        "wp_model_1st": wp_model_1st,
        "par_scores_1st": par_scores_1st,
    }
