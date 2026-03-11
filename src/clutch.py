"""
Clutch / Pressure Index — Feature 3

Identifies high-leverage situations in T20 cricket and measures how players
perform under pressure compared to normal conditions.  Produces a per-player
"Clutch Index" that is positive when the player elevates in pressure and
negative when they shrink.

High-leverage situations (batting):
  - Chasing a high required run rate (configurable, default >9 RPO)
  - Batting after a top-order collapse (configurable, default 3+ wickets
    down inside the powerplay)
  - Knockout / elimination matches (semi-final, final in event names)
  - Deep chase: batting in innings 2 with target_runs set and required
    runs > 50% of target remaining in the last 8 overs

High-leverage situations (bowling):
  - Defending a low total (team set ≤140 and bowling in innings 2)
  - Bowling in the death overs of a close chase (last 4 overs, margin <30)
  - Bowling in a knockout / elimination match

The Clutch Index is the difference in composite performance between
pressure innings/spells and non-pressure innings/spells:

    clutch_index = pressure_composite − normal_composite

Positive = player performs better under pressure ("clutch").
Negative = player performs worse under pressure ("choker").

Design
------
- All pressure tagging happens at the **delivery level** before being
  aggregated to innings/spell level.
- The module works on the already-computed ``bat_components`` and
  ``bowl_components`` DataFrames (post ``compute_batting_components`` /
  ``compute_bowling_components``), enriched with pressure flags.
- Config keys live under ``clutch.*`` in ``config.yaml``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import cfg

# ---------------------------------------------------------------------------
# Config constants (read once at import time; tests can override via config)
# ---------------------------------------------------------------------------

_CLUTCH_ENABLED = cfg("clutch.enabled", default=True)
_MIN_PRESSURE_INNINGS = cfg("clutch.min_pressure_innings", default=5)
_HIGH_RRR_THRESHOLD = cfg("clutch.high_rrr_threshold", default=9.0)
_COLLAPSE_WICKETS = cfg("clutch.collapse_wickets", default=3)

# Additional thresholds not yet in config (sensible defaults)
_KNOCKOUT_KEYWORDS = (
    "final",
    "semi-final",
    "semi final",
    "semifinal",
    "eliminator",
    "qualifier",
    "knockout",
    "playoff",
    "play-off",
    "play off",
)
_LOW_TOTAL_THRESHOLD = 140  # defending ≤ this is pressure for bowlers
_DEATH_CHASE_OVERS_LEFT = 8  # last N overs for "deep chase" pressure
_DEATH_CHASE_REMAINING_PCT = 0.50  # >50% of target still needed
_BOWLING_DEATH_CLOSE_MARGIN = 30  # runs margin for close-chase death bowling
_BOWLING_DEATH_OVER_START = 16  # over 16+ = last 4 overs


# ═══════════════════════════════════════════════════════════════════════════
# 1. Delivery-level pressure tagging
# ═══════════════════════════════════════════════════════════════════════════


def _is_knockout_match(event_name: pd.Series) -> pd.Series:
    """
    Return a boolean Series: True if the event name suggests a knockout match.

    Works with plain strings or categorical columns.
    """
    if hasattr(event_name, "cat"):
        event_name = event_name.astype(str)
    event_lower = event_name.fillna("").str.lower()
    mask = pd.Series(False, index=event_name.index)
    for kw in _KNOCKOUT_KEYWORDS:
        mask = mask | event_lower.str.contains(kw, regex=False)
    return mask


def tag_pressure_deliveries(
    df: pd.DataFrame,
    *,
    high_rrr_threshold: float | None = None,
    collapse_wickets: int | None = None,
) -> pd.DataFrame:
    """
    Tag each delivery with pressure flags.

    Adds columns to a **copy** of *df*:
    - ``is_pressure_high_rrr``   — chasing with required RR > threshold
    - ``is_pressure_collapse``   — 3+ wickets down in the powerplay
    - ``is_pressure_knockout``   — knockout / elimination match
    - ``is_pressure_deep_chase`` — deep in a chase, >50% of target left
    - ``is_pressure``            — any of the above

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.
    high_rrr_threshold : float, optional
        Override for required run-rate threshold (default from config).
    collapse_wickets : int, optional
        Override for powerplay collapse wicket threshold.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with pressure flag columns appended.
    """
    if high_rrr_threshold is None:
        high_rrr_threshold = _HIGH_RRR_THRESHOLD
    if collapse_wickets is None:
        collapse_wickets = _COLLAPSE_WICKETS

    out = df.copy()

    # Ensure working columns are plain types (not categorical)
    _innings_num = out["innings_num"]
    if hasattr(_innings_num, "cat"):
        _innings_num = _innings_num.astype(int)

    _event_name = (
        out["event_name"]
        if "event_name" in out.columns
        else pd.Series("", index=out.index)
    )

    _phase = out["phase"]
    if hasattr(_phase, "cat"):
        _phase = _phase.astype(str)

    # ------------------------------------------------------------------
    # Flag 1: High required run rate (2nd innings only)
    # ------------------------------------------------------------------
    # Required runs = target_runs − team_score_before
    # Remaining balls = (overs_limit × 6) − legal_ball_seq
    # Required RR = required_runs / (remaining_balls / 6)
    overs_limit = (
        out["overs_limit"].fillna(20).astype(float)
        if "overs_limit" in out.columns
        else 20.0
    )
    total_balls_in_innings = overs_limit * 6.0
    legal_ball_seq = (
        out["legal_ball_seq"].astype(float) if "legal_ball_seq" in out.columns else 0.0
    )

    target_runs = (
        pd.to_numeric(out["target_runs"], errors="coerce").astype(float)
        if "target_runs" in out.columns
        else pd.Series(np.nan, index=out.index, dtype=float)
    )
    team_score_before = (
        out["team_score_before"].astype(float)
        if "team_score_before" in out.columns
        else 0.0
    )

    required_runs = target_runs - team_score_before
    remaining_balls = total_balls_in_innings - legal_ball_seq
    remaining_overs = remaining_balls / 6.0
    required_rr = np.where(
        remaining_overs > 0,
        required_runs / remaining_overs,
        0.0,
    )

    is_chasing = (_innings_num == 2) & target_runs.notna()
    out["required_run_rate"] = np.where(is_chasing, required_rr, np.nan)
    out["is_pressure_high_rrr"] = is_chasing & (
        pd.Series(required_rr, index=out.index) > high_rrr_threshold
    )

    # ------------------------------------------------------------------
    # Flag 2: Top-order collapse (3+ wickets in the powerplay)
    # ------------------------------------------------------------------
    is_powerplay = _phase == "powerplay"
    team_wickets_before = (
        out["team_wickets_before"].astype(int)
        if "team_wickets_before" in out.columns
        else 0
    )
    out["is_pressure_collapse"] = (
        team_wickets_before >= collapse_wickets
    ) & is_powerplay

    # ------------------------------------------------------------------
    # Flag 3: Knockout / elimination match
    # ------------------------------------------------------------------
    out["is_pressure_knockout"] = _is_knockout_match(_event_name)

    # ------------------------------------------------------------------
    # Flag 4: Deep chase — innings 2, last N overs, >50% of target left
    # ------------------------------------------------------------------
    over_col = out["over"].astype(float) if "over" in out.columns else 0.0
    overs_remaining = overs_limit - over_col - 1  # 0-indexed overs
    deep_chase_start = overs_limit - _DEATH_CHASE_OVERS_LEFT
    in_death_zone = over_col >= deep_chase_start
    pct_remaining = np.where(
        target_runs > 0,
        required_runs / target_runs,
        0.0,
    )
    out["is_pressure_deep_chase"] = (
        is_chasing
        & in_death_zone
        & (pd.Series(pct_remaining, index=out.index) > _DEATH_CHASE_REMAINING_PCT)
    )

    # ------------------------------------------------------------------
    # Combined pressure flag (any of the above)
    # ------------------------------------------------------------------
    out["is_pressure"] = (
        out["is_pressure_high_rrr"]
        | out["is_pressure_collapse"]
        | out["is_pressure_knockout"]
        | out["is_pressure_deep_chase"]
    )

    return out


# ═══════════════════════════════════════════════════════════════════════════
# 2. Bowling-specific pressure tagging
# ═══════════════════════════════════════════════════════════════════════════


def tag_bowling_pressure_deliveries(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Tag deliveries with bowling-specific pressure flags.

    This EXTENDS the flags already added by ``tag_pressure_deliveries``
    (knockout is shared) with bowling-specific situations:

    - ``is_pressure_low_defend``  — defending a low total (≤140) in innings 2
    - ``is_pressure_death_close`` — death overs (16+) of a close chase (margin <30)
    - ``is_bowl_pressure``        — any bowling pressure flag

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame (should already have ``is_pressure_knockout``
        from ``tag_pressure_deliveries``).

    Returns
    -------
    pd.DataFrame
        Copy of *df* with bowling pressure columns appended.
    """
    out = df.copy()

    _innings_num = out["innings_num"]
    if hasattr(_innings_num, "cat"):
        _innings_num = _innings_num.astype(int)

    # Bowling pressure only applies in the innings the bowler bowls
    # (bowling team is in the field).  For innings 2, bowling team
    # is the team that batted first.

    # Flag A: Defending a low total
    # When bowling in innings 2, the batting team is chasing.
    # The bowler's team set a low total if target_runs <= threshold.
    target_runs = (
        pd.to_numeric(out["target_runs"], errors="coerce")
        if "target_runs" in out.columns
        else pd.Series(np.nan, index=out.index)
    )

    is_inn2 = _innings_num == 2
    out["is_pressure_low_defend"] = is_inn2 & (target_runs <= _LOW_TOTAL_THRESHOLD)

    # Flag B: Death overs of a close chase
    over_col = out["over"].astype(float) if "over" in out.columns else 0.0
    team_score_before = (
        out["team_score_before"].astype(float)
        if "team_score_before" in out.columns
        else 0.0
    )
    is_death = over_col >= _BOWLING_DEATH_OVER_START
    margin = target_runs - team_score_before
    out["is_pressure_death_close"] = (
        is_inn2
        & is_death
        & target_runs.notna()
        & (margin <= _BOWLING_DEATH_CLOSE_MARGIN)
        & (margin > 0)
    )

    # Knockout flag — reuse if already tagged, otherwise compute
    if "is_pressure_knockout" not in out.columns:
        _event_name = (
            out["event_name"]
            if "event_name" in out.columns
            else pd.Series("", index=out.index)
        )
        out["is_pressure_knockout"] = _is_knockout_match(_event_name)

    # Combined bowling pressure
    out["is_bowl_pressure"] = (
        out.get("is_pressure_knockout", pd.Series(False, index=out.index))
        | out["is_pressure_low_defend"]
        | out["is_pressure_death_close"]
    )

    return out


# ═══════════════════════════════════════════════════════════════════════════
# 3. Aggregate pressure flags to innings / spell level
# ═══════════════════════════════════════════════════════════════════════════


def aggregate_pressure_to_innings(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate delivery-level pressure flags to the innings level.

    An innings is tagged as "pressure" if **any** delivery in that innings
    was pressure, OR if >30% of deliveries faced were pressure.  This
    avoids counting an innings where a single early-chase delivery happened
    to exceed the RR threshold for one ball.

    Returns a DataFrame keyed on (match_id, innings_num, batter_id) with:
    - ``pressure_ball_pct``  — fraction of balls faced under pressure
    - ``is_pressure_innings`` — True if pressure_ball_pct > 0.30 OR knockout
    - Individual flag totals for diagnostics

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame with pressure flags (from
        ``tag_pressure_deliveries``).  Should be filtered to batter balls
        (``is_batter_ball == True``) before calling.
    """
    # Ensure we only look at balls the batter actually faced
    faced = (
        df[df["is_batter_ball"]].copy() if "is_batter_ball" in df.columns else df.copy()
    )

    for c in ["match_id", "batter_id"]:
        if c in faced.columns and hasattr(faced[c], "cat"):
            faced[c] = faced[c].astype(str)

    grp_keys = ["match_id", "innings_num", "batter_id"]

    # Ensure boolean columns exist with defaults
    for col in [
        "is_pressure",
        "is_pressure_high_rrr",
        "is_pressure_collapse",
        "is_pressure_knockout",
        "is_pressure_deep_chase",
    ]:
        if col not in faced.columns:
            faced[col] = False

    agg = (
        faced.groupby(grp_keys, observed=True)
        .agg(
            total_balls=("is_pressure", "size"),
            pressure_balls=("is_pressure", "sum"),
            high_rrr_balls=("is_pressure_high_rrr", "sum"),
            collapse_balls=("is_pressure_collapse", "sum"),
            knockout_balls=("is_pressure_knockout", "sum"),
            deep_chase_balls=("is_pressure_deep_chase", "sum"),
        )
        .reset_index()
    )

    agg["pressure_ball_pct"] = np.where(
        agg["total_balls"] > 0,
        agg["pressure_balls"] / agg["total_balls"],
        0.0,
    )

    # An innings is a "pressure innings" if:
    #  - >30% of balls were pressure, OR
    #  - it's a knockout match (all balls are pressure by definition)
    agg["is_pressure_innings"] = (agg["pressure_ball_pct"] > 0.30) | (
        agg["knockout_balls"] > 0
    )

    return agg


def aggregate_pressure_to_spells(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate delivery-level bowling pressure flags to spell level.

    Returns a DataFrame keyed on (match_id, innings_num, bowler_id) with:
    - ``bowl_pressure_ball_pct`` — fraction of balls bowled under pressure
    - ``is_pressure_spell``     — True if pressure pct > 0.30 OR knockout

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame with bowling pressure flags (from
        ``tag_bowling_pressure_deliveries``).
    """
    bowled = df.copy()

    for c in ["match_id", "bowler_id"]:
        if c in bowled.columns and hasattr(bowled[c], "cat"):
            bowled[c] = bowled[c].astype(str)

    grp_keys = ["match_id", "innings_num", "bowler_id"]

    for col in [
        "is_bowl_pressure",
        "is_pressure_knockout",
        "is_pressure_low_defend",
        "is_pressure_death_close",
    ]:
        if col not in bowled.columns:
            bowled[col] = False

    agg = (
        bowled.groupby(grp_keys, observed=True)
        .agg(
            total_balls=("is_bowl_pressure", "size"),
            pressure_balls=("is_bowl_pressure", "sum"),
            knockout_balls=("is_pressure_knockout", "sum"),
            low_defend_balls=("is_pressure_low_defend", "sum"),
            death_close_balls=("is_pressure_death_close", "sum"),
        )
        .reset_index()
    )

    agg["bowl_pressure_ball_pct"] = np.where(
        agg["total_balls"] > 0,
        agg["pressure_balls"] / agg["total_balls"],
        0.0,
    )

    agg["is_pressure_spell"] = (agg["bowl_pressure_ball_pct"] > 0.30) | (
        agg["knockout_balls"] > 0
    )

    return agg


# ═══════════════════════════════════════════════════════════════════════════
# 4. Clutch Index computation (batting)
# ═══════════════════════════════════════════════════════════════════════════


def _batting_composite(sub_df: pd.DataFrame) -> pd.Series:
    """
    Compute a simple composite score for a subset of innings.

    Uses the same acceleration/power/control sub-components that are
    already on ``bat_components`` to build a comparable composite.

    The composite is:
        0.40 × mean(acc_overall_sr)
      + 0.25 × mean(acc_impact)
      + 0.20 × mean(ctrl_scoring_consistency)
      + 0.15 × mean(ctrl_contribution)

    This deliberately parallels the main rating system's emphasis on
    context-adjusted SR, impact, and control — but uses raw means (not
    z-scored) so the difference between pressure and normal is meaningful
    on the same scale.
    """
    n = len(sub_df)
    if n == 0:
        return pd.Series(
            {
                "composite": np.nan,
                "avg_sr_vs_par": np.nan,
                "avg_impact": np.nan,
                "avg_control": np.nan,
                "avg_contribution": np.nan,
                "avg_runs": np.nan,
                "innings": 0,
            }
        )

    # Use opp_quality_weight if available for weighted means
    if "opp_quality_weight" in sub_df.columns:
        w = sub_df["opp_quality_weight"].fillna(1.0)
        w_sum = w.sum()
        if w_sum == 0:
            w = pd.Series(1.0, index=sub_df.index)
            w_sum = len(sub_df)

        def _wmean(col: str) -> float:
            vals = sub_df[col]
            mask = vals.notna()
            if mask.sum() == 0:
                return np.nan
            return float((vals[mask] * w[mask]).sum() / w[mask].sum())
    else:

        def _wmean(col: str) -> float:
            vals = sub_df[col]
            return float(vals.mean()) if vals.notna().any() else np.nan

    sr_vs_par = (
        _wmean("acc_overall_sr") if "acc_overall_sr" in sub_df.columns else np.nan
    )
    impact = _wmean("acc_impact") if "acc_impact" in sub_df.columns else np.nan
    control = (
        _wmean("ctrl_scoring_consistency")
        if "ctrl_scoring_consistency" in sub_df.columns
        else np.nan
    )
    contrib = (
        _wmean("ctrl_contribution") if "ctrl_contribution" in sub_df.columns else np.nan
    )
    avg_runs = float(sub_df["runs"].mean()) if "runs" in sub_df.columns else np.nan

    # Fill NaN components with 0 for composite computation
    _sr = sr_vs_par if pd.notna(sr_vs_par) else 0.0
    _imp = impact if pd.notna(impact) else 0.0
    _ctrl = control if pd.notna(control) else 0.0
    _con = contrib if pd.notna(contrib) else 0.0

    composite = 0.40 * _sr + 0.25 * _imp + 0.20 * _ctrl + 0.15 * _con

    return pd.Series(
        {
            "composite": composite,
            "avg_sr_vs_par": sr_vs_par,
            "avg_impact": impact,
            "avg_control": control,
            "avg_contribution": contrib,
            "avg_runs": avg_runs,
            "innings": n,
        }
    )


def compute_clutch_index(
    bat_components: pd.DataFrame,
    pressure_innings: pd.DataFrame,
    *,
    min_pressure_innings: int | None = None,
) -> pd.DataFrame:
    """
    Compute the batting Clutch Index for each batter.

    Clutch Index = pressure composite − normal composite

    A positive value means the batter performs **better** under pressure;
    negative means they perform worse.

    Parameters
    ----------
    bat_components : pd.DataFrame
        Output of ``compute_batting_components()`` — one row per
        (match, innings, batter) with ``acc_overall_sr``, ``acc_impact``,
        ``ctrl_scoring_consistency``, ``ctrl_contribution``, etc.
    pressure_innings : pd.DataFrame
        Output of ``aggregate_pressure_to_innings()`` — keyed on
        (match_id, innings_num, batter_id) with ``is_pressure_innings``.
    min_pressure_innings : int, optional
        Minimum number of pressure innings required to compute the index.
        Defaults to config value (5).

    Returns
    -------
    pd.DataFrame
        One row per (batter_id, batter) with columns:
        - ``pressure_innings``     — count of pressure innings
        - ``normal_innings``       — count of non-pressure innings
        - ``pressure_composite``   — composite under pressure
        - ``normal_composite``     — composite in normal conditions
        - ``clutch_index``         — pressure − normal (positive = clutch)
        - ``pressure_avg_sr_vs_par``   — avg SR vs par under pressure
        - ``normal_avg_sr_vs_par``     — avg SR vs par in normal
        - ``pressure_avg_runs``    — avg runs per innings under pressure
        - ``normal_avg_runs``      — avg runs per innings in normal
    """
    if min_pressure_innings is None:
        min_pressure_innings = _MIN_PRESSURE_INNINGS

    bc = bat_components.copy()
    pi = pressure_innings.copy()

    for c in ["batter_id", "batter", "match_id"]:
        if c in bc.columns and hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)
    for c in ["batter_id", "match_id"]:
        if c in pi.columns and hasattr(pi[c], "cat"):
            pi[c] = pi[c].astype(str)

    # Merge pressure flag onto bat_components
    merge_keys = ["match_id", "innings_num", "batter_id"]
    bc = bc.merge(
        pi[merge_keys + ["is_pressure_innings", "pressure_ball_pct"]],
        on=merge_keys,
        how="left",
    )
    bc["is_pressure_innings"] = bc["is_pressure_innings"].fillna(False)

    pressure = bc[bc["is_pressure_innings"]]
    normal = bc[~bc["is_pressure_innings"]]

    # Group by batter and compute composites for each condition
    results = []
    for (bid, bname), grp in bc.groupby(["batter_id", "batter"]):
        p_sub = grp[grp["is_pressure_innings"]]
        n_sub = grp[~grp["is_pressure_innings"]]

        p_stats = _batting_composite(p_sub)
        n_stats = _batting_composite(n_sub)

        results.append(
            {
                "batter_id": bid,
                "batter": bname,
                "pressure_innings": int(p_stats["innings"]),
                "normal_innings": int(n_stats["innings"]),
                "pressure_composite": p_stats["composite"],
                "normal_composite": n_stats["composite"],
                "pressure_avg_sr_vs_par": p_stats["avg_sr_vs_par"],
                "normal_avg_sr_vs_par": n_stats["avg_sr_vs_par"],
                "pressure_avg_impact": p_stats["avg_impact"],
                "normal_avg_impact": n_stats["avg_impact"],
                "pressure_avg_runs": p_stats["avg_runs"],
                "normal_avg_runs": n_stats["avg_runs"],
            }
        )

    if not results:
        return pd.DataFrame(
            columns=[
                "batter_id",
                "batter",
                "pressure_innings",
                "normal_innings",
                "pressure_composite",
                "normal_composite",
                "clutch_index",
                "pressure_avg_sr_vs_par",
                "normal_avg_sr_vs_par",
                "pressure_avg_runs",
                "normal_avg_runs",
            ]
        )

    df_out = pd.DataFrame(results)

    # Clutch Index: only computed when enough pressure innings exist
    has_enough = df_out["pressure_innings"] >= min_pressure_innings
    df_out["clutch_index"] = np.where(
        has_enough,
        df_out["pressure_composite"] - df_out["normal_composite"],
        np.nan,
    )

    # Also compute a "clutch SR delta" (purely SR-based, easier to interpret)
    df_out["clutch_sr_delta"] = np.where(
        has_enough,
        df_out["pressure_avg_sr_vs_par"].fillna(0)
        - df_out["normal_avg_sr_vs_par"].fillna(0),
        np.nan,
    )

    return df_out


# ═══════════════════════════════════════════════════════════════════════════
# 5. Clutch Index computation (bowling)
# ═══════════════════════════════════════════════════════════════════════════


def _bowling_composite(sub_df: pd.DataFrame) -> pd.Series:
    """
    Compute a simple bowling composite for a subset of spells.

    Uses components already on ``bowl_components``:
        0.35 × mean(acc_economy_vs_par)     — economy vs par (lower = better, already inverted)
      + 0.30 × mean(acc_dot_pct)            — dot ball pct
      + 0.35 × mean(threat_wickets)         — wickets taken

    Note: For bowling, LOWER economy is better.  ``acc_economy_vs_par``
    is already coded so that positive = better (economy below par), so
    higher composite = better bowling.
    """
    n = len(sub_df)
    if n == 0:
        return pd.Series(
            {
                "composite": np.nan,
                "avg_economy_vs_par": np.nan,
                "avg_dot_pct": np.nan,
                "avg_wickets": np.nan,
                "spells": 0,
            }
        )

    # Use spell-level weighting if available
    if "opp_quality_weight" in sub_df.columns:
        w = sub_df["opp_quality_weight"].fillna(1.0)
        w_sum = w.sum()
        if w_sum == 0:
            w = pd.Series(1.0, index=sub_df.index)
            w_sum = len(sub_df)

        def _wmean(col: str) -> float:
            vals = sub_df[col]
            mask = vals.notna()
            if mask.sum() == 0:
                return np.nan
            return float((vals[mask] * w[mask]).sum() / w[mask].sum())
    else:

        def _wmean(col: str) -> float:
            vals = sub_df[col]
            return float(vals.mean()) if vals.notna().any() else np.nan

    econ = (
        _wmean("acc_economy_vs_par")
        if "acc_economy_vs_par" in sub_df.columns
        else np.nan
    )
    dot_pct = _wmean("acc_dot_pct") if "acc_dot_pct" in sub_df.columns else np.nan
    wickets = float(sub_df["wickets"].mean()) if "wickets" in sub_df.columns else np.nan

    _e = econ if pd.notna(econ) else 0.0
    _d = dot_pct if pd.notna(dot_pct) else 0.0
    _w = wickets if pd.notna(wickets) else 0.0

    composite = 0.35 * _e + 0.30 * _d + 0.35 * _w

    return pd.Series(
        {
            "composite": composite,
            "avg_economy_vs_par": econ,
            "avg_dot_pct": dot_pct,
            "avg_wickets": wickets,
            "spells": n,
        }
    )


def compute_bowling_clutch_index(
    bowl_components: pd.DataFrame,
    pressure_spells: pd.DataFrame,
    *,
    min_pressure_spells: int | None = None,
) -> pd.DataFrame:
    """
    Compute the bowling Clutch Index for each bowler.

    Clutch Index = pressure composite − normal composite
    Positive = bowler performs better under pressure.

    Parameters
    ----------
    bowl_components : pd.DataFrame
        Output of ``compute_bowling_components()``.
    pressure_spells : pd.DataFrame
        Output of ``aggregate_pressure_to_spells()``.
    min_pressure_spells : int, optional
        Minimum pressure spells required.  Defaults to config value (5).

    Returns
    -------
    pd.DataFrame
        One row per (bowler_id, bowler) with clutch metrics.
    """
    if min_pressure_spells is None:
        min_pressure_spells = _MIN_PRESSURE_INNINGS  # reuse same threshold

    bc = bowl_components.copy()
    ps = pressure_spells.copy()

    for c in ["bowler_id", "bowler", "match_id"]:
        if c in bc.columns and hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)
    for c in ["bowler_id", "match_id"]:
        if c in ps.columns and hasattr(ps[c], "cat"):
            ps[c] = ps[c].astype(str)

    merge_keys = ["match_id", "innings_num", "bowler_id"]
    bc = bc.merge(
        ps[merge_keys + ["is_pressure_spell", "bowl_pressure_ball_pct"]],
        on=merge_keys,
        how="left",
    )
    bc["is_pressure_spell"] = bc["is_pressure_spell"].fillna(False)

    results = []
    for (bid, bname), grp in bc.groupby(["bowler_id", "bowler"]):
        p_sub = grp[grp["is_pressure_spell"]]
        n_sub = grp[~grp["is_pressure_spell"]]

        p_stats = _bowling_composite(p_sub)
        n_stats = _bowling_composite(n_sub)

        results.append(
            {
                "bowler_id": bid,
                "bowler": bname,
                "pressure_spells": int(p_stats["spells"]),
                "normal_spells": int(n_stats["spells"]),
                "pressure_composite_bowl": p_stats["composite"],
                "normal_composite_bowl": n_stats["composite"],
                "pressure_avg_economy_vs_par": p_stats["avg_economy_vs_par"],
                "normal_avg_economy_vs_par": n_stats["avg_economy_vs_par"],
                "pressure_avg_wickets": p_stats["avg_wickets"],
                "normal_avg_wickets": n_stats["avg_wickets"],
            }
        )

    if not results:
        return pd.DataFrame(
            columns=[
                "bowler_id",
                "bowler",
                "pressure_spells",
                "normal_spells",
                "pressure_composite_bowl",
                "normal_composite_bowl",
                "clutch_index_bowl",
            ]
        )

    df_out = pd.DataFrame(results)

    has_enough = df_out["pressure_spells"] >= min_pressure_spells
    df_out["clutch_index_bowl"] = np.where(
        has_enough,
        df_out["pressure_composite_bowl"] - df_out["normal_composite_bowl"],
        np.nan,
    )

    return df_out


# ═══════════════════════════════════════════════════════════════════════════
# 6. Convenience wrapper
# ═══════════════════════════════════════════════════════════════════════════


def compute_all_clutch_metrics(
    deliveries: pd.DataFrame,
    bat_components: pd.DataFrame,
    bowl_components: pd.DataFrame,
    *,
    min_pressure_innings: int | None = None,
    min_pressure_spells: int | None = None,
    high_rrr_threshold: float | None = None,
    collapse_wickets: int | None = None,
) -> dict[str, pd.DataFrame]:
    """
    One-call convenience wrapper that runs the full clutch pipeline.

    Parameters
    ----------
    deliveries : pd.DataFrame
        Raw delivery-level DataFrame from the parser.
    bat_components : pd.DataFrame
        Output of ``compute_batting_components()``.
    bowl_components : pd.DataFrame
        Output of ``compute_bowling_components()``.
    min_pressure_innings : int, optional
        Override for minimum pressure innings threshold.
    min_pressure_spells : int, optional
        Override for minimum pressure spells threshold.
    high_rrr_threshold : float, optional
        Override for high required run rate threshold.
    collapse_wickets : int, optional
        Override for powerplay collapse wicket threshold.

    Returns
    -------
    dict with keys:
        - ``pressure_deliveries``  — enriched delivery DataFrame with flags
        - ``pressure_innings``     — innings-level pressure aggregation
        - ``pressure_spells``      — spell-level pressure aggregation
        - ``batting_clutch``       — per-batter clutch index
        - ``bowling_clutch``       — per-bowler clutch index
    """
    # Step 1: Tag deliveries with pressure flags
    tagged = tag_pressure_deliveries(
        deliveries,
        high_rrr_threshold=high_rrr_threshold,
        collapse_wickets=collapse_wickets,
    )
    tagged = tag_bowling_pressure_deliveries(tagged)

    # Step 2: Aggregate to innings / spell level
    pressure_innings = aggregate_pressure_to_innings(tagged)
    pressure_spells = aggregate_pressure_to_spells(tagged)

    # Step 3: Compute clutch indices
    batting_clutch = compute_clutch_index(
        bat_components,
        pressure_innings,
        min_pressure_innings=min_pressure_innings,
    )

    bowling_clutch = compute_bowling_clutch_index(
        bowl_components,
        pressure_spells,
        min_pressure_spells=min_pressure_spells,
    )

    return {
        "pressure_deliveries": tagged,
        "pressure_innings": pressure_innings,
        "pressure_spells": pressure_spells,
        "batting_clutch": batting_clutch,
        "bowling_clutch": bowling_clutch,
    }
