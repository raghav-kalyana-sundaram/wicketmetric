"""
Unit tests for the rating module: Bayesian shrinkage, confidence bonus,
percentile mapping, and the full apply_rating_system pipeline.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rating import (
    apply_rating_system,
    bayesian_shrinkage,
    confidence_bonus,
    lookup_player,
    to_percentile_score,
)

# ---------------------------------------------------------------------------
# bayesian_shrinkage
# ---------------------------------------------------------------------------


class TestBayesianShrinkage:
    """Tests for bayesian_shrinkage()."""

    def test_single_innings_dominated_by_population(self):
        """With n=1 and k=12, player score should be ~92% population mean."""
        scores = pd.Series([100.0, 50.0, 50.0, 50.0, 50.0])
        sizes = pd.Series([1, 50, 50, 50, 50])
        pop_mean = scores.mean()  # 60.0

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=12.0)

        # Player 0: (1*100 + 12*60) / (1+12) = 820/13 ≈ 63.08
        expected_0 = (1 * 100 + 12 * pop_mean) / (1 + 12)
        assert abs(result.iloc[0] - expected_0) < 0.01

    def test_large_sample_converges_to_own_score(self):
        """With n=1000 and k=12, player score should dominate."""
        scores = pd.Series([80.0, 50.0])
        sizes = pd.Series([1000, 1000])
        pop_mean = scores.mean()  # 65.0

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=12.0)

        # Player 0: (1000*80 + 12*65) / (1000+12) ≈ 79.82
        expected_0 = (1000 * 80 + 12 * pop_mean) / (1000 + 12)
        assert abs(result.iloc[0] - expected_0) < 0.01
        # Should be very close to 80
        assert abs(result.iloc[0] - 80.0) < 0.5

    def test_equal_sample_and_k_gives_midpoint(self):
        """With n=k, result should be midpoint of player score and pop mean."""
        scores = pd.Series([100.0, 0.0])
        sizes = pd.Series([12, 12])
        k = 12.0
        pop_mean = scores.mean()  # 50.0

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=k)

        # Player 0: (12*100 + 12*50) / (12+12) = 1800/24 = 75.0
        expected_0 = (12 * 100 + 12 * pop_mean) / (12 + 12)
        assert abs(result.iloc[0] - expected_0) < 0.01

    def test_zero_shrinkage_returns_original(self):
        """With k=0, shrinkage should return the original scores."""
        scores = pd.Series([10.0, 20.0, 30.0])
        sizes = pd.Series([5, 10, 15])

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=0.0)

        pd.testing.assert_series_equal(result, scores, check_names=False)

    def test_all_same_scores_unchanged(self):
        """If all scores are identical, shrinkage should return them unchanged."""
        scores = pd.Series([50.0, 50.0, 50.0])
        sizes = pd.Series([1, 10, 100])

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=12.0)

        for val in result:
            assert abs(val - 50.0) < 0.01

    def test_handles_all_nan(self):
        """All-NaN input should not crash."""
        scores = pd.Series([np.nan, np.nan])
        sizes = pd.Series([10, 20])

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=12.0)

        assert result.isna().all()

    def test_handles_empty_series(self):
        """Empty input should return empty."""
        scores = pd.Series([], dtype=float)
        sizes = pd.Series([], dtype=float)

        result = bayesian_shrinkage(scores, sizes, shrinkage_k=12.0)

        assert len(result) == 0

    def test_higher_k_pulls_more_toward_mean(self):
        """Higher shrinkage_k should pull the outlier closer to pop mean."""
        scores = pd.Series([100.0, 50.0, 50.0])
        sizes = pd.Series([5, 5, 5])

        result_low_k = bayesian_shrinkage(scores, sizes, shrinkage_k=5.0)
        result_high_k = bayesian_shrinkage(scores, sizes, shrinkage_k=50.0)

        pop_mean = scores.mean()
        # With higher k, player 0's score should be closer to pop_mean
        assert abs(result_high_k.iloc[0] - pop_mean) < abs(
            result_low_k.iloc[0] - pop_mean
        )


# ---------------------------------------------------------------------------
# confidence_bonus
# ---------------------------------------------------------------------------


class TestConfidenceBonus:
    """Tests for confidence_bonus()."""

    def test_zero_matches_gives_zero_bonus(self):
        """n=0 should give 0 bonus."""
        sizes = pd.Series([0])
        result = confidence_bonus(sizes, alpha=0.03, reference_n=100.0)
        assert abs(result.iloc[0]) < 1e-10

    def test_reference_n_gives_full_bonus(self):
        """n=reference_n should give exactly alpha."""
        sizes = pd.Series([100.0])
        result = confidence_bonus(sizes, alpha=0.03, reference_n=100.0)
        assert abs(result.iloc[0] - 0.03) < 1e-6

    def test_beyond_reference_n_capped(self):
        """n > reference_n should still be capped at alpha."""
        sizes = pd.Series([500.0, 1000.0])
        result = confidence_bonus(sizes, alpha=0.03, reference_n=100.0)
        assert result.iloc[0] == pytest.approx(0.03, abs=1e-6)
        assert result.iloc[1] == pytest.approx(0.03, abs=1e-6)

    def test_monotonically_increasing(self):
        """Bonus should increase with sample size (up to the cap)."""
        sizes = pd.Series([1, 5, 10, 25, 50, 100])
        result = confidence_bonus(sizes, alpha=0.03, reference_n=100.0)

        for i in range(len(result) - 1):
            assert result.iloc[i] <= result.iloc[i + 1] + 1e-10

    def test_bonus_between_zero_and_alpha(self):
        """All values should be in [0, alpha]."""
        sizes = pd.Series([0, 1, 10, 50, 100, 200])
        alpha = 0.05
        result = confidence_bonus(sizes, alpha=alpha, reference_n=100.0)

        assert (result >= -1e-10).all()
        assert (result <= alpha + 1e-10).all()

    def test_small_n_gives_small_bonus(self):
        """n=1 should give a small but positive bonus."""
        sizes = pd.Series([1])
        result = confidence_bonus(sizes, alpha=0.03, reference_n=100.0)
        assert result.iloc[0] > 0
        assert result.iloc[0] < 0.01  # much less than full bonus


# ---------------------------------------------------------------------------
# to_percentile_score
# ---------------------------------------------------------------------------


class TestToPercentileScore:
    """Tests for to_percentile_score()."""

    def test_known_ranks(self):
        """Simple 4-element test with known percentile ranks."""
        values = pd.Series([10.0, 20.0, 30.0, 40.0])
        result = to_percentile_score(values)

        # Ranks: 1,2,3,4 out of 4 → pct: 0.25, 0.50, 0.75, 1.00
        assert result.iloc[0] == pytest.approx(25.0, abs=0.1)
        assert result.iloc[1] == pytest.approx(50.0, abs=0.1)
        assert result.iloc[2] == pytest.approx(75.0, abs=0.1)
        assert result.iloc[3] == pytest.approx(100.0, abs=0.1)

    def test_range_0_to_100(self):
        """All values should be in [0, 100]."""
        np.random.seed(0)
        values = pd.Series(np.random.randn(100))
        result = to_percentile_score(values)

        assert (result >= 0).all()
        assert (result <= 100).all()

    def test_ties_get_average_rank(self):
        """Tied values should get the average percentile rank."""
        values = pd.Series([10.0, 10.0, 10.0, 40.0])
        result = to_percentile_score(values)

        # First three are tied at rank (1+2+3)/3 = 2 → pct = 2/4 = 0.50
        assert result.iloc[0] == result.iloc[1] == result.iloc[2]
        assert result.iloc[0] == pytest.approx(50.0, abs=0.1)

    def test_all_same_values(self):
        """If all values are the same, all should get the same percentile."""
        values = pd.Series([5.0, 5.0, 5.0])
        result = to_percentile_score(values)

        assert result.iloc[0] == result.iloc[1] == result.iloc[2]

    def test_single_value(self):
        """Single element should get 100th percentile."""
        values = pd.Series([42.0])
        result = to_percentile_score(values)
        assert result.iloc[0] == pytest.approx(100.0, abs=0.1)

    def test_handles_nan(self):
        """NaN values should remain NaN (ranked at bottom via na_option)."""
        values = pd.Series([10.0, np.nan, 30.0])
        result = to_percentile_score(values)

        assert not pd.isna(result.iloc[0])
        assert not pd.isna(result.iloc[2])

    def test_empty_series(self):
        """Empty series should return empty."""
        values = pd.Series([], dtype=float)
        result = to_percentile_score(values)
        assert len(result) == 0

    def test_all_nan(self):
        """All-NaN should not crash."""
        values = pd.Series([np.nan, np.nan])
        result = to_percentile_score(values)
        assert len(result) == 2

    def test_preserves_ordering(self):
        """Higher raw value should always get higher or equal percentile."""
        values = pd.Series([5, 3, 8, 1, 10, 2, 7, 4, 6, 9], dtype=float)
        result = to_percentile_score(values)

        sorted_pairs = sorted(zip(values, result), key=lambda x: x[0])
        for i in range(len(sorted_pairs) - 1):
            assert sorted_pairs[i][1] <= sorted_pairs[i + 1][1]


# ---------------------------------------------------------------------------
# apply_rating_system (integration)
# ---------------------------------------------------------------------------


class TestApplyRatingSystem:
    """Integration tests for the full three-step rating pipeline."""

    @pytest.fixture
    def sample_career_df(self):
        """Small career DataFrame for testing."""
        return pd.DataFrame(
            {
                "player_id": ["p1", "p2", "p3", "p4", "p5"],
                "player_name": [
                    "Alice",
                    "Bob",
                    "Carol",
                    "Dave",
                    "Eve",
                ],
                "raw_metric_a": [80.0, 60.0, 40.0, 20.0, 50.0],
                "raw_metric_b": [30.0, 70.0, 50.0, 90.0, 10.0],
                "sample_size": [100, 50, 10, 2, 75],
                "is_provisional": [False, False, False, True, False],
            }
        )

    def test_adds_score_columns(self, sample_career_df):
        """Should add score_ and adjusted_ columns for each raw metric."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a", "raw_metric_b"],
            sample_col="sample_size",
            provisional_col="is_provisional",
        )

        assert "score_metric_a" in result.columns
        assert "score_metric_b" in result.columns
        assert "adjusted_metric_a" in result.columns
        assert "adjusted_metric_b" in result.columns

    def test_scores_in_0_100_range(self, sample_career_df):
        """All score_ columns should be in [0, 100]."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a", "raw_metric_b"],
            sample_col="sample_size",
            provisional_col="is_provisional",
        )

        for col in ["score_metric_a", "score_metric_b"]:
            assert (result[col] >= 0).all()
            assert (result[col] <= 100).all()

    def test_highest_raw_gets_highest_score(self, sample_career_df):
        """Player with highest raw score and large sample should rank highest."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a"],
            sample_col="sample_size",
            provisional_col="is_provisional",
        )

        # Alice has highest raw_metric_a=80 and large sample=100
        alice = result[result["player_name"] == "Alice"]
        assert alice["score_metric_a"].iloc[0] == result["score_metric_a"].max()

    def test_provisional_player_shrunk_toward_mean(self, sample_career_df):
        """Player with n=2 should be heavily shrunk toward population mean."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a"],
            sample_col="sample_size",
            provisional_col="is_provisional",
            shrinkage_k=12.0,
        )

        # Dave has raw=20 and n=2; after shrinkage his adjusted should be
        # pulled toward the mean (50), so adjusted > 20
        dave = result[result["player_name"] == "Dave"]
        assert dave["adjusted_metric_a"].iloc[0] > 20.0

    def test_preserves_original_columns(self, sample_career_df):
        """Original columns should be preserved in the output."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a"],
            sample_col="sample_size",
            provisional_col="is_provisional",
        )

        assert "player_id" in result.columns
        assert "player_name" in result.columns
        assert "raw_metric_a" in result.columns

    def test_missing_raw_col_skipped_gracefully(self, sample_career_df):
        """A raw_col that doesn't exist should be skipped with a warning."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a", "raw_nonexistent"],
            sample_col="sample_size",
            provisional_col="is_provisional",
        )

        assert "score_metric_a" in result.columns
        assert "score_nonexistent" not in result.columns

    def test_zero_shrinkage_no_change(self, sample_career_df):
        """With shrinkage_k=0, adjusted should equal raw (plus small bonus)."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a"],
            sample_col="sample_size",
            provisional_col="is_provisional",
            shrinkage_k=0.0,
            confidence_alpha=0.0,
            uncertainty_penalty_scale=0.0,
        )

        pd.testing.assert_series_equal(
            result["adjusted_metric_a"],
            sample_career_df["raw_metric_a"],
            check_names=False,
        )

    def test_larger_sample_gets_higher_confidence_bonus(self, sample_career_df):
        """Players with more matches should get a larger confidence bonus."""
        result = apply_rating_system(
            sample_career_df,
            raw_cols=["raw_metric_a"],
            sample_col="sample_size",
            provisional_col="is_provisional",
            shrinkage_k=0.0,  # disable shrinkage to isolate bonus
            confidence_alpha=0.05,
        )

        # Alice (n=100) should have higher adjusted than raw by more than
        # Dave (n=2), proportionally.
        alice_boost = (
            result.loc[result["player_name"] == "Alice", "adjusted_metric_a"].iloc[0]
            / sample_career_df.loc[
                sample_career_df["player_name"] == "Alice", "raw_metric_a"
            ].iloc[0]
        )
        dave_boost = (
            result.loc[result["player_name"] == "Dave", "adjusted_metric_a"].iloc[0]
            / sample_career_df.loc[
                sample_career_df["player_name"] == "Dave", "raw_metric_a"
            ].iloc[0]
        )
        assert alice_boost > dave_boost


# ---------------------------------------------------------------------------
# lookup_player
# ---------------------------------------------------------------------------


class TestLookupPlayer:
    """Tests for the lookup_player helper."""

    @pytest.fixture
    def career_df(self):
        return pd.DataFrame(
            {
                "batter_id": ["id1", "id2", "id3"],
                "batter": ["Virat Kohli", "Jos Buttler", "Babar Azam"],
                "score": [90.0, 85.0, 80.0],
            }
        )

    def test_lookup_by_exact_id(self, career_df):
        result = lookup_player(career_df, player_id="id2")
        assert len(result) == 1
        assert result.iloc[0]["batter"] == "Jos Buttler"

    def test_lookup_by_name_substring(self, career_df):
        result = lookup_player(career_df, player_name="Kohli")
        assert len(result) == 1
        assert result.iloc[0]["batter_id"] == "id1"

    def test_lookup_case_insensitive(self, career_df):
        result = lookup_player(career_df, player_name="babar")
        assert len(result) == 1

    def test_lookup_no_match(self, career_df):
        result = lookup_player(career_df, player_name="Sachin")
        assert len(result) == 0

    def test_lookup_no_criteria(self, career_df):
        result = lookup_player(career_df)
        assert len(result) == 0

    def test_lookup_with_category_dtype(self, career_df):
        """Should work even if columns are categorical."""
        career_df["batter_id"] = career_df["batter_id"].astype("category")
        career_df["batter"] = career_df["batter"].astype("category")

        result = lookup_player(career_df, player_name="Buttler")
        assert len(result) == 1

    def test_lookup_multiple_matches(self, career_df):
        """Should return all matching rows."""
        # Add another player with 'Ba' in name
        extra = pd.DataFrame(
            {
                "batter_id": ["id4"],
                "batter": ["Bairstow"],
                "score": [75.0],
            }
        )
        df = pd.concat([career_df, extra], ignore_index=True)
        result = lookup_player(df, player_name="Ba")
        assert len(result) == 2  # Babar Azam and Bairstow
