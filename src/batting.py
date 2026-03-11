"""
Batting metrics: Acceleration, Power, Control.

Built on the Expected Value (xR) framework from algorithm_update.md.
Every delivery is scored against a state-space baseline (expected runs per
ball given phase, wickets, venue difficulty).  The difference between actual
and expected outcomes — Run Value Added (RVA) — is the fundamental unit of
player evaluation.

Pipeline
--------
0. merge_player_identities       – Deduplicate players with split profiles
                                   (different registry IDs for the same person)
                                   using a curated alias table plus heuristics.
1. compute_bowler_strength_index – Compute a per-bowler career strength score
                                   from raw delivery data (economy, dot %,
                                   strike rate).  Independent of batting ratings
                                   so there is no circular dependency.
1b. compute_team_quality         – Compute team strength from win rates,
                                   weighted by opponent quality (iterative).
                                   Used to weight innings so performances
                                   against strong teams matter more.
2. extract_batting_innings       – Per (match, batter) innings summaries from
                                   delivery-level data, including phase splits,
                                   SR progression, entry situation, team
                                   contribution context, opposition bowling
                                   quality, and team quality weighting.
3. compute_batting_components    – Raw sub-component scores per innings for each
                                   of the three metrics.  NOW integrates xR-based
                                   Run Value Added, CABI (Context-Adjusted Boundary
                                   Index), and Expected Survival Rate.
4. aggregate_batting_careers     – Career-level aggregation with opposition-
                                   quality-weighted AND team-quality-weighted
                                   means across all innings, plus volume
                                   scaling for innings played.

Metric Dimensions (per algorithm_update.md)
-------------------------------------------
**Acceleration** — A batter's capacity to increase scoring rate as their
innings progresses.  Measured via GAM-inspired spline derivative of the
cumulative runs curve, plus xR-based runs above expected.

**Power** — Context-Adjusted Boundary Index (CABI): actual boundaries vs
expected boundaries given phase, venue boundary rates, and wickets situation.
Isolates raw clearing-the-boundary ability independent of ground size.

**Control** — Expected Survival Rate (xSR): hazard-model-based survival
analysis.  High control batters display significantly lower hazard rates
across long ball sequences.  Properly handles not-out (censored) innings
via the hazard model.

Design notes
------------
- Every metric is context-adjusted via the xR model and match_par_sr so a
  130 SR in 2008 (when par was ~120) is valued the same as a 165 SR in
  2024 (when par is ~155).
- Phase-specific par rates are used: powerplay, middle, and death overs each
  have their own par SR computed from the match, so death-over acceleration
  isn't compared against overall match par.
- **Run Value Added (RVA)** from the xR model is now a primary component of
  Acceleration, replacing pure SR-based metrics where possible.
- **CABI** replaces raw boundary % for Power — boundaries are valued relative
  to the expected boundary rate for the match state, penalizing flat-track
  bullies and rewarding those who clear the ropes in tough conditions.
- **Expected Survival Rate** replaces simple batting average for Control —
  the hazard model naturally handles not-out innings (censored data) and
  measures true dismissal resistance relative to the baseline hazard.
- Leverage Index from the WP model weights high-pressure deliveries more
  heavily, so runs scored in critical moments contribute more to ratings.
- Opposition bowling quality weights each innings during career aggregation.
  An innings against a strong bowling attack counts more than one against
  a weak attack.
- Team quality weights innings: playing against teams with high win rates
  against good opponents is valued more.
- Volume scaling: players with more innings get a meaningful bonus via
  increased confidence multiplier.  A 19-innings player cannot match
  a 50-innings player's scores all else being equal.
- All sub-components are z-score normalised before compositing so that each
  component contributes proportionally to its weight, regardless of its
  natural scale.  This eliminates the need for magic scaling constants.
- Phase stats require a minimum number of balls faced (MIN_PHASE_BALLS)
  to be considered valid; otherwise they are treated as missing and do not
  contribute to the composite.
"""

import numpy as np
import pandas as pd

from src.config import cfg

# Recency / time-decay constants
RECENCY_ENABLED: bool = cfg("recency.enabled", default=True)
RECENCY_HALF_LIFE_DAYS: float = cfg("recency.half_life_days", default=730.0)
RECENCY_MIN_WEIGHT: float = cfg("recency.min_weight", default=0.05)

# ---------------------------------------------------------------------------
# Constants — all read from config.yaml (with hardcoded fallbacks)
# ---------------------------------------------------------------------------

# Minimum balls faced in a phase for that phase's stats to be considered
# reliable for a single innings.  Below this, phase SR / dot% etc. are NaN.
MIN_PHASE_BALLS: int = cfg("pipeline.min_phase_balls_batting", default=4)

# ---------------------------------------------------------------------------
# Batting position-group comparisons
# ---------------------------------------------------------------------------
# Batters are z-scored within their position group so that finishers (6-7)
# are compared to other finishers, openers (1-3) to other openers, etc.
# This prevents a finisher batting at the death with SR 125 from appearing
# similar to an opener with SR 136 — the finisher's SR is below-par for
# their role while the opener's is above-par.

POSITION_GROUPS_ENABLED: bool = cfg("batting_position_groups.enabled", default=True)
MIN_POSITION_GROUP_SIZE: int = cfg("batting_position_groups.min_group_size", default=20)

# Blend weight for within-group vs population z-scores.
# α = 1.0 → pure within-group (old behaviour, cross-group incomparable)
# α = 0.0 → pure population (no position adjustment at all)
# α = 0.6 → 60% within-group + 40% population (recommended)
#
# The blend prevents a top-order batter who is average *for an opener* from
# scoring near-zero on Power while a middle-order batter with identical raw
# stats scores in the 90s because they're above-average *for middle-order*.
GROUP_ZSCORE_BLEND_ALPHA: float = cfg(
    "batting_position_groups.blend_alpha", default=0.6
)

_raw_pos_groups: dict = cfg(
    "batting_position_groups.groups",
    default={
        1: "top_order",
        2: "top_order",
        3: "top_order",
        4: "upper_middle",
        5: "upper_middle",
        6: "lower_middle",
        7: "lower_middle",
        8: "lower_order",
        9: "lower_order",
        10: "tail",
        11: "tail",
    },
)
POSITION_GROUP_MAP: dict[int, str] = {
    int(k): str(v) for k, v in _raw_pos_groups.items()
}

_raw_merge_fallback: dict = cfg(
    "batting_position_groups.merge_fallback",
    default={"tail": "lower_order", "lower_order": "lower_middle"},
)
POSITION_GROUP_MERGE_FALLBACK: dict[str, str] = {
    str(k): str(v) for k, v in _raw_merge_fallback.items()
}

# Canonical ordering of position groups (for merge fallback logic)
POSITION_GROUP_ORDER: list[str] = [
    "top_order",
    "upper_middle",
    "lower_middle",
    "lower_order",
    "tail",
]


def classify_position_group(position: int) -> str:
    """Map a batting position (1-11) to a position group name."""
    return POSITION_GROUP_MAP.get(position, "lower_middle")


def _determine_modal_position(innings_df: pd.DataFrame) -> pd.DataFrame:
    """
    Determine each batter's modal (most frequent) batting position.

    Returns a DataFrame with columns: batter_id, batter, modal_position, position_group.
    """
    pos_counts = (
        innings_df.groupby(["batter_id", "batter", "batting_position"])
        .size()
        .reset_index(name="count")
    )

    # Modal position = position with the most innings appearances
    modal = (
        pos_counts.sort_values("count", ascending=False)
        .drop_duplicates(subset=["batter_id", "batter"], keep="first")
        .rename(columns={"batting_position": "modal_position"})
    )[["batter_id", "batter", "modal_position"]]

    modal["position_group"] = modal["modal_position"].apply(classify_position_group)
    return modal


def _grouped_zscore(
    career_df: pd.DataFrame,
    col: str,
    group_col: str = "position_group",
    min_group_size: int = MIN_POSITION_GROUP_SIZE,
    blend_alpha: float = GROUP_ZSCORE_BLEND_ALPHA,
) -> pd.Series:
    """
    Blended z-score: within-group + population, weighted by ``blend_alpha``.

    Pure within-group z-scoring (the old behaviour) makes scores
    incomparable across position groups.  A top-order batter who is
    *average for an opener* on boundary% gets z ≈ 0, while a middle-order
    batter with identical raw boundary% can get z ≈ +1.2 because
    middle-order batters hit fewer boundaries on average.  This caused
    V Kohli (top_order, IPL) to score Power=28 while RG Sharma
    (upper_middle, similar raw stats) scored Power=96.

    The fix is a **weighted blend** of within-group and population z-scores::

        blended = α × within_group_z + (1 − α) × population_z

    With α = 0.6 (default):
    - Still rewards players who are strong *relative to their position*
    - But also accounts for absolute performance level vs the full pool
    - Prevents near-zero scores for players who are merely "average for
      their (high-performing) position group"

    Falls back to pure population z-score for groups smaller than
    ``min_group_size``.

    Parameters
    ----------
    career_df : pd.DataFrame
        Career-level DataFrame with the column to z-score and a group column.
    col : str
        Column name to z-score.
    group_col : str
        Column name containing group labels.
    min_group_size : int
        Minimum group size; smaller groups use population-wide z-score.
    blend_alpha : float
        Weight for within-group z-score.  0.0 = pure population,
        1.0 = pure within-group (old behaviour).

    Returns
    -------
    pd.Series of blended z-scored values, same index as career_df.
    """
    result = pd.Series(np.nan, index=career_df.index)
    values = career_df[col]

    # Population-wide z-score (always computed — used as blend component
    # and as fallback for small groups)
    pop_zscore = _zscore_series(values)

    group_sizes = career_df[group_col].value_counts()

    for group_name, group_idx in career_df.groupby(group_col).groups.items():
        if group_sizes.get(group_name, 0) >= min_group_size:
            group_data = values.loc[group_idx]
            within_z = _zscore_series(group_data)
            pop_z = pop_zscore.loc[group_idx]
            # Blend: α × within-group + (1 − α) × population
            result.loc[group_idx] = blend_alpha * within_z + (1.0 - blend_alpha) * pop_z
        else:
            # Fallback to population-wide z-score for small groups
            result.loc[group_idx] = pop_zscore.loc[group_idx]

    # Fill any remaining NaN (shouldn't happen but safety net)
    result = result.fillna(pop_zscore)
    return result


# ---------------------------------------------------------------------------
# Player identity merging (deduplication)
# ---------------------------------------------------------------------------

# Curated alias table: maps secondary registry IDs to the canonical ID.
# Built by cross-referencing team, stats, and known Cricsheet data issues.
# Key = secondary (duplicate) batter_id, Value = canonical batter_id.
#
# To add a new merge, add to player_aliases in config.yaml:
#   player_aliases:
#     "secondary_id": "canonical_id"
PLAYER_ALIASES: dict[str, str] = cfg("player_aliases", default={})

# Name-preference table: when merging, keep this display name.
# Key = canonical batter_id, Value = preferred display name.
PLAYER_NAME_OVERRIDES: dict[str, str] = cfg("player_name_overrides", default={})


def merge_player_identities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate players with split profiles in the delivery-level DataFrame.

    Uses the curated ``PLAYER_ALIASES`` table to merge secondary registry IDs
    into canonical IDs.  Also applies ``PLAYER_NAME_OVERRIDES`` so the
    preferred display name is used.

    Additionally runs heuristic detection: flags potential duplicates where
    the same surname appears on the same team with non-overlapping date
    ranges, similar batting positions, etc.  These are logged as warnings
    but NOT auto-merged (to avoid false positives).

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.

    Returns
    -------
    pd.DataFrame with aliased IDs replaced.
    """
    if not PLAYER_ALIASES:
        return df

    df = df.copy()

    # Remap batter_id
    for col_id, col_name in [
        ("batter_id", "batter"),
        ("bowler_id", "bowler"),
        ("non_striker_id", "non_striker"),
        ("player_out_id", "player_out"),
    ]:
        if col_id not in df.columns:
            continue
        id_series = df[col_id]
        if hasattr(id_series, "cat"):
            id_series = id_series.astype(str)

        mapped = id_series.map(PLAYER_ALIASES)
        mask = mapped.notna()
        if mask.any():
            df.loc[mask, col_id] = mapped[mask]

    # Apply name overrides
    for col_id, col_name in [("batter_id", "batter"), ("bowler_id", "bowler")]:
        if col_id not in df.columns or not PLAYER_NAME_OVERRIDES:
            continue
        id_series = df[col_id]
        if hasattr(id_series, "cat"):
            id_series = id_series.astype(str)
        for canonical_id, preferred_name in PLAYER_NAME_OVERRIDES.items():
            mask = id_series == canonical_id
            if mask.any():
                df.loc[mask, col_name] = preferred_name

    return df


def detect_potential_duplicates(df: pd.DataFrame, min_innings: int = 5) -> pd.DataFrame:
    """
    Heuristic duplicate detection.  Returns a DataFrame of suspected pairs.

    Looks for players with:
    - Same surname (last word of name)
    - Same primary team
    - Non-overlapping match dates
    - Both having at least ``min_innings`` innings

    This is informational — results should be manually reviewed and confirmed
    duplicates added to PLAYER_ALIASES.

    Returns
    -------
    pd.DataFrame with columns: id_a, name_a, id_b, name_b, team, reason
    """
    work = df.copy()
    for c in ["batter_id", "batter", "batting_team", "match_id"]:
        if hasattr(work[c], "cat"):
            work[c] = work[c].astype(str)

    # Get per-batter summary
    batter_summary = (
        work[work["is_batter_ball"]]
        .groupby(["batter_id", "batter", "batting_team"])
        .agg(
            innings=("match_id", "nunique"),
            first_date=("date", "min"),
            last_date=("date", "max"),
            matches=("match_id", lambda x: set(x)),
        )
        .reset_index()
    )

    batter_summary = batter_summary[batter_summary["innings"] >= min_innings]
    batter_summary["surname"] = batter_summary["batter"].str.split().str[-1]

    suspects = []
    for (surname, team), group in batter_summary.groupby(["surname", "batting_team"]):
        if len(group) < 2:
            continue
        ids = group["batter_id"].tolist()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                row_a = group[group["batter_id"] == ids[i]].iloc[0]
                row_b = group[group["batter_id"] == ids[j]].iloc[0]
                # Check for non-overlapping match sets
                overlap = row_a["matches"] & row_b["matches"]
                if len(overlap) == 0:
                    suspects.append(
                        {
                            "id_a": ids[i],
                            "name_a": row_a["batter"],
                            "id_b": ids[j],
                            "name_b": row_b["batter"],
                            "team": team,
                            "innings_a": row_a["innings"],
                            "innings_b": row_b["innings"],
                            "reason": "same_surname_same_team_no_match_overlap",
                        }
                    )

    return (
        pd.DataFrame(suspects)
        if suspects
        else pd.DataFrame(
            columns=[
                "id_a",
                "name_a",
                "id_b",
                "name_b",
                "team",
                "innings_a",
                "innings_b",
                "reason",
            ]
        )
    )


# ---------------------------------------------------------------------------
# Team quality computation (ICC ranking-based)
# ---------------------------------------------------------------------------

# Scale factor for converting team quality z-score to innings weight.
# weight = 1 + clip(team_quality * TEAM_QUALITY_SCALE, -TEAM_QUALITY_CLIP, TEAM_QUALITY_CLIP)
TEAM_QUALITY_SCALE: float = cfg("team_quality.scale", default=0.10)
TEAM_QUALITY_CLIP: float = cfg("team_quality.clip", default=0.25)

# ---------------------------------------------------------------------------
# ICC T20I ranking-based opposition weighting
# ---------------------------------------------------------------------------
# Performances against higher-ranked teams receive more weight.
# Not all opposition is equal: scoring runs against India (ICC rating 272)
# is fundamentally harder and more meaningful than against an associate
# nation with rating 50.  The weight is computed as:
#
#   normalised = icc_rating / max_rating          (0 to 1)
#   icc_weight = floor + (ceiling - floor) * normalised ^ curve
#
# This sits alongside (and multiplies with) the existing opposition
# bowling quality weight, team quality weight, and recency weight.

ICC_RANKING_ENABLED: bool = cfg("icc_ranking.enabled", default=True)
ICC_RANKING_FLOOR: float = cfg("icc_ranking.floor", default=0.70)
ICC_RANKING_CEILING: float = cfg("icc_ranking.ceiling", default=1.20)
ICC_RANKING_CURVE: float = cfg("icc_ranking.curve", default=1.0)
ICC_RANKING_MAX_RATING: float = cfg("icc_ranking.max_rating", default=272.0)
ICC_RANKING_DEFAULT_RATING: float = cfg("icc_ranking.default_rating", default=50.0)
ICC_RANKING_RATINGS: dict[str, int] = cfg("icc_ranking.ratings", default={})

# ---------------------------------------------------------------------------
# Match quality — symmetric weight based on BOTH teams' ICC rankings
# ---------------------------------------------------------------------------
# Performances in matches between two high-ranked teams are inherently
# higher quality.  This captures the overall quality of the contest beyond
# individual opposition strength: fielding standards, depth of lineups,
# pressure of the occasion, etc.
#
# weight = floor + (ceiling - floor) * (avg_rating / max_rating) ^ curve

MATCH_QUALITY_ENABLED: bool = cfg("match_quality.enabled", default=True)
MATCH_QUALITY_FLOOR: float = cfg("match_quality.floor", default=0.75)
MATCH_QUALITY_CEILING: float = cfg("match_quality.ceiling", default=1.20)
MATCH_QUALITY_CURVE: float = cfg("match_quality.curve", default=1.3)


def compute_icc_ranking_weight(team_name: str) -> float:
    """
    Compute the ICC ranking-based innings weight for a given opposition team.

    Uses the ICC Men's T20I Team Rankings to produce a multiplicative weight
    that rewards performances against higher-ranked teams and penalises
    performances against weak/unranked opposition.

    Parameters
    ----------
    team_name : str
        The name of the opposing team (must match Cricsheet naming).

    Returns
    -------
    float
        Weight in [ICC_RANKING_FLOOR, ICC_RANKING_CEILING].
        Top teams (~270 rating) → ~1.20 (20% bonus).
        Mid-tier (~175 rating) → ~1.02 (roughly neutral).
        Low associates (~50 rating) → ~0.79.
        Unranked / unknown → ICC_RANKING_FLOOR (0.70).
    """
    rating = ICC_RANKING_RATINGS.get(team_name, ICC_RANKING_DEFAULT_RATING)
    max_r = max(ICC_RANKING_MAX_RATING, 1.0)  # avoid division by zero
    normalised = np.clip(rating / max_r, 0.0, 1.0)
    weight = ICC_RANKING_FLOOR + (ICC_RANKING_CEILING - ICC_RANKING_FLOOR) * (
        normalised**ICC_RANKING_CURVE
    )
    return float(weight)


def compute_icc_ranking_weights(teams: pd.Series) -> pd.Series:
    """
    Vectorised version: compute ICC ranking weights for a Series of team names.

    Parameters
    ----------
    teams : pd.Series
        Series of team name strings (the opposing team for each innings).

    Returns
    -------
    pd.Series of float weights, same index as input.
    """
    if not ICC_RANKING_ENABLED:
        return pd.Series(1.0, index=teams.index)

    max_r = max(ICC_RANKING_MAX_RATING, 1.0)
    ratings = teams.map(ICC_RANKING_RATINGS).fillna(ICC_RANKING_DEFAULT_RATING)
    normalised = (ratings / max_r).clip(0.0, 1.0)
    weights = ICC_RANKING_FLOOR + (ICC_RANKING_CEILING - ICC_RANKING_FLOOR) * (
        normalised**ICC_RANKING_CURVE
    )
    return weights


def compute_match_quality_weights(
    batting_teams: pd.Series,
    bowling_teams: pd.Series,
) -> pd.Series:
    """
    Compute match quality weights based on the average ICC ranking of both teams.

    A match between two top-ranked teams (e.g. India vs Australia) is
    inherently higher quality than a match between two low-ranked associates.
    This symmetric weight rewards performances in elite contests and penalises
    performances in low-quality matches.

    The weight is multiplied into the per-innings weight alongside opposition
    quality, team quality, ICC ranking, and recency.

    Parameters
    ----------
    batting_teams : pd.Series
        Series of batting team names for each innings row.
    bowling_teams : pd.Series
        Series of bowling team names for each innings row.

    Returns
    -------
    pd.Series of float weights, same index as input.
    """
    if not MATCH_QUALITY_ENABLED:
        return pd.Series(1.0, index=batting_teams.index)

    max_r = max(ICC_RANKING_MAX_RATING, 1.0)

    bat_ratings = batting_teams.map(ICC_RANKING_RATINGS).fillna(
        ICC_RANKING_DEFAULT_RATING
    )
    bowl_ratings = bowling_teams.map(ICC_RANKING_RATINGS).fillna(
        ICC_RANKING_DEFAULT_RATING
    )

    avg_rating = (bat_ratings + bowl_ratings) / 2.0
    normalised = (avg_rating / max_r).clip(0.0, 1.0)

    weights = MATCH_QUALITY_FLOOR + (MATCH_QUALITY_CEILING - MATCH_QUALITY_FLOOR) * (
        normalised**MATCH_QUALITY_CURVE
    )
    return weights


def compute_team_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute a quality index for every team using ICC T20I rankings.

    Each team that appears in the dataset is assigned its ICC rating from
    ``ICC_RANKING_RATINGS`` (configured under ``icc_ranking.ratings``).
    Teams not in the table receive ``ICC_RANKING_DEFAULT_RATING``.

    The raw ratings are then z-score normalised so that 0 = average team
    across those present in the dataset, positive = strong, negative = weak.

    This replaces the old PageRank-style iterative win-rate computation,
    which was unreliable for small samples and produced nonsensical rankings
    (e.g. Spain > India) because associate teams with a handful of wins
    against other weak associates would float to the top.

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.  Only used to discover
        which teams appear in the dataset.

    Returns
    -------
    pd.DataFrame with columns ``team`` and ``team_quality`` (z-score scale).
    """
    # Discover every team that appears in the dataset.
    teams_bat = df["batting_team"]
    teams_bowl = df["bowling_team"]
    if hasattr(teams_bat, "cat"):
        teams_bat = teams_bat.astype(str)
    if hasattr(teams_bowl, "cat"):
        teams_bowl = teams_bowl.astype(str)

    all_teams = sorted(set(teams_bat.unique()) | set(teams_bowl.unique()))

    if not all_teams:
        return pd.DataFrame(
            {"team": pd.Series(dtype=str), "team_quality": pd.Series(dtype=float)}
        )

    # Look up ICC rating for each team; default for unlisted/unranked teams.
    result = pd.DataFrame({"team": all_teams})
    result["icc_rating"] = (
        result["team"]
        .map(ICC_RANKING_RATINGS)
        .fillna(ICC_RANKING_DEFAULT_RATING)
        .astype(float)
    )

    # Z-score normalise across the teams present in the dataset.
    mean_r = result["icc_rating"].mean()
    std_r = result["icc_rating"].std()
    if pd.isna(std_r) or std_r < 1e-12:
        result["team_quality"] = 0.0
    else:
        result["team_quality"] = (result["icc_rating"] - mean_r) / std_r

    return result[["team", "team_quality"]]


# ---------------------------------------------------------------------------
# Franchise league (IPL) — season-by-season team quality from win records
# ---------------------------------------------------------------------------
# For franchise leagues like the IPL, ICC rankings are meaningless because
# the teams are franchises (Chennai Super Kings, Mumbai Indians, etc.) that
# don't appear in the ICC T20I rankings table.  Instead we compute team
# quality year-by-year from actual match results within each season.
#
# Each franchise's win rate in a given season is mapped to a rating on
# the same 0–272 scale used by ICC rankings, so existing weight formulas
# (floor/ceiling/curve) work without modification.
#
# A team that won 70%+ of matches in a season gets a top-tier rating (~260);
# a team that won ~30% gets a low rating (~120).  The mapping is:
#
#   rating = FRANCHISE_RATING_MIN
#          + (FRANCHISE_RATING_MAX - FRANCHISE_RATING_MIN)
#          * win_rate ^ FRANCHISE_RATING_CURVE

FRANCHISE_RATING_MIN: float = cfg("franchise_quality.min_rating", default=120.0)
FRANCHISE_RATING_MAX: float = cfg("franchise_quality.max_rating", default=272.0)
FRANCHISE_RATING_CURVE: float = cfg("franchise_quality.curve", default=0.7)


def compute_franchise_season_quality(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute per-team per-season quality ratings from match win records.

    For each IPL season (calendar year), computes each franchise's win rate
    and maps it to a rating on the ICC-compatible 0-272 scale.

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.  Must contain ``date``,
        ``match_id``, ``batting_team``, ``bowling_team``, and ``winner``.

    Returns
    -------
    pd.DataFrame with columns:
        - ``team`` : franchise name
        - ``season`` : int year
        - ``wins`` : number of wins in that season
        - ``matches`` : number of matches played in that season
        - ``win_rate`` : wins / matches
        - ``franchise_rating`` : rating on 0-272 scale
    """
    match_cols = ["match_id", "date", "batting_team", "bowling_team", "winner"]
    for c in match_cols:
        if c not in df.columns:
            return pd.DataFrame(
                columns=[
                    "team",
                    "season",
                    "wins",
                    "matches",
                    "win_rate",
                    "franchise_rating",
                ]
            )

    work = df[match_cols].copy()
    for c in ["batting_team", "bowling_team", "winner"]:
        if hasattr(work[c], "cat"):
            work[c] = work[c].astype(str)

    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["season"] = work["date"].dt.year

    # Deduplicate to one row per match
    matches = work.drop_duplicates(subset=["match_id"]).copy()

    # For each match, identify both teams
    team1 = matches[["match_id", "season", "batting_team", "winner"]].rename(
        columns={"batting_team": "team"}
    )
    team2 = matches[["match_id", "season", "bowling_team", "winner"]].rename(
        columns={"bowling_team": "team"}
    )
    all_team_matches = pd.concat([team1, team2], ignore_index=True).drop_duplicates(
        subset=["match_id", "team"]
    )

    all_team_matches["is_win"] = (
        all_team_matches["team"] == all_team_matches["winner"]
    ).astype(int)

    # Aggregate per team per season
    season_stats = (
        all_team_matches.groupby(["team", "season"])
        .agg(
            wins=("is_win", "sum"),
            matches=("match_id", "nunique"),
        )
        .reset_index()
    )

    season_stats["win_rate"] = np.where(
        season_stats["matches"] > 0,
        season_stats["wins"] / season_stats["matches"],
        0.5,
    )

    # Map win rate to a rating on the ICC-compatible scale.
    # Sub-linear curve (< 1) spreads out the middle and compresses extremes.
    rating_range = FRANCHISE_RATING_MAX - FRANCHISE_RATING_MIN
    season_stats["franchise_rating"] = FRANCHISE_RATING_MIN + rating_range * np.power(
        season_stats["win_rate"].clip(0.0, 1.0),
        FRANCHISE_RATING_CURVE,
    )

    return season_stats[
        ["team", "season", "wins", "matches", "win_rate", "franchise_rating"]
    ]


def compute_franchise_team_quality(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute an overall team quality index for franchise leagues.

    Aggregates per-season franchise ratings into a single quality score
    per team, with more recent seasons weighted more heavily.  Returns
    the same interface as ``compute_team_quality()`` so it can be used
    as a drop-in replacement.

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.

    Returns
    -------
    pd.DataFrame with columns ``team`` and ``team_quality`` (z-score scale).
    """
    season_quality = compute_franchise_season_quality(df)

    if season_quality.empty:
        return pd.DataFrame(
            {"team": pd.Series(dtype=str), "team_quality": pd.Series(dtype=float)}
        )

    # Weight more recent seasons more heavily (simple linear ramp)
    min_season = season_quality["season"].min()
    max_season = season_quality["season"].max()
    span = max(1, max_season - min_season)
    season_quality["recency_w"] = (
        1.0 + 0.1 * (season_quality["season"] - min_season) / span
    )

    # Weighted mean rating per team
    team_agg = (
        season_quality.groupby("team")
        .apply(
            lambda g: np.average(g["franchise_rating"], weights=g["recency_w"]),
            include_groups=False,
        )
        .reset_index(name="franchise_rating")
    )

    # Z-score normalise
    mean_r = team_agg["franchise_rating"].mean()
    std_r = team_agg["franchise_rating"].std()
    if pd.isna(std_r) or std_r < 1e-12:
        team_agg["team_quality"] = 0.0
    else:
        team_agg["team_quality"] = (team_agg["franchise_rating"] - mean_r) / std_r

    return team_agg[["team", "team_quality"]]


def compute_franchise_ranking_weights(
    teams: pd.Series,
    dates: pd.Series,
    franchise_season_ratings: pd.DataFrame,
) -> pd.Series:
    """
    Compute per-innings ranking weights using franchise season ratings.

    Drop-in replacement for ``compute_icc_ranking_weights()`` that uses
    per-team-per-season franchise ratings instead of static ICC rankings.

    Parameters
    ----------
    teams : pd.Series
        Series of opposition team names for each innings row.
    dates : pd.Series
        Series of match dates for each innings row.
    franchise_season_ratings : pd.DataFrame
        Output of ``compute_franchise_season_quality()``.  Must contain
        columns ``team``, ``season``, ``franchise_rating``.

    Returns
    -------
    pd.Series of float weights in [ICC_RANKING_FLOOR, ICC_RANKING_CEILING].
    """
    idx = teams.index

    fsr = franchise_season_ratings.copy()
    fsr["season"] = fsr["season"].astype(int)
    rating_map = dict(zip(zip(fsr["team"], fsr["season"]), fsr["franchise_rating"]))

    team_vals = teams.astype(str) if hasattr(teams, "cat") else teams
    date_vals = pd.to_datetime(dates, errors="coerce")
    seasons = date_vals.dt.year

    # Fallback: overall mean franchise rating for missing (team, season) pairs
    fallback = (
        fsr["franchise_rating"].mean() if len(fsr) > 0 else ICC_RANKING_DEFAULT_RATING
    )
    keys = list(zip(team_vals, seasons))
    ratings = pd.Series(
        [rating_map.get(k, fallback) for k in keys],
        index=idx,
        dtype=float,
    )

    max_r = max(ICC_RANKING_MAX_RATING, 1.0)
    normalised = (ratings / max_r).clip(0.0, 1.0)
    weights = ICC_RANKING_FLOOR + (ICC_RANKING_CEILING - ICC_RANKING_FLOOR) * (
        normalised**ICC_RANKING_CURVE
    )
    return weights


def compute_franchise_match_quality_weights(
    batting_teams: pd.Series,
    bowling_teams: pd.Series,
    dates: pd.Series,
    franchise_season_ratings: pd.DataFrame,
) -> pd.Series:
    """
    Compute match quality weights using franchise season ratings.

    Drop-in replacement for ``compute_match_quality_weights()``.

    Parameters
    ----------
    batting_teams, bowling_teams : pd.Series
        Series of team names for each innings row.
    dates : pd.Series
        Series of match dates for each innings row.
    franchise_season_ratings : pd.DataFrame
        Output of ``compute_franchise_season_quality()``.

    Returns
    -------
    pd.Series of float weights.
    """
    if not MATCH_QUALITY_ENABLED:
        return pd.Series(1.0, index=batting_teams.index)

    idx = batting_teams.index

    fsr = franchise_season_ratings.copy()
    fsr["season"] = fsr["season"].astype(int)
    rating_map = dict(zip(zip(fsr["team"], fsr["season"]), fsr["franchise_rating"]))

    date_vals = pd.to_datetime(dates, errors="coerce")
    seasons = date_vals.dt.year

    bat_vals = (
        batting_teams.astype(str) if hasattr(batting_teams, "cat") else batting_teams
    )
    bowl_vals = (
        bowling_teams.astype(str) if hasattr(bowling_teams, "cat") else bowling_teams
    )

    fallback = (
        fsr["franchise_rating"].mean() if len(fsr) > 0 else ICC_RANKING_DEFAULT_RATING
    )

    bat_ratings = pd.Series(
        [rating_map.get(k, fallback) for k in zip(bat_vals, seasons)],
        index=idx,
        dtype=float,
    )
    bowl_ratings = pd.Series(
        [rating_map.get(k, fallback) for k in zip(bowl_vals, seasons)],
        index=idx,
        dtype=float,
    )

    max_r = max(ICC_RANKING_MAX_RATING, 1.0)
    avg_rating = (bat_ratings + bowl_ratings) / 2.0
    normalised = (avg_rating / max_r).clip(0.0, 1.0)

    weights = MATCH_QUALITY_FLOOR + (MATCH_QUALITY_CEILING - MATCH_QUALITY_FLOOR) * (
        normalised**MATCH_QUALITY_CURVE
    )
    return weights


def compute_franchise_opp_icc_rating(
    opp_teams: pd.Series,
    dates: pd.Series,
    franchise_season_ratings: pd.DataFrame,
) -> pd.Series:
    """
    Look up per-innings franchise rating for the opposition team.

    Drop-in replacement for the ICC_RANKING_RATINGS lookup that populates
    ``opp_icc_rating`` on innings rows.

    Parameters
    ----------
    opp_teams : pd.Series
        Series of opposition team names.
    dates : pd.Series
        Series of match dates.
    franchise_season_ratings : pd.DataFrame
        Output of ``compute_franchise_season_quality()``.

    Returns
    -------
    pd.Series of float ratings on the 0-272 scale.
    """
    fsr = franchise_season_ratings.copy()
    fsr["season"] = fsr["season"].astype(int)
    rating_map = dict(zip(zip(fsr["team"], fsr["season"]), fsr["franchise_rating"]))

    team_vals = opp_teams.astype(str) if hasattr(opp_teams, "cat") else opp_teams
    date_vals = pd.to_datetime(dates, errors="coerce")
    seasons = date_vals.dt.year

    fallback = (
        fsr["franchise_rating"].mean() if len(fsr) > 0 else ICC_RANKING_DEFAULT_RATING
    )

    return pd.Series(
        [rating_map.get(k, fallback) for k in zip(team_vals, seasons)],
        index=opp_teams.index,
        dtype=float,
    )


# ---------------------------------------------------------------------------
# Step 0: Bowler strength index (opposition quality)
# ---------------------------------------------------------------------------


def compute_bowler_strength_index(
    df: pd.DataFrame,
    min_balls: int = 120,
) -> pd.DataFrame:
    """
    Compute a career-level strength index for every bowler from raw deliveries.

    This is intentionally independent of any batting ratings so there is no
    circular dependency.  It uses three raw bowling stats:

        1. Economy rate (lower is better) — inverted z-score
        2. Dot ball % (higher is better) — z-score
        3. Bowling strike rate (lower is better) — inverted z-score

    The three z-scores are averaged into a single ``bowler_strength`` value.
    Bowlers with fewer than ``min_balls`` legal deliveries are assigned the
    population mean (0.0) since we don't have enough data to judge them.

    Parameters
    ----------
    df : pd.DataFrame
        Full delivery-level DataFrame from the parser.
    min_balls : int
        Minimum legal balls bowled to be included in the strength index.
        Default 120 (~20 overs) filters out very occasional bowlers while
        keeping part-timers who bowl regularly.

    Returns
    -------
    pd.DataFrame with columns ``bowler_id`` and ``bowler_strength``.
        bowler_strength is a z-score-scale value: 0 = average,
        positive = stronger than average, negative = weaker.
    """
    # Work with plain strings for groupby
    work = df.copy()
    for c in ["bowler_id"]:
        if hasattr(work[c], "cat"):
            work[c] = work[c].astype(str)

    grp = work.groupby("bowler_id")
    career = grp.agg(
        legal_balls=("is_legal", "sum"),
        runs_conceded=("total_runs", "sum"),
        dots=("is_dot_bowler", "sum"),
        wickets=("is_wicket", "sum"),
    ).reset_index()

    # Only bowlers with enough data
    qualified = career[career["legal_balls"] >= min_balls].copy()

    if len(qualified) == 0:
        # Edge case: no qualified bowlers — return all zeros
        return pd.DataFrame({"bowler_id": career["bowler_id"], "bowler_strength": 0.0})

    overs = qualified["legal_balls"] / 6.0
    qualified["economy"] = qualified["runs_conceded"] / overs
    qualified["dot_pct"] = qualified["dots"] / qualified["legal_balls"]
    qualified["bowl_sr"] = np.where(
        qualified["wickets"] > 0,
        qualified["legal_balls"] / qualified["wickets"],
        qualified["legal_balls"].max(),  # cap for wicketless bowlers
    )

    def _zscore(s: pd.Series) -> pd.Series:
        mean, std = s.mean(), s.std()
        if pd.isna(std) or std < 1e-12:
            return pd.Series(0.0, index=s.index)
        return (s - mean) / std

    # Lower economy = better → invert
    z_econ = -_zscore(qualified["economy"])
    # Higher dot % = better
    z_dot = _zscore(qualified["dot_pct"])
    # Lower SR = better → invert
    z_sr = -_zscore(qualified["bowl_sr"])

    qualified["bowler_strength"] = (z_econ + z_dot + z_sr) / 3.0

    # Merge back: unqualified bowlers get 0.0 (population average)
    result = career[["bowler_id"]].merge(
        qualified[["bowler_id", "bowler_strength"]],
        on="bowler_id",
        how="left",
    )
    result["bowler_strength"] = result["bowler_strength"].fillna(0.0)

    return result[["bowler_id", "bowler_strength"]]


def compute_opposition_quality(
    df: pd.DataFrame,
    bowler_strength: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each (match, innings, batter), compute the average strength of the
    bowlers they faced, weighted by balls faced against each bowler.

    Returns a DataFrame keyed on (match_id, innings_num, batter_id) with
    a single column ``opposition_quality`` — a z-score-scale value where
    0 = average opposition, positive = strong opposition, negative = weak.

    This is then mapped to an innings weight via:
        weight = 1 + clip(opposition_quality * OPP_QUALITY_SCALE, -0.3, 0.3)
    so innings against elite attacks get up to 30% more weight and innings
    against weak attacks get up to 30% less weight in career aggregation.

    Parameters
    ----------
    df : pd.DataFrame
        Full delivery-level DataFrame.
    bowler_strength : pd.DataFrame
        Output of compute_bowler_strength_index().
    """
    # Only balls the batter actually faced (exclude wides)
    faced = df[df["is_batter_ball"]].copy()
    for c in ["match_id", "batter_id", "bowler_id"]:
        if hasattr(faced[c], "cat"):
            faced[c] = faced[c].astype(str)

    # Balls faced per (match, innings, batter, bowler)
    per_bowler = (
        faced.groupby(["match_id", "innings_num", "batter_id", "bowler_id"])
        .size()
        .reset_index(name="balls_vs_bowler")
    )

    # Join bowler strength
    bs = bowler_strength.copy()
    if hasattr(bs["bowler_id"], "cat"):
        bs["bowler_id"] = bs["bowler_id"].astype(str)

    per_bowler = per_bowler.merge(bs, on="bowler_id", how="left")
    per_bowler["bowler_strength"] = per_bowler["bowler_strength"].fillna(0.0)

    # Weighted average: strength weighted by balls faced against each bowler
    per_bowler["weighted_strength"] = (
        per_bowler["bowler_strength"] * per_bowler["balls_vs_bowler"]
    )

    opp_qual = (
        per_bowler.groupby(["match_id", "innings_num", "batter_id"])
        .agg(
            total_balls=("balls_vs_bowler", "sum"),
            sum_weighted_strength=("weighted_strength", "sum"),
        )
        .reset_index()
    )

    opp_qual["opposition_quality"] = np.where(
        opp_qual["total_balls"] > 0,
        opp_qual["sum_weighted_strength"] / opp_qual["total_balls"],
        0.0,
    )

    return opp_qual[["match_id", "innings_num", "batter_id", "opposition_quality"]]


# ---------------------------------------------------------------------------
# Wicket quality for bowlers: value of each dismissal by batting position
# ---------------------------------------------------------------------------

# Weight assigned to wickets based on batting position of the dismissed batter.
# Top-order (1-3) are most valuable, middle (4-6) are valuable,
# lower-middle (7-8) are moderate, tail (9-11) are low value.
_raw_position_weights: dict = cfg(
    "wicket_quality.position_weights",
    default={
        1: 1.5,
        2: 1.5,
        3: 1.4,
        4: 1.2,
        5: 1.1,
        6: 1.0,
        7: 0.8,
        8: 0.7,
        9: 0.5,
        10: 0.4,
        11: 0.3,
    },
)
# YAML may parse integer keys as int or str; normalise to int.
WICKET_POSITION_WEIGHTS: dict[int, float] = {
    int(k): float(v) for k, v in _raw_position_weights.items()
}

# Default weight for unknown positions
WICKET_POSITION_DEFAULT: float = cfg("wicket_quality.default_weight", default=0.8)


def compute_wicket_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each bowler spell (match, innings, bowler), compute the quality-weighted
    wicket count based on the batting position of dismissed batters.

    Top-order wickets (positions 1-3) are worth ~1.4-1.5× a standard wicket,
    while tailender wickets (positions 9-11) are worth ~0.3-0.5×.

    Parameters
    ----------
    df : pd.DataFrame
        Full delivery-level DataFrame from the parser.

    Returns
    -------
    pd.DataFrame keyed on (match_id, innings_num, bowler_id) with columns:
        - ``quality_wickets``: weighted wicket count
        - ``raw_wickets``: unweighted wicket count (for reference)
        - ``avg_wicket_quality``: mean quality per wicket taken
    """
    wkt_df = df[df["is_wicket"]].copy()
    for c in ["match_id", "bowler_id", "player_out_id"]:
        if c in wkt_df.columns and hasattr(wkt_df[c], "cat"):
            wkt_df[c] = wkt_df[c].astype(str)

    if len(wkt_df) == 0:
        return pd.DataFrame(
            columns=[
                "match_id",
                "innings_num",
                "bowler_id",
                "quality_wickets",
                "raw_wickets",
                "avg_wicket_quality",
            ]
        )

    # Map batting position to weight
    wkt_df["position_weight"] = (
        wkt_df["batting_position"]
        .map(WICKET_POSITION_WEIGHTS)
        .fillna(WICKET_POSITION_DEFAULT)
    )

    result = (
        wkt_df.groupby(["match_id", "innings_num", "bowler_id"])
        .agg(
            quality_wickets=("position_weight", "sum"),
            raw_wickets=("position_weight", "size"),
        )
        .reset_index()
    )

    result["avg_wicket_quality"] = np.where(
        result["raw_wickets"] > 0,
        result["quality_wickets"] / result["raw_wickets"],
        0.0,
    )

    return result


# Scale factor for converting opposition_quality z-score to an innings weight.
# weight = 1 + clip(opposition_quality * OPP_QUALITY_SCALE, -0.3, 0.3)
# With scale=0.15, a bowler strength of +2 (very strong) → weight 1.30,
# and -2 (very weak) → weight 0.70.
OPP_QUALITY_SCALE = 0.15
OPP_QUALITY_CLIP = 0.3


# ---------------------------------------------------------------------------
# Step 1: Extract per-innings batting stats from delivery-level data
# ---------------------------------------------------------------------------


def extract_batting_innings(
    df: pd.DataFrame,
    innings_ctx: pd.DataFrame,
    bowler_strength: pd.DataFrame | None = None,
    team_quality: pd.DataFrame | None = None,
    franchise_season_ratings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build one row per (match, innings, batter) with full innings statistics.

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.
    innings_ctx : pd.DataFrame
        Innings-level context from context.build_full_context().
    bowler_strength : pd.DataFrame, optional
        Output of compute_bowler_strength_index().  If provided, an
        ``opposition_quality`` column is added to each innings row
        representing the average strength of the bowlers faced.
    team_quality : pd.DataFrame, optional
        Output of compute_team_quality().  If provided, an
        ``opp_team_quality`` column is added representing the strength
        of the opposing team.

    Returns
    -------
    pd.DataFrame with columns for runs, balls, phases, SR halves, context,
    opposition_quality, and opp_team_quality.
    """

    # ── Only deliveries the batter actually faced (exclude wides) ──
    faced = df[df["is_batter_ball"]].copy()

    # We need plain string columns for grouping (categories can cause issues)
    id_cols_cat = ["match_id", "batter_id", "batter", "batting_team"]
    for c in id_cols_cat:
        if hasattr(faced[c], "cat"):
            faced[c] = faced[c].astype(str)

    # ── Per-innings aggregates ──
    grp_keys = ["match_id", "innings_num", "batter_id", "batter", "batting_team"]
    grp = faced.groupby(grp_keys, observed=True)

    agg = grp.agg(
        balls_faced=("batter_runs", "size"),
        runs=("batter_runs", "sum"),
        fours=("is_four", "sum"),
        sixes=("is_six", "sum"),
        dots=("is_dot_batter", "sum"),
        ones=("batter_runs", lambda x: (x == 1).sum()),
        twos=("batter_runs", lambda x: (x == 2).sum()),
        threes=("batter_runs", lambda x: (x == 3).sum()),
        batting_position=("batting_position", "first"),
        entry_team_score=("team_score_before", "first"),
        entry_team_wickets=("team_wickets_before", "first"),
        date=("date", "first"),
    ).reset_index()

    # ── Dismissal info ──
    dismissals = df[df["is_wicket"]].copy()
    for c in ["match_id", "player_out_id", "wicket_kind", "phase"]:
        if hasattr(dismissals[c], "cat"):
            dismissals[c] = dismissals[c].astype(str)

    dismissals = dismissals[
        [
            "match_id",
            "innings_num",
            "player_out_id",
            "wicket_kind",
            "team_score_before",
            "team_wickets_before",
            "over",
            "phase",
        ]
    ].rename(
        columns={
            "player_out_id": "batter_id",
            "wicket_kind": "how_out",
            "team_score_before": "dismissal_team_score",
            "team_wickets_before": "dismissal_team_wickets",
            "over": "dismissal_over",
            "phase": "dismissal_phase",
        }
    )

    # A batter can only be dismissed once per innings – take the first
    dismissals = dismissals.drop_duplicates(
        subset=["match_id", "innings_num", "batter_id"], keep="first"
    )

    agg = agg.merge(
        dismissals,
        on=["match_id", "innings_num", "batter_id"],
        how="left",
    )
    agg["is_out"] = agg["how_out"].notna()

    # ── Phase-level splits (powerplay / middle / death) ──
    for phase_name in ("powerplay", "middle", "death"):
        phase_df = faced[faced["phase"] == phase_name]
        phase_grp = phase_df.groupby(
            ["match_id", "innings_num", "batter_id"], observed=True
        )

        phase_agg = phase_grp.agg(
            **{
                f"{phase_name}_balls": ("batter_runs", "size"),
                f"{phase_name}_runs": ("batter_runs", "sum"),
                f"{phase_name}_dots": ("is_dot_batter", "sum"),
                f"{phase_name}_fours": ("is_four", "sum"),
                f"{phase_name}_sixes": ("is_six", "sum"),
            }
        ).reset_index()

        # Only compute phase SR if enough balls faced
        phase_agg[f"{phase_name}_sr"] = np.where(
            phase_agg[f"{phase_name}_balls"] >= MIN_PHASE_BALLS,
            phase_agg[f"{phase_name}_runs"] / phase_agg[f"{phase_name}_balls"] * 100.0,
            np.nan,
        )

        agg = agg.merge(
            phase_agg,
            on=["match_id", "innings_num", "batter_id"],
            how="left",
        )

    # ── SR in first half vs second half of the individual innings ──
    faced_sorted = faced.sort_values(
        ["match_id", "innings_num", "batter_id", "over", "ball_idx"]
    ).copy()
    faced_sorted["batter_ball_num"] = faced_sorted.groupby(
        ["match_id", "innings_num", "batter_id"], observed=True
    ).cumcount()

    balls_per_innings = faced_sorted.groupby(
        ["match_id", "innings_num", "batter_id"], observed=True
    )["batter_ball_num"].transform("count")
    faced_sorted["is_second_half"] = faced_sorted["batter_ball_num"] >= (
        balls_per_innings / 2
    )

    for is_second, label in [(False, "first_half"), (True, "second_half")]:
        half_df = faced_sorted[faced_sorted["is_second_half"] == is_second]
        half_grp = half_df.groupby(
            ["match_id", "innings_num", "batter_id"], observed=True
        )
        half_agg = half_grp.agg(
            **{
                f"{label}_balls": ("batter_runs", "size"),
                f"{label}_runs": ("batter_runs", "sum"),
            }
        ).reset_index()
        half_agg[f"{label}_sr"] = np.where(
            half_agg[f"{label}_balls"] >= MIN_PHASE_BALLS,
            half_agg[f"{label}_runs"] / half_agg[f"{label}_balls"] * 100.0,
            np.nan,
        )
        agg = agg.merge(
            half_agg,
            on=["match_id", "innings_num", "batter_id"],
            how="left",
        )

    # ── SR in first two-thirds vs final third of the individual innings ──
    # Captures gear-shifting: a batter going 50(40) → 90(60) has a final
    # third SR of ~200 vs first-two-thirds SR of ~125.  This is the
    # finishing burst that the power metric needs to reward.
    faced_sorted["is_final_third"] = faced_sorted["batter_ball_num"] >= (
        balls_per_innings * 2 / 3
    )

    for is_final, label in [(False, "first_two_thirds"), (True, "final_third")]:
        third_df = faced_sorted[faced_sorted["is_final_third"] == is_final]
        third_grp = third_df.groupby(
            ["match_id", "innings_num", "batter_id"], observed=True
        )
        third_agg = third_grp.agg(
            **{
                f"{label}_balls": ("batter_runs", "size"),
                f"{label}_runs": ("batter_runs", "sum"),
                f"{label}_sixes": ("is_six", "sum"),
                f"{label}_fours": ("is_four", "sum"),
            }
        ).reset_index()
        third_agg[f"{label}_sr"] = np.where(
            third_agg[f"{label}_balls"] >= MIN_PHASE_BALLS,
            third_agg[f"{label}_runs"] / third_agg[f"{label}_balls"] * 100.0,
            np.nan,
        )
        agg = agg.merge(
            third_agg,
            on=["match_id", "innings_num", "batter_id"],
            how="left",
        )

    # ── Overall SR ──
    agg["sr"] = np.where(
        agg["balls_faced"] > 0, agg["runs"] / agg["balls_faced"] * 100.0, 0.0
    )

    # ── Cumulative batter runs (used by Anchor Cost + Selfless Index) ──
    # Compute once; both features build on the same cumulative tracking.
    faced_sorted["cum_batter_runs"] = faced_sorted.groupby(
        ["match_id", "innings_num", "batter_id"], observed=True
    )["batter_runs"].cumsum()

    # Score BEFORE this delivery (for milestone zone classification)
    faced_sorted["score_before_ball"] = (
        faced_sorted["cum_batter_runs"] - faced_sorted["batter_runs"]
    )

    # Cumulative batter SR at each delivery
    faced_sorted["cum_batter_sr"] = np.where(
        faced_sorted["batter_ball_num"] + 1 > 0,
        faced_sorted["cum_batter_runs"] / (faced_sorted["batter_ball_num"] + 1) * 100.0,
        0.0,
    )

    # ── Anchor Cost: Balls-to-Par ──────────────────────────────────────
    # For each delivery, determine the par SR for the batter's current
    # phase and find the first ball where cumulative SR >= par.
    if ANCHOR_COST_ENABLED:
        # We need phase par for each match — compute now, merge onto
        # faced_sorted.  _compute_phase_par_sr is called below for agg
        # as well, but we need it here per-delivery.
        _anchor_phase_par = _compute_phase_par_sr(df)
        faced_sorted = faced_sorted.merge(
            _anchor_phase_par[
                ["match_id", "pp_par_sr", "middle_par_sr", "death_par_sr"]
            ],
            on="match_id",
            how="left",
        )

        # Determine the current-phase par SR for each delivery
        _phase_col = faced_sorted["phase"]
        if hasattr(_phase_col, "cat"):
            _phase_col = _phase_col.astype(str)
        faced_sorted["current_par_sr"] = np.select(
            [
                _phase_col == "powerplay",
                _phase_col == "middle",
                _phase_col == "death",
            ],
            [
                faced_sorted["pp_par_sr"],
                faced_sorted["middle_par_sr"],
                faced_sorted["death_par_sr"],
            ],
            default=faced_sorted["pp_par_sr"],
        )

        # Find first ball where cumulative SR >= current phase par
        reached_par = faced_sorted[
            faced_sorted["cum_batter_sr"] >= faced_sorted["current_par_sr"]
        ]
        balls_to_par = (
            reached_par.groupby(
                ["match_id", "innings_num", "batter_id"], observed=True
            )["batter_ball_num"]
            .first()
            .reset_index(name="balls_to_par")
        )

        agg = agg.merge(
            balls_to_par,
            on=["match_id", "innings_num", "batter_id"],
            how="left",
        )
        # Batters who NEVER reached par: set to balls_faced (worst case)
        agg["balls_to_par"] = agg["balls_to_par"].fillna(agg["balls_faced"])

        # Clean up temporary columns from faced_sorted (avoid polluting
        # downstream code if faced_sorted is reused)
        faced_sorted.drop(
            columns=["pp_par_sr", "middle_par_sr", "death_par_sr", "current_par_sr"],
            inplace=True,
            errors="ignore",
        )
    else:
        agg["balls_to_par"] = np.nan

    # ── Selfless Index: Milestone Approach Zone SRs ────────────────────
    # Track SR in the 40-49 and 90-99 run zones (approaching 50 / 100).
    if SELFLESS_ENABLED:
        _fifty_lo, _fifty_hi = SELFLESS_FIFTY_RANGE
        _cent_lo, _cent_hi = SELFLESS_CENTURY_RANGE

        for zone_name, zone_min, zone_max in [
            ("fifty_approach", _fifty_lo, _fifty_hi),
            ("century_approach", _cent_lo, _cent_hi),
        ]:
            zone_mask = (faced_sorted["score_before_ball"] >= zone_min) & (
                faced_sorted["score_before_ball"] <= zone_max
            )
            zone_df = faced_sorted[zone_mask]
            zone_agg = (
                zone_df.groupby(["match_id", "innings_num", "batter_id"], observed=True)
                .agg(
                    **{
                        f"{zone_name}_balls": ("batter_runs", "size"),
                        f"{zone_name}_runs": ("batter_runs", "sum"),
                    }
                )
                .reset_index()
            )

            zone_agg[f"{zone_name}_sr"] = np.where(
                zone_agg[f"{zone_name}_balls"] >= SELFLESS_MIN_ZONE_BALLS,
                zone_agg[f"{zone_name}_runs"] / zone_agg[f"{zone_name}_balls"] * 100.0,
                np.nan,
            )
            agg = agg.merge(
                zone_agg,
                on=["match_id", "innings_num", "batter_id"],
                how="left",
            )
    else:
        for zone_name in ("fifty_approach", "century_approach"):
            agg[f"{zone_name}_balls"] = np.nan
            agg[f"{zone_name}_runs"] = np.nan
            agg[f"{zone_name}_sr"] = np.nan

    # ── Compute phase-specific par SR from the match ──
    # This gives us PP par, middle par, death par for each match so that
    # we compare death-overs batting to death-overs par (not overall par).
    phase_par = _compute_phase_par_sr(df)
    agg = agg.merge(phase_par, on=["match_id"], how="left")

    # ── Join match / innings context ──
    ctx_cols = [
        "match_id",
        "innings_num",
        "batting_team",
        "total_runs",
        "legal_balls",
        "innings_sr",
        "match_par_sr",
        "match_par_rr",
        "match_boundary_rate",
    ]
    # Ensure join keys are plain strings
    ctx = innings_ctx.copy()
    for c in ["match_id", "batting_team"]:
        if c in ctx.columns and hasattr(ctx[c], "cat"):
            ctx[c] = ctx[c].astype(str)

    available_ctx_cols = [c for c in ctx_cols if c in ctx.columns]
    agg = agg.merge(
        ctx[available_ctx_cols],
        on=["match_id", "innings_num", "batting_team"],
        how="left",
    )

    # ── Context-adjusted metrics ──

    # SR relative to match par (ratio-based: >1 means faster than par)
    par = agg["match_par_sr"].fillna(agg["match_par_sr"].mean()).clip(lower=1)
    agg["sr_vs_par"] = agg["sr"] / par  # ratio centered at ~1.0
    agg["sr_diff_par"] = agg["sr"] - par  # difference (for backwards compat)

    # Contribution to own team's total
    agg["team_contribution_pct"] = np.where(
        agg["total_runs"] > 0,
        agg["runs"] / agg["total_runs"],
        0.0,
    )

    # Balls used as share of team's legal balls (resource usage)
    agg["balls_pct_of_team"] = np.where(
        agg["legal_balls"].fillna(0) > 0,
        agg["balls_faced"] / agg["legal_balls"],
        0.0,
    )

    # Boundary %
    agg["boundary_pct"] = np.where(
        agg["runs"] > 0,
        (agg["fours"] * 4 + agg["sixes"] * 6) / agg["runs"],
        0.0,
    )

    # Dot ball %
    agg["dot_pct"] = np.where(
        agg["balls_faced"] > 0, agg["dots"] / agg["balls_faced"], 0.0
    )

    # Rotation rate (1s + 2s per ball faced)
    agg["rotation_rate"] = np.where(
        agg["balls_faced"] > 0,
        (agg["ones"] + agg["twos"]) / agg["balls_faced"],
        0.0,
    )

    # ── Opposition bowling quality ──
    if bowler_strength is not None:
        opp_qual = compute_opposition_quality(df, bowler_strength)
        agg = agg.merge(
            opp_qual,
            on=["match_id", "innings_num", "batter_id"],
            how="left",
        )
        agg["opposition_quality"] = agg["opposition_quality"].fillna(0.0)

        # Convert to an innings weight: stronger opposition → higher weight
        agg["opp_quality_weight"] = 1.0 + np.clip(
            agg["opposition_quality"] * OPP_QUALITY_SCALE,
            -OPP_QUALITY_CLIP,
            OPP_QUALITY_CLIP,
        )
    else:
        agg["opposition_quality"] = 0.0
        agg["opp_quality_weight"] = 1.0

    # ── Team quality weighting ──
    if team_quality is not None:
        tq = team_quality.copy()
        if hasattr(tq.get("team", pd.Series()), "cat"):
            tq["team"] = tq["team"].astype(str)

        # The opposing team's quality determines the weight of this innings.
        # Get bowling_team for each innings row.
        bowling_team_map = df[
            ["match_id", "innings_num", "batting_team", "bowling_team"]
        ].drop_duplicates()
        for c in ["match_id", "batting_team", "bowling_team"]:
            if hasattr(bowling_team_map[c], "cat"):
                bowling_team_map[c] = bowling_team_map[c].astype(str)

        agg = agg.merge(
            bowling_team_map[
                ["match_id", "innings_num", "batting_team", "bowling_team"]
            ].drop_duplicates(),
            on=["match_id", "innings_num", "batting_team"],
            how="left",
        )

        agg = agg.merge(
            tq.rename(
                columns={"team": "bowling_team", "team_quality": "opp_team_quality"}
            ),
            on="bowling_team",
            how="left",
        )
        agg["opp_team_quality"] = agg["opp_team_quality"].fillna(0.0)

        # Team quality weight: stronger opponent team → higher innings weight
        agg["team_quality_weight"] = 1.0 + np.clip(
            agg["opp_team_quality"] * TEAM_QUALITY_SCALE,
            -TEAM_QUALITY_CLIP,
            TEAM_QUALITY_CLIP,
        )

        # Combined innings weight = bowling quality × team quality
        agg["opp_quality_weight"] = (
            agg["opp_quality_weight"] * agg["team_quality_weight"]
        )
    else:
        agg["opp_team_quality"] = 0.0
        agg["team_quality_weight"] = 1.0

    # ── ICC T20I ranking-based opposition weighting ──
    # Multiplies into opp_quality_weight so performances against top-ranked
    # teams carry more weight.  For franchise leagues (IPL), uses per-season
    # franchise win-rate ratings instead of static ICC rankings.
    if ICC_RANKING_ENABLED and "bowling_team" in agg.columns:
        bowling_teams = agg["bowling_team"]
    elif ICC_RANKING_ENABLED and team_quality is None:
        # If we didn't join bowling_team above, derive it from deliveries
        bowling_team_map = df[
            ["match_id", "innings_num", "batting_team", "bowling_team"]
        ].drop_duplicates()
        for c in ["match_id", "batting_team", "bowling_team"]:
            if hasattr(bowling_team_map[c], "cat"):
                bowling_team_map[c] = bowling_team_map[c].astype(str)
        agg = agg.merge(
            bowling_team_map[
                ["match_id", "innings_num", "batting_team", "bowling_team"]
            ].drop_duplicates(),
            on=["match_id", "innings_num", "batting_team"],
            how="left",
        )
        bowling_teams = agg["bowling_team"]
    else:
        bowling_teams = None

    if franchise_season_ratings is not None and bowling_teams is not None:
        # Franchise mode: per-season win-rate-based ranking weights
        agg["icc_ranking_weight"] = compute_franchise_ranking_weights(
            bowling_teams, agg["date"], franchise_season_ratings
        )
        agg["opp_quality_weight"] = (
            agg["opp_quality_weight"] * agg["icc_ranking_weight"]
        )
    elif ICC_RANKING_ENABLED and bowling_teams is not None:
        agg["icc_ranking_weight"] = compute_icc_ranking_weights(bowling_teams)
        agg["opp_quality_weight"] = (
            agg["opp_quality_weight"] * agg["icc_ranking_weight"]
        )
    else:
        agg["icc_ranking_weight"] = 1.0

    # ── Match quality weighting (symmetric — both teams' rankings) ──
    # A match between two top-8 teams is inherently higher quality than
    # a match between two associates, even beyond the opposition ranking.
    if franchise_season_ratings is not None and "bowling_team" in agg.columns:
        agg["match_quality_weight"] = compute_franchise_match_quality_weights(
            agg["batting_team"],
            agg["bowling_team"],
            agg["date"],
            franchise_season_ratings,
        )
        agg["opp_quality_weight"] = (
            agg["opp_quality_weight"] * agg["match_quality_weight"]
        )
    elif MATCH_QUALITY_ENABLED and "bowling_team" in agg.columns:
        agg["match_quality_weight"] = compute_match_quality_weights(
            agg["batting_team"], agg["bowling_team"]
        )
        agg["opp_quality_weight"] = (
            agg["opp_quality_weight"] * agg["match_quality_weight"]
        )
    else:
        agg["match_quality_weight"] = 1.0

    # ── Raw opponent rating (for competition quality gate at career level) ──
    # For franchise leagues, uses per-season franchise ratings instead of
    # static ICC rankings.
    if franchise_season_ratings is not None and "bowling_team" in agg.columns:
        agg["opp_icc_rating"] = compute_franchise_opp_icc_rating(
            agg["bowling_team"], agg["date"], franchise_season_ratings
        )
    elif "bowling_team" in agg.columns:
        agg["opp_icc_rating"] = (
            agg["bowling_team"]
            .map(ICC_RANKING_RATINGS)
            .fillna(ICC_RANKING_DEFAULT_RATING)
        )
    else:
        agg["opp_icc_rating"] = ICC_RANKING_DEFAULT_RATING

    # ── Recency / time-decay weighting ──
    # More recent innings count for more in career aggregation.
    # weight = max(2^(-(days_since / half_life)), min_weight)
    # Multiplied into the combined opp_quality_weight so it flows through
    # to all downstream weighted-mean aggregations.
    if RECENCY_ENABLED and "date" in agg.columns:
        dates = pd.to_datetime(agg["date"], errors="coerce")
        reference_date = dates.max()
        if pd.notna(reference_date):
            days_since = (reference_date - dates).dt.total_seconds() / 86400.0
            days_since = days_since.fillna(0.0).clip(lower=0.0)
            half_life = max(RECENCY_HALF_LIFE_DAYS, 1.0)
            recency_weight = np.power(2.0, -(days_since / half_life))
            recency_weight = recency_weight.clip(lower=RECENCY_MIN_WEIGHT)
            agg["recency_weight"] = recency_weight
            agg["opp_quality_weight"] = agg["opp_quality_weight"] * recency_weight
        else:
            agg["recency_weight"] = 1.0
    else:
        agg["recency_weight"] = 1.0

    return agg


def _compute_phase_par_sr(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-match, per-phase par strike rates.

    Returns a DataFrame keyed on match_id with columns:
        pp_par_sr, middle_par_sr, death_par_sr
    """
    legal = df[df["is_legal"]].copy()
    for c in ["match_id", "phase"]:
        if hasattr(legal[c], "cat"):
            legal[c] = legal[c].astype(str)

    phase_stats = (
        legal.groupby(["match_id", "phase"])
        .agg(
            phase_runs=("batter_runs", "sum"),
            phase_extras=("extras_runs", "sum"),
            phase_balls=("is_legal", "sum"),
        )
        .reset_index()
    )

    # Total runs on that ball (batter + extras from legbyes/byes, NOT
    # wides/noballs since those aren't legal deliveries here)
    phase_stats["phase_total"] = phase_stats["phase_runs"] + phase_stats["phase_extras"]
    phase_stats["phase_sr"] = np.where(
        phase_stats["phase_balls"] > 0,
        phase_stats["phase_total"] / phase_stats["phase_balls"] * 100.0,
        np.nan,
    )

    pivoted = phase_stats.pivot_table(
        index="match_id", columns="phase", values="phase_sr"
    ).reset_index()

    rename_map = {}
    for col in pivoted.columns:
        if col == "powerplay":
            rename_map[col] = "pp_par_sr"
        elif col == "middle":
            rename_map[col] = "middle_par_sr"
        elif col == "death":
            rename_map[col] = "death_par_sr"
    pivoted = pivoted.rename(columns=rename_map)

    # Ensure all columns exist even if some matches lack a phase
    for col in ["pp_par_sr", "middle_par_sr", "death_par_sr"]:
        if col not in pivoted.columns:
            pivoted[col] = np.nan

    return pivoted[["match_id", "pp_par_sr", "middle_par_sr", "death_par_sr"]]


# ---------------------------------------------------------------------------
# Feature 11: Anchor Cost config
# ---------------------------------------------------------------------------
ANCHOR_COST_ENABLED: bool = cfg("anchor_cost.enabled", default=True)

# ---------------------------------------------------------------------------
# Feature 8: Selfless Index config
# ---------------------------------------------------------------------------
SELFLESS_ENABLED: bool = cfg("selfless.enabled", default=True)
SELFLESS_FIFTY_RANGE: list = cfg("selfless.fifty_approach_range", default=[40, 49])
SELFLESS_CENTURY_RANGE: list = cfg("selfless.century_approach_range", default=[90, 99])
SELFLESS_MIN_ZONE_BALLS: int = cfg("selfless.min_zone_balls", default=3)

# ---------------------------------------------------------------------------
# Feature 6: Chase Master config
# ---------------------------------------------------------------------------
CHASE_MASTER_ENABLED: bool = cfg("chase_master.enabled", default=True)
CHASE_MASTER_MIN_INN: int = cfg("chase_master.min_innings_per_type", default=5)

# ---------------------------------------------------------------------------
# Step 2: Compute raw metric components per innings
# ---------------------------------------------------------------------------

# Weights for each sub-component (exposed here for easy tuning).
#
# REWORKED per algorithm_update.md:
#   - Acceleration now centres on xR-based Run Value Added and leveraged RVA
#     as primary signals, with SR-based components as supporting evidence.
#   - Power now uses Context-Adjusted Boundary Index (CABI) as a primary
#     signal alongside six rate and finishing burst.
#   - Control now uses Expected Survival Rate as a primary signal alongside
#     dot ball management and rotation.
#
# Average (survivability) affects all three metrics:
#   - Control: additive z-score component at 0.25 weight PLUS a post-percentile
#     gate (milder than ACC/POW), PLUS survival_ratio from hazard model.
#   - Acceleration & Power: multiplicative quality factor (see AVG_QUALITY_*
#     constants below).  A batter averaging 15 gets their ACC/POW scores
#     scaled down by ~30-40%, which is far more impactful than an additive
#     component.  This prevents low-average sloggers from dominating.
ACC_WEIGHTS: dict[str, float] = cfg(
    "batting_acceleration_weights",
    default={
        "overall_sr": 0.15,
        "sr_growth": 0.12,
        "death_sr": 0.10,
        "impact": 0.13,
        "runs_above_expected": 0.25,
        "leveraged_rva": 0.25,
    },
)

POW_WEIGHTS: dict[str, float] = cfg(
    "batting_power_weights",
    default={
        "boundary_pct": 0.12,
        "six_rate": 0.15,
        "boundary_rate_vs_par": 0.13,
        "peak_phase_sr": 0.10,
        "finishing_burst": 0.15,
        "power_impact": 0.10,
        "cabi": 0.25,
    },
)

# Multiplicative average quality factor for Acceleration and Power.
#
# Two-stage system ensures low-average batters are meaningfully penalised:
#
# STAGE 1 — Pre-percentile (on raw z-score composites):
#   Asymmetric factor around the population median (~18):
#     Below: steep penalty (exponent 2.5)
#     Above: gentle bonus (exponent 0.5, capped)
#   This improves *relative ordering* among batters.
#
# STAGE 2 — Post-percentile (on final 0-100 scores):
#   Direct gate applied via apply_avg_quality_gate():
#     gate = AVG_GATE_BASE + (1 - AVG_GATE_BASE) * clip(avg / AVG_GATE_REF, 0, 1)
#   This provides *visible score reduction* for low-average batters
#   that z-score compression alone cannot achieve due to long tails.
#
# Combined effect examples (approximate):
#     avg 10 → acc/pow scores reduced to ~55-60% of ungated value
#     avg 15 → acc/pow scores reduced to ~80-83% (e.g. Karan KC ~99 → ~82)
#     avg 18 → acc/pow scores reduced to ~88% (mild, population median)
#     avg 25 → acc/pow scores unchanged (gate = 1.0)
#     avg 35 → acc/pow scores unchanged (gate = 1.0)
#
# Stage 1 constants:
AVG_QUALITY_REFERENCE: float = cfg("batting_avg_quality.reference", default=18.0)
AVG_QUALITY_EXPONENT_BELOW: float = cfg(
    "batting_avg_quality.exponent_below", default=2.5
)
AVG_QUALITY_EXPONENT_ABOVE: float = cfg(
    "batting_avg_quality.exponent_above", default=0.5
)
AVG_QUALITY_FLOOR: float = cfg("batting_avg_quality.floor", default=0.40)
AVG_QUALITY_CEIL: float = cfg("batting_avg_quality.ceil", default=1.20)

# Stage 2 constants (post-percentile gate):
# gate = AVG_GATE_BASE + (1 - AVG_GATE_BASE) * clip(career_avg / AVG_GATE_REF, 0, 1)
#   AVG_GATE_BASE : minimum gate value (floor).  0.55 means even the worst
#                   average can't reduce ACC/POW below 55% of the percentile score.
#   AVG_GATE_REF  : average at which the gate reaches 1.0 (no penalty).
#                   Set to 25 — a solid T20 average for a proper batter.
AVG_GATE_BASE: float = cfg("batting_avg_quality.gate_base", default=0.55)
AVG_GATE_REF: float = cfg("batting_avg_quality.gate_ref", default=25.0)

# Control gate: milder than ACC/POW since Control already has avg as additive
# component (0.30 weight).  The gate provides additional differentiation for
# very low averages that implies poor innings control.
#   CTRL_AVG_GATE_BASE : minimum gate for Control.  0.70 is milder than 0.55.
#   CTRL_AVG_GATE_REF  : average at which gate = 1.0 for Control.
CTRL_AVG_GATE_BASE: float = cfg("batting_avg_quality.ctrl_gate_base", default=0.70)
CTRL_AVG_GATE_REF: float = cfg("batting_avg_quality.ctrl_gate_ref", default=22.0)

# Dot-ball penalty phase weights (read from config).
# Death dots are most punishing (need to score fastest at the death);
# PP dots more acceptable (fielders in the circle, harder to rotate strike).
DOT_PENALTY_PP: float = cfg("batting_dot_penalty_phase_weights.powerplay", default=0.7)
DOT_PENALTY_MID: float = cfg("batting_dot_penalty_phase_weights.middle", default=1.0)
DOT_PENALTY_DEATH: float = cfg("batting_dot_penalty_phase_weights.death", default=1.5)

# Volume scaling constants.
# Players with more innings get a meaningful advantage.  The volume factor
# is applied post-percentile to all three scores:
#   factor = VOLUME_BASE + (1 - VOLUME_BASE) * clip(innings / VOLUME_REF, 0, 1) ** VOLUME_CURVE
#
# Players who exceed VOLUME_REF get a beyond-reference bonus:
#   beyond_bonus = VOLUME_BEYOND_MAX * clip((innings - ref) / ref, 0, 1)
#
# With default values (base=0.70, ref=100, curve=0.5, beyond_max=0.06):
#   10 innings → factor ~0.79   (21% penalty)
#   19 innings → factor ~0.83   (17% penalty)
#   30 innings → factor ~0.86   (14% penalty)
#   50 innings → factor ~0.91   ( 9% penalty)
#   75 innings → factor ~0.96   ( 4% penalty)
#   100 innings → factor 1.00   (no penalty)
#   120 innings → factor 1.01   ( 1% bonus)
#   150 innings → factor 1.03   ( 3% bonus)
#   200 innings → factor 1.06   ( 6% bonus, max)
VOLUME_BASE: float = cfg("batting_volume.base", default=0.70)
VOLUME_REF: float = cfg("batting_volume.ref", default=100.0)
VOLUME_CURVE: float = cfg("batting_volume.curve", default=0.5)
VOLUME_BEYOND_MAX: float = cfg("batting_volume.beyond_max", default=0.06)

CTRL_WEIGHTS: dict[str, float] = cfg(
    "batting_control_weights",
    default={
        "dot_pct_weighted": 0.12,
        "rotation": 0.08,
        "contribution": 0.10,
        "avg_proxy": 0.20,
        "dismissal_quality": 0.10,
        "scoring_consistency": 0.10,
        "survival_ratio": 0.30,
    },
)


def apply_avg_quality_gate(bat_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Post-percentile average quality gate for all three batting scores.

    After the rating system converts raw composites to 0-100 percentile
    scores, this function scales scores by a gate derived from the batter's
    career average.

    **Acceleration & Power** use a steeper gate::

        gate = AVG_GATE_BASE + (1 - AVG_GATE_BASE) * clip(avg / AVG_GATE_REF, 0, 1)

    With default constants (base=0.55, ref=25):
        avg  5  → gate 0.64
        avg 10  → gate 0.73
        avg 15  → gate 0.82
        avg 25+ → gate 1.00

    **Control** uses a milder gate (because Control already has avg as a 0.30
    additive z-score component, but a high average still implies better
    innings control and should provide additional lift)::

        ctrl_gate = CTRL_AVG_GATE_BASE + (1 - CTRL_AVG_GATE_BASE) * clip(avg / CTRL_AVG_GATE_REF, 0, 1)

    With default constants (base=0.70, ref=22):
        avg  5  → gate 0.77
        avg 10  → gate 0.84
        avg 15  → gate 0.90
        avg 22+ → gate 1.00

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Career profiles **after** the rating system has been applied.

    Returns
    -------
    pd.DataFrame with all three scores adjusted, plus gate columns.
    """
    df = bat_careers.copy()

    avg = df["career_avg"].fillna(0.0)

    # ACC / POW gate (steeper)
    gate = AVG_GATE_BASE + (1.0 - AVG_GATE_BASE) * (avg / AVG_GATE_REF).clip(
        lower=0.0, upper=1.0
    )
    df["avg_quality_gate"] = gate

    for col in ["score_acceleration", "score_power"]:
        if col in df.columns:
            df[col] = (df[col] * gate).round(1).clip(lower=0.0, upper=100.0)

    # Control gate (milder)
    ctrl_gate = CTRL_AVG_GATE_BASE + (1.0 - CTRL_AVG_GATE_BASE) * (
        avg / CTRL_AVG_GATE_REF
    ).clip(lower=0.0, upper=1.0)
    df["ctrl_avg_gate"] = ctrl_gate

    if "score_control" in df.columns:
        df["score_control"] = (
            (df["score_control"] * ctrl_gate).round(1).clip(lower=0.0, upper=100.0)
        )

    return df


def apply_volume_scaling(bat_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Post-percentile volume scaling: rewards players with more innings.

    A 19-innings player cannot match a 50-innings player all else being equal.
    This is separate from Bayesian shrinkage (which pulls toward the mean)
    and confidence bonus (which is only 3%).  Volume scaling applies a direct
    multiplicative factor to all three scores::

        factor = VOLUME_BASE + (1 - VOLUME_BASE) * clip(innings / VOLUME_REF, 0, 1) ** VOLUME_CURVE

    Players who exceed VOLUME_REF get a beyond-reference bonus that rewards
    sustained career volume::

        beyond_bonus = VOLUME_BEYOND_MAX * clip((innings - ref) / ref, 0, 1)

    With defaults (base=0.70, ref=100, curve=0.5, beyond_max=0.06):
        10 innings → factor ~0.79   (21% penalty)
        19 innings → factor ~0.83   (17% penalty)
        30 innings → factor ~0.86   (14% penalty)
        50 innings → factor ~0.91   ( 9% penalty)
        75 innings → factor ~0.96   ( 4% penalty)
        100 innings → factor 1.00   (no penalty)
        120 innings → factor 1.01   ( 1% bonus)
        150 innings → factor 1.03   ( 3% bonus)
        200+ innings → factor 1.06  ( 6% bonus, max)

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Career profiles after rating system and avg gate.

    Returns
    -------
    pd.DataFrame with scores scaled by volume factor.
    """
    df = bat_careers.copy()

    innings = df["innings_count"].fillna(0).astype(float)
    ratio = (innings / VOLUME_REF).clip(lower=0.0, upper=1.0)
    factor = VOLUME_BASE + (1.0 - VOLUME_BASE) * (ratio**VOLUME_CURVE)

    # Beyond-reference bonus: players exceeding VOLUME_REF get up to
    # VOLUME_BEYOND_MAX additional scaling (e.g. 6% at 2× the reference).
    beyond_mask = innings > VOLUME_REF
    if beyond_mask.any():
        extra_ratio = ((innings - VOLUME_REF) / VOLUME_REF).clip(lower=0.0, upper=1.0)
        factor = factor + VOLUME_BEYOND_MAX * extra_ratio

    df["volume_factor"] = factor

    for col in ["score_acceleration", "score_power", "score_control"]:
        if col in df.columns:
            df[col] = (df[col] * factor).round(1).clip(lower=0.0, upper=100.0)

    return df


# ---------------------------------------------------------------------------
# Competition quality gate constants
# ---------------------------------------------------------------------------

COMPETITION_GATE_ENABLED: bool = cfg("competition_quality_gate.enabled", default=True)
COMPETITION_GATE_BASE: float = cfg("competition_quality_gate.base", default=0.55)
COMPETITION_GATE_CURVE: float = cfg("competition_quality_gate.curve", default=0.5)


def apply_competition_quality_gate(bat_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Post-percentile competition quality gate for all three batting scores.

    Directly scales down final 0-100 scores for batters who primarily face
    weak opposition.  This is separate from (and complementary to) the
    per-innings ICC ranking weight which affects career aggregation weights.

    The gate uses the player's average opponent ICC rating across their career::

        normalised = avg_opp_icc_rating / max_rating          (0 to 1)
        gate = base + (1 - base) * normalised ^ curve

    A sub-linear curve (< 1) concentrates the penalty on players with very
    low average opponent quality while barely affecting players who face
    top-ranked teams.

    Examples with defaults (base=0.55, curve=0.5, max_rating=272):
        avg_opp 260 (faces top-8 teams)   → gate 0.99
        avg_opp 230 (faces Test nations)   → gate 0.96
        avg_opp 200 (mixed opponents)      → gate 0.94
        avg_opp 150 (mid-tier associates)  → gate 0.88
        avg_opp 120 (low-tier associates)  → gate 0.85
        avg_opp  80 (very weak opponents)  → gate 0.79
        avg_opp  30 (unranked opponents)   → gate 0.70

    Parameters
    ----------
    bat_careers : pd.DataFrame
        Career profiles **after** the rating system, avg gate, and volume
        scaling have been applied.  Must contain ``avg_opp_icc_rating``.

    Returns
    -------
    pd.DataFrame with all three scores adjusted, plus a ``competition_gate``
    column for diagnostics.
    """
    if not COMPETITION_GATE_ENABLED:
        return bat_careers

    df = bat_careers.copy()

    max_r = max(ICC_RANKING_MAX_RATING, 1.0)
    avg_opp = df["avg_opp_icc_rating"].fillna(ICC_RANKING_DEFAULT_RATING)
    normalised = (avg_opp / max_r).clip(lower=0.0, upper=1.0)

    gate = COMPETITION_GATE_BASE + (1.0 - COMPETITION_GATE_BASE) * (
        normalised**COMPETITION_GATE_CURVE
    )
    df["competition_gate"] = gate

    for col in ["score_acceleration", "score_power", "score_control"]:
        if col in df.columns:
            df[col] = (df[col] * gate).round(1).clip(lower=0.0, upper=100.0)

    return df


def apply_bowling_competition_quality_gate(
    bowl_careers: pd.DataFrame,
) -> pd.DataFrame:
    """
    Post-percentile competition quality gate for all three bowling scores.

    Identical logic to the batting gate but applied to bowling careers.
    Scales down scores for bowlers who primarily bowl against weak batting
    lineups.

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Career profiles **after** the rating system and volume scaling.
        Must contain ``avg_opp_icc_rating``.

    Returns
    -------
    pd.DataFrame with all three scores adjusted, plus a ``competition_gate``
    column for diagnostics.
    """
    if not COMPETITION_GATE_ENABLED:
        return bowl_careers

    df = bowl_careers.copy()

    max_r = max(ICC_RANKING_MAX_RATING, 1.0)
    avg_opp = df["avg_opp_icc_rating"].fillna(ICC_RANKING_DEFAULT_RATING)
    normalised = (avg_opp / max_r).clip(lower=0.0, upper=1.0)

    gate = COMPETITION_GATE_BASE + (1.0 - COMPETITION_GATE_BASE) * (
        normalised**COMPETITION_GATE_CURVE
    )
    df["competition_gate"] = gate

    for col in ["score_accuracy", "score_control", "score_threat"]:
        if col in df.columns:
            df[col] = (df[col] * gate).round(1).clip(lower=0.0, upper=100.0)

    return df


def compute_batting_components(
    bat_innings: pd.DataFrame,
    ev_models: dict | None = None,
    scored_deliveries: pd.DataFrame | None = None,
    survival_rates: pd.DataFrame | None = None,
    cabi_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    For every batter-innings row, compute the sub-component values that feed
    into each of the three career metrics.

    All "good" directions are positive; components that are naturally inverted
    (like dot %) are flipped here so that higher always = better downstream.

    Phase stats that don't meet MIN_PHASE_BALLS are left as NaN and will be
    excluded from career aggregation (weighted mean ignores NaN).

    NEW in algorithm rework:
    - Acceleration uses xR-based Run Value Added (RVA) as a primary signal
      alongside the existing SR-based components.
    - Power integrates Context-Adjusted Boundary Index (CABI) residuals.
    - Control integrates Expected Survival Rate from the hazard model.

    Parameters
    ----------
    bat_innings : pd.DataFrame
        Output of extract_batting_innings().
    ev_models : dict, optional
        Output of expected_value.build_expected_value_models().
        If provided, xR-based components are added.
    scored_deliveries : pd.DataFrame, optional
        Deliveries with ``run_value_added`` column (from expected_value
        scoring).  Used to compute per-innings RVA aggregates.
    survival_rates : pd.DataFrame, optional
        Output of expected_value.compute_expected_survival_rates().
        Keyed on batter_id.  Used for Control dimension.
    cabi_data : pd.DataFrame, optional
        Output of expected_value.compute_context_adjusted_boundary_index().
        Keyed on batter_id.  Used for Power dimension.
    """
    df = bat_innings.copy()

    par = df["match_par_sr"].fillna(df["match_par_sr"].mean()).clip(lower=1)

    # Phase-specific pars (fall back to overall match par if missing)
    pp_par = df["pp_par_sr"].fillna(par)
    mid_par = df["middle_par_sr"].fillna(par)
    death_par = df["death_par_sr"].fillna(par)

    # ── Merge per-innings RVA from xR-scored deliveries ──
    has_rva = False
    if scored_deliveries is not None and "run_value_added" in scored_deliveries.columns:
        _sd = scored_deliveries[scored_deliveries["is_batter_ball"]].copy()
        for c in ["match_id", "batter_id"]:
            if hasattr(_sd[c], "cat"):
                _sd[c] = _sd[c].astype(str)

        rva_agg = (
            _sd.groupby(["match_id", "innings_num", "batter_id"])
            .agg(
                innings_rva=("run_value_added", "sum"),
                innings_rva_mean=("run_value_added", "mean"),
                innings_rva_balls=("run_value_added", "count"),
            )
            .reset_index()
        )

        # Also compute leveraged RVA if available
        if "leveraged_rva" in _sd.columns:
            lrva_agg = (
                _sd.groupby(["match_id", "innings_num", "batter_id"])
                .agg(innings_leveraged_rva=("leveraged_rva", "sum"))
                .reset_index()
            )
            rva_agg = rva_agg.merge(
                lrva_agg,
                on=["match_id", "innings_num", "batter_id"],
                how="left",
            )
        else:
            rva_agg["innings_leveraged_rva"] = rva_agg["innings_rva"]

        # Also compute per-innings WPA if available
        if "wpa" in _sd.columns:
            wpa_agg = (
                _sd.groupby(["match_id", "innings_num", "batter_id"])
                .agg(innings_wpa=("wpa", "sum"))
                .reset_index()
            )
            rva_agg = rva_agg.merge(
                wpa_agg,
                on=["match_id", "innings_num", "batter_id"],
                how="left",
            )
        else:
            rva_agg["innings_wpa"] = 0.0

        # Also get average leverage for this innings
        if "leverage_index" in _sd.columns:
            li_agg = (
                _sd.groupby(["match_id", "innings_num", "batter_id"])
                .agg(innings_avg_leverage=("leverage_index", "mean"))
                .reset_index()
            )
            rva_agg = rva_agg.merge(
                li_agg,
                on=["match_id", "innings_num", "batter_id"],
                how="left",
            )
        else:
            rva_agg["innings_avg_leverage"] = 1.0

        df = df.merge(
            rva_agg,
            on=["match_id", "innings_num", "batter_id"],
            how="left",
        )
        df["innings_rva"] = df["innings_rva"].fillna(0.0)
        df["innings_rva_mean"] = df["innings_rva_mean"].fillna(0.0)
        df["innings_leveraged_rva"] = df["innings_leveraged_rva"].fillna(0.0)
        df["innings_wpa"] = df["innings_wpa"].fillna(0.0)
        df["innings_avg_leverage"] = df["innings_avg_leverage"].fillna(1.0)
        has_rva = True
    else:
        df["innings_rva"] = 0.0
        df["innings_rva_mean"] = 0.0
        df["innings_leveraged_rva"] = 0.0
        df["innings_wpa"] = 0.0
        df["innings_avg_leverage"] = 1.0

    # =====================================================================
    # ACCELERATION components
    # =====================================================================

    # A1: Context-adjusted overall SR (ratio − 1.0, so 0 = par)
    #     Using ratio ensures era-independence and avoids individual-vs-team bias.
    df["acc_overall_sr"] = df["sr"] / par - 1.0

    # A2: SR growth first→second half
    #     Clamped at 0: flat-but-fast is not penalised.
    #     Normalised by match par so growth is era-independent.
    first_sr = df["first_half_sr"]  # NaN if < MIN_PHASE_BALLS
    second_sr = df["second_half_sr"]
    # Only compute growth when both halves are valid
    sr_growth = np.where(
        first_sr.notna() & second_sr.notna(),
        np.maximum(second_sr - first_sr, 0.0) / par,
        np.nan,
    )
    df["acc_sr_growth"] = sr_growth

    # A3: Death-overs SR relative to DEATH-PHASE par
    #     NaN if the batter didn't face enough death-over balls —
    #     this is INTENTIONALLY NaN (not 0) so it doesn't drag down
    #     batters who simply didn't bat in the death.
    df["acc_death_sr"] = np.where(
        df["death_sr"].notna(),
        df["death_sr"] / death_par - 1.0,
        np.nan,
    )

    # A4: Impact factor: volume × speed above par
    #     Rewards batters who score *lots* of runs *fast*, not just quick
    #     cameos of 15(6).
    sr_ratio_above_par = np.maximum(df["sr"] / par - 1.0, 0.0)
    df["acc_impact"] = df["runs"] * sr_ratio_above_par

    # A5: xR-based Runs Above Expected (Run Value Added per ball)
    #     From the Expected Value framework: actual runs − baseline expected
    #     runs at each match state, aggregated per innings and normalised
    #     per ball faced.  This is the single strongest context-adjusted
    #     signal — it controls for phase, wickets, venue difficulty, and
    #     era in one number.
    #     Falls back to the phase-par approximation if xR model not available.
    if has_rva:
        df["acc_runs_above_expected"] = df["innings_rva_mean"]
    else:
        # Fallback: phase-par approximation (original algorithm)
        pp_balls_a5 = df["powerplay_balls"].fillna(0)
        mid_balls_a5 = df["middle_balls"].fillna(0)
        death_balls_a5 = df["death_balls"].fillna(0)
        expected_runs = (
            pp_balls_a5 * pp_par / 100.0
            + mid_balls_a5 * mid_par / 100.0
            + death_balls_a5 * death_par / 100.0
        )
        df["acc_runs_above_expected"] = np.where(
            df["balls_faced"] > 0,
            (df["runs"] - expected_runs) / df["balls_faced"],
            0.0,
        )

    # A6: Leveraged RVA per ball — RVA weighted by Leverage Index.
    #     This is the context-adjusted run value as described in the
    #     algorithm document: RVA × LI.  Rewards runs scored in high-pressure
    #     situations (death overs, close chases) more than "garbage time" runs.
    #     Only available when full WP/LI computation is done.
    df["acc_leveraged_rva"] = np.where(
        df["balls_faced"] > 0,
        df["innings_leveraged_rva"] / df["balls_faced"].clip(lower=1),
        0.0,
    )

    # =====================================================================
    # POWER components
    # =====================================================================

    # P1: Boundary % of runs
    df["pow_boundary_pct"] = df["boundary_pct"]

    # P2: Six-hitting rate — sixes per ball faced.
    #     Direct measure of clearing-the-boundary ability.  This is the
    #     single clearest signal of raw power: a batter who hits 3 sixes
    #     in 20 balls is more powerful than one who hits 5 fours.
    df["pow_six_rate"] = np.where(
        df["balls_faced"] > 0, df["sixes"] / df["balls_faced"], 0.0
    )

    # P3: Context-adjusted boundary rate vs match average
    df["pow_boundary_rate"] = np.where(
        df["balls_faced"] > 0,
        (df["fours"] + df["sixes"]) / df["balls_faced"],
        0.0,
    )
    mbr = df["match_boundary_rate"].fillna(0)
    df["pow_boundary_rate_vs_par"] = df["pow_boundary_rate"] - mbr

    # P4: Peak phase SR (best phase the batter batted in, vs that phase's par)
    #     Only consider phases with enough balls.
    pp_sr_ratio = np.where(
        df["powerplay_sr"].notna(),
        df["powerplay_sr"] / pp_par - 1.0,
        np.nan,
    )
    mid_sr_ratio = np.where(
        df["middle_sr"].notna(),
        df["middle_sr"] / mid_par - 1.0,
        np.nan,
    )
    death_sr_ratio = np.where(
        df["death_sr"].notna(),
        df["death_sr"] / death_par - 1.0,
        np.nan,
    )

    phase_ratios = pd.DataFrame(
        {"pp": pp_sr_ratio, "mid": mid_sr_ratio, "death": death_sr_ratio}
    )
    df["pow_peak_phase_sr"] = phase_ratios.max(axis=1)
    # Fall back to overall SR ratio if no phase had enough balls
    df["pow_peak_phase_sr"] = df["pow_peak_phase_sr"].fillna(df["sr"] / par - 1.0)

    # P5: Finishing burst — gear-shifting from accumulation to explosion.
    #     Measures the SR jump from the first two-thirds to the final third
    #     of the innings, normalised by match par.  Captures the Kohli-style
    #     50(40) → 90(60) acceleration: first 2/3 SR ~125, final 1/3 SR ~200.
    #     Clamped at 0: not accelerating is neutral, not penalised.
    #     NaN if either segment has too few balls (won't drag down career avg).
    first_two_thirds_sr = df.get("first_two_thirds_sr")
    final_third_sr = df.get("final_third_sr")
    if first_two_thirds_sr is not None and final_third_sr is not None:
        df["pow_finishing_burst"] = np.where(
            first_two_thirds_sr.notna() & final_third_sr.notna(),
            np.maximum(final_third_sr - first_two_thirds_sr, 0.0) / par,
            np.nan,
        )
    else:
        df["pow_finishing_burst"] = np.nan

    # P6: Power impact — sustained big-hitting in substantial innings.
    #     Boundary runs × (SR/par) for innings of 20+ balls.
    #     This rewards batters who hit lots of boundaries while also scoring
    #     fast, over a sustained period — not just quick cameos of 15(6).
    #     Sub-20-ball innings get NaN (neutral at career level).
    #     Normalised by balls faced so innings of different lengths are
    #     comparable (gives "power runs per ball above par").
    boundary_runs = (df["fours"] * 4 + df["sixes"] * 6).astype(float)
    sr_ratio = df["sr"] / par
    substantial = df["balls_faced"] >= 20
    df["pow_power_impact"] = np.where(
        substantial,
        (boundary_runs / df["balls_faced"]) * sr_ratio,
        np.nan,
    )

    # =====================================================================
    # CONTROL components
    # =====================================================================

    # C1: Phase-weighted dot ball % (inverted: lower dot % = higher score)
    #     Death dots penalised most (1.5×) — need to score fastest there.
    #     PP dots penalised least (0.7×) — fielders in circle, harder to rotate.
    pp_balls = df["powerplay_balls"].fillna(0).clip(lower=0)
    mid_balls = df["middle_balls"].fillna(0).clip(lower=0)
    death_balls = df["death_balls"].fillna(0).clip(lower=0)

    pp_dot = df["powerplay_dots"].fillna(0)
    mid_dot = df["middle_dots"].fillna(0)
    death_dot = df["death_dots"].fillna(0)

    # Safe division for per-phase dot rates
    pp_dot_rate = np.where(pp_balls > 0, pp_dot / pp_balls, 0.0)
    mid_dot_rate = np.where(mid_balls > 0, mid_dot / mid_balls, 0.0)
    death_dot_rate = np.where(death_balls > 0, death_dot / death_balls, 0.0)

    weighted_dot_num = (
        pp_dot_rate * pp_balls * DOT_PENALTY_PP
        + mid_dot_rate * mid_balls * DOT_PENALTY_MID
        + death_dot_rate * death_balls * DOT_PENALTY_DEATH
    )
    weighted_dot_den = (
        pp_balls * DOT_PENALTY_PP
        + mid_balls * DOT_PENALTY_MID
        + death_balls * DOT_PENALTY_DEATH
    )

    raw_weighted_dot = np.where(
        weighted_dot_den > 0,
        weighted_dot_num / weighted_dot_den,
        df["dot_pct"],
    )
    # Invert: lower dot % → higher component value
    df["ctrl_dot_pct_weighted"] = 1.0 - raw_weighted_dot

    # C6: Scoring consistency — simple 1 − dot% (unweighted by phase)
    #     Measures pure ability to get bat on ball and find gaps.
    #     Different from ctrl_dot_pct_weighted which phase-weights dots;
    #     this is the raw "control index" — a batter who consistently
    #     makes contact and rotates strike has high scoring consistency
    #     regardless of which phase they bat in.
    df["ctrl_scoring_consistency"] = np.where(
        df["balls_faced"] > 0,
        1.0 - (df["dots"] / df["balls_faced"]),
        0.0,
    )

    # C2: Rotation rate (1s + 2s per ball faced)
    df["ctrl_rotation"] = df["rotation_rate"]

    # C3: Team contribution %
    #     Carrying the team = high control / importance.
    df["ctrl_contribution"] = df["team_contribution_pct"]

    # C4: Runs scored (proxy for average, actual avg computed at career level)
    #     Per-innings: just use runs, which rewards longer stays.
    #     Normalised at career level via z-score.
    df["ctrl_avg_proxy"] = df["runs"].astype(float)

    # C5: Dismissal context quality (inverted so higher = better)
    #     Getting out when the team is in trouble is worse.
    #     Not-out innings get 0 penalty (which becomes no contribution via NaN
    #     handling at career level for this component).
    df["ctrl_dismissal_quality"] = 0.0
    out_mask = df["is_out"].fillna(False)
    if out_mask.any():
        wkts = df.loc[out_mask, "dismissal_team_wickets"].fillna(0) / 10.0
        over_frac = (
            1.0 - df.loc[out_mask, "dismissal_over"].fillna(10).clip(upper=19) / 20.0
        )
        # Penalty is between 0 and ~0.5; invert so that lower penalty = better
        df.loc[out_mask, "ctrl_dismissal_quality"] = -(wkts * over_frac)

    # For not-out innings, dismissal quality is 0 (neutral, not a bonus).
    # This avoids biasing towards always-not-out (which could be tail-enders
    # who never face enough balls).

    return df


# ---------------------------------------------------------------------------
# Step 3: Aggregate across career into per-player metric scores
# ---------------------------------------------------------------------------


def _zscore_series(s: pd.Series) -> pd.Series:
    """
    Z-score normalise a series.  Returns (s - mean) / std.
    If std is 0 (all values identical), returns 0s.
    NaN values remain NaN.
    """
    mean = s.mean()
    std = s.std()
    if pd.isna(std) or std < 1e-12:
        return pd.Series(0.0, index=s.index)
    return (s - mean) / std


def aggregate_batting_careers(
    bat_components: pd.DataFrame,
    min_innings: int = 10,
    survival_rates: pd.DataFrame | None = None,
    cabi_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Aggregate per-innings components into career-level raw composite scores.

    One row per batter_id with:
    - Career stats (runs, balls, SR, avg, 4s, 6s)
    - raw_acceleration, raw_power, raw_control  (z-score composites)
    - is_provisional_bat flag
    - modal_position, position_group  (batting position context)
    - xR-derived metrics (RVA, leveraged RVA, WPA)
    - CABI (Context-Adjusted Boundary Index) for Power
    - survival_ratio for Control

    The aggregation uses **opposition-quality-weighted** AND **team-quality-
    weighted** means: innings played against stronger bowling attacks and
    stronger teams contribute more to a batter's career profile.  The
    combined weight per innings is::

        opp_quality_weight (already incorporates both bowling + team quality)

    Missing phase stats (e.g. a batter who never batted in the death) simply
    don't contribute — they are NOT filled with 0 and penalised.

    After computing per-player weighted means for each sub-component, the
    components are z-score normalised **within batting position groups** (if
    enabled) and then weight-averaged to form the final raw composite.  This
    ensures openers are compared to openers, finishers to finishers, etc.

    Parameters
    ----------
    bat_components : pd.DataFrame
        Output of compute_batting_components().
    min_innings : int
        Fewer innings than this → provisional rating.
    survival_rates : pd.DataFrame, optional
        Output of expected_value.compute_expected_survival_rates().
        If provided, survival_ratio is merged as a Control component.
    cabi_data : pd.DataFrame, optional
        Output of expected_value.compute_context_adjusted_boundary_index().
        If provided, CABI is merged as a Power component.
    """

    # Ensure grouping columns are plain strings
    bc = bat_components.copy()
    for c in ["batter_id", "batter", "batting_team"]:
        if hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)

    # Ensure opp_quality_weight exists (backwards compat if missing)
    if "opp_quality_weight" not in bc.columns:
        bc["opp_quality_weight"] = 1.0

    grp = bc.groupby(["batter_id", "batter"])

    # ── Opposition-quality-weighted mean helpers ──
    def _weighted_mean(values, weights):
        """Weighted mean ignoring NaN in values (weights kept where values valid)."""
        mask = values.notna()
        v = values[mask]
        w = weights[mask]
        if len(v) == 0 or w.sum() == 0:
            return np.nan
        return (v * w).sum() / w.sum()

    def _opp_weighted_mean(col_name):
        """Return an aggregation function that computes opp-quality-weighted mean."""

        def _agg(sub_df):
            return _weighted_mean(sub_df[col_name], sub_df["opp_quality_weight"])

        return _agg

    def _opp_weighted_nanmean(col_name):
        """Like _opp_weighted_mean but explicitly NaN-aware (same behaviour, clearer intent)."""
        return _opp_weighted_mean(col_name)

    # ── Build career aggregations ──
    # Basic stats use simple sums (not weighted — these are factual totals)
    # Also track team quality if available
    has_team_quality = "opp_team_quality" in bc.columns

    has_opp_icc_rating = "opp_icc_rating" in bc.columns

    basic_stats = grp.agg(
        innings_count=("match_id", "nunique"),
        total_runs=("runs", "sum"),
        total_balls=("balls_faced", "sum"),
        total_fours=("fours", "sum"),
        total_sixes=("sixes", "sum"),
        total_outs=("is_out", "sum"),
        sr_vs_par_std=("sr_vs_par", "std"),
        avg_opp_quality=("opposition_quality", "mean"),
        avg_team_quality=(
            "opp_team_quality" if has_team_quality else "opposition_quality",
            "mean",
        ),
        avg_opp_icc_rating=(
            "opp_icc_rating" if has_opp_icc_rating else "opposition_quality",
            "mean",
        ),
    ).reset_index()

    # Rename if we used the fallback column
    if not has_team_quality:
        basic_stats["avg_team_quality"] = 0.0
    if not has_opp_icc_rating:
        basic_stats["avg_opp_icc_rating"] = ICC_RANKING_DEFAULT_RATING

    # ── Primary country: team the batter has played the most matches for ──
    country_df = (
        bc.groupby(["batter_id", "batter", "batting_team"])["match_id"]
        .nunique()
        .reset_index(name="team_matches")
    )
    primary_country = (
        country_df.sort_values("team_matches", ascending=False)
        .drop_duplicates(subset=["batter_id", "batter"], keep="first")
        .rename(columns={"batting_team": "country"})[["batter_id", "batter", "country"]]
    )
    basic_stats = basic_stats.merge(
        primary_country, on=["batter_id", "batter"], how="left"
    )

    # Component means use opposition-quality-weighted averaging
    component_cols = {
        # Acceleration
        "acc_overall_sr": "acc_overall_sr_mean",
        "acc_sr_growth": "acc_sr_growth_mean",
        "acc_death_sr": "acc_death_sr_mean",
        "acc_impact": "acc_impact_mean",
        "acc_runs_above_expected": "acc_runs_above_expected_mean",
        "acc_leveraged_rva": "acc_leveraged_rva_mean",
        # Power
        "pow_boundary_pct": "pow_boundary_pct_mean",
        "pow_six_rate": "pow_six_rate_mean",
        "pow_boundary_rate_vs_par": "pow_boundary_rate_vs_par_mean",
        "pow_peak_phase_sr": "pow_peak_phase_sr_mean",
        "pow_finishing_burst": "pow_finishing_burst_mean",
        "pow_power_impact": "pow_power_impact_mean",
        # Control
        "ctrl_dot_pct_weighted": "ctrl_dot_pct_weighted_mean",
        "ctrl_scoring_consistency": "ctrl_scoring_consistency_mean",
        "ctrl_rotation": "ctrl_rotation_mean",
        "ctrl_contribution": "ctrl_contribution_mean",
        "ctrl_avg_proxy": "ctrl_avg_proxy_mean",
        "ctrl_dismissal_quality": "ctrl_dismissal_quality_mean",
    }

    # Also aggregate xR-derived innings-level stats (RVA, WPA, LI)
    has_rva_cols = "innings_rva" in bc.columns
    if has_rva_cols:
        component_cols["innings_rva"] = "avg_innings_rva"
        component_cols["innings_rva_mean"] = "avg_rva_per_ball"
        component_cols["innings_leveraged_rva"] = "avg_leveraged_rva"
        component_cols["innings_wpa"] = "avg_innings_wpa"
        component_cols["innings_avg_leverage"] = "avg_leverage"

    # Filter to only columns that actually exist in the input DataFrame.
    # New xR-based columns (acc_leveraged_rva, etc.) may be absent when
    # the xR model wasn't run or in synthetic test data.
    component_cols = {
        src: out for src, out in component_cols.items() if src in bc.columns
    }

    weighted_aggs = grp.apply(
        lambda g: pd.Series(
            {
                out_name: _weighted_mean(g[src_col], g["opp_quality_weight"])
                for src_col, out_name in component_cols.items()
            }
        ),
        include_groups=False,
    ).reset_index()

    career = basic_stats.merge(weighted_aggs, on=["batter_id", "batter"], how="left")

    # ── Career-level derived stats ──
    career["career_sr"] = np.where(
        career["total_balls"] > 0,
        career["total_runs"] / career["total_balls"] * 100.0,
        0.0,
    )
    career["career_avg"] = np.where(
        career["total_outs"] > 0,
        career["total_runs"] / career["total_outs"],
        career["total_runs"].astype(float),  # never out → use total
    )

    # Fill NaN std (single-innings players) with a high value (inconsistent)
    career["sr_vs_par_std"] = career["sr_vs_par_std"].fillna(
        career["sr_vs_par_std"].quantile(0.75) if len(career) > 0 else 50
    )

    # ── Anchor Cost career aggregation (Feature 11) ──────────────────
    if ANCHOR_COST_ENABLED and "balls_to_par" in bc.columns:
        anchor_agg = grp.agg(
            avg_balls_to_par=("balls_to_par", "mean"),
        ).reset_index()
        career = career.merge(anchor_agg, on=["batter_id", "batter"], how="left")
        # Anchor cost ratio: avg_balls_to_par normalised by average
        # innings length.  Higher = slower to reach par.
        avg_inn_length = np.where(
            career["innings_count"] > 0,
            career["total_balls"] / career["innings_count"],
            1.0,
        )
        career["anchor_cost_ratio"] = np.where(
            avg_inn_length > 0,
            career["avg_balls_to_par"] / avg_inn_length,
            np.nan,
        )
    else:
        career["avg_balls_to_par"] = np.nan
        career["anchor_cost_ratio"] = np.nan

    # ── Selfless Index career aggregation (Feature 8) ────────────────
    if SELFLESS_ENABLED:
        selfless_cols = {}
        for zone_name in ("fifty_approach", "century_approach"):
            sr_col = f"{zone_name}_sr"
            balls_col = f"{zone_name}_balls"
            if sr_col in bc.columns:
                selfless_cols[f"{zone_name}_sr_mean"] = (sr_col, "mean")
                selfless_cols[f"{zone_name}_balls_total"] = (balls_col, "sum")

        if selfless_cols:
            selfless_agg = grp.agg(**selfless_cols).reset_index()
            career = career.merge(selfless_agg, on=["batter_id", "batter"], how="left")

        # Selfless index: milestone approach SR / career SR
        # Ratio near 1.0 = consistent intent; below 0.8 = significant
        # slowdown approaching milestones.  > 1.0 = actually accelerates.
        if "fifty_approach_sr_mean" in career.columns:
            career["selfless_fifty"] = np.where(
                career["career_sr"] > 0,
                career["fifty_approach_sr_mean"] / career["career_sr"],
                np.nan,
            )
        else:
            career["selfless_fifty"] = np.nan

        if "century_approach_sr_mean" in career.columns:
            career["selfless_century"] = np.where(
                career["career_sr"] > 0,
                career["century_approach_sr_mean"] / career["career_sr"],
                np.nan,
            )
        else:
            career["selfless_century"] = np.nan

        # Combined selfless index: weighted average of both zones
        # (fifty zone gets most weight — more data points for most batters)
        _sf = career["selfless_fifty"].fillna(1.0)
        _sc = career["selfless_century"].fillna(1.0)
        _has_fifty = career["selfless_fifty"].notna()
        _has_cent = career["selfless_century"].notna()
        career["selfless_index"] = np.where(
            _has_fifty & _has_cent,
            0.7 * _sf + 0.3 * _sc,
            np.where(_has_fifty, _sf, np.where(_has_cent, _sc, np.nan)),
        )
    else:
        career["fifty_approach_sr_mean"] = np.nan
        career["century_approach_sr_mean"] = np.nan
        career["selfless_fifty"] = np.nan
        career["selfless_century"] = np.nan
        career["selfless_index"] = np.nan

    # ──────────────────────────────────────────────────────────────────────
    # Determine each batter's modal batting position and position group.
    # This drives within-group z-scoring: openers compared to openers,
    # finishers to finishers, etc.
    # ──────────────────────────────────────────────────────────────────────
    modal_pos = _determine_modal_position(bc)
    career = career.merge(
        modal_pos[["batter_id", "batter", "modal_position", "position_group"]],
        on=["batter_id", "batter"],
        how="left",
    )
    # Fallback for any unmatched players
    career["modal_position"] = career["modal_position"].fillna(5).astype(int)
    career["position_group"] = career["position_group"].fillna("upper_middle")

    # Merge small position groups into adjacent groups for stable z-scoring
    if POSITION_GROUPS_ENABLED:
        group_counts = career["position_group"].value_counts()
        for small_group, merge_into in POSITION_GROUP_MERGE_FALLBACK.items():
            if group_counts.get(small_group, 0) < MIN_POSITION_GROUP_SIZE:
                mask = career["position_group"] == small_group
                if mask.any():
                    career.loc[mask, "position_group"] = merge_into
                    print(
                        f"  ℹ Position group '{small_group}' "
                        f"({group_counts.get(small_group, 0)} players) "
                        f"merged into '{merge_into}' for z-scoring"
                    )

    # ──────────────────────────────────────────────────────────────────────
    # Z-score normalise each sub-component, then weight-average to form
    # the composite.
    #
    # When position groups are enabled, z-scores are computed WITHIN each
    # group so openers compete with openers, finishers with finishers.
    # This prevents inflated acceleration scores for finishers who bat at
    # the death (where SR is naturally high) and ensures control metrics
    # compare aggressive openers against peer openers (Kohli, Babar) rather
    # than against the whole population including tailenders.
    #
    # For components that may be NaN for some players (e.g. acc_death_sr_mean
    # for batters who never batted in death overs), we fill with 0 AFTER
    # z-scoring.  A z-score of 0 means "population average" which is the
    # correct neutral value — the batter is neither rewarded nor penalised
    # for a phase they didn't participate in.
    # ──────────────────────────────────────────────────────────────────────

    # Choose z-score function based on whether position groups are enabled.
    # If a column doesn't exist (e.g. xR-derived columns when the xR model
    # wasn't run, or in synthetic test data), return a neutral zero Series
    # so the downstream weighted sum treats the missing component as average.
    if POSITION_GROUPS_ENABLED:

        def _zs(col_name: str) -> pd.Series:
            if col_name not in career.columns:
                return pd.Series(0.0, index=career.index)
            return _grouped_zscore(
                career, col_name, "position_group", MIN_POSITION_GROUP_SIZE
            )
    else:

        def _zs(col_name: str) -> pd.Series:
            if col_name not in career.columns:
                return pd.Series(0.0, index=career.index)
            return _zscore_series(career[col_name])

    # ── Merge career-level xR-derived metrics ──
    # CABI (Context-Adjusted Boundary Index) for Power dimension
    if cabi_data is not None and not cabi_data.empty:
        cabi = cabi_data.copy()
        if hasattr(cabi.get("batter_id", pd.Series()), "cat"):
            cabi["batter_id"] = cabi["batter_id"].astype(str)
        cabi_merge_cols = ["batter_id", "cabi", "boundary_residual_total"]
        available_cabi = [c for c in cabi_merge_cols if c in cabi.columns]
        career = career.merge(cabi[available_cabi], on="batter_id", how="left")
        career["cabi"] = career["cabi"].fillna(0.0)
        career["boundary_residual_total"] = career.get(
            "boundary_residual_total", pd.Series(0.0, index=career.index)
        ).fillna(0.0)
    else:
        career["cabi"] = 0.0
        career["boundary_residual_total"] = 0.0

    # Survival ratio for Control dimension
    if survival_rates is not None and not survival_rates.empty:
        surv = survival_rates.copy()
        if hasattr(surv.get("batter_id", pd.Series()), "cat"):
            surv["batter_id"] = surv["batter_id"].astype(str)
        surv_merge_cols = ["batter_id", "survival_ratio"]
        available_surv = [c for c in surv_merge_cols if c in surv.columns]
        career = career.merge(surv[available_surv], on="batter_id", how="left")
        career["survival_ratio"] = career["survival_ratio"].fillna(1.0)
    else:
        career["survival_ratio"] = 1.0

    # --- ACCELERATION z-scores ---
    z_acc_overall = _zs("acc_overall_sr_mean")
    z_acc_growth = _zs("acc_sr_growth_mean").fillna(0)
    z_acc_death = _zs("acc_death_sr_mean").fillna(0)
    z_acc_impact = _zs("acc_impact_mean")
    z_acc_xr = _zs("acc_runs_above_expected_mean")

    # xR-based leveraged RVA — primary context-adjusted signal
    # Falls back to 0 z-score (neutral) if xR model wasn't available
    z_acc_lrva = _zs("acc_leveraged_rva_mean").fillna(0)

    career["raw_acceleration"] = (
        ACC_WEIGHTS.get("overall_sr", 0.15) * z_acc_overall
        + ACC_WEIGHTS.get("sr_growth", 0.12) * z_acc_growth
        + ACC_WEIGHTS.get("death_sr", 0.10) * z_acc_death
        + ACC_WEIGHTS.get("impact", 0.13) * z_acc_impact
        + ACC_WEIGHTS.get("runs_above_expected", 0.25) * z_acc_xr
        + ACC_WEIGHTS.get("leveraged_rva", 0.25) * z_acc_lrva
    )

    # --- POWER z-scores ---
    z_pow_bpct = _zs("pow_boundary_pct_mean")
    z_pow_six = _zs("pow_six_rate_mean")
    z_pow_br_par = _zs("pow_boundary_rate_vs_par_mean")
    z_pow_peak = _zs("pow_peak_phase_sr_mean").fillna(0)
    z_pow_burst = _zs("pow_finishing_burst_mean").fillna(0)
    z_pow_impact = _zs("pow_power_impact_mean").fillna(0)

    # CABI z-score — primary context-adjusted boundary power signal
    z_pow_cabi = _zs("cabi")

    career["raw_power"] = (
        POW_WEIGHTS.get("boundary_pct", 0.12) * z_pow_bpct
        + POW_WEIGHTS.get("six_rate", 0.15) * z_pow_six
        + POW_WEIGHTS.get("boundary_rate_vs_par", 0.13) * z_pow_br_par
        + POW_WEIGHTS.get("peak_phase_sr", 0.10) * z_pow_peak
        + POW_WEIGHTS.get("finishing_burst", 0.15) * z_pow_burst
        + POW_WEIGHTS.get("power_impact", 0.10) * z_pow_impact
        + POW_WEIGHTS.get("cabi", 0.25) * z_pow_cabi
    )

    # --- Multiplicative average quality factor for ACC & POW ---
    # Asymmetric: steep penalty below median avg, gentle bonus above.
    avg_ratio = career["career_avg"] / AVG_QUALITY_REFERENCE
    avg_quality_factor = np.where(
        avg_ratio < 1.0,
        avg_ratio**AVG_QUALITY_EXPONENT_BELOW,  # steep penalty
        avg_ratio**AVG_QUALITY_EXPONENT_ABOVE,  # gentle bonus
    )
    avg_quality_factor = pd.Series(avg_quality_factor, index=career.index).clip(
        lower=AVG_QUALITY_FLOOR, upper=AVG_QUALITY_CEIL
    )
    career["raw_acceleration"] = career["raw_acceleration"] * avg_quality_factor
    career["raw_power"] = career["raw_power"] * avg_quality_factor

    # --- CONTROL z-scores ---
    z_ctrl_dot = _zs("ctrl_dot_pct_weighted_mean")
    z_ctrl_rot = _zs("ctrl_rotation_mean")
    z_ctrl_contrib = _zs("ctrl_contribution_mean")
    z_ctrl_scoring = _zs("ctrl_scoring_consistency_mean")

    # For avg proxy, use career_avg directly (better than per-innings mean
    # of runs, which penalises short innings).
    # Z-score within position groups so a finisher with avg 25 is compared
    # to other finishers, not to openers who typically average 30+.
    z_ctrl_avg = (
        _zs("career_avg")
        if POSITION_GROUPS_ENABLED
        else _zscore_series(career["career_avg"])
    )

    z_ctrl_dismiss = _zs("ctrl_dismissal_quality_mean")

    # Expected Survival Rate — primary control signal from hazard model.
    # survival_ratio > 1.0 = survives longer than expected (elite control).
    # Z-scored so it integrates proportionally with other components.
    z_ctrl_survival = _zs("survival_ratio")

    raw_ctrl = (
        CTRL_WEIGHTS.get("dot_pct_weighted", 0.12) * z_ctrl_dot
        + CTRL_WEIGHTS.get("rotation", 0.08) * z_ctrl_rot
        + CTRL_WEIGHTS.get("contribution", 0.10) * z_ctrl_contrib
        + CTRL_WEIGHTS.get("avg_proxy", 0.20) * z_ctrl_avg
        + CTRL_WEIGHTS.get("dismissal_quality", 0.10) * z_ctrl_dismiss
        + CTRL_WEIGHTS.get("scoring_consistency", 0.10) * z_ctrl_scoring
        + CTRL_WEIGHTS.get("survival_ratio", 0.30) * z_ctrl_survival
    )

    # ── Responsibility multiplier ─────────────────────────────────
    # Reward batters who face more balls per innings (true anchors /
    # accumulators).  A batter averaging 25+ balls/inn starts getting a
    # bonus, up to 15% for those averaging 75+ balls/inn.
    avg_balls_per_inn = np.where(
        career["innings_count"] > 0,
        career["total_balls"] / career["innings_count"],
        0.0,
    )
    # multiplier: 1.0 when avg_balls <= 25, linearly up to 1.15 at 75+
    responsibility_mult = np.clip(
        1.0 + (avg_balls_per_inn - 25.0) / 50.0 * 0.15,
        1.0,
        1.15,
    )
    career["raw_control"] = raw_ctrl * responsibility_mult

    career["is_provisional_bat"] = career["innings_count"] < min_innings

    return career


# ---------------------------------------------------------------------------
# Feature 6: Chase Master Index
# ---------------------------------------------------------------------------


def compute_chase_splits(bat_components: pd.DataFrame) -> pd.DataFrame:
    """
    Compute setting vs chasing career splits per batter.

    Setting = innings_num 1 (batting first), Chasing = innings_num 2.
    Returns one row per batter with setting/chasing aggregates and a
    ``chase_master_index`` (positive = better when chasing).

    Also computes a ``bat_first_index`` (positive = better when setting).

    Parameters
    ----------
    bat_components : pd.DataFrame
        Output of ``compute_batting_components()``.  Must contain
        ``innings_num``, ``batter_id``, ``batter``, and the component
        columns used for aggregation.

    Returns
    -------
    pd.DataFrame
        One row per (batter_id, batter) with setting/chasing columns
        and the chase master indices.
    """
    if not CHASE_MASTER_ENABLED:
        return pd.DataFrame()

    bc = bat_components.copy()

    for c in ["batter_id", "batter"]:
        if hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)

    setting = bc[bc["innings_num"] == 1]
    chasing = bc[bc["innings_num"] == 2]

    def _agg_composite(sub_df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        """Aggregate key metrics for a setting/chasing subset.

        In addition to the original component-level means, this now
        computes actual career SR and batting average for the subset so
        that the frontend can display meaningful numbers (not just
        differential indices).
        """
        agg_dict: dict[str, tuple[str, str]] = {
            "inn": ("match_id", "nunique"),
            "avg_sr_vs_par": ("acc_overall_sr", "mean"),
            "avg_impact": ("acc_impact", "mean"),
            "avg_runs": ("runs", "mean"),
            "avg_control": ("ctrl_scoring_consistency", "mean"),
            "total_runs": ("runs", "sum"),
        }

        # Only include columns that actually exist in the DataFrame
        if "balls_faced" in sub_df.columns:
            agg_dict["total_balls"] = ("balls_faced", "sum")
        if "is_out" in sub_df.columns:
            agg_dict["total_outs"] = ("is_out", "sum")

        grp = sub_df.groupby(["batter_id", "batter"]).agg(**agg_dict).reset_index()

        # Compute actual SR = total_runs / total_balls * 100
        if "total_balls" in grp.columns:
            grp["sr"] = np.where(
                grp["total_balls"] > 0,
                (grp["total_runs"] / grp["total_balls"] * 100).round(2),
                np.nan,
            )
        else:
            grp["sr"] = np.nan

        # Compute actual batting avg = total_runs / total_outs
        if "total_outs" in grp.columns:
            grp["avg"] = np.where(
                grp["total_outs"] > 0,
                (grp["total_runs"] / grp["total_outs"]).round(2),
                np.nan,
            )
        else:
            grp["avg"] = np.nan

        # Drop intermediate total columns before renaming
        grp = grp.drop(
            columns=[
                c
                for c in ["total_runs", "total_balls", "total_outs"]
                if c in grp.columns
            ]
        )

        rename_cols = [
            "inn",
            "avg_sr_vs_par",
            "avg_impact",
            "avg_runs",
            "avg_control",
            "sr",
            "avg",
        ]
        grp = grp.rename(
            columns={c: f"{prefix}_{c}" for c in rename_cols if c in grp.columns}
        )
        return grp

    set_agg = _agg_composite(setting, "setting")
    chase_agg = _agg_composite(chasing, "chasing")

    splits = set_agg.merge(chase_agg, on=["batter_id", "batter"], how="outer")

    # Apply minimum innings filter: null out metrics where the batter
    # doesn't have enough innings of either type for a reliable split.
    min_inn = CHASE_MASTER_MIN_INN
    _set_ok = splits["setting_inn"].fillna(0) >= min_inn
    _chase_ok = splits["chasing_inn"].fillna(0) >= min_inn
    _both_ok = _set_ok & _chase_ok

    # Chase Master Index = chasing composite - setting composite
    # Positive = better when chasing (the "Chase Master" signal).
    splits["chase_master_index"] = np.where(
        _both_ok,
        splits["chasing_avg_sr_vs_par"].fillna(0)
        - splits["setting_avg_sr_vs_par"].fillna(0),
        np.nan,
    )

    # Bat First Index = setting composite - chasing composite
    # Positive = better when setting a target.
    splits["bat_first_index"] = np.where(
        _both_ok,
        splits["setting_avg_sr_vs_par"].fillna(0)
        - splits["chasing_avg_sr_vs_par"].fillna(0),
        np.nan,
    )

    # Fuller version incorporating control stability
    splits["chase_master_full"] = np.where(
        _both_ok,
        (
            splits["chasing_avg_sr_vs_par"].fillna(0)
            - splits["setting_avg_sr_vs_par"].fillna(0)
        )
        + 0.5
        * (
            splits["chasing_avg_control"].fillna(0)
            - splits["setting_avg_control"].fillna(0)
        ),
        np.nan,
    )

    return splits
