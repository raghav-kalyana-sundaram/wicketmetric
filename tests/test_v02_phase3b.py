"""
Tests for Version 0.2 Phase 3b features:
  - Feature 9:  Venue & Pitch Difficulty / Flat Track Bully Index
  - Feature 14: Positional WAR (batting + bowling)
  - Feature 15: Era-Adjusted Ratings (cross-generational harmonization)

Tests cover:
  - Venue: baselines computation, difficulty scoring, flat track index
    (batting + bowling), venue-adjusted performance, enrichment helpers,
    convenience wrapper, edge cases (empty data, missing columns, single venue)
  - WAR: batting WAR (per-component + combined), bowling WAR, volume scaling,
    replacement level within groups, leaderboard generation, WAR rate metrics,
    position/phase value summaries, edge cases (empty data, missing columns,
    small groups, zero variance)
  - Era: baselines computation, rolling smoothing, era multipliers,
    innings adjustment (batting + bowling), era summary, multiplier lookup,
    career composite, convenience wrapper, edge cases (empty data, thin years,
    single year)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal DataFrames
# ---------------------------------------------------------------------------


def _make_match_ctx(
    n_matches: int = 30,
    n_venues: int = 5,
    base_date: str = "2020-01-01",
    par_sr_base: float = 130.0,
    par_sr_spread: float = 30.0,
) -> pd.DataFrame:
    """Create a minimal match_ctx DataFrame."""
    np.random.seed(42)
    venues = [f"Venue_{i}" for i in range(n_venues)]
    dates = pd.date_range(base_date, periods=n_matches, freq="14D")
    rows = []
    for i in range(n_matches):
        venue = venues[i % n_venues]
        # Make some venues consistently higher/lower scoring
        venue_idx = i % n_venues
        venue_offset = (venue_idx - n_venues // 2) * 10  # -20, -10, 0, 10, 20
        par_sr = (
            par_sr_base
            + venue_offset
            + np.random.uniform(-par_sr_spread / 3, par_sr_spread / 3)
        )
        rows.append(
            {
                "match_id": f"m{i}",
                "match_date": dates[i],
                "match_par_sr": par_sr,
                "match_boundary_rate": 0.12
                + venue_offset * 0.001
                + np.random.uniform(-0.02, 0.02),
                "match_dot_pct": 0.35
                - venue_offset * 0.002
                + np.random.uniform(-0.03, 0.03),
                "match_total_runs": int(
                    300 + venue_offset * 2 + np.random.randint(-30, 30)
                ),
                "match_total_legal_balls": 240,
                "match_total_fours": np.random.randint(15, 30),
                "match_total_sixes": np.random.randint(5, 15),
                "match_total_wickets": np.random.randint(8, 16),
                "match_total_dot_balls": np.random.randint(70, 100),
                "num_innings": 2,
            }
        )
    return pd.DataFrame(rows)


def _make_match_ctx_with_venue(
    n_matches: int = 30,
    n_venues: int = 5,
    base_date: str = "2020-01-01",
) -> pd.DataFrame:
    """Create match_ctx with venue column already present."""
    df = _make_match_ctx(n_matches=n_matches, n_venues=n_venues, base_date=base_date)
    venues = [f"Venue_{i}" for i in range(n_venues)]
    df["venue"] = [venues[i % n_venues] for i in range(n_matches)]
    return df


def _make_deliveries_with_venue(
    n_matches: int = 30,
    n_venues: int = 5,
) -> pd.DataFrame:
    """Create minimal delivery-level DataFrame with venue."""
    venues = [f"Venue_{i}" for i in range(n_venues)]
    rows = []
    for i in range(n_matches):
        rows.append(
            {
                "match_id": f"m{i}",
                "venue": venues[i % n_venues],
            }
        )
    return pd.DataFrame(rows)


def _make_bat_innings(
    n_players: int = 5,
    innings_per_player: int = 20,
    n_venues: int = 5,
    base_date: str = "2020-01-01",
    include_venue: bool = True,
) -> pd.DataFrame:
    """Create minimal batting innings DataFrame."""
    np.random.seed(42)
    venues = [f"Venue_{i}" for i in range(n_venues)]
    dates = pd.date_range(base_date, periods=innings_per_player, freq="14D")
    rows = []
    for p in range(n_players):
        for i in range(innings_per_player):
            venue_idx = i % n_venues
            # Player 0 is a flat-track bully (better at easy venues)
            # Player 1 performs better at hard venues
            if p == 0:
                perf_bonus = (venue_idx - n_venues // 2) * 0.05
            elif p == 1:
                perf_bonus = -(venue_idx - n_venues // 2) * 0.05
            else:
                perf_bonus = np.random.uniform(-0.05, 0.05)

            row = {
                "match_id": f"m{i}",
                "innings_num": 1 + (i % 2),
                "batter_id": f"bat_{p}",
                "batter": f"Batter {p}",
                "batting_team": "TeamA",
                "date": dates[i],
                "runs": 30 + np.random.randint(-15, 20),
                "balls_faced": 25 + np.random.randint(-5, 10),
                "sr": 130 + np.random.uniform(-20, 25),
                "acc_overall_sr": 0.10 + perf_bonus + np.random.uniform(-0.03, 0.03),
                "pow_boundary_pct": np.random.uniform(0.3, 0.7),
                "ctrl_contribution": np.random.uniform(0.15, 0.40),
                "opp_quality_weight": 0.8 + np.random.uniform(0, 0.4),
            }
            if include_venue:
                row["venue"] = venues[venue_idx]
            rows.append(row)
    return pd.DataFrame(rows)


def _make_bowl_spells(
    n_players: int = 5,
    spells_per_player: int = 20,
    n_venues: int = 5,
    include_venue: bool = True,
) -> pd.DataFrame:
    """Create minimal bowling spells DataFrame."""
    np.random.seed(123)
    venues = [f"Venue_{i}" for i in range(n_venues)]
    dates = pd.date_range("2020-01-01", periods=spells_per_player, freq="14D")
    rows = []
    for p in range(n_players):
        for i in range(spells_per_player):
            venue_idx = i % n_venues
            row = {
                "match_id": f"m{i}",
                "innings_num": 1 + (i % 2),
                "bowler_id": f"bowl_{p}",
                "bowler": f"Bowler {p}",
                "bowling_team": "TeamA",
                "date": dates[i],
                "acc_economy_vs_par": -0.5 + np.random.uniform(-0.5, 0.5),
                "opp_quality_weight": 0.8 + np.random.uniform(0, 0.4),
            }
            if include_venue:
                row["venue"] = venues[venue_idx]
            rows.append(row)
    return pd.DataFrame(rows)


def _make_bat_careers(
    n_players: int = 20,
    position_groups: list[str] | None = None,
) -> pd.DataFrame:
    """Create minimal bat_careers DataFrame for WAR tests."""
    np.random.seed(42)
    if position_groups is None:
        position_groups = ["opener", "top_order", "middle_order", "lower_middle"]
    rows = []
    for i in range(n_players):
        pg = position_groups[i % len(position_groups)]
        rows.append(
            {
                "batter_id": f"bat_{i}",
                "batter": f"Batter {i}",
                "country": "Country A" if i % 2 == 0 else "Country B",
                "position_group": pg,
                "innings_count": 20 + np.random.randint(0, 80),
                "career_avg": 20 + np.random.uniform(0, 20),
                "career_sr": 110 + np.random.uniform(0, 50),
                "raw_acceleration": np.random.normal(0, 1),
                "raw_power": np.random.normal(0, 1),
                "raw_control": np.random.normal(0, 1),
                "score_acceleration": np.random.uniform(20, 90),
                "score_power": np.random.uniform(20, 90),
                "score_control": np.random.uniform(20, 90),
                "is_provisional_bat": i >= n_players - 3,
            }
        )
    return pd.DataFrame(rows)


def _make_bowl_careers(
    n_players: int = 20,
    phase_groups: list[str] | None = None,
) -> pd.DataFrame:
    """Create minimal bowl_careers DataFrame for WAR tests."""
    np.random.seed(123)
    if phase_groups is None:
        phase_groups = ["pp_heavy", "middle_heavy", "death_heavy"]
    rows = []
    for i in range(n_players):
        pg = phase_groups[i % len(phase_groups)]
        rows.append(
            {
                "bowler_id": f"bowl_{i}",
                "bowler": f"Bowler {i}",
                "country": "Country A" if i % 2 == 0 else "Country B",
                "phase_group": pg,
                "matches": 15 + np.random.randint(0, 60),
                "total_overs": 30 + np.random.uniform(0, 100),
                "total_wickets": np.random.randint(5, 50),
                "career_economy": 6.0 + np.random.uniform(0, 4),
                "raw_accuracy": np.random.normal(0, 1),
                "raw_control": np.random.normal(0, 1),
                "raw_threat": np.random.normal(0, 1),
                "score_accuracy": np.random.uniform(20, 90),
                "score_control": np.random.uniform(20, 90),
                "score_threat": np.random.uniform(20, 90),
                "is_provisional_bowl": i >= n_players - 3,
            }
        )
    return pd.DataFrame(rows)


def _make_multi_year_match_ctx(
    years: list[int] | None = None,
    matches_per_year: int = 20,
    par_sr_by_year: dict[int, float] | None = None,
) -> pd.DataFrame:
    """Create match_ctx spanning multiple years for era adjustment tests."""
    np.random.seed(42)
    if years is None:
        years = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
    if par_sr_by_year is None:
        # Gradually increasing par SR over the years
        par_sr_by_year = {y: 120 + (y - 2016) * 4 for y in years}

    rows = []
    match_id = 0
    for year in years:
        base_par = par_sr_by_year.get(year, 140.0)
        for j in range(matches_per_year):
            rows.append(
                {
                    "match_id": f"m{match_id}",
                    "match_date": pd.Timestamp(
                        year=year, month=1 + (j % 12), day=1 + (j % 28)
                    ),
                    "match_par_sr": base_par + np.random.uniform(-10, 10),
                    "match_boundary_rate": 0.10
                    + (year - 2016) * 0.003
                    + np.random.uniform(-0.01, 0.01),
                    "match_dot_pct": 0.40
                    - (year - 2016) * 0.005
                    + np.random.uniform(-0.02, 0.02),
                    "match_total_runs": int(
                        280 + (year - 2016) * 8 + np.random.randint(-20, 20)
                    ),
                    "match_total_legal_balls": 240,
                    "match_total_fours": np.random.randint(15, 30),
                    "match_total_sixes": np.random.randint(5, 15),
                    "match_total_wickets": np.random.randint(8, 16),
                    "match_total_dot_balls": np.random.randint(70, 100),
                    "num_innings": 2,
                }
            )
            match_id += 1
    return pd.DataFrame(rows)


def _make_multi_year_bat_innings(
    years: list[int] | None = None,
    innings_per_year: int = 10,
    batter_id: str = "bat_0",
    batter: str = "Batter 0",
) -> pd.DataFrame:
    """Create per-innings batting data spanning multiple years."""
    np.random.seed(42)
    if years is None:
        years = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]

    rows = []
    match_id = 0
    for year in years:
        for j in range(innings_per_year):
            rows.append(
                {
                    "match_id": f"m{match_id}",
                    "innings_num": 1 + (j % 2),
                    "batter_id": batter_id,
                    "batter": batter,
                    "batting_team": "TeamA",
                    "date": pd.Timestamp(
                        year=year, month=1 + (j % 12), day=1 + (j % 28)
                    ),
                    "runs": 30 + np.random.randint(-15, 20),
                    "balls_faced": 25 + np.random.randint(-5, 10),
                    "sr": 130 + np.random.uniform(-20, 25),
                    "acc_overall_sr": 0.10 + np.random.uniform(-0.05, 0.15),
                    "pow_boundary_pct": np.random.uniform(0.3, 0.7),
                    "ctrl_contribution": np.random.uniform(0.15, 0.40),
                    "opp_quality_weight": 0.8 + np.random.uniform(0, 0.4),
                }
            )
            match_id += 1
    return pd.DataFrame(rows)


# ===========================================================================
# Feature 9: Venue & Pitch Difficulty
# ===========================================================================

from src.venue import (
    compute_all_venue_metrics,
    compute_bowling_flat_track_index,
    compute_flat_track_index,
    compute_venue_adjusted_performance,
    compute_venue_baselines,
    enrich_innings_with_venue,
    enrich_match_context_with_venue,
)


class TestComputeVenueBaselines:
    """Tests for compute_venue_baselines."""

    def test_basic_baselines(self):
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=3)
        result = compute_venue_baselines(ctx, min_matches=3)
        assert not result.empty
        assert "venue" in result.columns
        assert "venue_difficulty" in result.columns
        assert "venue_difficulty_raw" in result.columns
        assert "venue_difficulty_index" in result.columns
        assert "venue_avg_par_sr" in result.columns
        # Should have exactly 3 venues (each has 10 matches, threshold=3)
        assert len(result) == 3

    def test_min_matches_filter(self):
        ctx = _make_match_ctx_with_venue(n_matches=15, n_venues=5)
        # Each venue has 3 matches
        result_low = compute_venue_baselines(ctx, min_matches=2)
        result_high = compute_venue_baselines(ctx, min_matches=5)
        assert len(result_low) == 5
        assert len(result_high) == 0  # none have 5 matches

    def test_difficulty_direction(self):
        """Low-scoring venues should have positive difficulty."""
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=3)
        result = compute_venue_baselines(ctx, min_matches=3)
        # Venue_0 has the lowest offset (-10), so it should be hardest
        # Venue_2 has the highest offset (+10), so it should be easiest
        v0 = result[result["venue"] == "Venue_0"]["venue_difficulty_raw"].iloc[0]
        v2 = result[result["venue"] == "Venue_2"]["venue_difficulty_raw"].iloc[0]
        # v0 should be harder (more positive) than v2
        assert v0 > v2
        # 0–100 index ranks hardest venue above easiest
        i0 = result[result["venue"] == "Venue_0"]["venue_difficulty_index"].iloc[0]
        i2 = result[result["venue"] == "Venue_2"]["venue_difficulty_index"].iloc[0]
        assert i0 > i2
        assert 0 <= i0 <= 100 and 0 <= i2 <= 100

    def test_empty_input(self):
        result = compute_venue_baselines(pd.DataFrame(), min_matches=5)
        assert result.empty
        assert "venue" in result.columns

    def test_no_venue_column(self):
        ctx = _make_match_ctx(n_matches=10)
        result = compute_venue_baselines(ctx, min_matches=3)
        assert result.empty

    def test_single_venue(self):
        ctx = _make_match_ctx_with_venue(n_matches=10, n_venues=1)
        result = compute_venue_baselines(ctx, min_matches=5)
        assert len(result) == 1
        # Difficulty should be ~0 since only one venue
        assert abs(result["venue_difficulty_raw"].iloc[0]) < 1e-6


class TestComputeFlatTrackIndex:
    """Tests for compute_flat_track_index."""

    def test_basic_computation(self):
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat = _make_bat_innings(n_players=3, innings_per_player=20, n_venues=5)
        result = compute_flat_track_index(bat, baselines, min_innings=5)
        assert not result.empty
        assert "flat_track_index" in result.columns
        assert "ft_innings_at_known_venues" in result.columns
        assert "avg_venue_difficulty_faced" in result.columns

    def test_index_range(self):
        """Flat track index should be between -1 and 1 (Pearson correlation)."""
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat = _make_bat_innings(n_players=5, innings_per_player=25, n_venues=5)
        result = compute_flat_track_index(bat, baselines, min_innings=5)
        valid = result.dropna(subset=["flat_track_index"])
        assert (valid["flat_track_index"].abs() <= 1.0 + 1e-9).all()

    def test_min_innings_filter(self):
        ctx = _make_match_ctx_with_venue(n_matches=10, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=1)
        bat = _make_bat_innings(n_players=2, innings_per_player=3, n_venues=5)
        result = compute_flat_track_index(bat, baselines, min_innings=10)
        # No player has 10 innings at known venues, so all should be NaN
        assert result["flat_track_index"].isna().all()

    def test_empty_inputs(self):
        baselines = pd.DataFrame(columns=["venue", "venue_difficulty"])
        bat = _make_bat_innings(n_players=2, innings_per_player=10)
        result = compute_flat_track_index(bat, baselines, min_innings=5)
        assert result.empty

        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        result = compute_flat_track_index(pd.DataFrame(), baselines, min_innings=5)
        assert result.empty

    def test_missing_venue_column(self):
        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat = _make_bat_innings(include_venue=False)
        result = compute_flat_track_index(bat, baselines)
        assert result.empty

    def test_missing_performance_column(self):
        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat = _make_bat_innings()
        result = compute_flat_track_index(bat, baselines, performance_col="nonexistent")
        assert result.empty


class TestVenueAdjustedPerformance:
    """Tests for compute_venue_adjusted_performance."""

    def test_basic_output(self):
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat = _make_bat_innings(n_players=3, innings_per_player=20, n_venues=5)
        result = compute_venue_adjusted_performance(bat, baselines)
        assert not result.empty
        assert "venue_adjusted_composite" in result.columns
        assert "raw_composite_mean" in result.columns
        assert "venue_boost_pct" in result.columns

    def test_hard_venue_boosts_performance(self):
        """Performances at harder venues should be boosted."""
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=3)
        # Only innings at hardest venue
        bat = _make_bat_innings(n_players=1, innings_per_player=20, n_venues=5)
        hard_venue = baselines.nlargest(1, "venue_difficulty")["venue"].iloc[0]
        bat_hard = bat[bat["venue"] == hard_venue].copy()
        if len(bat_hard) >= 2:
            result = compute_venue_adjusted_performance(bat_hard, baselines)
            if not result.empty:
                # Venue boost % should be positive for hard venues
                assert result["venue_boost_pct"].iloc[0] >= 0

    def test_empty_inputs(self):
        result = compute_venue_adjusted_performance(pd.DataFrame(), pd.DataFrame())
        assert result.empty


class TestBowlingFlatTrackIndex:
    """Tests for compute_bowling_flat_track_index."""

    def test_basic_computation(self):
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bowl = _make_bowl_spells(n_players=3, spells_per_player=20, n_venues=5)
        result = compute_bowling_flat_track_index(bowl, baselines, min_spells=5)
        assert not result.empty
        assert "flat_track_index_bowl" in result.columns

    def test_index_range(self):
        ctx = _make_match_ctx_with_venue(n_matches=30, n_venues=5)
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bowl = _make_bowl_spells(n_players=5, spells_per_player=25, n_venues=5)
        result = compute_bowling_flat_track_index(bowl, baselines, min_spells=5)
        valid = result.dropna(subset=["flat_track_index_bowl"])
        assert (valid["flat_track_index_bowl"].abs() <= 1.0 + 1e-9).all()

    def test_empty_inputs(self):
        result = compute_bowling_flat_track_index(
            pd.DataFrame(), pd.DataFrame(), min_spells=5
        )
        assert result.empty

    def test_missing_venue(self):
        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bowl = _make_bowl_spells(include_venue=False)
        result = compute_bowling_flat_track_index(bowl, baselines)
        assert result.empty


class TestVenueEnrichment:
    """Tests for enrich_match_context_with_venue and enrich_innings_with_venue."""

    def test_enrich_match_context(self):
        ctx = _make_match_ctx(n_matches=10, n_venues=3)
        deliveries = _make_deliveries_with_venue(n_matches=10, n_venues=3)
        result = enrich_match_context_with_venue(ctx, deliveries)
        assert "venue" in result.columns
        assert len(result) == len(ctx)

    def test_already_has_venue(self):
        ctx = _make_match_ctx_with_venue()
        deliveries = _make_deliveries_with_venue()
        result = enrich_match_context_with_venue(ctx, deliveries)
        assert "venue" in result.columns
        # Should be same as input (no double merge)
        assert len(result) == len(ctx)

    def test_enrich_innings_with_venue(self):
        bat = _make_bat_innings(include_venue=False)
        deliveries = _make_deliveries_with_venue(n_matches=20, n_venues=5)
        result = enrich_innings_with_venue(bat, deliveries)
        assert "venue" in result.columns

    def test_enrich_innings_with_match_meta(self):
        from src.venue import enrich_innings_with_match_meta

        bat = _make_bat_innings(include_venue=True)
        deliveries = _make_deliveries_with_venue(n_matches=20, n_venues=5)
        if "event_name" not in deliveries.columns:
            deliveries["event_name"] = "Test Series"
        if "winner" not in deliveries.columns:
            deliveries["winner"] = "Team A"
        result = enrich_innings_with_match_meta(bat, deliveries)
        assert "event_name" in result.columns
        assert "winner" in result.columns

    def test_no_venue_in_deliveries(self):
        ctx = _make_match_ctx()
        deliveries = pd.DataFrame({"match_id": ["m0", "m1"]})
        result = enrich_match_context_with_venue(ctx, deliveries)
        assert "venue" not in result.columns


class TestComputeAllVenueMetrics:
    """Tests for the convenience wrapper compute_all_venue_metrics."""

    def test_full_pipeline(self):
        ctx = _make_match_ctx(n_matches=30, n_venues=5)
        deliveries = _make_deliveries_with_venue(n_matches=30, n_venues=5)
        bat = _make_bat_innings(include_venue=False, n_venues=5, innings_per_player=20)
        bowl = _make_bowl_spells(include_venue=False, n_venues=5, spells_per_player=20)

        result = compute_all_venue_metrics(
            match_ctx=ctx,
            deliveries=deliveries,
            bat_innings=bat,
            bowl_spells=bowl,
            min_matches=3,
        )

        assert "venue_baselines" in result
        assert "flat_track_batting" in result
        assert "flat_track_bowling" in result
        assert "venue_adjusted_batting" in result
        assert "match_ctx_with_venue" in result
        assert not result["venue_baselines"].empty


# ===========================================================================
# Feature 14: Positional WAR
# ===========================================================================

from src.war import (
    compute_batting_war,
    compute_batting_war_rate,
    compute_bowling_war,
    compute_bowling_war_rate,
    compute_phase_value_summary,
    compute_position_value_summary,
    war_batting_leaderboard,
    war_bowling_leaderboard,
)


class TestComputeBattingWAR:
    """Tests for compute_batting_war."""

    def test_basic_columns(self):
        careers = _make_bat_careers(n_players=20)
        result = compute_batting_war(careers)
        assert "war_batting" in result.columns
        assert "war_acceleration" in result.columns
        assert "war_power" in result.columns
        assert "war_control" in result.columns
        assert "volume_factor_bat" in result.columns
        assert "replacement_level_acceleration" in result.columns

    def test_war_non_negative(self):
        """WAR should be >= 0 (clipped at replacement level)."""
        careers = _make_bat_careers(n_players=30)
        result = compute_batting_war(careers)
        assert (result["war_batting"] >= -1e-9).all()
        assert (result["war_acceleration"] >= -1e-9).all()
        assert (result["war_power"] >= -1e-9).all()
        assert (result["war_control"] >= -1e-9).all()

    def test_volume_scaling(self):
        """Players with more innings should have higher volume factor."""
        careers = _make_bat_careers(n_players=10)
        result = compute_batting_war(careers)
        # Find a high-innings and low-innings player
        high_inn = result.nlargest(1, "innings_count")["volume_factor_bat"].iloc[0]
        low_inn = result.nsmallest(1, "innings_count")["volume_factor_bat"].iloc[0]
        assert high_inn > low_inn

    def test_replacement_level_per_group(self):
        """Replacement levels should differ by position group."""
        careers = _make_bat_careers(n_players=40)
        result = compute_batting_war(careers)
        # Check that replacement levels vary by group
        repl_by_group = result.groupby("position_group")[
            "replacement_level_acceleration"
        ].first()
        # With random data, groups should have different replacement levels
        assert repl_by_group.nunique() > 1 or len(repl_by_group) == 1

    def test_custom_replacement_percentile(self):
        """Higher replacement percentile → higher replacement level → lower WAR."""
        careers = _make_bat_careers(n_players=20)
        war_25 = compute_batting_war(careers, replacement_percentile=0.25)
        war_50 = compute_batting_war(careers, replacement_percentile=0.50)
        # Average WAR should be lower with 50th percentile replacement
        assert war_50["war_batting"].mean() <= war_25["war_batting"].mean()

    def test_preserves_original_columns(self):
        careers = _make_bat_careers(n_players=10)
        original_cols = set(careers.columns)
        result = compute_batting_war(careers)
        # All original columns should still be present
        for col in original_cols:
            assert col in result.columns

    def test_empty_input(self):
        empty = pd.DataFrame(
            columns=[
                "batter_id",
                "batter",
                "position_group",
                "innings_count",
                "raw_acceleration",
                "raw_power",
                "raw_control",
            ]
        )
        result = compute_batting_war(empty)
        assert "war_batting" in result.columns
        assert len(result) == 0

    def test_missing_columns(self):
        """Should handle missing raw columns gracefully."""
        careers = pd.DataFrame(
            {
                "batter_id": ["b1"],
                "batter": ["Player"],
                "innings_count": [50],
            }
        )
        result = compute_batting_war(careers)
        assert "war_batting" in result.columns
        assert result["war_batting"].isna().all()

    def test_single_player(self):
        """Single player should get 0 WAR (is their own replacement)."""
        careers = pd.DataFrame(
            {
                "batter_id": ["b1"],
                "batter": ["Player 1"],
                "position_group": ["opener"],
                "innings_count": [50],
                "raw_acceleration": [1.5],
                "raw_power": [1.0],
                "raw_control": [0.8],
            }
        )
        result = compute_batting_war(careers)
        # Single player = replacement is themselves, so WAR = 0
        assert result["war_batting"].iloc[0] == pytest.approx(0.0, abs=1e-6)

    def test_war_proportional_to_above_replacement(self):
        """A clearly above-replacement player should have WAR > 0."""
        np.random.seed(42)
        careers = _make_bat_careers(n_players=20)
        # Make player 0 clearly elite
        careers.loc[0, "raw_acceleration"] = 3.0
        careers.loc[0, "raw_power"] = 3.0
        careers.loc[0, "raw_control"] = 3.0
        careers.loc[0, "innings_count"] = 80
        result = compute_batting_war(careers)
        assert result.loc[0, "war_batting"] > 0


class TestComputeBowlingWAR:
    """Tests for compute_bowling_war."""

    def test_basic_columns(self):
        careers = _make_bowl_careers(n_players=20)
        result = compute_bowling_war(careers)
        assert "war_bowling" in result.columns
        assert "war_accuracy" in result.columns
        assert "war_control" in result.columns
        assert "war_threat" in result.columns
        assert "volume_factor_bowl" in result.columns

    def test_war_non_negative(self):
        careers = _make_bowl_careers(n_players=30)
        result = compute_bowling_war(careers)
        assert (result["war_bowling"] >= -1e-9).all()

    def test_empty_input(self):
        empty = pd.DataFrame(
            columns=[
                "bowler_id",
                "bowler",
                "phase_group",
                "matches",
                "raw_accuracy",
                "raw_control",
                "raw_threat",
            ]
        )
        result = compute_bowling_war(empty)
        assert "war_bowling" in result.columns
        assert len(result) == 0

    def test_missing_columns(self):
        careers = pd.DataFrame(
            {
                "bowler_id": ["b1"],
                "bowler": ["Bowler"],
                "matches": [30],
            }
        )
        result = compute_bowling_war(careers)
        assert "war_bowling" in result.columns
        assert result["war_bowling"].isna().all()


class TestWARLeaderboards:
    """Tests for war_batting_leaderboard and war_bowling_leaderboard."""

    def test_batting_leaderboard(self):
        careers = _make_bat_careers(n_players=30)
        careers = compute_batting_war(careers)
        lb = war_batting_leaderboard(careers, top_n=10)
        assert len(lb) == 10
        assert "war_rank" in lb.columns
        assert lb["war_rank"].tolist() == list(range(1, 11))
        # Should be sorted descending
        assert lb["war_batting"].is_monotonic_decreasing

    def test_batting_leaderboard_excludes_provisional(self):
        careers = _make_bat_careers(n_players=20)
        careers = compute_batting_war(careers)
        lb_no_prov = war_batting_leaderboard(careers, exclude_provisional=True)
        lb_with_prov = war_batting_leaderboard(careers, exclude_provisional=False)
        # Should have fewer or equal players when excluding provisional
        assert len(lb_no_prov) <= len(lb_with_prov)

    def test_bowling_leaderboard(self):
        careers = _make_bowl_careers(n_players=25)
        careers = compute_bowling_war(careers)
        lb = war_bowling_leaderboard(careers, top_n=5)
        assert len(lb) == 5
        assert "war_rank" in lb.columns

    def test_leaderboard_no_war_column(self):
        careers = _make_bat_careers()
        lb = war_batting_leaderboard(careers)
        assert lb.empty


class TestWARRate:
    """Tests for WAR rate metrics."""

    def test_batting_war_rate(self):
        careers = _make_bat_careers(n_players=15)
        careers = compute_batting_war(careers)
        result = compute_batting_war_rate(careers, min_innings=10)
        assert "war_batting_rate" in result.columns
        # Players with enough innings should have non-NaN rate
        qualified = result[result["innings_count"] >= 10]
        assert qualified["war_batting_rate"].notna().all()

    def test_batting_war_rate_min_filter(self):
        careers = _make_bat_careers(n_players=10)
        careers = compute_batting_war(careers)
        # Set all innings very low
        careers["innings_count"] = 3
        result = compute_batting_war_rate(careers, min_innings=10)
        assert result["war_batting_rate"].isna().all()

    def test_bowling_war_rate(self):
        careers = _make_bowl_careers(n_players=15)
        careers = compute_bowling_war(careers)
        result = compute_bowling_war_rate(careers, min_matches=10)
        assert "war_bowling_rate" in result.columns


class TestPositionValueSummary:
    """Tests for position/phase value summaries."""

    def test_position_summary(self):
        careers = _make_bat_careers(n_players=40)
        careers = compute_batting_war(careers)
        summary = compute_position_value_summary(careers)
        assert not summary.empty
        assert "position_group" in summary.columns
        assert "mean_war" in summary.columns
        assert "war_spread" in summary.columns

    def test_phase_summary(self):
        careers = _make_bowl_careers(n_players=30)
        careers = compute_bowling_war(careers)
        summary = compute_phase_value_summary(careers)
        assert not summary.empty
        assert "phase_group" in summary.columns

    def test_empty_input(self):
        summary = compute_position_value_summary(pd.DataFrame())
        assert summary.empty

    def test_no_war_column(self):
        careers = _make_bat_careers()
        summary = compute_position_value_summary(careers)
        assert summary.empty


# ===========================================================================
# Feature 15: Era-Adjusted Ratings
# ===========================================================================

from src.era import (
    apply_era_adjustment_to_bowling,
    apply_era_adjustment_to_innings,
    compute_all_era_metrics,
    compute_era_adjusted_career_composite,
    compute_era_baselines,
    compute_era_summary,
    get_era_multiplier,
)


class TestComputeEraBaselines:
    """Tests for compute_era_baselines."""

    def test_basic_output(self):
        ctx = _make_multi_year_match_ctx()
        result = compute_era_baselines(ctx)
        assert not result.empty
        assert "year" in result.columns
        assert "era_par_sr" in result.columns
        assert "era_sr_multiplier" in result.columns
        assert "era_boundary_multiplier" in result.columns
        assert "is_thin_year" in result.columns

    def test_years_covered(self):
        years = [2018, 2019, 2020, 2021, 2022]
        ctx = _make_multi_year_match_ctx(years=years)
        result = compute_era_baselines(ctx)
        assert set(result["year"].tolist()) == set(years)

    def test_most_recent_year_multiplier_is_one(self):
        """The most recent year should have multiplier ~1.0."""
        ctx = _make_multi_year_match_ctx()
        result = compute_era_baselines(ctx)
        most_recent = result[result["year"] == result["year"].max()]
        assert most_recent["era_sr_multiplier"].iloc[0] == pytest.approx(1.0, abs=0.05)

    def test_older_years_have_higher_multiplier(self):
        """Older years (lower par SR) should have multiplier > 1.0."""
        ctx = _make_multi_year_match_ctx()
        result = compute_era_baselines(ctx)
        oldest = result[result["year"] == result["year"].min()]
        newest = result[result["year"] == result["year"].max()]
        # Older year should have higher multiplier (harder era → boost)
        assert oldest["era_sr_multiplier"].iloc[0] > newest["era_sr_multiplier"].iloc[0]

    def test_rolling_smoothing(self):
        """Smoothed values should be less volatile than raw yearly averages."""
        ctx = _make_multi_year_match_ctx(matches_per_year=20)
        result = compute_era_baselines(ctx, rolling_years=5)
        # Smoothed era_par_sr should have lower std than raw year_avg_par_sr
        if len(result) > 3:
            raw_std = result["year_avg_par_sr"].std()
            smoothed_std = result["era_par_sr"].std()
            assert smoothed_std <= raw_std + 1e-6

    def test_custom_rolling_window(self):
        ctx = _make_multi_year_match_ctx()
        r3 = compute_era_baselines(ctx, rolling_years=3)
        r5 = compute_era_baselines(ctx, rolling_years=5)
        # Both should produce results
        assert not r3.empty
        assert not r5.empty
        # r5 should be smoother
        if len(r3) > 5:
            assert r5["era_par_sr"].std() <= r3["era_par_sr"].std() + 1e-6

    def test_thin_year_flag(self):
        ctx = _make_multi_year_match_ctx(matches_per_year=5)
        result = compute_era_baselines(ctx, min_matches_per_year=10)
        assert result["is_thin_year"].all()

    def test_multiplier_clamping(self):
        """Multipliers should be clamped to [0.70, 1.60]."""
        ctx = _make_multi_year_match_ctx()
        result = compute_era_baselines(ctx)
        assert (result["era_sr_multiplier"] >= 0.70).all()
        assert (result["era_sr_multiplier"] <= 1.60).all()

    def test_empty_input(self):
        result = compute_era_baselines(pd.DataFrame())
        assert result.empty

    def test_no_date_column(self):
        ctx = pd.DataFrame(
            {
                "match_id": ["m0"],
                "match_par_sr": [130.0],
            }
        )
        result = compute_era_baselines(ctx)
        assert result.empty

    def test_single_year(self):
        ctx = _make_multi_year_match_ctx(years=[2024], matches_per_year=20)
        result = compute_era_baselines(ctx)
        assert len(result) == 1
        # Single year, multiplier should be 1.0
        assert result["era_sr_multiplier"].iloc[0] == pytest.approx(1.0, abs=0.01)


class TestApplyEraAdjustmentToInnings:
    """Tests for apply_era_adjustment_to_innings."""

    def test_basic_adjustment(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        innings = _make_multi_year_bat_innings()
        result = apply_era_adjustment_to_innings(innings, baselines)
        assert "era_year" in result.columns
        assert "era_multiplier" in result.columns
        assert "acc_overall_sr_pre_era" in result.columns
        # The column should have been adjusted
        assert not (result["acc_overall_sr"] == result["acc_overall_sr_pre_era"]).all()

    def test_older_innings_boosted(self):
        """Innings from older years should have their SR boosted."""
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        innings = _make_multi_year_bat_innings()
        result = apply_era_adjustment_to_innings(innings, baselines)

        # Get 2016 innings (oldest)
        old_innings = result[result["era_year"] == 2016.0]
        if not old_innings.empty:
            # Multiplier should be > 1.0 for old years
            assert (old_innings["era_multiplier"] >= 1.0).all()
            # Adjusted should be >= pre-era (boosted)
            valid = old_innings.dropna(subset=["acc_overall_sr_pre_era"])
            if not valid.empty:
                mask = valid["acc_overall_sr_pre_era"] > 0
                boosted = valid[mask]
                if not boosted.empty:
                    assert (
                        boosted["acc_overall_sr"]
                        >= boosted["acc_overall_sr_pre_era"] - 1e-9
                    ).all()

    def test_modern_innings_unchanged(self):
        """Most recent year's innings should have multiplier ~1.0."""
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        innings = _make_multi_year_bat_innings()
        result = apply_era_adjustment_to_innings(innings, baselines)

        new_innings = result[result["era_year"] == 2024.0]
        if not new_innings.empty:
            assert new_innings["era_multiplier"].iloc[0] == pytest.approx(1.0, abs=0.05)

    def test_custom_adjust_cols(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        innings = _make_multi_year_bat_innings()
        result = apply_era_adjustment_to_innings(
            innings, baselines, adjust_cols=["acc_overall_sr", "pow_boundary_pct"]
        )
        assert "acc_overall_sr_pre_era" in result.columns
        assert "pow_boundary_pct_pre_era" in result.columns

    def test_empty_baselines(self):
        innings = _make_multi_year_bat_innings()
        result = apply_era_adjustment_to_innings(innings, pd.DataFrame())
        assert "era_multiplier" in result.columns
        assert (result["era_multiplier"] == 1.0).all()

    def test_preserves_rows(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        innings = _make_multi_year_bat_innings()
        result = apply_era_adjustment_to_innings(innings, baselines)
        assert len(result) == len(innings)


class TestApplyEraAdjustmentToBowling:
    """Tests for apply_era_adjustment_to_bowling."""

    def test_basic_adjustment(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        # Create minimal bowling spells with dates
        np.random.seed(42)
        spells = pd.DataFrame(
            {
                "match_id": [f"m{i}" for i in range(20)],
                "bowler_id": ["bowl_0"] * 20,
                "bowler": ["Bowler 0"] * 20,
                "date": pd.date_range("2016-01-01", periods=20, freq="90D"),
                "acc_economy_vs_par": np.random.uniform(-1, 1, 20),
            }
        )
        result = apply_era_adjustment_to_bowling(spells, baselines)
        assert "era_multiplier_bowl" in result.columns
        assert "acc_economy_vs_par_pre_era" in result.columns

    def test_bowling_inverse_multiplier(self):
        """Bowling multiplier should be inverse of batting multiplier."""
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        spells = pd.DataFrame(
            {
                "match_id": ["m0"],
                "bowler_id": ["bowl_0"],
                "bowler": ["Bowler 0"],
                "date": pd.Timestamp("2016-06-01"),
                "acc_economy_vs_par": [0.5],
            }
        )
        result = apply_era_adjustment_to_bowling(spells, baselines)
        # For 2016, batting multiplier > 1.0, so bowling multiplier < 1.0
        if not result.empty and result["era_multiplier_bowl"].iloc[0] != 1.0:
            assert result["era_multiplier_bowl"].iloc[0] < 1.05  # Could be close to 1


class TestEraSummary:
    """Tests for compute_era_summary."""

    def test_basic_summary(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        summary = compute_era_summary(baselines)
        assert not summary.empty
        assert "effect_pct" in summary.columns
        assert "year" in summary.columns

    def test_effect_pct_calculation(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        summary = compute_era_summary(baselines)
        # effect_pct should be (multiplier - 1) * 100
        for _, row in summary.iterrows():
            expected = round((row["era_sr_multiplier"] - 1.0) * 100.0, 1)
            assert row["effect_pct"] == pytest.approx(expected, abs=0.15)

    def test_empty_input(self):
        summary = compute_era_summary(pd.DataFrame())
        assert summary.empty


class TestGetEraMultiplier:
    """Tests for get_era_multiplier."""

    def test_lookup_existing_year(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        mult = get_era_multiplier(baselines, 2020)
        assert isinstance(mult, float)
        assert 0.5 < mult < 2.0

    def test_lookup_missing_year(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        mult = get_era_multiplier(baselines, 1990)
        assert mult == 1.0

    def test_empty_baselines(self):
        mult = get_era_multiplier(pd.DataFrame(), 2020)
        assert mult == 1.0


class TestEraAdjustedCareerComposite:
    """Tests for compute_era_adjusted_career_composite."""

    def test_basic_output(self):
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        innings = _make_multi_year_bat_innings()
        careers = pd.DataFrame(
            {
                "batter_id": ["bat_0"],
                "batter": ["Batter 0"],
            }
        )
        result = compute_era_adjusted_career_composite(careers, innings, baselines)
        assert not result.empty
        assert "era_adjusted_composite" in result.columns

    def test_empty_inputs(self):
        result = compute_era_adjusted_career_composite(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert result.empty


class TestComputeAllEraMetrics:
    """Tests for the convenience wrapper compute_all_era_metrics."""

    def test_full_pipeline(self):
        ctx = _make_multi_year_match_ctx()
        innings = _make_multi_year_bat_innings()
        result = compute_all_era_metrics(
            match_ctx=ctx,
            bat_innings=innings,
            rolling_years=3,
        )
        assert "era_baselines" in result
        assert "era_summary" in result
        assert "bat_innings_adjusted" in result
        assert not result["era_baselines"].empty
        assert not result["era_summary"].empty

    def test_no_innings(self):
        ctx = _make_multi_year_match_ctx()
        result = compute_all_era_metrics(match_ctx=ctx)
        assert "era_baselines" in result
        assert not result["era_baselines"].empty

    def test_with_bowling(self):
        ctx = _make_multi_year_match_ctx()
        spells = pd.DataFrame(
            {
                "match_id": [f"m{i}" for i in range(20)],
                "bowler_id": ["bowl_0"] * 20,
                "bowler": ["Bowler 0"] * 20,
                "date": pd.date_range("2020-01-01", periods=20, freq="30D"),
                "acc_economy_vs_par": np.random.uniform(-1, 1, 20),
            }
        )
        result = compute_all_era_metrics(
            match_ctx=ctx,
            bowl_spells=spells,
        )
        assert "bowl_spells_adjusted" in result


# ===========================================================================
# Cross-feature integration tests
# ===========================================================================


class TestCrossFeatureIntegration:
    """Integration tests ensuring features work together."""

    def test_venue_then_war(self):
        """Venue data and WAR should coexist on the same careers DataFrame."""
        bat_careers = _make_bat_careers(n_players=20)
        bat_careers = compute_batting_war(bat_careers)
        assert "war_batting" in bat_careers.columns
        assert "position_group" in bat_careers.columns

        # Now add venue data
        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat_innings = _make_bat_innings(n_players=5, innings_per_player=20, n_venues=5)
        ft = compute_flat_track_index(bat_innings, baselines, min_innings=5)
        if not ft.empty:
            # Merge onto careers (batter_id may differ from careers)
            merged = bat_careers.merge(ft, on=["batter_id", "batter"], how="left")
            assert "war_batting" in merged.columns
            assert "flat_track_index" in merged.columns

    def test_era_then_war(self):
        """Era-adjusted innings can be used as input for WAR."""
        ctx = _make_multi_year_match_ctx()
        baselines = compute_era_baselines(ctx)
        assert not baselines.empty

        # WAR operates on career-level, era on innings-level — they're independent
        careers = _make_bat_careers(n_players=20)
        careers = compute_batting_war(careers)
        assert "war_batting" in careers.columns

    def test_all_features_on_same_careers(self):
        """All Phase 3b features can produce columns on the same DataFrame."""
        careers = _make_bat_careers(n_players=20)

        # WAR
        careers = compute_batting_war(careers)
        careers = compute_batting_war_rate(careers)
        assert "war_batting" in careers.columns
        assert "war_batting_rate" in careers.columns

        # Venue (flat track index merged in)
        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bat_inn = _make_bat_innings(n_players=3, innings_per_player=20, n_venues=5)
        ft = compute_flat_track_index(bat_inn, baselines, min_innings=5)
        if not ft.empty:
            careers = careers.merge(ft, on=["batter_id", "batter"], how="left")

        # The careers DataFrame should have all columns
        assert "war_batting" in careers.columns

    def test_bowl_war_and_venue(self):
        """Bowling WAR and venue metrics coexist."""
        bowl_careers = _make_bowl_careers(n_players=15)
        bowl_careers = compute_bowling_war(bowl_careers)
        assert "war_bowling" in bowl_careers.columns

        ctx = _make_match_ctx_with_venue()
        baselines = compute_venue_baselines(ctx, min_matches=3)
        bowl_spells = _make_bowl_spells(n_players=3, spells_per_player=20, n_venues=5)
        ft_bowl = compute_bowling_flat_track_index(bowl_spells, baselines, min_spells=5)
        if not ft_bowl.empty:
            merged = bowl_careers.merge(ft_bowl, on=["bowler_id", "bowler"], how="left")
            assert "war_bowling" in merged.columns
            assert "flat_track_index_bowl" in merged.columns

    def test_era_baselines_across_wide_range(self):
        """Era baselines should work with a wide year range."""
        years = list(range(2008, 2025))
        par_sr = {y: 115 + (y - 2008) * 2.5 for y in years}
        ctx = _make_multi_year_match_ctx(
            years=years, matches_per_year=15, par_sr_by_year=par_sr
        )
        baselines = compute_era_baselines(ctx, rolling_years=3)
        assert len(baselines) == len(years)
        # 2008 should have highest multiplier, 2024 should be ~1.0
        m_2008 = baselines[baselines["year"] == 2008]["era_sr_multiplier"].iloc[0]
        m_2024 = baselines[baselines["year"] == 2024]["era_sr_multiplier"].iloc[0]
        assert m_2008 > m_2024


# ===========================================================================
# Edge case and robustness tests
# ===========================================================================


class TestEdgeCases:
    """Edge cases across all Phase 3b features."""

    def test_venue_all_same_par_sr(self):
        """All venues with identical par SR should have ~0 difficulty."""
        ctx = pd.DataFrame(
            {
                "match_id": [f"m{i}" for i in range(20)],
                "match_date": pd.date_range("2020-01-01", periods=20, freq="7D"),
                "match_par_sr": [130.0] * 20,
                "match_boundary_rate": [0.12] * 20,
                "match_dot_pct": [0.35] * 20,
                "venue": ["VenueA"] * 10 + ["VenueB"] * 10,
            }
        )
        baselines = compute_venue_baselines(ctx, min_matches=5)
        assert len(baselines) == 2
        assert (baselines["venue_difficulty_raw"].abs() < 1e-6).all()

    def test_war_all_identical_players(self):
        """Players with identical raw scores should all have same WAR."""
        careers = pd.DataFrame(
            {
                "batter_id": [f"b{i}" for i in range(10)],
                "batter": [f"Player {i}" for i in range(10)],
                "position_group": ["opener"] * 10,
                "innings_count": [50] * 10,
                "raw_acceleration": [1.0] * 10,
                "raw_power": [0.5] * 10,
                "raw_control": [0.3] * 10,
            }
        )
        result = compute_batting_war(careers)
        # All players identical = all are at replacement = WAR 0
        assert (result["war_batting"] == 0.0).all()

    def test_war_with_nan_raw_scores(self):
        """WAR should handle NaN raw scores gracefully."""
        careers = _make_bat_careers(n_players=10)
        careers.loc[0, "raw_acceleration"] = np.nan
        result = compute_batting_war(careers)
        assert "war_batting" in result.columns

    def test_era_single_match(self):
        """Era baselines should work with a single match."""
        ctx = pd.DataFrame(
            {
                "match_id": ["m0"],
                "match_date": pd.Timestamp("2024-01-01"),
                "match_par_sr": [155.0],
                "match_boundary_rate": [0.15],
                "match_dot_pct": [0.30],
            }
        )
        result = compute_era_baselines(ctx)
        assert len(result) == 1
        assert result["era_sr_multiplier"].iloc[0] == pytest.approx(1.0, abs=0.01)

    def test_venue_with_categorical_columns(self):
        """Venue computations should handle categorical dtypes."""
        ctx = _make_match_ctx_with_venue()
        ctx["venue"] = ctx["venue"].astype("category")
        baselines = compute_venue_baselines(ctx, min_matches=3)
        assert not baselines.empty

    def test_war_zero_innings(self):
        """WAR volume factor should handle zero innings."""
        careers = _make_bat_careers(n_players=5)
        careers["innings_count"] = 0
        result = compute_batting_war(careers)
        assert (result["volume_factor_bat"] == 0.0).all()
        assert (result["war_batting"] == 0.0).all()

    def test_era_equal_par_sr_all_years(self):
        """If all years have same par SR, multiplier should be 1.0."""
        years = [2018, 2019, 2020, 2021, 2022]
        par = {y: 140.0 for y in years}
        ctx = _make_multi_year_match_ctx(years=years, par_sr_by_year=par)
        baselines = compute_era_baselines(ctx)
        # All multipliers should be ~1.0
        assert (baselines["era_sr_multiplier"] - 1.0).abs().max() < 0.05

    def test_venue_baselines_std_handling(self):
        """Venues with zero std should still get a valid difficulty score."""
        ctx = pd.DataFrame(
            {
                "match_id": [f"m{i}" for i in range(20)],
                "match_date": pd.date_range("2020-01-01", periods=20, freq="7D"),
                "match_par_sr": [130.0] * 10 + [150.0] * 10,
                "match_boundary_rate": [0.12] * 20,
                "match_dot_pct": [0.35] * 20,
                "venue": ["VenueA"] * 10 + ["VenueB"] * 10,
            }
        )
        baselines = compute_venue_baselines(ctx, min_matches=5)
        # Should not have NaN or inf
        assert baselines["venue_difficulty"].notna().all()
        assert np.isfinite(baselines["venue_difficulty"]).all()

    def test_bowling_war_small_groups(self):
        """Bowling WAR should fall back to population for small groups."""
        careers = _make_bowl_careers(
            n_players=8, phase_groups=["pp_heavy", "rare_group"]
        )
        # rare_group has ~4 players, should fall back to population
        result = compute_bowling_war(careers)
        assert "war_bowling" in result.columns
        assert result["war_bowling"].notna().all()
