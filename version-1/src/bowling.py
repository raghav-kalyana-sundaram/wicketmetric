"""
Bowling metrics: Accuracy, Control, Threat.

Built on the Expected Value (xR) framework from algorithm_update.md.
Every delivery is scored against a state-space baseline (expected runs per
ball given phase, wickets, venue difficulty).  The difference between actual
and expected outcomes — Run Value Added (RVA) — is the fundamental unit of
player evaluation for bowlers as well as batters.

Pipeline
--------
1. extract_bowling_spells          – Per (match, bowler) spell summaries from
                                     delivery-level data, including phase splits,
                                     economy differentials, and match context.
2. compute_run_distribution_entropy – Shannon entropy of per-ball run distribution
                                     for each spell (lower = more controlled).
3. compute_bowling_components       – Raw sub-component scores per spell for each
                                     of the three metrics.  NOW integrates xR-based
                                     Adjusted Bowling Leveraged Run Value and
                                     Wicket Hazard Added (WHA).
4. aggregate_bowling_careers        – Career-level aggregation with weighted means
                                     across all spells to produce composite raw
                                     scores ready for the rating system.

Metric Dimensions (per algorithm_update.md)
-------------------------------------------
**Accuracy** — Inverse standard deviation of run-yield distribution per over,
adjusted for Leverage Index.  A highly accurate bowler demonstrates tight
clustering of run yields.  Supplemented by dot ball % and extras penalty.

**Control** — Adjusted Bowling Leveraged Run Value: baseline run expectancy
for the match state minus actual runs conceded.  This is the xR-derived
signal that replaces simple economy-vs-par.  Positive residual = high control.

**Threat** — Wicket Hazard Added (WHA): how much a bowler elevates the
baseline probability of a wicket falling, controlling for phase, batter
quality, and venue.  Isolates "strike bowlers" who consistently break
partnerships.

Design notes
------------
- Economy is always judged relative to the match par run rate, so 8 rpo in a
  200-a-side game is valued differently from 8 rpo in a 120-a-side game.
- **Adjusted Bowling Leveraged Run Value** from the xR model is now a primary
  component of Control, replacing the simple economy_vs_par where possible.
- **Wicket Hazard Added (WHA)** from the hazard model is now a primary
  component of Threat, isolating wicket-taking potency independent of run
  prevention.
- **Run-yield variance** (inverse) is now a primary Accuracy signal — a
  bowler who consistently concedes 0-1 runs per ball is more accurate than
  one who alternates boundaries and dots.
- "economy_vs_others" compares this bowler to the other bowlers in the *same*
  innings — the user's "run rate change when a bowler comes on" concept.
- Wides and no-balls are the bowler's fault and directly penalise both
  Accuracy and Control. Leg-byes and byes do not.
- Leverage Index from the WP model weights high-pressure deliveries more
  heavily, so runs prevented in critical moments contribute more to ratings.
- **Wicket quality**: top-order wickets (positions 1-3) are worth ~1.4-1.5×
  a standard wicket, while tailender wickets (9-11) are worth ~0.3-0.5×.
- **Volume scaling**: bowlers with more matches get a meaningful advantage.
- All sub-components are z-score normalised before compositing.
- Phase stats require a minimum number of legal balls bowled (MIN_PHASE_BALLS)
  to be considered valid; otherwise they are treated as missing.
"""

import numpy as np
import pandas as pd

from src.config import cfg

# Recency / time-decay constants
RECENCY_ENABLED: bool = cfg("recency.enabled", default=True)
RECENCY_HALF_LIFE_DAYS: float = cfg("recency.half_life_days", default=730.0)
RECENCY_MIN_WEIGHT: float = cfg("recency.min_weight", default=0.05)

# ICC T20I ranking-based opposition weighting (shared with batting module)
ICC_RANKING_ENABLED: bool = cfg("icc_ranking.enabled", default=True)

# ---------------------------------------------------------------------------
# Constants — all read from config.yaml (with hardcoded fallbacks)
# ---------------------------------------------------------------------------

# Minimum legal balls bowled in a phase for that phase's stats to be reliable.
MIN_PHASE_BALLS: int = cfg("pipeline.min_phase_balls_bowling", default=6)

# ---------------------------------------------------------------------------
# Bowling phase-group comparisons
# ---------------------------------------------------------------------------
# Bowlers are classified by their primary bowling phase so that death bowlers
# are compared to other death bowlers, powerplay specialists to PP specialists,
# etc.  A death bowler with economy 9 where death par is 10.5 is performing
# far better than a PP bowler with economy 9 where PP par is 7.5.

PHASE_GROUPS_ENABLED: bool = cfg("bowling_phase_groups.enabled", default=True)
MIN_PHASE_GROUP_SIZE: int = cfg("bowling_phase_groups.min_group_size", default=20)

# Blend weight for within-group vs population z-scores (same rationale as
# batting — see batting.py GROUP_ZSCORE_BLEND_ALPHA).
# α = 1.0 → pure within-group (old behaviour, cross-group incomparable)
# α = 0.0 → pure population (no phase adjustment at all)
# α = 0.6 → 60% within-group + 40% population (recommended)
PHASE_ZSCORE_BLEND_ALPHA: float = cfg("bowling_phase_groups.blend_alpha", default=0.6)

# ---------------------------------------------------------------------------
# Helper: ensure category columns are plain strings for groupby operations
# ---------------------------------------------------------------------------


def _decat(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Convert categorical columns to plain strings in-place and return df."""
    for c in cols:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].astype(str)
    return df


# ---------------------------------------------------------------------------
# Z-score normalisation
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


def _grouped_zscore_bowl(
    career_df: pd.DataFrame,
    col: str,
    group_col: str = "phase_group",
    min_group_size: int = MIN_PHASE_GROUP_SIZE,
    blend_alpha: float = PHASE_ZSCORE_BLEND_ALPHA,
) -> pd.Series:
    """
    Blended z-score: within-group + population, weighted by ``blend_alpha``.

    Pure within-group z-scoring makes scores incomparable across phase
    groups (e.g. a death bowler with economy 9 where death par is 10.5
    would get a very different z-score than a PP bowler with economy 9
    where PP par is 7.5, even though both are economy-9 bowlers).

    The blend preserves the phase-aware comparison while keeping
    cross-group scores on a comparable scale::

        blended = α × within_group_z + (1 − α) × population_z

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

    # Fill any remaining NaN (safety net)
    result = result.fillna(pop_zscore)
    return result


def classify_phase_group(
    pp_balls: float, middle_balls: float, death_balls: float
) -> str:
    """
    Classify a bowler into a phase group based on workload distribution.

    The group is determined by which phase has the plurality of legal balls.

    Returns one of: "pp_heavy", "middle_heavy", "death_heavy".
    """
    phases = {
        "pp_heavy": pp_balls,
        "middle_heavy": middle_balls,
        "death_heavy": death_balls,
    }
    return max(phases, key=phases.get)  # type: ignore[arg-type]


def _compute_phase_par_rr(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-match, per-phase par run rates (runs per over) for bowling.

    Returns a DataFrame keyed on match_id with columns:
        pp_par_rr, middle_par_rr, death_par_rr
    """
    legal = df[df["is_legal"]].copy()
    _decat(legal, ["match_id", "phase"])

    phase_stats = (
        legal.groupby(["match_id", "phase"])
        .agg(
            phase_total_runs=("total_runs", "sum"),
            phase_balls=("is_legal", "sum"),
        )
        .reset_index()
    )

    phase_stats["phase_overs"] = phase_stats["phase_balls"] / 6.0
    phase_stats["phase_rr"] = np.where(
        phase_stats["phase_overs"] > 0,
        phase_stats["phase_total_runs"] / phase_stats["phase_overs"],
        np.nan,
    )

    pivoted = phase_stats.pivot_table(
        index="match_id", columns="phase", values="phase_rr"
    ).reset_index()

    rename_map = {}
    for col in pivoted.columns:
        if col == "powerplay":
            rename_map[col] = "pp_par_rr"
        elif col == "middle":
            rename_map[col] = "middle_par_rr"
        elif col == "death":
            rename_map[col] = "death_par_rr"
    pivoted = pivoted.rename(columns=rename_map)

    # Ensure all columns exist even if some matches lack a phase
    for col in ["pp_par_rr", "middle_par_rr", "death_par_rr"]:
        if col not in pivoted.columns:
            pivoted[col] = np.nan

    return pivoted[["match_id", "pp_par_rr", "middle_par_rr", "death_par_rr"]]


# ---------------------------------------------------------------------------
# Component weights (exposed here for easy tuning)
# ---------------------------------------------------------------------------

# REWORKED per algorithm_update.md:
#   - Accuracy now centres on run-yield variance (inverse) as the primary
#     signal, plus dot ball % and economy vs par.  Captures tight clustering
#     of run yields (the "accuracy = consistency" concept).
#   - Control now uses Adjusted Bowling Leveraged Run Value from xR as the
#     primary signal, plus economy vs others in the same match.
#   - Threat now uses Wicket Hazard Added (WHA) as the primary signal,
#     isolating wicket-taking potency independent of run prevention.

ACC_WEIGHTS: dict[str, float] = cfg(
    "bowling_accuracy_weights",
    default={
        "economy_vs_par": 0.20,
        "dot_pct": 0.20,
        "extras_penalty": 0.15,
        "boundary_penalty": 0.15,
        "run_yield_variance": 0.30,
    },
)

# Control weights: Adjusted Bowling Leveraged Run Value from xR is the
# primary signal — it measures how much a bowler suppresses the expected
# run value at each match state.  Economy vs others remains important
# as it isolates performance within the SAME conditions.
CTRL_WEIGHTS: dict[str, float] = cfg(
    "bowling_control_weights",
    default={
        "entropy": 0.10,
        "extras": 0.08,
        "vs_others": 0.22,
        "extras_pct": 0.05,
        "phase_consistency": 0.10,
        "economy_vs_par": 0.15,
        "bowling_rv": 0.30,
    },
)

# Threat weights: Wicket Hazard Added (WHA) is the primary signal —
# it isolates a bowler's ability to take wickets above the baseline
# probability for their match state.  Quality wickets (top-order)
# still contribute, as do sustained pressure (dots) and bowling SR.
THREAT_WEIGHTS: dict[str, float] = cfg(
    "bowling_threat_weights",
    default={
        "wickets": 0.10,
        "quality_wickets": 0.10,
        "sr": 0.10,
        "bowled_lbw": 0.10,
        "pressure": 0.15,
        "dots": 0.15,
        "wha": 0.30,
    },
)

# Volume scaling constants for bowling.
# Players with more matches get a meaningful advantage.  The volume factor
# is applied post-percentile to all three scores:
#   factor = BOWL_VOLUME_BASE + (1 - BOWL_VOLUME_BASE) * clip(matches / BOWL_VOLUME_REF, 0, 1) ** BOWL_VOLUME_CURVE
#
# Players who exceed BOWL_VOLUME_REF get a beyond-reference bonus:
#   beyond_bonus = BOWL_VOLUME_BEYOND_MAX * clip((matches - ref) / ref, 0, 1)
#
# With defaults (base=0.70, ref=100, curve=0.5, beyond_max=0.06):
#   10 matches → factor ~0.79   (21% penalty)
#   19 matches → factor ~0.83   (17% penalty)
#   30 matches → factor ~0.86   (14% penalty)
#   50 matches → factor ~0.91   ( 9% penalty)
#   75 matches → factor ~0.96   ( 4% penalty)
#   100 matches → factor 1.00   (no penalty)
#   120 matches → factor 1.01   ( 1% bonus)
#   150 matches → factor 1.03   ( 3% bonus)
#   200+ matches → factor 1.06  ( 6% bonus, max)
BOWL_VOLUME_BASE: float = cfg("bowling_volume.base", default=0.70)
BOWL_VOLUME_REF: float = cfg("bowling_volume.ref", default=100.0)
BOWL_VOLUME_CURVE: float = cfg("bowling_volume.curve", default=0.5)
BOWL_VOLUME_BEYOND_MAX: float = cfg("bowling_volume.beyond_max", default=0.06)


# ---------------------------------------------------------------------------
# Step 1: Extract per-spell bowling stats
# ---------------------------------------------------------------------------


def extract_bowling_spells(
    df: pd.DataFrame,
    innings_ctx: pd.DataFrame,
    phase_par_rr: pd.DataFrame | None = None,
    team_quality: pd.DataFrame | None = None,
    franchise_season_ratings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build one row per (match, innings, bowler) with full spell statistics.

    Parameters
    ----------
    df : pd.DataFrame
        Delivery-level DataFrame from the parser.
    innings_ctx : pd.DataFrame
        Innings-level context from context.build_full_context().
    phase_par_rr : pd.DataFrame, optional
        Per-match phase par run rates.
    team_quality : pd.DataFrame, optional
        Output of compute_team_quality().  If provided, an
        ``opp_team_quality`` column is added representing the strength
        of the opposing (batting) team, and a ``team_quality_weight``
        is multiplied into the spell weight.

    Returns
    -------
    pd.DataFrame with economy, dot %, phase splits, economy vs others, etc.
    """
    bowl = df.copy()
    _decat(
        bowl,
        [
            "match_id",
            "bowler_id",
            "bowler",
            "bowling_team",
            "batting_team",
            "phase",
            "wicket_kind",
        ],
    )

    # ── Per-spell aggregates ──
    grp_keys = ["match_id", "innings_num", "bowler_id", "bowler", "bowling_team"]
    grp = bowl.groupby(grp_keys, observed=True)

    agg = grp.agg(
        total_deliveries=("total_runs", "size"),
        legal_balls=("is_legal", "sum"),
        runs_conceded=("total_runs", "sum"),
        wickets=("is_wicket", "sum"),
        dots_bowler=("is_dot_bowler", "sum"),
        fours_conceded=("is_four", "sum"),
        sixes_conceded=("is_six", "sum"),
        wides_count=("is_wide", "sum"),
        noballs_count=("is_noball", "sum"),
        wide_runs=("wide_runs", "sum"),
        noball_runs=("noball_runs", "sum"),
        legbye_runs=("legbye_runs", "sum"),
        bye_runs=("bye_runs", "sum"),
        date=("date", "first"),
        batting_team=("batting_team", "first"),
    ).reset_index()

    # Overs bowled
    agg["overs_bowled"] = agg["legal_balls"] / 6.0

    # Economy rate
    agg["economy"] = np.where(
        agg["overs_bowled"] > 0,
        agg["runs_conceded"] / agg["overs_bowled"],
        0.0,
    )

    # Bowling strike rate (legal balls per wicket) — NaN if no wickets
    agg["strike_rate_bowl"] = np.where(
        agg["wickets"] > 0,
        agg["legal_balls"] / agg["wickets"],
        np.nan,
    )

    # Dot ball % (of legal deliveries)
    agg["dot_pct"] = np.where(
        agg["legal_balls"] > 0,
        agg["dots_bowler"] / agg["legal_balls"],
        0.0,
    )

    # Wides + no-balls per over
    agg["extras_per_over"] = np.where(
        agg["overs_bowled"] > 0,
        (agg["wides_count"] + agg["noballs_count"]) / agg["overs_bowled"],
        0.0,
    )

    # Boundary % conceded (boundary runs / total runs conceded)
    agg["boundary_pct_conceded"] = np.where(
        agg["runs_conceded"] > 0,
        (agg["fours_conceded"] * 4 + agg["sixes_conceded"] * 6) / agg["runs_conceded"],
        0.0,
    )

    # Bowler-responsible extras as fraction of runs
    bowler_extras = agg["wide_runs"] + agg["noball_runs"]
    agg["bowler_extras_pct"] = np.where(
        agg["runs_conceded"] > 0,
        bowler_extras / agg["runs_conceded"],
        0.0,
    )

    # ── Phase-level breakdowns ──
    for phase_name in ("powerplay", "middle", "death"):
        phase_df = bowl[bowl["phase"] == phase_name]
        phase_grp = phase_df.groupby(
            ["match_id", "innings_num", "bowler_id"], observed=True
        )

        phase_agg = phase_grp.agg(
            **{
                f"{phase_name}_legal_balls": ("is_legal", "sum"),
                f"{phase_name}_runs": ("total_runs", "sum"),
                f"{phase_name}_wickets": ("is_wicket", "sum"),
                f"{phase_name}_dots": ("is_dot_bowler", "sum"),
                f"{phase_name}_wides": ("is_wide", "sum"),
                f"{phase_name}_noballs": ("is_noball", "sum"),
                f"{phase_name}_fours": ("is_four", "sum"),
                f"{phase_name}_sixes": ("is_six", "sum"),
            }
        ).reset_index()

        phase_agg[f"{phase_name}_overs"] = phase_agg[f"{phase_name}_legal_balls"] / 6.0

        # Only compute phase economy if enough balls bowled
        phase_agg[f"{phase_name}_economy"] = np.where(
            phase_agg[f"{phase_name}_legal_balls"] >= MIN_PHASE_BALLS,
            phase_agg[f"{phase_name}_runs"] / phase_agg[f"{phase_name}_overs"],
            np.nan,
        )
        phase_agg[f"{phase_name}_dot_pct"] = np.where(
            phase_agg[f"{phase_name}_legal_balls"] >= MIN_PHASE_BALLS,
            phase_agg[f"{phase_name}_dots"] / phase_agg[f"{phase_name}_legal_balls"],
            np.nan,
        )

        agg = agg.merge(
            phase_agg,
            on=["match_id", "innings_num", "bowler_id"],
            how="left",
        )

    # ── Economy vs other bowlers in the same innings ──
    innings_totals = (
        agg.groupby(["match_id", "innings_num"])
        .agg(
            innings_total_runs=("runs_conceded", "sum"),
            innings_total_overs=("overs_bowled", "sum"),
        )
        .reset_index()
    )

    agg = agg.merge(innings_totals, on=["match_id", "innings_num"], how="left")

    other_runs = agg["innings_total_runs"] - agg["runs_conceded"]
    other_overs = agg["innings_total_overs"] - agg["overs_bowled"]
    agg["other_bowlers_economy"] = np.where(
        other_overs > 0, other_runs / other_overs, agg["economy"]
    )
    # Negative = better than others (lower economy)
    agg["economy_vs_others"] = agg["economy"] - agg["other_bowlers_economy"]

    # ── Join match / innings context ──
    # Rename columns that collide with the bowler-spell columns before merging.
    ctx = innings_ctx.copy()
    _decat(ctx, ["match_id", "batting_team"])
    ctx = ctx.rename(
        columns={
            "total_runs": "innings_total_runs_ctx",
            "legal_balls": "innings_legal_balls",
        }
    )

    ctx_cols = [
        "match_id",
        "innings_num",
        "batting_team",
        "innings_total_runs_ctx",
        "innings_legal_balls",
        "innings_sr",
        "match_par_sr",
        "match_par_rr",
        "match_boundary_rate",
        "match_dot_pct",
        "match_wickets_per_ball",
    ]
    available_ctx = [c for c in ctx_cols if c in ctx.columns]

    agg = agg.merge(
        ctx[available_ctx],
        on=["match_id", "innings_num", "batting_team"],
        how="left",
    )

    # Context-adjusted economy (ratio-based: <1 means better than par)
    match_par_rr = (
        agg["match_par_rr"].fillna(agg["match_par_rr"].mean()).clip(lower=0.1)
    )
    agg["economy_ratio_par"] = agg["economy"] / match_par_rr
    # Also keep the difference for backwards compat
    agg["economy_vs_par"] = agg["economy"] - match_par_rr

    # ── Phase-weighted economy vs par ──────────────────────────────────
    # Instead of comparing overall economy to overall match par, compute a
    # weighted economy_vs_par where each phase uses its own par run rate.
    # This correctly values a death bowler with economy 9 against death
    # par 10.5 as elite, rather than comparing to overall par ~7.5.
    if phase_par_rr is not None:
        ppr = phase_par_rr.copy()
        _decat(ppr, ["match_id"])
        agg = agg.merge(ppr, on="match_id", how="left")
    else:
        # Compute phase par RR from the delivery data if not passed in
        ppr = _compute_phase_par_rr(df)
        agg = agg.merge(ppr, on="match_id", how="left")

    # Fill missing phase pars with overall match par
    for phase_par_col in ["pp_par_rr", "middle_par_rr", "death_par_rr"]:
        if phase_par_col in agg.columns:
            agg[phase_par_col] = agg[phase_par_col].fillna(match_par_rr)

    # For each spell, compute phase-weighted economy_ratio_par:
    #   For each phase the bowler bowled in, compute economy_ratio = phase_economy / phase_par
    #   Weight by legal balls in that phase, resulting in a single blended ratio.
    pp_balls = agg.get("powerplay_legal_balls", pd.Series(0, index=agg.index)).fillna(0)
    mid_balls = agg.get("middle_legal_balls", pd.Series(0, index=agg.index)).fillna(0)
    death_balls_col = agg.get(
        "death_legal_balls", pd.Series(0, index=agg.index)
    ).fillna(0)

    pp_econ = agg.get("powerplay_economy", pd.Series(np.nan, index=agg.index))
    mid_econ = agg.get("middle_economy", pd.Series(np.nan, index=agg.index))
    death_econ = agg.get("death_economy", pd.Series(np.nan, index=agg.index))

    pp_par = agg["pp_par_rr"].clip(lower=0.1)
    mid_par = agg["middle_par_rr"].clip(lower=0.1)
    death_par = agg["death_par_rr"].clip(lower=0.1)

    # Phase economy ratios (NaN where not enough balls or economy is NaN)
    pp_ratio = np.where(pp_econ.notna(), pp_econ / pp_par, np.nan)
    mid_ratio = np.where(mid_econ.notna(), mid_econ / mid_par, np.nan)
    death_ratio = np.where(death_econ.notna(), death_econ / death_par, np.nan)

    # Weighted blend: weight by legal balls in each phase
    weighted_ratio_num = np.nansum(
        [
            np.where(np.isnan(pp_ratio), 0, pp_ratio * pp_balls),
            np.where(np.isnan(mid_ratio), 0, mid_ratio * mid_balls),
            np.where(np.isnan(death_ratio), 0, death_ratio * death_balls_col),
        ],
        axis=0,
    )
    weighted_ratio_den = np.nansum(
        [
            np.where(np.isnan(pp_ratio), 0, pp_balls),
            np.where(np.isnan(mid_ratio), 0, mid_balls),
            np.where(np.isnan(death_ratio), 0, death_balls_col),
        ],
        axis=0,
    )

    safe_den = np.where(weighted_ratio_den > 0, weighted_ratio_den, 1.0)
    phase_weighted_ratio = np.where(
        weighted_ratio_den > 0,
        weighted_ratio_num / safe_den,
        agg["economy_ratio_par"],  # fallback to overall if no phase data
    )
    agg["phase_weighted_economy_ratio_par"] = phase_weighted_ratio

    # ── Recency / time-decay weighting ──
    # More recent spells count for more in career aggregation.
    # weight = max(2^(-(days_since / half_life)), min_weight)
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
        else:
            agg["recency_weight"] = 1.0
    else:
        agg["recency_weight"] = 1.0

    # ── Team quality weighting ──
    # Bowling against a stronger batting team is worth more.  This mirrors
    # the team quality weighting used in batting innings extraction.
    if team_quality is not None:
        tq = team_quality.copy()
        if hasattr(tq.get("team", pd.Series()), "cat"):
            tq["team"] = tq["team"].astype(str)

        # The batting team's quality determines the weight of this spell.
        agg = agg.merge(
            tq.rename(
                columns={"team": "batting_team", "team_quality": "opp_team_quality"}
            ),
            on="batting_team",
            how="left",
        )
        agg["opp_team_quality"] = agg["opp_team_quality"].fillna(0.0)

        from src.batting import TEAM_QUALITY_CLIP, TEAM_QUALITY_SCALE

        agg["team_quality_weight"] = 1.0 + np.clip(
            agg["opp_team_quality"] * TEAM_QUALITY_SCALE,
            -TEAM_QUALITY_CLIP,
            TEAM_QUALITY_CLIP,
        )
    else:
        agg["opp_team_quality"] = 0.0
        agg["team_quality_weight"] = 1.0

    # ── ICC T20I ranking-based opposition weighting ──
    # A bowler's spell against a higher-ranked batting side is worth more.
    # For franchise leagues (IPL), uses per-season franchise ratings instead
    # of static ICC rankings.
    if franchise_season_ratings is not None and "batting_team" in agg.columns:
        from src.batting import compute_franchise_ranking_weights

        agg["icc_ranking_weight"] = compute_franchise_ranking_weights(
            agg["batting_team"], agg["date"], franchise_season_ratings
        )
    elif ICC_RANKING_ENABLED and "batting_team" in agg.columns:
        from src.batting import compute_icc_ranking_weights

        agg["icc_ranking_weight"] = compute_icc_ranking_weights(agg["batting_team"])
    else:
        agg["icc_ranking_weight"] = 1.0

    # ── Match quality weighting (symmetric — both teams' rankings) ──
    if franchise_season_ratings is not None and "batting_team" in agg.columns:
        from src.batting import compute_franchise_match_quality_weights

        agg["match_quality_weight"] = compute_franchise_match_quality_weights(
            agg["bowling_team"],
            agg["batting_team"],
            agg["date"],
            franchise_season_ratings,
        )
    elif ICC_RANKING_ENABLED and "batting_team" in agg.columns:
        from src.batting import (
            MATCH_QUALITY_ENABLED,
            compute_match_quality_weights,
        )

        if MATCH_QUALITY_ENABLED:
            agg["match_quality_weight"] = compute_match_quality_weights(
                agg["bowling_team"], agg["batting_team"]
            )
        else:
            agg["match_quality_weight"] = 1.0
    else:
        agg["match_quality_weight"] = 1.0

    # ── Raw opponent rating (for competition quality gate at career level) ──
    # For franchise leagues, uses per-season franchise ratings instead of
    # static ICC rankings.
    if franchise_season_ratings is not None and "batting_team" in agg.columns:
        from src.batting import compute_franchise_opp_icc_rating

        agg["opp_icc_rating"] = compute_franchise_opp_icc_rating(
            agg["batting_team"], agg["date"], franchise_season_ratings
        )
    elif "batting_team" in agg.columns:
        from src.batting import ICC_RANKING_DEFAULT_RATING, ICC_RANKING_RATINGS

        agg["opp_icc_rating"] = (
            agg["batting_team"]
            .map(ICC_RANKING_RATINGS)
            .fillna(ICC_RANKING_DEFAULT_RATING)
        )
    else:
        from src.batting import ICC_RANKING_DEFAULT_RATING

        agg["opp_icc_rating"] = ICC_RANKING_DEFAULT_RATING

    # Spell weight combines recency, ICC ranking, team quality, and match quality
    agg["spell_weight"] = (
        agg["recency_weight"]
        * agg["icc_ranking_weight"]
        * agg["team_quality_weight"]
        * agg["match_quality_weight"]
    )

    return agg


# ---------------------------------------------------------------------------
# Step 2: Run distribution entropy per spell
# ---------------------------------------------------------------------------


def compute_run_distribution_entropy(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each bowler spell, compute the Shannon entropy of the per-legal-ball
    run distribution.

    Low entropy with low runs = very controlled (lots of dots, occasional single).
    High entropy = runs spread evenly across many values (less controlled).

    Returns
    -------
    DataFrame keyed on (match_id, innings_num, bowler_id) with column 'run_entropy'.
    """
    legal = df[df["is_legal"]].copy()
    _decat(legal, ["match_id", "bowler_id"])

    def _entropy(runs_series: pd.Series) -> float:
        if len(runs_series) == 0:
            return 0.0
        counts = runs_series.value_counts(normalize=True)
        # Shannon entropy in bits
        probs = counts.values
        probs = probs[probs > 0]
        return float(-(probs * np.log2(probs)).sum())

    entropy_df = (
        legal.groupby(["match_id", "innings_num", "bowler_id"], observed=True)
        .agg(run_entropy=("total_runs", _entropy))
        .reset_index()
    )

    return entropy_df


# ---------------------------------------------------------------------------
# Step 3: Compute raw metric components per spell
# ---------------------------------------------------------------------------


def compute_bowling_components(
    bowl_spells: pd.DataFrame,
    entropy_df: pd.DataFrame,
    wicket_quality: pd.DataFrame | None = None,
    scored_deliveries: pd.DataFrame | None = None,
    wha_data: pd.DataFrame | None = None,
    bowling_rv_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Compute the raw sub-component values for each bowling metric per spell.

    All components are oriented so that **higher = better**.
    Components that are naturally "lower is better" (economy, extras, entropy)
    are negated here.

    Phase stats that don't meet MIN_PHASE_BALLS are left as NaN and will be
    excluded from career aggregation (weighted mean ignores NaN).

    Uses **phase-weighted economy vs par** when available: a bowler's economy
    in each phase is compared to that phase's par run rate, then blended by
    workload.  This correctly values death bowlers whose economy of 9 is
    elite vs death par of 10.5, rather than penalising them vs overall par 7.5.

    NEW in algorithm rework:
    - Accuracy uses run-yield variance (inverse) as a primary signal.
    - Control integrates Adjusted Bowling Leveraged Run Value from xR.
    - Threat integrates Wicket Hazard Added (WHA) from the hazard model.

    Parameters
    ----------
    bowl_spells : pd.DataFrame
        Output of extract_bowling_spells().
    entropy_df : pd.DataFrame
        Output of compute_run_distribution_entropy().
    wicket_quality : pd.DataFrame, optional
        Output of compute_wicket_quality() from batting module.
        If provided, quality-weighted wickets feed into the Threat metric.
    scored_deliveries : pd.DataFrame, optional
        Deliveries with ``run_value_added`` column (from expected_value
        scoring).  Used to compute per-spell bowling RV aggregates.
    wha_data : pd.DataFrame, optional
        Output of expected_value.compute_wicket_hazard_added().
        Keyed on bowler_id.  Used for Threat dimension at career level.
    bowling_rv_data : pd.DataFrame, optional
        Output of expected_value.compute_bowling_run_value().
        Keyed on bowler_id.  Used for Control dimension at career level.
    """
    df = bowl_spells.merge(
        entropy_df,
        on=["match_id", "innings_num", "bowler_id"],
        how="left",
    )
    df["run_entropy"] = df["run_entropy"].fillna(2.0)  # moderate default

    # =====================================================================
    # ACCURACY components
    # =====================================================================

    # Ac1: Context-adjusted economy (ratio-based, inverted: lower econ = better)
    #      Uses phase-weighted economy ratio when available so that each phase
    #      is judged against its own par, not overall match par.
    econ_ratio_col = (
        "phase_weighted_economy_ratio_par"
        if "phase_weighted_economy_ratio_par" in df.columns
        else "economy_ratio_par"
    )
    df["acc_economy_vs_par"] = 1.0 - df[econ_ratio_col].fillna(1.0)

    # Ac2: Dot ball %
    df["acc_dot_pct"] = df["dot_pct"]

    # Ac3: Wides + no-balls per over — negated
    df["acc_extras_penalty"] = -df["extras_per_over"]

    # Ac4: Boundary % conceded — negated
    df["acc_boundary_penalty"] = -df["boundary_pct_conceded"]

    # Ac5: Run-yield variance (inverse) — the algorithm document's primary
    #      Accuracy signal.  A highly accurate bowler demonstrates tight
    #      clustering of run yields, consistently conceding singles or dots.
    #      An inaccurate bowler alternates between boundaries and dots
    #      (high variance).
    #      Computed per spell from the spell-level run distribution.
    #      Uses negative std dev so higher = better (lower variance).
    #      If scored_deliveries available, compute from actual per-ball data;
    #      otherwise approximate from spell-level stats.
    if scored_deliveries is not None and "total_runs" in scored_deliveries.columns:
        _sd = scored_deliveries.copy()
        for c in ["match_id", "bowler_id"]:
            if hasattr(_sd[c], "cat"):
                _sd[c] = _sd[c].astype(str)
        # Compute per-delivery run yield std dev per spell
        run_yield_std = (
            _sd.groupby(["match_id", "innings_num", "bowler_id"])["total_runs"]
            .std()
            .reset_index(name="_run_yield_std")
        )
        _decat(run_yield_std, ["match_id", "bowler_id"])
        df = df.merge(
            run_yield_std, on=["match_id", "innings_num", "bowler_id"], how="left"
        )
        df["acc_run_yield_variance"] = -(df["_run_yield_std"].fillna(2.0))
        df.drop(columns=["_run_yield_std"], inplace=True, errors="ignore")
    else:
        # Approximate: use boundary_pct_conceded as a proxy for variance
        # High boundary % = high variance in run yield
        df["acc_run_yield_variance"] = -(
            df["boundary_pct_conceded"].fillna(0) * 2.0
            + df["extras_per_over"].fillna(0) * 0.5
        )

    # =====================================================================
    # CONTROL components
    # =====================================================================

    # Co1: Run distribution entropy — negated (lower entropy = more controlled)
    df["ctrl_entropy"] = -df["run_entropy"]

    # Co2: Wides + no-balls per over — negated
    df["ctrl_extras"] = -df["extras_per_over"]

    # Co3: Economy vs other bowlers in the same match — THE key control signal.
    #      economy_vs_others < 0 means better than teammates → −(negative) = positive
    #      This is the best measure of bowling control because it compares
    #      performance in the SAME conditions (same pitch, same opposition).
    df["ctrl_vs_others"] = -df["economy_vs_others"]

    # Co4: Bowler-responsible extras as % of runs — negated
    df["ctrl_extras_pct"] = -df["bowler_extras_pct"]

    # Co5: Phase consistency (low variance in economy across phases)
    #      Only consider phases with valid data (MIN_PHASE_BALLS met).
    #      Uses NaN-aware std so phases without enough data are simply skipped.
    phase_econs = df[["powerplay_economy", "middle_economy", "death_economy"]]
    df["ctrl_phase_consistency"] = -phase_econs.std(axis=1, skipna=True).fillna(0)

    # Co6: Context-adjusted economy (phase-weighted: each phase vs its own par)
    #      A bowler who consistently beats the phase-specific par shows control.
    df["ctrl_economy_vs_par"] = 1.0 - df[econ_ratio_col].fillna(1.0)

    # Co7: Adjusted Bowling Leveraged Run Value — xR-derived primary Control signal.
    #      Measures how much a bowler suppresses the expected run value at each
    #      match state.  Positive = bowler restricted scoring below expected.
    #      Per-spell aggregation from scored deliveries.
    if scored_deliveries is not None and "run_value_added" in scored_deliveries.columns:
        _sd = scored_deliveries.copy()
        for c in ["match_id", "bowler_id"]:
            if hasattr(_sd[c], "cat"):
                _sd[c] = _sd[c].astype(str)
        # For bowlers: negative RVA = good (conceded less than expected)
        # So we negate to make positive = good
        bowl_rv_spell = (
            _sd.groupby(["match_id", "innings_num", "bowler_id"])
            .agg(
                spell_bowling_rv=("run_value_added", "sum"),
                spell_bowling_rv_mean=("run_value_added", "mean"),
                spell_rv_balls=("run_value_added", "count"),
            )
            .reset_index()
        )
        _decat(bowl_rv_spell, ["match_id", "bowler_id"])
        # Negate: for bowlers, conceding LESS than expected is positive
        bowl_rv_spell["spell_bowling_rv"] = -bowl_rv_spell["spell_bowling_rv"]
        bowl_rv_spell["spell_bowling_rv_mean"] = -bowl_rv_spell["spell_bowling_rv_mean"]

        df = df.merge(
            bowl_rv_spell, on=["match_id", "innings_num", "bowler_id"], how="left"
        )
        df["ctrl_bowling_rv"] = df["spell_bowling_rv_mean"].fillna(0.0)
    else:
        df["ctrl_bowling_rv"] = 0.0
        df["spell_bowling_rv"] = 0.0
        df["spell_bowling_rv_mean"] = 0.0

    # =====================================================================
    # THREAT components
    # =====================================================================

    # T1: Wickets taken in the spell (raw count)
    df["threat_wickets"] = df["wickets"]

    # T1b: Quality-weighted wickets (top-order worth more than tailenders)
    if wicket_quality is not None:
        wq = wicket_quality.copy()
        for c in ["match_id", "bowler_id"]:
            if c in wq.columns and hasattr(wq[c], "cat"):
                wq[c] = wq[c].astype(str)
        df = df.merge(
            wq[
                [
                    "match_id",
                    "innings_num",
                    "bowler_id",
                    "quality_wickets",
                    "avg_wicket_quality",
                ]
            ],
            on=["match_id", "innings_num", "bowler_id"],
            how="left",
        )
        df["quality_wickets"] = df["quality_wickets"].fillna(0.0)
        df["avg_wicket_quality"] = df["avg_wicket_quality"].fillna(0.0)
    else:
        # Fallback: quality_wickets = raw wickets (unweighted)
        df["quality_wickets"] = df["wickets"].astype(float)
        df["avg_wicket_quality"] = np.where(df["wickets"] > 0, 1.0, 0.0)

    df["threat_quality_wickets"] = df["quality_wickets"]

    # T2: Bowling strike rate — inverted (fewer balls per wicket = better)
    #     No wickets → NaN (not penalised, just no contribution)
    df["threat_sr"] = np.where(
        df["strike_rate_bowl"].notna() & (df["strike_rate_bowl"] > 0),
        -df["strike_rate_bowl"],
        np.nan,
    )

    # T3: Bowled / LBW %
    #     Computed at career level — per-spell samples are too small.
    #     Placeholder column filled later.

    # T4: Economy vs others (pressure differential)
    df["threat_pressure"] = -df["economy_vs_others"]

    # T5: Dot ball % (sustained pressure creation)
    df["threat_dots"] = df["dot_pct"]

    # T6: Wicket Hazard Added (WHA) per spell — xR-derived primary Threat signal.
    #     Measures how much this bowler elevates the baseline probability of
    #     taking a wicket.  This is a career-level metric from the hazard model,
    #     stored here as a constant per spell for the same bowler.
    #     Actual per-spell WHA would require more granular hazard modelling;
    #     instead we assign the career WHA to each spell at aggregation time.
    #     For now, mark as 0.0 (filled at career aggregation from wha_data).
    df["threat_wha"] = 0.0

    return df


# ---------------------------------------------------------------------------
# Step 4: Aggregate bowling careers
# ---------------------------------------------------------------------------


def apply_bowling_volume_scaling(bowl_careers: pd.DataFrame) -> pd.DataFrame:
    """
    Post-percentile volume scaling for bowlers: rewards players with more matches.

    A 15-match bowler cannot match a 50-match bowler all else being equal.
    The volume factor is::

        factor = BOWL_VOLUME_BASE + (1 - BOWL_VOLUME_BASE) * clip(matches / BOWL_VOLUME_REF, 0, 1) ** BOWL_VOLUME_CURVE

    Players who exceed BOWL_VOLUME_REF get a beyond-reference bonus that
    rewards sustained career volume::

        beyond_bonus = BOWL_VOLUME_BEYOND_MAX * clip((matches - ref) / ref, 0, 1)

    With defaults (base=0.70, ref=100, curve=0.5, beyond_max=0.06):
        10 matches → factor ~0.79   (21% penalty)
        19 matches → factor ~0.83   (17% penalty)
        30 matches → factor ~0.86   (14% penalty)
        50 matches → factor ~0.91   ( 9% penalty)
        75 matches → factor ~0.96   ( 4% penalty)
        100 matches → factor 1.00   (no penalty)
        120 matches → factor 1.01   ( 1% bonus)
        150 matches → factor 1.03   ( 3% bonus)
        200+ matches → factor 1.06  ( 6% bonus, max)

    Parameters
    ----------
    bowl_careers : pd.DataFrame
        Career profiles after rating system.

    Returns
    -------
    pd.DataFrame with scores scaled by volume factor.
    """
    df = bowl_careers.copy()

    matches = df["matches"].fillna(0).astype(float)
    ratio = (matches / BOWL_VOLUME_REF).clip(lower=0.0, upper=1.0)
    factor = BOWL_VOLUME_BASE + (1.0 - BOWL_VOLUME_BASE) * (ratio**BOWL_VOLUME_CURVE)

    # Beyond-reference bonus: players exceeding BOWL_VOLUME_REF get up to
    # BOWL_VOLUME_BEYOND_MAX additional scaling (e.g. 6% at 2× the reference).
    beyond_mask = matches > BOWL_VOLUME_REF
    if beyond_mask.any():
        extra_ratio = ((matches - BOWL_VOLUME_REF) / BOWL_VOLUME_REF).clip(
            lower=0.0, upper=1.0
        )
        factor = factor + BOWL_VOLUME_BEYOND_MAX * extra_ratio

    df["volume_factor"] = factor

    for col in ["score_accuracy", "score_control", "score_threat"]:
        if col in df.columns:
            df[col] = (df[col] * factor).round(1).clip(lower=0.0, upper=100.0)

    return df


def aggregate_bowling_careers(
    bowl_components: pd.DataFrame,
    df_deliveries: pd.DataFrame,
    min_overs: int = 30,
    wha_data: pd.DataFrame | None = None,
    bowling_rv_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Aggregate per-spell components into career-level raw composite scores.

    One row per bowler_id with:
    - Career stats (overs, wickets, economy, SR)
    - raw_accuracy, raw_control, raw_threat  (z-score composites)
    - bowled_lbw_pct  (share of wickets that are bowled or lbw)
    - phase_group  (primary bowling phase: pp_heavy / middle_heavy / death_heavy)
    - is_provisional_bowl flag
    - xR-derived metrics (bowling RV, WHA)

    The aggregation uses NaN-aware means so that missing phase stats
    (e.g. from spells too short to compute phase economy) simply don't
    contribute — they are NOT filled with 0 and penalised.

    After computing per-player means for each sub-component, the components
    are z-score normalised **within bowling phase groups** (if enabled) and
    then weight-averaged to form the final raw composite.  This ensures
    death bowlers are compared to other death bowlers, PP specialists to
    PP specialists, etc.

    NEW in algorithm rework:
    - Accuracy integrates run-yield variance (inverse).
    - Control integrates Adjusted Bowling Leveraged Run Value from xR.
    - Threat integrates Wicket Hazard Added (WHA) from the hazard model.

    Parameters
    ----------
    bowl_components : pd.DataFrame
        Output of compute_bowling_components().
    df_deliveries : pd.DataFrame
        Full delivery-level DataFrame (for wicket-type analysis).
    min_overs : int
        Fewer total overs than this → provisional rating.
    wha_data : pd.DataFrame, optional
        Output of expected_value.compute_wicket_hazard_added().
        If provided, WHA is merged as a Threat component.
    bowling_rv_data : pd.DataFrame, optional
        Output of expected_value.compute_bowling_run_value().
        If provided, bowling RV is merged as a Control component.
    """
    bc = bowl_components.copy()
    _decat(bc, ["bowler_id", "bowler", "bowling_team"])

    # Ensure spell_weight exists (backwards compat if missing)
    if "spell_weight" not in bc.columns:
        bc["spell_weight"] = 1.0

    grp = bc.groupby(["bowler_id", "bowler"])

    def _nanmean(s):
        vals = s.dropna()
        return vals.mean() if len(vals) > 0 else np.nan

    def _weighted_mean(values, weights):
        """Weighted mean ignoring NaN in values (weights kept where values valid)."""
        mask = values.notna()
        v = values[mask]
        w = weights[mask]
        if len(v) == 0 or w.sum() == 0:
            return np.nan
        return (v * w).sum() / w.sum()

    def _spell_weighted_mean(col_name):
        """Return an aggregation function that computes spell-weight-weighted mean."""

        def _agg(sub_df):
            return _weighted_mean(sub_df[col_name], sub_df["spell_weight"])

        return _agg

    def _threat_sr_mean(sub_df):
        """Weighted average only for spells where the bowler actually took wickets."""
        sr = sub_df["threat_sr"]
        w = sub_df["spell_weight"]
        non_nan = sr.dropna()
        non_zero = non_nan[non_nan != 0]
        if len(non_zero) == 0:
            return np.nan
        w_valid = w.loc[non_zero.index]
        return (non_zero * w_valid).sum() / w_valid.sum()

    # Basic stats use simple sums (factual totals, not weighted)
    has_opp_icc_rating = "opp_icc_rating" in bc.columns

    basic_stats = grp.agg(
        matches=("match_id", "nunique"),
        total_legal_balls=("legal_balls", "sum"),
        total_runs_conceded=("runs_conceded", "sum"),
        total_wickets=("wickets", "sum"),
        total_quality_wickets=("quality_wickets", "sum"),
        total_wides=("wides_count", "sum"),
        total_noballs=("noballs_count", "sum"),
        total_fours_conceded=("fours_conceded", "sum"),
        total_sixes_conceded=("sixes_conceded", "sum"),
        avg_wicket_quality_mean=("avg_wicket_quality", "mean"),
        avg_opp_icc_rating=(
            "opp_icc_rating" if has_opp_icc_rating else "wickets",
            "mean",
        ),
    ).reset_index()

    # Fix fallback column if opp_icc_rating wasn't available
    if not has_opp_icc_rating:
        from src.batting import ICC_RANKING_DEFAULT_RATING

        basic_stats["avg_opp_icc_rating"] = ICC_RANKING_DEFAULT_RATING

    # ── Primary country: team the bowler has played the most matches for ──
    country_df = (
        bc.groupby(["bowler_id", "bowler", "bowling_team"])["match_id"]
        .nunique()
        .reset_index(name="team_matches")
    )
    primary_country = (
        country_df.sort_values("team_matches", ascending=False)
        .drop_duplicates(subset=["bowler_id", "bowler"], keep="first")
        .rename(columns={"bowling_team": "country"})[["bowler_id", "bowler", "country"]]
    )
    basic_stats = basic_stats.merge(
        primary_country, on=["bowler_id", "bowler"], how="left"
    )

    # Component means use spell-weight-weighted averaging (incorporates recency)
    component_cols = {
        # Accuracy
        "acc_economy_vs_par": "acc_economy_vs_par_mean",
        "acc_dot_pct": "acc_dot_pct_mean",
        "acc_extras_penalty": "acc_extras_penalty_mean",
        "acc_boundary_penalty": "acc_boundary_penalty_mean",
        "acc_run_yield_variance": "acc_run_yield_variance_mean",
        # Control
        "ctrl_entropy": "ctrl_entropy_mean",
        "ctrl_extras": "ctrl_extras_mean",
        "ctrl_vs_others": "ctrl_vs_others_mean",
        "ctrl_extras_pct": "ctrl_extras_pct_mean",
        "ctrl_economy_vs_par": "ctrl_economy_vs_par_mean",
        "ctrl_bowling_rv": "ctrl_bowling_rv_mean",
        # Threat
        "threat_wickets": "threat_wickets_mean",
        "threat_quality_wickets": "threat_quality_wickets_mean",
        "threat_pressure": "threat_pressure_mean",
        "threat_dots": "threat_dots_mean",
    }

    weighted_aggs = grp.apply(
        lambda g: pd.Series(
            {
                out_name: _weighted_mean(g[src_col], g["spell_weight"])
                for src_col, out_name in component_cols.items()
            }
            | {
                "ctrl_phase_consistency_mean": _weighted_mean(
                    g["ctrl_phase_consistency"], g["spell_weight"]
                ),
                "threat_sr_mean": _threat_sr_mean(g),
            }
        ),
        include_groups=False,
    ).reset_index()

    career = basic_stats.merge(weighted_aggs, on=["bowler_id", "bowler"], how="left")

    # Career-level derived stats
    career["total_overs"] = career["total_legal_balls"] / 6.0
    career["career_economy"] = np.where(
        career["total_overs"] > 0,
        career["total_runs_conceded"] / career["total_overs"],
        0.0,
    )
    career["career_sr_bowl"] = np.where(
        career["total_wickets"] > 0,
        career["total_legal_balls"] / career["total_wickets"],
        999.0,
    )
    career["career_dot_pct"] = np.where(
        career["total_legal_balls"] > 0,
        career["acc_dot_pct_mean"],  # already aggregated
        0.0,
    )

    # ── Wicket type quality: bowled + lbw % (pure bowler skill) ──
    wkt_df = df_deliveries[df_deliveries["is_wicket"]].copy()
    _decat(wkt_df, ["bowler_id", "wicket_kind"])

    if len(wkt_df) > 0:
        bowler_wkt_quality = (
            wkt_df.groupby("bowler_id")
            .apply(
                lambda g: (
                    g["wicket_kind"].isin(["bowled", "lbw"]).mean()
                    if len(g) > 0
                    else 0.0
                ),
                include_groups=False,
            )
            .reset_index(name="bowled_lbw_pct")
        )
        career = career.merge(bowler_wkt_quality, on="bowler_id", how="left")
    else:
        career["bowled_lbw_pct"] = 0.0

    career["bowled_lbw_pct"] = career["bowled_lbw_pct"].fillna(0.0)

    # ──────────────────────────────────────────────────────────────────────
    # Determine each bowler's primary phase group based on career workload.
    # This drives within-group z-scoring: death bowlers compared to death
    # bowlers, PP specialists to PP specialists, etc.
    # ──────────────────────────────────────────────────────────────────────
    phase_balls = (
        bc.groupby(["bowler_id", "bowler"])
        .agg(
            career_pp_balls=("powerplay_legal_balls", lambda x: x.fillna(0).sum()),
            career_mid_balls=("middle_legal_balls", lambda x: x.fillna(0).sum()),
            career_death_balls=("death_legal_balls", lambda x: x.fillna(0).sum()),
        )
        .reset_index()
    )

    phase_balls["phase_group"] = phase_balls.apply(
        lambda r: classify_phase_group(
            r["career_pp_balls"], r["career_mid_balls"], r["career_death_balls"]
        ),
        axis=1,
    )

    career = career.merge(
        phase_balls[
            [
                "bowler_id",
                "bowler",
                "career_pp_balls",
                "career_mid_balls",
                "career_death_balls",
                "phase_group",
            ]
        ],
        on=["bowler_id", "bowler"],
        how="left",
    )
    career["phase_group"] = career["phase_group"].fillna("middle_heavy")

    # Merge small phase groups if needed
    if PHASE_GROUPS_ENABLED:
        group_counts = career["phase_group"].value_counts()
        for pg in ["pp_heavy", "death_heavy", "middle_heavy"]:
            if group_counts.get(pg, 0) < MIN_PHASE_GROUP_SIZE:
                # Merge into middle_heavy as the most generic fallback
                mask = career["phase_group"] == pg
                if mask.any() and pg != "middle_heavy":
                    career.loc[mask, "phase_group"] = "middle_heavy"
                    print(
                        f"  ℹ Bowling phase group '{pg}' "
                        f"({group_counts.get(pg, 0)} bowlers) "
                        f"merged into 'middle_heavy' for z-scoring"
                    )

    # ──────────────────────────────────────────────────────────────────────
    # Merge career-level xR-derived metrics
    # ──────────────────────────────────────────────────────────────────────

    # Wicket Hazard Added (WHA) for Threat dimension
    if wha_data is not None and not wha_data.empty:
        wha = wha_data.copy()
        if hasattr(wha.get("bowler_id", pd.Series()), "cat"):
            wha["bowler_id"] = wha["bowler_id"].astype(str)
        wha_merge_cols = ["bowler_id", "wha", "wicket_residual_total"]
        available_wha = [c for c in wha_merge_cols if c in wha.columns]
        career = career.merge(wha[available_wha], on="bowler_id", how="left")
        career["wha"] = career["wha"].fillna(0.0)
        career["wicket_residual_total"] = career.get(
            "wicket_residual_total", pd.Series(0.0, index=career.index)
        ).fillna(0.0)
    else:
        career["wha"] = 0.0
        career["wicket_residual_total"] = 0.0

    # Bowling Run Value for Control dimension (career-level)
    if bowling_rv_data is not None and not bowling_rv_data.empty:
        brv = bowling_rv_data.copy()
        if hasattr(brv.get("bowler_id", pd.Series()), "cat"):
            brv["bowler_id"] = brv["bowler_id"].astype(str)
        brv_merge_cols = ["bowler_id", "total_bowling_rv", "mean_bowling_rv_per_ball"]
        available_brv = [c for c in brv_merge_cols if c in brv.columns]
        career = career.merge(brv[available_brv], on="bowler_id", how="left")
        career["total_bowling_rv"] = career.get(
            "total_bowling_rv", pd.Series(0.0, index=career.index)
        ).fillna(0.0)
        career["mean_bowling_rv_per_ball"] = career.get(
            "mean_bowling_rv_per_ball", pd.Series(0.0, index=career.index)
        ).fillna(0.0)
    else:
        career["total_bowling_rv"] = 0.0
        career["mean_bowling_rv_per_ball"] = 0.0

    # ──────────────────────────────────────────────────────────────────────
    # Z-score normalise each sub-component, then weight-average to form
    # the composite.
    #
    # When phase groups are enabled, z-scores are computed WITHIN each
    # group so death bowlers compete with death bowlers, PP specialists
    # with PP specialists.  This prevents a death bowler with economy 9
    # (elite for death overs) from being penalised against PP bowlers who
    # naturally have lower economies.
    #
    # For components that may be NaN for some players (e.g. threat_sr_mean
    # for bowlers who never took wickets), we fill with 0 AFTER z-scoring.
    # A z-score of 0 means "population average" which is the correct neutral
    # value — the bowler is neither rewarded nor penalised for something
    # they didn't participate in.
    # ──────────────────────────────────────────────────────────────────────

    # Choose z-score function based on whether phase groups are enabled
    if PHASE_GROUPS_ENABLED:

        def _zs(col_name: str) -> pd.Series:
            return _grouped_zscore_bowl(
                career, col_name, "phase_group", MIN_PHASE_GROUP_SIZE
            )
    else:

        def _zs(col_name: str) -> pd.Series:
            return _zscore_series(career[col_name])

    # --- ACCURACY z-scores ---
    z_acc_econ = _zs("acc_economy_vs_par_mean")
    z_acc_dot = _zs("acc_dot_pct_mean")
    z_acc_extras = _zs("acc_extras_penalty_mean")
    z_acc_boundary = _zs("acc_boundary_penalty_mean")
    # Run-yield variance — primary Accuracy signal from algorithm_update.md
    z_acc_ryv = _zs("acc_run_yield_variance_mean").fillna(0)

    career["raw_accuracy"] = (
        ACC_WEIGHTS.get("economy_vs_par", 0.20) * z_acc_econ
        + ACC_WEIGHTS.get("dot_pct", 0.20) * z_acc_dot
        + ACC_WEIGHTS.get("extras_penalty", 0.15) * z_acc_extras
        + ACC_WEIGHTS.get("boundary_penalty", 0.15) * z_acc_boundary
        + ACC_WEIGHTS.get("run_yield_variance", 0.30) * z_acc_ryv
    )

    # --- CONTROL z-scores ---
    z_ctrl_entropy = _zs("ctrl_entropy_mean")
    z_ctrl_extras = _zs("ctrl_extras_mean")
    z_ctrl_others = _zs("ctrl_vs_others_mean")
    z_ctrl_epct = _zs("ctrl_extras_pct_mean")
    z_ctrl_phase = _zs("ctrl_phase_consistency_mean").fillna(0)
    z_ctrl_econ_par = _zs("ctrl_economy_vs_par_mean")
    # Bowling Run Value — xR-derived primary Control signal
    z_ctrl_brv = _zs("ctrl_bowling_rv_mean").fillna(0)

    career["raw_control"] = (
        CTRL_WEIGHTS.get("entropy", 0.10) * z_ctrl_entropy
        + CTRL_WEIGHTS.get("extras", 0.08) * z_ctrl_extras
        + CTRL_WEIGHTS.get("vs_others", 0.22) * z_ctrl_others
        + CTRL_WEIGHTS.get("extras_pct", 0.05) * z_ctrl_epct
        + CTRL_WEIGHTS.get("phase_consistency", 0.10) * z_ctrl_phase
        + CTRL_WEIGHTS.get("economy_vs_par", 0.15) * z_ctrl_econ_par
        + CTRL_WEIGHTS.get("bowling_rv", 0.30) * z_ctrl_brv
    )

    # --- THREAT z-scores ---
    z_thr_wickets = _zs("threat_wickets_mean")
    z_thr_quality_wkts = _zs("threat_quality_wickets_mean")
    z_thr_sr = _zs("threat_sr_mean").fillna(0)
    z_thr_blbw = _zscore_series(
        career["bowled_lbw_pct"]
    )  # career-level, not phase-dependent
    z_thr_pressure = _zs("threat_pressure_mean")
    z_thr_dots = _zs("threat_dots_mean")
    # Wicket Hazard Added — xR-derived primary Threat signal
    z_thr_wha = _zs("wha")

    career["raw_threat"] = (
        THREAT_WEIGHTS.get("wickets", 0.10) * z_thr_wickets
        + THREAT_WEIGHTS.get("quality_wickets", 0.10) * z_thr_quality_wkts
        + THREAT_WEIGHTS.get("sr", 0.10) * z_thr_sr
        + THREAT_WEIGHTS.get("bowled_lbw", 0.10) * z_thr_blbw
        + THREAT_WEIGHTS.get("pressure", 0.15) * z_thr_pressure
        + THREAT_WEIGHTS.get("dots", 0.15) * z_thr_dots
        + THREAT_WEIGHTS.get("wha", 0.30) * z_thr_wha
    )

    career["is_provisional_bowl"] = career["total_overs"] < min_overs

    return career


# ---------------------------------------------------------------------------
# Bowl First / Bowl Second Index (algorithm_update.md)
# ---------------------------------------------------------------------------

# Config for bowling innings splits
BOWL_SPLITS_ENABLED: bool = cfg("bowl_splits.enabled", default=True)
BOWL_SPLITS_MIN_SPELLS: int = cfg("bowl_splits.min_spells_per_type", default=5)


def compute_bowling_innings_splits(
    bowl_components: pd.DataFrame,
    min_spells_per_type: int | None = None,
) -> pd.DataFrame:
    """
    Compute bowling-first vs bowling-second career splits per bowler.

    Per algorithm_update.md:
    - **Bowl First Index** measures a bowler's ability to restrict an
      unknown total (innings 1).  Relies on Expected Runs suppression.
    - **Bowl Second Index** measures a bowler's ability to defend a set
      target (innings 2).  Operating under acute scoreboard pressure
      makes WPA the preferred evaluative metric, but we use economy-
      and wicket-based composites as proxies.

    Bowling first  = innings_num 1 (restricting the opposition's score)
    Bowling second = innings_num 2 (defending a target)

    Parameters
    ----------
    bowl_components : pd.DataFrame
        Output of ``compute_bowling_components()``.  Must contain
        ``innings_num``, ``bowler_id``, ``bowler``, and the component
        columns used for aggregation.
    min_spells_per_type : int, optional
        Minimum number of spells in *each* innings type for the split
        indices to be computed.  Defaults to config value or 5.

    Returns
    -------
    pd.DataFrame
        One row per (bowler_id, bowler) with:
        - ``bowl_first_spells`` / ``bowl_second_spells``: spell counts
        - ``bowl_first_econ_vs_par`` / ``bowl_second_econ_vs_par``: avg
          economy vs par in each innings type
        - ``bowl_first_dot_pct`` / ``bowl_second_dot_pct``: avg dot %
        - ``bowl_first_wickets_per_spell`` / ``bowl_second_wickets_per_spell``
        - ``bowl_first_index``: positive = better when restricting (inn 1)
        - ``bowl_second_index``: positive = better when defending (inn 2)
    """
    if not BOWL_SPLITS_ENABLED:
        return pd.DataFrame()

    min_sp = (
        min_spells_per_type
        if min_spells_per_type is not None
        else BOWL_SPLITS_MIN_SPELLS
    )

    bc = bowl_components.copy()

    for c in ["bowler_id", "bowler"]:
        if c in bc.columns and hasattr(bc[c], "cat"):
            bc[c] = bc[c].astype(str)

    # Ensure innings_num is available
    if "innings_num" not in bc.columns:
        return pd.DataFrame()

    bowling_first = bc[bc["innings_num"] == 1]
    bowling_second = bc[bc["innings_num"] == 2]

    def _agg_spells(sub_df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        """Aggregate key bowling metrics for a first/second innings subset."""
        if sub_df.empty:
            return pd.DataFrame(columns=["bowler_id", "bowler"])

        grp = (
            sub_df.groupby(["bowler_id", "bowler"])
            .agg(
                spells=("match_id", "nunique"),
                avg_econ_vs_par=("acc_economy_vs_par", "mean"),
                avg_dot_pct=("acc_dot_pct", "mean"),
                total_wickets=("wickets", "sum"),
                total_spells_count=("match_id", "size"),
                avg_ctrl_vs_others=("ctrl_vs_others", "mean"),
                avg_bowling_rv=("ctrl_bowling_rv", "mean"),
            )
            .reset_index()
        )

        # Wickets per spell
        grp["wickets_per_spell"] = np.where(
            grp["total_spells_count"] > 0,
            grp["total_wickets"] / grp["total_spells_count"],
            0.0,
        )

        # Composite performance score for this innings type:
        #   Economy vs par (higher = better, already oriented correctly)
        #   + dot ball % (higher = better)
        #   + wickets per spell (higher = better, scaled to similar magnitude)
        #   + bowling RV (higher = better, xR-derived)
        grp["composite"] = (
            grp["avg_econ_vs_par"].fillna(0) * 0.35
            + grp["avg_dot_pct"].fillna(0) * 0.20
            + grp["wickets_per_spell"].fillna(0) * 0.15
            + grp["avg_bowling_rv"].fillna(0) * 0.15
            + grp["avg_ctrl_vs_others"].fillna(0) * 0.15
        )

        grp = grp.rename(
            columns={
                c: f"{prefix}_{c}"
                for c in [
                    "spells",
                    "avg_econ_vs_par",
                    "avg_dot_pct",
                    "wickets_per_spell",
                    "composite",
                    "avg_bowling_rv",
                ]
            }
        )

        # Drop intermediate columns
        grp = grp.drop(
            columns=["total_wickets", "total_spells_count", "avg_ctrl_vs_others"],
            errors="ignore",
        )

        return grp

    first_agg = _agg_spells(bowling_first, "bowl_first")
    second_agg = _agg_spells(bowling_second, "bowl_second")

    splits = first_agg.merge(second_agg, on=["bowler_id", "bowler"], how="outer")

    # Apply minimum spells filter
    _first_ok = (
        splits.get("bowl_first_spells", pd.Series(0, index=splits.index)).fillna(0)
        >= min_sp
    )
    _second_ok = (
        splits.get("bowl_second_spells", pd.Series(0, index=splits.index)).fillna(0)
        >= min_sp
    )
    _both_ok = _first_ok & _second_ok

    # Bowl First Index = bowl_first composite - bowl_second composite
    # Positive = bowler is better when restricting (bowling first).
    splits["bowl_first_index"] = np.where(
        _both_ok,
        splits.get("bowl_first_composite", pd.Series(0.0, index=splits.index)).fillna(0)
        - splits.get(
            "bowl_second_composite", pd.Series(0.0, index=splits.index)
        ).fillna(0),
        np.nan,
    )

    # Bowl Second Index = bowl_second composite - bowl_first composite
    # Positive = bowler is better when defending a target.
    splits["bowl_second_index"] = np.where(
        _both_ok,
        splits.get("bowl_second_composite", pd.Series(0.0, index=splits.index)).fillna(
            0
        )
        - splits.get("bowl_first_composite", pd.Series(0.0, index=splits.index)).fillna(
            0
        ),
        np.nan,
    )

    # Round for readability
    for c in splits.columns:
        if splits[c].dtype in ("float64", "float32"):
            splits[c] = splits[c].round(4)

    return splits
