"""
Cricket Metrics — Main Pipeline

Orchestrates the full player-profiling pipeline:

    Parse  →  Dedup  →  Context  →  Team Quality  →  Batting / Bowling  →  Rating  →  Output

Usage
-----
    python src/main.py                       # default: ../t20s_male_json
    python src/main.py /path/to/json/dir     # custom data directory
    python src/main.py /path/to/json/dir --config path/to/config.yaml

Output
------
    output/batting_profiles.csv          – One row per batter, 0-100 scores
    output/bowling_profiles.csv          – One row per bowler, 0-100 scores
    output/batting_careers_full.parquet  – Full career detail (for website)
    output/bowling_careers_full.parquet  – Full career detail (for website)
    output/batting_innings_detail.parquet – Per-innings component breakdown
    output/bowling_spells_detail.parquet  – Per-spell component breakdown
    output/potential_duplicates.csv      – Suspected player-ID duplicates (if any)
"""

import os
import sys
import time

import pandas as pd

# ---------------------------------------------------------------------------
# Ensure the project root (parent of src/) is on sys.path so that
# `from src.X import Y` works regardless of working directory.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.batting import (
    aggregate_batting_careers,
    apply_avg_quality_gate,
    apply_bowling_competition_quality_gate,
    apply_competition_quality_gate,
    apply_volume_scaling,
    compute_batting_components,
    compute_bowler_strength_index,
    compute_chase_splits,
    compute_franchise_season_quality,
    compute_franchise_team_quality,
    compute_team_quality,
    compute_wicket_quality,
    detect_potential_duplicates,
    extract_batting_innings,
    merge_player_identities,
)
from src.bowling import (
    _compute_phase_par_rr,
    aggregate_bowling_careers,
    apply_bowling_volume_scaling,
    compute_bowling_components,
    compute_bowling_innings_splits,
    compute_run_distribution_entropy,
    extract_bowling_spells,
)
from src.clutch import (
    compute_all_clutch_metrics,
)
from src.condition import (
    compute_all_condition_metrics,
)
from src.config import get_config, reload_config
from src.context import build_full_context
from src.era import (
    apply_era_adjustment_to_bowling,
    apply_era_adjustment_to_innings,
    compute_era_baselines,
    compute_era_summary,
)
from src.expected_value import (
    aggregate_batter_rva,
    aggregate_bowler_rva,
    build_expected_value_models,
    compute_bowling_run_value,
    compute_context_adjusted_boundary_index,
    compute_expected_survival_rates,
    compute_wicket_hazard_added,
    score_all_deliveries,
)
from src.form_tracker import (
    compute_batting_form_series,
    compute_bowling_form_series,
)
from src.matchups import (
    apply_bayesian_matchup_shrinkage,
    compute_all_matchup_metrics,
)
from src.parser import parse_all_matches
from src.peak_ratings import (
    compute_peak_ratings,
    compute_peak_ratings_bowl,
    compute_sliding_peak,
    compute_sliding_peak_bowl,
)
from src.presentation import (
    add_batting_grades,
    add_bowling_grades,
    assign_batting_archetypes,
    assign_bowling_archetypes,
)
from src.rating import apply_rating_system, lookup_player
from src.similarity import (
    compute_batting_similarity,
    compute_bowling_similarity,
    pivot_similarity_wide,
)
from src.venue import (
    compute_all_venue_metrics,
)
from src.war import (
    compute_allrounder_war,
    compute_batting_war,
    compute_batting_war_rate,
    compute_bowling_war,
    compute_bowling_war_rate,
    compute_runs_per_win,
)
from src.wpa import (
    compute_all_wpa_metrics,
)

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    data_dir: str,
    output_dir: str = "output",
    config_path: str | None = None,
    min_bat_innings: int | None = None,
    min_bowl_overs: int | None = None,
    shrinkage_k_bat: float | None = None,
    shrinkage_k_bowl: float | None = None,
    confidence_alpha: float | None = None,
    data_format: str = "t20i",
) -> dict:
    """
    Run the full cricket-metrics pipeline end-to-end.

    Parameters
    ----------
    data_dir : str
        Path to the directory containing Cricsheet JSON match files.
    output_dir : str
        Where to write CSV / Parquet outputs.
    config_path : str, optional
        Path to a YAML config file.  If None, uses ``config.yaml`` in
        the project root (or built-in defaults if that file is absent).
    min_bat_innings : int, optional
        Batting innings threshold for provisional flag.
        Overrides config if provided.
    min_bowl_overs : int, optional
        Bowling overs threshold for provisional flag.
        Overrides config if provided.
    shrinkage_k_bat : float, optional
        Bayesian shrinkage strength for batting ratings.
        Overrides config if provided.
    shrinkage_k_bowl : float, optional
        Bayesian shrinkage strength for bowling ratings.
        Overrides config if provided.
    confidence_alpha : float, optional
        Maximum confidence bonus for match volume.
        Overrides config if provided.
    data_format : str, optional
        Data format: ``"t20i"`` for international T20 data (uses ICC
        rankings for team quality), or ``"ipl"`` for franchise league
        data (uses per-season win-rate-based team quality instead of
        ICC rankings and skips the competition quality gate).
        Default ``"t20i"``.

    Returns
    -------
    dict with keys:
        deliveries, batting_careers, bowling_careers,
        batting_innings, bowling_spells, match_context, innings_context
    """
    # ── Load configuration ──
    if config_path is not None:
        config = reload_config(config_path)
    else:
        config = get_config()

    # Resolve parameters: explicit arg > config > built-in default
    min_bat_innings = (
        min_bat_innings
        if min_bat_innings is not None
        else config.get("pipeline.min_bat_innings", default=10)
    )
    min_bowl_overs = (
        min_bowl_overs
        if min_bowl_overs is not None
        else config.get("pipeline.min_bowl_overs", default=30)
    )
    shrinkage_k_bat = (
        shrinkage_k_bat
        if shrinkage_k_bat is not None
        else config.get("rating.shrinkage_k_bat", default=12.0)
    )
    shrinkage_k_bowl = (
        shrinkage_k_bowl
        if shrinkage_k_bowl is not None
        else config.get("rating.shrinkage_k_bowl", default=10.0)
    )
    confidence_alpha = (
        confidence_alpha
        if confidence_alpha is not None
        else config.get("rating.confidence_alpha", default=0.03)
    )

    os.makedirs(output_dir, exist_ok=True)
    t0 = time.time()

    def _elapsed() -> str:
        return f"{time.time() - t0:.1f}s"

    # ── Print active config summary ──
    recency_enabled = config.get("recency.enabled", default=True)
    recency_half_life = config.get("recency.half_life_days", default=730)
    icc_ranking_enabled = config.get("icc_ranking.enabled", default=True)
    icc_floor = config.get("icc_ranking.floor", default=0.50)
    icc_ceiling = config.get("icc_ranking.ceiling", default=1.35)
    icc_curve = config.get("icc_ranking.curve", default=1.8)
    match_quality_enabled = config.get("match_quality.enabled", default=True)
    mq_floor = config.get("match_quality.floor", default=0.75)
    mq_ceiling = config.get("match_quality.ceiling", default=1.20)
    print("=" * 65)
    print("CONFIG SUMMARY")
    print("=" * 65)
    print(f"  Config source    : {config_path or 'config.yaml (default)'}")
    print(f"  Min bat innings  : {min_bat_innings}")
    print(f"  Min bowl overs   : {min_bowl_overs}")
    print(f"  Shrinkage (bat)  : {shrinkage_k_bat}")
    print(f"  Shrinkage (bowl) : {shrinkage_k_bowl}")
    print(f"  Confidence alpha : {confidence_alpha}")
    print(
        f"  Recency decay    : {'ON' if recency_enabled else 'OFF'}"
        + (f"  (half-life {recency_half_life} days)" if recency_enabled else "")
    )
    print(
        f"  ICC ranking wt   : {'ON' if icc_ranking_enabled else 'OFF'}"
        + (
            f"  (floor {icc_floor}, ceil {icc_ceiling}, curve {icc_curve})"
            if icc_ranking_enabled
            else ""
        )
    )
    print(
        f"  Match quality wt : {'ON' if match_quality_enabled else 'OFF'}"
        + (f"  (floor {mq_floor}, ceil {mq_ceiling})" if match_quality_enabled else "")
    )
    print()

    # ── Step 1: Parse all match files ────────────────────────────────────
    print("=" * 65)
    print("STEP 1 / 9 — Parsing match files")
    print("=" * 65)
    df, match_infos = parse_all_matches(data_dir)
    print(f"  Deliveries : {len(df):>10,}")
    print(f"  Matches    : {len(match_infos):>10,}")
    print(f"  Date range : {df['date'].min().date()} → {df['date'].max().date()}")
    unique_players = df["batter_id"].nunique() + df["bowler_id"].nunique()
    print(f"  Unique IDs : ~{unique_players:,} (batter + bowler, overlapping)")
    print(f"  [{_elapsed()}]\n")

    # ── Step 1a: Remove excluded teams (Afghanistan) ─────────────────────
    # Filter out all matches involving Afghanistan — both matches where they
    # bat and where they bowl.  This removes all Afghanistan players from
    # the dataset entirely (they only appear in Afghanistan matches).
    excluded_teams = {"Afghanistan"}
    batting_teams = df["batting_team"]
    bowling_teams = df["bowling_team"]
    if hasattr(batting_teams, "cat"):
        batting_teams = batting_teams.astype(str)
    if hasattr(bowling_teams, "cat"):
        bowling_teams = bowling_teams.astype(str)
    excl_mask = batting_teams.isin(excluded_teams) | bowling_teams.isin(excluded_teams)
    n_before = len(df)
    matches_before = df["match_id"].nunique()
    df = df[~excl_mask].reset_index(drop=True)
    match_infos = [
        mi
        for mi in match_infos
        if not any(t in excluded_teams for t in mi.get("teams", []))
    ]
    n_removed = n_before - len(df)
    matches_removed = matches_before - df["match_id"].nunique()
    if n_removed > 0:
        print(f"  ✂ Excluded {', '.join(sorted(excluded_teams))} matches:")
        print(f"    Matches removed   : {matches_removed:,}")
        print(f"    Deliveries removed: {n_removed:,}")
        print(
            f"    Remaining         : {len(df):,} deliveries, {df['match_id'].nunique():,} matches"
        )
    # Re-apply categorical dtypes after filtering (categories may be stale)
    for c in ["batting_team", "bowling_team"]:
        if c in df.columns and hasattr(df[c], "cat"):
            df[c] = df[c].cat.remove_unused_categories()
    print(f"  [{_elapsed()}]\n")

    # ── Step 1b: Build Expected Value (xR) models ────────────────────────
    print("  Building Expected Value (xR + WP) models...")
    ev_models = build_expected_value_models(df)
    print(f"  [{_elapsed()}]\n")

    # ── Step 1c: Score all deliveries with xR and RVA ────────────────────
    print("  Scoring all deliveries with Expected Runs (xR) model...")
    scored_df = score_all_deliveries(df, ev_models, full_wp=False)
    # Copy xR columns back onto the main deliveries DataFrame
    for col in ["xr_per_ball", "run_value_added"]:
        if col in scored_df.columns:
            df[col] = scored_df[col].values
    print(f"  ✓ xR scoring complete: {len(df):,} deliveries scored")
    print(f"  [{_elapsed()}]\n")

    # ── Step 1d: Compute xR-derived career metrics ───────────────────────
    print("  Computing xR-derived career metrics (CABI, Survival, WHA, BowlRV)...")
    survival_rates = compute_expected_survival_rates(df)
    n_surv = (survival_rates["survival_ratio"] != 1.0).sum()
    print(f"  ✓ Expected Survival Rates: {n_surv:,} batters with sufficient data")

    cabi_data = compute_context_adjusted_boundary_index(df)
    n_cabi = (cabi_data["cabi"] != 0.0).sum()
    print(f"  ✓ Context-Adjusted Boundary Index (CABI): {n_cabi:,} batters")

    wha_data = compute_wicket_hazard_added(df)
    n_wha = (wha_data["wha"] != 0.0).sum()
    print(f"  ✓ Wicket Hazard Added (WHA): {n_wha:,} bowlers")

    bowling_rv_data = compute_bowling_run_value(df, ev_models["xr_model"])
    n_brv = (bowling_rv_data["total_bowling_rv"] != 0.0).sum()
    print(f"  ✓ Adjusted Bowling Run Value: {n_brv:,} bowlers")
    print(f"  [{_elapsed()}]\n")

    # ── Step 1e: Player identity deduplication ───────────────────────────
    print("  Deduplicating player identities...")
    df = merge_player_identities(df)
    dedup_min_innings = config.get("duplicate_detection.min_innings", default=5)
    suspects = detect_potential_duplicates(df, min_innings=dedup_min_innings)
    if len(suspects) > 0:
        print(f"  ⚠ {len(suspects)} potential duplicate pairs detected:")
        for _, s in suspects.head(10).iterrows():
            print(
                f"    {s['name_a']} ({s['innings_a']} inn) ↔ "
                f"    {s['name_b']} ({s['innings_b']} inn) [{s['team']}]"
            )
        if len(suspects) > 10:
            print(f"    ... and {len(suspects) - 10} more")
        print("    (Add confirmed duplicates to player_aliases in config.yaml)")

        # Export duplicates CSV for manual review if configured
        if config.get("duplicate_detection.export_csv", default=True):
            dup_csv_path = os.path.join(output_dir, "potential_duplicates.csv")
            suspects.to_csv(dup_csv_path, index=False)
            print(f"    → Exported to {dup_csv_path}")
    else:
        print("  No suspected duplicates found.")
    print(f"  [{_elapsed()}]\n")

    # ── Step 2: Compute match & team context ─────────────────────────────
    print("=" * 65)
    print("STEP 2 / 9 — Computing match & innings context")
    print("=" * 65)
    innings_ctx, match_ctx = build_full_context(df)
    print(f"  Innings records : {len(innings_ctx):,}")
    print(f"  Match records   : {len(match_ctx):,}")
    avg_par_sr = match_ctx["match_par_sr"].mean()
    avg_par_rr = match_ctx["match_par_rr"].mean()
    print(f"  Avg match par SR: {avg_par_sr:.1f}   (run rate {avg_par_rr:.2f})")
    print(f"  [{_elapsed()}]\n")

    # ── Step 2b: Compute bowler strength index (for opposition quality) ──
    print("  Computing bowler strength index for opposition quality...")
    bowler_strength = compute_bowler_strength_index(df)
    qualified_bowlers = (bowler_strength["bowler_strength"] != 0.0).sum()
    print(f"  Qualified bowlers: {qualified_bowlers:,}  (others default to average)")
    print(
        f"  Strength range: [{bowler_strength['bowler_strength'].min():.2f}, "
        f"{bowler_strength['bowler_strength'].max():.2f}]"
    )
    print(f"  [{_elapsed()}]\n")

    # ── Step 2c: Compute team quality ──
    is_franchise = data_format.lower() in ("ipl",)
    franchise_season_ratings = None

    if is_franchise:
        print("  Computing franchise season quality (win-rate based)...")
        franchise_season_ratings = compute_franchise_season_quality(df)
        team_quality = compute_franchise_team_quality(df)
        n_seasons = franchise_season_ratings["season"].nunique()
        top_teams = team_quality.nlargest(5, "team_quality")
        print(f"  Teams indexed: {len(team_quality):,}  ({n_seasons} seasons)")
        print(
            f"  Top 5 teams (franchise win-rate): "
            f"{', '.join(top_teams['team'].tolist())}"
        )
        print(
            f"  Quality range: [{team_quality['team_quality'].min():.2f}, "
            f"{team_quality['team_quality'].max():.2f}]"
        )
        # Print a few sample season ratings
        for _, row in franchise_season_ratings.nlargest(
            3, "franchise_rating"
        ).iterrows():
            print(
                f"    {row['team']} {int(row['season'])}: "
                f"{row['wins']}/{row['matches']} wins "
                f"({row['win_rate']:.0%}) -> rating {row['franchise_rating']:.0f}"
            )
    else:
        print("  Computing team quality index (ICC rankings)...")
        team_quality = compute_team_quality(df)
        top_teams = team_quality.nlargest(5, "team_quality")
        print(f"  Teams indexed: {len(team_quality):,}")
        print(f"  Top 5 teams (ICC): {', '.join(top_teams['team'].tolist())}")
        print(
            f"  Quality range: [{team_quality['team_quality'].min():.2f}, "
            f"{team_quality['team_quality'].max():.2f}]"
        )
    print(f"  [{_elapsed()}]\n")

    # ── Step 3: Extract batting innings ──────────────────────────────────
    print("=" * 65)
    print("STEP 3 / 9 — Extracting batting innings")
    print("=" * 65)
    bat_innings = extract_batting_innings(
        df,
        innings_ctx,
        bowler_strength=bowler_strength,
        team_quality=team_quality,
        franchise_season_ratings=franchise_season_ratings,
    )
    print(f"  Batting innings extracted: {len(bat_innings):,}")
    bat_components = compute_batting_components(
        bat_innings,
        ev_models=ev_models,
        scored_deliveries=scored_df,
        survival_rates=survival_rates,
        cabi_data=cabi_data,
    )
    print(
        f"  Component columns added : {[c for c in bat_components.columns if c.startswith(('acc_', 'pow_', 'ctrl_'))]}"
    )
    print(f"  [{_elapsed()}]\n")

    # ── Step 4: Extract bowling spells ───────────────────────────────────
    print("=" * 65)
    print("STEP 4 / 9 — Extracting bowling spells")
    print("=" * 65)
    print("  Computing phase-specific par run rates (PP / middle / death)...")
    phase_par_rr = _compute_phase_par_rr(df)
    bowl_spells = extract_bowling_spells(
        df,
        innings_ctx,
        phase_par_rr=phase_par_rr,
        team_quality=team_quality,
        franchise_season_ratings=franchise_season_ratings,
    )
    print(f"  Bowling spells extracted: {len(bowl_spells):,}")

    print("  Computing run-distribution entropy...")
    entropy_df = compute_run_distribution_entropy(df)

    print("  Computing wicket quality (position-weighted)...")
    wicket_quality = compute_wicket_quality(df)
    if len(wicket_quality) > 0:
        avg_wq = wicket_quality["avg_wicket_quality"].mean()
        print(f"  Avg wicket quality: {avg_wq:.2f}  (1.0 = neutral)")
    else:
        print("  No wickets found.")

    bowl_components = compute_bowling_components(
        bowl_spells,
        entropy_df,
        wicket_quality=wicket_quality,
        scored_deliveries=scored_df,
        wha_data=wha_data,
        bowling_rv_data=bowling_rv_data,
    )
    print(
        f"  Component columns added : {[c for c in bowl_components.columns if c.startswith(('acc_', 'ctrl_', 'threat_'))]}"
    )
    print(f"  [{_elapsed()}]\n")

    # ── Step 5: Aggregate career profiles ────────────────────────────────
    print("=" * 65)
    print("STEP 5 / 9 — Aggregating career profiles")
    print("=" * 65)
    bat_careers = aggregate_batting_careers(
        bat_components,
        min_innings=min_bat_innings,
        survival_rates=survival_rates,
        cabi_data=cabi_data,
    )
    bowl_careers = aggregate_bowling_careers(
        bowl_components,
        df,
        min_overs=min_bowl_overs,
        wha_data=wha_data,
        bowling_rv_data=bowling_rv_data,
    )

    bat_prov = bat_careers["is_provisional_bat"].sum()
    bowl_prov = bowl_careers["is_provisional_bowl"].sum()
    print(f"  Batters profiled : {len(bat_careers):,}  ({bat_prov:,} provisional)")
    print(f"  Bowlers profiled : {len(bowl_careers):,}  ({bowl_prov:,} provisional)")

    # Print position / phase group summaries
    if "position_group" in bat_careers.columns:
        pg_counts = bat_careers["position_group"].value_counts()
        print(f"  Batting position groups: {dict(pg_counts)}")
    if "phase_group" in bowl_careers.columns:
        phg_counts = bowl_careers["phase_group"].value_counts()
        print(f"  Bowling phase groups   : {dict(phg_counts)}")
    print(f"  [{_elapsed()}]\n")

    # ── Step 6: Apply Bayesian rating system ─────────────────────────────
    print("=" * 65)
    print("STEP 6 / 9 — Applying Bayesian rating system → 0-100 scores")
    print("=" * 65)

    bat_careers = apply_rating_system(
        bat_careers,
        raw_cols=["raw_acceleration", "raw_power", "raw_control"],
        sample_col="innings_count",
        provisional_col="is_provisional_bat",
        shrinkage_k=shrinkage_k_bat,
        confidence_alpha=confidence_alpha,
    )

    bowl_careers = apply_rating_system(
        bowl_careers,
        raw_cols=["raw_accuracy", "raw_control", "raw_threat"],
        sample_col="matches",
        provisional_col="is_provisional_bowl",
        shrinkage_k=shrinkage_k_bowl,
        confidence_alpha=confidence_alpha,
    )

    print("  Rating system applied.")
    print(f"  [{_elapsed()}]\n")

    # ── Step 7: Apply post-percentile gates and volume scaling ───────────
    print("=" * 65)
    print("STEP 7 / 9 — Applying average gates & volume scaling")
    print("=" * 65)

    # Post-percentile average quality gate: scales all three batting scores
    # by career average (steeper for ACC/POW, milder for Control).
    bat_careers = apply_avg_quality_gate(bat_careers)
    print("  ✓ Batting avg quality gate applied (ACC/POW + Control)")

    # Volume scaling: rewards players with more innings/matches.
    bat_careers = apply_volume_scaling(bat_careers)
    print("  ✓ Batting volume scaling applied")

    bowl_careers = apply_bowling_volume_scaling(bowl_careers)
    print("  ✓ Bowling volume scaling applied")

    # Competition quality gate: scales down scores for players who primarily
    # face weak opposition (based on average opponent ICC rating).
    competition_gate_enabled = config.get(
        "competition_quality_gate.enabled", default=True
    )
    if is_franchise:
        # For franchise leagues, the competition quality gate is replaced by
        # per-season franchise ratings applied at the per-innings weighting
        # level.  The post-percentile gate (which uses avg_opp_icc_rating)
        # is skipped because franchise ratings already provide meaningful
        # differentiation during career aggregation.
        print(
            "  ℹ Competition quality gate skipped (franchise mode — "
            "per-season team quality applied at innings level)"
        )
    elif competition_gate_enabled:
        bat_careers = apply_competition_quality_gate(bat_careers)
        print("  ✓ Batting competition quality gate applied")
        bowl_careers = apply_bowling_competition_quality_gate(bowl_careers)
        print("  ✓ Bowling competition quality gate applied")
    else:
        print("  ℹ Competition quality gate disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7b: Presentation layer (grades + archetypes) ────────────────
    print("  Applying presentation layer (grades + archetypes)...")
    bat_careers = add_batting_grades(bat_careers)
    bat_careers = assign_batting_archetypes(bat_careers)
    print("  ✓ Batting grades & archetypes assigned")

    bowl_careers = add_bowling_grades(bowl_careers)
    bowl_careers = assign_bowling_archetypes(bowl_careers)
    print("  ✓ Bowling grades & archetypes assigned")
    print(f"  [{_elapsed()}]\n")

    # ── Step 7c: Chase Master Index (Feature 6) ──────────────────────────
    chase_master_enabled = config.get("chase_master.enabled", default=True)
    if chase_master_enabled:
        print("  Computing Chase Master Index (innings 1 vs 2 splits)...")
        chase_splits = compute_chase_splits(bat_components)
        if not chase_splits.empty:
            chase_cols_to_merge = [
                "batter_id",
                "batter",
                "setting_inn",
                "chasing_inn",
                "setting_sr",
                "setting_avg",
                "chasing_sr",
                "chasing_avg",
                "chase_master_index",
                "bat_first_index",
                "chase_master_full",
            ]
            available_chase_cols = [
                c for c in chase_cols_to_merge if c in chase_splits.columns
            ]
            bat_careers = bat_careers.merge(
                chase_splits[available_chase_cols],
                on=["batter_id", "batter"],
                how="left",
            )
            n_chase = chase_splits["chase_master_index"].notna().sum()
            print(f"  ✓ Chase Master Index computed for {n_chase:,} batters")
        else:
            print("  ℹ Chase Master Index disabled or no data")
    else:
        print("  ℹ Chase Master Index disabled")

    # ── Step 7d: Anchor Cost & Selfless Index (Features 11 & 8) ──────────
    # These are computed inside extract_batting_innings and aggregated in
    # aggregate_batting_careers, so they're already on bat_careers.
    anchor_cost_enabled = config.get("anchor_cost.enabled", default=True)
    if anchor_cost_enabled and "avg_balls_to_par" in bat_careers.columns:
        n_anchor = bat_careers["avg_balls_to_par"].notna().sum()
        print(f"  ✓ Anchor Cost (balls-to-par) available for {n_anchor:,} batters")

    selfless_enabled = config.get("selfless.enabled", default=True)
    if selfless_enabled and "selfless_index" in bat_careers.columns:
        n_selfless = bat_careers["selfless_index"].notna().sum()
        print(f"  ✓ Selfless Index available for {n_selfless:,} batters")

    # ── Step 7e: Peak vs Current Ratings (Feature 5) ─────────────────────
    print("\n  Computing Peak Ratings (recency-free career aggregates)...")
    peak_bat = compute_peak_ratings(bat_components)
    if not peak_bat.empty:
        bat_careers = bat_careers.merge(
            peak_bat,
            on=["batter_id", "batter"],
            how="left",
        )
        n_peak_bat = peak_bat["peak_composite_batting"].notna().sum()
        print(f"  ✓ Peak batting ratings computed for {n_peak_bat:,} batters")
    else:
        print("  ℹ No peak batting ratings (insufficient data)")

    peak_bowl = compute_peak_ratings_bowl(bowl_components)
    if not peak_bowl.empty:
        bowl_careers = bowl_careers.merge(
            peak_bowl,
            on=["bowler_id", "bowler"],
            how="left",
        )
        n_peak_bowl = peak_bowl["peak_composite_bowling"].notna().sum()
        print(f"  ✓ Peak bowling ratings computed for {n_peak_bowl:,} bowlers")
    else:
        print("  ℹ No peak bowling ratings (insufficient data)")

    # Sliding-window peak (true 2-year best)
    print("  Computing sliding-window peak (best 2-year window)...")
    sliding_peak_bat = compute_sliding_peak(bat_components)
    if not sliding_peak_bat.empty:
        bat_careers = bat_careers.merge(
            sliding_peak_bat[
                [
                    "batter_id",
                    "batter",
                    "peak_window_start",
                    "peak_window_end",
                    "peak_window_innings",
                    "peak_window_composite",
                ]
            ],
            on=["batter_id", "batter"],
            how="left",
        )
        n_sp = sliding_peak_bat["peak_window_composite"].notna().sum()
        print(f"  ✓ Sliding-window peak computed for {n_sp:,} batters")

    sliding_peak_bowl = compute_sliding_peak_bowl(bowl_components)
    if not sliding_peak_bowl.empty:
        bowl_careers = bowl_careers.merge(
            sliding_peak_bowl[
                [
                    "bowler_id",
                    "bowler",
                    "peak_window_start",
                    "peak_window_end",
                    "peak_window_spells",
                    "peak_window_composite",
                ]
            ],
            on=["bowler_id", "bowler"],
            how="left",
        )
        n_sp_bowl = sliding_peak_bowl["peak_window_composite"].notna().sum()
        print(f"  ✓ Sliding-window peak computed for {n_sp_bowl:,} bowlers")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7f: Player Similarity Engine (Feature 7) ────────────────────
    similarity_enabled = config.get("similarity.enabled", default=True)
    sim_top_k = config.get("similarity.top_k", default=3)
    sim_min_innings = config.get("similarity.min_innings", default=15)

    bat_similarities = pd.DataFrame()
    bowl_similarities = pd.DataFrame()
    if similarity_enabled:
        print("  Computing Player Similarity Engine (cosine similarity on profiles)...")
        bat_similarities = compute_batting_similarity(
            bat_careers,
            top_k=sim_top_k,
            min_innings=sim_min_innings,
        )
        if not bat_similarities.empty:
            n_bat_sim = bat_similarities["batter_id"].nunique()
            print(
                f"  ✓ Batting similarities computed for {n_bat_sim:,} batters (top-{sim_top_k})"
            )
        else:
            print("  ℹ No batting similarities (insufficient data)")

        bowl_similarities = compute_bowling_similarity(
            bowl_careers,
            top_k=sim_top_k,
            min_matches=sim_min_innings,
        )
        if not bowl_similarities.empty:
            n_bowl_sim = bowl_similarities["bowler_id"].nunique()
            print(
                f"  ✓ Bowling similarities computed for {n_bowl_sim:,} bowlers (top-{sim_top_k})"
            )
        else:
            print("  ℹ No bowling similarities (insufficient data)")
    else:
        print("  ℹ Player Similarity Engine disabled")

    # ── Step 7g: Form Tracker / Time-Series (Feature 13) ─────────────────
    form_tracker_enabled = config.get("form_tracker.enabled", default=True)
    bat_form_series = pd.DataFrame()
    bowl_form_series = pd.DataFrame()
    if form_tracker_enabled:
        ft_window_bat = config.get("form_tracker.window_matches_bat", default=10)
        ft_window_bowl = config.get("form_tracker.window_matches_bowl", default=10)
        ft_min_window = config.get("form_tracker.min_window", default=5)

        print("  Computing Form Tracker (rolling-window time-series)...")
        bat_form_series = compute_batting_form_series(
            bat_components,
            window_matches=ft_window_bat,
            min_window=ft_min_window,
        )
        if not bat_form_series.empty:
            n_bat_form = bat_form_series["batter_id"].nunique()
            print(
                f"  ✓ Batting form series: {len(bat_form_series):,} rows ({n_bat_form:,} batters)"
            )
        else:
            print("  ℹ No batting form series (insufficient data)")

        bowl_form_series = compute_bowling_form_series(
            bowl_components,
            window_matches=ft_window_bowl,
            min_window=ft_min_window,
        )
        if not bowl_form_series.empty:
            n_bowl_form = bowl_form_series["bowler_id"].nunique()
            print(
                f"  ✓ Bowling form series: {len(bowl_form_series):,} rows ({n_bowl_form:,} bowlers)"
            )
        else:
            print("  ℹ No bowling form series (insufficient data)")
    else:
        print("  ℹ Form Tracker disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7h: Venue & Pitch Difficulty (Feature 9) ────────────────────
    venue_enabled = config.get("venue.enabled", default=True)
    venue_baselines = pd.DataFrame()
    if venue_enabled:
        venue_min_matches = config.get("venue.min_matches", default=5)
        print("  Computing Venue & Pitch Difficulty (flat track bully index)...")
        venue_results = compute_all_venue_metrics(
            match_ctx=match_ctx,
            deliveries=df,
            bat_innings=bat_components,
            bowl_spells=bowl_components,
            min_matches=venue_min_matches,
        )
        venue_baselines = venue_results["venue_baselines"]
        if not venue_baselines.empty:
            n_venues = len(venue_baselines)
            print(f"  ✓ Venue baselines computed for {n_venues:,} venues")

        ft_batting = venue_results["flat_track_batting"]
        if not ft_batting.empty:
            bat_careers = bat_careers.merge(
                ft_batting,
                on=["batter_id", "batter"],
                how="left",
            )
            n_ft = ft_batting["flat_track_index"].notna().sum()
            print(f"  ✓ Flat Track Bully Index (batting) for {n_ft:,} batters")

        ft_bowling = venue_results["flat_track_bowling"]
        if not ft_bowling.empty:
            bowl_careers = bowl_careers.merge(
                ft_bowling,
                on=["bowler_id", "bowler"],
                how="left",
            )
            n_ft_bowl = ft_bowling["flat_track_index_bowl"].notna().sum()
            print(f"  ✓ Flat Track Bully Index (bowling) for {n_ft_bowl:,} bowlers")

        va_batting = venue_results["venue_adjusted_batting"]
        if not va_batting.empty:
            bat_careers = bat_careers.merge(
                va_batting,
                on=["batter_id", "batter"],
                how="left",
            )
            n_va = va_batting["venue_adjusted_composite"].notna().sum()
            print(f"  ✓ Venue-adjusted batting composite for {n_va:,} batters")
    else:
        print("  ℹ Venue & Pitch Difficulty disabled")

    # ── Step 7i: Positional WAR (Feature 14) ─────────────────────────────
    war_enabled = config.get("war.enabled", default=True)
    if war_enabled:
        war_replacement = config.get("war.replacement_percentile", default=0.25)
        print("  Computing cricWAR (xR-based Wins Above Replacement)...")

        # Compute dynamic Runs Per Win converter from match data
        rpw = compute_runs_per_win(match_ctx)
        print(f"  Runs Per Win converter: {rpw:.1f}")

        bat_careers = compute_batting_war(
            bat_careers,
            replacement_percentile=war_replacement,
            runs_per_win=rpw,
            match_context=match_ctx,
        )
        bat_careers = compute_batting_war_rate(bat_careers)
        n_war_bat = bat_careers["war_batting"].notna().sum()
        print(f"  ✓ Batting WAR computed for {n_war_bat:,} batters")

        bowl_careers = compute_bowling_war(
            bowl_careers,
            replacement_percentile=war_replacement,
            runs_per_win=rpw,
            match_context=match_ctx,
        )
        bowl_careers = compute_bowling_war_rate(bowl_careers)
        n_war_bowl = bowl_careers["war_bowling"].notna().sum()
        print(f"  ✓ Bowling WAR computed for {n_war_bowl:,} bowlers")

        # All-Rounder WAR (vector magnitude in 2D skill space)
        allrounder_war = compute_allrounder_war(bat_careers, bowl_careers)
        if not allrounder_war.empty:
            n_ar = len(allrounder_war)
            print(f"  ✓ All-Rounder WAR computed for {n_ar:,} dual-threat players")
            # Log top all-rounders
            top_ar = allrounder_war.nlargest(3, "war_allrounder")
            for _, ar_row in top_ar.iterrows():
                print(
                    f"    {ar_row['player_id']}: "
                    f"WAR={ar_row['war_allrounder']:.2f} "
                    f"({ar_row['allrounder_archetype']})"
                )
        else:
            print("  ℹ No qualified all-rounders found")
    else:
        allrounder_war = pd.DataFrame()
        print("  ℹ Positional WAR disabled")

    # ── Step 7j: Era-Adjusted Ratings (Feature 15) ───────────────────────
    era_enabled = config.get("era_adjustment.enabled", default=False)
    era_baselines = pd.DataFrame()
    era_summary = pd.DataFrame()
    if era_enabled:
        era_rolling = config.get("era_adjustment.rolling_years", default=3)
        print("  Computing Era-Adjusted Ratings (cross-generational harmonization)...")
        era_baselines = compute_era_baselines(match_ctx, rolling_years=era_rolling)
        if not era_baselines.empty:
            era_summary = compute_era_summary(era_baselines)
            n_years = len(era_baselines)
            print(f"  ✓ Era baselines computed for {n_years} years")
            # Print a few sample multipliers
            for _, row in era_summary.head(3).iterrows():
                print(
                    f"    {int(row['year'])}: par SR {row['era_par_sr']:.1f}, "
                    f"multiplier {row['era_sr_multiplier']:.3f} "
                    f"({row['effect_pct']:+.1f}%)"
                )
            if len(era_summary) > 3:
                last = era_summary.iloc[-1]
                print(
                    f"    {int(last['year'])}: par SR {last['era_par_sr']:.1f}, "
                    f"multiplier {last['era_sr_multiplier']:.3f} "
                    f"({last['effect_pct']:+.1f}%) [reference]"
                )
        else:
            print("  ℹ No era baselines (insufficient match data)")
    else:
        print("  ℹ Era-Adjusted Ratings disabled (experimental)")

    # ── Step 7k: Clutch / Pressure Index (Feature 3) ─────────────────────
    clutch_enabled = config.get("clutch.enabled", default=True)
    batting_clutch = pd.DataFrame()
    bowling_clutch = pd.DataFrame()
    if clutch_enabled:
        clutch_min_inn = config.get("clutch.min_pressure_innings", default=5)
        clutch_rrr = config.get("clutch.high_rrr_threshold", default=9.0)
        clutch_collapse = config.get("clutch.collapse_wickets", default=3)
        print("  Computing Clutch / Pressure Index (batting + bowling)...")
        clutch_results = compute_all_clutch_metrics(
            deliveries=df,
            bat_components=bat_components,
            bowl_components=bowl_components,
            min_pressure_innings=clutch_min_inn,
            min_pressure_spells=clutch_min_inn,
            high_rrr_threshold=clutch_rrr,
            collapse_wickets=clutch_collapse,
        )
        batting_clutch = clutch_results["batting_clutch"]
        bowling_clutch = clutch_results["bowling_clutch"]

        if not batting_clutch.empty:
            clutch_bat_cols = [
                "batter_id",
                "batter",
                "clutch_index",
                "pressure_innings",
                "normal_innings",
                "clutch_sr_delta",
            ]
            available_clutch_bat = [
                c for c in clutch_bat_cols if c in batting_clutch.columns
            ]
            bat_careers = bat_careers.merge(
                batting_clutch[available_clutch_bat],
                on=["batter_id", "batter"],
                how="left",
            )
            n_clutch_bat = batting_clutch["clutch_index"].notna().sum()
            print(f"  ✓ Batting Clutch Index computed for {n_clutch_bat:,} batters")
        else:
            print("  ℹ No batting clutch data (insufficient pressure innings)")

        if not bowling_clutch.empty:
            clutch_bowl_cols = [
                "bowler_id",
                "bowler",
                "clutch_index_bowl",
                "pressure_spells",
                "normal_spells",
            ]
            available_clutch_bowl = [
                c for c in clutch_bowl_cols if c in bowling_clutch.columns
            ]
            bowl_careers = bowl_careers.merge(
                bowling_clutch[available_clutch_bowl],
                on=["bowler_id", "bowler"],
                how="left",
            )
            n_clutch_bowl = bowling_clutch["clutch_index_bowl"].notna().sum()
            print(f"  ✓ Bowling Clutch Index computed for {n_clutch_bowl:,} bowlers")
        else:
            print("  ℹ No bowling clutch data (insufficient pressure spells)")
    else:
        print("  ℹ Clutch / Pressure Index disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7k2: Bowl First / Bowl Second Index (Feature 16) ────────────
    bowl_splits_enabled = config.get("bowl_splits.enabled", default=True)
    if bowl_splits_enabled:
        bowl_splits_min = config.get("bowl_splits.min_spells_per_type", default=5)
        print("  Computing Bowl First / Bowl Second Index (bowling innings splits)...")
        bowl_splits = compute_bowling_innings_splits(
            bowl_components,
            min_spells_per_type=bowl_splits_min,
        )
        if not bowl_splits.empty:
            bowl_splits_merge_cols = [
                "bowler_id",
                "bowler",
                "bowl_first_spells",
                "bowl_second_spells",
                "bowl_first_avg_econ_vs_par",
                "bowl_second_avg_econ_vs_par",
                "bowl_first_avg_dot_pct",
                "bowl_second_avg_dot_pct",
                "bowl_first_wickets_per_spell",
                "bowl_second_wickets_per_spell",
                "bowl_first_index",
                "bowl_second_index",
            ]
            available_bs_cols = [
                c for c in bowl_splits_merge_cols if c in bowl_splits.columns
            ]
            bowl_careers = bowl_careers.merge(
                bowl_splits[available_bs_cols],
                on=["bowler_id", "bowler"],
                how="left",
            )
            n_bs = bowl_splits["bowl_first_index"].notna().sum()
            print(f"  ✓ Bowl First/Second Index computed for {n_bs:,} bowlers")
        else:
            print("  ℹ No bowl splits data (insufficient spells)")
    else:
        print("  ℹ Bowl First / Bowl Second Index disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7l: Head-to-Head Matchups (Feature 4) ───────────────────────
    matchup_results: dict = {}
    matchup_min_balls = config.get("matchups.min_balls", default=6)
    matchup_top_k_bunnies = config.get("matchups.top_k_bunnies", default=5)
    matchup_top_k_dominant = config.get("matchups.top_k_dominant", default=5)
    print("  Computing Head-to-Head Matchups (batter × bowler)...")
    matchup_results = compute_all_matchup_metrics(
        deliveries=df,
        min_balls=matchup_min_balls,
        include_phase=True,
        top_k_bunnies=matchup_top_k_bunnies,
        top_k_dominant=matchup_top_k_dominant,
    )
    matchups_df = matchup_results.get("matchups", pd.DataFrame())
    matchups_phase_df = matchup_results.get("matchups_by_phase", pd.DataFrame())
    batter_diversity = matchup_results.get("batter_diversity", pd.DataFrame())
    bowler_matchup_summary = matchup_results.get("bowler_summary", pd.DataFrame())

    if not matchups_df.empty:
        n_matchups = len(matchups_df)
        n_batter_ids = matchups_df["batter_id"].nunique()
        n_bowler_ids = matchups_df["bowler_id"].nunique()
        print(
            f"  ✓ Matchups computed: {n_matchups:,} pairs "
            f"({n_batter_ids:,} batters × {n_bowler_ids:,} bowlers)"
        )
    else:
        print("  ℹ No qualified matchups found")

    if not matchups_phase_df.empty:
        print(f"  ✓ Phase-level matchups: {len(matchups_phase_df):,} rows")

    # Merge matchup diversity stats onto bat_careers
    if not batter_diversity.empty:
        diversity_merge_cols = [
            "batter_id",
            "avg_dominance",
            "pct_dominant",
            "matchup_consistency",
            "unique_bowlers",
        ]
        available_div = [
            c for c in diversity_merge_cols if c in batter_diversity.columns
        ]
        bat_careers = bat_careers.merge(
            batter_diversity[available_div],
            on="batter_id",
            how="left",
        )
        n_div = batter_diversity["avg_dominance"].notna().sum()
        print(f"  ✓ Matchup diversity stats merged for {n_div:,} batters")

    # Merge bowler matchup summary onto bowl_careers
    if not bowler_matchup_summary.empty:
        bowl_summary_merge_cols = [
            "bowler_id",
            "avg_dominance",
            "pct_dominant_bowl",
        ]
        available_bowl_sum = [
            c for c in bowl_summary_merge_cols if c in bowler_matchup_summary.columns
        ]
        # Rename to avoid collision with batting avg_dominance
        bowl_sum_rename = bowler_matchup_summary[available_bowl_sum].rename(
            columns={"avg_dominance": "avg_dominance_bowl"}
        )
        bowl_careers = bowl_careers.merge(
            bowl_sum_rename,
            on="bowler_id",
            how="left",
        )
        n_bowl_sum = bowler_matchup_summary["avg_dominance"].notna().sum()
        print(f"  ✓ Bowler matchup summary merged for {n_bowl_sum:,} bowlers")

    # ── Step 7l2: Bayesian Matchup Shrinkage (Feature 18) ────────────────
    matchup_shrinkage_enabled = config.get("matchup_shrinkage.enabled", default=True)
    if matchup_shrinkage_enabled and not matchups_df.empty:
        shrinkage_balls = config.get("matchup_shrinkage.shrinkage_balls", default=30)
        print("  Applying Bayesian matchup shrinkage (archetype-based priors)...")
        matchups_df = apply_bayesian_matchup_shrinkage(
            matchups_df,
            bowler_archetypes=bowl_careers[
                ["bowler_id", "archetype", "phase_group"]
            ].copy()
            if "archetype" in bowl_careers.columns
            else None,
            batter_archetypes=bat_careers[
                ["batter_id", "archetype", "position_group"]
            ].copy()
            if "archetype" in bat_careers.columns
            else None,
            shrinkage_balls=shrinkage_balls,
        )
        n_shrunk = (matchups_df["bayesian_dominance"].notna()).sum()
        print(
            f"  ✓ Bayesian shrinkage applied to {n_shrunk:,} matchups "
            f"(k={shrinkage_balls})"
        )
    else:
        if not matchup_shrinkage_enabled:
            print("  ℹ Bayesian matchup shrinkage disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7m: Win Probability Added / WPA (Feature 10) ────────────────
    wpa_enabled = config.get("wpa.enabled", default=False)
    wpa_batting = pd.DataFrame()
    wpa_bowling = pd.DataFrame()
    wpa_deliveries = pd.DataFrame()
    if wpa_enabled:
        wpa_buckets = config.get("wpa.score_ratio_buckets", default=10)
        wpa_rr_buckets = config.get("wpa.rr_ratio_buckets", default=8)
        print("  Computing Win Probability Added (WPA)...")
        print("    Building win-probability models from historical data...")
        wpa_results = compute_all_wpa_metrics(
            deliveries=df,
            score_ratio_buckets=wpa_buckets,
            rr_ratio_buckets=wpa_rr_buckets,
            use_vectorised=True,
        )
        wpa_deliveries = wpa_results.get("wpa_deliveries", pd.DataFrame())
        wpa_batting = wpa_results.get("batting_wpa", pd.DataFrame())
        wpa_bowling = wpa_results.get("bowling_wpa", pd.DataFrame())

        if not wpa_batting.empty:
            wpa_bat_merge_cols = [
                "batter_id",
                "batter",
                "career_wpa_bat",
                "wpa_per_match_bat",
                "clutch_wpa_pct_bat",
            ]
            available_wpa_bat = [
                c for c in wpa_bat_merge_cols if c in wpa_batting.columns
            ]
            bat_careers = bat_careers.merge(
                wpa_batting[available_wpa_bat],
                on=["batter_id", "batter"],
                how="left",
            )
            n_wpa_bat = wpa_batting["career_wpa_bat"].notna().sum()
            print(f"  ✓ Batting WPA computed for {n_wpa_bat:,} batters")
        else:
            print("  ℹ No batting WPA data")

        if not wpa_bowling.empty:
            wpa_bowl_merge_cols = [
                "bowler_id",
                "bowler",
                "career_wpa_bowl",
                "wpa_per_match_bowl",
            ]
            available_wpa_bowl = [
                c for c in wpa_bowl_merge_cols if c in wpa_bowling.columns
            ]
            bowl_careers = bowl_careers.merge(
                wpa_bowling[available_wpa_bowl],
                on=["bowler_id", "bowler"],
                how="left",
            )
            n_wpa_bowl = wpa_bowling["career_wpa_bowl"].notna().sum()
            print(f"  ✓ Bowling WPA computed for {n_wpa_bowl:,} bowlers")
        else:
            print("  ℹ No bowling WPA data")
    else:
        print("  ℹ Win Probability Added (WPA) disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 7n: Condition-Dependence Metrics (Feature 17) ───────────────
    condition_enabled = config.get("condition_dependence.enabled", default=True)
    batting_condition = pd.DataFrame()
    bowling_condition = pd.DataFrame()
    batting_terciles = pd.DataFrame()
    if condition_enabled:
        cd_min_bat = config.get("condition_dependence.min_bat_innings", default=10)
        cd_min_bowl = config.get("condition_dependence.min_bowl_spells", default=10)
        cd_par_col = config.get(
            "condition_dependence.par_sr_col", default="match_par_sr"
        )
        cd_bat_perf = config.get(
            "condition_dependence.bat_performance_col", default="acc_overall_sr"
        )
        cd_bowl_perf = config.get(
            "condition_dependence.bowl_performance_col", default="acc_economy_vs_par"
        )
        print(
            "  Computing Condition-Dependence Metrics (flat-track bully detection)..."
        )
        condition_results = compute_all_condition_metrics(
            bat_innings=bat_components,
            bowl_spells=bowl_components,
            match_ctx=match_ctx,
            min_bat_innings=cd_min_bat,
            min_bowl_spells=cd_min_bowl,
            par_sr_col=cd_par_col,
            bat_performance_col=cd_bat_perf,
            bowl_performance_col=cd_bowl_perf,
        )
        batting_condition = condition_results["batting_condition"]
        bowling_condition = condition_results["bowling_condition"]
        batting_terciles = condition_results["batting_terciles"]

        if not batting_condition.empty:
            cdi_bat_cols = [
                "batter_id",
                "batter",
                "condition_dependence_index",
                "condition_dependence_tag",
                "condition_innings",
                "easy_sr_vs_par",
                "hard_sr_vs_par",
                "condition_spread",
            ]
            available_cdi_bat = [
                c for c in cdi_bat_cols if c in batting_condition.columns
            ]
            bat_careers = bat_careers.merge(
                batting_condition[available_cdi_bat],
                on=["batter_id", "batter"],
                how="left",
            )
            n_cdi_bat = batting_condition["condition_dependence_index"].notna().sum()
            print(f"  ✓ Batting CDI computed for {n_cdi_bat:,} batters")
            # Log tag distribution
            if "condition_dependence_tag" in batting_condition.columns:
                tag_counts = batting_condition[
                    "condition_dependence_tag"
                ].value_counts()
                for tag, cnt in tag_counts.items():
                    if pd.notna(tag):
                        print(f"    {tag}: {cnt:,}")
        else:
            print("  ℹ No batting condition-dependence data")

        if not bowling_condition.empty:
            cdi_bowl_cols = [
                "bowler_id",
                "bowler",
                "condition_dependence_index_bowl",
                "condition_dependence_tag_bowl",
                "condition_spells",
                "easy_econ_vs_par",
                "hard_econ_vs_par",
                "condition_spread_bowl",
            ]
            available_cdi_bowl = [
                c for c in cdi_bowl_cols if c in bowling_condition.columns
            ]
            bowl_careers = bowl_careers.merge(
                bowling_condition[available_cdi_bowl],
                on=["bowler_id", "bowler"],
                how="left",
            )
            n_cdi_bowl = (
                bowling_condition["condition_dependence_index_bowl"].notna().sum()
            )
            print(f"  ✓ Bowling CDI computed for {n_cdi_bowl:,} bowlers")
        else:
            print("  ℹ No bowling condition-dependence data")
    else:
        print("  ℹ Condition-Dependence Metrics disabled")

    print(f"  [{_elapsed()}]\n")

    # ── Step 8: Save outputs ─────────────────────────────────────────────
    print("=" * 65)
    print("STEP 8 / 9 — Saving results")
    print("=" * 65)

    # Batting CSV — clean, human-readable summary
    bat_csv_cols = [
        "batter_id",
        "batter",
        "country",
        "innings_count",
        "total_runs",
        "total_balls",
        "career_sr",
        "career_avg",
        "total_fours",
        "total_sixes",
        "modal_position",
        "position_group",
        "score_acceleration",
        "score_power",
        "score_control",
        "overall_score",
        "overall_grade",
        "grade_acceleration",
        "grade_power",
        "grade_control",
        "archetype",
        "avg_balls_to_par",
        "anchor_cost_ratio",
        "selfless_fifty",
        "selfless_century",
        "selfless_index",
        "chase_master_index",
        "bat_first_index",
        "peak_composite_batting",
        "peak_window_composite",
        "flat_track_index",
        "venue_adjusted_composite",
        "war_batting",
        "war_batting_rate",
        "clutch_index",
        "pressure_innings",
        "clutch_sr_delta",
        "avg_dominance",
        "pct_dominant",
        "matchup_consistency",
        "career_wpa_bat",
        "wpa_per_match_bat",
        "condition_dependence_index",
        "condition_dependence_tag",
        "condition_spread",
        "is_provisional_bat",
    ]
    bat_out = bat_careers[
        [c for c in bat_csv_cols if c in bat_careers.columns]
    ].sort_values("score_acceleration", ascending=False)

    # Bowling CSV — clean, human-readable summary
    bowl_csv_cols = [
        "bowler_id",
        "bowler",
        "country",
        "matches",
        "total_overs",
        "total_wickets",
        "career_economy",
        "career_sr_bowl",
        "phase_group",
        "score_accuracy",
        "score_control",
        "score_threat",
        "overall_score",
        "overall_grade",
        "grade_accuracy",
        "grade_control",
        "grade_threat",
        "archetype",
        "avg_wicket_quality_mean",
        "bowled_lbw_pct",
        "peak_composite_bowling",
        "peak_window_composite",
        "flat_track_index_bowl",
        "war_bowling",
        "war_bowling_rate",
        "clutch_index_bowl",
        "pressure_spells",
        "avg_dominance_bowl",
        "pct_dominant_bowl",
        "career_wpa_bowl",
        "wpa_per_match_bowl",
        "bowl_first_index",
        "bowl_second_index",
        "condition_dependence_index_bowl",
        "condition_dependence_tag_bowl",
        "condition_spread_bowl",
        "is_provisional_bowl",
    ]
    bowl_out = bowl_careers[
        [c for c in bowl_csv_cols if c in bowl_careers.columns]
    ].sort_values("score_accuracy", ascending=False)

    # Round numeric columns for readability
    for c in [
        "career_sr",
        "career_avg",
        "overall_score",
        "avg_balls_to_par",
        "anchor_cost_ratio",
        "selfless_fifty",
        "selfless_century",
        "selfless_index",
        "chase_master_index",
        "bat_first_index",
        "peak_composite_batting",
        "peak_window_composite",
        "flat_track_index",
        "venue_adjusted_composite",
        "war_batting",
        "war_batting_rate",
        "clutch_index",
        "clutch_sr_delta",
        "avg_dominance",
        "pct_dominant",
        "matchup_consistency",
        "career_wpa_bat",
        "wpa_per_match_bat",
        "condition_dependence_index",
        "condition_spread",
    ]:
        if c in bat_out.columns:
            bat_out[c] = bat_out[c].round(2)
    for c in [
        "career_economy",
        "career_sr_bowl",
        "total_overs",
        "avg_wicket_quality_mean",
        "bowled_lbw_pct",
        "overall_score",
        "peak_composite_bowling",
        "peak_window_composite",
        "flat_track_index_bowl",
        "war_bowling",
        "war_bowling_rate",
        "clutch_index_bowl",
        "avg_dominance_bowl",
        "pct_dominant_bowl",
        "career_wpa_bowl",
        "wpa_per_match_bowl",
        "bowl_first_index",
        "bowl_second_index",
        "condition_dependence_index_bowl",
        "condition_spread_bowl",
    ]:
        if c in bowl_out.columns:
            bowl_out[c] = bowl_out[c].round(2)

    # Write CSVs
    bat_csv_path = os.path.join(output_dir, "batting_profiles.csv")
    bowl_csv_path = os.path.join(output_dir, "bowling_profiles.csv")
    bat_out.to_csv(bat_csv_path, index=False)
    bowl_out.to_csv(bowl_csv_path, index=False)
    print(f"  ✓ {bat_csv_path}  ({len(bat_out):,} batters)")
    print(f"  ✓ {bowl_csv_path}  ({len(bowl_out):,} bowlers)")

    # Write full Parquet files for the website / detailed analysis
    parquet_files = {
        "batting_careers_full.parquet": bat_careers,
        "bowling_careers_full.parquet": bowl_careers,
        "batting_innings_detail.parquet": bat_components,
        "bowling_spells_detail.parquet": bowl_components,
    }

    # All-Rounder WAR (Feature: All-Rounder Value Framework)
    if war_enabled and not allrounder_war.empty:
        parquet_files["allrounder_war.parquet"] = allrounder_war

    # Form tracker time-series (Feature 13)
    if form_tracker_enabled and not bat_form_series.empty:
        parquet_files["batting_form_series.parquet"] = bat_form_series
    if form_tracker_enabled and not bowl_form_series.empty:
        parquet_files["bowling_form_series.parquet"] = bowl_form_series

    # Head-to-Head Matchups (Feature 4)
    if not matchups_df.empty:
        parquet_files["matchups.parquet"] = matchups_df
    if not matchups_phase_df.empty:
        parquet_files["matchups_by_phase.parquet"] = matchups_phase_df

    # WPA detail (Feature 10)
    if wpa_enabled and not wpa_batting.empty:
        parquet_files["wpa_batting.parquet"] = wpa_batting
    if wpa_enabled and not wpa_bowling.empty:
        parquet_files["wpa_bowling.parquet"] = wpa_bowling

    # Condition-Dependence tercile splits (Feature 17)
    if condition_enabled and not batting_terciles.empty:
        parquet_files["batting_condition_terciles.parquet"] = batting_terciles

    # Player similarity engine (Feature 7)
    # Venue baselines (Feature 9)
    if venue_enabled and not venue_baselines.empty:
        parquet_files["venue_baselines.parquet"] = venue_baselines

    # Era baselines and summary (Feature 15)
    if era_enabled and not era_baselines.empty:
        parquet_files["era_baselines.parquet"] = era_baselines
        if not era_summary.empty:
            era_csv_path = os.path.join(output_dir, "era_summary.csv")
            era_summary.to_csv(era_csv_path, index=False)
            print(f"  ✓ {era_csv_path}  ({len(era_summary):,} years)")

    if similarity_enabled and not bat_similarities.empty:
        parquet_files["batting_similarities.parquet"] = bat_similarities
        # Also write wide-form CSV for easy consumption
        bat_sim_wide = pivot_similarity_wide(
            bat_similarities,
            id_col="batter_id",
            name_col="batter",
            top_k=sim_top_k,
        )
        if not bat_sim_wide.empty:
            bat_sim_csv_path = os.path.join(output_dir, "batting_similarities.csv")
            bat_sim_wide.to_csv(bat_sim_csv_path, index=False)
            print(f"  ✓ {bat_sim_csv_path}  ({len(bat_sim_wide):,} batters)")
    if similarity_enabled and not bowl_similarities.empty:
        parquet_files["bowling_similarities.parquet"] = bowl_similarities
        bowl_sim_wide = pivot_similarity_wide(
            bowl_similarities,
            id_col="bowler_id",
            name_col="bowler",
            top_k=sim_top_k,
        )
        if not bowl_sim_wide.empty:
            bowl_sim_csv_path = os.path.join(output_dir, "bowling_similarities.csv")
            bowl_sim_wide.to_csv(bowl_sim_csv_path, index=False)
            print(f"  ✓ {bowl_sim_csv_path}  ({len(bowl_sim_wide):,} bowlers)")
    for fname, frame in parquet_files.items():
        fpath = os.path.join(output_dir, fname)
        # Convert category columns to string before writing parquet
        for c in frame.columns:
            if hasattr(frame[c], "cat"):
                frame[c] = frame[c].astype(str)
        frame.to_parquet(fpath, index=False)
        print(f"  ✓ {fpath}  ({len(frame):,} rows)")

    # ── Step 9: Summary spot-checks ──────────────────────────────────────
    print("=" * 65)
    print("STEP 9 / 9 — Spot-check summaries")
    print("=" * 65)

    # Quick sanity checks on key players — diverse positions & roles
    # Includes openers (Kohli, Allen, Head), middle (SA Yadav, Buttler),
    # finishers (Dhoni, David), and bowlers across phases (Bumrah, Rashid).
    spot_check_batters = [
        "Kohli",
        "SA Yadav",
        "Buttler",
        "Allen",
        "Head",
        "Dhoni",
        "David",
        "Riazat Ali Shah",
        "Babar",
    ]
    spot_check_bowlers = ["Bumrah", "Arshdeep", "Shaheen"]

    print("\n  ── Batting spot-checks ──")
    print(
        f"  {'Name':22s} {'Pos':>4s} {'Group':>13s}  "
        f"{'ACC':>5s}  {'POW':>5s}  {'CTRL':>5s}  "
        f"{'OVR':>5s} {'Grd':>3s}  "
        f"{'Inn':>4s}  {'Avg':>5s}  {'SR':>6s}  "
        f"{'BtP':>4s} {'Slf':>4s} {'Chs':>5s} {'WAR':>5s} {'Clu':>5s} {'Dom':>5s} {'WPA':>6s}  {'Archetype':<20s}"
    )
    print("  " + "─" * 168)
    for name in spot_check_batters:
        bat_match = bat_careers[
            bat_careers["batter"].str.contains(name, case=False, na=False)
        ]
        if not bat_match.empty:
            row = bat_match.iloc[0]
            pos = int(row.get("modal_position", 0))
            pg = row.get("position_group", "?")
            ovr = row.get("overall_score", 0)
            grd = row.get("overall_grade", "?")
            arch = row.get("archetype", "")
            btp = row.get("avg_balls_to_par", float("nan"))
            slf = row.get("selfless_index", float("nan"))
            chs = row.get("chase_master_index", float("nan"))
            btp_s = f"{btp:4.1f}" if pd.notna(btp) else "   —"
            slf_s = f"{slf:4.2f}" if pd.notna(slf) else "   —"
            chs_s = f"{chs:+5.2f}" if pd.notna(chs) else "    —"
            war = row.get("war_batting", float("nan"))
            war_s = f"{war:5.2f}" if pd.notna(war) else "    —"
            clu = row.get("clutch_index", float("nan"))
            clu_s = f"{clu:+5.2f}" if pd.notna(clu) else "    —"
            dom = row.get("avg_dominance", float("nan"))
            dom_s = f"{dom:+5.2f}" if pd.notna(dom) else "    —"
            wpa_val = row.get("career_wpa_bat", float("nan"))
            wpa_s = f"{wpa_val:+6.3f}" if pd.notna(wpa_val) else "     —"
            print(
                f"  {row['batter']:22s} #{pos:<3d} {pg:>13s}  "
                f"{row.get('score_acceleration', 0):5.1f}  "
                f"{row.get('score_power', 0):5.1f}  "
                f"{row.get('score_control', 0):5.1f}  "
                f"{ovr:5.1f} {grd:>3s}  "
                f"{int(row['innings_count']):4d}  "
                f"{row['career_avg']:5.1f}  "
                f"{row['career_sr']:6.1f}  "
                f"{btp_s} {slf_s} {chs_s} {war_s} {clu_s} {dom_s} {wpa_s}  {arch:<20s}"
            )

    print("\n  ── Bowling spot-checks ──")
    print(
        f"  {'Name':22s} {'Phase':>13s}  "
        f"{'ACC':>5s}  {'CTRL':>5s}  {'THR':>5s}  "
        f"{'OVR':>5s} {'Grd':>3s}  "
        f"{'Mat':>4s}  {'Econ':>5s}  {'Archetype':<20s}"
    )
    print("  " + "─" * 105)
    for name in spot_check_bowlers:
        bowl_match = bowl_careers[
            bowl_careers["bowler"].str.contains(name, case=False, na=False)
        ]
        if not bowl_match.empty:
            row = bowl_match.iloc[0]
            phg = row.get("phase_group", "?")
            ovr = row.get("overall_score", 0)
            grd = row.get("overall_grade", "?")
            arch = row.get("archetype", "")
            print(
                f"  {row['bowler']:22s} {phg:>13s}  "
                f"{row.get('score_accuracy', 0):5.1f}  "
                f"{row.get('score_control', 0):5.1f}  "
                f"{row.get('score_threat', 0):5.1f}  "
                f"{ovr:5.1f} {grd:>3s}  "
                f"{int(row['matches']):4d}  "
                f"{row['career_economy']:5.2f}  {arch:<20s}"
            )

    total_time = time.time() - t0
    print(f"\n{'=' * 65}")
    print(f"  PIPELINE COMPLETE — {total_time:.1f}s total")
    print(f"{'=' * 65}")

    return {
        "deliveries": df,
        "scored_deliveries": scored_df,
        "batting_careers": bat_careers,
        "bowling_careers": bowl_careers,
        "batting_innings": bat_components,
        "bowling_spells": bowl_components,
        "match_context": match_ctx,
        "innings_context": innings_ctx,
        "team_quality": team_quality,
        "franchise_season_ratings": franchise_season_ratings,
        "ev_models": ev_models,
        "survival_rates": survival_rates,
        "cabi_data": cabi_data,
        "wha_data": wha_data,
        "bowling_rv_data": bowling_rv_data,
        "allrounder_war": allrounder_war if war_enabled else pd.DataFrame(),
        "config": config,
        "potential_duplicates": suspects,
        "batting_form_series": bat_form_series,
        "bowling_form_series": bowl_form_series,
        "batting_similarities": bat_similarities,
        "bowling_similarities": bowl_similarities,
        "venue_baselines": venue_baselines,
        "era_baselines": era_baselines,
        "era_summary": era_summary,
        "batting_clutch": batting_clutch,
        "bowling_clutch": bowling_clutch,
        "matchups": matchups_df,
        "matchups_by_phase": matchups_phase_df,
        "batter_diversity": batter_diversity,
        "bowler_matchup_summary": bowler_matchup_summary,
        "wpa_batting": wpa_batting,
        "wpa_bowling": wpa_bowling,
        "batting_condition": batting_condition,
        "bowling_condition": bowling_condition,
        "batting_terciles": batting_terciles,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Quick spot-check helpers (call after pipeline)
# ---------------------------------------------------------------------------


def print_top_batters(
    bat_careers: pd.DataFrame, metric: str = "score_acceleration", n: int = 15
):
    """Print the top N non-provisional batters for a given metric."""
    col = metric if metric in bat_careers.columns else f"score_{metric}"
    if col not in bat_careers.columns:
        print(f"Column '{col}' not found.")
        return

    filtered = bat_careers[~bat_careers["is_provisional_bat"]].copy()
    top = filtered.nlargest(n, col)

    display_cols = [
        "batter",
        "innings_count",
        "total_runs",
        "career_sr",
        "score_acceleration",
        "score_power",
        "score_control",
    ]
    display_cols = [c for c in display_cols if c in top.columns]

    print(f"\n{'─' * 65}")
    print(f"  TOP {n} BATTERS by {col}")
    print(f"{'─' * 65}")
    print(top[display_cols].to_string(index=False))
    print()


def print_top_bowlers(
    bowl_careers: pd.DataFrame, metric: str = "score_accuracy", n: int = 15
):
    """Print the top N non-provisional bowlers for a given metric."""
    col = metric if metric in bowl_careers.columns else f"score_{metric}"
    if col not in bowl_careers.columns:
        print(f"Column '{col}' not found.")
        return

    filtered = bowl_careers[~bowl_careers["is_provisional_bowl"]].copy()
    top = filtered.nlargest(n, col)

    display_cols = [
        "bowler",
        "matches",
        "total_wickets",
        "career_economy",
        "score_accuracy",
        "score_control",
        "score_threat",
    ]
    display_cols = [c for c in display_cols if c in top.columns]

    print(f"\n{'─' * 65}")
    print(f"  TOP {n} BOWLERS by {col}")
    print(f"{'─' * 65}")
    print(top[display_cols].to_string(index=False))
    print()


def print_player_profile(career_df: pd.DataFrame, name: str, role: str = "bat"):
    """
    Print a detailed profile for a player (fuzzy name match).

    Parameters
    ----------
    career_df : batting_careers or bowling_careers DataFrame.
    name : str  — substring to match (e.g. "Kohli", "Bumrah").
    role : "bat" or "bowl"
    """
    if role == "bat":
        results = lookup_player(
            career_df, player_name=name, id_col="batter_id", name_col="batter"
        )
    else:
        results = lookup_player(
            career_df, player_name=name, id_col="bowler_id", name_col="bowler"
        )

    if results.empty:
        print(f"  No player found matching '{name}'.")
        return

    for _, row in results.iterrows():
        print(f"\n{'═' * 55}")
        if role == "bat":
            prov_marker = " (?)" if row.get("is_provisional_bat", False) else ""
            print(f"  {row['batter']}{prov_marker}")
            print(f"{'═' * 55}")
            print(f"  Innings : {int(row['innings_count']):>5}")
            print(f"  Runs    : {int(row['total_runs']):>5}")
            print(f"  SR      : {row['career_sr']:>8.1f}")
            print(f"  Avg     : {row['career_avg']:>8.1f}")
            print(
                f"  4s / 6s : {int(row['total_fours']):>4} / {int(row['total_sixes'])}"
            )
            print(f"{'─' * 55}")
            for m in ["acceleration", "power", "control"]:
                sc = row.get(f"score_{m}", 0)
                bar = "█" * int(sc / 2) + "░" * (50 - int(sc / 2))
                print(f"  {m.upper():>14s}  {bar}  {sc:.1f}")
        else:
            prov_marker = " (?)" if row.get("is_provisional_bowl", False) else ""
            print(f"  {row['bowler']}{prov_marker}")
            print(f"{'═' * 55}")
            print(f"  Matches : {int(row['matches']):>5}")
            print(f"  Wickets : {int(row['total_wickets']):>5}")
            print(f"  Econ    : {row['career_economy']:>8.2f}")
            print(f"  SR      : {row['career_sr_bowl']:>8.1f}")
            print(f"{'─' * 55}")
            for m in ["accuracy", "control", "threat"]:
                sc = row.get(f"score_{m}", 0)
                bar = "█" * int(sc / 2) + "░" * (50 - int(sc / 2))
                print(f"  {m.upper():>14s}  {bar}  {sc:.1f}")
        print(f"{'═' * 55}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Cricket Metrics — T20 Player Profiling Pipeline",
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=os.path.join(_PROJECT_ROOT, "t20s_male_json"),
        help="Path to directory containing Cricsheet JSON match files "
        "(default: t20s_male_json in the project root)",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to a YAML config file (default: config.yaml in project root)",
    )
    parser.add_argument(
        "--output",
        dest="output_dir",
        default=os.path.join(_PROJECT_ROOT, "output"),
        help="Directory for CSV / Parquet outputs (default: output/)",
    )
    parser.add_argument(
        "--format",
        dest="data_format",
        default="t20i",
        choices=["t20i", "ipl"],
        help="Data format: t20i (international) or ipl (franchise league). "
        "Franchise formats use win-rate-based team quality instead of "
        "ICC rankings. (default: t20i)",
    )
    args = parser.parse_args()

    data_path = args.data_dir
    if not os.path.isdir(data_path):
        print(f"ERROR: Data directory not found: {data_path}")
        sys.exit(1)

    output_path = args.output_dir
    results = run_pipeline(
        data_path,
        output_dir=output_path,
        config_path=args.config_path,
        data_format=args.data_format,
    )

    # ── Quick sanity-check printouts ──
    bat = results["batting_careers"]
    bowl = results["bowling_careers"]

    print_top_batters(bat, "score_acceleration")
    print_top_batters(bat, "score_power")
    print_top_batters(bat, "score_control")
    print_top_bowlers(bowl, "score_accuracy")
    print_top_bowlers(bowl, "score_threat")

    # Spot-check some well-known players
    print("\n" + "=" * 65)
    print("  SPOT-CHECK: Well-known player profiles")
    print("=" * 65)

    for name in ["Kohli", "Buttler", "Babar", "SA Yadav"]:
        print_player_profile(bat, name, role="bat")

    for name in ["Bumrah", "Rashid Khan", "Nortje", "Shaheen"]:
        print_player_profile(bowl, name, role="bowl")
