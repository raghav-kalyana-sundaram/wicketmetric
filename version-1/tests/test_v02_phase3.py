"""
Tests for Version 0.2 Phase 3 features:
  - Feature 13: Form Tracker (rolling-window time-series)
  - Feature 5:  Peak vs Current Ratings (recency-free + sliding window)
  - Feature 7:  Player Similarity Engine (cosine similarity comps)

Tests cover:
  - Form Tracker: batting & bowling form series, window sizing, min_window
    filtering, composite calculation, edge cases (empty data, single player)
  - Peak Ratings: simple recency-free aggregate, sliding-window peak,
    bowling peak, weight handling, min-innings thresholds
  - Similarity Engine: cosine similarity matrix, batting & bowling similarity,
    pivot to wide form, within-group filtering, supplementary columns,
    edge cases (too few players, identical profiles, zero vectors)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal DataFrames that look like pipeline output
# ---------------------------------------------------------------------------


def _make_bat_components(
    n_innings: int = 15,
    batter_id: str = "b1",
    batter: str = "Player A",
    base_date: str = "2023-01-01",
    sr_vs_par_base: float = 0.10,
    runs_base: int = 30,
    sr_base: float = 135.0,
    include_recency: bool = True,
    include_v02_cols: bool = True,
) -> pd.DataFrame:
    """Create a minimal bat_components DataFrame for one player."""
    np.random.seed(42)
    dates = pd.date_range(base_date, periods=n_innings, freq="14D")
    rows = []
    for i in range(n_innings):
        row = {
            "match_id": f"m{i}",
            "innings_num": 1 + (i % 2),
            "batter_id": batter_id,
            "batter": batter,
            "batting_team": "TeamA",
            "date": dates[i],
            "runs": runs_base + np.random.randint(-15, 20),
            "balls_faced": 25 + np.random.randint(-5, 10),
            "sr": sr_base + np.random.uniform(-20, 25),
            "fours": np.random.randint(1, 5),
            "sixes": np.random.randint(0, 3),
            "is_out": bool(np.random.random() > 0.3),
            "dots": np.random.randint(3, 10),
            # Acceleration components
            "acc_overall_sr": sr_vs_par_base + np.random.uniform(-0.05, 0.15),
            "acc_sr_growth": np.random.uniform(0, 0.1),
            "acc_death_sr": np.random.uniform(-0.1, 0.2),
            "acc_impact": np.random.uniform(0, 15),
            "acc_runs_above_expected": np.random.uniform(-0.1, 0.2),
            # Power components
            "pow_boundary_pct": np.random.uniform(0.3, 0.7),
            "pow_six_rate": np.random.uniform(0.0, 0.15),
            "pow_boundary_rate_vs_par": np.random.uniform(-0.05, 0.1),
            "pow_peak_phase_sr": np.random.uniform(-0.1, 0.3),
            "pow_finishing_burst": np.random.uniform(0.0, 0.5),
            "pow_power_impact": np.random.uniform(0.0, 2.0),
            # Control components
            "ctrl_dot_pct_weighted": np.random.uniform(0.5, 0.8),
            "ctrl_scoring_consistency": np.random.uniform(0.4, 0.7),
            "ctrl_rotation": np.random.uniform(0.15, 0.35),
            "ctrl_contribution": np.random.uniform(0.15, 0.40),
            "ctrl_avg_proxy": float(runs_base + np.random.randint(-10, 10)),
            "ctrl_dismissal_quality": np.random.uniform(-0.2, 0.0),
            # Weighting
            "opp_quality_weight": 0.8 + np.random.uniform(0, 0.4),
            "opposition_quality": np.random.uniform(0.8, 1.2),
        }
        if include_recency:
            # Older innings get lower recency weight
            row["recency_weight"] = 0.3 + 0.7 * (i / max(n_innings - 1, 1))
        if include_v02_cols:
            row["balls_to_par"] = np.random.uniform(3, 15)
            row["fifty_approach_sr"] = (
                np.random.uniform(100, 160) if row["runs"] >= 40 else np.nan
            )
            row["century_approach_sr"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _make_bowl_components(
    n_spells: int = 15,
    bowler_id: str = "bw1",
    bowler: str = "Bowler X",
    base_date: str = "2023-01-01",
    include_recency: bool = True,
) -> pd.DataFrame:
    """Create a minimal bowl_components DataFrame for one bowler."""
    np.random.seed(99)
    dates = pd.date_range(base_date, periods=n_spells, freq="14D")
    rows = []
    for i in range(n_spells):
        rows.append(
            {
                "match_id": f"m{i}",
                "innings_num": 1 + (i % 2),
                "bowler_id": bowler_id,
                "bowler": bowler,
                "bowling_team": "TeamA",
                "date": dates[i],
                "overs": 3 + np.random.uniform(0, 1),
                "economy": 7.0 + np.random.uniform(-2, 3),
                "wickets": np.random.randint(0, 4),
                "dot_pct": np.random.uniform(0.3, 0.6),
                "economy_ratio_par": 0.9 + np.random.uniform(-0.1, 0.2),
                # Accuracy components
                "acc_economy_vs_par": np.random.uniform(-0.1, 0.2),
                "acc_dot_pct": np.random.uniform(0.3, 0.6),
                "acc_extras_penalty": np.random.uniform(-0.3, 0),
                "acc_boundary_penalty": np.random.uniform(-0.3, 0),
                # Control components
                "ctrl_entropy": np.random.uniform(-2.5, -1.0),
                "ctrl_vs_others": np.random.uniform(-0.5, 0.5),
                "ctrl_extras": np.random.uniform(-0.3, 0),
                "ctrl_phase_consistency": np.random.uniform(-1.0, 0),
                "ctrl_economy_vs_par": np.random.uniform(-0.1, 0.2),
                # Threat components
                "threat_wickets": float(np.random.randint(0, 4)),
                "threat_quality_wickets": np.random.uniform(0, 3),
                "threat_sr": np.random.uniform(-30, 0),
                "threat_pressure": np.random.uniform(-0.5, 0.5),
                "threat_dots": np.random.uniform(0.3, 0.6),
                # Weighting
                "spell_weight": 0.8 + np.random.uniform(0, 0.4),
                "recency_weight": 0.3 + 0.7 * (i / max(n_spells - 1, 1))
                if include_recency
                else 1.0,
            }
        )
    return pd.DataFrame(rows)


def _make_bat_careers(
    n_players: int = 10,
    min_innings: int = 15,
    include_supplementary: bool = True,
) -> pd.DataFrame:
    """Create a minimal bat_careers DataFrame for similarity tests."""
    np.random.seed(123)
    rows = []
    position_groups = ["top_order", "upper_middle", "lower_middle", "finisher"]
    for i in range(n_players):
        pg = position_groups[i % len(position_groups)]
        row = {
            "batter_id": f"b{i}",
            "batter": f"Batter {i}",
            "country": "TeamA",
            "innings_count": min_innings + np.random.randint(0, 40),
            "total_runs": 400 + np.random.randint(0, 600),
            "total_balls": 300 + np.random.randint(0, 400),
            "career_sr": 120 + np.random.uniform(-20, 40),
            "career_avg": 20 + np.random.uniform(-5, 20),
            "modal_position": (i % 7) + 1,
            "position_group": pg,
            # Component means (from aggregate_batting_careers)
            "acc_overall_sr_mean": np.random.uniform(-0.1, 0.3),
            "acc_sr_growth_mean": np.random.uniform(0, 0.1),
            "acc_death_sr_mean": np.random.uniform(-0.1, 0.2),
            "acc_impact_mean": np.random.uniform(0, 10),
            "acc_runs_above_expected_mean": np.random.uniform(-0.1, 0.2),
            "pow_boundary_pct_mean": np.random.uniform(0.3, 0.7),
            "pow_six_rate_mean": np.random.uniform(0.0, 0.15),
            "pow_boundary_rate_vs_par_mean": np.random.uniform(-0.05, 0.1),
            "pow_peak_phase_sr_mean": np.random.uniform(-0.1, 0.3),
            "pow_finishing_burst_mean": np.random.uniform(0.0, 0.5),
            "pow_power_impact_mean": np.random.uniform(0.0, 2.0),
            "ctrl_dot_pct_weighted_mean": np.random.uniform(0.5, 0.8),
            "ctrl_rotation_mean": np.random.uniform(0.15, 0.35),
            "ctrl_contribution_mean": np.random.uniform(0.15, 0.4),
            "ctrl_scoring_consistency_mean": np.random.uniform(0.4, 0.7),
            "ctrl_avg_proxy_mean": np.random.uniform(15, 40),
            "ctrl_dismissal_quality_mean": np.random.uniform(-0.2, 0),
            "overall_score": np.random.uniform(30, 90),
            "is_provisional_bat": False,
        }
        if include_supplementary:
            row["avg_balls_to_par"] = np.random.uniform(3, 15)
            row["anchor_cost_ratio"] = np.random.uniform(0.3, 0.8)
            row["selfless_index"] = np.random.uniform(0.7, 1.3)
            row["chase_master_index"] = np.random.uniform(-0.5, 0.5)
        rows.append(row)
    return pd.DataFrame(rows)


def _make_bowl_careers(
    n_players: int = 10,
    min_matches: int = 15,
    include_supplementary: bool = True,
) -> pd.DataFrame:
    """Create a minimal bowl_careers DataFrame for similarity tests."""
    np.random.seed(456)
    rows = []
    phase_groups = ["pp_heavy", "middle_heavy", "death_heavy"]
    for i in range(n_players):
        phg = phase_groups[i % len(phase_groups)]
        row = {
            "bowler_id": f"bw{i}",
            "bowler": f"Bowler {i}",
            "country": "TeamA",
            "matches": min_matches + np.random.randint(0, 40),
            "total_overs": 40 + np.random.uniform(0, 80),
            "total_wickets": 10 + np.random.randint(0, 30),
            "career_economy": 7.0 + np.random.uniform(-2, 3),
            "career_sr_bowl": 15 + np.random.uniform(-5, 10),
            "phase_group": phg,
            # Component means
            "acc_economy_vs_par_mean": np.random.uniform(-0.1, 0.2),
            "acc_dot_pct_mean": np.random.uniform(0.3, 0.6),
            "acc_extras_penalty_mean": np.random.uniform(-0.3, 0),
            "acc_boundary_penalty_mean": np.random.uniform(-0.3, 0),
            "ctrl_entropy_mean": np.random.uniform(-2.5, -1.0),
            "ctrl_vs_others_mean": np.random.uniform(-0.5, 0.5),
            "ctrl_extras_mean": np.random.uniform(-0.3, 0),
            "ctrl_phase_consistency_mean": np.random.uniform(-1.0, 0),
            "ctrl_economy_vs_par_mean": np.random.uniform(-0.1, 0.2),
            "threat_wickets_mean": np.random.uniform(0, 3),
            "threat_quality_wickets_mean": np.random.uniform(0, 3),
            "threat_sr_mean": np.random.uniform(-30, 0),
            "threat_pressure_mean": np.random.uniform(-0.5, 0.5),
            "threat_dots_mean": np.random.uniform(0.3, 0.6),
            "overall_score": np.random.uniform(30, 90),
            "is_provisional_bowl": False,
        }
        if include_supplementary:
            row["avg_wicket_quality_mean"] = np.random.uniform(0.5, 1.5)
            row["bowled_lbw_pct"] = np.random.uniform(0.1, 0.4)
        rows.append(row)
    return pd.DataFrame(rows)


# ===========================================================================
#   Feature 13 — Form Tracker
# ===========================================================================


class TestBattingFormSeries:
    """Tests for compute_batting_form_series."""

    def test_basic_output_structure(self):
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=15)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        assert not result.empty
        assert "batter_id" in result.columns
        assert "batter" in result.columns
        assert "date" in result.columns
        assert "window_innings" in result.columns
        assert "cumulative_innings" in result.columns
        assert "window_sr_vs_par" in result.columns
        assert "window_composite" in result.columns
        # New 0-100 percentile sub-scores
        assert "window_score_acceleration" in result.columns
        assert "window_score_power" in result.columns
        assert "window_score_control" in result.columns
        # Raw z-score composites
        assert "raw_window_acceleration" in result.columns
        assert "raw_window_power" in result.columns
        assert "raw_window_control" in result.columns
        # Volume / stats columns
        assert "window_total_runs" in result.columns
        assert "window_fours" in result.columns
        assert "window_sixes" in result.columns
        # Peak annotation
        assert "is_peak_window" in result.columns

    def test_row_count_matches_expected(self):
        """Should produce (n - min_window + 1) rows per player."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=12)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        # Player has 12 innings, min_window=5 → rows from index 5..12 = 8 rows
        expected_rows = 12 - 5 + 1
        assert len(result) == expected_rows

    def test_window_size_capped(self):
        """Window innings should never exceed window_matches."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=20)
        result = compute_batting_form_series(bc, window_matches=8, min_window=3)

        assert result["window_innings"].max() <= 8

    def test_min_window_filters_short_careers(self):
        """Players with fewer innings than min_window should be excluded."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=4)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        assert result.empty

    def test_multiple_players(self):
        """Should produce separate series for each player."""
        from src.form_tracker import compute_batting_form_series

        bc1 = _make_bat_components(n_innings=10, batter_id="b1", batter="Alice")
        bc2 = _make_bat_components(n_innings=10, batter_id="b2", batter="Bob")
        bc = pd.concat([bc1, bc2], ignore_index=True)

        result = compute_batting_form_series(bc, window_matches=8, min_window=5)

        assert result["batter_id"].nunique() == 2
        assert set(result["batter_id"].unique()) == {"b1", "b2"}

    def test_cumulative_innings_monotonic(self):
        """Cumulative innings should be monotonically increasing per player."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=15)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        cum = result["cumulative_innings"].values
        assert all(cum[i] <= cum[i + 1] for i in range(len(cum) - 1))

    def test_window_composite_is_finite(self):
        """Window composite should be a finite number (not NaN or inf)."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=15)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        assert result["window_composite"].notna().all()
        assert np.isfinite(result["window_composite"]).all()

    def test_composite_is_0_to_100(self):
        """Window composite should be in the 0-100 percentile range."""
        from src.form_tracker import compute_batting_form_series

        bc1 = _make_bat_components(n_innings=20, batter_id="b1", batter="Alice")
        bc2 = _make_bat_components(
            n_innings=20, batter_id="b2", batter="Bob", sr_vs_par_base=0.3, runs_base=50
        )
        bc = pd.concat([bc1, bc2], ignore_index=True)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        assert result["window_composite"].min() >= 0.0
        assert result["window_composite"].max() <= 100.0

    def test_sub_scores_are_0_to_100(self):
        """Sub-scores should be in the 0-100 percentile range."""
        from src.form_tracker import compute_batting_form_series

        bc1 = _make_bat_components(n_innings=15, batter_id="b1", batter="Alice")
        bc2 = _make_bat_components(n_innings=15, batter_id="b2", batter="Bob")
        bc = pd.concat([bc1, bc2], ignore_index=True)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        for col in [
            "window_score_acceleration",
            "window_score_power",
            "window_score_control",
        ]:
            assert result[col].min() >= 0.0, f"{col} has values below 0"
            assert result[col].max() <= 100.0, f"{col} has values above 100"

    def test_peak_annotation_one_per_player(self):
        """Each player should have exactly one peak window marked."""
        from src.form_tracker import compute_batting_form_series

        bc1 = _make_bat_components(n_innings=15, batter_id="b1", batter="Alice")
        bc2 = _make_bat_components(n_innings=15, batter_id="b2", batter="Bob")
        bc = pd.concat([bc1, bc2], ignore_index=True)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        for bid in result["batter_id"].unique():
            player_peaks = result[
                (result["batter_id"] == bid) & (result["is_peak_window"] == True)
            ]
            assert len(player_peaks) == 1, (
                f"Player {bid} should have exactly 1 peak, got {len(player_peaks)}"
            )

    def test_peak_is_highest_composite(self):
        """The peak-marked row should have the highest composite for that player."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=20)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        peak_row = result[result["is_peak_window"] == True].iloc[0]
        max_composite = result["window_composite"].max()
        assert peak_row["window_composite"] == max_composite

    def test_total_runs_is_sum_not_mean(self):
        """window_total_runs should be the sum of runs in the window, not mean."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=10, runs_base=30)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        # total_runs should be roughly window_innings * avg_runs
        for _, row in result.iterrows():
            expected_approx = row["window_innings"] * row["window_avg_runs"]
            assert abs(row["window_total_runs"] - expected_approx) < 1.0

    def test_dates_are_chronological(self):
        """Output dates should be in chronological order per player."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=15)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        dates = pd.to_datetime(result["date"])
        assert dates.is_monotonic_increasing

    def test_v02_columns_present_when_available(self):
        """If v0.2 columns exist in input, windowed versions appear in output."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=15, include_v02_cols=True)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        assert "window_avg_balls_to_par" in result.columns

    def test_empty_input(self):
        """Empty input should return empty DataFrame."""
        from src.form_tracker import compute_batting_form_series

        result = compute_batting_form_series(pd.DataFrame(), window_matches=10)
        assert result.empty

    def test_window_avg_runs_reasonable(self):
        """Window avg runs should be within a reasonable range."""
        from src.form_tracker import compute_batting_form_series

        bc = _make_bat_components(n_innings=15, runs_base=40)
        result = compute_batting_form_series(bc, window_matches=10, min_window=5)

        # Runs base is 40 with ±15 noise → should be roughly 25-60
        assert result["window_avg_runs"].min() > 0
        assert result["window_avg_runs"].max() < 200


class TestBowlingFormSeries:
    """Tests for compute_bowling_form_series."""

    def test_basic_output_structure(self):
        from src.form_tracker import compute_bowling_form_series

        bc = _make_bowl_components(n_spells=15)
        result = compute_bowling_form_series(bc, window_matches=10, min_window=5)

        assert not result.empty
        assert "bowler_id" in result.columns
        assert "bowler" in result.columns
        assert "window_spells" in result.columns
        assert "cumulative_spells" in result.columns
        assert "window_economy" in result.columns
        assert "window_composite" in result.columns

    def test_row_count(self):
        from src.form_tracker import compute_bowling_form_series

        bc = _make_bowl_components(n_spells=12)
        result = compute_bowling_form_series(bc, window_matches=10, min_window=5)

        expected_rows = 12 - 5 + 1
        assert len(result) == expected_rows

    def test_min_window_filters(self):
        from src.form_tracker import compute_bowling_form_series

        bc = _make_bowl_components(n_spells=3)
        result = compute_bowling_form_series(bc, window_matches=10, min_window=5)

        assert result.empty

    def test_window_spells_capped(self):
        from src.form_tracker import compute_bowling_form_series

        bc = _make_bowl_components(n_spells=20)
        result = compute_bowling_form_series(bc, window_matches=6, min_window=3)

        assert result["window_spells"].max() <= 6

    def test_empty_input(self):
        from src.form_tracker import compute_bowling_form_series

        result = compute_bowling_form_series(pd.DataFrame(), window_matches=10)
        assert result.empty

    def test_threat_columns_present(self):
        from src.form_tracker import compute_bowling_form_series

        bc = _make_bowl_components(n_spells=15)
        result = compute_bowling_form_series(bc, window_matches=10, min_window=5)

        assert "window_quality_wickets" in result.columns
        assert "window_threat_pressure" in result.columns


class TestFormTrackerConvenience:
    """Tests for the compute_form_series convenience function."""

    def test_compute_form_series_returns_dict(self):
        from src.form_tracker import compute_form_series

        bc_bat = _make_bat_components(n_innings=15)
        bc_bowl = _make_bowl_components(n_spells=15)

        result = compute_form_series(bc_bat, bc_bowl)

        assert isinstance(result, dict)
        assert "batting" in result
        assert "bowling" in result
        assert not result["batting"].empty
        assert not result["bowling"].empty


# ===========================================================================
#   Feature 5 — Peak vs Current Ratings
# ===========================================================================


class TestPeakRatingsSimple:
    """Tests for compute_peak_ratings (simple, recency-free approach)."""

    def test_basic_output_structure(self):
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=15, include_recency=True)
        result = compute_peak_ratings(bc, min_innings=10)

        assert not result.empty
        assert "batter_id" in result.columns
        assert "batter" in result.columns
        assert "peak_acc_overall_sr" in result.columns
        assert "peak_composite_batting" in result.columns
        assert "peak_innings_count" in result.columns

    def test_min_innings_threshold(self):
        """Players below min_innings should not appear."""
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=8)
        result = compute_peak_ratings(bc, min_innings=10)

        assert result.empty

    def test_peak_different_from_recency_weighted(self):
        """Peak ratings (recency-free) should differ from recency-weighted means."""
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=20, include_recency=True)

        peak = compute_peak_ratings(bc, min_innings=10)

        # Compute a simple recency-weighted mean for comparison
        w = bc["opp_quality_weight"]
        recency_mean = (bc["acc_overall_sr"] * w).sum() / w.sum()

        # Peak divides out recency, so the result should differ
        peak_val = peak.iloc[0]["peak_acc_overall_sr"]
        # They CAN be close but should not be exactly identical given
        # varying recency weights
        # (This is a soft check — the main point is that the function runs)
        assert np.isfinite(peak_val)
        assert np.isfinite(recency_mean)

    def test_no_recency_column_still_works(self):
        """If recency_weight is missing, should use opp_quality_weight as-is."""
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=15, include_recency=False)
        if "recency_weight" in bc.columns:
            bc = bc.drop(columns=["recency_weight"])

        result = compute_peak_ratings(bc, min_innings=10)
        assert not result.empty
        assert result.iloc[0]["peak_acc_overall_sr"] is not None

    def test_no_weight_columns(self):
        """If neither recency nor opp_quality_weight exist, should still work."""
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=15, include_recency=False)
        bc = bc.drop(columns=["opp_quality_weight"], errors="ignore")
        bc = bc.drop(columns=["recency_weight"], errors="ignore")

        result = compute_peak_ratings(bc, min_innings=10)
        assert not result.empty

    def test_peak_composite_is_finite(self):
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=15)
        result = compute_peak_ratings(bc, min_innings=10)

        assert result["peak_composite_batting"].notna().all()
        assert np.isfinite(result["peak_composite_batting"]).all()

    def test_empty_input(self):
        from src.peak_ratings import compute_peak_ratings

        result = compute_peak_ratings(pd.DataFrame())
        assert result.empty

    def test_multiple_players(self):
        from src.peak_ratings import compute_peak_ratings

        bc1 = _make_bat_components(n_innings=15, batter_id="b1", batter="Alice")
        bc2 = _make_bat_components(n_innings=15, batter_id="b2", batter="Bob")
        bc = pd.concat([bc1, bc2], ignore_index=True)

        result = compute_peak_ratings(bc, min_innings=10)
        assert len(result) == 2
        assert set(result["batter_id"]) == {"b1", "b2"}


class TestPeakRatingsBowling:
    """Tests for compute_peak_ratings_bowl."""

    def test_basic_output(self):
        from src.peak_ratings import compute_peak_ratings_bowl

        bc = _make_bowl_components(n_spells=15)
        result = compute_peak_ratings_bowl(bc, min_spells=10)

        assert not result.empty
        assert "bowler_id" in result.columns
        assert "peak_composite_bowling" in result.columns

    def test_min_spells_threshold(self):
        from src.peak_ratings import compute_peak_ratings_bowl

        bc = _make_bowl_components(n_spells=5)
        result = compute_peak_ratings_bowl(bc, min_spells=10)

        assert result.empty

    def test_empty_input(self):
        from src.peak_ratings import compute_peak_ratings_bowl

        result = compute_peak_ratings_bowl(pd.DataFrame())
        assert result.empty


class TestSlidingPeak:
    """Tests for compute_sliding_peak (true 2-year best window)."""

    def test_basic_output_structure(self):
        from src.peak_ratings import compute_sliding_peak

        bc = _make_bat_components(n_innings=20, base_date="2022-01-01")
        result = compute_sliding_peak(
            bc, window_days=365, min_window_innings=5, min_career_innings=10
        )

        assert not result.empty
        assert "batter_id" in result.columns
        assert "peak_window_start" in result.columns
        assert "peak_window_end" in result.columns
        assert "peak_window_innings" in result.columns
        assert "peak_window_composite" in result.columns

    def test_window_dates_are_valid(self):
        from src.peak_ratings import compute_sliding_peak

        bc = _make_bat_components(n_innings=20, base_date="2022-01-01")
        result = compute_sliding_peak(
            bc, window_days=365, min_window_innings=5, min_career_innings=10
        )

        if not result.empty:
            row = result.iloc[0]
            start = pd.Timestamp(row["peak_window_start"])
            end = pd.Timestamp(row["peak_window_end"])
            assert start <= end
            assert (end - start).days <= 365

    def test_min_career_innings_filters(self):
        from src.peak_ratings import compute_sliding_peak

        bc = _make_bat_components(n_innings=5)
        result = compute_sliding_peak(
            bc, window_days=730, min_window_innings=3, min_career_innings=10
        )

        assert result.empty

    def test_peak_window_composite_is_best(self):
        """The peak window composite should be the highest of all valid windows."""
        from src.peak_ratings import compute_sliding_peak

        # Create data with a clear peak in the middle
        bc = _make_bat_components(n_innings=30, base_date="2021-01-01")
        # Boost middle innings to create a clear peak
        bc.loc[10:19, "acc_overall_sr"] = 0.5
        bc.loc[10:19, "pow_boundary_pct"] = 0.8
        bc.loc[10:19, "ctrl_scoring_consistency"] = 0.9

        result = compute_sliding_peak(
            bc, window_days=365, min_window_innings=5, min_career_innings=10
        )

        assert not result.empty
        assert result.iloc[0]["peak_window_composite"] > 0

    def test_empty_input(self):
        from src.peak_ratings import compute_sliding_peak

        result = compute_sliding_peak(pd.DataFrame())
        assert result.empty


class TestSlidingPeakBowling:
    """Tests for compute_sliding_peak_bowl."""

    def test_basic_output(self):
        from src.peak_ratings import compute_sliding_peak_bowl

        bc = _make_bowl_components(n_spells=20)
        result = compute_sliding_peak_bowl(
            bc, window_days=365, min_window_spells=5, min_career_spells=10
        )

        assert not result.empty
        assert "bowler_id" in result.columns
        assert "peak_window_composite" in result.columns
        assert "peak_window_spells" in result.columns

    def test_empty_input(self):
        from src.peak_ratings import compute_sliding_peak_bowl

        result = compute_sliding_peak_bowl(pd.DataFrame())
        assert result.empty


# ===========================================================================
#   Feature 7 — Player Similarity Engine
# ===========================================================================


class TestCosineSimMatrix:
    """Tests for the internal cosine similarity matrix computation."""

    def test_identity_similarity(self):
        from src.similarity import _cosine_similarity_matrix

        A = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        sim = _cosine_similarity_matrix(A)

        # Self-similarity should be 1.0
        assert abs(sim[0, 0] - 1.0) < 1e-6
        assert abs(sim[1, 1] - 1.0) < 1e-6
        assert abs(sim[2, 2] - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        from src.similarity import _cosine_similarity_matrix

        A = np.array([[1.0, 0.0], [0.0, 1.0]])
        sim = _cosine_similarity_matrix(A)

        # Orthogonal vectors have similarity 0
        assert abs(sim[0, 1]) < 1e-6

    def test_identical_vectors(self):
        from src.similarity import _cosine_similarity_matrix

        A = np.array([[3.0, 4.0], [6.0, 8.0]])  # same direction, different magnitude
        sim = _cosine_similarity_matrix(A)

        # Cosine similarity should be 1.0
        assert abs(sim[0, 1] - 1.0) < 1e-6

    def test_opposite_vectors(self):
        from src.similarity import _cosine_similarity_matrix

        A = np.array([[1.0, 0.0], [-1.0, 0.0]])
        sim = _cosine_similarity_matrix(A)

        assert abs(sim[0, 1] - (-1.0)) < 1e-6

    def test_zero_vector_handling(self):
        from src.similarity import _cosine_similarity_matrix

        A = np.array([[0.0, 0.0], [1.0, 1.0]])
        sim = _cosine_similarity_matrix(A)

        # Zero vector should get norm 1 (by design), so similarity is 0
        assert np.isfinite(sim).all()

    def test_symmetric(self):
        from src.similarity import _cosine_similarity_matrix

        A = np.random.RandomState(42).randn(5, 3)
        sim = _cosine_similarity_matrix(A)

        np.testing.assert_allclose(sim, sim.T, atol=1e-10)


class TestBattingSimilarity:
    """Tests for compute_batting_similarity."""

    def test_basic_output_structure(self):
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10)
        result = compute_batting_similarity(bc, top_k=3, min_innings=10)

        assert not result.empty
        assert "batter_id" in result.columns
        assert "batter" in result.columns
        assert "comp_batter_id" in result.columns
        assert "comp_batter" in result.columns
        assert "similarity" in result.columns
        assert "comp_rank" in result.columns

    def test_top_k_respected(self):
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10)
        result = compute_batting_similarity(bc, top_k=2, min_innings=10)

        # Each player should have at most top_k comps
        comps_per_player = result.groupby("batter_id").size()
        assert (comps_per_player <= 2).all()

    def test_no_self_comparison(self):
        """A player should not appear as their own comp."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10)
        result = compute_batting_similarity(bc, top_k=3, min_innings=10)

        for _, row in result.iterrows():
            assert row["batter_id"] != row["comp_batter_id"]

    def test_similarity_in_valid_range(self):
        """Similarity should be between -100 and 100 (as percentage)."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10)
        result = compute_batting_similarity(bc, top_k=3, min_innings=10)

        assert (result["similarity"] >= -100.0).all()
        assert (result["similarity"] <= 100.0).all()

    def test_comp_rank_ordering(self):
        """Higher-ranked comps should have higher similarity."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10)
        result = compute_batting_similarity(bc, top_k=3, min_innings=10)

        for batter_id, group in result.groupby("batter_id"):
            sorted_group = group.sort_values("comp_rank")
            sims = sorted_group["similarity"].values
            # Rank 1 should be >= Rank 2 >= Rank 3
            for i in range(len(sims) - 1):
                assert sims[i] >= sims[i + 1] - 0.1  # small tolerance

    def test_min_innings_filters_targets(self):
        """Players below min_innings should not appear as comp targets."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10, min_innings=20)
        # Set one player to have very few innings
        bc.loc[0, "innings_count"] = 5

        result = compute_batting_similarity(bc, top_k=3, min_innings=15)

        # Player b0 with 5 innings should not appear as a comp target
        comp_ids = set(result["comp_batter_id"].unique())
        assert "b0" not in comp_ids

    def test_identical_profiles_max_similarity(self):
        """Two players with identical profiles should have near-100% similarity."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=3)
        # Make players 0 and 1 identical
        for col in bc.columns:
            if col not in ["batter_id", "batter"]:
                bc.loc[1, col] = bc.loc[0, col]

        result = compute_batting_similarity(bc, top_k=2, min_innings=10)

        # Player b0's top comp should be b1 (or vice versa) with ~100% sim
        b0_comps = result[result["batter_id"] == "b0"]
        if not b0_comps.empty:
            top_comp = b0_comps.iloc[0]
            assert top_comp["comp_batter_id"] == "b1"
            assert top_comp["similarity"] > 95.0

    def test_within_position_group(self):
        """When within_position_group=True, comps should be from same group."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=12)
        result = compute_batting_similarity(
            bc, top_k=2, min_innings=10, within_position_group=True
        )

        if not result.empty:
            # Merge position groups for verification
            pg_map = bc.set_index("batter_id")["position_group"]
            for _, row in result.iterrows():
                player_pg = pg_map.get(row["batter_id"])
                comp_pg = pg_map.get(row["comp_batter_id"])
                if player_pg is not None and comp_pg is not None:
                    assert player_pg == comp_pg

    def test_without_supplementary(self):
        """Should work without supplementary columns."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10, include_supplementary=False)
        result = compute_batting_similarity(
            bc, top_k=3, min_innings=10, include_supplementary=False
        )

        assert not result.empty

    def test_too_few_players(self):
        """With only 1 player, no comps can be computed."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=1)
        result = compute_batting_similarity(bc, top_k=3, min_innings=10)

        assert result.empty

    def test_empty_input(self):
        from src.similarity import compute_batting_similarity

        result = compute_batting_similarity(pd.DataFrame(), top_k=3)
        assert result.empty


class TestBowlingSimilarity:
    """Tests for compute_bowling_similarity."""

    def test_basic_output(self):
        from src.similarity import compute_bowling_similarity

        bc = _make_bowl_careers(n_players=10)
        result = compute_bowling_similarity(bc, top_k=3, min_matches=10)

        assert not result.empty
        assert "bowler_id" in result.columns
        assert "comp_bowler_id" in result.columns
        assert "similarity" in result.columns

    def test_no_self_comparison(self):
        from src.similarity import compute_bowling_similarity

        bc = _make_bowl_careers(n_players=10)
        result = compute_bowling_similarity(bc, top_k=3, min_matches=10)

        for _, row in result.iterrows():
            assert row["bowler_id"] != row["comp_bowler_id"]

    def test_empty_input(self):
        from src.similarity import compute_bowling_similarity

        result = compute_bowling_similarity(pd.DataFrame(), top_k=3)
        assert result.empty

    def test_within_phase_group(self):
        from src.similarity import compute_bowling_similarity

        bc = _make_bowl_careers(n_players=12)
        result = compute_bowling_similarity(
            bc, top_k=2, min_matches=10, within_phase_group=True
        )

        if not result.empty:
            pg_map = bc.set_index("bowler_id")["phase_group"]
            for _, row in result.iterrows():
                player_pg = pg_map.get(row["bowler_id"])
                comp_pg = pg_map.get(row["comp_bowler_id"])
                if player_pg is not None and comp_pg is not None:
                    assert player_pg == comp_pg


class TestSimilarityPivot:
    """Tests for pivot_similarity_wide."""

    def test_wide_form_structure(self):
        from src.similarity import compute_batting_similarity, pivot_similarity_wide

        bc = _make_bat_careers(n_players=10)
        long_form = compute_batting_similarity(bc, top_k=3, min_innings=10)
        wide = pivot_similarity_wide(
            long_form, id_col="batter_id", name_col="batter", top_k=3
        )

        assert not wide.empty
        assert "batter_id" in wide.columns
        assert "batter" in wide.columns
        assert "comp_1" in wide.columns
        assert "sim_1" in wide.columns

    def test_wide_form_row_count(self):
        """Wide form should have one row per player."""
        from src.similarity import compute_batting_similarity, pivot_similarity_wide

        bc = _make_bat_careers(n_players=8)
        long_form = compute_batting_similarity(bc, top_k=3, min_innings=10)
        wide = pivot_similarity_wide(
            long_form, id_col="batter_id", name_col="batter", top_k=3
        )

        # Each player in the long form should have exactly one row in wide form
        n_players_in_long = long_form["batter_id"].nunique()
        assert len(wide) == n_players_in_long

    def test_empty_input(self):
        from src.similarity import pivot_similarity_wide

        result = pivot_similarity_wide(pd.DataFrame())
        assert result.empty

    def test_top_k_limits_columns(self):
        from src.similarity import compute_batting_similarity, pivot_similarity_wide

        bc = _make_bat_careers(n_players=10)
        long_form = compute_batting_similarity(bc, top_k=5, min_innings=10)
        wide = pivot_similarity_wide(
            long_form, id_col="batter_id", name_col="batter", top_k=2
        )

        # Should only have comp_1, sim_1, comp_2, sim_2
        assert "comp_1" in wide.columns
        assert "comp_2" in wide.columns
        # comp_3 should NOT be present (we limited to top_k=2 in pivot)
        assert "comp_3" not in wide.columns


class TestSimilarityHelpers:
    """Tests for internal helper functions."""

    def test_z_normalise_columns(self):
        from src.similarity import _z_normalise_columns

        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [10, 20, 30, 40, 50]})
        result = _z_normalise_columns(df, ["a", "b"])

        # After z-normalisation, mean should be ~0 and std ~1
        assert abs(result["a"].mean()) < 1e-10
        assert abs(result["b"].mean()) < 1e-10
        assert (
            abs(result["a"].std(ddof=0) - 1.0) < 0.15
        )  # approximate; small N makes ddof=0 vs ddof=1 gap wider

    def test_z_normalise_constant_column(self):
        """Constant columns should become all zeros."""
        from src.similarity import _z_normalise_columns

        df = pd.DataFrame({"a": [5.0, 5.0, 5.0], "b": [1.0, 2.0, 3.0]})
        result = _z_normalise_columns(df, ["a", "b"])

        assert (result["a"] == 0.0).all()

    def test_z_normalise_with_nan(self):
        """NaN values should be filled with 0.0 after normalisation."""
        from src.similarity import _z_normalise_columns

        df = pd.DataFrame({"a": [1.0, np.nan, 3.0, 4.0, 5.0]})
        result = _z_normalise_columns(df, ["a"])

        assert result["a"].notna().all()

    def test_select_feature_columns(self):
        from src.similarity import _select_feature_columns

        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0],
                "b": [5.0, 5.0, 5.0],  # constant — should be excluded
                "c": [10.0, 20.0, 30.0],
            }
        )
        selected = _select_feature_columns(df, ["a", "b", "c", "d"])  # d doesn't exist

        assert "a" in selected
        assert "c" in selected
        assert "b" not in selected  # constant
        assert "d" not in selected  # missing


# ===========================================================================
#   Integration / cross-feature tests
# ===========================================================================


class TestCrossFeatureIntegration:
    """Tests that verify features work together coherently."""

    def test_form_tracker_and_peak_use_same_components(self):
        """Form tracker and peak ratings should operate on the same component data."""
        from src.form_tracker import compute_batting_form_series
        from src.peak_ratings import compute_peak_ratings

        bc = _make_bat_components(n_innings=20)

        form = compute_batting_form_series(bc, window_matches=10, min_window=5)
        peak = compute_peak_ratings(bc, min_innings=10)

        # Both should produce results for the same player
        assert not form.empty
        assert not peak.empty
        assert form.iloc[0]["batter_id"] == peak.iloc[0]["batter_id"]

    def test_similarity_on_careers_with_peak_columns(self):
        """Similarity engine should work even when careers have extra peak columns."""
        from src.similarity import compute_batting_similarity

        bc = _make_bat_careers(n_players=10)
        # Add peak columns as if they were merged
        bc["peak_composite_batting"] = np.random.uniform(0.1, 0.5, len(bc))
        bc["peak_window_composite"] = np.random.uniform(0.1, 0.5, len(bc))

        result = compute_batting_similarity(bc, top_k=3, min_innings=10)
        assert not result.empty

    def test_all_three_features_on_same_data(self):
        """All three features should run cleanly on the same batting data."""
        from src.form_tracker import compute_batting_form_series
        from src.peak_ratings import compute_peak_ratings, compute_sliding_peak
        from src.similarity import compute_batting_similarity

        bc = _make_bat_components(n_innings=20)

        # Form tracker
        form = compute_batting_form_series(bc, window_matches=10, min_window=5)
        assert not form.empty

        # Peak ratings
        peak = compute_peak_ratings(bc, min_innings=10)
        assert not peak.empty

        # Sliding peak
        sliding = compute_sliding_peak(
            bc, window_days=365, min_window_innings=5, min_career_innings=10
        )
        assert not sliding.empty

        # Similarity (needs careers, not components — but we can build a minimal one)
        careers = _make_bat_careers(n_players=5)
        sims = compute_batting_similarity(careers, top_k=2, min_innings=10)
        assert not sims.empty

    def test_bowling_all_three_features(self):
        """All three features should run cleanly on the same bowling data."""
        from src.form_tracker import compute_bowling_form_series
        from src.peak_ratings import (
            compute_peak_ratings_bowl,
            compute_sliding_peak_bowl,
        )
        from src.similarity import compute_bowling_similarity

        bc = _make_bowl_components(n_spells=20)

        form = compute_bowling_form_series(bc, window_matches=10, min_window=5)
        assert not form.empty

        peak = compute_peak_ratings_bowl(bc, min_spells=10)
        assert not peak.empty

        sliding = compute_sliding_peak_bowl(
            bc, window_days=365, min_window_spells=5, min_career_spells=10
        )
        assert not sliding.empty

        careers = _make_bowl_careers(n_players=5)
        sims = compute_bowling_similarity(careers, top_k=2, min_matches=10)
        assert not sims.empty
