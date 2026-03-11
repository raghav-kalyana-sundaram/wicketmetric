"""
Positional WAR (Wins Above Replacement) — cricWAR Implementation.

Built on the Expected Value (xR) framework from algorithm_update.md.
WAR is the ultimate cumulative metric of a player's value, consolidating
batting, bowling, and all-rounder impact into a single universal currency:
wins.

Architecture (per algorithm_update.md)
--------------------------------------
1. **Context-Adjusted Runs Above Average (RAA)**: Raw run values from the
   xR model are adjusted for Leverage Index, venue, and opposition quality.
   The residual represents isolated skill contribution.

2. **Replacement Level**: Defined as the 20th percentile of international
   players within a specific role and format — NOT the global average.
   A replacement player represents a fringe domestic / bench player.

3. **Runs Per Win Converter**: A dynamic scalar representing the number of
   runs required to alter the outcome of a match by one full win in a
   specific era and format.  Computed from historical match data as:
       RPW = avg_total_runs_per_match / 2
   This allows batting, bowling, and all-rounder impact to be consolidated
   into wins.

4. **Volume Factor**: WAR is cumulative.  More innings = more total value.
   Uses log-scaling to prevent extreme counts from dominating.

Key outputs
-----------
- **Batting WAR**: Leveraged runs above replacement → wins.
  Components: WAR for Acceleration, Power, and Control, plus combined.
- **Bowling WAR**: Leveraged runs saved above replacement → wins.
  Components: WAR for Accuracy, Control, and Threat, plus combined.
- **All-Rounder WAR**: Vector magnitude in (Batting WAR, Bowling WAR)
  space with balance penalty — rewards true dual-threat players.

Design
------
- Replacement level is the Nth percentile (default: 20th per algorithm doc)
  of the raw component z-scores within each position/phase group.
- Value above replacement = max(raw_score − replacement_level, 0).
- The Runs Per Win converter dynamically adapts to era and format.
- All functions are pure — DataFrames in, DataFrames out.

Integration
-----------
Called from ``main.py`` after the rating system and gates have been applied.
The ``raw_*`` columns and ``position_group``/``phase_group`` columns must
already be present on the career DataFrames.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────

# Reference innings/matches for volume scaling.
# log1p(50) ≈ 3.93.  A player with 50 innings gets volume factor = 1.0.
# Players with more get >1.0 (diminishing), fewer get <1.0.
_VOLUME_REFERENCE_BAT = 50
_VOLUME_REFERENCE_BOWL = 50

# Batting raw component columns used for WAR
_BAT_RAW_COLS = ["raw_acceleration", "raw_power", "raw_control"]

# Bowling raw component columns used for WAR
_BOWL_RAW_COLS = ["raw_accuracy", "raw_control", "raw_threat"]

# Minimum group size — if a position/phase group has fewer players than
# this, we fall back to the overall population for replacement level.
_MIN_GROUP_SIZE = 5

# Default Runs Per Win — how many runs of value equate to one win.
# Dynamically recalculated from match data when available.
# For T20I: typical match total ~300 runs across both innings, so RPW ≈ 150.
_DEFAULT_RUNS_PER_WIN_T20 = 150.0

# Replacement percentile — per algorithm_update.md, the 20th percentile
# of international players within a role represents a fringe/bench player.
_DEFAULT_REPLACEMENT_PERCENTILE = 0.20


# ──────────────────────────────────────────────────────────────────────────
# 0. Runs Per Win Converter
# ──────────────────────────────────────────────────────────────────────────


def compute_runs_per_win(
    match_context: pd.DataFrame | None = None,
    *,
    default_rpw: float = _DEFAULT_RUNS_PER_WIN_T20,
) -> float:
    """
    Compute the dynamic Runs Per Win (RPW) converter from match data.

    Per algorithm_update.md: RPW is a dynamic scalar representing the number
    of runs required to alter the outcome of a match by one full win in a
    specific era and format.

    RPW = avg(total_runs_per_match) / 2

    This means in a typical T20I where ~300 runs are scored across both
    innings, ~150 runs of value = 1 win.

    Parameters
    ----------
    match_context : pd.DataFrame, optional
        Match-level context DataFrame with ``match_total_runs`` column.
        If None, uses the default RPW constant.
    default_rpw : float
        Fallback value if match_context is unavailable.

    Returns
    -------
    float — runs per win converter value.
    """
    if match_context is not None and "match_total_runs" in match_context.columns:
        avg_total = match_context["match_total_runs"].mean()
        if pd.notna(avg_total) and avg_total > 0:
            rpw = avg_total / 2.0
            # Sanity bounds: RPW should be between 80 and 250 for T20
            return float(np.clip(rpw, 80.0, 250.0))
    return default_rpw


# ──────────────────────────────────────────────────────────────────────────
# 0b. All-Rounder Balance Score
# ──────────────────────────────────────────────────────────────────────────


def compute_allrounder_war(
    bat_careers: pd.DataFrame,
    bowl_careers: pd.DataFrame,
    *,
    balance_penalty_scale: float = 0.15,
) -> pd.DataFrame:
    """
    Compute All-Rounder WAR using vector magnitude in 2D skill space.

    Per algorithm_update.md: the All-Rounder Value is the Euclidean distance
    from the origin in a (Batting WAR, Bowling WAR) Cartesian plane.
    A balance penalty scales with the angle relative to the 45-degree line
    (perfect balance), rewarding true dual-threat players and penalising
    those heavily skewed toward one discipline.

    This produces All-Rounder Archetypes:
    - True All-Rounder: near 45° line with high magnitude
    - Batting All-Rounder: vector skewed toward batting axis
    - Bowling All-Rounder: vector skewed toward bowling axis

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Must contain ``batter_id``, ``war_batting``.
    bowl_careers : pd.DataFrame
        Must contain ``bowler_id``, ``war_bowling``.
    balance_penalty_scale : float
        How much to penalise imbalance.  0 = no penalty, 1 = maximum.

    Returns
    -------
    pd.DataFrame with columns:
        - ``player_id`` : shared ID
        - ``war_batting`` : from batting careers
        - ``war_bowling`` : from bowling careers
        - ``war_allrounder`` : combined vector magnitude with balance penalty
        - ``allrounder_archetype`` : True/Batting/Bowling All-Rounder
        - ``balance_angle`` : angle in degrees (45 = perfect balance)
    """
    # Find players who appear in both batting and bowling careers
    bat = (
        bat_careers[["batter_id", "war_batting"]].copy().dropna(subset=["war_batting"])
    )
    bowl = (
        bowl_careers[["bowler_id", "war_bowling"]].copy().dropna(subset=["war_bowling"])
    )

    bat = bat.rename(columns={"batter_id": "player_id"})
    bowl = bowl.rename(columns={"bowler_id": "player_id"})

    for c in ["player_id"]:
        if hasattr(bat[c], "cat"):
            bat[c] = bat[c].astype(str)
        if hasattr(bowl[c], "cat"):
            bowl[c] = bowl[c].astype(str)

    merged = bat.merge(bowl, on="player_id", how="inner")

    if merged.empty:
        return pd.DataFrame(
            columns=[
                "player_id",
                "war_batting",
                "war_bowling",
                "war_allrounder",
                "allrounder_archetype",
                "balance_angle",
            ]
        )

    # Only consider players with positive WAR in both disciplines
    merged = merged[
        (merged["war_batting"] > 0.01) & (merged["war_bowling"] > 0.01)
    ].copy()

    if merged.empty:
        return pd.DataFrame(
            columns=[
                "player_id",
                "war_batting",
                "war_bowling",
                "war_allrounder",
                "allrounder_archetype",
                "balance_angle",
            ]
        )

    # Z-score normalise WAR values so batting and bowling are on same scale
    bat_mean = merged["war_batting"].mean()
    bat_std = max(merged["war_batting"].std(), 1e-10)
    bowl_mean = merged["war_bowling"].mean()
    bowl_std = max(merged["war_bowling"].std(), 1e-10)

    z_bat = (merged["war_batting"] - bat_mean) / bat_std
    z_bowl = (merged["war_bowling"] - bowl_mean) / bowl_std

    # Vector magnitude (Euclidean distance from origin)
    magnitude = np.sqrt(z_bat**2 + z_bowl**2)

    # Balance angle: 45° = perfect balance, 0° = pure batting, 90° = pure bowling
    angle_rad = np.arctan2(z_bowl.clip(lower=0.01), z_bat.clip(lower=0.01))
    angle_deg = np.degrees(angle_rad)

    # Balance penalty: scales with deviation from 45° line
    deviation_from_balance = np.abs(angle_deg - 45.0) / 45.0  # 0 to 1
    balance_factor = 1.0 - balance_penalty_scale * deviation_from_balance

    merged["war_allrounder"] = (magnitude * balance_factor).clip(lower=0.0)
    merged["balance_angle"] = angle_deg

    # Archetype classification
    merged["allrounder_archetype"] = np.where(
        np.abs(angle_deg - 45.0) <= 15.0,
        "True All-Rounder",
        np.where(angle_deg < 30.0, "Batting All-Rounder", "Bowling All-Rounder"),
    )

    return merged[
        [
            "player_id",
            "war_batting",
            "war_bowling",
            "war_allrounder",
            "allrounder_archetype",
            "balance_angle",
        ]
    ]


# ──────────────────────────────────────────────────────────────────────────
# 1. Batting WAR
# ──────────────────────────────────────────────────────────────────────────


def compute_batting_war(
    bat_careers: pd.DataFrame,
    replacement_percentile: float = _DEFAULT_REPLACEMENT_PERCENTILE,
    volume_reference: int = _VOLUME_REFERENCE_BAT,
    raw_cols: list[str] | None = None,
    group_col: str = "position_group",
    innings_col: str = "innings_count",
    runs_per_win: float | None = None,
    match_context: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Compute cricWAR (Wins Above Replacement) for batters.

    Per algorithm_update.md:
        1. Context-adjusted runs above replacement are calculated from the
           raw z-score composites, adjusted for Leverage Index.
        2. Replacement baseline = 20th percentile within position group.
        3. Accumulated runs above replacement are divided by the Runs Per Win
           converter to produce wins.

    WAR = sum(value_above_replacement_per_component) × volume_factor / RPW_scaling

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Career-level batting DataFrame.  Must contain ``raw_acceleration``,
        ``raw_power``, ``raw_control``, ``position_group``, and
        ``innings_count`` columns (plus ``batter_id`` and ``batter``).
    replacement_percentile : float
        Percentile (0–1) defining replacement level within each group.
        Default 0.20 (20th percentile per algorithm_update.md).
    volume_reference : int
        Reference innings count for volume scaling.
    raw_cols : list[str], optional
        Override the raw component columns.
    group_col : str
        Column containing the grouping (default ``"position_group"``).
    innings_col : str
        Column containing the innings count for volume scaling.
    runs_per_win : float, optional
        The RPW converter.  If None, computed from match_context or uses
        the default constant.
    match_context : pd.DataFrame, optional
        Match-level context for computing dynamic RPW.

    Returns
    -------
    pd.DataFrame
        Copy of ``bat_careers`` with additional columns:
        - ``war_acceleration``, ``war_power``, ``war_control`` — per-component WAR
        - ``war_batting`` — combined WAR (in wins)
        - ``raa_batting`` — Runs Above Average (z-score composite × volume)
        - ``volume_factor_bat`` — the volume multiplier used
        - ``runs_per_win`` — the RPW converter used
        - ``replacement_level_acceleration``, etc. — the replacement thresholds
    """
    if raw_cols is None:
        raw_cols = list(_BAT_RAW_COLS)

    df = bat_careers.copy()

    # ── Compute Runs Per Win converter ──
    if runs_per_win is None:
        rpw = compute_runs_per_win(match_context)
    else:
        rpw = runs_per_win
    df["runs_per_win"] = rpw

    # ── Validate required columns ──
    required = raw_cols + [group_col, innings_col]
    missing = [c for c in required if c not in df.columns]
    if missing or df.empty:
        for rc in raw_cols:
            short = rc.replace("raw_", "")
            df[f"war_{short}"] = np.nan
            df[f"replacement_level_{short}"] = np.nan
        df["war_batting"] = np.nan
        df["raa_batting"] = np.nan
        df["volume_factor_bat"] = np.nan
        return df

    # ── Compute replacement level per group, per component ──
    for metric in raw_cols:
        short_name = metric.replace("raw_", "")
        repl_col = f"replacement_level_{short_name}"
        var_col = f"{metric}_above_replacement"

        pop_replacement = df[metric].quantile(replacement_percentile)

        replacement_values = df.groupby(group_col)[metric].transform(
            lambda x: (
                x.quantile(replacement_percentile)
                if len(x) >= _MIN_GROUP_SIZE
                else pop_replacement
            )
        )

        df[repl_col] = replacement_values
        df[var_col] = (df[metric] - df[repl_col]).clip(lower=0.0)

    # ── Volume factor ──
    ref_log = np.log1p(volume_reference)
    if ref_log < 1e-12:
        ref_log = 1.0
    df["volume_factor_bat"] = (
        np.log1p(df[innings_col].fillna(0).astype(float)) / ref_log
    )

    # ── Leverage multiplier ──
    # If average leverage is available from xR scoring, use it to scale WAR.
    # High-leverage performers get a boost; low-leverage stat-padders get
    # reduced WAR.  Falls back to 1.0 if not available.
    if "avg_leverage" in df.columns:
        leverage_mult = df["avg_leverage"].fillna(1.0).clip(lower=0.5, upper=2.0)
    else:
        leverage_mult = 1.0

    # ── Combined WAR with Runs Per Win conversion ──
    war_components = []
    for metric in raw_cols:
        short_name = metric.replace("raw_", "")
        var_col = f"{metric}_above_replacement"
        war_col = f"war_{short_name}"
        # WAR = value_above_replacement × volume × leverage / RPW_normaliser
        # We normalise by a reference RPW so that the z-score-based values
        # produce sensible win values (typically 0-5 range for elite players).
        rpw_normaliser = max(rpw / _DEFAULT_RUNS_PER_WIN_T20, 0.5)
        df[war_col] = (
            df[var_col] * df["volume_factor_bat"] * leverage_mult / rpw_normaliser
        )
        war_components.append(war_col)

    df["war_batting"] = df[war_components].sum(axis=1)

    # ── Runs Above Average (RAA) ──
    # Per algorithm_update.md: the residual represents isolated skill
    # contribution, forming the basis of the RAA calculation.
    # RAA = sum(raw_composites) × volume_factor (not replacement-adjusted)
    raa_components = [df[rc].fillna(0.0) for rc in raw_cols]
    df["raa_batting"] = sum(raa_components) * df["volume_factor_bat"] * leverage_mult

    # ── Clean up intermediate columns ──
    for metric in raw_cols:
        var_col = f"{metric}_above_replacement"
        if var_col in df.columns:
            df.drop(columns=[var_col], inplace=True)

    return df


# ──────────────────────────────────────────────────────────────────────────
# 2. Bowling WAR
# ──────────────────────────────────────────────────────────────────────────


def compute_bowling_war(
    bowl_careers: pd.DataFrame,
    replacement_percentile: float = _DEFAULT_REPLACEMENT_PERCENTILE,
    volume_reference: int = _VOLUME_REFERENCE_BOWL,
    raw_cols: list[str] | None = None,
    group_col: str = "phase_group",
    matches_col: str = "matches",
    runs_per_win: float | None = None,
    match_context: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Compute cricWAR (Wins Above Replacement) for bowlers.

    Same methodology as batting WAR but using bowling components and
    ``phase_group`` for grouping.  Uses the same Runs Per Win converter.

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Career-level bowling DataFrame.  Must contain ``raw_accuracy``,
        ``raw_control``, ``raw_threat``, ``phase_group``, and ``matches``.
    replacement_percentile : float
        Percentile (0–1) defining replacement level within each group.
        Default 0.20 per algorithm_update.md.
    volume_reference : int
        Reference match count for volume scaling.
    raw_cols : list[str], optional
        Override the raw component columns.
    group_col : str
        Column for grouping (default ``"phase_group"``).
    matches_col : str
        Column for volume scaling (default ``"matches"``).
    runs_per_win : float, optional
        The RPW converter.  If None, computed from match_context.
    match_context : pd.DataFrame, optional
        Match-level context for computing dynamic RPW.

    Returns
    -------
    pd.DataFrame
        Copy of ``bowl_careers`` with additional columns:
        - ``war_accuracy``, ``war_control``, ``war_threat`` — per-component WAR
        - ``war_bowling`` — combined WAR (in wins)
        - ``raa_bowling`` — Runs Above Average
        - ``volume_factor_bowl`` — the volume multiplier used
        - ``runs_per_win`` — the RPW converter used
        - ``replacement_level_accuracy``, etc. — the replacement thresholds
    """
    if raw_cols is None:
        raw_cols = list(_BOWL_RAW_COLS)

    df = bowl_careers.copy()

    # ── Compute Runs Per Win converter ──
    if runs_per_win is None:
        rpw = compute_runs_per_win(match_context)
    else:
        rpw = runs_per_win
    df["runs_per_win"] = rpw

    # ── Validate required columns ──
    required = raw_cols + [group_col, matches_col]
    missing = [c for c in required if c not in df.columns]
    if missing or df.empty:
        for rc in raw_cols:
            short = rc.replace("raw_", "")
            df[f"war_{short}"] = np.nan
            df[f"replacement_level_{short}"] = np.nan
        df["war_bowling"] = np.nan
        df["raa_bowling"] = np.nan
        df["volume_factor_bowl"] = np.nan
        return df

    # ── Compute replacement level per group, per component ──
    for metric in raw_cols:
        short_name = metric.replace("raw_", "")
        repl_col = f"replacement_level_{short_name}"
        var_col = f"{metric}_above_replacement"

        pop_replacement = df[metric].quantile(replacement_percentile)

        replacement_values = df.groupby(group_col)[metric].transform(
            lambda x: (
                x.quantile(replacement_percentile)
                if len(x) >= _MIN_GROUP_SIZE
                else pop_replacement
            )
        )

        df[repl_col] = replacement_values
        df[var_col] = (df[metric] - df[repl_col]).clip(lower=0.0)

    # ── Volume factor ──
    ref_log = np.log1p(volume_reference)
    if ref_log < 1e-12:
        ref_log = 1.0
    df["volume_factor_bowl"] = (
        np.log1p(df[matches_col].fillna(0).astype(float)) / ref_log
    )

    # ── Leverage multiplier for bowlers ──
    if "avg_leverage_bowl" in df.columns:
        leverage_mult = df["avg_leverage_bowl"].fillna(1.0).clip(lower=0.5, upper=2.0)
    else:
        leverage_mult = 1.0

    # ── Combined WAR with Runs Per Win conversion ──
    war_components = []
    for metric in raw_cols:
        short_name = metric.replace("raw_", "")
        var_col = f"{metric}_above_replacement"
        war_col = f"war_{short_name}"
        rpw_normaliser = max(rpw / _DEFAULT_RUNS_PER_WIN_T20, 0.5)
        df[war_col] = (
            df[var_col] * df["volume_factor_bowl"] * leverage_mult / rpw_normaliser
        )
        war_components.append(war_col)

    df["war_bowling"] = df[war_components].sum(axis=1)

    # ── Runs Above Average (RAA) ──
    raa_components = [df[rc].fillna(0.0) for rc in raw_cols]
    df["raa_bowling"] = sum(raa_components) * df["volume_factor_bowl"] * leverage_mult

    # ── Clean up intermediate columns ──
    for metric in raw_cols:
        var_col = f"{metric}_above_replacement"
        if var_col in df.columns:
            df.drop(columns=[var_col], inplace=True)

    return df


# ──────────────────────────────────────────────────────────────────────────
# 3. WAR Ranking Helpers
# ──────────────────────────────────────────────────────────────────────────


def war_batting_leaderboard(
    bat_careers: pd.DataFrame,
    top_n: int = 25,
    exclude_provisional: bool = True,
) -> pd.DataFrame:
    """
    Produce a ranked WAR leaderboard for batters.

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Must have ``war_batting`` column (output of ``compute_batting_war``).
    top_n : int
        Number of top players to return.
    exclude_provisional : bool
        If True, exclude provisional players from the leaderboard.

    Returns
    -------
    pd.DataFrame
        Top-N batters sorted by ``war_batting`` descending, with rank column.
    """
    if "war_batting" not in bat_careers.columns:
        return pd.DataFrame()

    df = bat_careers.copy()

    if exclude_provisional and "is_provisional_bat" in df.columns:
        df = df[~df["is_provisional_bat"]].copy()

    df = df.dropna(subset=["war_batting"])
    df = df.nlargest(top_n, "war_batting").copy()
    df["war_rank"] = range(1, len(df) + 1)

    # Select relevant columns
    cols = ["war_rank", "batter_id", "batter"]
    if "country" in df.columns:
        cols.append("country")
    if "position_group" in df.columns:
        cols.append("position_group")
    cols.extend(
        [
            "innings_count",
            "war_acceleration",
            "war_power",
            "war_control",
            "war_batting",
        ]
    )
    available = [c for c in cols if c in df.columns]
    return df[available].reset_index(drop=True)


def war_bowling_leaderboard(
    bowl_careers: pd.DataFrame,
    top_n: int = 25,
    exclude_provisional: bool = True,
) -> pd.DataFrame:
    """
    Produce a ranked WAR leaderboard for bowlers.

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Must have ``war_bowling`` column (output of ``compute_bowling_war``).
    top_n : int
        Number of top players to return.
    exclude_provisional : bool
        If True, exclude provisional players from the leaderboard.

    Returns
    -------
    pd.DataFrame
        Top-N bowlers sorted by ``war_bowling`` descending, with rank column.
    """
    if "war_bowling" not in bowl_careers.columns:
        return pd.DataFrame()

    df = bowl_careers.copy()

    if exclude_provisional and "is_provisional_bowl" in df.columns:
        df = df[~df["is_provisional_bowl"]].copy()

    df = df.dropna(subset=["war_bowling"])
    df = df.nlargest(top_n, "war_bowling").copy()
    df["war_rank"] = range(1, len(df) + 1)

    cols = ["war_rank", "bowler_id", "bowler"]
    if "country" in df.columns:
        cols.append("country")
    if "phase_group" in df.columns:
        cols.append("phase_group")
    cols.extend(
        [
            "matches",
            "war_accuracy",
            "war_control",
            "war_threat",
            "war_bowling",
        ]
    )
    available = [c for c in cols if c in df.columns]
    return df[available].reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────
# 4. WAR Per-Innings Rate (supplementary metric)
# ──────────────────────────────────────────────────────────────────────────


def compute_batting_war_rate(
    bat_careers: pd.DataFrame,
    innings_col: str = "innings_count",
    min_innings: int = 10,
) -> pd.DataFrame:
    """
    Compute WAR per innings — a rate metric complementing the cumulative WAR.

    This is useful for comparing players with different career lengths.
    An elite player with 20 innings and WAR 3.0 has a higher rate (0.15/inn)
    than a good player with 100 innings and WAR 5.0 (0.05/inn).

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Must have ``war_batting`` and ``innings_count`` columns.
    innings_col : str
        Column with innings count.
    min_innings : int
        Minimum innings to produce a rate (avoids noisy small-sample rates).

    Returns
    -------
    pd.DataFrame
        Copy of input with ``war_batting_rate`` column added.
    """
    df = bat_careers.copy()

    if "war_batting" not in df.columns or innings_col not in df.columns:
        df["war_batting_rate"] = np.nan
        return df

    innings = df[innings_col].fillna(0).astype(float)
    df["war_batting_rate"] = np.where(
        innings >= min_innings,
        df["war_batting"] / innings.clip(lower=1),
        np.nan,
    )

    return df


def compute_bowling_war_rate(
    bowl_careers: pd.DataFrame,
    matches_col: str = "matches",
    min_matches: int = 10,
) -> pd.DataFrame:
    """
    Compute WAR per match for bowlers — a rate metric.

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Must have ``war_bowling`` and ``matches`` columns.
    matches_col : str
        Column with match count.
    min_matches : int
        Minimum matches to produce a rate.

    Returns
    -------
    pd.DataFrame
        Copy of input with ``war_bowling_rate`` column added.
    """
    df = bowl_careers.copy()

    if "war_bowling" not in df.columns or matches_col not in df.columns:
        df["war_bowling_rate"] = np.nan
        return df

    matches = df[matches_col].fillna(0).astype(float)
    df["war_bowling_rate"] = np.where(
        matches >= min_matches,
        df["war_bowling"] / matches.clip(lower=1),
        np.nan,
    )

    return df


# ──────────────────────────────────────────────────────────────────────────
# 5. Position-Value Analysis
# ──────────────────────────────────────────────────────────────────────────


def compute_position_value_summary(
    bat_careers: pd.DataFrame,
    group_col: str = "position_group",
) -> pd.DataFrame:
    """
    Summarise WAR distribution by position group.

    Useful for understanding which positions have the deepest talent pools
    and where replacement level is hardest to beat.

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Must have ``war_batting``, ``position_group``, and raw component cols.

    Returns
    -------
    pd.DataFrame with one row per position group:
        position_group, n_players, mean_war, median_war, max_war,
        replacement_war, war_spread (max − replacement)
    """
    if "war_batting" not in bat_careers.columns or group_col not in bat_careers.columns:
        return pd.DataFrame()

    df = bat_careers.dropna(subset=["war_batting"]).copy()

    if df.empty:
        return pd.DataFrame()

    summary = (
        df.groupby(group_col)
        .agg(
            n_players=("war_batting", "size"),
            mean_war=("war_batting", "mean"),
            median_war=("war_batting", "median"),
            max_war=("war_batting", "max"),
            p25_war=("war_batting", lambda x: x.quantile(0.25)),
            p75_war=("war_batting", lambda x: x.quantile(0.75)),
            std_war=("war_batting", "std"),
        )
        .reset_index()
    )

    summary["war_spread"] = summary["max_war"] - summary["p25_war"]
    summary = summary.rename(columns={group_col: "position_group"})

    return summary.sort_values("mean_war", ascending=False).reset_index(drop=True)


def compute_phase_value_summary(
    bowl_careers: pd.DataFrame,
    group_col: str = "phase_group",
) -> pd.DataFrame:
    """
    Summarise WAR distribution by bowling phase group.

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Must have ``war_bowling`` and ``phase_group`` columns.

    Returns
    -------
    pd.DataFrame with one row per phase group.
    """
    if (
        "war_bowling" not in bowl_careers.columns
        or group_col not in bowl_careers.columns
    ):
        return pd.DataFrame()

    df = bowl_careers.dropna(subset=["war_bowling"]).copy()

    if df.empty:
        return pd.DataFrame()

    summary = (
        df.groupby(group_col)
        .agg(
            n_bowlers=("war_bowling", "size"),
            mean_war=("war_bowling", "mean"),
            median_war=("war_bowling", "median"),
            max_war=("war_bowling", "max"),
            p25_war=("war_bowling", lambda x: x.quantile(0.25)),
            p75_war=("war_bowling", lambda x: x.quantile(0.75)),
            std_war=("war_bowling", "std"),
        )
        .reset_index()
    )

    summary["war_spread"] = summary["max_war"] - summary["p25_war"]
    summary = summary.rename(columns={group_col: "phase_group"})

    return summary.sort_values("mean_war", ascending=False).reset_index(drop=True)
